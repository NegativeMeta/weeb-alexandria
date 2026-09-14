# Normalización de facetas de apariencia

## Objetivo

Convertir las facetas repetidas de las asociaciones de apariencia en un catálogo
controlado, reclasificar los casos inequívocos y separar las afirmaciones que no
son rasgos visuales sin eliminar su historial ni su evidencia.

## Contrato

- `appearance_facet_catalog` define cada faceta, su grupo semántico y si es
  visual.
- `character_appearance_features.facet_id` enlaza cada asociación con el
  catálogo; `facet` se conserva como caché textual compatible.
- Las asociaciones siguen siendo independientes por `appearance_key` y
  conservan valor, role, estado y enlaces de evidencia.
- La migración es transaccional e idempotente.
- No se eliminan filas ni enlaces de evidencia.
- `wings` será una faceta visual explícita.
- Se mantienen `identity`/biología (`gender`, `species`, `body`, `skin`) como
  grupo separado, conservando las claves públicas actuales.
- Las facetas no visuales `context` y `expression` sirven para clasificar
  registros heredados que no deben confundirse con ropa o anatomía.
- Los tags obvios de profesión/expresión se retiran del conjunto activo de
  apariencia, conservando sus filas como `retired` y sus fuentes.

## Reclasificación segura

### Desde `unclassified`

- `*_wings` y `white_wings` -> `wings`.
- `pointy_ears`, `floppy_ears`, `mouse_ears`, `rabbit_ears` -> `ears`.
- `blindfold`, `glasses`, `third_eye` -> `face`.
- `serafuku`, `black_serafuku`, `gown`, `japanese_clothes`, `plugsuit`,
  `robe`, `black_suit` -> `dress`.
- `black_blazer`, `haori` -> `jacket`.
- `green_tunic` -> `upper_body`.
- `orange_neckerchief`, `pink_neckerchief`, `red_neckerchief` -> `neck`.
- `double_halo`, `halo`, `pink_halo` -> `headwear`.
- `bamboo`, `leaf`, `plum_blossoms` -> `props`.
- `scar` -> `markings`.
- `suspenders` -> `accessories`.
- `blue_fire` -> `effects`.
- `miko`, `nontraditional_miko`, `samurai` -> `context`.
- `dancer`, `detective`, `necromancer`, `ouji_fashion` -> `context`.
- `jitome` -> `expression`.

No se reclasifican automáticamente tags desconocidos fuera de esta lista.

### Conflictos de faceta inequívocos

Se corrigen únicamente las asociaciones donde la semántica es estable:

- `pointy_ears`, `cat_ears`, `extra_ears`, `mouse_ears`, `rabbit_ears` -> `ears`.
- `third_eye` -> `face`.
- `serafuku` -> `dress`.
- `short_sleeves` -> `sleeves`.
- `black_thighhighs` -> `legwear`.
- `bow_(weapon)` -> `props`.
- `collared_shirt` -> `upper_body`.
- `frilled_shirt_collar` -> `neck`.
- `earrings` -> `jewelry`.
- `headgear`, `mob_cap` -> `headwear`.
- `glasses` -> `face`.
- `mole_on_breast` -> `body`.
- `white_wings` -> `wings`.

Los tags ambiguos, como `red_bow`, `black_ribbon` o `brown_cape`, conservan
su faceta por asociación hasta disponer de evidencia contextual suficiente.

## Consumidores

- Promoción y migración garantizan que la faceta exista en el catálogo.
- Runtime mantiene la agrupación pública por nombre de faceta y añade metadatos
  del catálogo de forma aditiva.
- El builder de candidatos usa las nuevas facetas `wings`, `markings` y
  `effects` cuando la inferencia sea inequívoca.

## Aceptación

- Todas las asociaciones activas tienen `facet_id` válido.
- Ninguna asociación activa usa `unclassified` después de la migración.
- Las filas reclasificadas conservan el mismo `feature_id` y sus enlaces.
- Los tags no visuales no aparecen como activos en el conjunto visual.
- No existen duplicados activos por `(appearance_key, facet, canonical_tag)`.
- `normalize_appearance_facets.py` produce el mismo resultado al ejecutarse dos
  veces.
- El payload MCP conserva las claves existentes y refleja las facetas nuevas.
- Tests, integridad SQLite e índices derivados pasan después de la migración.
