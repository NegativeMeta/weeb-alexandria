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
