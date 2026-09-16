# Automatización y limpieza de apariencia

## Contrato

- `general_appearance_worker.py --tick` es la única entrada de ejecución automática.
- Un `tick` no crea otro batch si existe un manifest; continúa el actual.
- En fases `prepared`/`reviewing`, todas las decisiones deben existir. Los seeds `published` se validan contra la misma huella de DB/candidatos; cada seed inválido se convierte de forma idempotente en `deferred`, con errores literales y auditoría de la decisión original.
- Los seeds válidos siguen hacia promoción atómica y cierre; los diferidos no se publican.
- Un manifest `aborted` nunca se elimina desde `tick`; `--reconcile-aborted --run-id RUN_ID` es obligatorio.
- La reconciliación hace backup externo de la DB, valida invariantes, reconstruye índices derivados, verifica el runtime read-only, actualiza solo las métricas canónicas del último reporte y ejecuta `--clear` con el mismo `run_id`.
- La limpieza usa una lista cerrada de scripts one-shot/temporales confirmados, calcula SHA-256 y mueve primero a cuarentena externa con manifiesto. Nunca toca DBs, índices, seeds, backups ni estados.
- Después de un `close` exitoso, el worker mueve únicamente los seeds `published` explícitamente asignados a ese run hacia `seeds/archive/<run_id>/`; exige coincidencia exacta con un perfil canónico publicado, registra SHA-256/rutas/fecha en `data/appearance_seed_archive_manifest.json` y reanuda movimientos parciales sin sobrescribir destinos con hash distinto.

## Verificación

- Tests unitarios para deferencia automática, idempotencia, run_id exacto, cierre del tick, archivado selectivo/idempotente y cuarentena protegida.
- Suite completa, compilación y `git diff --check`.
- Reconciliación real del run 56, preflight `READY`, worker state ausente e índices frescos.
- Cron worker/monitor recreados solo después de verificar el estado limpio.
