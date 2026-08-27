# Weeb Alexandria

## About the project

Weeb Alexandria is a project that unifies anime, otaku, weeb, NSFW, and SFW knowledge into a single, simple, locally hosted knowledge base.

It gives local AI agents access to reliable information about the topics you ask them about, helping them retrieve grounded data and reduce hallucinations in this area of knowledge.

The project combines tag definitions, aliases, implications, characters, franchises, artists, traits, sources, and other useful information for anime-related research and image generation.

## Current snapshot

The current `tag_library.db` snapshot contains approximately:

- **1.42 million unique tags**
- **1.51 million tag records** across sources
- **673,000 wiki entries**
- **592,000 wiki entries with definitions**
- **38,000 tag aliases**
- **25,000 active aliases**
- **24,000 tag implications**
- **21,000 active implications**

Database size: approximately **866 MB**.

Snapshot date: **2026-08-25**.

These counts refer to the published database snapshot and may change between releases.

## Quick Start

### 1. Get the project

Clone the repository or download its source files into a local directory:

```bash
git clone https://github.com/NegativeMeta/weeb-alexandria.git "<WEEB_ALEXANDRIA_DIR>"
```

#### Alternative: without the Git CLI

Open the GitHub repository in a browser:

```text
https://github.com/NegativeMeta/weeb-alexandria
```

Select **Code → Download ZIP**, extract the archive, and use the extracted folder as `<WEEB_ALEXANDRIA_DIR>`.

### 2. Download the database

Download the public database snapshot from Hugging Face:

```bash
hf download negativemeta/weeb-alexandria tag_library.db \
  --repo-type dataset \
  --local-dir "<WEEB_ALEXANDRIA_DIR>"
```

#### Alternative: without the Hugging Face CLI

Open the dataset in a browser:

```text
https://huggingface.co/datasets/negativemeta/weeb-alexandria
```

Open **Files and versions**, download `tag_library.db`, and place it in `<WEEB_ALEXANDRIA_DIR>`.

The database must be located at:

```text
<WEEB_ALEXANDRIA_DIR>\tag_library.db
```

### 2.1 Build the character-context index (recommended)

The derived index helps resolve queries such as `Rika Higurashi` by separating the character name from the franchise context:

```bash
.venv/Scripts/python.exe scripts/build_context_index.py
```

It creates `data/character_context.sqlite`, which is local/generated and is intentionally excluded from Git. Rebuild it after replacing `tag_library.db`.

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

### 5. Try it in a conversation

You do not need to call the MCP tools manually. Ask the model naturally, for example:

```text
Tell me what Inugami Korone looks like. You can use Weeb Alexandria to check the character information and relevant tags.
```

The model can use the appropriate Weeb Alexandria tool, such as `get_character`, `search_characters`, or `search_knowledge`, and then explain the result in normal language.

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

## Glossary

See [`GLOSSARY.md`](GLOSSARY.md) for a simple explanation of the database contents and MCP tools. Spanish, Simplified Chinese, and Japanese versions are available in [`GLOSSARY.es.md`](GLOSSARY.es.md), [`GLOSSARY.zh-CN.md`](GLOSSARY.zh-CN.md), and [`GLOSSARY.ja.md`](GLOSSARY.ja.md).

## Credits and sources

- [AnimaDex](https://github.com/zetaneko/AnimaDex) — structured character and artist data.
- [Danbooru](https://danbooru.donmai.us/) — wiki, tag metadata, aliases, implications, and popularity data.
- [e621](https://e621.net/) — wiki and tag metadata.
- [Gelbooru](https://gelbooru.com/) — wiki and tag metadata.
- [`CREDITS.md`](CREDITS.md) — full acknowledgements, attribution, and source details.
