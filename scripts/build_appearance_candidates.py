#!/usr/bin/env python3
"""Build a reviewable appearance-candidate database from captured booru data.

The script never writes canonical rows to tag_library.db. Wiki rows already
present in the local snapshot can be used directly; post samples are supplied
as JSONL so network capture remains explicit and reproducible.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from weeb_alexandria_mcp.appearance_schema import (  # noqa: E402
    infer_facet,
    normalize_tag,
)

DEFAULT_DB = ROOT / "tag_library.db"
DEFAULT_OUTPUT = ROOT / "data" / "character_appearance.sqlite"
WIKI_LINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")

DERIVED_SCHEMA_SQL = """
CREATE TABLE appearance_tag_observations (
    character_tag TEXT NOT NULL,
    variant_tag TEXT NOT NULL,
    source_site TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    observed_tag TEXT NOT NULL,
    facet_guess TEXT NOT NULL DEFAULT '',
    support_count INTEGER NOT NULL,
    sample_size INTEGER NOT NULL,
    support_ratio REAL NOT NULL,
    captured_at TEXT NOT NULL,
    PRIMARY KEY(character_tag, variant_tag, source_site, source_kind, observed_tag)
);
CREATE INDEX idx_observations_character_variant
    ON appearance_tag_observations(character_tag, variant_tag, source_site, source_kind);
CREATE INDEX idx_observations_tag
    ON appearance_tag_observations(observed_tag, facet_guess);

CREATE TABLE appearance_candidates (
    candidate_id INTEGER PRIMARY KEY,
    character_tag TEXT NOT NULL,
    variant_tag TEXT NOT NULL,
    facet TEXT NOT NULL,
    canonical_tag TEXT NOT NULL,
    score REAL NOT NULL,
    confidence TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE(character_tag, variant_tag, facet, canonical_tag)
);
CREATE INDEX idx_candidates_character_variant
    ON appearance_candidates(character_tag, variant_tag, status, score DESC);

CREATE TABLE appearance_index_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_link_tag(raw: str) -> str:
    # Booru wiki links use display labels after `|`; the first component is
    # the canonical tag (and may contain parentheses or a leading colon).
    return normalize_tag(raw.replace(" ", "_"))


def read_tag_categories(con: sqlite3.Connection, site: str,
                        names: Iterable[str]) -> dict[str, str]:
    names = sorted({normalize_tag(name) for name in names if normalize_tag(name)})
    if not names:
        return {}
    placeholders = ",".join("?" for _ in names)
    rows = con.execute(
        f"SELECT name, category_name FROM tags WHERE site=? AND name IN ({placeholders})",
        [site, *names],
    ).fetchall()
    return {row[0]: (row[1] or "").strip().lower() for row in rows}


def escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def wiki_observations(con: sqlite3.Connection, character_tag: str,
                      captured_at: str) -> list[dict[str, Any]]:
    rows = con.execute(
        """SELECT site, title, body FROM wiki
           WHERE title=? OR title LIKE ? ESCAPE '\\'
           ORDER BY site, title""",
        (character_tag, escape_like(character_tag) + r"\_(%"),
    ).fetchall()
    result: list[dict[str, Any]] = []
    for site, title, body in rows:
        variant_tag = normalize_tag(title)
        raw_tags = [canonical_link_tag(match) for match in WIKI_LINK_RE.findall(body or "")]
        categories = read_tag_categories(con, site, raw_tags)
        for tag in sorted(set(raw_tags)):
            if not tag or tag in {character_tag, variant_tag}:
                continue
            category = categories.get(tag, "")
            if category in {"meta", "artist", "copyright", "character", "alias"}:
                continue
            if tag not in categories:
                # A link without a local tag row is not a canonical tag in the
                # active snapshot, so leave it for a future source import.
                continue
            result.append({
                "character_tag": character_tag,
                "variant_tag": variant_tag,
                "source_site": site,
                "source_kind": "wiki",
                "source_key": title,
                "source_url": f"https://{site}.donmai.us/wiki_pages/{title}.json"
                    if site == "danbooru" else
                    f"https://gelbooru.com/index.php?page=wiki&s=view&id={title}",
                "observed_tag": tag,
                "facet_guess": infer_facet(tag, category),
                "support_count": 1,
                "sample_size": 1,
                "evidence_text": f"Linked from {site} wiki {title}.",
                "captured_at": captured_at,
            })
    return result


def _as_tag_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [normalize_tag(item) for item in value.split() if normalize_tag(item)]
    if isinstance(value, list):
        return [normalize_tag(str(item)) for item in value if normalize_tag(str(item))]
    return []


def post_record_tags(record: dict[str, Any]) -> list[str]:
    # Prefer category-specific general tags. This avoids accidentally treating
    # artists, copyright, character, or metadata as clothing.
    tags = record.get("tags")
    if isinstance(tags, dict):
        for key in ("general", "tag_string_general", "general_tags"):
            if key in tags:
                return _as_tag_list(tags[key])
    for key in ("tag_string_general", "general_tags"):
        if key in record:
            return _as_tag_list(record[key])
    if isinstance(tags, (str, list)):
        return _as_tag_list(tags)
    return []


def load_post_jsonl(path: Path, selected: set[str], captured_at: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    path_text = "/".join(path.parts).lower()
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
            if not isinstance(record, dict):
                raise ValueError(f"{path}:{line_number}: expected a JSON object")
            character_values = set(_as_tag_list(record.get("tag_string_character", "")))
            character_tag = normalize_tag(record.get("character_tag", ""))
            if not character_tag:
                matching = sorted(selected.intersection(character_values))
                if len(matching) > 1:
                    raise ValueError(
                        f"{path}:{line_number}: ambiguous character tags {matching}; "
                        "provide character_tag explicitly"
                    )
                character_tag = matching[0] if matching else ""
            if not character_tag or (selected and character_tag not in selected):
                continue
            variant_tag = normalize_tag(record.get("variant_tag", ""))
            variants = sorted(
                tag for tag in character_values
                if tag != character_tag and tag.startswith(character_tag + "_(")
            )
            if not variant_tag:
                if len(variants) > 1:
                    raise ValueError(
                        f"{path}:{line_number}: ambiguous variants {variants}; "
                        "provide variant_tag explicitly"
                    )
                variant_tag = variants[0] if variants else character_tag
            elif variant_tag != character_tag and not variant_tag.startswith(character_tag + "_("):
                raise ValueError(
                    f"{path}:{line_number}: variant_tag {variant_tag!r} is not scoped "
                    f"to character_tag {character_tag!r}"
                )
            source_site = normalize_tag(record.get("source_site", ""))
            if not source_site:
                source_site = "danbooru" if "danbooru" in path_text else path.stem
            meta_tags = set(_as_tag_list(record.get("tag_string_meta", "")))
            source_kind = normalize_tag(record.get("source_kind", ""))
            if not source_kind:
                source_kind = "reference_post" if "official_art" in meta_tags else "post_sample"
            source_key = str(record.get("source_key", record.get("id", line_number)))
            source_url = str(record.get("source_url", ""))
            if not source_url and source_site == "danbooru" and source_key.isdigit():
                source_url = f"https://danbooru.donmai.us/posts/{source_key}"
            tags = sorted(set(post_record_tags(record)))
            for tag in tags:
                if tag in {character_tag, variant_tag}:
                    continue
                result.append({
                    "character_tag": character_tag,
                    "variant_tag": variant_tag,
                    "source_site": source_site,
                    "source_kind": source_kind,
                    "source_key": source_key,
                    "source_url": source_url,
                    "observed_tag": tag,
                    "facet_guess": infer_facet(tag, "general"),
                    "support_count": 1,
                    "sample_size": 1,
                    "evidence_text": f"Observed in {source_site} {source_kind} {source_key}.",
                    "captured_at": captured_at,
                })
    return result


def aggregate_observations(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    sample_keys: dict[tuple[str, str, str, str], set[str]] = defaultdict(set)
    support_keys: dict[tuple[str, str, str, str, str], set[str]] = defaultdict(set)
    for row in rows:
        key = (
            row["character_tag"], row["variant_tag"], row["source_site"],
            row["source_kind"], row["observed_tag"],
        )
        sample_key = key[:-1]
        source_key = str(row["source_key"])
        sample_keys[sample_key].add(source_key)
        item = grouped.get(key)
        if item is None:
            item = dict(row)
            item["support_count"] = 0
            grouped[key] = item
        if source_key not in support_keys[key]:
            support_keys[key].add(source_key)
            item["support_count"] += 1
        item["evidence_text"] = row.get("evidence_text", item.get("evidence_text", ""))
        item["source_url"] = row.get("source_url", item.get("source_url", ""))
    for key, item in grouped.items():
        sample_size = len(sample_keys[key[:-1]]) or int(item.get("sample_size", 1))
        item["sample_size"] = sample_size
        item["support_ratio"] = round(min(1.0, item["support_count"] / sample_size), 6)
    return sorted(grouped.values(), key=lambda row: (
        row["character_tag"], row["variant_tag"], row["source_site"],
        row["source_kind"], row["observed_tag"],
    ))


def build_candidates(observations: list[dict[str, Any]], created_at: str) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in observations:
        grouped[(row["character_tag"], row["variant_tag"], row["observed_tag"])].append(row)
    candidates: list[dict[str, Any]] = []
    tier_weight = {"wiki": 1.0, "reference_post": 1.0, "post_sample": 0.7}
    for (character_tag, variant_tag, canonical_tag), evidence in sorted(grouped.items()):
        facet = next((row["facet_guess"] for row in evidence if row["facet_guess"]), "")
        if not facet:
            # Unknown/non-visual tags remain auditable observations, but must
            # not become appearance candidates requiring human cleanup.
            continue
        primary = any(row["source_kind"] in {"wiki", "reference_post"} for row in evidence)
        support = sum(float(row["support_ratio"]) * tier_weight.get(row["source_kind"], 0.5)
                      for row in evidence)
        source_bonus = min(0.25, 0.1 * len({row["source_site"] for row in evidence}))
        score = round(min(1.0, support / max(1, len(evidence)) + source_bonus), 6)
        confidence = "high" if primary else "medium" if score >= 0.5 else "low"
        sources = ", ".join(sorted({
            f"{row['source_site']}:{row['source_kind']}"
            for row in evidence
        }))
        reason = (
            f"Observed in {sources}; support="
            + ", ".join(
                f"{row['source_site']} {row['support_count']}/{row['sample_size']}"
                for row in evidence
            )
            + ("; deterministic facet" if facet else "; facet requires review")
        )
        candidates.append({
            "character_tag": character_tag,
            "variant_tag": variant_tag,
            "facet": facet,
            "canonical_tag": canonical_tag,
            "score": score,
            "confidence": confidence,
            "status": "pending",
            "reason": reason,
            "created_at": created_at,
        })
    return candidates


def write_derived(output: Path, db: Path, observations: list[dict[str, Any]],
                  candidates: list[dict[str, Any]], built_at: str,
                  source_size: int, source_sha256: str) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{output.name}.", suffix=".tmp", dir=output.parent)
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        con = sqlite3.connect(temp_path)
        con.executescript(DERIVED_SCHEMA_SQL)
        con.executemany(
            """INSERT INTO appearance_tag_observations(
                character_tag, variant_tag, source_site, source_kind,
                observed_tag, facet_guess, support_count, sample_size,
                support_ratio, captured_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [(
                row["character_tag"], row["variant_tag"], row["source_site"],
                row["source_kind"], row["observed_tag"], row["facet_guess"],
                row["support_count"], row["sample_size"], row["support_ratio"],
                row["captured_at"],
            ) for row in observations],
        )
        con.executemany(
            """INSERT INTO appearance_candidates(
                character_tag, variant_tag, facet, canonical_tag, score,
                confidence, status, reason, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [(
                row["character_tag"], row["variant_tag"], row["facet"],
                row["canonical_tag"], row["score"], row["confidence"],
                row["status"], row["reason"], row["created_at"],
            ) for row in candidates],
        )
        metadata = {
            "schema_version": "1",
            "built_at": built_at,
            "source_db": str(db.resolve()),
            "source_size": str(source_size),
            "source_sha256": source_sha256,
            "observation_rows": str(len(observations)),
            "candidate_rows": str(len(candidates)),
        }
        con.executemany(
            "INSERT INTO appearance_index_metadata(key, value) VALUES (?, ?)",
            sorted(metadata.items()),
        )
        con.commit()
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"derived appearance index integrity check failed: {integrity}")
        con.close()
        os.replace(temp_path, output)
    except Exception:
        try:
            con.close()  # type: ignore[union-attr]
        except Exception:
            pass
        temp_path.unlink(missing_ok=True)
        raise


def build(db: Path, output: Path, characters: list[str],
          post_jsonl: list[Path]) -> dict[str, int]:
    selected = {normalize_tag(value) for value in characters if normalize_tag(value)}
    if not selected:
        raise ValueError("at least one --character is required")
    if db.resolve() == output.resolve():
        raise ValueError("derived output must not overwrite the source database")
    captured_at = datetime.now(timezone.utc).isoformat()
    source_size = db.stat().st_size
    source_sha256 = sha256_file(db)
    con = sqlite3.connect(db)
    try:
        observations: list[dict[str, Any]] = []
        for character_tag in sorted(selected):
            observations.extend(wiki_observations(con, character_tag, captured_at))
    finally:
        con.close()
    for path in post_jsonl:
        observations.extend(load_post_jsonl(path, selected, captured_at))
    if db.stat().st_size != source_size or sha256_file(db) != source_sha256:
        raise RuntimeError(
            "source database changed while building appearance candidates; retry from a stable snapshot"
        )
    aggregated = aggregate_observations(observations)
    candidates = build_candidates(aggregated, captured_at)
    write_derived(
        output, db, aggregated, candidates, captured_at,
        source_size, source_sha256,
    )
    return {
        "characters": len(selected),
        "observations": len(aggregated),
        "candidates": len(candidates),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--character", action="append", required=True,
                        help="Canonical character tag; may be repeated.")
    parser.add_argument("--posts-jsonl", action="append", type=Path, default=[],
                        help="Captured post JSONL; may be repeated.")
    args = parser.parse_args()
    result = build(args.db, args.output, args.character, args.posts_jsonl)
    for key, value in result.items():
        print(f"{key}: {value}")
    print(f"output: {args.output.resolve()}")


if __name__ == "__main__":
    main()
