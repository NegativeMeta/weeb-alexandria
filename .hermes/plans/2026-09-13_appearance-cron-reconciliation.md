# Reconciliación y endurecimiento del worker general de apariencia

## Objetivo
Cerrar de forma auditable el batch general 42 ya promovido y evitar que el cron vuelva a avanzar cuando la DB canónica y el reporte estén desincronizados o cuando el conjunto de features no haya pasado la puerta del builder.

## Alcance
- `reports/hololive_appearance_queue.md`: añadir únicamente la sección cronológica del batch 42.
- `scripts/rank_general_queue.py`: registrar las cuatro decisiones deferred nuevas en el ledger estático del ranker.
- `scripts/general_appearance_preflight.py`: preflight determinista, de solo lectura, para el cron.
- Job Hermes `f89a084a887a`: prompt autónomo general, preflight, continuidad y mismo proveedor/modelo fijado.
- Job Hermes `670e41960d99`: mantenerlo separado y de solo lectura.

No se borran perfiles/features, no se hace rollback, no se toca Hololive, no se hace commit/push/Hugging Face y no se imprimen credenciales.

## Contrato del preflight

Entrada: `tag_library.db`, el reporte y el ranker local.

Salida: líneas deterministas `key=value`, sin timestamps ni secretos, incluyendo:
- conteos publicados y enlaces de evidencia;
- invariantes de duplicados, evidencia, facets e integridad declarada como `not_run` (el worker la ejecuta al cierre);
- último seed promovido y última sección del reporte;
- `close_required=1` si el último seed publicado no aparece en la sección de reporte más reciente;
- ranking siguiente reproducible, limitado y sin escribir archivos.

El preflight no promociona, no edita seeds/reporte/ledger, no reconstruye índices, no ejecuta `PRAGMA integrity_check` completo en cada tick y falla cerrado si no puede leer la DB o el reporte.

## Cierre batch 42

Ranking previo al batch, diez posiciones:
1. `kuroki_tomoko` — 3.007 / 4.879 / 0 = 7.886 — deferred.
2. `miyako_(blue_archive)` — 3.364 / 4.521 / 0 = 7.885 — deferred.
3. `kishin_sagume` — 3.327 / 4.548 / 0 = 7.875 — published, 8 features.
4. `ruler_(fate/apocrypha)` — 0 / 7.863 / 0 = 7.863 — deferred.
5. `w_(arknights)` — 3.388 / 4.460 / 0 = 7.848 — deferred.
6. `hifumi_(blue_archive)` — 3.378 / 4.460 / 0 = 7.838 — published, 10 features.
7. `bea_(pokemon)` — 2.886 / 4.943 / 0 = 7.829 — published, 15 features.
8. `robin_(honkai:_star_rail)` — 3.428 / 4.381 / 0 = 7.809 — published, 17 features.
9. `fischl_(genshin_impact)` — 3.542 / 4.266 / 0 = 7.808 — published, 21 features.
10. `ultimate_madoka` — 3.230 / 4.556 / 0 = 7.786 — published, 29 features.

Snapshot final del builder, reconstruido contra el fingerprint posterior a la promoción: **277 observaciones** y **149 candidatos** para las diez posiciones. Los cuatro diferidos conservaron sus conteos (Kuroki 4/1, Miyako 13/7, Ruler 1/1 y W 4/0); los seis aceptados pasaron la validación estricta con **93 features** y **0 errores**. La reconciliación retiró 7 asignaciones sin candidato (`short_hair`, `white_jacket`, `cut_in_pleats`, `purple_pumps`, `purple_high_heels`, `pink_gems`, `layered_frills`) sin borrar sus filas ni evidencias.

## Aceptación
- El report tail conserva intacto el batch 41 y añade exactamente una sección 42.
- El ranker no vuelve a seleccionar los cuatro deferred del batch 42.
- El preflight no escribe en DB/reporte/seed y su salida es estable entre dos ejecuciones.
- El worker recibe `close_required` y, ante esa bandera, solo reconcilia/cierra; nunca inicia otro batch.
- El worker mantiene scope general, un batch por tick, continuidad activada, proveedor/modelo fijados y publicación externa deshabilitada.
- El monitor sigue separado, read-only, con salida change-triggered y sin `integrity_check` minuto a minuto.
- Tras el cierre: validación de seeds, promoción idempotente, bootstrap MCP, rebuild serial de search/context/candidate, fingerprints, integridad, tests y probes reales; cualquier fallo se reporta y bloquea la reanudación.

## Verificación
```text
python scripts/general_appearance_preflight.py (dos veces; salida idéntica)
.venv/Scripts/python.exe scripts/rank_general_queue.py --limit 10
.venv/Scripts/python.exe -m unittest discover -s tests -q
.venv/Scripts/python.exe scripts/build_search_index.py
.venv/Scripts/python.exe scripts/build_context_index.py
sqlite PRAGMA integrity_check y checks de duplicados/evidencia/facets
hermes cron list (worker y monitor: estado, schedule, continuidad/modelo)
```
