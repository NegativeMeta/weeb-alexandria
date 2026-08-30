"""Shared schema and deterministic tag classification for appearance data."""
from __future__ import annotations

import re
import sqlite3
from typing import Optional

APPEARANCE_SCHEMA_VERSION = "3"

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

CREATE TABLE IF NOT EXISTS appearance_facet_catalog (
    facet_id INTEGER PRIMARY KEY,
    facet_key TEXT NOT NULL UNIQUE,
    facet_group TEXT NOT NULL,
    is_visual INTEGER NOT NULL DEFAULT 1,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active'
);
CREATE INDEX IF NOT EXISTS idx_appearance_facet_catalog_group
    ON appearance_facet_catalog(facet_group, is_visual, status);

CREATE TABLE IF NOT EXISTS appearance_feature_catalog (
    catalog_id INTEGER PRIMARY KEY,
    canonical_tag TEXT NOT NULL UNIQUE,
    default_facet TEXT NOT NULL,
    default_value TEXT NOT NULL,
    label TEXT NOT NULL,
    provenance TEXT NOT NULL DEFAULT 'appearance_normalization',
    confidence TEXT NOT NULL DEFAULT 'medium',
    status TEXT NOT NULL DEFAULT 'active'
);
CREATE INDEX IF NOT EXISTS idx_appearance_catalog_tag
    ON appearance_feature_catalog(canonical_tag, status);

CREATE TABLE IF NOT EXISTS character_appearance_features (
    feature_id INTEGER PRIMARY KEY,
    catalog_id INTEGER REFERENCES appearance_feature_catalog(catalog_id),
    facet_id INTEGER REFERENCES appearance_facet_catalog(facet_id),
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

CREATE TABLE IF NOT EXISTS character_appearance_conflicts (
    conflict_id INTEGER PRIMARY KEY,
    appearance_key TEXT NOT NULL,
    facet TEXT NOT NULL,
    conflict_key TEXT NOT NULL,
    alternatives_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    reason TEXT NOT NULL,
    source_refs_json TEXT NOT NULL DEFAULT '[]',
    resolution_note TEXT NOT NULL DEFAULT '',
    UNIQUE(appearance_key, conflict_key)
);
CREATE INDEX IF NOT EXISTS idx_appearance_conflicts_profile
    ON character_appearance_conflicts(appearance_key, status);
"""

DEFAULT_METADATA = {
    "schema_version": APPEARANCE_SCHEMA_VERSION,
    "system": "character_appearance_cards",
    "source_policy": "danbooru_gelbooru_primary",
}

DEFAULT_FACETS = {
    "hair": ("visual", 1, "Color, length, and general hair characteristics."),
    "hair_accessory": ("visual", 1, "Hairstyles and items attached to the hair."),
    "eyes": ("visual", 1, "Eye color and visible eye structure."),
    "face": ("visual", 1, "Visible facial features and face-worn items."),
    "ears": ("visual", 1, "Ear shape and extra ears."),
    "horns": ("visual", 1, "Horns, antlers, and similar head appendages."),
    "headwear": ("visual", 1, "Hats, helmets, halos, and head-worn items."),
    "neck": ("visual", 1, "Collars, chokers, ties, and neckwear."),
    "dress": ("visual", 1, "Dresses, uniforms, robes, and full garments."),
    "jacket": ("visual", 1, "Coats, jackets, capes, and outer layers."),
    "upper_body": ("visual", 1, "Shirts, tops, tunics, and upper-body clothing."),
    "lower_body": ("visual", 1, "Skirts, pants, shorts, and lower-body clothing."),
    "sleeves": ("visual", 1, "Sleeves and arm coverings."),
    "gloves": ("visual", 1, "Gloves and hand coverings."),
    "legwear": ("visual", 1, "Socks, stockings, tights, and thigh-highs."),
    "footwear": ("visual", 1, "Shoes, boots, sandals, and other footwear."),
    "jewelry": ("visual", 1, "Jewelry and ornamental metalwork."),
    "accessories": ("visual", 1, "General wearable accessories."),
    "props": ("visual", 1, "Held or carried objects."),
    "wings": ("visual", 1, "Wings and wing-like appendages."),
    "tail": ("visual", 1, "Tails and tail-like appendages."),
    "markings": ("visual", 1, "Scars, birthmarks, tattoos, and body markings."),
    "effects": ("visual", 1, "Visible energy, fire, glow, or other effects."),
    "body": ("identity", 1, "Body shape and physical form."),
    "skin": ("identity", 1, "Skin tone and skin material."),
    "species": ("identity", 1, "Species or biological design identity."),
    "gender": ("identity", 1, "Gender or presentation metadata."),
    "context": ("context", 0, "Role, occupation, style, or non-visual context."),
    "expression": ("context", 0, "Facial expression or pose-related metadata."),
    "unclassified": ("review", 1, "Temporary review bucket for unresolved facets."),
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

_EXPLICIT_FACETS = {
    "pointy_ears": "ears",
    "floppy_ears": "ears",
    "mouse_ears": "ears",
    "rabbit_ears": "ears",
    "cat_ears": "ears",
    "extra_ears": "ears",
    "blindfold": "face",
    "glasses": "face",
    "third_eye": "face",
    "serafuku": "dress",
    "black_serafuku": "dress",
    "gown": "dress",
    "japanese_clothes": "dress",
    "plugsuit": "dress",
    "robe": "dress",
    "black_suit": "dress",
    "black_blazer": "jacket",
    "haori": "jacket",
    "green_tunic": "upper_body",
    "orange_neckerchief": "neck",
    "pink_neckerchief": "neck",
    "red_neckerchief": "neck",
    "double_halo": "headwear",
    "halo": "headwear",
    "pink_halo": "headwear",
    "bamboo": "props",
    "leaf": "props",
    "plum_blossoms": "props",
    "scar": "markings",
    "suspenders": "accessories",
    "blue_fire": "effects",
    "short_sleeves": "sleeves",
    "black_thighhighs": "legwear",
    "bow_(weapon)": "props",
    "collared_shirt": "upper_body",
    "frilled_shirt_collar": "neck",
    "earrings": "jewelry",
    "headgear": "headwear",
    "mob_cap": "headwear",
    "mole_on_breast": "body",
    "miko": "context",
    "nontraditional_miko": "context",
    "samurai": "context",
    "dancer": "context",
    "detective": "context",
    "necromancer": "context",
    "ouji_fashion": "context",
    "jitome": "expression",
}


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
    if normalized in _EXPLICIT_FACETS:
        return _EXPLICIT_FACETS[normalized]
    if normalized.endswith("_wings") or normalized == "wings":
        return "wings"
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


def canonical_facet(facet: str, tag: str) -> str:
    """Choose a controlled facet while preserving ambiguous assignments."""
    normalized_facet = normalize_tag(facet)
    normalized_tag = normalize_tag(tag)
    explicit = _EXPLICIT_FACETS.get(normalized_tag)
    if explicit:
        return explicit
    if normalized_tag.endswith("_wings") or normalized_tag == "wings":
        return "wings"
    if normalized_facet in DEFAULT_FACETS:
        return normalized_facet
    return infer_facet(normalized_tag) or "unclassified"


def upsert_appearance_facet_catalog(
    con: sqlite3.Connection,
    facet: str,
    facet_group: Optional[str] = None,
    is_visual: Optional[int] = None,
    description: Optional[str] = None,
) -> int:
    """Return the stable catalog row for one controlled appearance facet."""
    facet_key = normalize_tag(facet)
    if not facet_key:
        raise ValueError("appearance facet entries require a facet key")
    default_group, default_visual, default_description = DEFAULT_FACETS.get(
        facet_key, ("review", 1, "Facet requires review.")
    )
    group = str(facet_group or default_group)
    visual = int(default_visual if is_visual is None else bool(is_visual))
    detail = str(description if description is not None else default_description)
    con.execute(
        """INSERT INTO appearance_facet_catalog(
               facet_key, facet_group, is_visual, description, status
           ) VALUES (?, ?, ?, ?, 'active')
           ON CONFLICT(facet_key) DO UPDATE SET
               facet_group=excluded.facet_group,
               is_visual=excluded.is_visual,
               description=excluded.description,
               status='active'
           WHERE appearance_facet_catalog.facet_group <> excluded.facet_group
              OR appearance_facet_catalog.is_visual <> excluded.is_visual
              OR appearance_facet_catalog.description <> excluded.description
              OR appearance_facet_catalog.status <> 'active'""",
        (facet_key, group, visual, detail),
    )
    row = con.execute(
        "SELECT facet_id FROM appearance_facet_catalog WHERE facet_key=?",
        (facet_key,),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"could not retrieve appearance facet {facet_key}")
    return int(row[0])


def sync_appearance_facet_catalog(con: sqlite3.Connection) -> int:
    """Seed the facet dictionary and backfill links for every feature row."""
    for facet_key, (group, visual, description) in DEFAULT_FACETS.items():
        upsert_appearance_facet_catalog(con, facet_key, group, visual, description)
    rows = con.execute(
        "SELECT DISTINCT facet FROM character_appearance_features WHERE facet <> '' ORDER BY facet"
    ).fetchall()
    for row in rows:
        upsert_appearance_facet_catalog(con, row[0])
    con.execute(
        """UPDATE character_appearance_features
           SET facet_id=(
               SELECT facet_id FROM appearance_facet_catalog c
               WHERE c.facet_key=character_appearance_features.facet
           )
           WHERE facet <> '' AND (
               facet_id IS NULL OR facet_id <> (
                   SELECT facet_id FROM appearance_facet_catalog c
                   WHERE c.facet_key=character_appearance_features.facet
               )
           )"""
    )
    return len(rows)


def ensure_appearance_schema(con: sqlite3.Connection) -> None:
    """Create the owned appearance schema and immutable policy defaults."""
    con.executescript(APPEARANCE_SCHEMA_SQL)
    columns = {
        row[1] for row in con.execute(
            "PRAGMA table_info(character_appearance_features)"
        )
    }
    if "catalog_id" not in columns:
        con.execute(
            "ALTER TABLE character_appearance_features ADD COLUMN "
            "catalog_id INTEGER REFERENCES appearance_feature_catalog(catalog_id)"
        )
    if "facet_id" not in columns:
        con.execute(
            "ALTER TABLE character_appearance_features ADD COLUMN "
            "facet_id INTEGER REFERENCES appearance_facet_catalog(facet_id)"
        )
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_appearance_features_catalog "
        "ON character_appearance_features(catalog_id, status)"
    )
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_appearance_features_facet "
        "ON character_appearance_features(facet_id, status)"
    )
    sync_appearance_facet_catalog(con)
    sync_appearance_feature_catalog(con)
    con.executemany(
        """INSERT INTO appearance_schema_metadata(key, value) VALUES (?, ?)
           ON CONFLICT(key) DO UPDATE SET value=excluded.value
           WHERE appearance_schema_metadata.value <> excluded.value""",
        list(DEFAULT_METADATA.items()),
    )
    con.commit()


def upsert_appearance_feature_catalog(
    con: sqlite3.Connection,
    canonical_tag: str,
    facet: str,
    value: str,
    provenance: str = "appearance_normalization",
    confidence: str = "medium",
) -> int:
    """Return the stable global catalog row for one canonical appearance tag."""
    canonical_tag = normalize_tag(canonical_tag)
    facet = normalize_tag(facet) or "unclassified"
    if not canonical_tag:
        raise ValueError("appearance catalog entries require a canonical tag")
    display_value = str(value or humanize_tag(canonical_tag))
    con.execute(
        """INSERT INTO appearance_feature_catalog(
               canonical_tag, default_facet, default_value, label,
               provenance, confidence, status
           ) VALUES (?, ?, ?, ?, ?, ?, 'active')
           ON CONFLICT(canonical_tag) DO UPDATE SET
               default_facet=excluded.default_facet,
               default_value=excluded.default_value,
               label=excluded.label,
               provenance=CASE
                   WHEN excluded.provenance='promoted_appearance_seed'
                   THEN excluded.provenance
                   ELSE appearance_feature_catalog.provenance
               END,
               confidence=CASE
                   WHEN appearance_feature_catalog.confidence='high' THEN 'high'
                   ELSE excluded.confidence
               END,
               status='active'
           WHERE appearance_feature_catalog.default_facet <> excluded.default_facet
              OR appearance_feature_catalog.default_value <> excluded.default_value
              OR appearance_feature_catalog.label <> excluded.label
              OR (excluded.provenance='promoted_appearance_seed'
                  AND appearance_feature_catalog.provenance <> excluded.provenance)
              OR (appearance_feature_catalog.confidence <> 'high'
                  AND appearance_feature_catalog.confidence <> excluded.confidence)
              OR appearance_feature_catalog.status <> 'active'""",
        (canonical_tag, facet, display_value, humanize_tag(canonical_tag),
         provenance, confidence),
    )
    row = con.execute(
        "SELECT catalog_id FROM appearance_feature_catalog WHERE canonical_tag=?",
        (canonical_tag,),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"could not retrieve catalog tag {canonical_tag}")
    return int(row[0])


def sync_appearance_feature_catalog(con: sqlite3.Connection) -> int:
    """Backfill and repair catalog links for legacy or newly imported rows."""
    rows = con.execute(
        """SELECT f.canonical_tag, f.facet, f.value, f.confidence
           FROM character_appearance_features f
           JOIN (
               SELECT canonical_tag, MIN(feature_id) AS feature_id
               FROM character_appearance_features
               WHERE canonical_tag <> '' AND status <> 'retired'
               GROUP BY canonical_tag
           ) first_row ON first_row.feature_id=f.feature_id
           ORDER BY f.feature_id"""
    ).fetchall()
    for row in rows:
        upsert_appearance_feature_catalog(
            con, row[0], row[1], row[2], "appearance_normalization", row[3]
        )
    con.execute(
        """UPDATE character_appearance_features
           SET catalog_id=(
               SELECT catalog_id FROM appearance_feature_catalog c
               WHERE c.canonical_tag=character_appearance_features.canonical_tag
           )
           WHERE canonical_tag <> '' AND (
               catalog_id IS NULL OR catalog_id <> (
                   SELECT catalog_id FROM appearance_feature_catalog c
                   WHERE c.canonical_tag=character_appearance_features.canonical_tag
               )
           )"""
    )
    con.execute(
        """UPDATE appearance_feature_catalog
           SET status=CASE WHEN EXISTS (
               SELECT 1 FROM character_appearance_features f
               WHERE f.canonical_tag=appearance_feature_catalog.canonical_tag
                 AND f.status <> 'retired'
           ) THEN 'active' ELSE 'retired' END
           WHERE status <> CASE WHEN EXISTS (
               SELECT 1 FROM character_appearance_features f
               WHERE f.canonical_tag=appearance_feature_catalog.canonical_tag
                 AND f.status <> 'retired'
           ) THEN 'active' ELSE 'retired' END"""
    )
    return len(rows)


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
