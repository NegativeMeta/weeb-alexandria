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
EXCLUDED = {
    "remilia_scarlet", "miku_hatsune", "sensei_(blue_archive)",
    "admiral_(kancolle)", "fujiwara_no_mokou", "saigyouji_yuyuko",
    "konpaku_youmu_(ghost)", "rumia", "reiuji_utsuho",
    "warrior_of_light_(ff14)",
    "scaramouche_(genshin_impact)", "doodle_sensei_(blue_archive)",
    "tatara_kogasa", "hinanawi_tenshi", "trailblazer_(honkai:_star_rail)",
    "pikachu", "inkling_player_character",
    "kamishirasawa_keine", "houraisan_kaguya",
    "ibuki_suika", "koakuma",
    "cloud_strife", "artoria_pendragon_(saber)_(fate)",
    "aether_(genshin_impact)", "princess_peach", "inkling_girl",
    "illyasviel_von_einzbern", "chun-li",
    "nero_claudius_(fate)", "houjuu_nue",
    "ayanami_rei", "hijiri_byakuren",
}


def rank(db: Path, limit: int) -> list[dict[str, int | str]]:
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    published = {r[0] for r in con.execute(
        "SELECT character_tag FROM character_appearance_profiles WHERE status='published'"
    )}
    aliases_to_published = {
        r[0] for r in con.execute(
            "SELECT antecedent_name FROM tag_aliases "
            "WHERE status='active' AND consequent_name IN (%s)" %
            ",".join("?" for _ in published), tuple(published)
        )
    } if published else set()
    excluded_names = EXCLUDED | aliases_to_published
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row in con.execute(
        "SELECT site, name, post_count FROM tags "
        "WHERE category_name='character' AND site IN ('danbooru','gelbooru','e621')"
    ):
        counts[row["name"]][row["site"]] += int(row["post_count"] or 0)

    result = []
    for name, sites in counts.items():
        if name in excluded_names or name in published or normalize_tag(name) in published:
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
