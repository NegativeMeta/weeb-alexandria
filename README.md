# Weeb Alexandria

## Quick Start

### 1. Get the project

Clone the repository or download its source files into a local directory:

```bash
git clone https://github.com/NegativeMeta/weeb-alexandria.git "<WEEB_ALEXANDRIA_DIR>"
```

### 2. Download the database

Download the public database snapshot from Hugging Face:

```bash
hf download negativemeta/weeb-alexandria tag_library.db \
  --repo-type dataset \
  --local-dir "<WEEB_ALEXANDRIA_DIR>"
```

The database must be located at:

```text
<WEEB_ALEXANDRIA_DIR>\tag_library.db
```

### 3. Connect it to Hermes

Register the local stdio MCP server:

```bash
hermes mcp add weeb-alexandria \
  --command "C:\\Windows\\System32\\cmd.exe" \
  --args /d /c "<WEEB_ALEXANDRIA_DIR>\\run.bat"
```

### 4. Connect it to LM Studio

Open **Program → Install → Edit mcp.json** and add:

```json
{
  "mcpServers": {
    "weeb-alexandria": {
      "command": "C:\\Windows\\System32\\cmd.exe",
      "args": [
        "/d",
        "/c",
        "<WEEB_ALEXANDRIA_DIR>\\run.bat"
      ]
    }
  }
}
```

Start a new chat and confirm that the five Weeb Alexandria tools are available.

## About the project

Weeb Alexandria is a project that unifies anime, otaku, weeb, NSFW, and SFW knowledge into a single, simple, locally hosted knowledge base.

It gives local AI agents access to reliable information about the topics you ask them about, helping them retrieve grounded data and reduce hallucinations in this area of knowledge.

The project combines tag definitions, aliases, implications, characters, franchises, artists, traits, sources, and other useful information for anime-related research and image generation.

## Structure

```text
WeebAlexandria/
├── weeb_alexandria_mcp/   Active MCP server
├── .venv/                  Python runtime for the MCP
├── tag_library.db          Main unified knowledge base
├── raw/                    Downloaded source data
│   ├── animadex/           Original AnimaDex database
│   ├── danbooru/
│   ├── e621/               Processed wiki and tag data
│   ├── gelbooru/
│   └── danbooru_wiki_extra/
├── reports/                Audits and review lists
├── scripts/                Data maintenance and fusion scripts
├── data/backups/           Database backups
├── CREDITS.md              Credits and source information
├── run.bat                 MCP launcher
└── README.md
```

The original AnimaDex web application, legacy MCP, and visual assets are not part of the active runtime. They are preserved reversibly at:

```text
C:\Users\johin\Code_Library\AI\WeebAlexandria_legacy_archive
```

## Databases

`tag_library.db` contains:

- Tags and categories.
- Danbooru, e621, and Gelbooru definitions.
- Aliases and implications.
- Synthetic definitions marked with `lang='llm'`.
- Migrated AnimaDex tables for characters, traits, artists, and LoRAs.

`raw/animadex/animadex.db` is preserved under its original name as a reference copy. The active MCP uses the migrated AnimaDex tables inside `tag_library.db`.

## MCP

Launcher:

```text
run.bat
```

Available tools:

- `search_knowledge`
- `get_tag_knowledge`
- `search_characters`
- `get_character`
- `get_sources_status`

Weeb Alexandria performs its queries locally and does not require the original AnimaDex Flask server.

See `CREDITS.md` for the original projects and sources.
