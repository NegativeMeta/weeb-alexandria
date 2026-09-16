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
SEED_ARCHIVE = ROOT / "seeds" / "archive"
DATA = ROOT / "data"
STATE_PATH = DATA / "general_appearance_worker_state.json"
ARCHIVE_MANIFEST_PATH = DATA / "appearance_seed_archive_manifest.json"
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
AUTO_DEFER_POLICY = "strict_validation_to_deferred_v1"
ACTIVE_PHASES = {
    "reserved", "prepared", "reviewing", "promoted", "finalizing", "archiving", "closed",
}
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
        if not _seed_archive_complete(state):
            if dry_run:
                _print_gate_state(state, continuation=True)
                print("worker_dry_run=1")
                print(json.dumps({"wakeAgent": False}, separators=(",", ":")))
                return 0
            state["phase"] = "promoted"
            state["last_error"] = (
                "closed manifest has incomplete seed archive; retrying close"
            )
            save_state(state)
        else:
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
        "seed_archive": None,
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


def _seed_key(value: Path | str) -> str:
    """Return a stable cross-platform key for a seed path in the manifest."""
    return str(value).replace("\\", "/").lower()


def _archive_result_complete(item: dict[str, Any]) -> bool:
    return item.get("result") in {
        "moved", "already_archived", "reconciled_existing_destination",
    }


def _seed_archive_complete(state: dict[str, Any]) -> bool:
    archive = state.get("seed_archive")
    if not isinstance(archive, dict):
        return False
    if archive.get("status") not in {"complete", "not_applicable"}:
        return False
    items = archive.get("items", [])
    return isinstance(items, list) and all(
        isinstance(item, dict)
        and _archive_result_complete(item)
        and item.get("sha256_before") == item.get("sha256_after_move")
        and bool(item.get("moved_at"))
        for item in items
    )


def _archive_source_path(value: str) -> Path:
    raw = Path(value)
    if not raw.is_absolute():
        raw = ROOT / raw
    if raw.is_symlink():
        raise RuntimeError(f"seed archive source must not be a symlink: {raw}")
    path = raw.resolve()
    try:
        relative = path.relative_to(SEEDS.resolve())
    except ValueError as exc:
        raise ValueError(f"seed archive source is outside seeds/appearance: {value}") from exc
    if not relative.parts or path.suffix.lower() != ".json":
        raise ValueError(f"seed archive source must be a JSON seed: {value}")
    return path


def _archive_destination_path(value: str, run_id: str, source_name: str) -> Path:
    if not run_id or any(separator in run_id for separator in ("/", "\\")):
        raise ValueError("archive run_id is not a safe directory name")
    raw = Path(value)
    if not raw.is_absolute():
        raw = ROOT / raw
    if raw.is_symlink():
        raise RuntimeError(f"seed archive destination must not be a symlink: {raw}")
    path = raw.resolve()
    try:
        relative = path.relative_to(SEED_ARCHIVE.resolve())
    except ValueError as exc:
        raise ValueError(f"seed archive destination is outside seeds/archive: {value}") from exc
    if relative.parts != (run_id, source_name):
        raise ValueError(
            "seed archive destination must be exactly one run directory and the original filename"
        )
    return path


def _archive_profile_key(seed_path: Path, character: str) -> str:
    from scripts.promote_appearance import read_seed, stable_appearance_key

    data = read_seed(seed_path)
    if str(data.get("character_tag")) != character:
        raise ValueError(
            f"seed character_tag {data.get('character_tag')!r} does not match {character!r}"
        )
    profiles = data.get("profiles")
    if not isinstance(profiles, list) or len(profiles) != 1:
        raise ValueError("published seed must contain exactly one profile before archiving")
    profile = profiles[0]
    if not isinstance(profile, dict):
        raise ValueError("published seed profile must be a JSON object before archiving")
    if str(profile.get("status", "published")) != "published":
        raise ValueError("only published seed profiles may be archived")
    variant_tag = str(profile.get("variant_tag") or character)
    return str(profile.get("appearance_key") or stable_appearance_key(character, variant_tag))


def _load_archive_manifest() -> dict[str, Any]:
    if not ARCHIVE_MANIFEST_PATH.exists():
        return {
            "schema_version": 1,
            "policy": "closed_published_seeds_v1",
            "runs": [],
        }
    try:
        value = json.loads(ARCHIVE_MANIFEST_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(
            f"seed archive manifest is not valid JSON: {ARCHIVE_MANIFEST_PATH}: {exc}"
        ) from exc
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise RuntimeError("seed archive manifest has an unsupported schema")
    if not isinstance(value.get("runs"), list) or any(
        not isinstance(run, dict) for run in value["runs"]
    ):
        raise RuntimeError("seed archive manifest runs are malformed")
    return value


def _find_archive_run(manifest: dict[str, Any], run_id: str) -> dict[str, Any] | None:
    matches = [run for run in manifest["runs"] if run.get("run_id") == run_id]
    if len(matches) > 1:
        raise RuntimeError(f"seed archive manifest contains duplicate run_id: {run_id}")
    return matches[0] if matches else None


def _build_archive_plan(
    state: dict[str, Any], canonical: sqlite3.Connection
) -> list[dict[str, Any]]:
    run_id = str(state["run_id"])
    if not run_id or any(separator in run_id for separator in ("/", "\\")):
        raise ValueError("archive run_id is not a safe directory name")
    plan: list[dict[str, Any]] = []
    seen_sources: set[str] = set()
    seen_destinations: set[str] = set()
    for character in state["selected"]:
        decision = state["decisions"][character]
        if decision.get("decision") != "published":
            continue
        raw_seed = decision.get("seed_path")
        if not raw_seed:
            raise RuntimeError(f"published decision has no seed path: {character}")
        source = _archive_source_path(str(raw_seed))
        source_key = _seed_key(source)
        if source_key in seen_sources:
            raise RuntimeError(f"same seed is assigned more than once: {source}")
        seen_sources.add(source_key)
        if not source.is_file():
            raise FileNotFoundError(source)
        appearance_key = _archive_profile_key(source, character)
        canonical_row = canonical.execute(
            """SELECT 1 FROM character_appearance_profiles
               WHERE appearance_key=? AND character_tag=? AND status='published'
               LIMIT 1""",
            (appearance_key, character),
        ).fetchone()
        if canonical_row is None:
            raise RuntimeError(
                "published seed is not present as an exact published canonical profile: "
                f"{character}/{appearance_key}"
            )
        destination = SEED_ARCHIVE / run_id / source.name
        destination_key = _seed_key(destination)
        if destination_key in seen_destinations:
            raise RuntimeError(f"multiple seeds target the same archive destination: {destination}")
        seen_destinations.add(destination_key)
        plan.append({
            "run_id": run_id,
            "batch_number": state["batch_number"],
            "character": character,
            "appearance_key": appearance_key,
            "decision": "published",
            "original_path": str(source),
            "archive_path": str(destination),
            "sha256_before": source_fingerprint(source)["sha256"],
            "sha256_after_move": None,
            "moved_at": None,
            "result": "pending",
        })
    return plan


def _validate_archive_plan_item(
    state: dict[str, Any], item: dict[str, Any], canonical: sqlite3.Connection
) -> tuple[Path, Path]:
    run_id = str(state["run_id"])
    if item.get("run_id") != run_id:
        raise RuntimeError("seed archive plan contains a different run_id")
    if item.get("batch_number") != state["batch_number"]:
        raise RuntimeError("seed archive plan contains a different batch_number")
    if item.get("decision") != "published":
        raise RuntimeError("seed archive plan contains a non-published decision")
    character = str(item.get("character") or "")
    if character not in state["selected"]:
        raise RuntimeError(f"seed archive plan contains an unselected character: {character}")
    decision = state["decisions"].get(character, {})
    if decision.get("decision") != "published":
        raise RuntimeError(f"seed archive plan contains a non-published decision: {character}")
    source = _archive_source_path(str(item.get("original_path") or ""))
    decision_source = _archive_source_path(str(decision.get("seed_path") or ""))
    if _seed_key(source) != _seed_key(decision_source):
        raise RuntimeError(f"seed archive plan does not match the decision seed: {character}")
    destination = _archive_destination_path(
        str(item.get("archive_path") or ""), run_id, source.name
    )
    expected_sha = str(item.get("sha256_before") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha):
        raise RuntimeError(f"seed archive plan has an invalid SHA-256: {source}")
    appearance_key = str(item.get("appearance_key") or "")
    if not appearance_key:
        raise RuntimeError(f"seed archive plan has no appearance_key: {source}")
    canonical_row = canonical.execute(
        """SELECT 1 FROM character_appearance_profiles
           WHERE appearance_key=? AND character_tag=? AND status='published'
           LIMIT 1""",
        (appearance_key, character),
    ).fetchone()
    if canonical_row is None:
        raise RuntimeError(
            "seed archive plan no longer points to an exact published canonical profile: "
            f"{character}/{appearance_key}"
        )
    if source.exists():
        if not source.is_file():
            raise RuntimeError(f"seed archive source is not a regular file: {source}")
        if _archive_profile_key(source, character) != appearance_key:
            raise RuntimeError(f"seed archive source profile changed: {source}")
    return source, destination


def _merge_archive_items(
    plan: list[dict[str, Any]], previous: list[Any]
) -> list[dict[str, Any]]:
    previous_by_source: dict[str, dict[str, Any]] = {}
    for raw_item in previous:
        if not isinstance(raw_item, dict):
            raise RuntimeError("seed archive manifest contains a malformed item")
        source_key = _seed_key(str(raw_item.get("original_path") or ""))
        if not source_key or source_key in previous_by_source:
            raise RuntimeError("seed archive manifest contains duplicate original paths")
        previous_by_source[source_key] = raw_item
    merged: list[dict[str, Any]] = []
    plan_sources = {_seed_key(str(item["original_path"])) for item in plan}
    unexpected = set(previous_by_source) - plan_sources
    if unexpected:
        raise RuntimeError(
            "seed archive manifest contains items absent from the worker plan: "
            f"{sorted(unexpected)}"
        )
    for item in plan:
        prior = previous_by_source.get(_seed_key(str(item["original_path"])))
        if prior is not None:
            for key in ("run_id", "batch_number", "archive_path", "sha256_before"):
                if prior.get(key) != item.get(key):
                    raise RuntimeError(f"seed archive manifest conflicts for {item['original_path']}")
            item = dict(item)
            if _archive_result_complete(prior):
                for key in ("sha256_after_move", "moved_at", "result"):
                    item[key] = prior.get(key)
        merged.append(item)
    return merged


def _archive_one_seed(item: dict[str, Any], source: Path, destination: Path) -> dict[str, Any]:
    expected_sha = str(item["sha256_before"])
    if source.is_symlink():
        raise RuntimeError(f"seed archive source must not be a symlink: {source}")
    if destination.is_symlink():
        raise RuntimeError(f"seed archive destination must not be a symlink: {destination}")
    source_exists = source.exists()
    destination_exists = destination.exists()
    if source_exists and not source.is_file():
        raise RuntimeError(f"seed archive source is not a regular file: {source}")
    if destination_exists and not destination.is_file():
        raise RuntimeError(f"seed archive destination exists but is not a regular file: {destination}")

    if source_exists:
        if source_fingerprint(source)["sha256"] != expected_sha:
            raise RuntimeError(f"seed changed after archive plan was recorded: {source}")
        if destination_exists:
            if source_fingerprint(destination)["sha256"] != expected_sha:
                raise RuntimeError(
                    "seed archive destination exists with a different SHA-256: "
                    f"{destination}"
                )
            result = "reconciled_existing_destination"
        else:
            result = "moved"
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(str(source), str(destination))
    else:
        if not destination_exists:
            raise FileNotFoundError(
                f"seed archive source and destination are both missing: {source}"
            )
        if source_fingerprint(destination)["sha256"] != expected_sha:
            raise RuntimeError(f"seed archive destination SHA-256 mismatch: {destination}")
        result = item.get("result") if _archive_result_complete(item) else "already_archived"

    after_sha = source_fingerprint(destination)["sha256"]
    if after_sha != expected_sha:
        raise RuntimeError(f"SHA-256 changed during seed archive: {destination}")
    updated = dict(item)
    updated["sha256_after_move"] = after_sha
    updated["moved_at"] = item.get("moved_at") or now()
    updated["result"] = result
    return updated


def _archive_seeds_after_close(state: dict[str, Any]) -> dict[str, Any]:
    """Move only this closed run's published seeds into its audited archive."""
    if state.get("phase") not in {"archiving", "closed"}:
        raise RuntimeError(f"cannot archive seeds from phase {state.get('phase')}")
    if _seed_archive_complete(state):
        return state["seed_archive"]

    manifest = _load_archive_manifest()
    run = _find_archive_run(manifest, str(state["run_id"]))
    archive_state = state.get("seed_archive")
    if isinstance(archive_state, dict) and isinstance(archive_state.get("items"), list) and archive_state["items"]:
        plan = [dict(item) for item in archive_state["items"]]
    elif run is not None and isinstance(run.get("items"), list) and run["items"]:
        plan = [dict(item) for item in run["items"]]
    else:
        canonical = _connect_read_only(DB)
        try:
            plan = _build_archive_plan(state, canonical)
        finally:
            canonical.close()

    if not plan:
        result = {
            "policy": "closed_published_seeds_v1",
            "status": "not_applicable",
            "items": [],
            "completed_at": now(),
        }
        state["seed_archive"] = result
        save_state(state)
        if run is not None:
            run["status"] = "complete"
            run["items"] = []
            run["updated_at"] = now()
            run["finished_at"] = result["completed_at"]
            atomic_write_json(ARCHIVE_MANIFEST_PATH, manifest)
        return result

    canonical = _connect_read_only(DB)
    try:
        validated_paths = [
            _validate_archive_plan_item(state, item, canonical) for item in plan
        ]
    finally:
        canonical.close()
    source_keys = {_seed_key(source) for source, _ in validated_paths}
    destination_keys = {_seed_key(destination) for _, destination in validated_paths}
    if len(source_keys) != len(validated_paths) or len(destination_keys) != len(validated_paths):
        raise RuntimeError("seed archive plan contains duplicate source or destination paths")

    archive_state = {
        "policy": "closed_published_seeds_v1",
        "status": "in_progress",
        "items": plan,
        "started_at": (
            archive_state.get("started_at")
            if isinstance(archive_state, dict) else None
        ) or now(),
    }
    state["seed_archive"] = archive_state
    save_state(state)

    if run is None:
        run = {
            "run_id": str(state["run_id"]),
            "batch_number": state["batch_number"],
            "policy": "closed_published_seeds_v1",
            "status": "in_progress",
            "started_at": archive_state["started_at"],
            "items": [],
        }
        manifest["runs"].append(run)
    elif run.get("batch_number") != state["batch_number"]:
        raise RuntimeError("seed archive manifest batch_number conflicts with worker state")
    plan = _merge_archive_items(plan, run.get("items", []))
    archive_state["items"] = plan
    run["items"] = plan
    run["status"] = "in_progress"
    run["updated_at"] = now()
    atomic_write_json(ARCHIVE_MANIFEST_PATH, manifest)

    try:
        for index, item in enumerate(plan):
            source, destination = validated_paths[index]
            plan[index] = _archive_one_seed(item, source, destination)
            archive_state["items"] = plan
            save_state(state)
            run["items"] = plan
            run["updated_at"] = now()
            atomic_write_json(ARCHIVE_MANIFEST_PATH, manifest)
    except Exception as exc:
        archive_state["status"] = "partial"
        archive_state["last_error"] = str(exc)[-1200:]
        save_state(state)
        run["items"] = plan
        run["status"] = "partial"
        run["last_error"] = str(exc)[-1200:]
        run["updated_at"] = now()
        atomic_write_json(ARCHIVE_MANIFEST_PATH, manifest)
        raise

    completed_at = now()
    archive_state["status"] = "complete"
    archive_state["completed_at"] = completed_at
    archive_state.pop("last_error", None)
    run["items"] = plan
    run["status"] = "complete"
    run["updated_at"] = completed_at
    run["finished_at"] = completed_at
    atomic_write_json(ARCHIVE_MANIFEST_PATH, manifest)
    save_state(state)
    return archive_state


def _strict_validate_seeds(state: dict[str, Any]) -> dict[str, Any]:
    """Validate accepted seeds and return per-seed errors without writing."""
    seeds = _accepted_seed_paths(state)
    result: dict[str, Any] = {
        "errors_by_seed": {},
        "metrics_by_seed": {},
    }
    if not seeds:
        return result

    from scripts.validate_general_appearance_batch import load_seed, validate_seed

    current_source = source_fingerprint()
    snapshot = state.get("source_snapshot") or {}
    if (
        snapshot.get("sha256") != current_source["sha256"]
        or str(snapshot.get("size")) != str(current_source["size"])
    ):
        raise RuntimeError(
            "canonical DB fingerprint changed since manifest snapshot; "
            "refusing automatic resolution"
        )

    canonical = _connect_read_only(DB)
    candidates = _connect_read_only(CANDIDATES)
    try:
        metadata = dict(candidates.execute(
            "SELECT key, value FROM appearance_index_metadata"
        ).fetchall())
        expected = current_source
        if metadata.get("source_sha256") != expected["sha256"]:
            raise RuntimeError(
                "candidate database fingerprint mismatch; refusing automatic resolution"
            )
        if metadata.get("source_size") != str(expected["size"]):
            raise RuntimeError(
                "candidate database size mismatch; refusing automatic resolution"
            )
        source_keys = {
            (row[0], row[1], row[2]) for row in canonical.execute(
                "SELECT source_site, source_kind, source_key "
                "FROM character_appearance_sources"
            )
        }
        candidate_keys = {
            (row[0], row[1], row[3]) for row in candidates.execute(
                "SELECT character_tag, variant_tag, facet, canonical_tag "
                "FROM appearance_candidates"
            )
        }
        for seed_path in seeds:
            key = _seed_key(seed_path)
            if not seed_path.is_file():
                result["errors_by_seed"][key] = [
                    f"{seed_path.name}: seed file is missing"
                ]
                result["metrics_by_seed"][key] = {"accepted": 0, "candidates": 0}
                continue
            seed, load_errors = load_seed(seed_path)
            if seed is None:
                errors = load_errors
                metrics = {"accepted": 0, "candidates": 0}
            else:
                errors, metrics = validate_seed(
                    seed_path,
                    seed,
                    canonical,
                    candidates,
                    candidate_keys,
                    source_keys,
                )
            result["errors_by_seed"][key] = errors
            result["metrics_by_seed"][key] = metrics
    finally:
        candidates.close()
        canonical.close()
    return result


def auto_resolve(run_id: str) -> dict[str, Any]:
    """Defer only published seeds rejected by strict validation.

    The original decision and seed path remain in ``auto_resolution`` so a
    reviewer can repair the seed later without losing the audit trail.
    """
    state = _require_state(run_id)
    if state["phase"] not in {"prepared", "reviewing"}:
        raise RuntimeError(f"cannot auto-resolve from phase {state['phase']}")
    _all_decisions(state)
    validation = _strict_validate_seeds(state)
    deferred: list[str] = []
    validated: list[str] = []
    errors_by_seed = {
        _seed_key(key): list(value)
        for key, value in validation["errors_by_seed"].items()
    }

    for character in state["selected"]:
        decision = state["decisions"][character]
        if decision["decision"] != "published":
            continue
        seed_path = Path(decision["seed_path"])
        errors = list(errors_by_seed.get(_seed_key(seed_path), []))
        if not errors:
            validated.append(character)
            continue
        original = dict(decision)
        decision["decision"] = "deferred"
        decision["seed_path"] = None
        decision["reason"] = (
            "auto-deferred by strict validation: " + "; ".join(errors)
        )[:1200]
        decision["auto_resolution"] = {
            "policy": AUTO_DEFER_POLICY,
            "previous_decision": original.get("decision"),
            "previous_seed_path": original.get("seed_path"),
            "errors": errors,
            "resolved_at": now(),
        }
        state.setdefault("auto_resolutions", []).append({
            "character": character,
            "seed_path": original.get("seed_path"),
            "errors": errors,
            "policy": AUTO_DEFER_POLICY,
        })
        deferred.append(character)

    if deferred:
        state["last_error"] = ""
        save_state(state)
    return {
        "run_id": run_id,
        "deferred": deferred,
        "validated": validated,
        "errors_by_seed": errors_by_seed,
    }


def _backup_reconciliation_database(run_id: str) -> Path:
    """Create a uniquely named external SQLite backup before reconciliation."""
    fingerprint = source_fingerprint()
    destination = Path(tempfile.gettempdir()) / (
        f"weeb_general_reconcile_{run_id}_{fingerprint['sha256'][:12]}.sqlite"
    )
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


def _validate_canonical_invariants(metrics: dict[str, Any]) -> None:
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


def _validate_canonical(state: dict[str, Any]) -> dict[str, Any]:
    metrics = _canonical_metrics()
    _validate_canonical_invariants(metrics)
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


def _reconciliation_indexes_fresh() -> bool:
    """Check every derived index against the current canonical fingerprint."""
    expected = source_fingerprint()
    for path, metadata_table in (
        (CANDIDATES, "appearance_index_metadata"),
        (SEARCH_INDEX, "tag_search_metadata"),
        (CONTEXT_INDEX, "context_index_metadata"),
    ):
        if not path.is_file():
            return False
        try:
            con = _connect_read_only(path)
            try:
                metadata = dict(con.execute(
                    f"SELECT key, value FROM {metadata_table}"
                ).fetchall())
            finally:
                con.close()
        except (OSError, sqlite3.Error):
            return False
        if metadata.get("source_sha256") != expected["sha256"]:
            return False
        if metadata.get("source_size") != str(expected["size"]):
            return False
    return True


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


def _reconcile_latest_report(metrics: dict[str, Any]) -> None:
    """Update canonical metrics in the latest close without inventing a batch."""
    if not REPORT.exists():
        raise FileNotFoundError(REPORT)
    existing = REPORT.read_text(encoding="utf-8", errors="replace")
    headings = list(re.finditer(r"^## .+$", existing, re.MULTILINE))
    if not headings:
        raise RuntimeError("appearance report has no section heading")
    start = headings[-1].start()
    prefix = existing[:start]
    section = existing[start:]
    values = {
        "canonical_db_size": str(DB.stat().st_size),
        "canonical_db_sha256": source_fingerprint()["sha256"],
        "canonical_published_profiles": str(metrics["published_profiles"]),
        "canonical_published_features": str(metrics["published_features"]),
        "canonical_all_evidence_links": str(metrics["all_evidence_links"]),
        "canonical_published_evidence_links": str(metrics["published_evidence_links"]),
        "canonical_retired_evidence_links": str(metrics["retired_evidence_links"]),
        "canonical_unjoined_evidence_links": str(metrics["unjoined_evidence_links"]),
    }
    for key, value in values.items():
        section, replacements = re.subn(
            rf"(?m)^{re.escape(key)}=.*$",
            f"{key}={value}",
            section,
            count=1,
        )
        if replacements != 1:
            raise RuntimeError(f"latest report is missing reconciliation metric: {key}")
    atomic_write_text(REPORT, prefix + section)


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
        if _seed_archive_complete(state):
            print("worker_close=already_closed")
            return 0
        state["phase"] = "promoted"
        state["last_error"] = "closed manifest has incomplete seed archive; retrying close"
        save_state(state)
    if state["phase"] not in {"promoted", "finalizing", "archiving"}:
        raise RuntimeError(f"cannot close from phase {state['phase']}")
    _all_decisions(state)
    state["phase"] = "finalizing"
    state["last_error"] = ""
    archive_state = state.get("seed_archive")
    if not _seed_archive_complete(state):
        if isinstance(archive_state, dict):
            archive_state["status"] = "pending"
            archive_state.pop("last_error", None)
            archive_state.setdefault("items", [])
        else:
            state["seed_archive"] = {
                "policy": "closed_published_seeds_v1",
                "status": "pending",
                "items": [],
            }
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
        state["phase"] = "archiving"
        save_state(state)
        state["seed_archive"] = _archive_seeds_after_close(state)
        state["phase"] = "closed"
        save_state(state)
        STATE_PATH.unlink(missing_ok=True)
        print("worker_close=complete")
        print(json.dumps({
            "run_id": run_id,
            "batch_number": state["batch_number"],
            "next_queue": state["next_queue"],
            "canonical_metrics": state["canonical_metrics"],
            "seed_archive": state["seed_archive"],
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


def reconcile_aborted(run_id: str) -> dict[str, Any]:
    """Reconcile an explicitly named aborted run before clearing its lease."""
    state = load_state()
    if state is None:
        raise RuntimeError("no active general appearance worker state")
    if state["run_id"] != run_id:
        raise RuntimeError(
            f"run_id mismatch: active={state['run_id']} supplied={run_id}"
        )
    if state["phase"] != "aborted":
        raise RuntimeError("reconciliation requires an explicitly aborted worker state")
    if state.get("promotion") is not None or state.get("canonical_after_promotion"):
        raise RuntimeError("aborted state contains promotion data; refusing reconciliation")

    original = json.loads(json.dumps(state))
    before = source_fingerprint()
    backup = _backup_reconciliation_database(run_id)
    state["phase"] = "reconciling"
    state["reconciliation"] = {
        "policy": "external_backup_indexes_report_runtime_v1",
        "before": before,
        "backup_path": str(backup),
        "database_mutated": False,
    }
    state["last_error"] = ""
    save_state(state)
    cleared = False
    try:
        metrics = _canonical_metrics()
        _validate_canonical_invariants(metrics)
        state["canonical_metrics"] = metrics
        save_state(state)

        state["candidate_final"] = _build_derived(state)
        state["mcp_probe"] = _probe_runtime(state)
        after = source_fingerprint()
        if after != before:
            raise RuntimeError("canonical database changed during reconciliation")
        _reconcile_latest_report(metrics)
        if not _reconciliation_indexes_fresh():
            raise RuntimeError("derived indexes are not fresh after reconciliation")

        verified_metrics = _canonical_metrics()
        _validate_canonical_invariants(verified_metrics)
        verified_after = source_fingerprint()
        if verified_after != before:
            raise RuntimeError("canonical database changed during reconciliation verification")
        state["canonical_metrics"] = verified_metrics
        state["reconciliation"]["after"] = verified_after
        state["reconciliation"]["status"] = "ready_to_clear"
        state["phase"] = "aborted"
        save_state(state)

        clear(run_id)
        cleared = True
        ready, output = _preflight()
        print(output)
        if not ready:
            raise RuntimeError("preflight did not return READY after reconciliation")
        result = {
            "run_id": run_id,
            "backup_path": str(backup),
            "database_mutated": False,
            "canonical_metrics": verified_metrics,
            "preflight_ready": True,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return result
    except Exception as exc:
        current = load_state()
        restored = current if current and current.get("run_id") == run_id else original
        restored["phase"] = "aborted"
        restored["last_error"] = f"reconciliation failed: {exc}"[-1200:]
        if current is None or current.get("run_id") != run_id:
            create_state_exclusive(restored)
        else:
            save_state(restored)
        raise


def tick(*, dry_run: bool = False) -> int:
    """Run the deterministic continuation policy used by the cron shim."""
    state = load_state()
    if state is None:
        return gate(dry_run=dry_run)
    phase = state["phase"]
    if dry_run:
        _print_gate_state(state, continuation=True)
        print("worker_dry_run=1")
        print(json.dumps({"wakeAgent": False}, separators=(",", ":")))
        return 0
    if phase == "aborted":
        _print_gate_state(state, continuation=True)
        print("worker_gate=aborted_requires_explicit_reconcile")
        print(json.dumps({"wakeAgent": False}, separators=(",", ":")))
        return 0
    if phase == "reconciling":
        _print_gate_state(state, continuation=True)
        print("worker_gate=reconciliation_in_progress")
        print(json.dumps({"wakeAgent": False}, separators=(",", ":")))
        return 0
    if phase == "reserved":
        _print_gate_state(state, continuation=True)
        print("worker_tick=awaiting_prepare_and_review")
        print(json.dumps({"wakeAgent": True}, separators=(",", ":")))
        return 0
    if phase in {"prepared", "reviewing"}:
        try:
            _all_decisions(state)
        except RuntimeError as exc:
            _print_gate_state(state, continuation=True)
            print(f"worker_tick=awaiting_decisions: {exc}")
            print(json.dumps({"wakeAgent": True}, separators=(",", ":")))
            return 0
        resolution = auto_resolve(state["run_id"])
        print(json.dumps(resolution, ensure_ascii=False, indent=2, sort_keys=True))
        publish(state["run_id"])
        return close(state["run_id"])
    if phase in {"promoted", "finalizing", "archiving"}:
        return close(state["run_id"])
    if phase == "closed":
        return gate()
    raise RuntimeError(f"unsupported worker phase for tick: {phase}")


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
    actions.add_argument("--tick", action="store_true")
    actions.add_argument("--auto-resolve", action="store_true")
    actions.add_argument("--reconcile-aborted", action="store_true")
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
    elif args.tick:
        action = "tick"
    elif args.auto_resolve:
        action = "auto-resolve"
    elif args.reconcile_aborted:
        action = "reconcile-aborted"

    try:
        if action == "gate":
            return gate(dry_run=args.dry_run)
        if action == "status":
            return status()
        if action == "tick":
            return tick(dry_run=args.dry_run)
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
        if action == "auto-resolve":
            print(json.dumps(
                auto_resolve(args.run_id),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ))
            return 0
        if action == "reconcile-aborted":
            reconcile_aborted(args.run_id)
            return 0
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
