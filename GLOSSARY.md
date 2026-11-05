# Weeb Alexandria Glossary

This glossary explains the information available in Weeb Alexandria and the MCP tools in simple, practical terms.

## Knowledge in the database

### Tags

Tags are the words used to describe an image, character, style, action, object, or concept. Examples:

```text
blue_hair
school_uniform
smile
holding_sword
```

Tags are the main building blocks used when searching for information or creating prompts.

### Categories

Categories describe what kind of tag something is. A tag may represent a general concept, a character, a series, an artist, or another type of information.

Category names are normalized per source. Depending on the source, they include `general`, `artist`, `contributor`, `copyright`, `character`, `species`, `invalid`, `meta`, and `lore`; legacy categories such as `alias` are retained where the source uses them. Numeric category IDs are not interchangeable between sources.

### Definitions

Definitions explain what a tag means. They may include its usual meaning, how it is used, and useful distinctions from similar tags.

Definitions come from the indexed sources whenever possible. Some definitions generated with language models are clearly marked as synthetic.

### Aliases

Aliases are alternative names for the same concept. They help connect different names used by different websites or communities.

Example:

```text
stuck_in_wall → through_wall
```

This means that `stuck_in_wall` is treated as an alternative name for `through_wall`.

### Implications

Implications describe relationships where one tag usually includes another idea.

Example:

```text
holding_tripod → holding
holding_tripod → tripod
```

This means that someone holding a tripod is also holding something and is associated with a tripod.

### Popularity and post count

The post count is the number of posts associated with a tag on a source website. It is used as an approximate indicator of how common or established a tag is.

A higher count does not automatically mean that a tag is better. It only means that it appears more frequently in that source.

### Sources

A source is the website or dataset where information came from, such as Danbooru, e621, Gelbooru, or AnimaDex.

Keeping the source helps users understand where a definition or relationship originated.

### Characters

Character-related tags can represent fictional characters even when they do not have a structured character record. The general tags table contains far more character tags than the curated character table.

The owned character-profile table is a curated, structured seed retained from a historical structured export. It does **not** represent the total number of characters in the whole database. Many character names may exist as ordinary tags with wiki entries, aliases, popularity, or source information without having an owned structured profile.

A character may include:

- Character name.
- Series or franchise.
- Trigger or identifying tag.
- Core tags useful for describing the character.
- Popularity or post count.
- Visual traits.

### Franchises and series

A franchise identifies the work or universe a character belongs to, such as a game, anime, manga, or fictional series.

The database may also call this a copyright because that is the term commonly used by booru tagging systems.

### Triggers

A trigger is the main tag or phrase used to identify a character in a prompt or search.

It is usually the most direct way to refer to that character.

### Core tags

Core tags are the most useful visual tags associated with a character. They can describe hair, clothing, accessories, colors, or other recognizable features.

They are intended as a starting point, not as a complete description of every appearance.

### Traits

Traits describe specific character features grouped by areas such as:

- Hair color.
- Hair length.
- Eye color.
- Gender.
- Clothing or other visual details.

Traits can help search for characters with similar visual characteristics.

### Artists

Artist-related tags can represent artists even when they do not have a structured artist record. The general tags table contains many more artist tags than the curated artist table.

Artist results are obtained from the global `tags` table and can include artist names, popularity, and source coverage. They should not be interpreted as a complete or separately curated artist catalogue.

They can help identify an artist or prepare an artist-related prompt.

### LoRAs

LoRAs are optional model add-ons used by image-generation systems. The current database snapshot does not contain published LoRA associations.

### NSFW and SFW

NSFW means content that may not be suitable for work or general audiences. SFW means content considered safe for work.

These labels help agents and users understand the general content category of information. They do not replace the rules of the application or platform where the data is used.

## MCP tools

### `search_knowledge`

Use this as the general-purpose search tool.

Multi-word queries that look like several tags return `query_parts` plus
`related_tags` (the tags that tie the parts together, such as the umbrella
concept). Alias/invalid stub rows with negligible coverage are skipped, so a real
tag answers instead of a 3-post redirect.

Spanish phrasing is translated first: the phrases in
`weeb_alexandria_mcp/query_aliases_es.json` are replaced by their English tag
wording, and the response carries `query_translation` with the wording actually
searched (`searched_as`).

It searches across:

- Tags.
- Characters.
- Artists.
- Franchises or series.

It is useful when the user provides a broad or uncertain query.

Example:

```text
Search for Miku
Find characters from Genshin Impact
Look for tags related to holding a sword
```

Search results are ranked with exact matches first, followed by prefix and partial matches. Search covers the tag library; characters live in `search_characters`. If no direct result is found, the tool also returns a `suggestions` list with likely tag names for spelling mistakes or non-canonical names.

### `get_knowledge`

Use this when you already know the exact tag you want to inspect.

It returns the tag's:

- Definitions.
- Source information.
- Category.
- Popularity.
- Aliases.
- Implications.
- NSFW status.

Example:

```text
Get the complete information for stuck_in_wall
```

This tool is intentionally precise and works best with the canonical tag spelling, usually lowercase with underscores.

### `resolve_character`

Use this when the character name is loose, misspelled, written in another
language, or ambiguous across franchises.

It returns the `recommended_tag` to use (or `null`), the winning recommendation
with its match type, confidence and matched work, the full ranked candidate
list, `candidates` from the owned profiles, and `ambiguous`/`ambiguity` when a
short name fits several characters. When the exact tag exists but is not a
character tag, `notes` says so.

Example:

```text
Which tag should I use for Anya Forger?
```

### `search_characters`

Use this to search the character database, especially when you want filters.
Facet-only searches read the owned legacy profiles by default; pass
`scope="all"` to include the reviewed appearance profiles as well.

You can search or filter by:

- Character name.
- Franchise.
- Hair color.
- Hair length.
- Eye color.
- Gender.
- Popularity or name order.

Example:

```text
Find female characters from Genshin Impact with blue hair
```

### `get_character`

Use this when you know the character and want the canonical card.

It returns:

- The published appearance profiles (default plus costume variants).
- Features grouped by facet (eyes, hair, outfit pieces...), with facet metadata.
- Optional per-feature evidence: source URL, tier and excerpt.
- Name resolution, including aliases stored in the tag rows such as `GawrGura` -> `gawr_gura`.

Example:

```text
Get the complete card for inugami_korone
```

Evidence is off by default to keep payloads small; pass `include_evidence=True` when you need the citation.

### `get_sources_status`

Use this to check whether the local sources and database are available.

It is useful for troubleshooting or confirming which parts of the knowledge base are installed locally.

## Choosing the right tool

```text
I am not sure what I need       → search_knowledge
I know the exact tag            → get_knowledge
I want to find characters       → search_characters
I know the exact character slug → get_character
I want to check the installation→ get_sources_status
```

## Important limitations

- Search results are based on the current local database snapshot.
- A missing result does not necessarily mean that the concept does not exist.
- Popularity counts come from source websites and may not represent current popularity everywhere.
- Definitions and relationships may differ between sources.
- Synthetic definitions are marked separately and should be treated as suggestions rather than official source text.
