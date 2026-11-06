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

## 0d. `search_knowledge`: alias stubs y tag paraguas

Probando el MCP con temas reales salieron dos defectos de recall/lectura:

1. **Filas `alias`/`invalid` ganaban por match exacto.** `search_knowledge("mating")` devolvía el
   stub `mating` (categoría alias, **3 posts**) con `confidence: high`, y el tag útil
   `mating_(animal)` solo aparecía si escribías "mating animal". Igual `2b` (stub de 54 posts).
   Regla aplicada: una fila `alias`/`invalid` es placeholder solo si su cobertura es
   insignificante (`< 1000` posts); `blushing` (2 599) y `saber` (20 415) son tags reales mal
   categorizados por la fuente y se conservan. Se filtra el resultado fusionado, no solo el
   exacto, porque el índice FTS también trae el stub.
2. **El modo multi-tag no proponía el concepto paraguas.** "dog mounting" devolvía
   `query_parts` (dog, mounting) y nada más. Ahora añade `related_tags`: tags que comparten un
   *nombre extra* con alguna parte, hallados con **una sola** consulta FTS `OR` sobre los
   aliases (`dog` y `bestiality` comparten 犬姦 → `bestiality`). Dos guardas:
   - los nombres extra compartidos por ≥3 tags son genéricos y se descartan;
   - el enlace solo corre si **todas** las partes resolvieron al tag que nombran
     (`_part_tag_is_named`), porque enlazar desde un match equivocado produce ruido seguro de sí
     mismo: "school uniform girl" proponía `cowgirl_position` y ahora no propone nada.

Medido: `dog mounting` → `related_tags: [bestiality]` con coste ~1,0 s (solo en multi-tag);
`mating` → `mating_press`, `mating_grip`, `mating_(animal)`; `2b` → `2b_(nier:automata)`;
consultas de un tag siguen en 0,00 s. `102 tests OK`, bench de personajes 27/27, guardián de
latencia dentro de presupuesto (FTS `miku` 1,55 s frío / 0,52 s tibio), auditoría stdio 7 ok.
Docs: los cuatro GLOSSARYs documentan `related_tags` y el descarte de stubs; de paso se corrigió
en ja/zh la mención obsoleta al namespace `entities`.

---

## 0e. Escaleras de calidad: alias, fragmentos, stopwords y español

Tercera tanda sobre `search_knowledge`, toda medida contra la base local:

1. **Alias-first cuando el exacto es placeholder** (`P3a`): `titjob` es alias de `paizuri`
   (115 985) y el MCP devolvía `titjob_under_clothes` (9 687). Ahora devuelve `paizuri` con
   `match_type: alias`, `confidence: high` y `note: alias of titjob`.
2. **Suelo de cobertura con discriminante de wiki** (`P3b`): una respuesta se considera
   fragmento si tiene `< 1000` posts **y** menos de 2 definiciones de wiki. Entonces se
   responde con los tags que nombran las palabras de la consulta:
   `ahegao face` → `ahegao` (72 137) en lugar de `ahegao_face` (13, 0 wikis);
   `facial cum` → `facial` (115 172) en lugar de `facial_cumshot` (3, 1 wiki).
   El discriminante importa: `mating_(animal)` tiene 204 posts pero 3 wikis, y sigue
   devolviéndose primero cuando se escribe tal cual. Cada respuesta trae `notes` con la
   sustitución.
3. **Stopwords y categoría en multi-tag** (`P5`): `tied up with rope` ya no se parte como
   `[tied up, with, rope]` sino `[tied up, rope]`, y los `related_tags` solo admiten categoría
   `general`, así que desaparecen `rope_(arknights)` y `reed_(arknights)`; `dog mounting` sigue
   devolviendo `bestiality`.
4. **Diccionario español → inglés** (`P4`): `weeb_alexandria_mcp/query_aliases_es.json` con
   **109 frases** generadas y verificadas por `scripts/build_query_aliases_es.py` (target con
   ≥1000 posts o ≥2 wikis; `ALLOW_LOW_COVERAGE` para `see_through`). `search_knowledge` traduce
   antes de buscar (frase más larga primero) y devuelve `query_translation.searched_as`.
   Resultado: **25/26** consultas en español aciertan (`tetas grandes` → `large_breasts`,
   `sexo` → `sex`, `corrida en la cara` → `facial`, `atada con cuerdas` → `bondage`,
   `vendas en los ojos` → `blindfold`); antes eran basura o vacío.

Medido: `108 tests OK` (6 nuevos), guardián de latencia dentro de presupuesto
(FTS `miku` 1,48 s frío / 0,49 s tibio), auditoría stdio 7 ok / 6 tools, bench de personajes
27/27. Latencia: consultas traducidas 0,00–0,02 s; multi-tag 1,0–2,0 s (una sola consulta FTS
adicional para el paraguas). Docs: los cuatro GLOSSARYs + `scripts/README.md`.

---

## 0f. Consistencia entre tools y gate permanente

Dos pruebas nuevas, ambas commiteadas como scripts:

1. **`scripts/mcp_consistency_probe.py`** compara `search_knowledge`,
   `resolve_character` y `get_knowledge` sobre 20 personajes y 15 tags ambiguos.
   Primera pasada: **6/20** de acuerdo y **11 casos** donde el search respondía un tag
   ínfimo mientras el resolver conocía el canónico (`Anya Forger` →
   `anya_forger`, 17 posts, vs `anya_(spy_x_family)`, 8 796).
   Causa: el discriminante de wiki trataba los nombres desnudos como tags legítimos
   (`nahida` 1 post con 4 wikis), así que el fallback no se disparaba.
   Arreglo: con `allow_character=True`, un top-1 **thin** (sin importar wiki) consulta
   `_character_recommendation` y elige su tag si tiene ≥1000 posts
   (`match_type: character`). El paso por tokens sigue reservado a fragmentos.
   Resultado: **17/20** de acuerdo, **0** respuestas flojas, **0** casos donde el
   resolver sabe más. Las 3 diferencias restantes son variantes con volumen
   (`hu_tao` 1 301 vs `hu_tao_(genshin_impact)` 14 950, `saber` 20 415 vs
   `saber_(fate)` 23 972, `miku_hatsune` 88 545 vs `hatsune_miku` 144 723): no son
   stubs y se aceptan como empate.
2. **`scripts/mcp_knowledge_bench.py`** — gate con **52 casos dorados** (12 personajes,
   17 tags EN, 12 en español, 4 paraguas multi-tag, 1 de segmentos, 2 vacíos) que
   falla si alguna respuesta baja de 1000 posts sin dos wikis, si el paraguas no
   aparece en `related_tags`, si los segmentos no son los esperados o si una consulta
   sin respuesta devuelve algo. Pasada actual: **52/52 (100%)**, exit 0.

Medido: `109 tests OK`, bench de personajes 27/27, knowledge bench 52/52,
consistencia 17/20 con cero respuestas flojas. Docs: `scripts/README.md` (dos
secciones nuevas) y los cuatro GLOSSARYs (regla de sustitución por resolver).

---

## 0g. Desempate por cobertura (bare name y permutación de tokens)

Los tres "empates legítimos" de la sección 0f se resuelven ahora por posts, sin llamar al
resolver (medido: 0,5–3,5 s incluso en caliente, y devuelve personajes absurdos para tags
como `blowjob` → `bloodberry`). Regla `_prefer_richer_variant`:

- Si el top es un **nombre desnudo** (sin `_(`) por debajo de 300 000 posts, se busca su
  variante `base_(%` con una consulta indexada (~0,15 s) y gana la de más posts:
  `saber` (20 415) → `saber_(fate)` (23 972), `hu_tao` (1 301) →
  `hu_tao_(genshin_impact)` (14 950), con `match_type: variant` y `note`.
- Si el nombre tiene **dos tokens y no está ordenado** alfabéticamente (la librería escribe
  nombres ordenados), una única búsqueda `%token%` (0,17 s) busca la permutación y exige
  mismo conjunto de tokens: `miku_hatsune` (88 545) → `hatsune_miku` (144 723).
- Nunca toca tags con franquicia, ni los que superan 300 000 posts, ni nombres ya ordenados
  (`mating_press`, `spread_legs`, `school_uniform` quedan intactos y en 0,00–0,15 s).

Medido: consistencia **20/20** de acuerdo con el resolver, **0** respuestas flojas, knowledge
bench **54/54 (100%)** con tres casos nuevos (`saber`, `hu tao`, `miku`), `111 tests OK`
(dos nuevos), bench de personajes 27/27. Docs: cuatro GLOSSARYs con la regla de desempate.

---

## 0h. Prompts escritos: segmentación tolerante y vocabulario de escena

Prueba 3 con **25 frases de prompt reales** (12 sentencias en español, 12 listas de tags en
inglés, 1 bloque canónico) midiendo qué porcentaje de los segmentos producidos resuelve a un
tag con ≥1000 posts. Línea base: **89,3 %** útil, con **12/12 frases en español al 0 %** y 11
de 25 consultas quedándose en modo single sin segmentos.

Causas encontradas y arregladas:

1. **La traducción inyectaba espacios** (`kimono ,`) y rompía las listas con comas. Se
   normaliza la puntuación después de traducir.
2. **La lista con comas era todo-o-nada**: `all(_exact_tag_rows(...))` obligaba a que *todas*
   las entradas fueran tags exactos; una sola desconocida (`sitting in snow`) descartaba el
   prompt entero. Ahora cada entrada se resuelve y, si no es un tag exacto, se segmenta palabra
   por palabra.
3. **El DP exigía cubrir todas las palabras**: `escena`, `grande`, `vista` anulaban la
   segmentación. Ahora una palabra desconocida se salta y los spans de alrededor se conservan.
4. **Una sugerencia fuerte bloqueaba el multi-tag**: `retrato nocturno…` devolvía `neon` como
   sugerencia en vez de 4 segmentos. Con ≥3 segmentos la segmentación gana.
5. **Números en palabras**: `two girls` caía en `two_girls` (69 posts) y el fallback por token
   lo "arreglaba" con `two_piece_swimsuit` (574k). Se normaliza a `2girls` (1 320 802) y el
   fallback por token ya solo acepta tags de **una** palabra.
6. **Vocabulario de escena**: el mapa ES pasó de 109 a **161 frases** (ropa, colores
   combinados, encuadres, escenarios, verbos). Los colores sueltos se descartaron porque
   resolvían a `red_eyes`/`black_hair`/`pink_nipples`; ahora van en compuestos
   (`kimono rojo` → `red kimono`, `falda roja` → `red skirt`).

Resultado: **100 % útil (98/98 segmentos)**, **25/25** frases en modo multi_tag, **0** frases
bajo 60 %. Gates: `114 tests OK` (3 nuevos), knowledge bench 54/54, consistencia 20/20, bench de
personajes 27/27. Docs: `scripts/README.md` (sección del probe) y los cuatro GLOSSARYs.

---

## 0i. El contrato que lee el modelo, en inglés

Tres de las seis tools tenían la descripción en **español** (`search_knowledge`,
`get_knowledge`, `get_sources_status`): el docstring es lo que el modelo que llama lee como
descripción, así que el contrato estaba partido por idioma. Traducidas las tres al inglés y
enriquecidas con lo que devuelven hoy (`query_mode`, `query_parts`, `related_tags`, `notes`,
`query_translation`).

Añadido `FastMCP(instructions=...)` en inglés, que el cliente ve antes de cualquier llamada, con
tres reglas: idioma (manda tags en inglés; el español se acepta y se traduce), enrutado
(`resolve_character` antes de trabajo de personaje) y prompts (`multi_tag` + `query_parts`).

Campo nuevo `query_translation.untranslated`: las palabras que no cubrió ni un segmento ni una
traducción. Medido: `pirata con parche en el ojo y loro` → `["pirata","parche","ojo","loro"]`;
`chica con kimono rojo sentada en la nieve` → sin campo, porque todo quedó cubierto. Es la señal
para que el modelo reintente exactamente esas palabras en inglés.

Gates: `117 tests OK` (3 nuevos, uno vigila que las descripciones sigan en inglés y que haya seis
tools). Docs: párrafo del contrato de idioma en los cuatro GLOSSARYs.

---

## 0j. Prompts narrativos reales y presupuesto de payload

Dos pruebas nuevas sobre datos reales, no sobre frases inventadas.

**Corpus real**: se extrajeron los workflows de ComfyUI (`user/default/workflows`, 119
archivos) → 34 prompts únicos de prosa narrativa de 30-80 palabras. Línea base: **0 de 12
respondían** y cada llamada tardaba **34 s**.

| Causa | Evidencia | Arreglo |
|---|---|---|
| `_tag_suggestions` recorría los 47 tokens del prompt (prefijo 2 000 filas + escaneo de sufijo por token) | 34,58 s en una sola consulta | Sugerencias solo si hay <3 segmentos y máximo 4 tokens (los más largos) |
| El DP de spans se rendía con >12 palabras | prosa = 0 segmentos | Troceo por puntuación + ventanas de 12 palabras con solape |
| Un prompt generaba 40-65 partes, cada una con FTS + resolver | 34-42 s | Tope de **12** partes (las más específicas) y resolver de personaje solo en las **4** primeras |
| Cada parte pagaba una FTS aunque viniera de un tag exacto | ~0,5-2 s por parte | Lookup indexado exacto y FTS solo en caso de fallo |
| `untranslated` contaba palabras de partes descartadas por el tope | 8 palabras "sin tag" que sí tenían | Se mide contra la lista completa; `query_parts_total` informa el total |

Resultado: **33/34 prompts con segmentos (97 %), 32/34 con tag usable (94 %)**, 326 segmentos
(67 % con ≥1000 posts), **p50 4,20 s · p95 7,87 s**.

**Presupuesto de payload**: gate `scripts/mcp_payload_budget.py` con 11 casos y presupuesto
por caso. Hallazgo: `search_characters(scope="all")` devolvía **94 231 B (~23 557 tokens)** en
una sola respuesta. Arreglado con `page_size=25` (param nuevo, antes fijo en 72) y
`detail="summary"` (rasgos como `{facet, value}`, sin `evidence_tag`; `detail="full"` lo
conserva). Ahora **19 310 B** (−79 %) y **0 casos fuera de presupuesto**; el mayor es
`get_character(include_evidence=True)` con 26 KB.

Gates: `121 tests OK` (+4: page_size/detail, evidencia en full, `detail` inválido, tope de 12
partes y payload <20 KB).

---

## 0k. Ruido de calidad fuera y frases que no son tags

Sobre el ejemplo real (`A finished cinematic editorial portrait of an adult woman, …`), la
respuesta seguía trayendo adjetivos como `finished` (27 724), `cinematic` (4) y `controlled`
(111) presentados como contenido, y `adult woman` resolvía a `adult` (9 248, alias) en vez de
`mature_female` (110 035). Además `skin` devolvía `skin_fang` por coincidencia de prefijo.

| Arreglo | Detalle |
|---|---|
| `_PROMPT_QUALIFIERS` | Calificadores y marcadores de render descartados como parte (solo palabras sueltas, así `depth of field` sobrevive) |
| `_keep_segment` | Un único punto de filtrado para palabras de unión y calificadores |
| `query_aliases_es.json` → `english_phrases` | 6 reescrituras en inglés verificadas: `adult woman/adult women/grown woman` → `mature_female`, `adult man/adult men/grown man` → `mature_male` |
| `_NAME_MATCH_TYPES` | Una parte de una sola palabra solo mantiene tags que **son** esa palabra (exact/normalized/alias/wiki_redirect/variant_base/character); prefijo, partial y fuzzy quedan fuera |
| `untranslated` | Ya no lista los calificadores descartados a propósito |

Medición sobre el mismo prompt: **17,53 s → 3,53 s**, partes `portrait`, `mature female`,
`facial`, `natural`, `texture` (sin `finished`/`cinematic`/`controlled`, sin `skin_fang`).
Corpus de 34: 33/34 con segmentos, 32/34 con tag usable, p50 4,00 s · p95 7,66 s, 1 caso sobre
8 s. Probe de 25 frases: 100 % tras añadir `character` a los match types (Gura volvía a
resolverse). Gates: `124 tests OK` (+3).

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
