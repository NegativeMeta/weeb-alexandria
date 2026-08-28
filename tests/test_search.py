import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path

import weeb_alexandria_mcp.server as server_module
from weeb_alexandria_mcp.server import (
    _tag_rows,
    _tag_suggestions,
    _context_tags,
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

    @staticmethod
    def _create_tag_source(path, rows):
        source = sqlite3.connect(path)
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
            CREATE INDEX idx_tags_name ON tags(name);
            """
        )
        source.executemany(
            "INSERT INTO tags VALUES (?, ?, ?, ?, ?, ?)", rows
        )
        source.commit()
        source.close()

    @staticmethod
    def _swap_runtime_paths(taglib, search=None, context=None):
        names = (
            "TAGLIB_DB", "SEARCH_DB", "CONTEXT_DB", "_SOURCE_HASH_CACHE",
            "_SOURCE_TAG_COUNT_CACHE", "_FTS_VALIDATION_CACHE",
            "_CONTEXT_VALIDATION_CACHE", "_SOURCE_STATUS_CACHE",
        )
        previous = {name: getattr(server_module, name, None) for name in names}
        server_module.TAGLIB_DB = str(taglib)
        if search is not None:
            server_module.SEARCH_DB = str(search)
        if context is not None:
            server_module.CONTEXT_DB = str(context)
        for name in names[3:]:
            if hasattr(server_module, name):
                setattr(server_module, name, None)
        return previous

    @staticmethod
    def _restore_runtime_paths(previous):
        for name, value in previous.items():
            if hasattr(server_module, name):
                setattr(server_module, name, value)

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
        from scripts.build_search_index import build

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "source.sqlite"
            search_path = root / "tag_search.sqlite"
            self._create_tag_source(source_path, [
                ("test", "ftsneedle_character", "character", 10, "needle alias", 0),
            ])
            build(source_path, search_path)
            source = sqlite3.connect(source_path)
            source.row_factory = sqlite3.Row
            previous_paths = self._swap_runtime_paths(source_path, search_path)
            try:
                rows = _tag_rows(source, "ftsneedle", "character", 5)
            finally:
                self._restore_runtime_paths(previous_paths)
                source.close()
        self.assertTrue(rows)
        self.assertEqual(rows[0]["name"], "ftsneedle_character")
        self.assertEqual(rows[0]["match_type"], "prefix")

    def test_stale_fts_index_falls_back_to_current_source(self):
        from scripts.build_search_index import build

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "source.sqlite"
            search_path = root / "tag_search.sqlite"
            self._create_tag_source(source_path, [
                ("test", "old_tag", "general", 10, "", 0),
            ])
            build(source_path, search_path)
            source = sqlite3.connect(source_path)
            source.execute("DELETE FROM tags")
            source.execute(
                "INSERT INTO tags VALUES (?, ?, ?, ?, ?, ?)",
                ("test", "new_tag", "general", 10, "", 0),
            )
            source.commit()
            source.row_factory = sqlite3.Row
            previous_paths = self._swap_runtime_paths(source_path, search_path)
            try:
                stale_rows = _tag_rows(source, "old_tag", "tag", 5)
                current_rows = _tag_rows(source, "new_tag", "tag", 5)
            finally:
                self._restore_runtime_paths(previous_paths)
                source.close()
        self.assertFalse(stale_rows)
        self.assertTrue(current_rows)
        self.assertEqual(current_rows[0]["name"], "new_tag")

    def test_partial_fts_index_falls_back_to_source_rows(self):
        from scripts.build_search_index import build

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "source.sqlite"
            search_path = root / "tag_search.sqlite"
            self._create_tag_source(source_path, [
                ("test", "first_tag", "general", 10, "", 0),
                ("test", "second_tag", "general", 9, "", 0),
            ])
            build(source_path, search_path)
            search = sqlite3.connect(search_path)
            search.execute("DELETE FROM tag_search WHERE name = 'second_tag'")
            search.commit()
            search.close()
            source = sqlite3.connect(source_path)
            source.row_factory = sqlite3.Row
            previous_paths = self._swap_runtime_paths(source_path, search_path)
            try:
                rows = _tag_rows(source, "cond_tag", "tag", 5)
            finally:
                self._restore_runtime_paths(previous_paths)
                source.close()
        self.assertTrue(rows)
        self.assertEqual(rows[0]["name"], "second_tag")

    def test_unopenable_fts_path_falls_back_to_sqlite(self):
        with tempfile.TemporaryDirectory() as tmp:
            search_path = Path(tmp) / "tag_search.sqlite"
            search_path.mkdir()
            previous = server_module.SEARCH_DB
            try:
                server_module.SEARCH_DB = str(search_path)
                rows = _tag_rows(self.con, "closed mouth", "tag", 5)
            finally:
                server_module.SEARCH_DB = previous
        self.assertTrue(rows)
        self.assertEqual(rows[0]["name"], "closed_mouth")

    def test_unicode_alias_is_searchable_with_fts(self):
        from scripts.build_search_index import build

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "source.sqlite"
            search_path = root / "tag_search.sqlite"
            self._create_tag_source(source_path, [
                ("test", "cat_tag", "general", 10, "猫咪", 0),
            ])
            build(source_path, search_path)
            source = sqlite3.connect(source_path)
            source.row_factory = sqlite3.Row
            previous_paths = self._swap_runtime_paths(source_path, search_path)
            try:
                rows = _tag_rows(source, "猫咪", "tag", 5)
            finally:
                self._restore_runtime_paths(previous_paths)
                source.close()
        self.assertTrue(rows)
        self.assertEqual(rows[0]["name"], "cat_tag")

    def test_fts_duplicate_uses_highest_count_representative(self):
        from scripts.build_search_index import build

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "source.sqlite"
            search_path = root / "tag_search.sqlite"
            self._create_tag_source(source_path, [
                ("general-site", "deep_throat", "general", 28213, "", 0),
                ("alias-site", "deep_throat", "alias", 7838, "old alias", 0),
            ])
            build(source_path, search_path)
            source = sqlite3.connect(source_path)
            source.row_factory = sqlite3.Row
            previous_paths = self._swap_runtime_paths(source_path, search_path)
            try:
                rows = _tag_rows(source, "thro", "tag", 5)
            finally:
                self._restore_runtime_paths(previous_paths)
                source.close()
        candidate = next(row for row in rows if row["name"] == "deep_throat")
        self.assertEqual(candidate["category"], "general")
        self.assertEqual(candidate["post_count"], 28213)
        self.assertEqual(set(candidate["sites"]), {"general-site", "alias-site"})

    def test_context_index_with_stale_source_hash_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "source.sqlite"
            context_path = root / "character_context.sqlite"
            self._create_tag_source(source_path, [
                ("test", "old_character", "character", 10, "", 0),
            ])
            source_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
            context = sqlite3.connect(context_path)
            context.executescript(
                """
                CREATE TABLE character_context(tag TEXT, context TEXT, source TEXT);
                CREATE TABLE character_work_context(
                    tag TEXT, work_tag TEXT, matched_terms TEXT, score INTEGER, source TEXT
                );
                CREATE TABLE context_index_metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                """
            )
            context.execute(
                "INSERT INTO character_context VALUES (?, ?, ?)",
                ("old_character", "old_work", "test"),
            )
            context.executemany(
                "INSERT INTO context_index_metadata VALUES (?, ?)",
                [("schema_version", "3"), ("source_db", str(source_path.resolve())),
                 ("source_size", str(source_path.stat().st_size)),
                 ("source_sha256", source_hash), ("source_wal_size", "-1"),
                 ("source_wal_mtime_ns", "-1"), ("character_wiki_rows", "1"),
                 ("context_rows", "1"), ("work_rows", "0")],
            )
            context.commit()
            context.close()
            source = sqlite3.connect(source_path)
            source.execute("UPDATE tags SET name='new_character'")
            source.commit()
            previous_paths = self._swap_runtime_paths(source_path, None, context_path)
            try:
                names = _context_tags(["old_work"])
            finally:
                self._restore_runtime_paths(previous_paths)
                source.close()
        self.assertEqual(names, set())

    def test_search_index_builder_preserves_existing_output_on_failure(self):
        from scripts.build_search_index import build

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "invalid.sqlite"
            output_path = root / "tag_search.sqlite"
            sqlite3.connect(source_path).close()
            output_path.write_bytes(b"previous-index")
            with self.assertRaises(sqlite3.OperationalError):
                build(source_path, output_path)
            self.assertEqual(output_path.read_bytes(), b"previous-index")

    def test_context_index_builder_preserves_existing_output_on_failure(self):
        from scripts.build_context_index import build

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "invalid.sqlite"
            output_path = root / "character_context.sqlite"
            sqlite3.connect(source_path).close()
            output_path.write_bytes(b"previous-index")
            with self.assertRaises(sqlite3.OperationalError):
                build(source_path, output_path)
            self.assertEqual(output_path.read_bytes(), b"previous-index")
            with self.assertRaises(ValueError):
                build(source_path, source_path)
            self.assertTrue(source_path.exists())


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
