# Appearance population — Batch 01

**Status:** candidate generation complete; human review pending
**Date:** 2026-08-28
**Source:** local `tag_library.db` wiki snapshot
**Canonical output:** `data/character_appearance.sqlite` (derived, not published)

## Selection rule

This batch is the top five existing canonical characters ordered by the sum of
independent Danbooru + Gelbooru `post_count` values. `combined` is excluded from
the ranking. Post volume determines processing order and expected utility; it is
not visual evidence and never promotes a feature.

| Order | Character | Independent posts |
|---:|---|---:|
| 1 | `hatsune_miku` | 220,172 |
| 2 | `hakurei_reimu` | 135,508 |
| 3 | `kirisame_marisa` | 113,210 |
| 4 | `artoria_pendragon_(fate)` | 76,468 |
| 5 | `souryuu_asuka_langley` | 40,141 |

Korone remains the golden card and is not part of this new batch.

## Generation result

Command:

```bash
.venv/Scripts/python.exe scripts/build_appearance_candidates.py \\
  --db tag_library.db \\
  --output data/character_appearance.sqlite \\
  --character 'hatsune_miku' \\
  --character 'hakurei_reimu' \\
  --character 'kirisame_marisa' \\
  --character 'artoria_pendragon_(fate)' \\
  --character 'souryuu_asuka_langley'
```

Observed result:

| Character | Observations | Variants observed | Candidates | Empty facets | Decision |
|---|---:|---:|---:|---:|---|
| `hatsune_miku` | 296 | 47 | 117 | 0 | Triage variants aggressively; do not create one profile per wiki page. |
| `hakurei_reimu` | 53 | 6 | 28 | 0 | Review base, PC-98, and named variants separately. |
| `kirisame_marisa` | 59 | 10 | 40 | 0 | Review base and named variants; keep props/outfits scoped. |
| `artoria_pendragon_(fate)` | 24 | 1 | 4 | 0 | Review the base profile first; no variant inferred. |
| `souryuu_asuka_langley` | 12 | 2 | 0 | 0 | Hold: observations exist but no deterministic visual facets passed classification. |
| **Total** | **444** | — | **189** | **0** | **No automatic publication.** |

The derived SQLite output passed `PRAGMA integrity_check = ok`.
All candidates remain `status='pending'` and are not exposed as canonical MCP
facts.

## Review order

1. Review the base profiles for Miku, Reimu, Marisa, Artoria, and Asuka.
2. For Miku, select only a small set of clearly defined visual variants;
   product pages, collaborations, software versions, and cosplay do not become
   profiles automatically.
3. For Reimu and Marisa, record conflicting colors or accessories as source
   conflicts rather than resolving them by popularity.
4. For Artoria, separate Fate identity/context from armor and outfit features.
5. Investigate Asuka's 12 observations and either add an explicit classifier,
   capture stronger evidence, or defer the card; do not publish from zero
   deterministic candidates.
6. Write one reviewed seed per character and promote only after the checklist
   in `docs/CHARACTER_APPEARANCE_PROFILES.md` passes.

## Batch metrics

- characters selected: `5`;
- source observations: `444`;
- pending visual candidates: `189`;
- candidates with missing facet: `0`;
- candidate-only statistical publication: `0`;
- canonical promotions from this batch: `0`;
- derived database integrity: `ok`.
