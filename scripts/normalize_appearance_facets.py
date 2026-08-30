#!/usr/bin/env python3
"""Normalize controlled appearance facets without deleting evidence.

This migration changes only facet classification and facet-catalog links. It
keeps feature IDs whenever possible, merges duplicate assignments safely, and
retains every feature-source link.
"""
from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.migrate_appearance_profiles import canonical_facet  # noqa: E402
from weeb_alexandria_mcp.appearance_schema import (  # noqa: E402
    ensure_appearance_schema,
    sync_appearance_facet_catalog,
)

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


def normalize_facets(db: Path) -> dict[str, int]:
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    try:
        ensure_appearance_schema(con)
        con.execute("BEGIN")
        rows = con.execute(
            """SELECT feature_id, appearance_key, facet, canonical_tag
               FROM character_appearance_features
               WHERE status <> 'retired'
               ORDER BY feature_id"""
        ).fetchall()
        groups: dict[tuple[str, str], list[sqlite3.Row]] = {}
        for row in rows:
            groups.setdefault((row["appearance_key"], row["canonical_tag"]), []).append(row)

        facet_changes = 0
        merged_features = 0
        for (_, canonical_tag), group in groups.items():
            target = canonical_facet(group[0]["facet"], canonical_tag)
            keeper = next((row for row in group if row["facet"] == target), group[0])
            if keeper["facet"] != target:
                con.execute(
                    "UPDATE character_appearance_features SET facet=? WHERE feature_id=?",
                    (target, keeper["feature_id"]),
                )
                facet_changes += 1
            for duplicate in group:
                if duplicate["feature_id"] == keeper["feature_id"]:
                    continue
                _merge_feature_sources(con, keeper["feature_id"], duplicate["feature_id"])
                merged_features += 1

        facet_links = sync_appearance_facet_catalog(con)
        active_features = con.execute(
            "SELECT count(*) FROM character_appearance_features WHERE status <> 'retired'"
        ).fetchone()[0]
        active_unclassified = con.execute(
            """SELECT count(*) FROM character_appearance_features
               WHERE status <> 'retired' AND facet='unclassified'"""
        ).fetchone()[0]
        unlinked_facets = con.execute(
            """SELECT count(*) FROM character_appearance_features f
               LEFT JOIN appearance_facet_catalog c
                 ON c.facet_id=f.facet_id AND c.facet_key=f.facet
               WHERE f.status <> 'retired' AND c.facet_id IS NULL"""
        ).fetchone()[0]
        duplicate_assignments = con.execute(
            """SELECT count(*) FROM (
                   SELECT appearance_key, canonical_tag
                   FROM character_appearance_features
                   WHERE status <> 'retired'
                   GROUP BY appearance_key, canonical_tag
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
        if active_unclassified or unlinked_facets or duplicate_assignments or evidence_missing:
            raise RuntimeError(
                "appearance facet normalization validation failed: "
                f"unclassified={active_unclassified}, unlinked_facets={unlinked_facets}, "
                f"duplicates={duplicate_assignments}, evidence_missing={evidence_missing}"
            )

        changed = facet_changes or merged_features
        normalized_at = con.execute(
            "SELECT value FROM appearance_schema_metadata WHERE key='facets_normalized_at'"
        ).fetchone()
        if changed or normalized_at is None:
            con.execute(
                """INSERT INTO appearance_schema_metadata(key, value) VALUES (?, ?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value
                   WHERE appearance_schema_metadata.value <> excluded.value""",
                ("facets_normalized_at", datetime.now(timezone.utc).isoformat()),
            )
        con.execute(
            """INSERT INTO appearance_schema_metadata(key, value) VALUES (?, ?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value
               WHERE appearance_schema_metadata.value <> excluded.value""",
            ("normalized_facet_count", str(facet_links)),
        )
        con.commit()
        return {
            "facet_changes": facet_changes,
            "merged_features": merged_features,
            "active_features": active_features,
            "facet_catalog": con.execute(
                "SELECT count(*) FROM appearance_facet_catalog WHERE status='active'"
            ).fetchone()[0],
            "active_unclassified": active_unclassified,
            "unlinked_facets": unlinked_facets,
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
    for key, value in normalize_facets(args.db).items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
