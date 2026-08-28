"""Shared schema and deterministic tag classification for appearance data."""
from __future__ import annotations

import re
import sqlite3
from typing import Optional

APPEARANCE_SCHEMA_VERSION = "1"

APPEARANCE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS character_appearance_profiles (
    appearance_key TEXT PRIMARY KEY,
    character_tag TEXT NOT NULL,
    variant_tag TEXT NOT NULL,
    display_name TEXT NOT NULL,
    appearance_kind TEXT NOT NULL,
    is_default INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'candidate',
    confidence TEXT NOT NULL DEFAULT 'medium',
    provenance TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    UNIQUE(character_tag, variant_tag)
);
CREATE INDEX IF NOT EXISTS idx_appearance_profiles_character
    ON character_appearance_profiles(character_tag, status, is_default);
CREATE INDEX IF NOT EXISTS idx_appearance_profiles_variant
    ON character_appearance_profiles(variant_tag, status);

CREATE TABLE IF NOT EXISTS character_appearance_features (
    feature_id INTEGER PRIMARY KEY,
    appearance_key TEXT NOT NULL,
    facet TEXT NOT NULL,
    value TEXT NOT NULL,
    canonical_tag TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'present',
    status TEXT NOT NULL DEFAULT 'published',
    confidence TEXT NOT NULL DEFAULT 'medium',
    display_order INTEGER NOT NULL DEFAULT 0,
    UNIQUE(appearance_key, facet, canonical_tag)
);
CREATE INDEX IF NOT EXISTS idx_appearance_features_profile
    ON character_appearance_features(appearance_key, status, facet, display_order);
CREATE INDEX IF NOT EXISTS idx_appearance_features_tag
    ON character_appearance_features(canonical_tag, status);

CREATE TABLE IF NOT EXISTS character_appearance_sources (
    source_id INTEGER PRIMARY KEY,
    source_site TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    source_key TEXT NOT NULL,
    source_url TEXT NOT NULL DEFAULT '',
    source_tier INTEGER NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    excerpt TEXT NOT NULL DEFAULT '',
    captured_at TEXT NOT NULL DEFAULT '',
    source_sha256 TEXT NOT NULL DEFAULT '',
    UNIQUE(source_site, source_kind, source_key)
);
CREATE INDEX IF NOT EXISTS idx_appearance_sources_site_kind
    ON character_appearance_sources(source_site, source_kind, source_tier);

CREATE TABLE IF NOT EXISTS character_appearance_feature_sources (
    feature_id INTEGER NOT NULL,
    source_id INTEGER NOT NULL,
    polarity TEXT NOT NULL DEFAULT 'supports',
    observed_tag TEXT NOT NULL DEFAULT '',
    support_count INTEGER,
    sample_size INTEGER,
    evidence_text TEXT NOT NULL DEFAULT '',
    confidence TEXT NOT NULL DEFAULT 'medium',
    PRIMARY KEY(feature_id, source_id)
);
CREATE INDEX IF NOT EXISTS idx_appearance_feature_sources_source
    ON character_appearance_feature_sources(source_id, polarity);

CREATE TABLE IF NOT EXISTS appearance_schema_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

DEFAULT_METADATA = {
    "schema_version": APPEARANCE_SCHEMA_VERSION,
    "system": "character_appearance_cards",
    "source_policy": "danbooru_gelbooru_primary",
}

# These values are intentionally conservative. Unknown tags remain candidates
# with an empty facet instead of being silently assigned to a wrong category.
_GENDER_TAGS = {"1boy", "1girl", "1other", "no_humans"}
_EYE_TAGS = {"aqua_eyes", "black_eyes", "blue_eyes", "brown_eyes", "green_eyes",
             "grey_eyes", "orange_eyes", "pink_eyes", "purple_eyes", "red_eyes",
             "silver_eyes", "yellow_eyes"}
_HAIR_ACCESSORY_WORDS = (
    "ahoge", "bang", "braid", "hair", "ponytail", "sidelock", "twintail",
    "hairband", "hairclip", "hair_ornament", "hair_tube", "ribbon",
)
_FACE_WORDS = (
    "blush", "fang", "freckle", "mole", "mouth", "eyepatch", "face",
)
_SPECIES_WORDS = (
    "girl", "boy", "humanoid", "kemonomimi", "animal_ears", "animal_ear",
    "dog_ears", "cat_ears", "fox_ears", "wolf_ears", "extra_ears", "horn",
)
_CLOTHING_FACETS = (
    ("headwear", ("hat", "beret", "helmet", "headgear", "cap")),
    ("neck", ("collar", "choker", "necklace", "necktie", "bowtie", "scarf")),
    ("hair_accessory", _HAIR_ACCESSORY_WORDS),
    ("dress", ("dress", "kimono", "uniform", "jumpsuit", "romper", "bodysuit")),
    ("jacket", ("jacket", "coat", "cape", "capelet", "shawl", "cardigan", "vest")),
    ("upper_body", ("shirt", "blouse", "sweater", "top", "armor", "bikini")),
    ("lower_body", ("skirt", "shorts", "pants", "trousers", "overalls")),
    ("sleeves", ("sleeve", "bracer", "pauldron")),
    ("gloves", ("glove", "wristband", "bracelet")),
    ("legwear", ("sock", "stocking", "pantyhose", "thighhigh", "kneehigh", "legwear")),
    ("footwear", ("shoe", "boot", "sneaker", "sandal", "geta", "slipper", "mary_jane", "footwear")),
    ("jewelry", ("jewelry", "earring", "pendant", "brooch", "ring")),
    ("accessories", ("bow", "belt", "apron", "pocket", "button", "zipper", "ornament", "print")),
    ("props", ("vial", "potion", "weapon", "flower", "bone", "kadomatsu")),
)


def normalize_tag(value: str) -> str:
    """Normalize human-written tag text without changing tag semantics."""
    return "_".join((value or "").strip().lower().replace("-", "_").split())


def humanize_tag(tag: str) -> str:
    """Produce a readable label while retaining the canonical tag elsewhere."""
    return re.sub(r"\s+", " ", normalize_tag(tag).replace("_", " ")).strip()


def infer_facet(tag: str, category: Optional[str] = None) -> str:
    """Assign only obvious appearance/clothing facets.

    An empty string means that the candidate needs review. The classifier is
    deliberately deterministic and does not use an LLM or a fuzzy guess.
    """
    normalized = normalize_tag(tag)
    category_key = (category or "").strip().lower()
    if not normalized or category_key in {"meta", "artist", "copyright", "character", "alias"}:
        return ""
    if normalized in _GENDER_TAGS:
        return "gender"
    if normalized in {"hair_between_eyes", "hair_over_one_eye", "hair_over_eye"}:
        return "hair"
    if normalized in _EYE_TAGS or normalized.endswith("_eyes"):
        return "eyes"
    if normalized.endswith("_tail") or normalized == "tail":
        return "tail"
    if normalized in {"dog_girl", "cat_girl", "fox_girl", "wolf_girl"}:
        return "species"
    if any(word in normalized for word in _SPECIES_WORDS) and any(
        word in normalized for word in ("ear", "horn", "girl", "boy", "humanoid")
    ):
        return "ears" if "ear" in normalized else "horns" if "horn" in normalized else "species"
    if any(word in normalized for word in _FACE_WORDS):
        return "face"
    if normalized.endswith("_hair") or normalized in {"hair", "long_hair", "short_hair", "medium_hair", "very_long_hair"}:
        return "hair"
    for facet, words in _CLOTHING_FACETS:
        if any(word in normalized for word in words):
            return facet
    return ""


def ensure_appearance_schema(con: sqlite3.Connection) -> None:
    """Create the owned appearance schema and immutable policy defaults."""
    con.executescript(APPEARANCE_SCHEMA_SQL)
    con.executemany(
        "INSERT OR IGNORE INTO appearance_schema_metadata(key, value) VALUES (?, ?)",
        list(DEFAULT_METADATA.items()),
    )
    con.commit()


def appearance_kind_for_variant(variant_tag: str, character_tag: str) -> str:
    """Classify a variant tag for display without claiming canon."""
    normalized = normalize_tag(variant_tag)
    if normalized == normalize_tag(character_tag):
        return "default"
    if "costume" in normalized:
        return "costume"
    if any(token in normalized for token in ("new_year", "summer", "christmas", "halloween")):
        return "seasonal"
    if any(token in normalized for token in ("collab", "sonikoro", "blue_journey")):
        return "collab"
    if normalized.endswith("_(dog)") or "animalization" in normalized:
        return "animalization"
    return "costume"
