import json
import sqlite3
import unittest
from pathlib import Path

from scripts.validate_general_appearance_batch import validate_seed


class ValidateGeneralAppearanceBatchTests(unittest.TestCase):
    def test_accepts_new_sources_staged_inside_seed(self):
        canonical = sqlite3.connect(":memory:")
        candidates = sqlite3.connect(":memory:")
        try:
            canonical.execute(
                "CREATE TABLE wiki (site TEXT, title TEXT, body TEXT)"
            )
            canonical.execute(
                "CREATE TABLE character_appearance_sources ("
                "source_site TEXT, source_kind TEXT, source_key TEXT"
                ")"
            )
            candidates.execute(
                "CREATE TABLE appearance_candidates ("
                "character_tag TEXT, variant_tag TEXT, facet TEXT, canonical_tag TEXT"
                ")"
            )
            canonical.execute(
                "INSERT INTO wiki(site, title, body) VALUES (?, ?, ?)",
                ("danbooru", "alice", "Alice has blue eyes."),
            )
            candidates.execute(
                "INSERT INTO appearance_candidates VALUES (?, ?, ?, ?)",
                ("alice", "alice", "eyes", "blue_eyes"),
            )

            seed = {
                "character_tag": "alice",
                "sources": [
                    {
                        "source_site": "danbooru",
                        "source_kind": "wiki",
                        "source_key": "alice",
                        "excerpt": "Alice has blue eyes.",
                    }
                ],
                "profiles": [
                    {
                        "appearance_key": "alice::default",
                        "variant_tag": "alice",
                        "appearance_kind": "default",
                        "features": [
                            {
                                "facet": "eyes",
                                "canonical_tag": "blue_eyes",
                                "source_refs": ["danbooru:wiki:alice"],
                            }
                        ],
                    }
                ],
            }

            errors, metrics = validate_seed(
                Path("staged_seed.json"),
                seed,
                canonical,
                candidates,
                {("alice", "alice", "blue_eyes")},
                set(),
            )

            self.assertEqual(errors, [])
            self.assertEqual(metrics, {"accepted": 1, "candidates": 1})

            unavailable_ref_seed = json.loads(json.dumps(seed))
            unavailable_ref_seed["profiles"][0]["features"][0]["source_refs"] = [
                "gelbooru:wiki:alice"
            ]
            unavailable_errors, _ = validate_seed(
                Path("unavailable_ref_seed.json"),
                unavailable_ref_seed,
                canonical,
                candidates,
                {("alice", "alice", "blue_eyes")},
                set(),
            )
            self.assertEqual(
                unavailable_errors,
                [
                    "unavailable_ref_seed.json: source_ref unavailable "
                    "'gelbooru:wiki:alice'"
                ],
            )
        finally:
            canonical.close()
            candidates.close()


if __name__ == "__main__":
    unittest.main()
