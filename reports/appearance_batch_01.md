# Appearance population — Batch 01

**Status:** candidate generation complete; human review pending
**Date:** 2026-08-28
**Source:** local `tag_library.db` wiki snapshot
**Canonical output:** `data/character_appearance.sqlite` (derived, not published)

## Scope

The first batch intentionally contains five characters with different review
risks:

- `2b_(nier_automata)` — complex recognizable outfit, sparse canonical-name
  coverage in the local snapshot;
- `ganyu_(genshin_impact)` — distinctive horns, hair, flower, and costume;
- `hatsune_miku` — many contextual variants and high contamination risk;
- `hakurei_reimu` — multiple variants and possible color conflicts;
- `yor_briar` — relatively clear base outfit and accessories.

Korone remains the golden card and is not part of this new batch.

## Generation result

Command:

```bash
.venv/Scripts/python.exe scripts/build_appearance_candidates.py \\
  --db tag_library.db \\
  --output data/character_appearance.sqlite \\
  --character '2b_(nier_automata)' \\
  --character 'ganyu_(genshin_impact)' \\
  --character 'hatsune_miku' \\
  --character 'hakurei_reimu' \\
  --character 'yor_briar'
```

Observed result:

| Character | Observations | Variants observed | Candidates | Empty facets | Decision |
|---|---:|---:|---:|---:|---|
| `2b_(nier_automata)` | 0 | 0 | 0 | 0 | Hold: local wiki uses `2b_(nier:automata)`; do not guess the alias. |
| `ganyu_(genshin_impact)` | 19 | 2 | 10 | 0 | Review base only first; cosplay is not canonical automatically. |
| `hatsune_miku` | 296 | 47 | 117 | 0 | Triage variants aggressively before any seed. |
| `hakurei_reimu` | 53 | 6 | 28 | 0 | Review base, PC-98, and named variants separately. |
| `yor_briar` | 10 | 2 | 8 | 0 | Review base first; cosplay remains pending. |
| **Total** | **378** | — | **163** | **0** | **No automatic publication.** |

The derived SQLite output passed `PRAGMA integrity_check = ok`.

## Important interpretation notes

- `2b_(nier_automata)` was deliberately not matched to the source title
  `2b_(nier:automata)`. The internal underscore is not a SQL wildcard anymore,
  and a punctuation/name mismatch requires explicit canonical mapping or a
  captured reference source before review.
- `hatsune_miku` has many observed wiki titles. A title is not automatically a
  publishable outfit: some are software versions, collaborations, cosplay,
  product variants, or other contextual pages.
- Empty-facet observations are retained only as auditable observations; the
  builder does not create candidates for them.
- All generated candidates have status `pending`. Nothing in this report is a
  canonical MCP fact.

## Review order

1. Review base profiles for Ganyu, Reimu, Miku, and Yor.
2. Reject or defer cosplay/product/context pages unless there is a clear reason
   to model them as a visual profile.
3. Resolve Reimu's conflicting color claims with source excerpts rather than
   popularity counts.
4. For Miku, select only a small set of well-defined visual variants; do not
   create dozens of profiles from every wiki title.
5. Resolve the 2B naming mismatch with an explicit alias/canonical source before
   adding any features.
6. Write one reviewed seed per character; promote only after the evidence
   checklist in `docs/CHARACTER_APPEARANCE_PROFILES.md` passes.

## Metrics recorded

- source observations: `378`;
- pending visual candidates: `163`;
- candidates with missing facet: `0`;
- candidate-only statistical publication: `0`;
- canonical promotions from this batch: `0`;
- derived database integrity: `ok`.
