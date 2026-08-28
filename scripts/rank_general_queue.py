#!/usr/bin/env python3
"""Rank the general appearance queue using independent booru post counts."""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import defaultdict
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from weeb_alexandria_mcp.appearance_schema import normalize_tag  # noqa: E402

SITES = ("danbooru", "gelbooru", "e621")
EXCLUDED = {"remilia_scarlet", "miku_hatsune", "sensei_(blue_archive)", "admiral_(kancolle)"}


def rank(db: Path, limit: int) -> list[dict[str, int | str]]:
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    published = {r[0] for r in con.execute(
        "SELECT character_tag FROM character_appearance_profiles WHERE status='published'"
    )}
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row in con.execute(
        "SELECT site, name, post_count FROM tags "
        "WHERE category_name='character' AND site IN ('danbooru','gelbooru','e621')"
    ):
        counts[row["name"]][row["site"]] += int(row["post_count"] or 0)

    result = []
    for name, sites in counts.items():
        if name in EXCLUDED or name in published or normalize_tag(name) in published:
            continue
        low = name.lower()
        if any(token in low for token in ("hololive", "_costume", "_(cosplay)")):
            continue
        body = " ".join((r[0] or "").lower() for r in con.execute(
            "SELECT body FROM wiki WHERE title=? AND lang='en'", (name,)
        ))
        if "hololive" in body and ("staff" in body or "virtual youtuber" in body):
            continue
        values = {site: sites.get(site, 0) for site in SITES}
        result.append({"name": name, **values, "total": sum(values.values())})
    con.close()
    return sorted(result, key=lambda row: (-int(row["total"]), str(row["name"])))[:limit]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=ROOT / "tag_library.db")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    print(json.dumps(rank(args.db, args.limit), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
