# Normalización del catálogo de features de apariencia

## Objetivo
Separar el vocabulario global de rasgos visuales reutilizables de las asignaciones concretas de cada perfil, conservando la evidencia por asociación y manteniendo compatible la respuesta MCP existente.

## Contrato

- `appearance_feature_catalog` contiene una fila por `canonical_tag` global.
- `character_appearance_features` continúa siendo la tabla de asociaciones `(appearance_key, canonical_tag)` y conserva `facet`, `value`, `role`, estado y confianza específicos de esa apariencia.
- Cada asociación activa debe tener `catalog_id` resoluble al catálogo.
- `canonical_tag` del catálogo es la identidad canónica; la columna homónima de la asociación se conserva como caché compatible y debe coincidir con el catálogo.
- Una misma feature, por ejemplo `black_hair`, puede tener muchas asociaciones a perfiles, pero una sola definición en el catálogo.
- `character_appearance_feature_sources` continúa enlazando evidencia a la asociación, no al concepto global.
- El MCP conserva las claves públicas actuales (`facet`, `value`, `canonical_tag`, `feature_count`, `evidence`, etc.); la normalización es interna y no elimina información.
- La migración debe ser transaccional, idempotente y validar perfiles, asociaciones, catálogo y enlaces antes de hacer commit.

## Esquema

`appearance_feature_catalog`:

- `catalog_id INTEGER PRIMARY KEY`
- `canonical_tag TEXT UNIQUE NOT NULL`
- `default_facet TEXT NOT NULL`
- `default_value TEXT NOT NULL`
- `label TEXT NOT NULL`
- `provenance TEXT NOT NULL`
- `confidence TEXT NOT NULL`
- `status TEXT NOT NULL`

La asociación añade `catalog_id` y un índice por catálogo. El catálogo usa un facet/label representativo; la faceta y el valor de una asociación siguen siendo específicos del personaje/variante.

## Migración

1. Crear el catálogo y la columna/index si no existen.
2. Normalizar facetas heredadas y deduplicar asociaciones por apariencia/tag antes de sincronizar el catálogo.
3. Crear o actualizar exactamente un concepto por `canonical_tag` y enlazar todas las asociaciones.
4. Comprobar que no queden asociaciones activas sin catálogo ni discrepancias entre IDs y tags.
5. Registrar versión de esquema `2` y métricas de migración.
6. Repetir la migración no debe crear filas adicionales ni cambiar conteos.

## Consumidores

- El promotor upserta el concepto global antes de insertar la asociación.
- La migración heredada y el esquema compartido mantienen el catálogo sincronizado.
- El runtime MCP lee el tag canónico desde el catálogo con fallback compatible para bases antiguas.
- `get_sources_status` expone el conteo del catálogo de forma aditiva.
- Los índices derivados no requieren cambios de formato: se reconstruyen después de modificar la base canónica.

## Aceptación

- La base actual conserva 264 perfiles publicados y 2,308 asociaciones publicadas.
- El catálogo contiene 719 conceptos canónicos activos (o el conteo equivalente validado desde las asociaciones activas).
- `black_hair` aparece una vez en el catálogo y mantiene todas sus asociaciones/evidencias.
- No hay asociaciones activas sin `catalog_id`, duplicados `(appearance_key, catalog_id)` ni features publicadas sin evidencia.
- Promover un seed nuevo y promoverlo dos veces es idempotente.
- La API MCP devuelve el mismo contenido semántico de features antes/después.
- La suite `unittest`, las reconstrucciones de índices, `PRAGMA integrity_check`, `git diff --check` y una sonda MCP real pasan.

## No objetivos

- No fusionar personajes, variantes o facetas.
- No mover la evidencia desde la asociación al catálogo global.
- No hacer commit, push, publicación externa ni cambiar el ranking de batches.
