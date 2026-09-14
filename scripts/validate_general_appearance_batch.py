#!/usr/bin/env python3
"""Validate an appearance batch without writing either database.

The validator is intentionally stricter than the legacy seed checker. A seed
may only be promoted when its source excerpts are literal slices of the raw
wiki bodies and every accepted feature pair exists in the candidate projection
built from the same canonical database snapshot.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def connect_ro(path: Path) -> sqlite3.Connection:
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    con = sqlite3.connect(uri, uri=True, timeout=15)
    con.execute("PRAGMA busy_timeout=15000")
    con.row_factory = sqlite3.Row
    return con


def parse_source_ref(value: str) -> tuple[str, str, str] | None:
    parts = value.split(":", 2)
    if len(parts) != 3 or not all(parts):
        return None
    return parts[0], parts[1], parts[2]


def load_seed(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return None, [f"{path.name}: JSON_PARSE: {exc}"]
    if not isinstance(value, dict):
        return None, [f"{path.name}: seed root is not an object"]
    return value, []


def source_body(
    con: sqlite3.Connection, site: str, key: str,
) -> str | None:
    row = con.execute(
        "SELECT body FROM wiki WHERE site=? AND title=?", (site, key)
    ).fetchone()
    return None if row is None else (row[0] or "")


def validate_seed(
    seed_path: Path,
    seed: dict[str, Any],
    canonical: sqlite3.Connection,
    candidates: sqlite3.Connection,
    candidate_keys: set[tuple[str, str, str]],
    source_keys: set[tuple[str, str, str]],
) -> tuple[list[str], dict[str, int]]:
    errors: list[str] = []
    character = str(seed.get("character_tag", ""))
    profiles = seed.get("profiles")
    if not character or not isinstance(profiles, list) or len(profiles) != 1:
        return [f"{seed_path.name}: profile shape invalid"], {"accepted": 0, "candidates": 0}

    profile = profiles[0]
    appearance_key = str(profile.get("appearance_key", ""))
    variant = str(profile.get("variant_tag") or character)
    appearance_kind = str(profile.get("appearance_kind", ""))
    expected_suffix = "default" if appearance_kind == "default" else variant
    if appearance_key != f"{character}::{expected_suffix}":
        errors.append(
            f"{seed_path.name}: appearance_key mismatch: {appearance_key!r}"
        )

    feature_pairs: set[tuple[str, str]] = set()
    features = profile.get("features")
    if not isinstance(features, list):
        errors.append(f"{seed_path.name}: features is not a list")
        features = []
    for index, feature in enumerate(features):
        if not isinstance(feature, dict):
            errors.append(f"{seed_path.name}: feature[{index}] is not an object")
            continue
        pair = (str(feature.get("facet", "")), str(feature.get("canonical_tag", "")))
        if not all(pair):
            errors.append(f"{seed_path.name}: feature[{index}] missing facet/tag")
            continue
        if pair in feature_pairs:
            errors.append(f"{seed_path.name}: duplicate feature {pair[0]}/{pair[1]}")
        feature_pairs.add(pair)
        if (character, variant, pair[1]) not in candidate_keys:
            errors.append(
                f"{seed_path.name}: CANDIDATE_FAIL {pair[0]}/{pair[1]}"
            )

        refs = feature.get("source_refs") or []
        if not refs:
            errors.append(f"{seed_path.name}: feature {pair[1]} has no source_refs")
        for ref in refs:
            parsed = parse_source_ref(str(ref))
            if parsed is None:
                errors.append(f"{seed_path.name}: bad source_ref {ref!r}")
                continue
            if parsed not in source_keys:
                errors.append(f"{seed_path.name}: source_ref not in DB {ref!r}")

    seed_sources = seed.get("sources") or []
    for source in seed_sources:
        if not isinstance(source, dict):
            errors.append(f"{seed_path.name}: source is not an object")
            continue
        site = str(source.get("source_site", ""))
        kind = str(source.get("source_kind", ""))
        key = str(source.get("source_key", ""))
        excerpt = str(source.get("excerpt", ""))
        if (site, kind, key) not in source_keys:
            errors.append(f"{seed_path.name}: source not in DB {site}:{kind}:{key}")
            continue
        body = source_body(canonical, site, key)
        if body is None:
            errors.append(f"{seed_path.name}: EXCERPT_FAIL missing wiki body {site}:{key}")
        elif not excerpt or excerpt not in body:
            errors.append(f"{seed_path.name}: EXCERPT_FAIL {site}:{key}")

    candidate_count = candidates.execute(
        "SELECT count(*) FROM appearance_candidates "
        "WHERE character_tag=? AND variant_tag=?", (character, variant)
    ).fetchone()[0]
    return errors, {"accepted": len(feature_pairs), "candidates": int(candidate_count)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=ROOT / "tag_library.db")
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--seed", type=Path, action="append", required=True)
    args = parser.parse_args()

    if not args.db.is_file() or not args.candidates.is_file():
        print("ERROR missing --db or --candidates", file=sys.stderr)
        return 2

    canonical_hash = sha256_file(args.db)
    canonical_size = args.db.stat().st_size
    canonical = connect_ro(args.db)
    candidates = connect_ro(args.candidates)
    try:
        metadata = dict(candidates.execute(
            "SELECT key, value FROM appearance_index_metadata"
        ).fetchall())
        if metadata.get("source_sha256") != canonical_hash:
            print(
                "ERROR candidate fingerprint mismatch: "
                f"expected={canonical_hash} actual={metadata.get('source_sha256', '[missing]')}"
            )
            return 1
        if metadata.get("source_size") != str(canonical_size):
            print(
                "ERROR candidate size mismatch: "
                f"expected={canonical_size} actual={metadata.get('source_size', '[missing]')}"
            )
            return 1

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
        total_errors = 0
        totals = {"accepted": 0, "candidates": 0}
        for seed_path in sorted(args.seed):
            seed, errors = load_seed(seed_path)
            metrics = {"accepted": 0, "candidates": 0}
            if seed is not None:
                errors, metrics = validate_seed(
                    seed_path, seed, canonical, candidates,
                    candidate_keys, source_keys,
                )
            totals = {
                key: totals[key] + metrics[key] for key in totals
            }
            total_errors += len(errors)
            label = "FAIL" if errors else "OK"
            print(
                f"{label} {seed_path.name} "
                f"accepted={metrics['accepted']} candidates={metrics['candidates']}"
            )
            for error in errors:
                print(f"  - {error}")
        print(
            f"summary seeds={len(args.seed)} accepted={totals['accepted']} "
            f"candidate_rows={totals['candidates']} errors={total_errors}"
        )
        return 1 if total_errors else 0
    finally:
        candidates.close()
        canonical.close()


if __name__ == "__main__":
    raise SystemExit(main())
