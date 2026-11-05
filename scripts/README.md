# Scripts

Standalone helper scripts used by the active Weeb Alexandria data
pipeline. They are not imported by the MCP server; they are tools you run
by hand (or get shelled out to by the orchestrator).

## `mcp_surface_audit.py`

Drives the real MCP over stdio with the same `run.bat` launcher Hermes uses and
calls every exposed tool once, printing per-call latency and payload size. Exit
code is 0 only when every tool answered without error, so it can gate
maintenance work.

```bash
.venv/Scripts/python.exe scripts/mcp_surface_audit.py
.venv/Scripts/python.exe scripts/mcp_surface_audit.py --repeat 2 --preview 600
```

`--calls calls.json` overrides the default battery; tools whose required
arguments are missing are skipped instead of called with garbage.

## `bench_mcp_tools.py`

Latency guard for the helpers behind the MCP search tools. Cold and warm
timings for the FTS, suggestion, and character paths; exits 1 when a cold call
exceeds the budget (`--budget`, default 2.0 seconds). Run it before and after
touching `_fts_tag_rows`, `_tag_rows`, `_tag_suggestions`,
`_local_characters`, or `_appearance_characters`.

```bash
.venv/Scripts/python.exe scripts/bench_mcp_tools.py
.venv/Scripts/python.exe scripts/bench_mcp_tools.py --budget 2.0 --json
```

## `mcp_character_bench.py`

Regression bench for character resolution: runs `resolve_character` and
`get_character` over 22 popular characters in their colloquial spelling and
compares each recommendation with the tag the library actually holds. Exits 1 on
any mismatch, so a change to the resolver cannot silently regress.

```bash
.venv/Scripts/python.exe scripts/mcp_character_bench.py
.venv/Scripts/python.exe scripts/mcp_character_bench.py --json reports/mcp_character_bench.json
```

`card=False` is informational: most library characters are tag rows without a
reviewed appearance profile yet.

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
normalizes legacy facets such as `eye_color` and `hair_length`, links each
feature to a `legacy_profile` source, merges duplicate feature evidence, validates
every expected profile/feature/link inside the transaction, and can be run
repeatedly without duplicating rows. A normalization collision is rejected
before migration data is written. Back up `tag_library.db` before the first
migration.

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
candidates. Duplicate post records are counted once per source key. A post
with multiple possible outfit variants must provide `variant_tag`; otherwise
the builder rejects it instead of guessing. The output is atomically replaced
only after a valid SQLite build and a stable source-database fingerprint is
confirmed, and it is never read by the MCP as canonical data.

## `promote_appearance.py`

Promotes an explicitly reviewed JSON seed into the canonical appearance tables:

```bash
.venv/Scripts/python.exe scripts/promote_appearance.py \\
  --input seeds/appearance/inugami_korone.json
```

This is a legacy/maintenance entry point. **Do not call it from the general
appearance cron or while a general worker lease is active**: it has no batch
manifest and can desynchronize the report from the canonical database. The
general queue must use `general_appearance_worker.py --publish`, which performs
strict validation and one atomic multi-seed promotion. The character must
already exist as an owned profile or canonical character tag. Profile keys and
variant prefixes are checked, and every feature must name at least one source
reference. Do not promote raw candidates without human/source review.

## `promote_appearance_batch.py`

Promotes multiple reviewed seeds in one canonical SQLite transaction. The
lifecycle worker invokes it only after its lease, fingerprint, staged-source
validation, and full seed validation have passed:

```bash
.venv/Scripts/python.exe scripts/promote_appearance_batch.py \\
  --input seeds/appearance/first.json \\
  --input seeds/appearance/second.json
```

All seed JSON and profile invariants are validated before the transaction
starts. New source records may be staged in the seed: their excerpts are
checked against the canonical wiki body and the source rows are inserted in the
same transaction. If a later seed fails, no appearance profile, feature,
evidence link, or source row from the batch is committed. For the general
queue, invoke this only through `general_appearance_worker.py --publish` so the
manifest and report remain synchronized.

## `general_appearance_worker.py`

This is the lifecycle controller used by the general cron worker. Its durable
manifest is stored under ignored `data/` runtime state. The normal sequence is:

```bash
python scripts/general_appearance_worker.py --prepare --run-id RUN_ID
python scripts/general_appearance_worker.py --record-decision --run-id RUN_ID --character NAME --decision published --seed seeds/appearance/NAME.json
python scripts/general_appearance_worker.py --publish --run-id RUN_ID
python scripts/general_appearance_worker.py --close --run-id RUN_ID
```

The controller reserves at most five ranked characters, refuses a new batch
while any earlier manifest is open, validates the complete batch before
promotion, rebuilds all derived indexes, probes the read-only appearance
the report close, runs the final preflight before releasing the manifest, and
archives the run's published seeds only after that final preflight succeeds.
Use `--status` for inspection. An interrupted run is resumed by the next gate;
only an explicitly aborted run may be cleared.

## Automatic continuation and reconciliation

The cron shim invokes the deterministic continuation entry point:

```bash
.venv/Scripts/python.exe scripts/general_appearance_worker.py --tick
```

`--tick` never clears an aborted manifest. When a prepared/reviewing manifest
has all decisions, it validates every published seed against the candidate
fingerprint. A seed with candidate, excerpt, profile, or source-reference
errors is changed idempotently to `deferred`; the original decision, path, and
literal validator errors remain in the manifest. Valid seeds continue through
`--publish` and `--close`, so one bad seed cannot strand the batch or cause a
partial promotion. Global fingerprint/index failures remain fail-closed.

An aborted run requires an explicit, exact reconciliation command:

```bash
.venv/Scripts/python.exe scripts/general_appearance_worker.py \\
  --reconcile-aborted --run-id RUN_ID
```

That command backs up the canonical DB outside the repository, checks its
invariants, rebuilds candidate/search/context indexes, probes the read-only
runtime, updates only the canonical metrics of the latest report section, and
runs the final preflight before clearing that same `RUN_ID`. It never restores
or mutates canonical appearance rows automatically.

## Post-close seed archive

A successful `close` archives only the seeds explicitly assigned to that run
with a `published` decision and an exact matching row in
`character_appearance_profiles` with `status='published'`:

```text
seeds/appearance/NAME.json
  -> seeds/archive/RUN_ID/NAME.json
```

The worker uses an atomic same-volume move and records every operation in
`data/appearance_seed_archive_manifest.json`, including the run and batch IDs,
character, appearance key, original and destination paths, SHA-256 before and
after the move, UTC movement time, and result. The archive operation is
idempotent: a missing source is accepted only when the destination exists with
the recorded SHA-256. A destination with a different hash, a changed seed, a
non-published decision, or a canonical mismatch fails closed without deleting
the source. Deferred, pending, invalid, aborted, and incomplete-run seeds stay
under `seeds/appearance/`; an incomplete archive keeps the worker manifest
active so the next tick can resume it.

## Auditable script cleanup

`cleanup_legacy_scripts.py` contains a closed allowlist of historical
one-shot/debug helpers. Inventory is read-only; `--apply` moves only those
confirmed files to an external quarantine and records their SHA-256 values:

```bash
.venv/Scripts/python.exe scripts/cleanup_legacy_scripts.py
.venv/Scripts/python.exe scripts/cleanup_legacy_scripts.py --apply
```

The cleaner does not use broad globs and does not touch operational scripts,
DBs, generated indexes, seeds, backups, worker state, manifests, or evidence.

## Normalize combined-source tag categories

`build_db.py` uses source-specific category maps. To repair an existing
snapshot created with the old shared map, preview the combined-source changes:

```bash
.venv/Scripts/python.exe scripts/normalize_combined_tag_categories.py
```

Apply them with `--apply`. The script creates a SQLite backup under
`data/backups/` before writing. Rebuild the optional search and character
context indexes after applying the migration.

## Spanish query aliases

`build_query_aliases_es.py` verifies a Spanish -> English tag phrase map against
the local library and (re)writes `weeb_alexandria_mcp/query_aliases_es.json`,
which `search_knowledge` loads to translate Spanish phrasing before searching:

```bash
.venv/Scripts/python.exe scripts/build_query_aliases_es.py          # review table
.venv/Scripts/python.exe scripts/build_query_aliases_es.py --write  # update JSON
```

A phrase is accepted only when its English target resolves to a tag with at
least 1000 posts, or to a tag documented by two or more wikis (small but
legitimate tags such as `rope_marks`). Targets listed in
`ALLOW_LOW_COVERAGE` are kept deliberately even when neither rule passes.
