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
