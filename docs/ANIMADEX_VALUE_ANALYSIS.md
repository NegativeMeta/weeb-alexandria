# Weeb Alexandria — AnimaDex Value Analysis

**Date:** 2026-08-27  
**Audience:** Future agents and maintainers  
**Scope:** Determine which migrated AnimaDex tables and fields provide real value beyond `tags`, `wiki`, aliases, and implications.  
**Sources inspected:** `tag_library.db`, `raw/animadex/animadex.db`, `weeb_alexandria_mcp/server.py`, and the local AnimaDex import/build metadata.  
**Status:** Evidence-based audit; no schema changes are made by this document.

## Executive conclusion

The migrated AnimaDex data is useful as a **small structured enrichment layer**, not as a complete character or artist catalogue.

The highest-value material is:

1. `animadex_characters`: curated character identity, franchise association, prompt-ready core tags, and source links.
2. `animadex_character_traits`: normalized facet/value/label records that make structured filtering possible.
3. The original AnimaDex asset/search metadata (`imgname`, `thumbname`, `search_blob`, `image_version`) that was not migrated into the active database.

The lower-value material is:

- `animadex_artists`: useful as a generation/style catalogue, but only 10 rows are present.
- `animadex_artist_categories`: empty.
- `animadex_categories`: empty.
- `animadex_loras`: empty, so the current `get_character` response always returns an empty `loras` list.

The 20 characters and 10 artists must not be presented as global totals. The general `tags` table remains the broad source of character and artist coverage.

## Inventory observed

| Table | Rows | Current value | Recommendation |
|---|---:|---|---|
| `animadex_characters` | 20 | Structured identity, copyright, trigger, core prompt tags, count, URL | Keep and expose as curated enrichment |
| `animadex_character_traits` | 84 | Four structured facets: gender, eye color, hair color, hair length | Keep; this is the strongest unique capability |
| `animadex_artists` | 10 | Artist trigger, popularity snapshot, URL, style-catalogue seed | Keep as auxiliary data; expand only from a complete export |
| `animadex_artist_categories` | 0 | No current information | Preserve schema for compatibility, do not advertise as populated |
| `animadex_categories` | 0 | No current information | Preserve schema for compatibility, do not advertise as populated |
| `animadex_loras` | 0 | No LoRA associations | Preserve only if future imports will populate it |

The original `raw/animadex/animadex.db` contains the same row counts. Its file size is 110,592 bytes, compared with 866,381,824 bytes for `tag_library.db`.

## What `animadex_characters` contributes

### Structured identity and work association

Each of the 20 rows has non-empty values for:

- canonical character slug;
- human-readable name;
- normalized display name;
- canonical copyright/work slug;
- human-readable copyright/work name;
- generation/search trigger;
- prompt-oriented `core_tags`;
- AnimaDex/Danbooru count snapshot;
- direct Danbooru search URL.

There are 13 distinct copyright/work values among the 20 characters. The character-to-work relationship is useful for contextual resolution and generation, although the same work tags are usually also present in the general `tags` table.

### Coverage is partial and inconsistent

Against the active unified database:

- 19/20 AnimaDex character slugs have some exact row in `tags`.
- 17/20 have exact `category_name='character'` rows.
- 17/20 have exact wiki rows.
- 19/20 have an exact work/copyright tag row.

The exceptions demonstrate why the tables are useful as enrichment but cannot be treated as authority for the entire database:

- `9s_(nier_automata)` has no exact active tag row.
- `2b_(nier_automata)` is present as an alias rather than an active character tag.
- `emilia_(re_zero)` is present as a `general` tag rather than a character/copyright tag in the current snapshot.

### `core_tags` is valuable as a bundled prompt preset

There are 143 core-tag tokens across the 20 characters. All 143 match existing tag names after the expected space-to-underscore normalization.

That means the individual terms are not necessarily unique to AnimaDex, but the **curated bundle and its ordering** are useful for:

- image-generation prompts;
- quick character summaries;
- UI cards;
- fallback character recommendations;
- reproducible generation presets.

The active server currently returns these terms as `tags` from `get_character`, preserving their human-readable form. A future enhancement could also return a separate canonical `tag_slugs` list instead of forcing clients to normalize phrases themselves.

### Counts and URLs are convenience fields, not unique facts

The AnimaDex `count` is a useful popularity snapshot, but it does not consistently equal the highest current `tags.post_count` value. Differences are expected because the sources and snapshots are not identical.

The URL is convenient but derivable from the Danbooru slug. It should not be treated as the primary identity key.

## What `animadex_character_traits` contributes

This table contains 84 rows for all 20 characters and four facets:

| Facet | Rows | Characters |
|---|---:|---:|
| `eye_color` | 22 | 20 |
| `gender` | 20 | 20 |
| `hair_color` | 21 | 20 |
| `hair_length` | 21 | 20 |

Each record has:

- a character key;
- a stable facet name;
- a tag-like value such as `white hair`;
- a user-facing label such as `White`.

The values correspond to general tags after normalization (`white hair` → `white_hair`), but the **facet/value/label structure does not exist in that form in the general tag tables**. This is the clearest reason to keep the AnimaDex character layer.

The current MCP uses these rows to implement filters such as:

```text
hair_color=white  → 4 characters
hair_length=short → 5 characters
eye_color=red     → 5 characters
gender=1boy       → 2 characters
copyright=genshin_impact → 5 characters
```

This is a real capability difference from a plain tag search: the client can request a semantic facet instead of manually composing tag conditions.

## What `animadex_artists` contributes

The current table contains only 10 artists. All 10 have:

- an exact tag row;
- `category_name='artist'`;
- a non-empty trigger;
- a count snapshot;
- a direct Danbooru search URL.

Only 3 of the 10 have exact wiki rows, and every `score` value is null. Therefore this is currently a **small style-catalogue seed**, not a complete artist knowledge source.

It is still useful for the image-generation workflow because the trigger and URL provide a ready-to-use style entry. It becomes substantially more valuable only after importing a complete, versioned AnimaDex artist export.

## Data omitted during migration

The common columns of the raw and migrated character rows are byte-for-byte identical, and the common columns of the raw and migrated artist rows are also identical. However, the raw database contains additional non-empty columns that are missing from `tag_library.db`:

### Characters

```text
imgname
thumbname
search_blob
image_version
```

All 20 characters have non-empty, distinct `imgname`, `thumbname`, and `search_blob` values. `image_version` is present for all 20 rows but currently has only one distinct value: `0`.

Example filenames include:

```text
hatsune miku, vocaloid.png
hatsune miku, vocaloid.webp
```

### Artists

The same four columns are present for all 10 raw artist rows:

```text
imgname
thumbname
search_blob
image_version
```

All `imgname`, `thumbname`, and `search_blob` values are non-empty and distinct. `image_version` is again constant at `0`.

### Interpretation

These omitted fields have different levels of value:

- `imgname` and `thumbname`: useful if the image/thumb asset pipeline is restored. No PNG files were found in the active repository, so they are currently pointers without corresponding shipped assets.
- `search_blob`: useful as a prebuilt search field, but it is reproducible from the other columns and should not be treated as canonical data.
- `image_version`: useful for cache invalidation after an asset pipeline exists, but currently constant and therefore not informative.

## Raw database versus migrated tables

The migration preserved the row data for the shared columns, but not the complete raw schema:

- `characters`: 20 raw rows and 20 migrated rows; 4 raw columns omitted.
- `traits`: 84 raw rows and 84 migrated rows; rows and columns identical.
- `artists`: 10 raw rows and 10 migrated rows; 4 raw columns omitted.
- `artist_categories`: 0 rows in both.
- `loras`: 0 rows in both.
- `categories`: 0 rows in both.

The raw database metadata contains only:

```text
characters_built_at = 2026-07-11 20:13:24
artists_built_at    = 2026-07-11 20:13:24
```

It does not identify a catalogue version, upstream commit, source license snapshot, or source row count beyond the tables themselves. Future imports should add explicit provenance metadata.

## Where the active MCP uses AnimaDex

The current server uses the migrated tables in these paths:

- `search_knowledge`: returns AnimaDex characters, artists, and copyright aggregates alongside general tag results.
- `search_characters`: uses `animadex_characters` and `animadex_character_traits` for semantic filtering.
- `get_character`: returns the structured character record, core tags, traits, and the currently empty LoRA list.
- `get_sources_status`: reports counts for the migrated AnimaDex tables.

There is no current endpoint dedicated to `animadex_artist_categories` or `animadex_categories`, and the LoRA endpoint is structurally present but has no rows to return.

## Recommended extraction priorities

### Priority 1 — Keep the structured character layer

Keep `animadex_characters` and `animadex_character_traits` in the active database. Treat them as a curated/structured subset, not as the complete character universe.

Preserve:

- character-to-work relation;
- trigger;
- core prompt tags;
- facet/value/label traits;
- source count and URL as provenance/convenience fields.

### Priority 2 — Restore the omitted asset/search metadata selectively

If the AnimaDex image catalogue or UI is revived, migrate the four omitted fields into either:

- the two active tables; or
- a separate `animadex_assets` table keyed by character/artist.

Prefer a separate asset table if asset versions, local paths, CDN URLs, or multiple resolutions will be added later. Do not migrate `search_blob` as an unquestioned source of truth; regenerate it or replace it with a proper indexed search field.

### Priority 3 — Add provenance metadata

Future imports should record at least:

- source catalogue version or export version;
- build timestamp;
- upstream source URL;
- row counts;
- source database hash or size;
- schema version;
- whether image assets were included.

This should apply both to the raw AnimaDex copy and the migrated tables.

### Priority 4 — Expand artists only with a complete export

Retain the current artist table for compatibility and generation support, but do not spend effort building artist-specific ranking or category logic around 10 rows and null scores. First obtain/import a complete, versioned catalogue.

### Priority 5 — Defer empty tables

Do not delete `animadex_loras`, `animadex_categories`, or `animadex_artist_categories` immediately because their presence preserves compatibility with the original schema and current response shape. Mark them as empty/unavailable until an import actually populates them.

## Do not infer

- The 20 AnimaDex characters are not all characters in Weeb Alexandria.
- A missing AnimaDex row does not mean the character is absent from `tags`.
- An AnimaDex count is not automatically the current canonical popularity count.
- `core_tags` is a curated prompt preset, not an exhaustive list of every valid appearance tag.
- The MIT repository license automatically covers upstream-derived database records.
- The raw image filenames prove that the corresponding image files are available; the active repository currently has no PNG assets.

## Suggested next implementation tasks

1. Add an explicit `animadex_provenance` table or metadata keys for catalogue version and build information.
2. Add a regression test ensuring `search_characters` keeps using facet/value/label filters.
3. Decide whether asset fields belong in the active character/artist tables or a separate `animadex_assets` table.
4. Return both human-readable `tags` and normalized `tag_slugs` from `get_character`.
5. Keep global character discovery in `tags`/wiki/context indexes, using AnimaDex only for structured enrichment.
6. Revisit the empty LoRA/category tables only after importing a source snapshot that contains those records.

## Reproduction commands

From the repository root:

```bash
.venv/Scripts/python.exe -m unittest tests.test_search -v
.venv/Scripts/python.exe scripts/build_context_index.py
```

The database audit used read-only SQLite queries against:

```text
tag_library.db
raw/animadex/animadex.db
```
