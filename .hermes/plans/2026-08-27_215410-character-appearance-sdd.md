# Character Appearance and Outfit Cards — SDD

> **For Hermes:** Implement this specification incrementally. Do not publish or commit generated databases. Preserve the current tag/profile API and add the appearance contract additively.

**Goal:** Add an auditable, offline-capable appearance layer that describes a character's base visual identity and each outfit/variant using canonical tags, source priority, and evidence.

**Architecture:** Keep canonical, reviewed appearance facts in `tag_library.db` beside the owned character schema. Keep post-tag observations and unreviewed candidates in the optional derived `data/character_appearance.sqlite`. Keep raw source responses under `raw/appearance/`. Render a card as an MCP response projection; do not store HTML or a pre-rendered card.

**Tech Stack:** Python 3.11, stdlib `sqlite3`, JSON/JSONL, FastMCP stdio, Danbooru/Gelbooru wiki and bounded post samples. No new runtime dependencies.

---

## 1. Source policy

Source authority is per evidence type, not merely per website:

| Tier | Evidence | Meaning |
|---:|---|---|
| 1 | Danbooru/Gelbooru wiki statements and official/reference posts | Primary canonical evidence |
| 2 | Danbooru/Gelbooru tags on bounded post samples | Strong discovery/confirmation signal |
| 3 | e621 or other supplemental source | Additional coverage |
| 9 | LLM-generated text | Draft/classification only; never canonical by itself |

The derived `combined` rows are aggregates and must not be counted as an independent source.

Every published feature must retain at least one source reference. Facts appearing in both primary wikis or in a primary wiki plus an official/reference post may be `high` confidence. Frequency-only facts remain `medium` or `low` until reviewed.

---

## 2. Canonical schema in `tag_library.db`

Add these tables through the owned schema initializer. Existing tables and fields remain compatible.

### `character_appearance_profiles`

One row per character appearance, where the default look is also an appearance profile.

Required fields:

```text
appearance_key TEXT PRIMARY KEY
character_tag TEXT NOT NULL
variant_tag TEXT NOT NULL
display_name TEXT NOT NULL
appearance_kind TEXT NOT NULL       -- default, costume, seasonal, collab, animalization
is_default INTEGER NOT NULL DEFAULT 0
status TEXT NOT NULL DEFAULT 'candidate' -- candidate, reviewed, published, retired
confidence TEXT NOT NULL DEFAULT 'medium'
provenance TEXT NOT NULL
notes TEXT NOT NULL DEFAULT ''
UNIQUE(character_tag, variant_tag)
```

Published profiles require a canonical character tag. A character not yet promoted to the owned profile schema remains a candidate and is not presented as canonical.

### `character_appearance_features`

One row per canonical appearance fact.

```text
feature_id INTEGER PRIMARY KEY
appearance_key TEXT NOT NULL
facet TEXT NOT NULL
value TEXT NOT NULL
canonical_tag TEXT NOT NULL
role TEXT NOT NULL DEFAULT 'present' -- present, optional, alternative, uncertain, excluded
status TEXT NOT NULL DEFAULT 'published'
confidence TEXT NOT NULL DEFAULT 'medium'
display_order INTEGER NOT NULL DEFAULT 0
UNIQUE(appearance_key, facet, canonical_tag)
```

Canonical facets include `hair`, `eyes`, `face`, `species`, `ears`, `horns`, `tail`, `markings`, `headwear`, `hair_accessory`, `neck`, `upper_body`, `dress`, `jacket`, `sleeves`, `lower_body`, `gloves`, `legwear`, `footwear`, `jewelry`, `accessories`, and `props`.

### `character_appearance_sources`

A normalized source/citation catalog.

```text
source_id INTEGER PRIMARY KEY
source_site TEXT NOT NULL
source_kind TEXT NOT NULL          -- wiki, reference_post, post_sample, manual
source_key TEXT NOT NULL
source_url TEXT NOT NULL DEFAULT ''
source_tier INTEGER NOT NULL
title TEXT NOT NULL DEFAULT ''
excerpt TEXT NOT NULL DEFAULT ''
captured_at TEXT NOT NULL DEFAULT ''
source_sha256 TEXT NOT NULL DEFAULT ''
UNIQUE(source_site, source_kind, source_key)
```

### `character_appearance_feature_sources`

Many-to-many evidence links, including support and conflicts.

```text
feature_id INTEGER NOT NULL
source_id INTEGER NOT NULL
polarity TEXT NOT NULL DEFAULT 'supports' -- supports, contradicts
observed_tag TEXT NOT NULL DEFAULT ''
support_count INTEGER
sample_size INTEGER
evidence_text TEXT NOT NULL DEFAULT ''
confidence TEXT NOT NULL DEFAULT 'medium'
PRIMARY KEY(feature_id, source_id)
```

### `appearance_schema_metadata`

Stores schema and migration metadata independently from the existing trait metadata.

---

## 3. Derived schema in `data/character_appearance.sqlite`

This database is optional, reproducible, validated by metadata, and excluded from Git.

### `appearance_tag_observations`

```text
character_tag TEXT NOT NULL
variant_tag TEXT NOT NULL
source_site TEXT NOT NULL
source_kind TEXT NOT NULL             -- wiki, reference_post, post_sample
observed_tag TEXT NOT NULL
facet_guess TEXT NOT NULL DEFAULT ''
support_count INTEGER NOT NULL
sample_size INTEGER NOT NULL
support_ratio REAL NOT NULL
captured_at TEXT NOT NULL
PRIMARY KEY(character_tag, variant_tag, source_site, observed_tag)
```

### `appearance_candidates`

```text
candidate_id INTEGER PRIMARY KEY
character_tag TEXT NOT NULL
variant_tag TEXT NOT NULL
facet TEXT NOT NULL
canonical_tag TEXT NOT NULL
score REAL NOT NULL
confidence TEXT NOT NULL
status TEXT NOT NULL DEFAULT 'pending'
reason TEXT NOT NULL DEFAULT ''
created_at TEXT NOT NULL
```

The builder must write to a temporary SQLite file and atomically replace the derived output only after a successful build.

### `appearance_index_metadata`

Must record source path, source size, source SHA-256, schema version, observation count, candidate count, and capture/build time. Runtime readers must reject stale or malformed derived data.

---

## 4. Source layout

Raw source material is not opened by the MCP runtime:

```text
raw/appearance/
├── danbooru/
│   ├── wikis/
│   ├── reference_posts/
│   └── post_samples/
├── gelbooru/
│   ├── wikis/
│   └── post_samples/
└── manifests/
```

The source capture format must be JSON or JSONL and retain the original source key, URL, tags, metadata, and capture date.

---

## 5. Required runtime behavior

Add an MCP tool:

```text
get_character_appearance(character, variant=None, include_evidence=True, limit=100)
```

It must:

1. Resolve a canonical character tag using existing exact/normalized/contextual rules.
2. Return `found: false` and a recommendation when no published appearance profile exists.
3. Return one default profile plus all non-retired variants when `variant` is omitted.
4. Return only the requested canonical variant when `variant` is supplied.
5. Group feature rows by facet.
6. Include confidence, provenance, canonical tags, source references, and optional evidence.
7. Never include `candidate` or `retired` facts in the canonical card.
8. Return additive data only; do not remove existing `get_character` keys.

Expected shape:

```json
{
  "found": true,
  "character_tag": "inugami_korone",
  "profiles": [
    {
      "appearance_key": "korone::default",
      "variant_tag": "inugami_korone_(1st_costume)",
      "appearance_kind": "default",
      "is_default": true,
      "features": {
        "hair": [],
        "dress": [],
        "jacket": []
      },
      "sources": [],
      "evidence": []
    }
  ]
}
```

For an existing structured character returned by `get_character`, add an `appearance` field using the same projection. Existing profile fields, including `traits`, `tags`, and `loras`, remain intact.

---

## 6. Migration and builder behavior

### Existing seed migration

Create an idempotent script that:

- creates the canonical appearance tables;
- creates a default appearance profile for each existing `character_profiles` row;
- converts `core_tags` and existing `character_traits` into deduplicated features;
- links each migrated feature to a `legacy_curated_seed` source;
- validates counts before commit;
- never drops existing tables.

### Candidate builder

Create a script that can consume captured Danbooru/Gelbooru wiki/post JSONL and:

- extract linked canonical tags from wiki statements;
- read general tags from bounded post samples;
- exclude meta, artist, copyright, character, and unsafe metadata from clothing/appearance candidates;
- preserve source-specific counts rather than summing across sites;
- classify obvious facets deterministically;
- write observations and candidates to the derived SQLite database;
- leave promotion to a separate explicit operation.

A bounded public Danbooru fetch may be supported for a small sample, but the runtime must never call the network. Gelbooru API credentials must never be embedded; local captures or explicit user-provided inputs are required.

---

## 7. Korone pilot acceptance data

Promote a pilot profile for `inugami_korone` only from evidence captured from Danbooru/Gelbooru:

- Character/base evidence: dog girl, dog ears, dog tail, brown eyes, brown hair, long hair, low twin braids, bone hair ornament, fangs.
- Default/1st costume: red animal collar, white sleeveless short dress, open yellow frilled jacket, red/blue bows, red socks, sneakers, red wristbands.
- At least two separate outfit profiles from the primary wiki pair, such as `street` and `new_year`.
- Keep outfit features scoped to their variant; never merge `street` or `new_year` clothing into the default profile.
- Cite the Danbooru reference post `3466244` for the default outfit where applicable.
- Treat fanart-only conflicts as low-confidence observations, not canonical features.

---

## 8. Verification

Required checks:

```bash
env -u PYTHONPATH .venv/Scripts/python.exe -m unittest tests.test_search -v
env -u PYTHONPATH .venv/Scripts/python.exe -m py_compile \
  weeb_alexandria_mcp/server.py \
  weeb_alexandria_mcp/owned_schema.py \
  scripts/migrate_appearance_profiles.py \
  scripts/build_appearance_candidates.py \
  tests/test_search.py
git diff --check
```

Behavioral checks must prove:

- existing 46 search regressions still pass;
- migration is idempotent;
- default and variant features are isolated;
- evidence links include Danbooru and Gelbooru sources;
- candidate data is not exposed as published data;
- stale derived metadata falls back or is ignored;
- `get_character` remains backward compatible;
- MCP stdio lists the new tool and all previous tools without protocol errors;
- generated SQLite artifacts remain untracked.

No commit or push is part of implementation unless explicitly requested after review.
