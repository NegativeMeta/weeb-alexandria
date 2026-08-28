# Weeb Alexandria

## Sobre el proyecto

Weeb Alexandria es un proyecto que unifica conocimiento anime, otaku, weeb, NSFW y SFW en una única base de conocimiento sencilla y alojada localmente.

Permite que los agentes de IA locales accedan a información confiable sobre los temas que les consultes, ayudándolos a recuperar datos fundamentados y reducir las alucinaciones en esta área del conocimiento.

El proyecto combina definiciones de tags, aliases, implicaciones, personajes, franquicias, artistas, traits, cards de apariencia/vestimenta, fuentes y otra información útil para la investigación relacionada con anime y la generación de imágenes.

## Snapshot actual

El snapshot actual de `tag_library.db` contiene aproximadamente:

- **1.42 millones de tags únicas**
- **1.51 millones de registros de tags** entre las distintas fuentes
- **673,000 entradas de wiki**
- **592,000 entradas de wiki con definiciones**
- **38,000 aliases de tags**
- **25,000 aliases activos**
- **24,000 implicaciones de tags**
- **21,000 implicaciones activas**

Tamaño de la base: aproximadamente **866 MB**.

Fecha del snapshot: **2026-08-25**.

Estas cifras corresponden al snapshot publicado y pueden cambiar entre versiones.

## Inicio rápido

### 1. Obtener el proyecto

Clona el repositorio o descarga sus archivos en una carpeta local:

```bash
git clone https://github.com/NegativeMeta/weeb-alexandria.git "<WEEB_ALEXANDRIA_DIR>"
```

#### Alternativa: sin la CLI de Git

Abre el repositorio de GitHub en el navegador:

```text
https://github.com/NegativeMeta/weeb-alexandria
```

Selecciona **Code → Download ZIP**, extrae el archivo y utiliza la carpeta extraída como `<WEEB_ALEXANDRIA_DIR>`.

### 2. Descargar la base de datos

Descarga el snapshot público desde Hugging Face:

```bash
hf download negativemeta/weeb-alexandria tag_library.db \
  --repo-type dataset \
  --local-dir "<WEEB_ALEXANDRIA_DIR>"
```

#### Alternativa: sin la CLI de Hugging Face

Abre el dataset en el navegador:

```text
https://huggingface.co/datasets/negativemeta/weeb-alexandria
```

Entra en **Files and versions**, descarga `tag_library.db` y colócalo en `<WEEB_ALEXANDRIA_DIR>`.

La base debe quedar en:

```text
<WEEB_ALEXANDRIA_DIR>\tag_library.db
```

### 2.1 Construir el índice de contexto de personajes (recomendado)

El índice derivado ayuda a resolver consultas como `Rika Higurashi` separando el nombre del personaje del contexto de su franquicia. También registra relaciones canónicas de obras, por ejemplo:

```text
furude_rika → higurashi_no_naku_koro_ni
```

Constrúyelo o regénéralo con:

```bash
.venv/Scripts/python.exe scripts/build_context_index.py
```

Crea `data/character_context.sqlite` con las tablas `character_context`, `character_work_context` y `context_index_metadata`. El índice es local/generado, está excluido intencionalmente de Git y debe regenerarse después de reemplazar `tag_library.db`. La metadata registra el tamaño, SHA-256, estado de sidecars, conteos de filas y versión del esquema de la base de origen. El MCP ignora índices de contexto obsoletos o incompletos y vuelve a su ruta normal de resolución.

### 2.2 Construir el índice de búsqueda de tags (recomendado)

El índice FTS5 opcional acelera las búsquedas parciales sobre nombres y aliases de tags. Constrúyelo o regénéralo después de reemplazar `tag_library.db`:

```bash
.venv/Scripts/python.exe scripts/build_search_index.py
```

Crea `data/tag_search.sqlite`, guarda el SHA-256 de la base de origen y el conteo de filas indexadas, y está excluido intencionalmente de Git. El MCP valida esos valores (incluidos los sidecars de SQLite) y vuelve automáticamente a las consultas SQLite principales si el índice falta, está obsoleto, incompleto, malformado o no se puede abrir.

### 3. Conectarlo a Hermes

Registra el servidor MCP local por stdio:

```bash
hermes mcp add weeb-alexandria \
  --command "C:\\Windows\\System32\\cmd.exe" \
  --args /d /c "<WEEB_ALEXANDRIA_DIR>\\run.bat"
```

### 4. Conectarlo a LM Studio

Abre **Program → Install → Edit mcp.json** y añade:

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

Inicia un chat nuevo y confirma que las seis herramientas de Weeb Alexandria están disponibles.

### 5. Pruébalo en una conversación

No necesitas llamar manualmente a las herramientas del MCP. Pídele algo al modelo de forma natural, por ejemplo:

```text
Dime cómo es Inugami Korone. Puedes usar Weeb Alexandria para consultar la información del personaje y sus tags relacionadas.
```

El modelo puede utilizar la herramienta adecuada, como `get_character`, `search_characters` o `search_knowledge`, y después explicar el resultado en lenguaje normal.

### Búsquedas con varias tags

Si `search_knowledge` recibe varias tags unidas en una sola consulta, por ejemplo `blushing red face`, puede devolver `query_mode: "multi_tag"`, partes separadas en `tag_library.query_parts` y una `query_recommendation` de nivel superior. El agente debe leer `query_recommendation.queries`, llamar a `search_knowledge` una vez por cada consulta y combinar los resultados solo después de realizar esas búsquedas independientes.

```json
{
  "query_recommendation": {
    "action": "search_each_tag_separately",
    "queries": ["blushing", "red face"]
  }
}
```

Las tags conocidas de varias palabras, como `red face` y `closed mouth`, permanecen intactas. Las consultas contextuales de personajes o franquicias, como `Fuwawa Hololive` y `Mococo Hololive`, se conservan sin dividirse.

## Cards de apariencia y vestimenta

La apariencia se divide entre un perfil base y perfiles separados para cada outfit o variante. Las filas canónicas viven en `tag_library.db`:

- `character_appearance_profiles`: una fila por apariencia base o variante.
- `character_appearance_features`: una fila por faceta/tag, como `hair`, `eyes`, `dress` o `footwear`.
- `character_appearance_sources`: catálogo de fuentes Danbooru, Gelbooru, posts de referencia y semillas revisadas.
- `character_appearance_feature_sources`: evidencia, conteos y conflictos por característica.

`data/character_appearance.sqlite` contiene observaciones y candidatos `pending` generados desde wikis y muestras de posts capturadas. Los candidatos no se exponen como hechos canónicos hasta que se revisan y promocionan explícitamente.

```bash
.venv/Scripts/python.exe scripts/build_appearance_candidates.py \\
  --character inugami_korone

.venv/Scripts/python.exe scripts/promote_appearance.py \\
  --input seeds/appearance/inugami_korone.json
```

La herramienta MCP es `get_character_appearance(character, variant=None, include_evidence=True, limit=100)`. `get_character_appearance("inugami_korone")` devuelve la apariencia base y los perfiles revisados de `1st_costume`, `street` y `new_year` sin mezclar sus prendas.

Para el contrato completo de cada profile, las reglas de evidencia, la checklist de revisión y la primera tanda de cinco personajes, consulta [`docs/CHARACTER_APPEARANCE_PROFILES.md`](docs/CHARACTER_APPEARANCE_PROFILES.md).

## Estructura

```text
WeebAlexandria/
├── weeb_alexandria_mcp/   Servidor MCP activo
├── .venv/                  Entorno Python del MCP
├── tag_library.db          Base de conocimiento unificada
├── raw/                    Fuentes descargadas
│   ├── animadex/           Base original de AnimaDex
│   ├── appearance/         Wikis/posts de apariencia capturados
│   ├── danbooru/
│   ├── e621/               Wikis y tags procesados
│   ├── gelbooru/
│   └── danbooru_wiki_extra/
├── reports/                Auditorías y listas de revisión
├── scripts/                Scripts de mantenimiento y fusión
├── seeds/appearance/       Semillas de apariencia revisadas
├── data/character_context.sqlite
│                           Índice de contexto derivado (local)
├── data/character_appearance.sqlite
│                           Observaciones/candidatos derivados (local)
├── data/tag_search.sqlite
│                           Índice FTS5 opcional de búsqueda (local)
├── data/backups/           Backups de la base
├── CREDITS.md              Créditos y fuentes
├── run.bat                 Launcher del MCP
└── README.md
```

La aplicación web original de AnimaDex, el MCP antiguo y los assets visuales no forman parte del runtime activo. Se conservan de forma reversible en:

```text
C:\Users\johin\Code_Library\AI\WeebAlexandria_legacy_archive
```

## Bases de datos

`tag_library.db` contiene:

- Tags y categorías.
- Definiciones de Danbooru, e621 y Gelbooru.
- Aliases e implicaciones.
- Definiciones sintéticas marcadas con `lang='llm'`.
- Perfiles estructurados propios y relaciones de traits (`character_profiles`, `trait_definitions` y `character_traits`).
- Perfiles canónicos de apariencia/vestimenta y procedencia por feature (`character_appearance_profiles`, `character_appearance_features`, `character_appearance_sources` y `character_appearance_feature_sources`).
- Búsqueda de artistas y franquicias desde la tabla global `tags`.

`raw/animadex/animadex.db` se conserva con su nombre original solo para auditoría y recuperación de la semilla. El MCP activo no lo abre ni necesita tablas estructuradas legacy.

El registro de la semilla histórica y de la migración está documentado en [`docs/ANIMADEX_VALUE_ANALYSIS.md`](docs/ANIMADEX_VALUE_ANALYSIS.md). `search_knowledge` devuelve los resultados estructurados dentro del namespace `entities`.

## MCP

Launcher:

```text
run.bat
```

Herramientas disponibles:

- `search_knowledge`
- `get_tag_knowledge`
- `search_characters`
- `get_character`
- `get_character_appearance`
- `get_sources_status`

Weeb Alexandria realiza sus consultas localmente y no necesita el servidor Flask original de AnimaDex.

## Glosario

Consulta [`GLOSSARY.es.md`](GLOSSARY.es.md) para una explicación sencilla de la base y las herramientas del MCP. También están disponibles las versiones en inglés, chino simplificado y japonés en [`GLOSSARY.md`](GLOSSARY.md), [`GLOSSARY.zh-CN.md`](GLOSSARY.zh-CN.md) y [`GLOSSARY.ja.md`](GLOSSARY.ja.md).

## Créditos y fuentes

- [AnimaDex](https://github.com/zetaneko/AnimaDex) — fuente histórica de la pequeña semilla estructurada; se conserva por atribución y procedencia, no como dependencia activa del runtime.
- [Danbooru](https://danbooru.donmai.us/) — wiki, metadata de tags, aliases, implicaciones y popularidad.
- [e621](https://e621.net/) — wiki y metadata de tags.
- [Gelbooru](https://gelbooru.com/) — wiki y metadata de tags.
- [`CREDITS.md`](CREDITS.md) — agradecimientos, atribución y detalles completos de las fuentes.
