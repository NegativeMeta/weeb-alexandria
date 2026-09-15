#!/usr/bin/env python3
"""Deterministic lifecycle controller for the general appearance worker.

The cron job invokes this file without arguments as a fail-closed gate.  The
LLM may review sources and create seeds, but canonical writes and batch closure
must go through the explicit lifecycle commands below.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DB = ROOT / "tag_library.db"
REPORT = ROOT / "reports" / "hololive_appearance_queue.md"
SEEDS = ROOT / "seeds" / "appearance"
DATA = ROOT / "data"
STATE_PATH = DATA / "general_appearance_worker_state.json"
EXCLUSION_PATH = DATA / "general_appearance_exclusions.json"
CANDIDATES = DATA / "character_appearance.sqlite"
SEARCH_INDEX = DATA / "tag_search.sqlite"
CONTEXT_INDEX = DATA / "character_context.sqlite"
PREFLIGHT = ROOT / "scripts" / "general_appearance_preflight.py"
RANKER = ROOT / "scripts" / "rank_general_queue.py"
CANDIDATE_BUILDER = ROOT / "scripts" / "build_appearance_candidates.py"
SEARCH_BUILDER = ROOT / "scripts" / "build_search_index.py"
CONTEXT_BUILDER = ROOT / "scripts" / "build_context_index.py"
VALIDATOR = ROOT / "scripts" / "validate_general_appearance_batch.py"
BATCH_PROMOTER = ROOT / "scripts" / "promote_appearance_batch.py"
MCP_PROBE = ROOT / "scripts" / "probe_appearance_runtime.py"
BATCH_LIMIT = 5
STATE_VERSION = 1
ACTIVE_PHASES = {"reserved", "prepared", "reviewing", "promoted", "finalizing"}
PROJECT_PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
PYTHON = str(PROJECT_PYTHON if PROJECT_PYTHON.is_file() else Path(sys.executable))


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_text(path, json_text(value))


def create_state_exclusive(state: dict[str, Any]) -> None:
    """Create the lease manifest atomically; never overwrite another run."""
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = json_text(state).encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(str(STATE_PATH), flags, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        STATE_PATH.unlink(missing_ok=True)
        raise


def load_state() -> dict[str, Any] | None:
    if not STATE_PATH.exists():
        return None
    try:
        value = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"worker state is not valid JSON: {STATE_PATH}: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"worker state must be a JSON object: {STATE_PATH}")
    if value.get("schema_version") != STATE_VERSION:
        raise RuntimeError(
            f"unsupported worker state version: {value.get('schema_version')!r}"
        )
    if not value.get("run_id") or not value.get("phase"):
        raise RuntimeError("worker state requires run_id and phase")
    return value


def save_state(state: dict[str, Any]) -> None:
    state["updated_at"] = now()
    atomic_write_json(STATE_PATH, state)


def source_fingerprint(path: Path = DB) -> dict[str, Any]:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return {"size": path.stat().st_size, "sha256": digest.hexdigest()}


def _command_result(
    command: list[str], label: str, *, timeout: int = 900,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
        check=False,
    )
    if result.returncode:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(
            f"{label} failed with exit {result.returncode}: {detail[-1200:]}"
        )
    return result


def _preflight() -> tuple[bool, str]:
    result = subprocess.run(
        [PYTHON, str(PREFLIGHT)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    output = (result.stdout or "") + (("\n" + result.stderr) if result.stderr else "")
    ready = False
    for line in reversed(result.stdout.splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and "wakeAgent" in value:
            ready = bool(value["wakeAgent"])
            break
    if result.returncode:
        raise RuntimeError(f"preflight failed with exit {result.returncode}: {output[-1200:]}")
    return ready, output.strip()


def _rank(limit: int) -> list[dict[str, Any]]:
    result = _command_result(
        [PYTHON, str(RANKER), "--db", str(DB), "--limit", str(limit)],
        "general queue ranking",
    )
    value = json.loads(result.stdout)
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise RuntimeError("general queue ranking did not return a JSON list of objects")
    return value


def _next_batch_number() -> int:
    if not REPORT.exists():
        return 1
    text = REPORT.read_text(encoding="utf-8", errors="replace")
    numbers = [
        int(match.group(1))
        for match in re.finditer(r"^## General appearance batch (\d+)\b", text, re.MULTILINE)
    ]
    return max(numbers, default=0) + 1


def _print_gate_state(state: dict[str, Any], continuation: bool) -> None:
    print("scope=general_appearance")
    print("worker_gate=continuation" if continuation else "worker_gate=reserved")
    print(f"worker_run_id={state['run_id']}")
    print(f"worker_phase={state['phase']}")
    print(f"worker_batch_number={state['batch_number']}")
    print(f"worker_selected={json.dumps(state['selected'], ensure_ascii=False)}")
    if state.get("last_error"):
        print(f"worker_last_error={state['last_error']}")


def gate(*, dry_run: bool = False) -> int:
    state = load_state()
    if state and state["phase"] == "closed":
        ready, output = _preflight()
        print(output)
        if ready and not dry_run:
            STATE_PATH.unlink(missing_ok=True)
            state = None
        elif not ready and not dry_run:
            state["phase"] = "promoted"
            state["last_error"] = "closed manifest failed its final preflight; retrying close"
            save_state(state)
        else:
            _print_gate_state(state, continuation=True)
            print(json.dumps({"wakeAgent": False}, separators=(",", ":")))
            return 0

    if state:
        _print_gate_state(state, continuation=True)
        print(json.dumps({"wakeAgent": state["phase"] in ACTIVE_PHASES}, separators=(",", ":")))
        return 0

    ready, output = _preflight()
    print(output)
    if not ready:
        print("worker_gate=blocked_preflight")
        print(json.dumps({"wakeAgent": False}, separators=(",", ":")))
        return 0

    ranking = _rank(BATCH_LIMIT)
    selected = [str(row["name"]) for row in ranking]
    if not selected:
        print("worker_gate=queue_empty")
        print(json.dumps({"wakeAgent": False}, separators=(",", ":")))
        return 0

    state = {
        "schema_version": STATE_VERSION,
        "scope": "general_appearance",
        "run_id": uuid.uuid4().hex,
        "batch_number": _next_batch_number(),
        "phase": "reserved",
        "created_at": now(),
        "updated_at": now(),
        "selected": selected,
        "ranking": ranking,
        "source_snapshot": source_fingerprint(),
        "candidate_snapshot": None,
        "candidate_final": None,
        "posts_jsonl": [],
        "decisions": {},
        "promotion": None,
        "backup_path": None,
        "exclusions_added": [],
        "next_queue": [],
        "mcp_probe": None,
        "canonical_metrics": None,
        "commands": [],
        "last_error": "",
    }
    if dry_run:
        _print_gate_state(state, continuation=False)
        print("worker_dry_run=1")
        print(json.dumps({"wakeAgent": False}, separators=(",", ":")))
        return 0
    try:
        create_state_exclusive(state)
    except FileExistsError:
        existing = load_state()
        if existing is None:
            raise RuntimeError("worker state appeared concurrently but could not be read")
        _print_gate_state(existing, continuation=True)
        print(json.dumps({"wakeAgent": existing["phase"] in ACTIVE_PHASES}, separators=(",", ":")))
        return 0
    _print_gate_state(state, continuation=False)
    print(json.dumps({"wakeAgent": True}, separators=(",", ":")))
    return 0


def _require_state(run_id: str) -> dict[str, Any]:
    state = load_state()
    if state is None:
        raise RuntimeError("no active general appearance worker state")
    if state["run_id"] != run_id:
        raise RuntimeError(
            f"run_id mismatch: active={state['run_id']} supplied={run_id}"
        )
    if state["phase"] == "aborted":
        raise RuntimeError("worker state is aborted; clear it explicitly before a new run")
    return state


def _record_command(state: dict[str, Any], label: str, result: subprocess.CompletedProcess[str]) -> None:
    state.setdefault("commands", []).append({
        "label": label,
        "returncode": result.returncode,
        "completed_at": now(),
    })
    save_state(state)


def _candidate_metrics(path: Path = CANDIDATES) -> dict[str, Any]:
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    con = sqlite3.connect(uri, uri=True, timeout=15)
    con.row_factory = sqlite3.Row
    try:
        metadata = dict(con.execute(
            "SELECT key, value FROM appearance_index_metadata"
        ).fetchall())
        rows = con.execute(
            """SELECT character_tag, count(*) AS observations
               FROM appearance_tag_observations
               GROUP BY character_tag"""
        ).fetchall()
        candidate_rows = con.execute(
            """SELECT character_tag, count(*) AS candidates
               FROM appearance_candidates
               GROUP BY character_tag"""
        ).fetchall()
    finally:
        con.close()
    per_character = {
        str(row["character_tag"]): {
            "observations": int(row["observations"]), "candidates": 0
        }
        for row in rows
    }
    for row in candidate_rows:
        per_character.setdefault(str(row["character_tag"]), {"observations": 0, "candidates": 0})
        per_character[str(row["character_tag"])] ["candidates"] = int(row["candidates"])
    return {
        "metadata": metadata,
        "observations": sum(item["observations"] for item in per_character.values()),
        "candidates": sum(item["candidates"] for item in per_character.values()),
        "per_character": per_character,
    }


def prepare(run_id: str, posts_jsonl: list[Path]) -> int:
    state = _require_state(run_id)
    if state["phase"] in {"prepared", "reviewing", "promoted", "finalizing"}:
        print(json.dumps(state.get("candidate_snapshot"), ensure_ascii=False, indent=2))
        return 0
    if state["phase"] != "reserved":
        raise RuntimeError(f"cannot prepare from phase {state['phase']}")
    if source_fingerprint() != state["source_snapshot"]:
        raise RuntimeError("canonical database changed after reservation; refusing stale preparation")
    paths = [Path(path).resolve() for path in posts_jsonl]
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(path)
    command = [
        PYTHON, str(CANDIDATE_BUILDER),
        "--db", str(DB), "--output", str(CANDIDATES),
    ]
    for character in state["selected"]:
        command.extend(["--character", character])
    for path in paths:
        command.extend(["--posts-jsonl", str(path)])
    result = _command_result(command, "review candidate build")
    _record_command(state, "prepare_candidates", result)
    metrics = _candidate_metrics()
    state["posts_jsonl"] = [str(path) for path in paths]
    state["candidate_snapshot"] = metrics
    state["phase"] = "prepared"
    state["last_error"] = ""
    save_state(state)
    print(json.dumps(metrics, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _seed_path(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = ROOT / path
    path = path.resolve()
    try:
        path.relative_to(ROOT)
    except ValueError as exc:
        raise ValueError("seed must be inside the repository") from exc
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def record_decision(
    run_id: str, character: str, decision: str, seed: str | None, reason: str,
) -> int:
    state = _require_state(run_id)
    if state["phase"] not in {"prepared", "reviewing"}:
        raise RuntimeError(f"cannot record decisions from phase {state['phase']}; prepare first")
    if character not in state["selected"]:
        raise ValueError(f"character is not selected for this run: {character}")
    if decision == "published":
        if not seed:
            raise ValueError("published decisions require --seed")
        seed_path = _seed_path(seed)
        from scripts.promote_appearance import read_seed  # local import keeps gate lightweight
        data = read_seed(seed_path)
        if str(data.get("character_tag")) != character:
            raise ValueError(
                f"seed character_tag {data.get('character_tag')!r} does not match {character!r}"
            )
        profiles = data.get("profiles", [])
        if len(profiles) != 1:
            raise ValueError("published seed must contain exactly one profile")
        if str(profiles[0].get("status", "published")) != "published":
            raise ValueError("published seed profile status must be 'published'")
        if not profiles[0].get("features"):
            raise ValueError("published seed must contain at least one feature")
        normalized = {
            "decision": decision,
            "seed_path": str(seed_path),
            "reason": reason.strip(),
        }
    else:
        if not reason.strip():
            raise ValueError("deferred decisions require a non-empty --reason")
        normalized = {
            "decision": decision,
            "seed_path": None,
            "reason": reason.strip(),
        }
    old = state["decisions"].get(character)
    if old:
        comparable_old = {key: old.get(key) for key in normalized}
        if comparable_old != normalized:
            raise ValueError(f"conflicting decision already recorded for {character}")
        print(json.dumps(old, ensure_ascii=False, sort_keys=True))
        return 0
    normalized["recorded_at"] = now()
    state["decisions"][character] = normalized
    state["phase"] = "reviewing"
    save_state(state)
    print(json.dumps(normalized, ensure_ascii=False, sort_keys=True))
    return 0


def _all_decisions(state: dict[str, Any]) -> None:
    missing = [character for character in state["selected"] if character not in state["decisions"]]
    if missing:
        raise RuntimeError(f"missing decisions for selected characters: {missing}")
    invalid = [
        character for character in state["selected"]
        if state["decisions"][character].get("decision") not in {"published", "deferred"}
    ]
    if invalid:
        raise RuntimeError(f"invalid decisions for selected characters: {invalid}")


def _accepted_seed_paths(state: dict[str, Any]) -> list[Path]:
    return [
        Path(state["decisions"][character]["seed_path"])
        for character in state["selected"]
        if state["decisions"][character]["decision"] == "published"
    ]


def _backup_database(run_id: str) -> Path:
    destination = Path(tempfile.gettempdir()) / f"weeb_general_worker_{run_id}_before.sqlite"
    if destination.exists():
        return destination
    source = sqlite3.connect(str(DB), timeout=120)
    target = sqlite3.connect(str(destination), timeout=120)
    try:
        source.backup(target)
        target.commit()
    finally:
        target.close()
        source.close()
    return destination


def _parse_json_output(output: str, label: str) -> dict[str, Any]:
    try:
        value = json.loads(output)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{label} did not return JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{label} did not return a JSON object")
    return value


def publish(run_id: str) -> int:
    state = _require_state(run_id)
    if state["phase"] in {"promoted", "finalizing"}:
        print(json.dumps(state.get("promotion"), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if state["phase"] not in {"prepared", "reviewing"}:
        raise RuntimeError(f"cannot publish from phase {state['phase']}")
    _all_decisions(state)
    if state.get("candidate_snapshot") is None:
        raise RuntimeError("candidate preparation has not completed")
    if source_fingerprint() != state["source_snapshot"]:
        raise RuntimeError("canonical database changed after candidate preparation; refusing stale seeds")
    seeds = _accepted_seed_paths(state)
    for seed in seeds:
        if not seed.is_file():
            raise FileNotFoundError(seed)
    if seeds:
        validation_command = [
            PYTHON, str(VALIDATOR),
            "--db", str(DB), "--candidates", str(CANDIDATES),
        ]
        for seed in seeds:
            validation_command.extend(["--seed", str(seed)])
        result = _command_result(validation_command, "strict appearance validation")
        _record_command(state, "validate_batch", result)
        if re.search(r"\berrors=[1-9]\d*\b", result.stdout):
            raise RuntimeError("strict appearance validation reported errors")
        backup = _backup_database(run_id)
        state["backup_path"] = str(backup)
        save_state(state)
        promote_command = [PYTHON, str(BATCH_PROMOTER), "--db", str(DB)]
        for seed in seeds:
            promote_command.extend(["--input", str(seed)])
        result = _command_result(promote_command, "atomic appearance promotion")
        _record_command(state, "promote_batch", result)
        promotion = _parse_json_output(result.stdout, "atomic appearance promotion")
    else:
        promotion = {
            "seeds": {},
            "totals": {
                "profiles": 0, "features": 0, "evidence_links": 0,
                "sources": 0, "conflicts": 0,
            },
        }
    state["promotion"] = promotion
    state["phase"] = "promoted"
    state["canonical_after_promotion"] = source_fingerprint()
    state["last_error"] = ""
    save_state(state)
    print(json.dumps(promotion, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _connect_read_only(path: Path) -> sqlite3.Connection:
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    con = sqlite3.connect(uri, uri=True, timeout=30)
    con.execute("PRAGMA busy_timeout=30000")
    con.execute("PRAGMA query_only=ON")
    con.row_factory = sqlite3.Row
    return con


def _canonical_metrics() -> dict[str, Any]:
    con = _connect_read_only(DB)
    try:
        integrity = str(con.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_keys = [tuple(row) for row in con.execute("PRAGMA foreign_key_check").fetchall()]
        queries = {
            "published_profiles": "SELECT count(*) FROM character_appearance_profiles WHERE status='published'",
            "published_features": "SELECT count(*) FROM character_appearance_features WHERE status='published'",
            "all_evidence_links": "SELECT count(*) FROM character_appearance_feature_sources",
            "published_evidence_links": """SELECT count(*)
                FROM character_appearance_feature_sources x
                JOIN character_appearance_features f ON f.feature_id=x.feature_id
                WHERE f.status='published'""",
            "retired_evidence_links": """SELECT count(*)
                FROM character_appearance_feature_sources x
                JOIN character_appearance_features f ON f.feature_id=x.feature_id
                WHERE f.status='retired'""",
            "unjoined_evidence_links": """SELECT count(*)
                FROM character_appearance_feature_sources x
                LEFT JOIN character_appearance_features f ON f.feature_id=x.feature_id
                WHERE f.feature_id IS NULL""",
            "evidence_gaps": """SELECT count(*) FROM character_appearance_features f
                WHERE f.status IN ('reviewed','published') AND NOT EXISTS (
                    SELECT 1 FROM character_appearance_feature_sources x
                    WHERE x.feature_id=f.feature_id)""",
            "duplicate_active_assignments": """SELECT count(*) FROM (
                SELECT appearance_key, canonical_tag, count(*) AS n
                FROM character_appearance_features WHERE status <> 'retired'
                GROUP BY appearance_key, canonical_tag HAVING n > 1)""",
            "missing_facet_links": """SELECT count(*) FROM character_appearance_features
                WHERE status <> 'retired' AND facet_id IS NULL""",
            "active_unclassified": """SELECT count(*) FROM character_appearance_features
                WHERE status <> 'retired' AND facet='unclassified'""",
        }
        metrics = {key: int(con.execute(query).fetchone()[0]) for key, query in queries.items()}
        row = con.execute(
            "SELECT value FROM appearance_schema_metadata WHERE key='last_promoted_seed'"
        ).fetchone()
        metrics["last_promoted_seed"] = str(row[0]) if row else ""
        metrics["integrity"] = integrity
        metrics["foreign_key_errors"] = len(foreign_keys)
        return metrics
    finally:
        con.close()


def _character_metrics(con: sqlite3.Connection, character: str) -> dict[str, int]:
    profiles = int(con.execute(
        "SELECT count(*) FROM character_appearance_profiles WHERE character_tag=? AND status='published'",
        (character,),
    ).fetchone()[0])
    features = int(con.execute(
        """SELECT count(*) FROM character_appearance_features f
           JOIN character_appearance_profiles p ON p.appearance_key=f.appearance_key
           WHERE p.character_tag=? AND p.status='published' AND f.status='published'""",
        (character,),
    ).fetchone()[0])
    evidence = int(con.execute(
        """SELECT count(*) FROM character_appearance_feature_sources x
           JOIN character_appearance_features f ON f.feature_id=x.feature_id
           JOIN character_appearance_profiles p ON p.appearance_key=f.appearance_key
           WHERE p.character_tag=? AND p.status='published' AND f.status='published'""",
        (character,),
    ).fetchone()[0])
    return {"profiles": profiles, "features": features, "evidence_links": evidence}


def _validate_canonical(state: dict[str, Any]) -> dict[str, Any]:
    metrics = _canonical_metrics()
    if metrics["integrity"] != "ok":
        raise RuntimeError(f"canonical integrity check failed: {metrics['integrity']}")
    if metrics["foreign_key_errors"]:
        raise RuntimeError(f"canonical foreign-key check failed: {metrics['foreign_key_errors']}")
    if metrics["evidence_gaps"] or metrics["duplicate_active_assignments"]:
        raise RuntimeError("canonical appearance evidence or uniqueness invariants failed")
    if metrics["missing_facet_links"] or metrics["active_unclassified"]:
        raise RuntimeError("canonical appearance facet invariants failed")
    if metrics["unjoined_evidence_links"]:
        raise RuntimeError("canonical appearance contains unjoined evidence links")
    con = _connect_read_only(DB)
    try:
        for character in state["selected"]:
            counts = _character_metrics(con, character)
            decision = state["decisions"][character]["decision"]
            if decision == "published":
                if counts["profiles"] < 1 or counts["features"] < 1 or counts["evidence_links"] < 1:
                    raise RuntimeError(
                        f"published character lacks complete canonical data: {character}: {counts}"
                    )
            elif counts["profiles"]:
                raise RuntimeError(f"deferred character unexpectedly has a published profile: {character}")
    finally:
        con.close()
    return metrics


def _probe_runtime(state: dict[str, Any]) -> dict[str, Any]:
    command = [PYTHON, str(MCP_PROBE), "--db", str(DB)]
    for character in state["selected"]:
        command.extend(["--character", character])
    result = _command_result(command, "appearance runtime probe", timeout=300)
    probe = _parse_json_output(result.stdout, "appearance runtime probe")
    if probe.get("status") != "ok":
        raise RuntimeError(f"appearance runtime probe returned {probe}")
    return probe


def _build_derived(state: dict[str, Any]) -> dict[str, Any]:
    before = source_fingerprint()
    search = _command_result(
        [PYTHON, str(SEARCH_BUILDER), "--source", str(DB), "--output", str(SEARCH_INDEX)],
        "search index rebuild",
    )
    _record_command(state, "rebuild_search_index", search)
    context = _command_result(
        [PYTHON, str(CONTEXT_BUILDER), "--source", str(DB), "--output", str(CONTEXT_INDEX)],
        "context index rebuild",
    )
    _record_command(state, "rebuild_context_index", context)
    candidates_command = [
        PYTHON, str(CANDIDATE_BUILDER),
        "--db", str(DB), "--output", str(CANDIDATES),
    ]
    for character in state["selected"]:
        candidates_command.extend(["--character", character])
    for path in state.get("posts_jsonl", []):
        candidates_command.extend(["--posts-jsonl", path])
    candidates = _command_result(candidates_command, "final appearance candidate rebuild")
    _record_command(state, "rebuild_appearance_candidates", candidates)
    after = source_fingerprint()
    if after != before:
        raise RuntimeError("canonical database changed during derived-index rebuild")
    return _candidate_metrics()


def _update_exclusions(state: dict[str, Any]) -> list[str]:
    deferred = [
        character for character in state["selected"]
        if state["decisions"][character]["decision"] == "deferred"
    ]
    if not deferred:
        return []
    existing: list[str] = []
    if EXCLUSION_PATH.exists():
        value = json.loads(EXCLUSION_PATH.read_text(encoding="utf-8"))
        if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
            raise RuntimeError("dynamic exclusion ledger is malformed")
        existing = [item.strip() for item in value]
    merged = sorted(set(existing) | set(deferred))
    atomic_write_json(EXCLUSION_PATH, merged)
    return sorted(set(deferred) - set(existing))


def _report_section(state: dict[str, Any], metrics: dict[str, Any], next_queue: list[dict[str, Any]]) -> str:
    last_seed = metrics.get("last_promoted_seed", "")
    last_seed_name = str(last_seed).replace("\\", "/").rsplit("/", 1)[-1] if last_seed else "(none)"
    lines = [
        f"## General appearance batch {state['batch_number']} (worker deterministic close)",
        "",
        f"worker_run_id={state['run_id']}",
        "batch_close=complete",
        f"selected_characters={len(state['selected'])}",
        f"source_snapshot_sha256={state['source_snapshot']['sha256']}",
        f"source_snapshot_size={state['source_snapshot']['size']}",
        f"last_promoted_seed={last_seed_name}",
        "",
        "### Review reservation",
        "",
        "| character | total posts | decision | seed | reason |",
        "| --- | ---: | --- | --- | --- |",
    ]
    ranking_by_name = {str(row["name"]): row for row in state["ranking"]}
    for character in state["selected"]:
        row = ranking_by_name.get(character, {})
        decision = state["decisions"][character]
        seed = decision.get("seed_path") or "—"
        seed = str(seed).replace("\\", "/").rsplit("/", 1)[-1]
        reason = str(decision.get("reason") or "—").replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| `{character}` | {int(row.get('total', 0))} | {decision['decision']} "
            f"| `{seed}` | {reason} |"
        )
    review = state.get("candidate_snapshot") or {}
    final = state.get("candidate_final") or {}
    lines.extend([
        "",
        f"review_observations={review.get('observations', 0)}",
        f"review_candidates={review.get('candidates', 0)}",
        f"final_observations={final.get('observations', 0)}",
        f"final_candidates={final.get('candidates', 0)}",
        "",
        "### Canonical close metrics",
        "",
        f"canonical_db_size={DB.stat().st_size}",
        f"canonical_db_sha256={source_fingerprint()['sha256']}",
        f"canonical_published_profiles={metrics['published_profiles']}",
        f"canonical_published_features={metrics['published_features']}",
        f"canonical_all_evidence_links={metrics['all_evidence_links']}",
        f"canonical_published_evidence_links={metrics['published_evidence_links']}",
        f"canonical_retired_evidence_links={metrics['retired_evidence_links']}",
        f"canonical_unjoined_evidence_links={metrics['unjoined_evidence_links']}",
        f"canonical_integrity={metrics['integrity']}",
        f"canonical_foreign_key_errors={metrics['foreign_key_errors']}",
        f"exclusions_added={json.dumps(state.get('exclusions_added', []), ensure_ascii=False)}",
        "",
        "### Next ranked queue",
        "",
    ])
    for index, row in enumerate(next_queue, 1):
        lines.append(
            f"{index}. `{row['name']}` — total={int(row.get('total', 0))}, "
            f"danbooru={int(row.get('danbooru', 0))}, gelbooru={int(row.get('gelbooru', 0))}, "
            f"e621={int(row.get('e621', 0))}"
        )
    lines.extend(["", "<!-- worker deterministic close; do not edit this section manually -->", ""])
    return "\n".join(lines)


def _report_metric(section: str, key: str) -> str | None:
    match = re.search(rf"(?m)^{re.escape(key)}=(.+)$", section)
    return match.group(1).strip() if match else None


def _append_report(state: dict[str, Any], metrics: dict[str, Any], next_queue: list[dict[str, Any]]) -> None:
    if not REPORT.exists():
        raise FileNotFoundError(REPORT)
    existing = REPORT.read_text(encoding="utf-8", errors="replace")
    heading = f"## General appearance batch {state['batch_number']} "
    section = _report_section(state, metrics, next_queue)
    if heading in existing:
        start = existing.index(heading)
        current = existing[start:]
        required = {
            "batch_close": "complete",
            "canonical_db_size": str(DB.stat().st_size),
            "canonical_db_sha256": source_fingerprint()["sha256"],
            "canonical_published_profiles": str(metrics["published_profiles"]),
            "canonical_published_features": str(metrics["published_features"]),
            "canonical_all_evidence_links": str(metrics["all_evidence_links"]),
            "canonical_published_evidence_links": str(metrics["published_evidence_links"]),
            "canonical_retired_evidence_links": str(metrics["retired_evidence_links"]),
            "canonical_unjoined_evidence_links": str(metrics["unjoined_evidence_links"]),
        }
        mismatches = [key for key, value in required.items() if _report_metric(current, key) != value]
        if mismatches:
            raise RuntimeError(f"existing batch report conflicts with canonical state: {mismatches}")
        return
    combined = existing.rstrip() + "\n\n" + section
    atomic_write_text(REPORT, combined.rstrip() + "\n")


def close(run_id: str) -> int:
    state = _require_state(run_id)
    if state["phase"] == "closed":
        print("worker_close=already_closed")
        return 0
    if state["phase"] != "promoted":
        raise RuntimeError(f"cannot close from phase {state['phase']}")
    _all_decisions(state)
    state["phase"] = "finalizing"
    state["last_error"] = ""
    save_state(state)
    try:
        if state.get("canonical_after_promotion") and source_fingerprint() != state["canonical_after_promotion"]:
            raise RuntimeError("canonical database changed before finalization")
        state["mcp_probe"] = _probe_runtime(state)
        save_state(state)
        state["candidate_final"] = _build_derived(state)
        state["canonical_metrics"] = _validate_canonical(state)
        state["exclusions_added"] = _update_exclusions(state)
        state["next_queue"] = _rank(10)
        _append_report(state, state["canonical_metrics"], state["next_queue"])
        state["phase"] = "closed"
        save_state(state)
        ready, output = _preflight()
        print(output)
        if not ready:
            raise RuntimeError("final preflight did not return READY")
        STATE_PATH.unlink(missing_ok=True)
        print("worker_close=complete")
        print(json.dumps({
            "run_id": run_id,
            "batch_number": state["batch_number"],
            "next_queue": state["next_queue"],
            "canonical_metrics": state["canonical_metrics"],
        }, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        current = load_state()
        if current and current["run_id"] == run_id:
            current["phase"] = "promoted"
            current["last_error"] = str(exc)[-1200:]
            save_state(current)
        raise


def abort(run_id: str, reason: str) -> int:
    state = _require_state(run_id)
    state["phase"] = "aborted"
    state["last_error"] = reason.strip() or "aborted explicitly"
    save_state(state)
    print(f"worker_abort=recorded run_id={run_id}")
    return 0


def clear(run_id: str) -> int:
    state = load_state()
    if state is None:
        raise RuntimeError("no active general appearance worker state")
    if state["run_id"] != run_id:
        raise RuntimeError(
            f"run_id mismatch: active={state['run_id']} supplied={run_id}"
        )
    if state["phase"] != "aborted":
        raise RuntimeError("only an explicitly aborted worker state may be cleared")
    STATE_PATH.unlink(missing_ok=True)
    print(f"worker_state=cleared run_id={run_id}")
    return 0


def status() -> int:
    state = load_state()
    if state is None:
        print("worker_state=none")
        return 0
    _print_gate_state(state, continuation=True)
    print(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--gate", action="store_true")
    actions.add_argument("--status", action="store_true")
    actions.add_argument("--prepare", action="store_true")
    actions.add_argument("--record-decision", action="store_true")
    actions.add_argument("--publish", action="store_true")
    actions.add_argument("--close", action="store_true")
    actions.add_argument("--abort", action="store_true")
    actions.add_argument("--clear", action="store_true")
    parser.add_argument("--run-id")
    parser.add_argument("--character")
    parser.add_argument("--decision", choices=("published", "deferred"))
    parser.add_argument("--seed")
    parser.add_argument("--reason", default="")
    parser.add_argument("--posts-jsonl", action="append", type=Path, default=[])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    action = "gate"
    if args.status:
        action = "status"
    elif args.prepare:
        action = "prepare"
    elif args.record_decision:
        action = "record-decision"
    elif args.publish:
        action = "publish"
    elif args.close:
        action = "close"
    elif args.abort:
        action = "abort"
    elif args.clear:
        action = "clear"

    try:
        if action == "gate":
            return gate(dry_run=args.dry_run)
        if action == "status":
            return status()
        if not args.run_id:
            parser.error(f"--run-id is required for --{action}")
        if action == "prepare":
            return prepare(args.run_id, args.posts_jsonl)
        if action == "record-decision":
            if not args.character or not args.decision:
                parser.error("--character and --decision are required for --record-decision")
            return record_decision(
                args.run_id, args.character, args.decision, args.seed, args.reason
            )
        if action == "publish":
            return publish(args.run_id)
        if action == "close":
            return close(args.run_id)
        if action == "abort":
            return abort(args.run_id, args.reason)
        if action == "clear":
            return clear(args.run_id)
        raise AssertionError(action)
    except Exception as exc:
        if args.run_id:
            try:
                state = load_state()
                if state and state["run_id"] == args.run_id and state["phase"] not in {"aborted", "closed"}:
                    state["last_error"] = str(exc)[-1200:]
                    save_state(state)
            except Exception:
                pass
        print(f"ERROR {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
