# AnimaDex MCP server

Model Context Protocol server (stdio) que expone la galeria **AnimaDex**
(Flask + SQLite, personajes/artistas/anime) para que cualquier modelo o
agente pueda consultarla como herramientas estandar.

Se comunica con el backend AnimaDex por HTTP (no necesita la DB local:
solo el server corriendo en `ANIMADEX_BASE_URL`).

## Requisitos
- El backend AnimaDex debe estar corriendo (por defecto http://127.0.0.1:5000).
  Levantalo con `START.bat` en la raiz del repo o `python -m animadex serve`.
- Python 3.11 en el venv del repo (`.venv/`). El paquete `mcp[cli]` ya esta
  instalado ahi.

## Arrancar
Doble clic en `run.bat` (modo stdio, para MCP clients).
O en git-bash:
```
cd /c/Users/johin/Code_Library/AI/AnimaDex
source .venv/Scripts/activate
python -m animadex_mcp.server
```

## Config para MCP clients (ej. Claude Desktop)
El cliente debe lanzar el server por stdio. Config tipica
(`claude_desktop_config.json` / `~/.config/mcp/...`):
```json
{
  "mcpServers": {
    "animadex": {
      "command": "C:\\Users\\johin\\Code_Library\\AI\\AnimaDex\\.venv\\Scripts\\python.exe",
      "args": ["-m", "animadex_mcp.server"],
      "cwd": "C:\\Users\\johin\\Code_Library\\AI\\AnimaDex",
      "env": {
        "ANIMADEX_BASE_URL": "http://127.0.0.1:5000",
        "PYTHONPATH": ""
      }
    }
  }
}
```
Nota: `PYTHONPATH` se deja vacio a proposito para NO cargar el venv de Hermes
ni otros site-packages del sistema.

## Tools disponibles
| Tool | Descripcion |
|------|-------------|
| `search_characters` | Busca personajes con filtros facetados (copyright, hair_color, hair_length, eye_color, gender), texto libre, sort y page. |
| `search_artists` | Busca artistas por texto. |
| `search_copyrights` | Busca series/franchises. |
| `get_character_facets` | Facetas y valores comunes para personajes. |
| `get_artist_facets` | Facetas para artistas. |
| `get_facet_values` | Lista los valores de una faceta concreta (ej. todos los hair_color). |
| `get_character` | Detalle completo de un personaje por slug. |

Todas devuelven `thumb_url` / `img_url` como URLs absolutas del backend.

## Variables de entorno
- `ANIMADEX_BASE_URL` — URL base del backend (default http://127.0.0.1:5000).
  Para apuntar a otro equipo/LAN, poner `http://<ip>:5000` y asegurarse de
  que el backend escuche en `0.0.0.0` (ver config.toml).
