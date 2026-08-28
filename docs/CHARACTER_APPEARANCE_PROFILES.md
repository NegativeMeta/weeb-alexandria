# Character appearance profiles

This document defines the contract for Weeb Alexandria's character appearance
cards and the operating procedure for adding new characters. It is the source
of truth for future batches.

## 1. What a profile represents

A profile is one coherent, reviewable visual presentation of one canonical
character:

```text
character identity
  -> appearance profile (base or one outfit/variant)
    -> visual feature
      -> canonical tag
        -> source evidence
```

A profile is **not** a generated prose description and is not a bag of the most
frequent tags found in fanart. It is a scoped projection of structured rows,
with provenance preserved at feature level.

Every outfit or contextual variant gets its own profile. Clothing, hair, body
features, accessories, and colors from one variant must never be copied into
the base profile or another variant merely because the character is the same.

## 2. Required profile contract

Each row in `character_appearance_profiles` must satisfy all of the following:

| Field | Requirement |
|---|---|
| `appearance_key` | Stable unique key: `<character_tag>::default` for the base profile, or `<character_tag>::<variant_tag>` for a variant. |
| `character_tag` | Canonical character tag, normalized and owned by this project. |
| `variant_tag` | The exact scoped variant tag. For the base profile it equals `character_tag`; it must start with `<character_tag>_(` for a variant. |
| `display_name` | Human-readable name that does not change identity or scope. |
| `status` | `candidate`, `reviewed`, or `published`. Only `reviewed`/`published` rows are exposed by the MCP. |
| identity fields | The profile must resolve to one character; aliases and redirects are resolved before inserting canonical rows. |
| provenance | The profile must be backed by one or more catalogued sources when promoted. |

Profile identity invariants:

- `appearance_key`, `character_tag`, and `variant_tag` must agree.
- A variant must belong to its requested character; a global `variant_tag`
  lookup is invalid.
- A seed cannot silently create a new character or reinterpret another
  character's variant.
- `candidate` rows belong only in the derived candidate database, never in the
  canonical MCP projection.

## 3. Required feature contract

Each row in `character_appearance_features` describes one visual fact inside
exactly one profile:

| Field | Requirement |
|---|---|
| `appearance_key` | Must reference the profile being described. |
| `facet` | Controlled visual facet such as `hair`, `eyes`, `face`, `clothing`, `dress`, `skirt`, `footwear`, `accessory`, or `body`. |
| `canonical_tag` | One normalized tag that describes the feature. Preserve legitimate multi-word tags. |
| `polarity` | `supports` for confirmed presence; `contradicts` only when a source explicitly conflicts. |
| `status` | `reviewed` or `published` for canonical data; candidates remain `pending` in the derived DB. |
| `confidence` | Evidence-based confidence, not frequency alone. |
| evidence link | At least one row in `character_appearance_feature_sources`. |

Feature rules:

- One feature belongs to one `appearance_key`; never attach it to the
  character globally.
- A frequent post tag is a candidate, not a canonical fact.
- Do not publish pose, expression, camera, background, scenery, artist,
  copyright, rating, metadata, or generation-control tags as appearance
  features.
- Do not infer a permanent body or clothing attribute from one exceptional
  fanart post without explicit review.
- Keep contradictory source claims visible as conflicts; do not hide them by
  selecting whichever count is larger.
- Prefer exact canonical tags and preserve tags such as `red face` or
  `closed mouth` when they are legitimate multi-word tags.
- Do not use a monolithic LLM-written description as primary evidence.

## 4. Required source and evidence contract

Every source in `character_appearance_sources` must retain:

- `source_site`: for example `danbooru`, `gelbooru`, or another explicitly
  named source;
- `source_kind`: `wiki`, `reference_post`, `official`, `seed`, or
  `post_sample`;
- `source_key`: stable source-local identifier;
- `source_url` when available;
- `source_tier` and capture date;
- enough title/excerpt or capture metadata to audit the claim later.

Every published feature must link to one or more sources through
`character_appearance_feature_sources`. Keep site-specific evidence separate:
`combined` is a derived aggregation, not a source. Preserve source identity,
counts, sample size, and conflicts independently.

## 5. Candidate-to-publication workflow

```text
captured wiki/posts
    ↓
build_appearance_candidates.py
    ↓
data/character_appearance.sqlite (observations + pending candidates)
    ↓
human review of each profile and feature
    ↓
seeds/appearance/<character>.json
    ↓
promote_appearance.py
    ↓
tag_library.db (reviewed/published canonical rows)
    ↓
appearance_runtime.py → get_character_appearance()
```

### Step 1 — Select a small batch

Start with five characters that deliberately exercise different risks:
straightforward appearance, complex outfit, accessories/body markers, multiple
variants, and contradictory or sparse evidence. Do not start with a mass import.

### Step 2 — Build candidates

Use only captured local sources and repeatable commands:

```bash
.venv/Scripts/python.exe scripts/build_appearance_candidates.py \\
  --db tag_library.db \\
  --output data/character_appearance.sqlite \\
  --character <canonical_tag> \\
  --character <canonical_tag>
```

Add a captured JSON/JSONL post file only when its source and character/variant
scope are explicit. A post containing multiple possible variants must declare
`variant_tag`; the builder must reject ambiguous input instead of guessing.

### Step 3 — Review candidates

For each character, review the base profile first, then each meaningful outfit.
For every proposed feature record:

1. canonical tag and facet;
2. exact profile scope;
3. source site/kind/key;
4. source excerpt or post evidence;
5. confidence and conflicts;
6. decision: accept, reject, or defer.

Reject candidates that are only statistical, non-visual, cross-character,
variant-ambiguous, or unsupported by evidence.

### Step 4 — Write one seed per character

Seeds are the review boundary. A seed must contain the canonical character,
explicit profiles, source catalog, and feature-to-source links. Keep the base
profile and each outfit separate. Never hand-edit `tag_library.db` to publish a
candidate.

### Step 5 — Promote and verify

Promote only a reviewed seed:

```bash
.venv/Scripts/python.exe scripts/promote_appearance.py \\
  --db tag_library.db \\
  --input seeds/appearance/<character>.json
```

Promotion must be idempotent. After promotion, verify:

- no published feature lacks evidence;
- no duplicate active `(appearance_key, canonical_tag)` exists;
- all variant keys remain scoped to the requested character;
- a second promotion does not change counts;
- the MCP returns only reviewed/published rows;
- aliases and redirects resolve to the canonical character profile.

## 6. Definition of done for one character

A character is complete only when all applicable checks pass:

- canonical identity, aliases, and franchise context resolved;
- base appearance exists and is intentionally scoped;
- important outfits/variants are separate profiles or explicitly marked absent;
- every published feature has at least one auditable source link;
- source conflicts are recorded rather than silently merged;
- non-visual and fanart-context tags are excluded;
- no cross-character or cross-variant contamination is reproducible;
- seed promotion is repeatable and MCP output is verified;
- unresolved or sparse evidence is documented instead of filled with guesses.

A short, reliable card is better than an exhaustive contaminated card.

## 7. First population batch

Korone remains the golden card and regression reference. The first new batch is:

| Character | Why it is included | Main review risk |
|---|---|---|
| `2b_(nier_automata)` | Complex recognizable design | Outfit/accessory boundaries and sparse exact wiki evidence |
| `ganyu_(genshin_impact)` | Distinctive horns, hair, flower, and costume | Separate identity traits from outfit-specific features |
| `hatsune_miku` | Iconic hair and many fanart costumes | Variant contamination and over-broad hair/clothing tags |
| `hakurei_reimu` | Strong visual identity with conflicting legacy color tags | Contradictory evidence and canonical feature selection |
| `yor_briar` | Clear base outfit and accessories | Distinguishing canonical clothing from pose/weapon context |

The first batch is a **candidate and review batch**, not an automatic publication
batch. Its initial output should be measured by evidence quality, rejected
candidate rate, conflicts, and review time—not by the number of rows created.

## 8. Batch metrics

Record these metrics for every batch:

- characters selected and candidates generated;
- profiles reviewed, accepted, rejected, and deferred;
- percentage of published features with evidence;
- percentage of candidates supported only by frequency;
- source conflicts per character;
- cross-variant contamination findings;
- ambiguous aliases or unresolved identities;
- review time per character;
- counts before/after repeated migration or promotion.

Do not call a batch complete based only on row counts.
