# CREDITS

## Upstream projects

### AnimaDex

Original project: [zetaneko/AnimaDex](https://github.com/zetaneko/AnimaDex)

Used here as the source of structured character, trait, artist, copyright, trigger, and frequency data. The original application code and gallery assets are preserved outside the active project in:

```text
C:\Users\johin\Code_Library\AI\WeebAlexandria_legacy_archive
```

### Tag sources

Weeb Alexandria contains data collected or derived from the following sources. Their respective terms and licenses apply to the data where applicable:

- Danbooru wiki and tag metadata: https://danbooru.donmai.us/
- e621 wiki and tag metadata: https://e621.net/
- Gelbooru wiki and tag metadata: https://gelbooru.com/
- Public datasets used during enrichment are retained under `raw/` with their source-specific files.

## Weeb Alexandria additions

The following integration work belongs to this project:

- Unified SQLite knowledge base.
- Cross-source definition fusion.
- Alias and implication tables exposed through MCP.
- AnimaDex character/trait/artist migration.
- Unified MCP tools in `weeb_alexandria_mcp`.
- Audit reports under `reports/`.
