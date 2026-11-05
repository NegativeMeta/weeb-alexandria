# Weeb Alexandria — limpieza de superficie MCP (P0+P1)

Fecha: 2026-11-05 · Autorización: Johiny ("implementemos el plan", "quitar get_character", renombrar tools).

## Objetivo

Reducir la superficie de 6 a 5 herramientas, eliminar la herramienta con 2,6 % de cobertura, arreglar la latencia del fallback FTS (~20 s → <1 s), resolver alias de la columna `tags.aliases`, honrar los facets en el fallback de apariencia y bajar el payload por defecto de la ficha de personaje.

## Superficie resultante (contrato)

| Tool | Reemplaza a | Contrato |
|---|---|---|
| `search_knowledge(query, category=None, limit=25)` | igual | Busca **solo tags** en la librería unificada. Se elimina el bloque `entities` (personajes/artistas/franquicias): su dueño es `search_characters`. |
| `get_knowledge(tag, include_relations=True, limit=50)` | `get_tag_knowledge` | Ficha de **una** tag: `tags[]`, `definitions[]` (wiki), `aliases[]`, `implications[]`, `resolution`. |
| `search_characters(q="", copyright, hair_color, hair_length, eye_color, gender, sort, page)` | igual | Busca/listа personajes. Los facets ahora se aplican también a los personajes de `character_appearance_profiles` cuando se pasa `q`. |
| `get_character(character, variant=None, include_evidence=False, evidence_limit=100)` | `get_character_appearance` | Ficha canónica de **un** personaje con todas sus variantes/outfits, features por facet, `facet_metadata` y evidencia opcional. Es el único dueño de la apariencia. |
| `get_sources_status()` | igual | Salud + conteos. Sin cambios. |

Eliminada: `get_character(slug)` legacy (20 perfiles legacy = 2,6 % de 776 personajes; su data está en `search_characters` + `get_character`).

### Cambio de precedencia en resolución de nombre (`_resolve_canonical_tag`)

```
exact tag (fuerte: post_count>0 y categoría ∉ {general, invalid, alias})
→ tag_aliases (antecedent → consequent, active)
→ wiki "Use X instead"
→ variant_base  ("x_(y)" → "x")
→ NUEVO: alias_column  (token presente en tags.aliases, vía índice FTS)
```

`alias_column` solo se evalúa si la coincidencia exacta es débil o inexistente, para no pagar el costo cuando la tag ya existe con posts (ej. `hololive`).

### Facets en `search_characters`

Filtro legacy (sin cambios, sobre `character_traits`): `eye_color`, `hair_color`, `hair_length`, `gender`.
Nuevo, sobre `character_appearance_features` (perfil elegido por personaje):

| Param | facet | condición |
|---|---|---|
| `eye_color=x` | `eyes` | `canonical_tag = x_eyes` |
| `hair_color=x` | `hair` | `canonical_tag = x_hair` y no es slug de longitud |
| `hair_length=x` | `hair` | `canonical_tag = x_hair` y **sí** es slug de longitud |
| `gender=female/male` | `gender` | `1girl` / `1boy` |

Longitudes conocidas: `very_short_hair, short_hair, medium_hair, long_hair, very_long_hair, absurdly_long_hair`.

## No-objetivos

- Búsqueda solo-por-facets sobre los 776 personajes sin `q` (cambiaría el `total` documentado; queda como P3).
- Recortar `definitions[]` de `get_knowledge` (es su valor; el `limit` ya acota aliases/implications).
- Commit, push o publicación.

## Archivos en alcance

- `weeb_alexandria_mcp/server.py` (tools, `_fts_tag_rows`, `_resolve_canonical_tag`, `_appearance_characters`)
- `weeb_alexandria_mcp/appearance_runtime.py` (`evidence_limit`, default sin evidencia)
- `tests/test_search.py` (imports + casos nuevos)
- `README.md`, `README.es.md`, `README.ja.md`, `README.zh-CN.md`, `GLOSSARY*.md`, `docs/CHARACTER_APPEARANCE_PROFILES.md`, `docs/huggingface_dataset_card.md`

## Criterios de aceptación

1. `tools/list` → exactamente 5 nombres: `search_knowledge, get_knowledge, search_characters, get_character, get_sources_status`.
2. `search_knowledge("miku", category="character")` < 2 s (era 23,2 s).
3. `_fts_tag_rows` directo con `miku` y `hatsune_miku` < 2 s (era 21,9 s / 21,2 s).
4. `get_knowledge("GawrGura")` → `tag="gawr_gura"`, `resolution.type="alias_column"`.
5. `get_knowledge("がうるぐら")` → `found=True`, `tag="gawr_gura"`.
6. `get_character("GawrGura")` → `found=True`, `character_tag="gawr_gura"`.
7. `search_characters(q="suisei", hair_color="red_hair")` → 0; con `blue_hair` → 1.
8. `search_characters(hair_color="white")` → sigue devolviendo 4 (contrato legacy intacto).
9. `get_character("hoshimachi suisei")` sin evidencia < 20 KB (era 157 KB).
10. `get_character` no devuelve `profiles` vacío para personajes solo-apariencia; `found=True`.
11. Suite `python -m unittest discover -s tests` verde.
12. `hermes mcp test weeb_alexandria` → ✓ Connected, 5 tools.

## Riesgos

- Rename rompe consumidores con nombres hardcodeados: se actualizan docs del repo; los agentes redescubren tools por sesión.
- `alias_column` agrega un lookup FTS en misses: acotado a nombres débiles, medido <1 s.
- Sin alias de compatibilidad (duplicaría superficie, contra el objetivo).

## Addendum (implementación)

La tool legacy `get_character(slug)` era también el motor de recomendación de nombres
(`recommended_tag`, `recommendation.confidence/match_type/matched_work`, `tag_match`,
`recommendations`). Al eliminarla, esos campos desaparecen de la superficie: el
diagnóstico de resolución queda en `get_character` como `resolution`, `ambiguous`,
`candidates` y `message` (misma capacidad de sugerir, sin las métricas internas).
`_tag_suggestions` sigue en el módulo, así que reexponer un `resolve_character`
dedicado sería barato si hiciera falta.

Tests de `tests/test_search.py` readaptados a `candidates`; se retiraron 3 casos cuyo
único objeto era un campo eliminado (`matched_work`, `confidence/match_type`,
`appearance` aditivo).
