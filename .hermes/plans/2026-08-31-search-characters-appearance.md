# Search characters: modern appearance profiles

## Goal
Make `search_characters(q=...)` discover canonical characters present only in `character_appearance_profiles`, while preserving the legacy trait-filter contract.

## Contract
- Query matching uses normalized tag/display-name forms.
- Legacy `character_profiles` rows retain precedence and response shape.
- Published/reviewed modern appearance profiles are additive fallback rows, deduplicated by `character_tag`.
- Modern rows expose `slug`, `name`, `character`, `count`, `traits`, and compatibility fields.
- Existing semantic trait filters remain backed by `character_profiles`/`character_traits`; no count changes for those filters.
- Empty query behavior remains unchanged in this patch.

## Scope
- `weeb_alexandria_mcp/server.py`
- `tests/test_search.py`

## Acceptance tests
- `search_characters(q="inugami_korone")` returns Korone.
- `search_characters(q="Inugami Korone")` returns Korone.
- Existing `hair_color="white"` regression remains unchanged.
- No duplicate slug when a character exists in both tables.
- Full unittest suite and MCP stdio probe pass.

## Verification
`.venv/Scripts/python.exe -m unittest discover -s tests -q`
