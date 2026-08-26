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

Character records describe known anime, manga, game, and other fictional characters.

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

Artist records contain information about artists and their associated tags, triggers, popularity, and scores when available.

They can help identify an artist or prepare an artist-related prompt.

### LoRAs

LoRAs are optional model add-ons used by image-generation systems. Weeb Alexandria has a place for LoRA information, but the current database snapshot does not contain published LoRA records.

### NSFW and SFW

NSFW means content that may not be suitable for work or general audiences. SFW means content considered safe for work.

These labels help agents and users understand the general content category of information. They do not replace the rules of the application or platform where the data is used.

## MCP tools

### `search_knowledge`

Use this as the general-purpose search tool.

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

Search results are ranked with exact matches first, followed by prefix and partial matches.

### `get_tag_knowledge`

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

### `search_characters`

Use this to search the character database, especially when you want filters.

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

Use this when you know the exact character slug and want the complete record.

It can return:

- Character name.
- Franchise.
- Trigger.
- Core tags.
- Traits.
- Popularity.
- Related LoRAs, when available.

Example:

```text
Get the complete record for hatsune_miku
```

### `get_sources_status`

Use this to check whether the local sources and database are available.

It is useful for troubleshooting or confirming which parts of the knowledge base are installed locally.

## Choosing the right tool

```text
I am not sure what I need       → search_knowledge
I know the exact tag            → get_tag_knowledge
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
