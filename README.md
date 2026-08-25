# Weeb Alexandria

Base de conocimiento unificada para generación e investigación de tags anime/booru.

## Estructura

```text
WeebAlexandria/
├── weeb_alexandria_mcp/   MCP activo
├── .venv/                  runtime Python del MCP
├── tag_library.db          base principal unificada
├── raw/                    fuentes descargadas
│   ├── animadex/           base original de AnimaDex
│   ├── danbooru/
│   ├── e621/               wikis y tags procesados
│   ├── gelbooru/
│   └── danbooru_wiki_extra/
├── reports/                auditorías y listas de revisión
├── scripts/                mantenimiento y fusiones de datos
├── data/backups/           backups de la base
├── CREDITS.md              créditos y fuentes
├── run.bat                 launcher del MCP
└── README.md
```

El código web, el MCP antiguo y los assets visuales de AnimaDex no forman parte del runtime activo. Se conservan de forma reversible en:

```text
C:\Users\johin\Code_Library\AI\WeebAlexandria_legacy_archive
```

## Bases

`tag_library.db` contiene:

- Tags y categorías.
- Definiciones Danbooru, e621 y Gelbooru.
- Aliases e implicaciones.
- Definiciones sintéticas marcadas como `lang='llm'`.
- Tablas migradas de AnimaDex: personajes, traits, artistas y LoRAs.

`raw/animadex/animadex.db` se conserva con su nombre original como copia de referencia; el MCP activo usa las tablas AnimaDex migradas dentro de `tag_library.db`.

## MCP

Launcher:

```text
run.bat
```

Herramientas:

- `search_knowledge`
- `get_tag_knowledge`
- `search_characters`
- `get_character`
- `get_sources_status`

Weeb Alexandria consulta todo localmente y no necesita el servidor Flask original de AnimaDex.

Consulta `CREDITS.md` para los proyectos y fuentes originales.
