# AnimaDex — setup local (Windows / Code Library)

Clonado de https://github.com/zetaneko/AnimaDex el 2026-07-11.

## Estado
- Repo clonado en `C:\Users\johin\Code_Library\AI\AnimaDex`
- venv Python 3.11 en `.venv/` (el Python del sistema es 3.10, insuficiente — exige >=3.11)
- Deps core instaladas (Flask 3.1.3, Pillow 12.2.0)
- `config.toml` creado desde el ejemplo con `secret_key` generado
- DB SQLite inicializada y sembrada con los samples (~20 personajes, ~10 artistas)
- Data dir: `C:\Users\johin\Code_Library\AI\animadex-data` (fuera del repo, gitignored)

## Cómo arrancar
Doble clic en **START.bat** (abre el navegador en http://127.0.0.1:5000 y levanta el server).
O en git-bash:
```
cd /c/Users/johin/Code_Library/AI/AnimaDex
source .venv/Scripts/activate
python -m animadex serve
```

## Notas
- `serve` NO acepta --host/--port; se toman de config.toml ([server] host/port).
- Para exponer en LAN cambia `host = "127.0.0.1"` -> `"0.0.0.0"` en config.toml
  (en este equipo WSL está en NAT mode; para acceso desde otros equipos habría
  que hacer `netsh portproxy` como admin, igual que con otros servicios).
- Features opcionales (scoring / generation / loras) vienen desactivadas.
- Para importar el dataset público de animadex.net: `import.bat` (necesita token).
