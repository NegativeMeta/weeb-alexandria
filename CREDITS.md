# CREDITS

## Upstream projects

### AnimaDex

Original project: [zetaneko/AnimaDex](https://github.com/zetaneko/AnimaDex)

Used here as the source of structured character, trait, artist, copyright, trigger, and frequency data. The original application code and gallery assets are preserved outside the active project in the local legacy archive. The archive location is intentionally not part of the public documentation because it depends on each installation.

### Thanks to the source projects

We sincerely thank the maintainers and contributors of AnimaDex, Danbooru, e621, and Gelbooru for making the underlying knowledge and metadata available. Weeb Alexandria would not be possible without their work.

Please consult each source's current terms, licenses, and attribution requirements before redistributing or using derived data.

### Tag sources

Weeb Alexandria contains data collected or derived from the following sources. Their respective terms and licenses apply to the data where applicable:

- **Danbooru** — wiki pages, tag metadata, aliases, implications, popularity counts, and the structured AnimaDex-compatible data used for character and artist records: https://danbooru.donmai.us/
- **e621** — wiki pages and tag metadata used to enrich definitions and tag coverage: https://e621.net/
- **Gelbooru** — wiki pages and tag metadata used as an additional source for definitions and coverage: https://gelbooru.com/
- **AnimaDex** — structured character, trait, artist, copyright, trigger, and frequency data integrated into the unified database: https://github.com/zetaneko/AnimaDex
- Public datasets used during enrichment are retained under `raw/` with their source-specific files.

## Weeb Alexandria additions

The following integration work belongs to this project:

- Unified SQLite knowledge base.
- Cross-source definition fusion.
- Alias and implication tables exposed through MCP.
- AnimaDex character/trait/artist migration.
- Unified MCP tools in `weeb_alexandria_mcp`.
- Audit reports under `reports/`.

## Licensing and redistribution

The repository `LICENSE` is the MIT license for project software and documentation to the extent that the project has the right to license those materials. It is **not** a blanket license for every record in `tag_library.db`, files under `raw/`, or the published Hugging Face dataset.

This release combines project-authored integration code and schemas with copied or derived records from upstream sources. Source-specific terms, licenses, attribution requirements, and redistribution restrictions remain applicable to the relevant records. Synthetic definitions marked with `lang='llm'` are project-generated additions and should not be mistaken for upstream statements.

Before redistributing the complete database or extracting upstream-derived records, review the current terms and licensing information for each source. If permission or applicable terms are unclear, do not assume that redistribution is allowed. The repository license retains the upstream AnimaDex copyright notice; it should not be interpreted as a claim that Weeb Alexandria owns third-party data.

The derived `data/character_context.sqlite` index is generated from the database snapshot and is intentionally kept outside GitHub. Its metadata identifies the source database size and index schema version.
