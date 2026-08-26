# Weeb Alexandria

## Sobre el proyecto

Weeb Alexandria es un proyecto que unifica conocimiento anime, otaku, weeb, NSFW y SFW en una única base de conocimiento sencilla y alojada localmente.

Permite que los agentes de IA locales accedan a información confiable sobre los temas que les consultes, ayudándolos a recuperar datos fundamentados y reducir las alucinaciones en esta área del conocimiento.

El proyecto combina definiciones de tags, aliases, implicaciones, personajes, franquicias, artistas, traits, fuentes y otra información útil para la investigación relacionada con anime y la generación de imágenes.

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
- **20 personajes**
- **84 traits de personajes**
- **10 artistas**

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

Abre un chat nuevo y confirma que las cinco herramientas de Weeb Alexandria estén disponibles.

## Estructura

```text
WeebAlexandria/
├── weeb_alexandria_mcp/   Servidor MCP activo
├── .venv/                  Entorno Python del MCP
├── tag_library.db          Base de conocimiento unificada
├── raw/                    Fuentes descargadas
│   ├── animadex/           Base original de AnimaDex
│   ├── danbooru/
│   ├── e621/               Wikis y tags procesados
│   ├── gelbooru/
│   └── danbooru_wiki_extra/
├── reports/                Auditorías y listas de revisión
├── scripts/                Scripts de mantenimiento y fusión
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
- Tablas migradas de AnimaDex para personajes, traits, artistas y LoRAs.

`raw/animadex/animadex.db` se conserva con su nombre original como copia de referencia. El MCP activo utiliza las tablas migradas de AnimaDex dentro de `tag_library.db`.

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
- `get_sources_status`

Weeb Alexandria realiza sus consultas localmente y no necesita el servidor Flask original de AnimaDex.

Consulta `CREDITS.md` para conocer los proyectos y fuentes originales.
