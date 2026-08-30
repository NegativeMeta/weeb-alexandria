#!/usr/bin/env python3
"""Promote existing owned character data into appearance profiles."""
from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from weeb_alexandria_mcp.appearance_schema import (  # noqa: E402
    canonical_facet as schema_canonical_facet,
    ensure_appearance_schema,
    infer_facet,
    humanize_tag,
    normalize_tag,
    sync_appearance_facet_catalog,
    sync_appearance_feature_catalog,
    upsert_appearance_facet_catalog,
    upsert_appearance_feature_catalog,
)
from weeb_alexandria_mcp.owned_schema import ensure_owned_schema  # noqa: E402

DEFAULT_DB = ROOT / "tag_library.db"


def appearance_key(character_tag: str) -> str:
    return f"{character_tag}::default"


def parse_tags(value: str) -> list[str]:
    result: list[str] = []
    for raw in (value or "").split(","):
        tag = normalize_tag(raw)
        if tag and tag not in result:
            result.append(tag)
    return result


_LEGACY_FACET_MAP = {
    "eye_color": "eyes",
    "hair_color": "hair",
    "hair_length": "hair",
    "hair_style": "hair",
    "ear_type": "ears",
    "tail_type": "tail",
    "accessory": "accessories",
}
_CANONICAL_FACETS = {
    "hair", "eyes", "skin", "face", "species", "ears", "horns", "tail",
    "body", "markings", "headwear", "hair_accessory", "neck", "upper_body",
    "lower_body", "dress", "jacket", "sleeves", "gloves", "legwear",
    "footwear", "jewelry", "accessories", "props", "wings", "effects",
    "context", "expression", "unclassified",
}


def canonical_facet(facet: str, tag: str) -> str:
    normalized = _LEGACY_FACET_MAP.get(normalize_tag(facet), normalize_tag(facet))
    return schema_canonical_facet(normalized, tag)


def _deduplicate_existing_features(con: sqlite3.Connection) -> int:
    rows = con.execute(
        """SELECT feature_id, appearance_key, facet, canonical_tag
           FROM character_appearance_features
           WHERE status <> 'retired'
           ORDER BY feature_id"""
    ).fetchall()
    groups: dict[tuple[str, str], list[sqlite3.Row]] = {}
    for row in rows:
        groups.setdefault((row["appearance_key"], row["canonical_tag"]), []).append(row)

    removed = 0
    for (_, canonical_tag), group in groups.items():
        target_facet = canonical_facet(group[0]["facet"], canonical_tag)
        keeper = next(
            (row for row in group if row["facet"] == target_facet),
            group[0],
        )
        if keeper["facet"] != target_facet:
            con.execute(
                "UPDATE character_appearance_features SET facet=? WHERE feature_id=?",
                (target_facet, keeper["feature_id"]),
            )
        for duplicate in group:
            if duplicate["feature_id"] == keeper["feature_id"]:
                continue
            con.execute(
                """INSERT OR IGNORE INTO character_appearance_feature_sources(
                       feature_id, source_id, polarity, observed_tag, support_count,
                       sample_size, evidence_text, confidence
                   ) SELECT ?, source_id, polarity, observed_tag, support_count,
                            sample_size, evidence_text, confidence
                   FROM character_appearance_feature_sources
                   WHERE feature_id=?""",
                (keeper["feature_id"], duplicate["feature_id"]),
            )
            con.execute(
                "DELETE FROM character_appearance_feature_sources WHERE feature_id=?",
                (duplicate["feature_id"],),
            )
            con.execute(
                "DELETE FROM character_appearance_features WHERE feature_id=?",
                (duplicate["feature_id"],),
            )
            removed += 1
    return removed


def source_id_for(con: sqlite3.Connection, character_tag: str,
                  source_url: str) -> int:
    con.execute(
        """INSERT OR IGNORE INTO character_appearance_sources(
            source_site, source_kind, source_key, source_url, source_tier,
            title, excerpt, captured_at, source_sha256
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "weeb_alexandria",
            "legacy_profile",
            character_tag,
            source_url or "",
            1,
            "Legacy curated character profile",
            "Migrated from character_profiles and character_traits.",
            "",
            "",
        ),
    )
    return int(con.execute(
        """SELECT source_id FROM character_appearance_sources
           WHERE source_site=? AND source_kind=? AND source_key=?""",
        ("weeb_alexandria", "legacy_profile", character_tag),
    ).fetchone()[0])


def upsert_feature(con: sqlite3.Connection, appearance_key_value: str,
                   facet: str, tag: str, value: str,
                   confidence: str = "high") -> int:
    canonical_tag = normalize_tag(tag)
    if not canonical_tag:
        raise ValueError("appearance feature cannot have an empty tag")
    feature_facet = canonical_facet(facet, canonical_tag)
    facet_id = upsert_appearance_facet_catalog(con, feature_facet)
    catalog_id = upsert_appearance_feature_catalog(
        con, canonical_tag, feature_facet, value,
        "legacy_appearance_migration", confidence,
    )
    con.execute(
        """INSERT INTO character_appearance_features(
            catalog_id, facet_id, appearance_key, facet, value, canonical_tag,
            role, status, confidence, display_order
        ) VALUES (?, ?, ?, ?, ?, ?, 'present', 'published', ?, 0)
        ON CONFLICT(appearance_key, facet, canonical_tag) DO UPDATE SET
            catalog_id=excluded.catalog_id,
            facet_id=excluded.facet_id,
            value=excluded.value,
            confidence=CASE
                WHEN character_appearance_features.confidence='high' THEN 'high'
                ELSE excluded.confidence
            END""",
        (
            catalog_id,
            facet_id,
            appearance_key_value,
            feature_facet,
            value or humanize_tag(canonical_tag),
            canonical_tag,
            confidence,
        ),
    )
    row = con.execute(
        """SELECT feature_id FROM character_appearance_features
           WHERE appearance_key=? AND facet=? AND canonical_tag=?""",
        (appearance_key_value, feature_facet, canonical_tag),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"could not retrieve feature {appearance_key_value}/{canonical_tag}")
    return int(row[0])


def link_feature(con: sqlite3.Connection, feature_id: int, source_id: int,
                 observed_tag: str, evidence_text: str) -> None:
    con.execute(
        """INSERT OR IGNORE INTO character_appearance_feature_sources(
            feature_id, source_id, polarity, observed_tag, support_count,
            sample_size, evidence_text, confidence
        ) VALUES (?, ?, 'supports', ?, NULL, NULL, ?, 'high')""",
        (feature_id, source_id, observed_tag, evidence_text),
    )


def migrate(db: Path) -> dict[str, int]:
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    try:
        ensure_owned_schema(con)
        profiles = con.execute(
            """SELECT character_tag, display_name, work_tag, work_name, trigger,
                      core_tags, source_url, provenance, confidence
               FROM character_profiles ORDER BY character_tag"""
        ).fetchall()
        if not profiles:
            raise RuntimeError("no character_profiles rows found")

        normalized_profile_tags: dict[str, str] = {}
        expected_profile_keys: set[str] = set()
        for row in profiles:
            raw_tag = str(row["character_tag"] or "")
            character_tag = normalize_tag(raw_tag)
            if not character_tag:
                raise ValueError("character_profiles contains an empty character_tag")
            previous = normalized_profile_tags.get(character_tag)
            if previous and previous != raw_tag:
                raise ValueError(
                    "character_tag normalization collision: "
                    f"{previous!r} and {raw_tag!r} both normalize to {character_tag!r}"
                )
            normalized_profile_tags[character_tag] = raw_tag
            expected_profile_keys.add(appearance_key(character_tag))

        trait_rows = con.execute(
            """SELECT ct.character_tag, ct.evidence_tag, ct.provenance,
                      ct.confidence, td.facet, td.value, td.label
               FROM character_traits ct
               JOIN trait_definitions td ON td.trait_slug=ct.trait_slug
               WHERE td.status='active'
               ORDER BY ct.character_tag, td.facet, td.value"""
        ).fetchall()
        traits_by_character: dict[str, list[sqlite3.Row]] = {}
        for row in trait_rows:
            character_tag = normalize_tag(row["character_tag"] or "")
            traits_by_character.setdefault(character_tag, []).append(row)

        expected_features: set[tuple[str, str, str]] = set()
        for row in profiles:
            character_tag = normalize_tag(row["character_tag"])
            key = appearance_key(character_tag)
            for tag in parse_tags(row["core_tags"]):
                expected_features.add((
                    key, canonical_facet(infer_facet(tag), tag), tag,
                ))
            for trait in traits_by_character.get(character_tag, []):
                tag = normalize_tag(trait["evidence_tag"] or trait["value"])
                if not tag:
                    raise ValueError(
                        f"character trait for {character_tag} has no evidence tag or value"
                    )
                expected_features.add((
                    key, canonical_facet(trait["facet"] or "", tag), tag,
                ))

        con.execute("BEGIN")
        deduplicated_features = _deduplicate_existing_features(con)
        sync_appearance_facet_catalog(con)
        for row in profiles:
            character_tag = normalize_tag(row["character_tag"])
            key = appearance_key(character_tag)
            con.execute(
                """INSERT OR IGNORE INTO character_appearance_profiles(
                    appearance_key, character_tag, variant_tag, display_name,
                    appearance_kind, is_default, status, confidence, provenance,
                    notes
                ) VALUES (?, ?, ?, ?, 'default', 1, 'published', ?, ?, '')""",
                (
                    key,
                    character_tag,
                    character_tag,
                    row["display_name"] or character_tag,
                    row["confidence"] or "high",
                    row["provenance"] or "legacy_curated_seed",
                ),
            )
            source_id = source_id_for(con, character_tag, row["source_url"])
            for tag in parse_tags(row["core_tags"]):
                feature_id = upsert_feature(
                    con,
                    key,
                    infer_facet(tag),
                    tag,
                    humanize_tag(tag),
                    row["confidence"] or "high",
                )
                link_feature(
                    con,
                    feature_id,
                    source_id,
                    tag,
                    "Migrated from character_profiles.core_tags.",
                )
            for trait in traits_by_character.get(character_tag, []):
                tag = normalize_tag(trait["evidence_tag"] or trait["value"])
                feature_id = upsert_feature(
                    con,
                    key,
                    canonical_facet(trait["facet"] or "", tag),
                    tag,
                    trait["value"] or humanize_tag(tag),
                    trait["confidence"] or "high",
                )
                link_feature(
                    con,
                    feature_id,
                    source_id,
                    tag,
                    "Migrated from character_traits and trait_definitions.",
                )

        catalog_count = sync_appearance_feature_catalog(con)
        con.execute(
            "INSERT OR REPLACE INTO appearance_schema_metadata(key, value) VALUES (?, ?)",
            ("migrated_at", datetime.now(timezone.utc).isoformat()),
        )
        con.execute(
            "INSERT OR REPLACE INTO appearance_schema_metadata(key, value) VALUES (?, ?)",
            ("seed_profile_count", str(len(profiles))),
        )

        actual_profiles = con.execute(
            "SELECT count(*) FROM character_appearance_profiles WHERE status <> 'retired'"
        ).fetchone()[0]
        actual_features = con.execute(
            "SELECT count(*) FROM character_appearance_features WHERE status <> 'retired'"
        ).fetchone()[0]
        actual_sources = con.execute(
            "SELECT count(*) FROM character_appearance_sources"
        ).fetchone()[0]
        linked_features = con.execute(
            """SELECT count(DISTINCT f.feature_id)
               FROM character_appearance_features f
               JOIN character_appearance_feature_sources fs
                 ON fs.feature_id=f.feature_id
               WHERE f.status <> 'retired'"""
        ).fetchone()[0]
        unlinked_catalog_features = con.execute(
            """SELECT count(*) FROM character_appearance_features f
               LEFT JOIN appearance_feature_catalog c
                 ON c.catalog_id=f.catalog_id AND c.canonical_tag=f.canonical_tag
               WHERE f.status <> 'retired' AND c.catalog_id IS NULL"""
        ).fetchone()[0]
        actual_profile_keys = {
            row[0] for row in con.execute(
                """SELECT appearance_key FROM character_appearance_profiles
                   WHERE status <> 'retired'"""
            )
        }
        missing_profiles = sorted(expected_profile_keys - actual_profile_keys)
        missing_features: list[str] = []
        unlinked_features: list[str] = []
        for key, facet, tag in sorted(expected_features):
            feature = con.execute(
                """SELECT feature_id FROM character_appearance_features
                   WHERE appearance_key=? AND facet=? AND canonical_tag=?
                     AND status <> 'retired'""",
                (key, facet, tag),
            ).fetchone()
            label = f"{key}/{facet}/{tag}"
            if feature is None:
                missing_features.append(label)
                continue
            linked = con.execute(
                """SELECT 1 FROM character_appearance_feature_sources
                   WHERE feature_id=? LIMIT 1""",
                (feature[0],),
            ).fetchone()
            if linked is None:
                unlinked_features.append(label)
        if missing_profiles or missing_features or unlinked_features or unlinked_catalog_features:
            raise RuntimeError(
                "appearance migration validation failed: "
                f"missing_profiles={missing_profiles[:5]}, "
                f"missing_features={missing_features[:5]}, "
                f"unlinked_features={unlinked_features[:5]}, "
                f"unlinked_catalog_features={unlinked_catalog_features}"
            )
        con.commit()
        return {
            "source_profiles": len(profiles),
            "source_traits": len(trait_rows),
            "appearance_profiles": actual_profiles,
            "appearance_features": actual_features,
            "appearance_sources": actual_sources,
            "linked_features": linked_features,
            "deduplicated_features": deduplicated_features,
            "catalog_features": catalog_count,
        }
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args()
    result = migrate(args.db)
    for key, value in result.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
