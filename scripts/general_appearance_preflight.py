#!/usr/bin/env python3
"""Read-only preflight for the general appearance cron worker.

The script is intentionally deterministic: it emits only authoritative state
that can change when the worker actually changes the queue, database, or report.
It never promotes, edits, rebuilds, or runs a full integrity check.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "tag_library.db"
REPORT = ROOT / "reports" / "hololive_appearance_queue.md"
RANKER = ROOT / "scripts" / "rank_general_queue.py"
SEARCH_INDEX = ROOT / "data" / "tag_search.sqlite"
CONTEXT_INDEX = ROOT / "data" / "character_context.sqlite"


def connect_read_only(path: Path) -> sqlite3.Connection:
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    last_error: Exception | None = None
    for attempt in range(5):
        try:
            connection = sqlite3.connect(uri, uri=True, timeout=2)
            connection.execute("PRAGMA busy_timeout=2000")
            connection.execute("PRAGMA query_only=ON")
            return connection
        except sqlite3.OperationalError as exc:
            last_error = exc
            if "locked" not in str(exc).lower() or attempt == 4:
                raise
            time.sleep(1)
    raise RuntimeError(f"could not open read-only database: {last_error}")


def scalar(connection: sqlite3.Connection, query: str) -> int:
    for attempt in range(5):
        try:
            return int(connection.execute(query).fetchone()[0])
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower() or attempt == 4:
                raise
            time.sleep(1)
    raise RuntimeError("unreachable")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def index_state(path: Path, metadata_table: str, expected_sha: str, expected_size: int) -> dict[str, object]:
    if not path.is_file():
        return {"path": str(path), "fresh": False, "reason": "missing"}
    try:
        connection = connect_read_only(path)
        try:
            metadata = dict(connection.execute(
                f"SELECT key, value FROM {metadata_table}"
            ).fetchall())
        finally:
            connection.close()
    except (sqlite3.DatabaseError, OSError) as exc:
        return {"path": str(path), "fresh": False, "reason": type(exc).__name__}
    actual_sha = metadata.get("source_sha256", "")
    actual_size = metadata.get("source_size", "")
    fresh = actual_sha == expected_sha and actual_size == str(expected_size)
    return {
        "path": str(path),
        "fresh": fresh,
        "source_sha256": actual_sha,
        "source_size": actual_size,
        "expected_sha256": expected_sha,
        "expected_size": str(expected_size),
    }


def report_metric(section: str, key: str) -> str | None:
    match = re.search(rf"(?m)^{re.escape(key)}=(.+)$", section)
    return match.group(1).strip() if match else None


def seed_basename(value: str) -> str:
    return value.replace("\\", "/").rsplit("/", 1)[-1]


def report_state(text: str) -> tuple[str, str]:
    matches = list(re.finditer(r"^## .+$", text, re.MULTILINE))
    if not matches:
        raise RuntimeError("appearance report has no section heading")
    latest = matches[-1].group(0)
    latest_section = text[matches[-1].start() :]
    return latest, latest_section


def next_queue() -> list[str]:
    result = subprocess.run(
        [sys.executable, str(RANKER), "--db", str(DB), "--limit", "5"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ranker failed: {result.stderr.strip()[-300:]}")
    rows = json.loads(result.stdout)
    return [str(row["name"]) for row in rows]


def main() -> int:
    if not DB.is_file():
        raise RuntimeError(f"missing canonical database: {DB}")
    if not REPORT.is_file():
        raise RuntimeError(f"missing appearance report: {REPORT}")

    report_text = REPORT.read_text(encoding="utf-8", errors="replace")
    latest_heading, latest_section = report_state(report_text)

    connection = connect_read_only(DB)
    try:
        published_profiles = scalar(
            connection,
            "SELECT count(*) FROM character_appearance_profiles WHERE status='published'",
        )
        published_features = scalar(
            connection,
            "SELECT count(*) FROM character_appearance_features WHERE status='published'",
        )
        all_evidence_links = scalar(
            connection,
            "SELECT count(*) FROM character_appearance_feature_sources",
        )
        evidence_links = scalar(
            connection,
            """SELECT count(*)
               FROM character_appearance_feature_sources x
               JOIN character_appearance_features f ON f.feature_id=x.feature_id
               WHERE f.status='published'""",
        )
        nonpublished_evidence_links = all_evidence_links - evidence_links
        retired_evidence_links = scalar(
            connection,
            """SELECT count(*)
               FROM character_appearance_feature_sources x
               JOIN character_appearance_features f ON f.feature_id=x.feature_id
               WHERE f.status='retired'""",
        )
        unjoined_evidence_links = scalar(
            connection,
            """SELECT count(*)
               FROM character_appearance_feature_sources x
               LEFT JOIN character_appearance_features f ON f.feature_id=x.feature_id
               WHERE f.feature_id IS NULL""",
        )
        unexpected_nonpublished_evidence_links = (
            nonpublished_evidence_links
            - retired_evidence_links
            - unjoined_evidence_links
        )
        evidence_gaps = scalar(
            connection,
            """SELECT count(*)
               FROM character_appearance_features f
               WHERE f.status IN ('reviewed','published')
                 AND NOT EXISTS (
                     SELECT 1 FROM character_appearance_feature_sources x
                     WHERE x.feature_id=f.feature_id
                 )""",
        )
        duplicate_assignments = scalar(
            connection,
            """SELECT count(*) FROM (
                 SELECT appearance_key, canonical_tag, count(*) AS n
                 FROM character_appearance_features
                 WHERE status <> 'retired'
                 GROUP BY appearance_key, canonical_tag
                 HAVING n > 1
            )""",
        )
        missing_facet_links = scalar(
            connection,
            """SELECT count(*) FROM character_appearance_features
               WHERE status <> 'retired' AND facet_id IS NULL""",
        )
        unclassified = scalar(
            connection,
            """SELECT count(*) FROM character_appearance_features
               WHERE status <> 'retired' AND facet='unclassified'""",
        )
        row = connection.execute(
            "SELECT value FROM appearance_schema_metadata WHERE key='last_promoted_seed'"
        ).fetchone()
        last_seed = str(row[0]) if row else ""
    finally:
        connection.close()

    last_seed_file = seed_basename(last_seed) if last_seed else "(none)"
    last_seed_stem = (
        last_seed_file[:-5] if last_seed_file.endswith(".json") else last_seed_file
    )
    current_seed_in_latest_report = bool(last_seed_stem and last_seed_stem in latest_section)
    close_required = bool(last_seed and not current_seed_in_latest_report)
    canonical_size = DB.stat().st_size
    canonical_sha256 = sha256_file(DB)
    index_states = [
        index_state(SEARCH_INDEX, "tag_search_metadata", canonical_sha256, canonical_size),
        index_state(CONTEXT_INDEX, "context_index_metadata", canonical_sha256, canonical_size),
    ]
    indexes_fresh = all(bool(state.get("fresh")) for state in index_states)
    expected_report = {
        "batch_close": "complete",
        "canonical_db_size": str(canonical_size),
        "canonical_db_sha256": canonical_sha256,
        "canonical_published_profiles": str(published_profiles),
        "canonical_published_features": str(published_features),
        "canonical_all_evidence_links": str(all_evidence_links),
        "canonical_published_evidence_links": str(evidence_links),
        "canonical_retired_evidence_links": str(retired_evidence_links),
        "canonical_unjoined_evidence_links": str(unjoined_evidence_links),
    }
    report_mismatches = [
        key for key, value in expected_report.items()
        if report_metric(latest_section, key) != value
    ]
    report_synchronized = not report_mismatches
    evidence_links_classified = (
        unexpected_nonpublished_evidence_links == 0
        and unjoined_evidence_links == 0
    )
    seed_artifacts = sorted(
        path.name for path in (ROOT / "seeds" / "appearance").iterdir()
        if path.is_file() and path.suffix.lower() != ".json"
    )
    ready = not any((
        close_required,
        not report_synchronized,
        not indexes_fresh,
        not evidence_links_classified,
        evidence_gaps,
        duplicate_assignments,
        missing_facet_links,
        unclassified,
        seed_artifacts,
    ))
    queue = next_queue()

    print("scope=general_appearance")
    print(f"state={'READY' if ready else ('CLOSE_REQUIRED' if close_required else 'BLOCKED')}")
    print(f"wake_agent={int(ready)}")
    print(f"close_required={int(close_required)}")
    print(f"published_profiles={published_profiles}")
    print(f"published_features={published_features}")
    print(f"all_evidence_links={all_evidence_links}")
    print(f"published_evidence_links={evidence_links}")
    print(f"nonpublished_evidence_links={nonpublished_evidence_links}")
    print(f"retired_evidence_links={retired_evidence_links}")
    print(f"unjoined_evidence_links={unjoined_evidence_links}")
    print(f"unexpected_nonpublished_evidence_links={unexpected_nonpublished_evidence_links}")
    print(f"evidence_links_classified={int(evidence_links_classified)}")
    print(f"evidence_gaps={evidence_gaps}")
    print(f"duplicate_active_assignments={duplicate_assignments}")
    print(f"missing_facet_links={missing_facet_links}")
    print(f"active_unclassified={unclassified}")
    print(f"last_promoted_seed={last_seed_file}")
    print(f"last_seed_in_latest_report={int(current_seed_in_latest_report)}")
    print(f"seed_artifacts={json.dumps(seed_artifacts, ensure_ascii=False)}")
    print(f"canonical_db_size={canonical_size}")
    print(f"canonical_db_sha256={canonical_sha256}")
    print(f"indexes_fresh={int(indexes_fresh)}")
    print(f"index_states={json.dumps(index_states, ensure_ascii=False, sort_keys=True)}")
    print(f"report_synchronized={int(report_synchronized)}")
    print(f"report_mismatches={json.dumps(report_mismatches, ensure_ascii=False)}")
    print(f"latest_report_heading={latest_heading}")
    print(f"next_queue={json.dumps(queue, ensure_ascii=False, separators=(',', ':'))}")
    print("integrity=not_run_worker_authoritative")
    print(json.dumps({"wakeAgent": ready}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
