#!/usr/bin/env python3
"""Inventory and quarantine confirmed one-shot repository scripts.

The allowlist is intentionally closed. This command never deletes files and
never considers databases, indexes, seeds, backups, manifests, or evidence.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_QUARANTINE_PARENT = Path(tempfile.gettempdir())

# These files are historical repair/debug helpers, not runtime entry points.
# Keep this list exact: a broad ``temp*.py`` glob could catch future tooling.
CONFIRMED_ONE_SHOT = (
    "_append_report_52.py",
    "check_fingerprint.py",
    "fix_state.py",
    "temp_fix_final.py",
    "temp_fix_matsuura.py",
    "temp_fix_seeds.py",
    "temp_fix_seeds_v2.py",
    "temp_fix_seeds_v3.py",
    "temp_verify_kitsan.py",
    "tmp_excerpt_check.py",
    "tmp_fix_seeds_v4.py",
    "tmp_inspect_candidates.py",
    "tmp_inspect_candidates2.py",
    "tmp_inspect_derived.py",
    "tmp_inspect_full.py",
    "tmp_inspect_sources.py",
    "scripts/_complete_close_b53.py",
    "scripts/_gen_batch51_seeds.py",
    "scripts/_reanimate_batch51.py",
    "scripts/_register_batch51_sources.py",
    "scripts/_sha_taglib.py",
    "scripts/_update_batch51_sources.py",
    "scripts/batch51_build_seeds.py",
    "scripts/populate_and_seed_batch42.py",
    "scripts/promote_batch42.py",
)

# Confirmed disposable artifacts from the same ad-hoc investigation. They are
# quarantined, not deleted, because the text dump may still be useful for audit.
CONFIRMED_TEMPORARY_ARTIFACTS = (
    "appearance.sqlite",
    "tmp_wiki_dump.txt",
)

ALL_CONFIRMED = frozenset(
    (*CONFIRMED_ONE_SHOT, *CONFIRMED_TEMPORARY_ARTIFACTS)
)


def _relative(root: Path, value: str) -> tuple[str, Path]:
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"allowlisted path is not repository-relative: {value}")
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"allowlisted path escapes repository: {value}") from exc
    return relative.as_posix(), candidate


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _classification(relative_path: str) -> tuple[str, str]:
    if relative_path in CONFIRMED_ONE_SHOT:
        return "legacy_one_shot", "historical repair or batch-specific helper"
    return "temporary_artifact", "confirmed disposable investigation artifact"


def inventory(root: Path = ROOT) -> list[dict[str, Any]]:
    """Return only existing regular files from the closed allowlist."""
    root = root.resolve()
    entries: list[dict[str, Any]] = []
    for raw_relative in sorted(ALL_CONFIRMED):
        relative_path, path = _relative(root, raw_relative)
        if path.is_symlink() or not path.is_file():
            continue
        classification, reason = _classification(relative_path)
        entries.append({
            "relative_path": relative_path,
            "classification": classification,
            "reason": reason,
            "size": path.stat().st_size,
            "sha256": _sha256(path),
        })
    return entries


def _assert_external(root: Path, quarantine: Path) -> None:
    try:
        quarantine.relative_to(root)
    except ValueError:
        return
    raise ValueError("quarantine must be outside the repository")


def apply_quarantine(
    root: Path, quarantine: Path, entries: list[dict[str, Any]]
) -> Path:
    """Move an inventory to a fresh external quarantine and write its manifest."""
    root = root.resolve()
    quarantine = quarantine.resolve()
    _assert_external(root, quarantine)
    if quarantine.exists():
        raise FileExistsError(f"quarantine already exists: {quarantine}")
    quarantine.mkdir(parents=True, exist_ok=False)

    moved: list[dict[str, Any]] = []
    manifest_path = quarantine / "manifest.json"
    try:
        for entry in entries:
            relative_path = str(entry["relative_path"])
            if relative_path not in ALL_CONFIRMED:
                raise ValueError(f"entry is not allowlisted: {relative_path}")
            _, source = _relative(root, relative_path)
            if source.is_symlink() or not source.is_file():
                raise FileNotFoundError(source)
            before_sha = _sha256(source)
            if before_sha != entry["sha256"]:
                raise RuntimeError(f"file changed after inventory: {relative_path}")
            destination = quarantine / Path(relative_path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))
            after_sha = _sha256(destination)
            if after_sha != before_sha:
                raise RuntimeError(f"SHA-256 changed during quarantine: {relative_path}")
            moved.append({
                **entry,
                "quarantine_path": str(destination),
                "sha256_after_move": after_sha,
            })
    except BaseException as exc:
        partial = {
            "schema_version": 1,
            "status": "partial",
            "root": str(root),
            "quarantine": str(quarantine),
            "moved": moved,
            "error": f"{type(exc).__name__}: {exc}",
        }
        manifest_path.write_text(
            json.dumps(partial, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        raise

    manifest = {
        "schema_version": 1,
        "status": "complete",
        "root": str(root),
        "quarantine": str(quarantine),
        "moved": moved,
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--quarantine", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    entries = inventory(root)
    result: dict[str, Any] = {
        "root": str(root),
        "allowlisted_paths": sorted(ALL_CONFIRMED),
        "inventory": entries,
    }
    if args.apply:
        quarantine = args.quarantine
        if quarantine is None:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            quarantine = DEFAULT_QUARANTINE_PARENT / f"weeb_alexandria_script_quarantine_{stamp}"
        manifest_path = apply_quarantine(root, quarantine, entries)
        result["manifest"] = str(manifest_path)
        result["moved"] = len(entries)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
