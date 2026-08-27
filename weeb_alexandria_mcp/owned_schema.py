"""Owned character-profile and trait schema.

The active MCP uses these tables instead of the legacy structured-character
schema. The schema is intentionally independent of any upstream project.
"""
from __future__ import annotations

import sqlite3

OWNED_SCHEMA_VERSION = "1"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS character_profiles (
    character_tag TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    display_name_normalized TEXT NOT NULL,
    work_tag TEXT,
    work_name TEXT,
    trigger TEXT NOT NULL DEFAULT '',
    core_tags TEXT NOT NULL DEFAULT '',
    source_count INTEGER NOT NULL DEFAULT 0,
    source_url TEXT NOT NULL DEFAULT '',
    provenance TEXT NOT NULL DEFAULT 'curated_seed',
    confidence TEXT NOT NULL DEFAULT 'high'
);
CREATE INDEX IF NOT EXISTS idx_character_profiles_name
    ON character_profiles(display_name_normalized);
CREATE INDEX IF NOT EXISTS idx_character_profiles_work
    ON character_profiles(work_tag);
CREATE INDEX IF NOT EXISTS idx_character_profiles_count
    ON character_profiles(source_count DESC, character_tag);

CREATE TABLE IF NOT EXISTS trait_definitions (
    trait_slug TEXT PRIMARY KEY,
    facet TEXT NOT NULL,
    value TEXT NOT NULL,
    label TEXT NOT NULL,
    aliases TEXT NOT NULL DEFAULT '',
    provenance TEXT NOT NULL DEFAULT 'curated_seed',
    confidence TEXT NOT NULL DEFAULT 'high',
    status TEXT NOT NULL DEFAULT 'active'
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_trait_definitions_facet_value
    ON trait_definitions(facet, value);
CREATE INDEX IF NOT EXISTS idx_trait_definitions_facet
    ON trait_definitions(facet, status);

CREATE TABLE IF NOT EXISTS character_traits (
    character_tag TEXT NOT NULL,
    trait_slug TEXT NOT NULL,
    evidence_tag TEXT NOT NULL,
    provenance TEXT NOT NULL DEFAULT 'curated_seed',
    confidence TEXT NOT NULL DEFAULT 'high',
    PRIMARY KEY(character_tag, trait_slug)
);
CREATE INDEX IF NOT EXISTS idx_character_traits_trait
    ON character_traits(trait_slug, character_tag);
CREATE INDEX IF NOT EXISTS idx_character_traits_character
    ON character_traits(character_tag, trait_slug);

CREATE TABLE IF NOT EXISTS trait_system_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def ensure_owned_schema(con: sqlite3.Connection) -> None:
    """Create the independent profile/trait tables if they are absent."""
    con.executescript(SCHEMA_SQL)
    con.executemany(
        "INSERT OR IGNORE INTO trait_system_metadata(key, value) VALUES (?, ?)",
        [
            ("schema_version", OWNED_SCHEMA_VERSION),
            ("system", "owned_character_traits"),
        ],
    )
    con.commit()
