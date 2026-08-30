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
    "samus_aran", "akemi_homura_(magical_girl)",
    "zhongli_(genshin_impact)", "doctor_(arknights)",
    "aerith_gainsborough", "amiya_(arknights)",
    "yasaka_kanako", "mona_(genshin_impact)", "yagokoro_eirin",
    "jeanne_d&#039;arc_(fate)", "kagiyama_hina", "manjuu_(azur_lane)",
    "misty_(pokemon)",
    "akiyama_mio", "nishizumi_miho",
    "mari_(blue_archive)", "aris_(blue_archive)",
    "daiyousei", "nishikino_maki",
    "asuka_langley_souryuu", "kazusa_(blue_archive)",
    "fate_testarossa", "kinomoto_sakura",
    "kayoko_(blue_archive)", "maribel_hearn", "yazawa_nico",
    "manhattan_cafe_(umamusume)", "keqing_(genshin_impact)",
    "morrigan_aensland",
    "yuzuki_yukari", "wanderer_(genshin_impact)", "zuikaku_(kancolle)",
    "toyosatomimi_no_miko", "producer_(idolmaster)", "onozuka_komachi",
    "shanghai_doll", "kafuu_chino", "sonoda_umi", "astolfo_(fate)",
    "monkey_d._luffy", "midoriya_izuku", "ayase_eli",
    "shuten_douji_(fate)", "texas_(arknights)", "mononobe_no_futo",
    "hyuuga_hinata", "watanabe_you", "kirby", "okita_souji_(fate)",
    "kamisato_ayaka", "ash_ketchum", "uzumaki_naruto", "ellen_joe",
    "shibuya_rin", "jeanne_d&#039;arc_alter_(fate)", "serval_(kemono_friends)",
    "shigure_kai_ni_(kancolle)", "nagato_yuki", "march_7th_(honkai:_star_rail)",
    "mirko", "haruno_sakura", "anya_(spy_x_family)", "takamachi_nanoha",
    "kafka_(honkai:_star_rail)",
    "amatsukaze_(kancolle)", "tomoe_mami_(magical_girl)", "peach_(mario)",
    "kitagawa_marin", "son_goku", "arona_(blue_archive)", "kyubey",
    "daiwa_scarlet_(umamusume)", "minami_kotori", "suletta_mercury",
    "klee_(genshin_impact)", "noa_(blue_archive)", "yamato_(kancolle)",
    "himekaidou_hatate",
    "aru_(blue_archive)", "tsukino_usagi", "infection_monitor_(arknights)",
    "tartaglia_(genshin_impact)", "gold_ship_(umamusume)", "trainer_(umamusume)",
    "ijichi_nijika", "denji_(chainsaw_man)", "shenhe_(genshin_impact)",
    "oshino_shinobu", "darjeeling_(girls_und_panzer)", "ibaraki_kasen",
    "skadi_(arknights)", "jalter", "asuna_(sao)", "kiana_kaslana",
    "mordred_(fate)", "reze_(chainsaw_man)",
    "tamamo_(fate)", "saotome_ranma", "oyama_mahiro",
    "ninomae_ina&#039;nis", "morichika_rinnosuke",
    "nishizumi_maho", "momoi_(blue_archive)", "hoshii_miki",
    "togawa_sakiko", "iono_(pokemon)", "miorine_rembran", "saber_alter",
    "eevee", "yuudachi_kai_ni_(kancolle)", "lappland_(arknights)",
    "kasodani_kyouko", "jeanne_d'arc_alter_(fate)", "nagae_iku",
    "ikari_shinji", "murasa_minamitsu", "yoko_littner",
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
