#!/usr/bin/env python3
"""One-time migration from the legacy structured-character tables.

The resulting runtime tables are owned by Weeb Alexandria. The legacy source
may be the current database (before the legacy tables are removed) or a raw
SQLite copy supplied with --source.
"""
from __future__ import annotations

import argparse
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from weeb_alexandria_mcp.owned_schema import ensure_owned_schema  # noqa: E402

DEFAULT_DB = ROOT / "tag_library.db"
LEGACY_TABLES = (
    "animadex_characters",
    "animadex_character_traits",
    "animadex_artists",
    "animadex_artist_categories",
    "animadex_loras",
    "animadex_categories",
)


def normalize(value: str) -> str:
    value = (value or "").strip().lower().replace("-", "_")
    return re.sub(r"_+", "_", re.sub(r"\s+", "_", value))


def table_names(con: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }


def read_legacy(source: sqlite3.Connection) -> tuple[list[dict], list[dict]]:
    names = table_names(source)
    if "animadex_characters" in names:
        character_table = "animadex_characters"
        trait_table = "animadex_character_traits"
    elif {"characters", "traits"} <= names:
        character_table = "characters"
        trait_table = "traits"
    else:
        raise RuntimeError("no supported legacy character/trait tables found")

    source.row_factory = sqlite3.Row
    characters = [dict(row) for row in source.execute(
        f"SELECT character, copyright, name, copyright_name, trigger, "
        f"core_tags, count, url FROM {character_table}"
    )]
    traits = [dict(row) for row in source.execute(
        f"SELECT character, facet, value, label FROM {trait_table}"
    )]
    return characters, traits


def migrate(db: Path, source_path: Path | None = None,
            drop_legacy: bool = False) -> tuple[int, int]:
    target = sqlite3.connect(db)
    target.row_factory = sqlite3.Row
    source = target
    separate_source = False
    if source_path is not None and source_path.resolve() != db.resolve():
        source = sqlite3.connect(source_path)
        separate_source = True

    try:
        characters, traits = read_legacy(source)
        ensure_owned_schema(target)

        target.executemany(
            """INSERT OR REPLACE INTO character_profiles(
                character_tag, display_name, display_name_normalized,
                work_tag, work_name, trigger, core_tags, source_count,
                source_url, provenance, confidence
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    row["character"],
                    row["name"] or row["character"],
                    normalize(row["name"] or row["character"]),
                    row["copyright"],
                    row["copyright_name"],
                    row["trigger"] or "",
                    row["core_tags"] or "",
                    int(row["count"] or 0),
                    row["url"] or "",
                    "legacy_curated_seed",
                    "high",
                )
                for row in characters
            ],
        )

        definitions: dict[str, tuple] = {}
        for row in traits:
            slug = normalize(row["value"])
            definitions.setdefault(
                slug,
                (
                    slug,
                    row["facet"],
                    row["value"],
                    row["label"],
                    "",
                    "legacy_curated_seed",
                    "high",
                    "active",
                ),
            )
        target.executemany(
            """INSERT OR REPLACE INTO trait_definitions(
                trait_slug, facet, value, label, aliases,
                provenance, confidence, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            definitions.values(),
        )
        target.executemany(
            """INSERT OR REPLACE INTO character_traits(
                character_tag, trait_slug, evidence_tag, provenance, confidence
            ) VALUES (?, ?, ?, ?, ?)""",
            [
                (
                    row["character"],
                    normalize(row["value"]),
                    normalize(row["value"]),
                    "legacy_curated_seed",
                    "high",
                )
                for row in traits
            ],
        )
        metadata = [
            ("schema_version", "1"),
            ("system", "owned_character_traits"),
            ("seed_source", "legacy_structured_character_export"),
            ("migrated_at", datetime.now(timezone.utc).isoformat()),
            ("seed_profile_count", str(len(characters))),
            ("seed_trait_count", str(len(traits))),
        ]
        target.executemany(
            "INSERT OR REPLACE INTO trait_system_metadata(key, value) VALUES (?, ?)",
            metadata,
        )
        target.commit()

        actual_profiles = target.execute(
            "SELECT count(*) FROM character_profiles"
        ).fetchone()[0]
        actual_traits = target.execute(
            "SELECT count(*) FROM character_traits"
        ).fetchone()[0]
        if actual_profiles < len(characters) or actual_traits < len(traits):
            raise RuntimeError(
                f"migration validation failed: profiles={actual_profiles}, "
                f"traits={actual_traits}"
            )

        if drop_legacy:
            for table in LEGACY_TABLES:
                if table in table_names(target):
                    target.execute(f'DROP TABLE "{table}"')
            target.commit()
        return actual_profiles, actual_traits
    finally:
        if separate_source:
            source.close()
        target.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument(
        "--source", type=Path,
        help="Optional raw legacy database; default reads legacy tables from --db.",
    )
    parser.add_argument(
        "--drop-legacy", action="store_true",
        help="Drop legacy animadex_* tables after validation.",
    )
    args = parser.parse_args()
    profiles, traits = migrate(args.db, args.source, args.drop_legacy)
    print(f"Owned profiles: {profiles}")
    print(f"Owned character traits: {traits}")
    print(f"Dropped legacy tables: {args.drop_legacy}")


if __name__ == "__main__":
    main()
