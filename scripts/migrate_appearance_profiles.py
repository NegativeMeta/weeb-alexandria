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
    ensure_appearance_schema,
    infer_facet,
    humanize_tag,
    normalize_tag,
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
    feature_facet = facet or infer_facet(canonical_tag) or "unclassified"
    con.execute(
        """INSERT INTO character_appearance_features(
            appearance_key, facet, value, canonical_tag, role, status,
            confidence, display_order
        ) VALUES (?, ?, ?, ?, 'present', 'published', ?, 0)
        ON CONFLICT(appearance_key, facet, canonical_tag) DO UPDATE SET
            value=excluded.value,
            confidence=CASE
                WHEN character_appearance_features.confidence='high' THEN 'high'
                ELSE excluded.confidence
            END""",
        (
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
            traits_by_character.setdefault(row["character_tag"], []).append(row)

        con.execute("BEGIN")
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
                    infer_facet(tag) or "unclassified",
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
                    trait["facet"] or "unclassified",
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

        con.execute(
            "INSERT OR REPLACE INTO appearance_schema_metadata(key, value) VALUES (?, ?)",
            ("migrated_at", datetime.now(timezone.utc).isoformat()),
        )
        con.execute(
            "INSERT OR REPLACE INTO appearance_schema_metadata(key, value) VALUES (?, ?)",
            ("seed_profile_count", str(len(profiles))),
        )
        con.commit()

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
        if actual_profiles < len(profiles) or actual_features < linked_features:
            raise RuntimeError(
                f"appearance migration validation failed: profiles={actual_profiles}, "
                f"features={actual_features}, linked_features={linked_features}"
            )
        return {
            "source_profiles": len(profiles),
            "source_traits": len(trait_rows),
            "appearance_profiles": actual_profiles,
            "appearance_features": actual_features,
            "appearance_sources": actual_sources,
            "linked_features": linked_features,
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
