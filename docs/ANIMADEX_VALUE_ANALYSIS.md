# Historical Structured-Data Analysis and Migration Record

**Date:** 2026-08-27  
**Status:** migration completed and verified
**Purpose:** record what was retained from the historical structured export, what was discarded, and how the active runtime became independent of its legacy schema.

## Executive result

The active Weeb Alexandria database no longer contains or queries the legacy `animadex_*` tables.

The useful structured information was copied into an owned schema:

| Owned table | Current rows | Purpose |
|---|---:|---|
| `character_profiles` | 20 | Curated character identity, work, trigger, core tags, count, and URL |
| `trait_definitions` | 24 | Unique facet/value/label definitions |
| `character_traits` | 84 | Character-to-trait assignments with evidence and confidence |
| `trait_system_metadata` | 6 | Schema and seed metadata |

The 84 assignments come from four initial facets: `gender`, `eye_color`, `hair_color`, and `hair_length`. Repeated values are stored once in `trait_definitions` and referenced by `trait_slug`.

`raw/animadex/animadex.db` remains outside the runtime as an audit and recovery source. The MCP server does not open it. The one-time migration script can read it when a future rebuild needs to recover the initial seed.

## Decision and scope

The historical structured data was useful as a seed, but it was not a complete character or artist catalogue. The long-term system is therefore based on:

- the broad `tags` table for discovery;
- `wiki`, aliases, implications, and source metadata for context;
- the derived character-context index for franchise resolution;
- the owned profile/trait tables for curated structured enrichment.

A missing owned profile does not mean that a character is missing from the database. It can still exist as a normal character tag with wiki, aliases, popularity, or context evidence.

## Pre-migration inventory

The source snapshot contained:

| Legacy table | Rows | Disposition |
|---|---:|---|
| `animadex_characters` | 20 | Mapped to `character_profiles` |
| `animadex_character_traits` | 84 | Mapped to `trait_definitions` and `character_traits` |
| `animadex_artists` | 10 | Not retained as a separate table; artist discovery uses global `tags` |
| `animadex_loras` | 0 | Discarded as empty; `get_character` keeps an empty compatibility list |
| `animadex_categories` | 0 | Discarded as empty |
| `animadex_artist_categories` | 0 | Discarded as empty |

The historical 20 profiles were never treated as the total character universe. The general database contains substantially broader character and artist tag coverage.

## Field mapping

### Character profiles

| Historical field | Owned field | Notes |
|---|---|---|
| `character` | `character_tag` | Stable tag key |
| `name` | `display_name` | Human-readable name |
| normalized name | `display_name_normalized` | Search normalization using tag-style separators |
| `copyright` | `work_tag` | Work/franchise tag |
| `copyright_name` | `work_name` | Human-readable work name |
| `trigger` | `trigger` | Search/prompt trigger |
| `core_tags` | `core_tags` | Curated prompt-oriented bundle |
| `count` | `source_count` | Historical popularity snapshot |
| `url` | `source_url` | Convenience source link |

The owned schema also records `provenance` and `confidence`. The initial rows use `legacy_curated_seed` provenance and `high` confidence as a statement about the migration quality, not as a claim that the upstream snapshot is complete or current.

### Traits

Each historical trait row is normalized into a stable `trait_slug`, for example:

```text
white hair -> white_hair
```

`trait_definitions` stores the facet, original tag-like value, user-facing label, aliases, provenance, confidence, and status. `character_traits` stores the character key, trait key, evidence tag, provenance, and confidence.

This preserves the semantic filtering capability without requiring the historical table names or schema.

## Data deliberately not migrated

The raw structured export also had asset/search fields that were not part of the active runtime:

- `imgname`
- `thumbname`
- `search_blob`
- `image_version`

No corresponding image asset pipeline is shipped in the active project. `search_blob` is reproducible from searchable fields, and `image_version` was not informative in the inspected snapshot. The raw database remains available if a future asset migration is justified.

No artist table was recreated because the historical artist sample contained only 10 rows and the global `tags` table is the broader, canonical discovery surface for artist tags. No LoRA table was recreated because the source contained zero LoRA associations.

## Runtime changes

`weeb_alexandria_mcp/server.py` now:

- reads structured characters from `character_profiles`;
- resolves semantic filters through `character_traits` joined to `trait_definitions`;
- reads artist and copyright discovery from global `tags` plus owned-profile coverage;
- returns the structured search namespace as `entities` instead of the former legacy namespace;
- reports `structured_mode: owned_local_tables` from `get_sources_status`;
- keeps tag/wiki/context fallback behavior for characters without an owned profile;
- never opens `raw/animadex/animadex.db`.

The `get_character` response still includes `loras: []` for compatibility, but there is no active legacy LoRA table behind it.

## Migration and recovery commands

From the repository root:

```bash
# Seed the owned tables from the current database while legacy tables exist.
.venv/Scripts/python.exe scripts/migrate_owned_traits.py

# One-time removal after the server and tests use the owned schema.
.venv/Scripts/python.exe scripts/migrate_owned_traits.py --drop-legacy

# Recover/reseed the owned tables from the preserved raw source.
.venv/Scripts/python.exe scripts/migrate_owned_traits.py \
  --source raw/animadex/animadex.db
```

The `--drop-legacy` operation was executed only after a separate checkpoint copy was made and validated. The active database passed `PRAGMA integrity_check` after the drop. The local checkpoint is outside the repository and is not published.

## Verification evidence

The completed migration was verified with:

```bash
.venv/Scripts/python.exe -m unittest tests.test_search -v
```

Result: **27 tests passed**.

The regression suite covers:

- existence of the owned tables;
- profile and trait retrieval for `hatsune_miku`;
- semantic filtering (`hair_color=white`);
- the `entities` search namespace;
- source-status reporting;
- removal of all `animadex_*` tables;
- aliases, redirects, fuzzy confidence, ambiguity, and franchise context.

The active database verification reported:

```text
PRAGMA integrity_check = ok
legacy animadex_* tables = []
character_profiles = 20
trait_definitions = 24
character_traits = 84
raw/animadex/animadex.db = present
```

## Future owned-system work

The current tables are a migrated seed, not the final automatic trait extractor. Future iterations can extend the owned vocabulary and evidence model with:

- clothing and accessories;
- species and non-human attributes;
- color and hairstyle refinements;
- explicit source records and timestamps;
- per-source evidence rather than one seed provenance value;
- human review state and conflict handling;
- canonical tag validation against the global tag library;
- optional normalized `tag_slugs` alongside the human-readable `core_tags`.

Those additions should extend the owned schema and keep global tag discovery independent from curated profile coverage.

## Related files

- `weeb_alexandria_mcp/owned_schema.py` — owned schema definition.
- `scripts/migrate_owned_traits.py` — one-time seed migration/recovery utility.
- `tests/test_search.py` — runtime and migration regressions.
- `raw/animadex/animadex.db` — preserved audit/recovery source, not runtime input.
