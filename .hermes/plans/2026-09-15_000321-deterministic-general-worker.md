# Worker determinista para la cola general de apariencia

## Objetivo

Eliminar las desalineaciones entre DB canónica, seeds, reporte, índices y estado
cron. El LLM conserva la revisión semántica de candidatos, pero una máquina de
estados determinista controla el límite de escritura y el cierre completo.

## Alcance

- Añadir `scripts/general_appearance_worker.py` como gate y orquestador de fases.
- Añadir promoción multi-seed en una sola transacción sin romper el CLI
  individual existente.
- Mover las nuevas exclusiones del ranking a un ledger JSON local, manteniendo
  las exclusiones históricas estáticas compatibles.
- Añadir probe MCP reutilizable para el cierre del worker.
- Añadir pruebas unitarias para lock/manifest, recuperación, exclusiones,
  promoción atómica y cierre de errores.
- Actualizar documentación y los dos jobs Hermes; no hacer commit, push ni
  publicación externa.

## Contrato de estado

El estado vive en `data/general_appearance_worker_state.json`, ignorado por Git,
y se escribe con archivo temporal + `os.replace`. La creación inicial usa
`O_CREAT|O_EXCL`, por lo que dos gates no pueden reservar el mismo tick.

Fases válidas:

```text
reserved -> prepared -> reviewed -> promoted -> closed
```

Un fallo conserva la última fase completada y `last_error`; no borra el
manifest ni permite iniciar otra tanda. `--abort` deja el estado bloqueado para
revisión explícita. Un manifest `closed` se limpia de forma idempotente.

El manifest conserva `run_id`, scope, ranking exacto, fingerprint inicial,
caracteres seleccionados, métricas del builder, decisiones, seeds aceptados,
diferidas, conteos de promoción y fingerprint final. Toda operación posterior
requiere el `run_id` exacto.

## Fases ejecutables

1. `--gate` (sin argumentos):
   - si existe una ejecución abierta, emite contexto de continuación y no crea
     otra tanda;
   - si no existe, ejecuta el preflight actual;
   - con preflight listo, obtiene el ranking de cinco nombres, reserva el
     manifest y emite el único sentinel final `{"wakeAgent":true}`;
   - cualquier bloqueo emite `{"wakeAgent":false}`.
2. `--prepare --run-id`: construye candidatos únicamente para los cinco nombres
   del manifest y guarda observaciones/candidatos por carácter.
3. `--record-decision --run-id`: registra `published` + seed o `deferred` +
   razón no vacía; rechaza nombres no seleccionados y decisiones duplicadas.
4. `--publish --run-id`: valida todos los seeds aceptados contra el snapshot
   exacto y llama a la promoción multi-seed de una sola transacción. Las
   deferencias no se promueven.
5. `--close --run-id`: actualiza el ledger de deferencias de forma atómica,
   ejecuta bootstrap read-only, recalcula fingerprint, reconstruye search,
   context y candidatos serialmente, valida integridad/evidencia/fingerprints,
   ejecuta el probe MCP real, genera el cierre append-only del reporte desde el
   manifest/DB y verifica el preflight antes de eliminar el manifest.
7. `--status`: muestra estado estable sin escribir.
8. `--abort/--clear`: operaciones explícitas con `run_id`; `--clear` solo acepta
   un manifest previamente abortado y nunca se ejecutan automáticamente desde el gate.

## Invariantes

- Una sola ejecución abierta por scope.
- Un solo batch por tick.
- Ninguna nueva selección mientras exista un manifest abierto.
- Todas las validaciones de seeds preceden a la primera escritura canónica.
- La promoción aceptada es una transacción multi-seed; un fallo no deja seeds
  anteriores confirmados dentro de esa tanda.
- El reporte lo escribe el orquestador después de índices, integridad y MCP; el
  LLM no lo edita durante la revisión.
- Las diferidas no aparecen en MCP ni en la siguiente cola.
- No se autoriza commit, push, Hugging Face ni publicación externa.
- El worker y el monitor mantienen procesos y permisos separados.

## Aceptación

- Dos gates concurrentes producen como máximo un `run_id`.
- Un segundo gate durante una ejecución devuelve continuación, no una tanda
  nueva.
- Un fallo simulado después de una promoción no libera el manifest ni despierta
  otra tanda; `--close` puede reanudar desde la fase persistida.
- Un fallo del segundo seed en promoción multi-seed deja las tablas de datos
  sin cambios respecto al snapshot lógico previo.
- El cierre exitoso deja preflight `READY`, reporte sincronizado, índices frescos,
  SQLite íntegra, probe MCP verde y manifest eliminado.
- Una segunda promoción del mismo batch devuelve los mismos conteos.
- La suite existente continúa en verde y se agregan regresiones de estado,
  ledger y transacción.
- Los jobs quedan `enabled=true`, `scheduled`, `every 1m`, con el nuevo gate y
  el provider/modelo fijados; el monitor sigue read-only.

## Verificación

```text
.venv/Scripts/python.exe -m unittest discover -s tests -q
.venv/Scripts/python.exe scripts/general_appearance_worker.py --status
.venv/Scripts/python.exe scripts/general_appearance_worker.py --gate --dry-run
.venv/Scripts/python.exe scripts/validate_general_appearance_batch.py ...
.venv/Scripts/python.exe scripts/build_search_index.py --source tag_library.db --output data/tag_search.sqlite
.venv/Scripts/python.exe scripts/build_context_index.py --source tag_library.db --output data/character_context.sqlite
.venv/Scripts/python.exe scripts/general_appearance_preflight.py (dos veces)
hermes cron list (worker + monitor)
```

Los datos canónicos y los artefactos generados permanecen locales. No se
conservan credenciales ni valores sensibles en el manifest, logs o reporte.
