#!/usr/bin/env python3
"""Batch-validate appearance seeds before promotion.

Checks:
- JSON parse
- one profile per seed with coherent keys
- unique (facet, canonical_tag) within each profile
- every canonical_tag in appearance_feature_catalog
- every facet in appearance_facet_catalog
- every source_ref resolvable in character_appearance_sources
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from weeb_alexandria_mcp.appearance_schema import normalize_tag  # noqa: E402

DB = ROOT / "tag_library.db"
SEEDS = ROOT / "seeds" / "appearance"

db = sqlite3.connect(str(DB))
cur = db.cursor()

cur.execute("SELECT canonical_tag FROM appearance_feature_catalog")
catalog = {normalize_tag(r[0]) for r in cur.fetchall()}

cur.execute("SELECT facet_key FROM appearance_facet_catalog WHERE status='active'")
facets = {normalize_tag(r[0]) for r in cur.fetchall()}

cur.execute(
    "SELECT source_site, source_kind, source_key FROM character_appearance_sources"
)
src_set = {
    (normalize_tag(r[0]), normalize_tag(r[1]), r[2])
    for r in cur.fetchall()
}
db.close()


def validate_seed(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        errors.append(f"JSON_PARSE: {e}")
        return errors

    char = data.get("character_tag")
    if not char:
        errors.append("missing character_tag")
        return errors

    profiles = data.get("profiles")
    if not isinstance(profiles, list) or not profiles:
        errors.append("missing/empty profiles")
        return errors
    if len(profiles) != 1:
        errors.append("seed must have exactly one profile")

    profile = profiles[0]
    key = profile.get("appearance_key")
    variant = normalize_tag(profile.get("variant_tag") or char)
    if not key:
        errors.append("missing appearance_key")
    if normalize_tag(char) != normalize_tag(key.split("::", 1)[0]):
        errors.append(f"appearance_key prefix != character_tag: {key} vs {char}")
    if variant != normalize_tag(profile.get("variant_tag", "")):
        pass

    features = profile.get("features")
    if not isinstance(features, list):
        errors.append("features not a list")
        return errors

    seen: set[tuple[str, str]] = set()
    for i, f in enumerate(features):
        if not isinstance(f, dict):
            errors.append(f"feature[{i}] not dict")
            continue
        facet = normalize_tag(f.get("facet", ""))
        ctag = normalize_tag(f.get("canonical_tag", ""))
        if not facet:
            errors.append(f"feature[{i}] missing facet")
        if not ctag:
            errors.append(f"feature[{i}] missing canonical_tag")
        if (facet, ctag) in seen:
            errors.append(f"duplicate feature: {facet}/{ctag}")
        seen.add((facet, ctag))
        if ctag and ctag not in catalog:
            errors.append(f"catalog miss: {ctag}")
        if facet and facet not in facets:
            errors.append(f"facet miss: {facet}")

    for ref in profile.get("source_refs", []) or []:
        pass

    for s in data.get("sources", []) or []:
        rs = normalize_tag(s.get("source_site", ""))
        rk = s.get("source_kind", "")
        rk = normalize_tag(rk) if rk else ""
        key_ = s.get("source_key", "")
        if (rs, rk, key_) not in src_set:
            errors.append(f"source not in DB: {rs}:{rk}:{key_}")

    for f in features:
        for ref in f.get("source_refs", []) or []:
            parts = ref.split(":", 2)
            if len(parts) != 3:
                errors.append(f"bad source_ref shape: {ref}")
                continue
            rs, rk, key_ = normalize_tag(parts[0]), normalize_tag(parts[1]), parts[2]
            if (rs, rk, key_) not in src_set:
                errors.append(f"source_ref not in DB: {ref}")

    return errors


def main() -> int:
    seed_paths = sorted(SEEDS.glob("*.json"))
    print(f"validating {len(seed_paths)} seeds")
    total_errors = 0
    for p in seed_paths:
        errs = validate_seed(p)
        if errs:
            total_errors += len(errs)
            print(f"\nFAIL {p.name}")
            for e in errs:
                print(f"  - {e}")
        else:
            print(f"ok {p.name}")
    print(f"\nerrors: {total_errors}")
    return 1 if total_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
