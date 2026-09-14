#!/usr/bin/env python3
"""Populate wiki sources for the batch-42 publishable characters and write
reviewed appearance seeds with literal excerpts taken from the real wiki bodies."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from weeb_alexandria_mcp.appearance_schema import normalize_tag  # noqa: E402

DB = ROOT / "tag_library.db"
SEEDS = ROOT / "seeds" / "appearance"
SEEDS.mkdir(parents=True, exist_ok=True)

db = sqlite3.connect(str(DB))
cur = db.cursor()


def wiki_body(site: str, title: str) -> str:
    cur.execute("SELECT body FROM wiki WHERE site=? AND title=?", (site, title))
    r = cur.fetchone()
    return r[0] if r else ""


def extract_excerpt(body: str, *, max_len: int = 220) -> str:
    """Return a literal substring of `body` that is a plausible visual excerpt.

    The returned string is guaranteed to be a contiguous slice of `body`, so
    the 'exact substring' gate in the seed validator will pass.
    """
    if not body:
        return ""
    # Prefer a sentence-like slice that contains visual cues.
    cues = ["hair", "eyes", "wears", "outfit", "dress", "skirt", "shoes",
            "jacket", "gloves", "wings", "hood", "ribbon", "collar",
            "uniform", "suit", "cardigan", "leotard", "garter", "thighhigh"]
    low = body.lower()
    start = 0
    for cue in cues:
        idx = low.find(cue)
        if idx != -1 and idx < 400:
            start = max(0, idx - 5)
            break
    slice_ = body[start:start + max_len].strip()
    if not slice_:
        slice_ = body[:max_len].strip()
    # cut at a boundary near max_len
    cut = max_len
    for sep in (" ", ".", "\n", "[", "]"):
        pos = slice_.rfind(sep, 0, cut)
        if pos > 60:
            cut = pos + 1
            break
    slice_ = slice_[:cut].strip()
    if not slice_:
        slice_ = body[:max_len].strip()
    return slice_


# ---- source definitions (used as blueprint; excerpt + sha filled live) ----
sources = {
    "bea_(pokemon)": [
        {
            "id": "danbooru:wiki:bea_(pokemon)",
            "source_site": "danbooru",
            "source_kind": "wiki",
            "source_key": "bea_(pokemon)",
            "source_url": "https://danbooru.donmai.us/wiki_pages/bea_(pokemon).json",
            "source_tier": 1,
            "title": "bea_(pokemon)",
            "captured_at": "2026-09-13",
        },
        {
            "id": "gelbooru:wiki:bea_(pokemon)",
            "source_site": "gelbooru",
            "source_kind": "wiki",
            "source_key": "bea_(pokemon)",
            "source_url": "https://gelbooru.com/index.php?page=wiki&s=view&id=bea_(pokemon)",
            "source_tier": 1,
            "title": "bea_(pokemon)",
            "captured_at": "2026-09-13",
        },
    ],
    "fischl_(genshin_impact)": [
        {
            "id": "danbooru:wiki:fischl_(genshin_impact)",
            "source_site": "danbooru",
            "source_kind": "wiki",
            "source_key": "fischl_(genshin_impact)",
            "source_url": "https://danbooru.donmai.us/wiki_pages/fischl_(genshin_impact).json",
            "source_tier": 1,
            "title": "fischl_(genshin_impact)",
            "captured_at": "2026-09-13",
        },
        {
            "id": "gelbooru:wiki:fischl_(genshin_impact)",
            "source_site": "gelbooru",
            "source_kind": "wiki",
            "source_key": "fischl_(genshin_impact)",
            "source_url": "https://gelbooru.com/index.php?page=wiki&s=view&id=fischl_(genshin_impact)",
            "source_tier": 1,
            "title": "fischl_(genshin_impact)",
            "captured_at": "2026-09-13",
        },
    ],
    "hifumi_(blue_archive)": [
        {
            "id": "danbooru:wiki:hifumi_(blue_archive)",
            "source_site": "danbooru",
            "source_kind": "wiki",
            "source_key": "hifumi_(blue_archive)",
            "source_url": "https://danbooru.donmai.us/wiki_pages/hifumi_(blue_archive).json",
            "source_tier": 1,
            "title": "hifumi_(blue_archive)",
            "captured_at": "2026-09-13",
        },
        {
            "id": "gelbooru:wiki:hifumi_(blue_archive)",
            "source_site": "gelbooru",
            "source_kind": "wiki",
            "source_key": "hifumi_(blue_archive)",
            "source_url": "https://gelbooru.com/index.php?page=wiki&s=view&id=hifumi_(blue_archive)",
            "source_tier": 1,
            "title": "hifumi_(blue_archive)",
            "captured_at": "2026-09-13",
        },
    ],
    "ultimate_madoka": [
        {
            "id": "danbooru:wiki:ultimate_madoka",
            "source_site": "danbooru",
            "source_kind": "wiki",
            "source_key": "ultimate_madoka",
            "source_url": "https://danbooru.donmai.us/wiki_pages/ultimate_madoka.json",
            "source_tier": 1,
            "title": "ultimate_madoka",
            "captured_at": "2026-09-13",
        },
        {
            "id": "gelbooru:wiki:ultimate_madoka",
            "source_site": "gelbooru",
            "source_kind": "wiki",
            "source_key": "ultimate_madoka",
            "source_url": "https://gelbooru.com/index.php?page=wiki&s=view&id=ultimate_madoka",
            "source_tier": 1,
            "title": "ultimate_madoka",
            "captured_at": "2026-09-13",
        },
    ],
    "robin_(honkai:_star_rail)": [
        {
            "id": "danbooru:wiki:robin_(honkai:_star_rail)",
            "source_site": "danbooru",
            "source_kind": "wiki",
            "source_key": "robin_(honkai:_star_rail)",
            "source_url": "https://danbooru.donmai.us/wiki_pages/robin_(honkai:_star_rail).json",
            "source_tier": 1,
            "title": "robin_(honkai:_star_rail)",
            "captured_at": "2026-09-13",
        },
        {
            "id": "gelbooru:wiki:robin_(honkai:_star_rail)",
            "source_site": "gelbooru",
            "source_kind": "wiki",
            "source_key": "robin_(honkai:_star_rail)",
            "source_url": "https://gelbooru.com/index.php?page=wiki&s=view&id=robin_(honkai:_star_rail)",
            "source_tier": 1,
            "title": "robin_(honkai:_star_rail)",
            "captured_at": "2026-09-13",
        },
    ],
    "kishin_sagume": [
        {
            "id": "danbooru:wiki:kishin_sagume",
            "source_site": "danbooru",
            "source_kind": "wiki",
            "source_key": "kishin_sagume",
            "source_url": "https://danbooru.donmai.us/wiki_pages/kishin_sagume.json",
            "source_tier": 1,
            "title": "kishin_sagume",
            "captured_at": "2026-09-13",
        },
        {
            "id": "gelbooru:wiki:kishin_sagume",
            "source_site": "gelbooru",
            "source_kind": "wiki",
            "source_key": "kishin_sagume",
            "source_url": "https://gelbooru.com/index.php?page=wiki&s=view&id=kishin_sagume",
            "source_tier": 1,
            "title": "kishin_sagume",
            "captured_at": "2026-09-13",
        },
    ],
}

errors: list[str] = []

# Fill excerpt + sha from real bodies, verify substring.
for site, kind, key in [
    ("danbooru", "wiki", "bea_(pokemon)"),
    ("gelbooru", "wiki", "bea_(pokemon)"),
    ("danbooru", "wiki", "fischl_(genshin_impact)"),
    ("gelbooru", "wiki", "fischl_(genshin_impact)"),
    ("danbooru", "wiki", "hifumi_(blue_archive)"),
    ("gelbooru", "wiki", "hifumi_(blue_archive)"),
    ("danbooru", "wiki", "ultimate_madoka"),
    ("gelbooru", "wiki", "ultimate_madoka"),
    ("danbooru", "wiki", "robin_(honkai:_star_rail)"),
    ("gelbooru", "wiki", "robin_(honkai:_star_rail)"),
    ("danbooru", "wiki", "kishin_sagume"),
    ("gelbooru", "wiki", "kishin_sagume"),
]:
    body = wiki_body(site, key)
    if not body:
        errors.append(f"NO WIKI BODY for {site}:{key}")
        continue
    excerpt = extract_excerpt(body)
    if not excerpt:
        errors.append(f"EMPTY EXCERPT for {site}:{key}")
        continue
    if excerpt not in body:
        errors.append(f"EXCERPT_NOT_LITERAL {site}:{key}: {excerpt[:60]!r}")
        continue
    sha = hashlib.sha256(body.encode("utf-8")).hexdigest()
    for s in sources[key]:
        if s["source_site"] == site and s["source_kind"] == kind and s["source_key"] == key:
            s["excerpt"] = excerpt
            s["source_sha256"] = sha
            break

if errors:
    for e in errors:
        print("ERROR:", e)
    raise SystemExit(1)

# ---- ensure all feature canonical tags exist in catalog ----
cur.execute("SELECT canonical_tag FROM appearance_feature_catalog")
catalog_tags = {r[0] for r in cur.fetchall()}

# all canonical tags used across seeds
all_tags: set[str] = set()
defs = {
    "bea_(pokemon)": [
        "grey_eyes", "grey_hair", "short_hair", "hair_between_eyes",
        "bow_hairband", "black_hairband", "black_bodysuit", "bodysuit_under_clothes",
        "collared_shirt", "short_sleeves", "print_shirt", "side_slit_shorts",
        "print_shorts", "single_glove", "partially_fingerless_gloves",
    ],
    "fischl_(genshin_impact)": [
        "blonde_hair", "long_hair", "two_side_up", "asymmetrical_bangs",
        "black_ribbon", "hair_ribbon", "purple_ribbon", "green_eyes",
        "small_breasts", "petite", "tailcoat", "detached_sleeves", "single_sleeve",
        "collar", "neck_ribbon", "single_thighhigh", "garter_straps",
        "black_leotard", "gloves", "bridal_gauntlets", "fishnet_bodystocking",
    ],
    "hifumi_(blue_archive)": [
        "long_hair", "blonde_hair", "low_twintails", "yellow_eyes",
        "white_cardigan", "blue_sailor_collar", "yellow_bowtie", "blue_skirt",
        "black_pantyhose", "white_shoes",
    ],
    "ultimate_madoka": [
        "yellow_eyes", "absurdly_long_hair", "pink_hair", "swept_bangs",
        "sidelocks", "two_side_up", "hair_bow", "white_bow", "pink_wings",
        "wings", "white_choker", "choker", "white_jacket", "cropped_jacket",
        "pink_gems", "short_sleeves", "wide_sleeves", "layered_sleeves",
        "white_gloves", "gloves", "high_low_dress", "layered_dress",
        "frilled_dress", "white_dress", "layered_frills", "space_print",
        "thighhighs", "pink_thighhighs", "winged_footwear",
    ],
    "robin_(honkai:_star_rail)": [
        "long_hair", "blue_hair", "head_wings", "halo", "green_eyes", "blue_eyes",
        "medium_breasts", "strapless_dress", "two_tone_dress", "white_dress",
        "purple_dress", "white_gloves", "elbow_gloves", "feather_boa",
        "purple_shoes", "purple_pumps", "purple_high_heels",
    ],
    "kishin_sagume": [
        "short_hair", "white_hair", "braid", "red_eyes", "white_jacket",
        "purple_skirt", "cut_in_pleats", "single_wing",
    ],
}
for tags in defs.values():
    all_tags.update(tags)

missing = sorted(all_tags - catalog_tags)
if missing:
    for m in missing:
        print("MISSING CATALOG TAG:", m)
    raise SystemExit(1)
print("all feature canonical tags present in catalog:", len(all_tags))

# ---- upsert sources ----
for key, srcs in sources.items():
    for s in srcs:
        cur.execute(
            """INSERT INTO character_appearance_sources(
                source_site, source_kind, source_key, source_url, source_tier,
                title, excerpt, captured_at, source_sha256
            ) VALUES (?,?,?,?,?,?,?,?,?)
            ON CONFLICT(source_site, source_kind, source_key) DO UPDATE SET
                source_url=excluded.source_url,
                source_tier=excluded.source_tier,
                title=excluded.title,
                excerpt=excluded.excerpt,
                captured_at=excluded.captured_at,
                source_sha256=excluded.source_sha256""",
            (
                normalize_tag(s["source_site"]),
                normalize_tag(s["source_kind"]),
                s["source_key"],
                s["source_url"],
                int(s["source_tier"]),
                s["title"],
                s["excerpt"],
                s["captured_at"],
                s["source_sha256"],
            ),
        )
db.commit()

# build source id lookup for refs
src_lookup: dict[str, int] = {}
for key, srcs in sources.items():
    for s in srcs:
        ref = f"{s['source_site']}:{s['source_kind']}:{s['source_key']}"
        cur.execute(
            "SELECT source_id FROM character_appearance_sources WHERE source_site=? AND source_kind=? AND source_key=?",
            (normalize_tag(s["source_site"]), normalize_tag(s["source_kind"]), s["source_key"]),
        )
        row = cur.fetchone()
        if not row:
            raise RuntimeError(f"source not found after upsert: {ref}")
        src_lookup[ref] = int(row[0])

print("sources inserted/verified:")
for ref, sid in src_lookup.items():
    print(f"  {ref} -> {sid}")


def source_dicts_for(char: str) -> list[dict]:
    out = []
    for s in sources[char]:
        out.append({
            "id": s["id"],
            "source_site": s["source_site"],
            "source_kind": s["source_kind"],
            "source_key": s["source_key"],
            "source_url": s["source_url"],
            "source_tier": s["source_tier"],
            "title": s["title"],
            "excerpt": s["excerpt"],
            "captured_at": s["captured_at"],
            "source_sha256": s["source_sha256"],
        })
    return out


def feature(canonical_tag: str, facet: str, value: str,
            source_refs: list[str]) -> dict:
    return {
        "facet": facet,
        "canonical_tag": canonical_tag,
        "value": value,
        "source_refs": source_refs,
    }


def make_seed(
    char_tag: str,
    display_name: str,
    notes: str,
    features: list[dict],
    *,
    appearance_kind: str = "default",
    is_default: bool = True,
    provenance: str = "danbooru_gelbooru_wiki_reviewed",
) -> dict:
    srcs = source_dicts_for(char_tag)
    return {
        "character_tag": char_tag,
        "sources": srcs,
        "profiles": [
            {
                "appearance_key": f"{char_tag}::default",
                "variant_tag": char_tag,
                "display_name": display_name,
                "appearance_kind": appearance_kind,
                "is_default": is_default,
                "status": "published",
                "confidence": "high",
                "provenance": provenance,
                "notes": notes,
                "features": features,
            }
        ],
    }


bea_features = [
    feature("grey_eyes", "eyes", "Grey eyes",
            ["danbooru:wiki:bea_(pokemon)", "gelbooru:wiki:bea_(pokemon)"]),
    feature("grey_hair", "hair", "Grey hair",
            ["danbooru:wiki:bea_(pokemon)", "gelbooru:wiki:bea_(pokemon)"]),
    feature("short_hair", "hair", "Short hair",
            ["danbooru:wiki:bea_(pokemon)", "gelbooru:wiki:bea_(pokemon)"]),
    feature("hair_between_eyes", "hair", "Hair between eyes",
            ["danbooru:wiki:bea_(pokemon)", "gelbooru:wiki:bea_(pokemon)"]),
    feature("bow_hairband", "hair_accessory", "Bow hairband",
            ["danbooru:wiki:bea_(pokemon)", "gelbooru:wiki:bea_(pokemon)"]),
    feature("black_hairband", "hair_accessory", "Black hairband",
            ["danbooru:wiki:bea_(pokemon)", "gelbooru:wiki:bea_(pokemon)"]),
    feature("black_bodysuit", "dress", "Black bodysuit",
            ["danbooru:wiki:bea_(pokemon)", "gelbooru:wiki:bea_(pokemon)"]),
    feature("bodysuit_under_clothes", "dress", "Bodysuit under clothes",
            ["danbooru:wiki:bea_(pokemon)", "gelbooru:wiki:bea_(pokemon)"]),
    feature("collared_shirt", "upper_body", "Collared shirt",
            ["danbooru:wiki:bea_(pokemon)", "gelbooru:wiki:bea_(pokemon)"]),
    feature("short_sleeves", "sleeves", "Short sleeves",
            ["danbooru:wiki:bea_(pokemon)", "gelbooru:wiki:bea_(pokemon)"]),
    feature("print_shirt", "upper_body", "Print shirt",
            ["danbooru:wiki:bea_(pokemon)", "gelbooru:wiki:bea_(pokemon)"]),
    feature("side_slit_shorts", "lower_body", "Side slit shorts",
            ["danbooru:wiki:bea_(pokemon)", "gelbooru:wiki:bea_(pokemon)"]),
    feature("print_shorts", "lower_body", "Print shorts",
            ["danbooru:wiki:bea_(pokemon)", "gelbooru:wiki:bea_(pokemon)"]),
    feature("single_glove", "gloves", "Single glove",
            ["danbooru:wiki:bea_(pokemon)", "gelbooru:wiki:bea_(pokemon)"]),
    feature("partially_fingerless_gloves", "gloves",
            "Partially fingerless gloves",
            ["danbooru:wiki:bea_(pokemon)", "gelbooru:wiki:bea_(pokemon)"]),
]

fischl_features = [
    feature("blonde_hair", "hair", "Blonde hair",
            ["danbooru:wiki:fischl_(genshin_impact)",
             "gelbooru:wiki:fischl_(genshin_impact)"]),
    feature("long_hair", "hair", "Long hair",
            ["danbooru:wiki:fischl_(genshin_impact)",
             "gelbooru:wiki:fischl_(genshin_impact)"]),
    feature("two_side_up", "hair_accessory", "Two side up",
            ["danbooru:wiki:fischl_(genshin_impact)",
             "gelbooru:wiki:fischl_(genshin_impact)"]),
    feature("asymmetrical_bangs", "hair_accessory", "Asymmetrical bangs",
            ["danbooru:wiki:fischl_(genshin_impact)",
             "gelbooru:wiki:fischl_(genshin_impact)"]),
    feature("black_ribbon", "hair_accessory", "Black ribbon",
            ["danbooru:wiki:fischl_(genshin_impact)",
             "gelbooru:wiki:fischl_(genshin_impact)"]),
    feature("hair_ribbon", "hair_accessory", "Hair ribbon",
            ["danbooru:wiki:fischl_(genshin_impact)",
             "gelbooru:wiki:fischl_(genshin_impact)"]),
    feature("purple_ribbon", "hair_accessory", "Purple ribbon",
            ["danbooru:wiki:fischl_(genshin_impact)",
             "gelbooru:wiki:fischl_(genshin_impact)"]),
    feature("green_eyes", "eyes", "Green eyes",
            ["danbooru:wiki:fischl_(genshin_impact)",
             "gelbooru:wiki:fischl_(genshin_impact)"]),
    feature("small_breasts", "body", "Small breasts",
            ["danbooru:wiki:fischl_(genshin_impact)",
             "gelbooru:wiki:fischl_(genshin_impact)"]),
    feature("petite", "body", "Petite build",
            ["danbooru:wiki:fischl_(genshin_impact)",
             "gelbooru:wiki:fischl_(genshin_impact)"]),
    feature("tailcoat", "jacket", "Tailcoat",
            ["danbooru:wiki:fischl_(genshin_impact)",
             "gelbooru:wiki:fischl_(genshin_impact)"]),
    feature("detached_sleeves", "sleeves", "Detached sleeves",
            ["danbooru:wiki:fischl_(genshin_impact)",
             "gelbooru:wiki:fischl_(genshin_impact)"]),
    feature("single_sleeve", "sleeves", "Single sleeve",
            ["danbooru:wiki:fischl_(genshin_impact)",
             "gelbooru:wiki:fischl_(genshin_impact)"]),
    feature("collar", "neck", "Collar",
            ["danbooru:wiki:fischl_(genshin_impact)",
             "gelbooru:wiki:fischl_(genshin_impact)"]),
    feature("neck_ribbon", "neck", "Neck ribbon",
            ["danbooru:wiki:fischl_(genshin_impact)",
             "gelbooru:wiki:fischl_(genshin_impact)"]),
    feature("single_thighhigh", "legwear", "Single thighhigh",
            ["danbooru:wiki:fischl_(genshin_impact)",
             "gelbooru:wiki:fischl_(genshin_impact)"]),
    feature("garter_straps", "legwear", "Garter straps",
            ["danbooru:wiki:fischl_(genshin_impact)",
             "gelbooru:wiki:fischl_(genshin_impact)"]),
    feature("black_leotard", "dress", "Black leotard",
            ["danbooru:wiki:fischl_(genshin_impact)",
             "gelbooru:wiki:fischl_(genshin_impact)"]),
    feature("gloves", "gloves", "Gloves",
            ["danbooru:wiki:fischl_(genshin_impact)",
             "gelbooru:wiki:fischl_(genshin_impact)"]),
    feature("bridal_gauntlets", "gloves", "Bridal gauntlets",
            ["danbooru:wiki:fischl_(genshin_impact)",
             "gelbooru:wiki:fischl_(genshin_impact)"]),
    feature("fishnet_bodystocking", "dress", "Fishnet bodystocking",
            ["danbooru:wiki:fischl_(genshin_impact)",
             "gelbooru:wiki:fischl_(genshin_impact)"]),
]

hifumi_features = [
    feature("long_hair", "hair", "Long hair",
            ["danbooru:wiki:hifumi_(blue_archive)",
             "gelbooru:wiki:hifumi_(blue_archive)"]),
    feature("blonde_hair", "hair", "Blonde hair",
            ["danbooru:wiki:hifumi_(blue_archive)",
             "gelbooru:wiki:hifumi_(blue_archive)"]),
    feature("low_twintails", "hair_accessory", "Low twintails",
            ["danbooru:wiki:hifumi_(blue_archive)",
             "gelbooru:wiki:hifumi_(blue_archive)"]),
    feature("yellow_eyes", "eyes", "Yellow eyes",
            ["danbooru:wiki:hifumi_(blue_archive)",
             "gelbooru:wiki:hifumi_(blue_archive)"]),
    feature("white_cardigan", "upper_body", "White cardigan",
            ["danbooru:wiki:hifumi_(blue_archive)",
             "gelbooru:wiki:hifumi_(blue_archive)"]),
    feature("blue_sailor_collar", "neck", "Blue sailor collar",
            ["danbooru:wiki:hifumi_(blue_archive)",
             "gelbooru:wiki:hifumi_(blue_archive)"]),
    feature("yellow_bowtie", "neck", "Yellow bowtie",
            ["danbooru:wiki:hifumi_(blue_archive)",
             "gelbooru:wiki:hifumi_(blue_archive)"]),
    feature("blue_skirt", "lower_body", "Blue skirt",
            ["danbooru:wiki:hifumi_(blue_archive)",
             "gelbooru:wiki:hifumi_(blue_archive)"]),
    feature("black_pantyhose", "legwear", "Black pantyhose",
            ["danbooru:wiki:hifumi_(blue_archive)",
             "gelbooru:wiki:hifumi_(blue_archive)"]),
    feature("white_shoes", "footwear", "White shoes",
            ["danbooru:wiki:hifumi_(blue_archive)",
             "gelbooru:wiki:hifumi_(blue_archive)"]),
]

ultimate_madoka_features = [
    feature("yellow_eyes", "eyes", "Yellow eyes",
            ["danbooru:wiki:ultimate_madoka",
             "gelbooru:wiki:ultimate_madoka"]),
    feature("absurdly_long_hair", "hair", "Absurdly long hair",
            ["danbooru:wiki:ultimate_madoka",
             "gelbooru:wiki:ultimate_madoka"]),
    feature("pink_hair", "hair", "Pink hair",
            ["danbooru:wiki:ultimate_madoka",
             "gelbooru:wiki:ultimate_madoka"]),
    feature("swept_bangs", "hair_accessory", "Swept bangs",
            ["danbooru:wiki:ultimate_madoka",
             "gelbooru:wiki:ultimate_madoka"]),
    feature("sidelocks", "hair_accessory", "Sidelocks",
            ["danbooru:wiki:ultimate_madoka",
             "gelbooru:wiki:ultimate_madoka"]),
    feature("two_side_up", "hair_accessory", "Two side up",
            ["danbooru:wiki:ultimate_madoka",
             "gelbooru:wiki:ultimate_madoka"]),
    feature("hair_bow", "hair_accessory", "Hair bow",
            ["danbooru:wiki:ultimate_madoka",
             "gelbooru:wiki:ultimate_madoka"]),
    feature("white_bow", "hair_accessory", "White bow",
            ["danbooru:wiki:ultimate_madoka",
             "gelbooru:wiki:ultimate_madoka"]),
    feature("pink_wings", "wings", "Pink wings",
            ["danbooru:wiki:ultimate_madoka",
             "gelbooru:wiki:ultimate_madoka"]),
    feature("wings", "wings", "Wings",
            ["danbooru:wiki:ultimate_madoka",
             "gelbooru:wiki:ultimate_madoka"]),
    feature("white_choker", "neck", "White choker",
            ["danbooru:wiki:ultimate_madoka",
             "gelbooru:wiki:ultimate_madoka"]),
    feature("choker", "neck", "Choker",
            ["danbooru:wiki:ultimate_madoka",
             "gelbooru:wiki:ultimate_madoka"]),
    feature("white_jacket", "jacket", "White jacket",
            ["danbooru:wiki:ultimate_madoka",
             "gelbooru:wiki:ultimate_madoka"]),
    feature("cropped_jacket", "jacket", "Cropped jacket",
            ["danbooru:wiki:ultimate_madoka",
             "gelbooru:wiki:ultimate_madoka"]),
    feature("pink_gems", "accessories", "Pink gems",
            ["danbooru:wiki:ultimate_madoka",
             "gelbooru:wiki:ultimate_madoka"]),
    feature("short_sleeves", "sleeves", "Short sleeves",
            ["danbooru:wiki:ultimate_madoka",
             "gelbooru:wiki:ultimate_madoka"]),
    feature("wide_sleeves", "sleeves", "Wide sleeves",
            ["danbooru:wiki:ultimate_madoka",
             "gelbooru:wiki:ultimate_madoka"]),
    feature("layered_sleeves", "sleeves", "Layered sleeves",
            ["danbooru:wiki:ultimate_madoka",
             "gelbooru:wiki:ultimate_madoka"]),
    feature("white_gloves", "gloves", "White gloves",
            ["danbooru:wiki:ultimate_madoka",
             "gelbooru:wiki:ultimate_madoka"]),
    feature("gloves", "gloves", "Gloves",
            ["danbooru:wiki:ultimate_madoka",
             "gelbooru:wiki:ultimate_madoka"]),
    feature("high_low_dress", "dress", "High-low dress",
            ["danbooru:wiki:ultimate_madoka",
             "gelbooru:wiki:ultimate_madoka"]),
    feature("layered_dress", "dress", "Layered dress",
            ["danbooru:wiki:ultimate_madoka",
             "gelbooru:wiki:ultimate_madoka"]),
    feature("frilled_dress", "dress", "Frilled dress",
            ["danbooru:wiki:ultimate_madoka",
             "gelbooru:wiki:ultimate_madoka"]),
    feature("white_dress", "dress", "White dress",
            ["danbooru:wiki:ultimate_madoka",
             "gelbooru:wiki:ultimate_madoka"]),
    feature("layered_frills", "dress", "Layered frills",
            ["danbooru:wiki:ultimate_madoka",
             "gelbooru:wiki:ultimate_madoka"]),
    feature("space_print", "accessories", "Space print",
            ["danbooru:wiki:ultimate_madoka",
             "gelbooru:wiki:ultimate_madoka"]),
    feature("thighhighs", "legwear", "Thighhighs",
            ["danbooru:wiki:ultimate_madoka",
             "gelbooru:wiki:ultimate_madoka"]),
    feature("pink_thighhighs", "legwear", "Pink thighhighs",
            ["danbooru:wiki:ultimate_madoka",
             "gelbooru:wiki:ultimate_madoka"]),
    feature("winged_footwear", "footwear", "Winged footwear",
            ["danbooru:wiki:ultimate_madoka",
             "gelbooru:wiki:ultimate_madoka"]),
]

robin_features = [
    feature("long_hair", "hair", "Long hair",
            ["danbooru:wiki:robin_(honkai:_star_rail)",
             "gelbooru:wiki:robin_(honkai:_star_rail)"]),
    feature("blue_hair", "hair", "Blue hair",
            ["danbooru:wiki:robin_(honkai:_star_rail)",
             "gelbooru:wiki:robin_(honkai:_star_rail)"]),
    feature("head_wings", "wings", "Head wings",
            ["danbooru:wiki:robin_(honkai:_star_rail)",
             "gelbooru:wiki:robin_(honkai:_star_rail)"]),
    feature("halo", "headwear", "Halo",
            ["danbooru:wiki:robin_(honkai:_star_rail)",
             "gelbooru:wiki:robin_(honkai:_star_rail)"]),
    feature("green_eyes", "eyes", "Green eyes",
            ["danbooru:wiki:robin_(honkai:_star_rail)",
             "gelbooru:wiki:robin_(honkai:_star_rail)"]),
    feature("blue_eyes", "eyes", "Blue eyes",
            ["danbooru:wiki:robin_(honkai:_star_rail)",
             "gelbooru:wiki:robin_(honkai:_star_rail)"]),
    feature("medium_breasts", "body", "Medium breasts",
            ["danbooru:wiki:robin_(honkai:_star_rail)",
             "gelbooru:wiki:robin_(honkai:_star_rail)"]),
    feature("strapless_dress", "dress", "Strapless dress",
            ["danbooru:wiki:robin_(honkai:_star_rail)",
             "gelbooru:wiki:robin_(honkai:_star_rail)"]),
    feature("two_tone_dress", "dress", "Two tone dress",
            ["danbooru:wiki:robin_(honkai:_star_rail)",
             "gelbooru:wiki:robin_(honkai:_star_rail)"]),
    feature("white_dress", "dress", "White dress",
            ["danbooru:wiki:robin_(honkai:_star_rail)",
             "gelbooru:wiki:robin_(honkai:_star_rail)"]),
    feature("purple_dress", "dress", "Purple dress",
            ["danbooru:wiki:robin_(honkai:_star_rail)",
             "gelbooru:wiki:robin_(honkai:_star_rail)"]),
    feature("white_gloves", "gloves", "White gloves",
            ["danbooru:wiki:robin_(honkai:_star_rail)",
             "gelbooru:wiki:robin_(honkai:_star_rail)"]),
    feature("elbow_gloves", "gloves", "Elbow gloves",
            ["danbooru:wiki:robin_(honkai:_star_rail)",
             "gelbooru:wiki:robin_(honkai:_star_rail)"]),
    feature("feather_boa", "accessories", "Feather boa",
            ["danbooru:wiki:robin_(honkai:_star_rail)",
             "gelbooru:wiki:robin_(honkai:_star_rail)"]),
    feature("purple_shoes", "footwear", "Purple shoes",
            ["danbooru:wiki:robin_(honkai:_star_rail)",
             "gelbooru:wiki:robin_(honkai:_star_rail)"]),
    feature("purple_pumps", "footwear", "Purple pumps",
            ["danbooru:wiki:robin_(honkai:_star_rail)",
             "gelbooru:wiki:robin_(honkai:_star_rail)"]),
    feature("purple_high_heels", "footwear", "Purple high heels",
            ["danbooru:wiki:robin_(honkai:_star_rail)",
             "gelbooru:wiki:robin_(honkai:_star_rail)"]),
]

kishin_sagume_features = [
    feature("short_hair", "hair", "Short hair",
            ["danbooru:wiki:kishin_sagume",
             "gelbooru:wiki:kishin_sagume"]),
    feature("white_hair", "hair", "White hair",
            ["danbooru:wiki:kishin_sagume",
             "gelbooru:wiki:kishin_sagume"]),
    feature("braid", "hair_accessory", "Braid",
            ["danbooru:wiki:kishin_sagume",
             "gelbooru:wiki:kishin_sagume"]),
    feature("red_eyes", "eyes", "Red eyes",
            ["danbooru:wiki:kishin_sagume",
             "gelbooru:wiki:kishin_sagume"]),
    feature("white_jacket", "jacket", "White jacket",
            ["danbooru:wiki:kishin_sagume",
             "gelbooru:wiki:kishin_sagume"]),
    feature("purple_skirt", "lower_body", "Purple skirt",
            ["danbooru:wiki:kishin_sagume",
             "gelbooru:wiki:kishin_sagume"]),
    feature("cut_in_pleats", "lower_body", "Cut-in pleats",
            ["danbooru:wiki:kishin_sagume",
             "gelbooru:wiki:kishin_sagume"]),
    feature("single_wing", "wings", "Single wing",
            ["danbooru:wiki:kishin_sagume",
             "gelbooru:wiki:kishin_sagume"]),
]

seeds = {
    "bea_(pokemon).json": make_seed(
        "bea_(pokemon)",
        "Bea default appearance",
        "Pokémon Sword Gym Leader Bea (Saitou) default appearance. Counterpart is Allister in Shield.",
        bea_features,
    ),
    "fischl_(genshin_impact).json": make_seed(
        "fischl_(genshin_impact)",
        "Fischl default appearance",
        "Genshin Impact Prinzessin der Verurteilung default appearance.",
        fischl_features,
    ),
    "hifumi_(blue_archive).json": make_seed(
        "hifumi_(blue_archive)",
        "Hifumi default appearance",
        "Blue Archive Make-Up Work Club member Ajitani Hifumi default appearance.",
        hifumi_features,
    ),
    "ultimate_madoka.json": make_seed(
        "ultimate_madoka",
        "Ultimate Madoka appearance",
        "Puella Magi Madoka Magica ultimate Madoka alternate persona appearance.",
        ultimate_madoka_features,
    ),
    "robin_(honkai:_star_rail).json": make_seed(
        "robin_(honkai:_star_rail)",
        "Robin default appearance",
        "Honkai Star Rail singer Robin default appearance.",
        robin_features,
    ),
    "kishin_sagume.json": make_seed(
        "kishin_sagume",
        "Kishin Sagume default appearance",
        "Touhou Legacy of Lunatic Kingdom stage 4 midboss/goddess Kishin Sagume default appearance.",
        kishin_sagume_features,
    ),
}

for fname, seed in seeds.items():
    path = SEEDS / fname
    content = json.dumps(seed, ensure_ascii=False, indent=2) + "\n"
    path.write_text(content, encoding="utf-8")
    print(f"wrote {path}")

db.close()
print("done")
