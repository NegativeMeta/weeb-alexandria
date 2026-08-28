import sqlite3
import tempfile
import unittest
from pathlib import Path

import weeb_alexandria_mcp.server as server_module
from weeb_alexandria_mcp.server import (
    _tag_rows,
    _tag_suggestions,
    get_character,
    get_sources_status,
    get_tag_knowledge,
    search_characters,
    search_knowledge,
)

DB = Path(__file__).parents[1] / "tag_library.db"


class SearchRegressionTests(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(DB)
        self.con.row_factory = sqlite3.Row

    def tearDown(self):
        self.con.close()

    def test_owned_trait_tables_are_present(self):
        names = {
            row[0] for row in self.con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        self.assertTrue({"character_profiles", "trait_definitions", "character_traits"} <= names)

    def test_get_character_reads_owned_profile_and_traits(self):
        result = get_character("hatsune_miku")
        self.assertTrue(result["found"])
        self.assertEqual(result["slug"], "hatsune_miku")
        self.assertEqual(result["profile_provenance"], "legacy_curated_seed")
        self.assertIn("aqua hair", {item["value"] for item in result["traits"]})
        self.assertTrue(all(item["evidence_tag"] for item in result["traits"]))
        self.assertTrue(all(item["confidence"] == "high" for item in result["traits"]))
        self.assertIn("twintails", result["tags"])

    def test_search_characters_uses_owned_trait_filters(self):
        result = search_characters(hair_color="white")
        self.assertEqual(result["total"], 4)
        self.assertIn("frieren", {item["slug"] for item in result["results"]})

    def test_search_knowledge_exposes_owned_entities_namespace(self):
        result = search_knowledge("hatsune miku", category="character", limit=5)
        self.assertIn("entities", result)
        self.assertNotIn("animadex", result)
        self.assertTrue(result["entities"]["characters"])

    def test_sources_status_reports_owned_schema(self):
        result = get_sources_status()
        self.assertEqual(result["structured_mode"], "owned_local_tables")
        self.assertNotIn("animadex_mode", result)
        self.assertIn("character_profiles", result["counts"])
        self.assertIn("trait_system_metadata", result["counts"])

    def test_sources_status_uses_memory_cache_until_database_changes(self):
        previous = getattr(server_module, "_SOURCE_STATUS_CACHE", None)
        try:
            server_module._SOURCE_STATUS_CACHE = None
            first = get_sources_status()
            second = get_sources_status()
            self.assertFalse(first["cached"])
            self.assertTrue(second["cached"])
            self.assertEqual(first["counts"], second["counts"])
        finally:
            server_module._SOURCE_STATUS_CACHE = previous

    def test_legacy_structured_tables_are_removed_after_migration(self):
        names = {
            row[0] for row in self.con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        self.assertFalse(any(name.startswith("animadex_") for name in names))

    def test_tag_category_alias_returns_general_tags(self):
        rows = _tag_rows(self.con, "closed mouth", "tag", 25)
        self.assertTrue(any(row["name"] == "closed_mouth" for row in rows))

    def test_tag_rows_uses_optional_fts_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            search_path = Path(tmp) / "tag_search.sqlite"
            search = sqlite3.connect(search_path)
            search.execute(
                "CREATE VIRTUAL TABLE tag_search USING fts5("
                "site UNINDEXED, name, category_name UNINDEXED, "
                "post_count UNINDEXED, aliases, nsfw UNINDEXED)"
            )
            search.execute(
                "INSERT INTO tag_search(site, name, category_name, post_count, aliases, nsfw) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("test", "ftsneedle_character", "character", 10, "needle alias", 0),
            )
            search.commit()
            previous = getattr(server_module, "SEARCH_DB", None)
            try:
                server_module.SEARCH_DB = str(search_path)
                rows = _tag_rows(self.con, "ftsneedle", "character", 5)
            finally:
                server_module.SEARCH_DB = previous
                search.close()
        self.assertTrue(rows)
        self.assertEqual(rows[0]["name"], "ftsneedle_character")
        self.assertEqual(rows[0]["match_type"], "prefix")

    def test_tag_rows_deduplicates_sites_when_prefix_and_fts_overlap(self):
        rows = _tag_rows(self.con, "hatsune miku", "character", 5)
        self.assertTrue(rows)
        self.assertTrue(all(
            len(row["sites"]) == len(set(row["sites"])) for row in rows
        ))

    def test_search_index_builder_copies_rows_and_records_source_hash(self):
        from scripts.build_search_index import build

        with tempfile.TemporaryDirectory() as tmp:
            source_path = Path(tmp) / "source.sqlite"
            output_path = Path(tmp) / "tag_search.sqlite"
            source = sqlite3.connect(source_path)
            source.executescript(
                """
                CREATE TABLE tags (
                    site TEXT NOT NULL,
                    name TEXT NOT NULL,
                    category_name TEXT NOT NULL,
                    post_count INTEGER,
                    aliases TEXT,
                    nsfw INTEGER
                );
                INSERT INTO tags VALUES
                    ('test', 'ftsneedle_character', 'character', 10, 'needle alias', 0),
                    ('test', 'other_tag', 'general', 2, '', 0);
                """
            )
            source.commit()
            source.close()
            source_size = str(source_path.stat().st_size)
            build(source_path, output_path)
            search = sqlite3.connect(output_path)
            try:
                rows = search.execute(
                    "SELECT name FROM tag_search WHERE tag_search MATCH ?",
                    ("ftsneedle*",),
                ).fetchall()
                metadata = dict(search.execute(
                    "SELECT key, value FROM tag_search_metadata"
                ).fetchall())
            finally:
                search.close()
        self.assertEqual(rows, [("ftsneedle_character",)])
        self.assertEqual(metadata["source_size"], source_size)
        self.assertTrue(metadata["source_sha256"])

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

    def test_search_knowledge_exposes_contextual_character(self):
        result = search_knowledge("Rika Higurashi", category="character", limit=10)
        suggestions = result["tag_library"].get("suggestions", [])
        candidate = next(item for item in suggestions if item["name"] == "furude_rika")
        self.assertEqual(candidate["match_type"], "contextual")
        self.assertEqual(candidate["confidence"], "high")

    def test_get_tag_knowledge_resolves_unique_contextual_character(self):
        result = get_tag_knowledge("Rika Higurashi")
        self.assertTrue(result["found"])
        self.assertEqual(result["tag"], "furude_rika")
        self.assertEqual(result["resolution"]["type"], "contextual_character")
        self.assertEqual(
            result["resolution"]["matched_work"],
            "higurashi_no_naku_koro_ni",
        )

    def test_short_ambiguous_name_reports_candidates_without_selection(self):
        result = get_character("Sakura")
        self.assertTrue(result["ambiguous"])
        self.assertIsNone(result["recommended_tag"])
        self.assertGreaterEqual(len(result["recommendations"]), 2)

    def test_short_character_name_without_context_is_ambiguous(self):
        result = get_character("Rem")
        self.assertTrue(result["ambiguous"])
        self.assertIsNone(result["recommended_tag"])
        self.assertGreaterEqual(len(result["recommendations"]), 2)

    def test_short_general_name_is_ambiguous_even_with_exact_tag(self):
        result = get_character("Cream")
        self.assertTrue(result["ambiguous"])
        self.assertIsNone(result["recommended_tag"])
        self.assertGreaterEqual(len(result["recommendations"]), 2)

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

    def test_contextual_recommendation_exposes_matched_work(self):
        result = get_character("Rika Higurashi")
        self.assertEqual(
            result["recommendation"]["matched_work"],
            "higurashi_no_naku_koro_ni",
        )

    def test_context_index_records_canonical_work_relation(self):
        index = Path(__file__).parents[1] / "data" / "character_context.sqlite"
        con = sqlite3.connect(index)
        try:
            relation = con.execute(
                "SELECT work_tag FROM character_work_context "
                "WHERE tag='furude_rika' AND work_tag='higurashi_no_naku_koro_ni'"
            ).fetchone()
            self.assertIsNotNone(relation)
            metadata = con.execute(
                "SELECT value FROM context_index_metadata WHERE key='source_db'"
            ).fetchone()
            self.assertIsNotNone(metadata)
        finally:
            con.close()

    def test_context_index_has_covering_lookup_indexes(self):
        index = Path(__file__).parents[1] / "data" / "character_context.sqlite"
        con = sqlite3.connect(index)
        try:
            context_indexes = {
                row[1] for row in con.execute(
                    "PRAGMA index_list('character_context')"
                )
            }
            work_indexes = {
                row[1] for row in con.execute(
                    "PRAGMA index_list('character_work_context')"
                )
            }
        finally:
            con.close()
        self.assertIn("idx_character_context_context_tag", context_indexes)
        self.assertIn("idx_character_work_context_tag_cover", work_indexes)

    def test_unknown_structured_character_can_fall_back_to_tag(self):
        result = get_character("wave_the_swallow")
        self.assertFalse(result["found"])
        self.assertTrue(result["tag_match"])
        self.assertEqual(result["tag"]["name"], "wave_the_swallow")


if __name__ == "__main__":
    unittest.main()
