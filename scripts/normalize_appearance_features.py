#!/usr/bin/env python3
"""Normalize existing appearance assignments into the shared feature catalog.

Unlike migrate_appearance_profiles.py, this command does not rebuild canonical
appearance data from legacy character_profiles. It only normalizes the current
appearance tables, preserving profile-specific values and evidence links.
"""
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
    normalize_appearance_tag,
    sync_appearance_facet_catalog,
    sync_appearance_feature_catalog,
)
from scripts.migrate_appearance_profiles import _deduplicate_existing_features  # noqa: E402

DEFAULT_DB = ROOT / "tag_library.db"


def _merge_feature_sources(con: sqlite3.Connection, keeper_id: int, duplicate_id: int) -> None:
    con.execute(
        """INSERT OR IGNORE INTO character_appearance_feature_sources(
               feature_id, source_id, polarity, observed_tag, support_count,
               sample_size, evidence_text, confidence
           ) SELECT ?, source_id, polarity, observed_tag, support_count,
                    sample_size, evidence_text, confidence
           FROM character_appearance_feature_sources
           WHERE feature_id=?""",
        (keeper_id, duplicate_id),
    )
    con.execute(
        "DELETE FROM character_appearance_feature_sources WHERE feature_id=?",
        (duplicate_id,),
    )
    con.execute(
        "DELETE FROM character_appearance_features WHERE feature_id=?",
        (duplicate_id,),
    )


def _normalize_canonical_aliases(con: sqlite3.Connection) -> tuple[int, int]:
    rows = con.execute(
        """SELECT feature_id, appearance_key, canonical_tag
           FROM character_appearance_features
           WHERE status <> 'retired'
           ORDER BY feature_id"""
    ).fetchall()
    changed = 0
    merged = 0
    for row in rows:
        target_tag = normalize_appearance_tag(row["canonical_tag"])
        if target_tag == row["canonical_tag"]:
            continue
        existing = con.execute(
            """SELECT feature_id FROM character_appearance_features
               WHERE appearance_key=? AND canonical_tag=? AND feature_id<>?
               ORDER BY feature_id LIMIT 1""",
            (row["appearance_key"], target_tag, row["feature_id"]),
        ).fetchone()
        if existing is None:
            con.execute(
                "UPDATE character_appearance_features SET canonical_tag=? WHERE feature_id=?",
                (target_tag, row["feature_id"]),
            )
            changed += 1
        else:
            _merge_feature_sources(con, int(existing[0]), int(row["feature_id"]))
            changed += 1
            merged += 1
    return changed, merged


def normalize(db: Path) -> dict[str, int]:
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    try:
        ensure_appearance_schema(con)
        con.execute("BEGIN")
        canonical_tag_changes, merged_aliases = _normalize_canonical_aliases(con)
        deduplicated = _deduplicate_existing_features(con)
        sync_appearance_facet_catalog(con)
        catalog_features = sync_appearance_feature_catalog(con)
        active_features = con.execute(
            "SELECT count(*) FROM character_appearance_features WHERE status <> 'retired'"
        ).fetchone()[0]
        active_catalog = con.execute(
            "SELECT count(*) FROM appearance_feature_catalog WHERE status='active'"
        ).fetchone()[0]
        unlinked = con.execute(
            """SELECT count(*) FROM character_appearance_features f
               LEFT JOIN appearance_feature_catalog c
                 ON c.catalog_id=f.catalog_id AND c.canonical_tag=f.canonical_tag
               WHERE f.status <> 'retired' AND c.catalog_id IS NULL"""
        ).fetchone()[0]
        duplicate_assignments = con.execute(
            """SELECT count(*) FROM (
                   SELECT appearance_key, catalog_id
                   FROM character_appearance_features
                   WHERE status <> 'retired'
                   GROUP BY appearance_key, catalog_id
                   HAVING count(*) > 1
               )"""
        ).fetchone()[0]
        evidence_missing = con.execute(
            """SELECT count(*) FROM character_appearance_features f
               LEFT JOIN character_appearance_feature_sources fs
                 ON fs.feature_id=f.feature_id
               WHERE f.status IN ('reviewed', 'published')
                 AND fs.feature_id IS NULL"""
        ).fetchone()[0]
        if unlinked or duplicate_assignments or evidence_missing:
            raise RuntimeError(
                "appearance normalization validation failed: "
                f"unlinked={unlinked}, duplicates={duplicate_assignments}, "
                f"evidence_missing={evidence_missing}"
            )
        normalized_at = con.execute(
            "SELECT value FROM appearance_schema_metadata WHERE key='normalized_at'"
        ).fetchone()
        if canonical_tag_changes or deduplicated or normalized_at is None:
            con.execute(
                """INSERT INTO appearance_schema_metadata(key, value) VALUES (?, ?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                ("normalized_at", datetime.now(timezone.utc).isoformat()),
            )
        con.execute(
            """INSERT INTO appearance_schema_metadata(key, value) VALUES (?, ?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
            ("normalized_catalog_count", str(active_catalog)),
        )
        con.commit()
        return {
            "deduplicated_features": deduplicated,
            "canonical_tag_changes": canonical_tag_changes,
            "merged_aliases": merged_aliases,
            "catalog_features": catalog_features,
            "active_features": active_features,
            "active_catalog": active_catalog,
            "unlinked": unlinked,
            "duplicate_assignments": duplicate_assignments,
            "evidence_missing": evidence_missing,
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
    for key, value in normalize(args.db).items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
