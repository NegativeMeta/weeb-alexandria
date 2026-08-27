import sqlite3
import unittest
from pathlib import Path

from weeb_alexandria_mcp.server import (
    _tag_rows,
    _tag_suggestions,
    get_character,
    get_tag_knowledge,
)

DB = Path(__file__).parents[1] / "tag_library.db"


class SearchRegressionTests(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(DB)
        self.con.row_factory = sqlite3.Row

    def tearDown(self):
        self.con.close()

    def test_tag_category_alias_returns_general_tags(self):
        rows = _tag_rows(self.con, "closed mouth", "tag", 25)
        self.assertTrue(any(row["name"] == "closed_mouth" for row in rows))

    def test_close_typo_returns_recommendations(self):
        suggestions = _tag_suggestions(self.con, "swalow", "tag", 25)
        self.assertTrue(any(row["name"] == "swallowing" for row in suggestions))

    def test_get_tag_normalizes_human_spacing(self):
        result = get_tag_knowledge("closed mouth")
        self.assertTrue(result["found"])
        self.assertTrue(any(row["name"] == "closed_mouth" for row in result["tags"]))

    def test_active_alias_is_recommended(self):
        suggestions = _tag_suggestions(self.con, "fingers_in_mouth", "tag", 5)
        self.assertTrue(any(row["name"] == "finger_in_own_mouth" and row["match_type"] == "alias"
                            for row in suggestions))

    def test_character_name_variant_recommends_canonical_tag(self):
        result = get_character("satoko hojo")
        self.assertFalse(result["found"])
        self.assertEqual(result["recommended_tag"], "houjou_satoko")
        self.assertEqual(result["recommendation"]["category"], "character")

    def test_wiki_redirect_resolves_to_canonical_tag(self):
        result = get_tag_knowledge("sakura_haruno")
        self.assertTrue(result["found"])
        self.assertEqual(result["requested_tag"], "sakura_haruno")
        self.assertEqual(result["tag"], "haruno_sakura")
        self.assertEqual(result["resolution"]["type"], "wiki_redirect")
        self.assertEqual(result["tags"][0]["name"], "haruno_sakura")

    def test_character_recommendation_is_canonicalized(self):
        result = get_character("Sakura Naruto")
        self.assertEqual(result["recommended_tag"], "haruno_sakura")
        self.assertEqual(result["recommendation"]["name"], "haruno_sakura")

    def test_character_variant_recommends_base_tag(self):
        result = get_character("okayu hololive")
        self.assertEqual(result["recommended_tag"], "nekomata_okayu")
        self.assertEqual(result["recommendation"]["category"], "character")

    def test_exact_general_tag_beats_weak_fuzzy_character_matches(self):
        result = get_character("Anya Forger")
        self.assertEqual(result["recommended_tag"], "anya_forger")
        self.assertEqual(result["recommendation"]["confidence"], "high")
        self.assertEqual(result["recommendation"]["match_type"], "normalized")

    def test_weak_multiword_fuzzy_match_is_low_confidence(self):
        suggestions = _tag_suggestions(self.con, "anya forger", "character", 10)
        weak = next(row for row in suggestions if row["name"] == "anya_flormer")
        self.assertEqual(weak["confidence"], "low")

    def test_contextual_variant_with_unique_wiki_is_preserved(self):
        result = get_tag_knowledge("fuu_(samurai_champloo)")
        self.assertEqual(result["tag"], "fuu_(samurai_champloo)")
        self.assertTrue(any(item["body"] for item in result["definitions"]))

    def test_contextual_character_queries_use_aliases_and_work_context(self):
        expected = {
            "marin kitagawa": "kitagawa_marin",
            "rem re zero": "rem_(re:zero)",
            "marine hololive": "houshou_marine",
            "korone hololive": "inugami_korone",
            "ai oshi no ko": "hoshino_ai",
        }
        for query, tag in expected.items():
            with self.subTest(query=query):
                self.assertEqual(get_character(query)["recommended_tag"], tag)

    def test_context_index_resolves_work_name_to_character(self):
        result = get_character("Rika Higurashi")
        self.assertEqual(result["recommended_tag"], "furude_rika")

    def test_unknown_structured_character_can_fall_back_to_tag(self):
        result = get_character("wave_the_swallow")
        self.assertFalse(result["found"])
        self.assertTrue(result["tag_match"])
        self.assertEqual(result["tag"]["name"], "wave_the_swallow")


if __name__ == "__main__":
    unittest.main()
