# Hololive appearance population queue

**Date:** 2026-08-28
**Priority:** Hololive talents before the general post-volume queue
**Status:** five base profiles promoted; outfit review deferred

## Scope

The working scope is female Hololive talents across JP, EN, ID, and DEV_IS,
including graduated talents when the local character tables identify them as
Hololive talents. Holostars, staff, mascots, fan characters, groups, and
outfit-only tags are excluded from the talent queue. Outfit and named costume
profiles remain separate and require independent review.

## First review batch

The first five canonical base tags were selected by independent post volume
(Danbooru + Gelbooru; `combined` excluded):

| Rank | Character | Danbooru | Gelbooru | Independent total |
|---:|---|---:|---:|---:|
| 1 | `houshou_marine` | 13,829 | 17,839 | 31,668 |
| 2 | `shirakami_fubuki` | 11,305 | 15,101 | 26,406 |
| 3 | `hoshimachi_suisei` | 11,168 | 14,525 | 25,693 |
| 4 | `usada_pekora` | 8,865 | 11,267 | 20,132 |
| 5 | `nekomata_okayu` | 8,035 | 11,460 | 19,495 |

## Candidate generation

```text
characters: 5
observations: 2,252
candidates: 920
```

Five base profiles were promoted after source review:

| Character | Profile | Features | Conflicts |
|---|---|---:|---:|
| `houshou_marine` | base | 10 | 0 |
| `shirakami_fubuki` | base | 14 | 1 |
| `hoshimachi_suisei` | base | 8 | 0 |
| `usada_pekora` | base | 15 | 1 |
| `nekomata_okayu` | base | 12 | 0 |

## Review warnings

The generated candidates include generic group/uniform tags such as
`hololive_idol_uniform_(bright)`, `holohoneygaoka_high_school_uniform`, and
`hololive_dance_practice_uniform`. These are not automatically canonical base
features for every talent. They must be retained as review observations and
accepted only when the source explicitly scopes them to a named outfit/profile.

The same applies to school uniforms, casual outfits, stage costumes, memes,
fan marks, mascots, and tags originating from multi-character posts. Frequency
alone is not evidence.

## Next steps

1. Review the five source sets character by character.
2. Separate base appearance from named outfits and group uniforms.
3. Record conflicts instead of resolving them by frequency.
4. Create one reviewed seed per accepted character.
5. Promote only reviewed seeds.
6. Rebuild all derived indexes and run the full test/MCP validation once this
   batch is complete.
