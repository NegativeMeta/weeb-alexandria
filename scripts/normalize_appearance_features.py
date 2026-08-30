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
    sync_appearance_facet_catalog,
    sync_appearance_feature_catalog,
)
from scripts.migrate_appearance_profiles import _deduplicate_existing_features  # noqa: E402

DEFAULT_DB = ROOT / "tag_library.db"


def normalize(db: Path) -> dict[str, int]:
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    try:
        ensure_appearance_schema(con)
        con.execute("BEGIN")
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
        if deduplicated or normalized_at is None:
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
