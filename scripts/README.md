# Scripts

Standalone helper scripts used by the active Weeb Alexandria data
pipeline. They are not imported by the MCP server; they are tools you run
by hand (or get shelled out to by the orchestrator).

## `generate_dataset.py`

The ComfyUI driver. Renders character / artist images from a CSV using
a ComfyUI workflow JSON.

The pipeline orchestrator shells out to this script when
`[generation].workflow_file` is configured. If you don't use ComfyUI,
replace this file with your own generator -- see `docs/pipeline.md`
for the contract. As long as your replacement:

- accepts `--out <path>` and writes the image at that path,
- returns exit code 0 on success,

the orchestrator doesn't care what's inside.

## `clean_explicit_tags.py`

One-off helper that strips NSFW / explicit tags from a Danbooru character CSV. Run it on your source CSV before feeding it to a compatible local importer.

## `build_context_index.py`

Builds the derived character/franchise context index at `data/character_context.sqlite`. It records the source SHA-256, SQLite sidecar state, row counts, and schema version. The builder writes a temporary database and replaces the previous output only after a successful build.

```bash
.venv/Scripts/python.exe scripts/build_context_index.py
```

## `build_search_index.py`

Builds the optional derived SQLite FTS5 index used for fast partial tag and alias searches:

```bash
.venv/Scripts/python.exe scripts/build_search_index.py
```

The output is `data/tag_search.sqlite`. It is reproducible from `tag_library.db`, records the source SHA-256 and indexed row count, and is excluded from Git because it is a generated artifact. The builder writes to a temporary database and replaces the previous output only after a successful build.

## `migrate_owned_traits.py`

One-time migration utility for the owned structured character schema. It
copies the historical character and trait seed into
`character_profiles`, `trait_definitions`, and `character_traits`. After
the server and tests have been switched over, `--drop-legacy` removes the
old structured tables from the active database. The preserved raw database
can be supplied with `--source` for recovery; it is not opened by the MCP
runtime.

## `migrate_appearance_profiles.py`

Creates the owned appearance schema and idempotently migrates existing
`character_profiles.core_tags` and `character_traits` into the canonical
appearance tables. It never drops existing tables:

```bash
.venv/Scripts/python.exe scripts/migrate_appearance_profiles.py
```

The migration creates a default appearance for each existing owned profile,
links each feature to a `legacy_profile` source, validates counts, and can be
run repeatedly without duplicating rows. Back up `tag_library.db` before the
first migration.

## `build_appearance_candidates.py`

Builds the optional derived `data/character_appearance.sqlite` from captured
Danbooru/Gelbooru wiki rows already present in `tag_library.db` and optional
post JSON/JSONL captures:

```bash
.venv/Scripts/python.exe scripts/build_appearance_candidates.py \\
  --character inugami_korone \\
  --posts-jsonl raw/appearance/danbooru/reference_posts/3466244.json
```

It writes source-specific observations and `pending` candidates. Wiki and
official/reference-post evidence stay separate from frequency samples; artist,
copyright, character, alias, and metadata categories are excluded from visual
candidates. The output is atomically replaced only after a valid SQLite build
and is never read by the MCP as canonical data.

## `promote_appearance.py`

Promotes an explicitly reviewed JSON seed into the canonical appearance tables:

```bash
.venv/Scripts/python.exe scripts/promote_appearance.py \\
  --input seeds/appearance/inugami_korone.json
```

Every feature must name at least one source reference. Promotion is performed
in one transaction and can be repeated safely. The example seed contains the
Korone base appearance plus isolated `1st_costume`, `street`, and `new_year`
profiles. Do not promote raw candidates without human/source review.
