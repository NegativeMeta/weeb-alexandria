# Weeb Alexandria — continuación de la limpieza de superficie MCP

> **Para la próxima sesión:** este plan retoma el trabajo ya implementado y verificado el
> 2026-11-05. No rehagas lo hecho: verifícalo con la sección "Cómo arrancar" y sigue por
> los pendientes.

**Estado:** continuación ejecutada el 2026-11-05 (sesión 2). Superficie en 6 tools otra vez
(por `resolve_character`), resolver reescrito con ranking por evidencia (22/22 en la batería
de personajes populares), 98 tests OK, tres scripts de mantenimiento vendorizados. Único
pendiente real: **commit** (requiere autorización de Johiny).

## 0. Continuación 2026-11-05 — qué se hizo y con qué evidencia

Las 3 decisiones de contrato quedaron sin respuesta (formulario expirado), así que se aplicó
la opción recomendada en cada una y el commit se dejó pendiente.

| Ítem | Decisión / resultado | Evidencia |
|---|---|---|
| A. Tools visibles en sesión nueva | **verificado** | `tool_search` → `mcp__weeb_alexandria__*`; `get_sources_status` respondió con `structured_mode: "owned_local_tables"` |
| A2. Harness vendorizado | **hecho** | `scripts/mcp_surface_audit.py` → `tools/list: 6 tools`, `summary: 7 ok, 0 errors`, initialize 0,98 s |
| B. Commit | **pendiente de autorización** | nada commiteado; todo sigue en working tree |
| C. Facets sin `q` | **opción 2** (`scope="legacy"` / `"all"`, default legacy) | `hair_color="white"`: legacy 4 → `scope="all"` 38 |
| D. `gender` con poca evidencia | **opción 1** (documentado en la descripción) | docstring: "only matches profiles that carry gender evidence" |
| E. Recomendador | **opción 2**: 6ª tool `resolve_character` | `resolve_character("Anya Forger")` → `recommended_tag: "anya_forger"`, `tag_match: true`, `found: false`, `notes` avisando que es tag `general` (17 posts) |
| F. Descripciones honestas | **hecho** | `search_characters` (scope + gender) y `get_character` (candidatos ≠ fuzzy, usar `resolve_character`) visibles en `hermes mcp test` |
| G. Guardián de latencia | **opción 1** | `scripts/bench_mcp_tools.py`: `fts_tag_rows(miku)` cold 1,89 s / warm 0,58 s, presupuesto 2,0 s → exit 0 |
| Tests | **95 tests, OK** | `Ran 95 tests in 26.310s / OK` (90 previos + 5 nuevos) |

Payloads medidos por el harness (referencia para futuras regresiones):

```
get_sources_status                    0,31 s    716 B
search_knowledge("hatsune miku")      0,00 s    515 B
get_knowledge("hatsune_miku")         0,00 s  6 277 B
search_characters("gawr gura")        0,00 s  3 761 B
search_characters(white, scope=all)   0,03 s 136 827 B (total 38)
get_character("hatsune_miku")         0,00 s  5 452 B
resolve_character("Anya Forger")      2,63 s  2 544 B
```

Archivos nuevos de esta continuación:

```
scripts/mcp_surface_audit.py     scripts/bench_mcp_tools.py
```

Archivos modificados de esta continuación (además de los de la tanda anterior):

```
weeb_alexandria_mcp/server.py    tests/test_search.py    scripts/README.md
README.md  README.es.md  README.ja.md  README.zh-CN.md
GLOSSARY.md  GLOSSARY.es.md  GLOSSARY.ja.md  GLOSSARY.zh-CN.md
```

---



---

## 0b. Resolver de personajes: ranking por evidencia (misma sesión)

La batería de 22 personajes populares mostró que `resolve_character` acertaba **11/22**.
Diagnóstico: el sort castigaba todo tag con `_(` (o sea todo tag canónico de Danbooru), el
tag "exacto" se sembraba con `confidence: high` sin mirar cobertura, y el gate de ambigüedad
devolvía `null` en nombres de una palabra. Además el resolver no consultaba ni las tablas de
aliases ni el `display_name` de los perfiles, que sí usan `get_character`/`get_knowledge`.

Cambios aplicados en `_character_recommendation`:

| P | Cambio | Código |
|---|---|---|
| P1 | Alias-first (`_resolve_canonical_tag`: aliases, alias column, wiki redirect) antes de adivinar por popularidad | `alias_target` + `_owned_profile_source` |
| P2 | Ranking `post_count × peso de match × cobertura de tokens`, sin castigar `_(` | `_MATCH_WEIGHTS`, `_match_score`, `_tag_post_count` |
| P3 | Ambigüedad solo entre bases distintas y con empate real (top < 3× el segundo); aun así devuelve el mejor candidato | `_base_character_name`, bloque `ambiguous` |
| P4 | `found` se calcula sobre el tag recomendado (post-alias), no sobre el slug literal | `winner_source` |

Antes/después (misma base de datos, mismos 22 casos):

| Estado | Resultado |
|---|---|
| Antes | 11/22 · 5 tags de cobertura ínfima (`tao_blu` 426, `anya_forger` 17, `zero_two` 3, `asuka_langley` 1, `bocchi` artist 3) · 6 `null` (Furina, Nahida, Saber, Rem, Makima, 2B) |
| Después | **22/22** · `furina_(genshin_impact)`, `nahida_(genshin_impact)`, `saber_(fate)`, `rem_(re:zero)`, `makima_(chainsaw_man)`, `2b_(nier:automata)`, `zero_two_(darling_in_the_franxx)`, `souryuu_asuka_langley`, `bocchi_(bocchi_the_rock!)`, `anya_(spy_x_family)` |
| Tarjetas | 14/22 sirven tarjeta; las otras 8 no tienen perfil de apariencia revisado (`found: false` es honesto) |

Verificado: `scripts/mcp_character_bench.py` → `resolved 22/22` (exit 0) ·
`scripts/mcp_surface_audit.py` → 7 ok, 0 errors, `resolve_character` 2,50 s / 2 418 B ·
`98 tests OK` (`Ran 98 tests in 31.415s`).

Limitación reportada en esa iteración: `resolve_character("miku")` proponía `miku_hatsune`
(88 545) en vez de `hatsune_miku` (144 723). **Resuelta en la sección 0c** — la causa era el
recall por prefijo, no el peso del alias.

---

## 0c. Nicknames (`miku` → `hatsune_miku`)

El límite reportado no era el peso de alias: `_tag_suggestions` construye su pool con
`name LIKE 'token%'`, o sea **solo prefijos**, así que un tag canónico cuyo primer vocablo es el
apellido/franquicia (`hatsune_miku`, `gawr_gura`, `inugami_korone`, `mori_calliope`) nunca
entraba como candidato. `miku_hatsune` (88 545) ganaba por default, no por mérito.

Opciones evaluadas:

| Opción | Medición | Veredicto |
|---|---|---|
| Bajar el peso de alias 3× → 1,5× | `hatsune_miku` ni estaba en el pool: no cambia nada | descartada |
| Pool desde `_tag_rows` (exacto + prefijo + FTS) | 0,00–1,44 s por consulta y FTS no encuentra `gawr_gura` | aplazada (queda como fuente 5) |
| Tabla curada nickname → tag | funciona pero suma mantenimiento manual | descartada |
| **Escaneo de sufijo acotado** | `name LIKE '%!_token' ESCAPE '!'` → **0,14–0,17 s** sobre 1,5 M filas; devuelve `gawr_gura`, `hatsune_miku`, `inugami_korone`, `mori_calliope` | **aplicada** |

Cambios: paso de recall por sufijo del último token (≥4 caracteres, 8 filas, peso `suffix` 1.2)
y ambigüedad por **conjunto de tokens** con rival solo entre bases distintas, para que
`miku_hatsune` no cuente como competidor de `hatsune_miku`.

Resultado: `miku`→`hatsune_miku` (`ambiguous: false`), `gura`→`gawr_gura`,
`korone`→`inugami_korone`, `calliope`→`mori_calliope`, `pekora`→`usada_pekora`.
`fubuki` sigue ambigua y es correcto (15 101 vs 12 649). Bench **27/27** (5 casos de nickname
añadidos) y **99 tests OK**; costo +0,15 s por consulta con token final ≥4 caracteres.

---

## 1. Lo que ya está hecho (no rehacer)

Spec original: `.hermes/plans/2026-11-05_1310-mcp-surface-cleanup.md`

| Cambio | Estado | Evidencia |
|---|---|---|
| Superficie 6 → 5 tools | hecho | `tools/list` = `search_knowledge`, `get_knowledge`, `search_characters`, `get_character`, `get_sources_status` |
| `get_character_appearance` → `get_character` | hecho | `hermes mcp test` ✓ Connected 2312 ms, 5 tools |
| `get_tag_knowledge` → `get_knowledge` | hecho | idem |
| `get_character(slug)` legacy eliminada | hecho | nombres viejos → `Unknown tool` |
| FTS: CTE con doble `ORDER BY` → dos pasos | hecho | 21,9 s → **0,7 s**; `search_knowledge("miku", category="character")` 23,2 s → **0,79 s** |
| Alias desde `tags.aliases` (`alias_column`) | hecho | `GawrGura`, `がうるぐら`, `gawrt` → `gawr_gura`; solo se consulta si la tag exacta es débil |
| Facets honrados en fallback de apariencia | hecho | `q="suisei"` + `blue_hair` → 1; + `red_hair` → 0; `hair_color="white"` sigue en 4 (legacy intacto) |
| `include_evidence=False` por defecto; `limit` → `evidence_limit` | hecho | ficha de Suisei 157 KB → **13,8 KB** |
| `search_knowledge` sin bloque `entities` | hecho | claves de respuesta: `query`, `tag_library` |
| Docs al nuevo contrato | hecho | README ×4, GLOSSARY ×4, `docs/CHARACTER_APPEARANCE_PROFILES.md`, `docs/huggingface_dataset_card.md` |
| Tests readaptados | hecho | `Ran 90 tests ... OK` (403 s) |

Archivos tocados por esta tanda:

```
weeb_alexandria_mcp/server.py
weeb_alexandria_mcp/appearance_runtime.py
tests/test_search.py
README.md  README.es.md  README.ja.md  README.zh-CN.md
GLOSSARY.md  GLOSSARY.es.md  GLOSSARY.ja.md  GLOSSARY.zh-CN.md
docs/CHARACTER_APPEARANCE_PROFILES.md  docs/huggingface_dataset_card.md
.hermes/plans/2026-11-05_1310-mcp-surface-cleanup.md
```

---

## 2. Cómo arrancar (5 minutos)

```bash
cd /c/Users/johin/Code_Library/AI/WeebAlexandria

# 1) superficie y handshake, con el mismo comando que usa Hermes
hermes mcp test weeb_alexandria          # esperado: ✓ Connected + 5 tools

# 2) estado del código
git status --short
git diff --stat -- weeb_alexandria_mcp tests

# 3) suite completa (~7 min)
env -u PYTHONPATH .venv/Scripts/python.exe -u -m unittest discover -s tests -v
# esperado: Ran 90 tests ... OK
```

Nota: `hermes mcp test` se colgó durante ~1 h el 2026-11-05 (también con `codegraph`).
Si vuelve a colgarse, no es del proyecto: usa el harness stdio (tarea A2) y sigue.

---

## 3. Pendientes

> Histórico: A, A2, C, D, E, F y G quedaron resueltos en la sesión 2 — ver la sección 0 para
> la decisión tomada y la evidencia. Sigue abierto **B (commit)**.

### A. Verificación en sesión nueva (bloqueante para usar las tools)

**Objetivo:** que el agente pueda llamar `mcp__weeb_alexandria__*` de verdad.

En la sesión anterior las tools no estaban cargadas porque el toolset se fija al abrir la
sesión. El servidor ya responde bien por stdio.

**Pasos**
1. Reiniciar la app de escritorio (o abrir sesión nueva).
2. `tool_search` por "weeb alexandria" y `tool_call` con `mcp__weeb_alexandria__get_sources_status`.
3. Esperado: `structured_mode: "owned_local_tables"` y 5 tools disponibles.

#### A2. Vendorizar el harness (recomendado)

Los scripts de auditoría viven en el scratch de Hermes
(`C:\Users\johin\AppData\Local\hermes\cache\scratch\alexandria_audit*.py`), que se poda a
las 24 h de inactividad. Si se quiere repetible:

- Crear: `scripts/mcp_surface_audit.py` — cliente stdio mínimo (JSON-RPC por líneas:
  `initialize` → `notifications/initialized` → `tools/list` → `tools/call`), lanzando
  `cmd /d /c run.bat`; imprime latencia y tamaño de payload por tool.
- Criterio: `python scripts/mcp_surface_audit.py` lista 5 tools y ninguna llamada falla.

---

### B. Commit selectivo (requiere autorización explícita)

**Problema:** el repo ya venía sucio antes de esta tanda. Un `git add -A` mezclaría trabajo
ajeno.

Pre-existentes (no tocar en este commit): `reports/hololive_appearance_queue.md`,
`scripts/README.md`, `scripts/general_appearance_worker.py`,
`tests/test_general_appearance_worker.py`, `docs/PUBLISHED_PROFILES.md`,
`scripts/build_batch1xx_reviewed_tmp.py` (×10+).

Mezclados (contienen hunks ajenos **y** de esta tanda): `README.md`, `README.es.md`,
`README.ja.md`, `README.zh-CN.md`.

**Opciones**
1. Commit de esta tanda con los archivos limpios + `git add -p` en los README para separar hunks.
2. Commit de todo (incluye trabajo previo) con mensaje que lo diga.
3. No commitear.

**Verificación:** `git show --stat HEAD` debe listar solo lo acordado.

---

### C. P3-a — búsqueda solo por facets (sin `q`)

**Situación:** `search_characters(hair_color="white")` sigue devolviendo los 4 perfiles
legacy, no los ~N de los 776 con apariencia. Los facets solo actúan sobre apariencia
cuando se pasa `q`.

**Por qué no se hizo:** cambiaría el `total` documentado (4 → N) y hay tests/docs que lo fijan.

**Opciones (elegir una)**
1. Dejarlo y documentar la limitación en el docstring de `search_characters`.
2. Añadir `scope: "legacy" | "all"` (default `legacy`): compatible hacia atrás, explícito.
3. Cambiar el default a `all` y actualizar `test_search_characters_keeps_legacy_facet_contract`
   + READMEs + GLOSSARY.

**Criterio de aceptación (opción 2/3):**
```bash
env -u PYTHONPATH .venv/Scripts/python.exe -c "
import weeb_alexandria_mcp.server as S
print(S.search_characters(hair_color='white')['total'])                 # legacy: 4
print(S.search_characters(hair_color='white', scope='all')['total'])    # > 4
"
```

**Archivos:** `weeb_alexandria_mcp/server.py` (`search_characters`, `_appearance_characters`),
`tests/test_search.py`, README ×4.

---

### D. P3-b — `gender` solo tiene evidencia en 22 de 867 perfiles

**Situación:** el filtro `gender` es estricto sobre evidencia de apariencia; personajes sin
evidencia (ej. `hoshimachi_suisei`) devuelven 0 aunque sean 1girl.

**Opciones**
1. Documentarlo en la descripción de la tool (barato, honesto).
2. Ampliar datos: agregar `1girl/1boy` al perfil default desde el tag del personaje o desde
   `character_traits` (requiere corrida del worker de apariencias + revisión).

**Criterio:** para cualquier personaje con evidencia (`2b_(nier_automata)` → `female` = 1;
`9s_(nier_automata)` → `male` = 1) y mensaje/documentación clara para el resto.

---

### E. P3-c — ¿reexponer el recomendador de nombres?

**Situación:** la tool legacy era también el motor de recomendación
(`recommended_tag`, `recommendation.confidence/match_type/matched_work`, `tag_match`,
`recommendations`). Al eliminarla, `get_character` solo devuelve `resolution`, `ambiguous`,
`candidates`, `message`.

Caso que quedó peor: `get_character("Anya Forger")` no incluye `anya_forger` en los 10
candidatos (antes lo recomendaba con `match_type=normalized`).

**Opciones**
1. Aceptar `candidates` como suficiente (superficie mínima).
2. Añadir 6ª tool `resolve_character(query) -> {recommended_tag, confidence, match_type, matched_work, ambiguous, candidates}`
   reusando `_tag_suggestions` (sigue en el módulo, ~60 líneas).

**Criterio (opción 2):** `resolve_character("Anya Forger")["recommended_tag"] == "anya_forger"`
y suite verde.

---

### F. Honestidad de las descripciones (barato, recomendado)

Añadir a los docstrings:
- `search_characters`: "Los facets se aplican a los perfiles legacy y, con `q`, también a los
  personajes de apariencia; `gender` solo donde hay evidencia."
- `get_character`: "Todas las variantes del personaje; usa `variant` para una sola y
  `include_evidence` para las citas."

**Criterio:** `hermes mcp test weeb_alexandria` muestra las descripciones nuevas.

---

### G. Guardián de latencia (evitar que el CTE vuelva)

**Opciones**
1. `scripts/bench_mcp_tools.py` (manual, sin CI): imprime latencia por tool y falla si
   `_fts_tag_rows('miku')` > 2 s.
2. Test unitario en `tests/test_search.py` con `SEARCH_DB` real — riesgo de flakiness por IO;
   si se elige, marcar `@unittest.skipUnless` cuando falte el índice.

**Criterio:** un cambio futuro que reintroduzca el doble `ORDER BY` se detecta en <1 min.

---

### H. Otros (baja prioridad)

- Revisar prosa nueva en `GLOSSARY.ja.md` / `GLOSSARY.zh-CN.md` (la escribí yo; verificar tono).
- `docs/huggingface_dataset_card.md`: si se republica en HF, requiere autorización y `hf` CLI.
- Limpieza opcional: `.db` de 0 bytes (`appearance.db`, `character_appearance.db`,
  `weeb_alexandria.db`, `data/*.db`), `tmp_candidates_batch49.db`, `backups/`.
- `tag_library.db` (833 MB) + `data/character_context.sqlite` (734 MB) dentro del repo: decidir
  si siguen versionados o pasan a `H_Hub`/release.

---

## 4. Decisiones que necesitan a Johiny

1. **C** — resuelto por default recomendado: `scope="legacy"` (default) / `"all"`. Si prefieres
   que `"all"` sea el default, es un cambio de una línea + actualizar el test `..._keeps_legacy_facet_contract`.
2. **E** — resuelto por default recomendado: `resolve_character` existe como 6ª tool. Si la
   superficie mínima importa más, se quita la tool y queda `candidates` (el helper sigue en pie).
3. **B** — **sigue abierto**: ¿commit selectivo de esta tanda, commit total (arrastra el trabajo
   previo), o nada? Nada se ha commiteado.

---

## 5. Riesgos

- Sin aliases de compatibilidad: cualquier script externo con `mcp__weeb_alexandria__get_tag_knowledge`
  falla con `Unknown tool` (verificado). Los agentes redescubren tools por sesión.
- `alias_column` añade un lookup FTS (~0,6 s) solo en nombres débiles/inexistentes.
- El rename obliga a reiniciar la app para que el agente vea los nombres nuevos.
