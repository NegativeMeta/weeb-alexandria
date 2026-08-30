#!/usr/bin/env python3
"""Normalize legacy facet names in appearance seed JSON files."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from weeb_alexandria_mcp.appearance_schema import (  # noqa: E402
    DEFAULT_FACETS,
    canonical_facet,
    infer_facet,
    normalize_tag,
)

DEFAULT_SEEDS = ROOT / "seeds" / "appearance"
_LEGACY_FACETS = {
    "hair_style": "hair",
    "neckwear": "neck",
    "anatomy": "body",
    "armor": "upper_body",
    "chest": "body",
    "halo": "headwear",
    "eyewear": "face",
    "occupation": "context",
    "identity": "context",
    "ability": "context",
    "outfit": "context",
    "expression": "expression",
}


def seed_facet(raw_facet: str, tag: str) -> str:
    facet = normalize_tag(raw_facet)
    canonical_tag = normalize_tag(tag)
    if facet in DEFAULT_FACETS:
        return canonical_facet(facet, canonical_tag)
    if facet in _LEGACY_FACETS:
        return _LEGACY_FACETS[facet]
    if facet == "clothing":
        return infer_facet(canonical_tag) or "dress"
    raise ValueError(f"unknown seed facet {raw_facet!r} for {canonical_tag!r}")


def normalize_seed(path: Path) -> int:
    data = json.loads(path.read_text(encoding="utf-8"))
    changed = 0
    for profile in data.get("profiles", []):
        for feature in profile.get("features", []):
            old = feature.get("facet", "")
            new = seed_facet(str(old), str(feature.get("canonical_tag", "")))
            if old != new:
                feature["facet"] = new
                changed += 1
    if changed:
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return changed


def normalize_directory(directory: Path) -> dict[str, int]:
    totals = {"files": 0, "changed_files": 0, "facet_changes": 0}
    for path in sorted(directory.glob("*.json")):
        totals["files"] += 1
        changes = normalize_seed(path)
        totals["facet_changes"] += changes
        if changes:
            totals["changed_files"] += 1
    return totals


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds-dir", type=Path, default=DEFAULT_SEEDS)
    args = parser.parse_args()
    for key, value in normalize_directory(args.seeds_dir).items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
