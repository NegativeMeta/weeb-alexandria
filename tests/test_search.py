import hashlib
import json
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
    get_character_appearance,
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

    def test_search_characters_finds_appearance_only_character_by_tag(self):
        result = search_characters(q="inugami_korone")
        self.assertIn("inugami_korone", {item["slug"] for item in result["results"]})
        korone = next(item for item in result["results"] if item["slug"] == "inugami_korone")
        self.assertEqual(korone["profile_provenance"], "appearance_profile")
        self.assertTrue(korone["traits"])

    def test_search_characters_finds_appearance_only_character_by_display_name(self):
        result = search_characters(q="Inugami Korone")
        self.assertIn("inugami_korone", {item["slug"] for item in result["results"]})

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

    def test_multi_tag_query_returns_separate_search_recommendation(self):
        result = search_knowledge("blushing red face", category="tag", limit=10)
        self.assertEqual(result["tag_library"]["query_mode"], "multi_tag")
        parts = result["tag_library"]["query_parts"]
        self.assertEqual([part["query"] for part in parts], ["blushing", "red face"])
        self.assertEqual(parts[0]["results"][0]["name"], "blushing")
        self.assertEqual(parts[1]["results"][0]["name"], "red_face")
        recommendation = result["query_recommendation"]
        self.assertEqual(recommendation["action"], "search_each_tag_separately")
        self.assertEqual(recommendation["queries"], ["blushing", "red face"])

    def test_known_multiword_tag_is_not_split(self):
        result = search_knowledge("red face", category="tag", limit=10)
        self.assertNotIn("query_mode", result["tag_library"])
        self.assertEqual(result["tag_library"]["results"][0]["name"], "red_face")

    def test_contextual_query_is_not_split(self):
        result = search_knowledge("Fuwawa Hololive", category="character", limit=10)
        self.assertNotIn("query_mode", result["tag_library"])
        candidate = result["tag_library"]["suggestions"][0]
        self.assertEqual(candidate["name"], "fuwawa_abyssgard")
        self.assertEqual(candidate["match_type"], "contextual")

    def test_explicit_separator_splits_known_tags(self):
        result = search_knowledge("blushing, red face", category="tag", limit=10)
        self.assertEqual(result["tag_library"]["query_mode"], "multi_tag")
        self.assertEqual(
            [part["query"] for part in result["tag_library"]["query_parts"]],
            ["blushing", "red face"],
        )

    def test_flash_and_red_face_are_split_as_independent_tags(self):
        result = search_knowledge("flash red face", category="tag", limit=10)
        self.assertEqual(result["tag_library"]["query_mode"], "multi_tag")
        self.assertEqual(
            [part["query"] for part in result["tag_library"]["query_parts"]],
            ["flash", "red face"],
        )
        self.assertEqual(
            result["query_recommendation"]["action"],
            "search_each_tag_separately",
        )

    def test_mococo_contextual_query_is_not_split(self):
        result = search_knowledge("Mococo Hololive", category="character", limit=10)
        self.assertNotIn("query_mode", result["tag_library"])
        candidate = result["tag_library"]["suggestions"][0]
        self.assertEqual(candidate["name"], "mococo_abyssgard")
        self.assertEqual(candidate["match_type"], "contextual")

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

    def test_korone_appearance_card_has_base_and_isolated_outfits(self):
        result = get_character_appearance("inugami_korone")
        self.assertTrue(result["found"])
        self.assertEqual(result["character_tag"], "inugami_korone")
        profiles = {item["variant_tag"]: item for item in result["profiles"]}
        self.assertEqual(
            set(profiles),
            {
                "inugami_korone",
                "inugami_korone_(1st_costume)",
                "inugami_korone_(street)",
                "inugami_korone_(new_year)",
            },
        )
        base_tags = {
            feature["canonical_tag"]
            for features in profiles["inugami_korone"]["features"].values()
            for feature in features
        }
        default_tags = {
            feature["canonical_tag"]
            for features in profiles["inugami_korone_(1st_costume)"]["features"].values()
            for feature in features
        }
        street_tags = {
            feature["canonical_tag"]
            for features in profiles["inugami_korone_(street)"]["features"].values()
            for feature in features
        }
        self.assertIn("dog_girl", base_tags)
        self.assertIn("brown_hair", base_tags)
        self.assertIn("white_dress", default_tags)
        self.assertIn("yellow_jacket", default_tags)
        self.assertIn("red_skirt", street_tags)
        self.assertNotIn("white_dress", base_tags)
        self.assertNotIn("red_skirt", base_tags)
        self.assertEqual(
            {source["source_site"] for source in profiles["inugami_korone_(1st_costume)"]["sources"]},
            {"danbooru", "gelbooru"},
        )
        self.assertTrue(profiles["inugami_korone_(1st_costume)"]["evidence"])

    def test_appearance_variant_can_be_passed_as_character_argument(self):
        result = get_character_appearance(
            "inugami_korone_(new_year)", include_evidence=False
        )
        self.assertTrue(result["found"])
        self.assertEqual(result["character_tag"], "inugami_korone")
        self.assertEqual(result["variant"], "inugami_korone_(new_year)")
        self.assertEqual(result["profile_count"], 1)
        self.assertEqual(result["profiles"][0]["variant_tag"], "inugami_korone_(new_year)")
        self.assertEqual(result["profiles"][0]["evidence"], [])
        self.assertEqual(result["profiles"][0]["sources"], [])

    def test_appearance_variant_is_scoped_to_requested_character(self):
        result = get_character_appearance(
            "hatsune_miku",
            variant="inugami_korone_(new_year)",
            include_evidence=False,
        )
        self.assertFalse(result["found"])
        self.assertEqual(result["character_tag"], "hatsune_miku")
        self.assertEqual(result["profiles"], [])
        self.assertNotIn("inugami_korone", result.get("character_tag", ""))

    def test_appearance_resolves_active_alias_to_canonical_profile(self):
        result = get_character_appearance("ganyu", include_evidence=False)
        self.assertTrue(result["found"])
        self.assertEqual(result["character_tag"], "ganyu_(genshin_impact)")
        self.assertEqual(result["resolution"]["type"], "alias")

    def test_appearance_migration_rejects_normalization_collisions_atomically(self):
        from scripts.migrate_appearance_profiles import migrate
        from weeb_alexandria_mcp.owned_schema import SCHEMA_SQL

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "collision.sqlite"
            con = sqlite3.connect(path)
            con.executescript(SCHEMA_SQL)
            con.executemany(
                """INSERT INTO character_profiles(
                    character_tag, display_name, display_name_normalized
                ) VALUES (?, ?, ?)""",
                [
                    ("Foo-Bar", "Foo Bar", "foo_bar"),
                    ("foo_bar", "Foo Bar 2", "foo_bar"),
                ],
            )
            con.commit()
            con.close()
            with self.assertRaises(ValueError):
                migrate(path)
            con = sqlite3.connect(path)
            appearance_count = con.execute(
                "SELECT count(*) FROM character_appearance_profiles"
            ).fetchone()[0]
            con.close()
        self.assertEqual(appearance_count, 0)

    def test_appearance_migration_normalizes_legacy_facets_and_deduplicates(self):
        from scripts.migrate_appearance_profiles import migrate
        from weeb_alexandria_mcp.owned_schema import SCHEMA_SQL

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "legacy_facets.sqlite"
            con = sqlite3.connect(path)
            con.executescript(SCHEMA_SQL)
            con.execute(
                """INSERT INTO character_profiles(
                    character_tag, display_name, display_name_normalized,
                    core_tags, provenance, confidence
                ) VALUES (?, ?, ?, ?, ?, ?)""",
                ("fixture_character", "Fixture Character", "fixture_character",
                 "blue_eyes", "fixture", "high"),
            )
            con.execute(
                """INSERT INTO trait_definitions(
                    trait_slug, facet, value, label, status
                ) VALUES (?, ?, ?, ?, 'active')""",
                ("blue_eyes_trait", "eye_color", "blue eyes", "Blue eyes"),
            )
            con.execute(
                """INSERT INTO character_traits(
                    character_tag, trait_slug, evidence_tag
                ) VALUES (?, ?, ?)""",
                ("fixture_character", "blue_eyes_trait", "blue_eyes"),
            )
            con.commit()
            con.close()
            migrate(path)
            con = sqlite3.connect(path)
            rows = con.execute(
                """SELECT facet, canonical_tag FROM character_appearance_features
                   WHERE appearance_key='fixture_character::default'"""
            ).fetchall()
            con.close()
        self.assertEqual(rows, [("eyes", "blue_eyes")])

    def test_promote_rejects_unregistered_character_before_writes(self):
        from scripts.promote_appearance import promote
        from weeb_alexandria_mcp.owned_schema import SCHEMA_SQL

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "promote.sqlite"
            seed_path = root / "seed.json"
            con = sqlite3.connect(db_path)
            con.executescript(SCHEMA_SQL)
            con.execute(
                "CREATE TABLE tags(site TEXT, name TEXT, category_name TEXT)"
            )
            con.commit()
            con.close()
            seed_path.write_text(json.dumps({
                "character_tag": "unregistered_character",
                "sources": [{
                    "id": "source-1", "source_site": "danbooru",
                    "source_kind": "wiki", "source_key": "fixture",
                    "source_tier": 1, "source_url": "https://example.invalid/wiki",
                }],
                "profiles": [{
                    "variant_tag": "unregistered_character",
                    "status": "published",
                    "features": [{
                        "facet": "hair", "canonical_tag": "brown_hair",
                        "source_refs": ["source-1"],
                    }],
                }],
            }), encoding="utf-8")
            with self.assertRaises(ValueError):
                promote(db_path, seed_path)
            con = sqlite3.connect(db_path)
            counts = [con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                      for table in (
                          "character_appearance_profiles",
                          "character_appearance_sources",
                      )]
            con.close()
        self.assertEqual(counts, [0, 0])

    def test_promote_replace_features_retires_unreviewed_legacy_rows(self):
        from scripts.promote_appearance import promote
        from weeb_alexandria_mcp.owned_schema import SCHEMA_SQL, ensure_owned_schema

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "promote_replace.sqlite"
            seed_path = root / "seed.json"
            con = sqlite3.connect(db_path)
            con.executescript(SCHEMA_SQL)
            ensure_owned_schema(con)
            con.execute(
                "CREATE TABLE tags(site TEXT, name TEXT, category_name TEXT)"
            )
            con.execute(
                "INSERT INTO tags VALUES ('danbooru', 'fixture_character', 'character')"
            )
            con.execute(
                """INSERT INTO character_appearance_profiles(
                    appearance_key, character_tag, variant_tag, display_name,
                    appearance_kind, is_default, status, confidence, provenance
                ) VALUES (?, ?, ?, ?, 'default', 1, 'published', 'high', 'legacy')""",
                (
                    "fixture_character::default", "fixture_character",
                    "fixture_character", "Fixture Character",
                ),
            )
            con.execute(
                """INSERT INTO character_appearance_features(
                    appearance_key, facet, value, canonical_tag, role, status, confidence
                ) VALUES (?, 'eyes', 'Blue eyes', 'blue_eyes', 'present', 'published', 'high')""",
                ("fixture_character::default",),
            )
            con.commit()
            con.close()
            seed_path.write_text(json.dumps({
                "character_tag": "fixture_character",
                "sources": [{
                    "id": "source-1", "source_site": "danbooru",
                    "source_kind": "wiki", "source_key": "fixture",
                    "source_tier": 1,
                }],
                "profiles": [{
                    "variant_tag": "fixture_character",
                    "status": "published", "replace_features": True,
                    "features": [{
                        "facet": "eyes", "canonical_tag": "green_eyes",
                        "source_refs": ["source-1"],
                    }],
                }],
            }), encoding="utf-8")
            promote(db_path, seed_path)
            con = sqlite3.connect(db_path)
            rows = dict(con.execute(
                "SELECT canonical_tag, status FROM character_appearance_features "
                "WHERE appearance_key='fixture_character::default'"
            ).fetchall())
            con.close()
        self.assertEqual(rows, {"blue_eyes": "retired", "green_eyes": "published"})

    def test_get_character_exposes_appearance_additively(self):
        result = get_character("hatsune_miku")
        self.assertTrue(result["found"])
        self.assertIn("appearance", result)
        self.assertTrue(result["appearance"]["found"])
        self.assertEqual(result["appearance"]["profiles"][0]["is_default"], True)

    def test_appearance_migration_is_idempotent(self):
        from scripts.migrate_appearance_profiles import migrate
        from weeb_alexandria_mcp.owned_schema import SCHEMA_SQL

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "source.sqlite"
            con = sqlite3.connect(path)
            con.executescript(SCHEMA_SQL)
            con.execute(
                """INSERT INTO character_profiles(
                    character_tag, display_name, display_name_normalized,
                    core_tags, provenance, confidence
                ) VALUES (?, ?, ?, ?, ?, ?)""",
                ("fixture_character", "Fixture Character", "fixture_character",
                 "brown_hair, blue_eyes", "fixture", "high"),
            )
            con.commit()
            con.close()
            first = migrate(path)
            second = migrate(path)
            con = sqlite3.connect(path)
            counts = {
                table: con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                for table in (
                    "character_appearance_profiles",
                    "character_appearance_features",
                    "appearance_feature_catalog",
                    "character_appearance_sources",
                    "character_appearance_feature_sources",
                )
            }
            integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
            con.close()
        self.assertEqual(first, second)
        self.assertEqual(counts, {
            "character_appearance_profiles": 1,
            "character_appearance_features": 2,
            "appearance_feature_catalog": 2,
            "character_appearance_sources": 1,
            "character_appearance_feature_sources": 2,
        })
        self.assertEqual(integrity, "ok")

    def test_appearance_catalog_deduplicates_shared_tags_and_keeps_links(self):
        catalog = self.con.execute(
            """SELECT catalog_id FROM appearance_feature_catalog
               WHERE canonical_tag='black_hair'"""
        ).fetchall()
        self.assertEqual(len(catalog), 1)
        catalog_id = catalog[0][0]
        assignment_count = self.con.execute(
            """SELECT count(*) FROM character_appearance_features
               WHERE canonical_tag='black_hair' AND status='published'"""
        ).fetchone()[0]
        linked_count = self.con.execute(
            """SELECT count(*) FROM character_appearance_features
               WHERE catalog_id=? AND canonical_tag='black_hair'
                 AND status='published'""",
            (catalog_id,),
        ).fetchone()[0]
        self.assertGreater(assignment_count, 1)
        self.assertEqual(linked_count, assignment_count)
        self.assertEqual(
            self.con.execute(
                """SELECT count(*) FROM character_appearance_features f
                   LEFT JOIN appearance_feature_catalog c
                     ON c.catalog_id=f.catalog_id
                    AND c.canonical_tag=f.canonical_tag
                   WHERE f.status <> 'retired' AND c.catalog_id IS NULL"""
            ).fetchone()[0],
            0,
        )

    def test_appearance_normalizer_deduplicates_legacy_facets_idempotently(self):
        from scripts.normalize_appearance_features import normalize
        from weeb_alexandria_mcp.owned_schema import SCHEMA_SQL, ensure_owned_schema

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "normalize.sqlite"
            con = sqlite3.connect(path)
            con.executescript(SCHEMA_SQL)
            ensure_owned_schema(con)
            con.executemany(
                """INSERT INTO character_appearance_sources(
                    source_site, source_kind, source_key, source_tier
                ) VALUES (?, ?, ?, ?)""",
                [
                    ("test", "wiki", "one", 1),
                    ("test", "wiki", "two", 1),
                ],
            )
            con.executemany(
                """INSERT INTO character_appearance_features(
                    appearance_key, facet, value, canonical_tag,
                    status, confidence
                ) VALUES (?, ?, ?, ?, 'published', 'high')""",
                [
                    ("fixture::default", "eye_color", "Blue eyes", "blue_eyes"),
                    ("fixture::default", "eyes", "Blue eyes", "blue_eyes"),
                ],
            )
            feature_ids = [
                row[0] for row in con.execute(
                    "SELECT feature_id FROM character_appearance_features"
                )
            ]
            source_ids = [
                row[0] for row in con.execute(
                    "SELECT source_id FROM character_appearance_sources"
                )
            ]
            con.executemany(
                """INSERT INTO character_appearance_feature_sources(
                    feature_id, source_id, evidence_text
                ) VALUES (?, ?, ?)""",
                [
                    (feature_ids[0], source_ids[0], "Evidence one"),
                    (feature_ids[1], source_ids[1], "Evidence two"),
                ],
            )
            con.commit()
            con.close()
            first = normalize(path)
            second = normalize(path)
            con = sqlite3.connect(path)
            associations = con.execute(
                """SELECT facet, canonical_tag, catalog_id
                   FROM character_appearance_features"""
            ).fetchall()
            evidence_count = con.execute(
                "SELECT count(*) FROM character_appearance_feature_sources"
            ).fetchone()[0]
            catalog_count = con.execute(
                "SELECT count(*) FROM appearance_feature_catalog"
            ).fetchone()[0]
            con.close()
        self.assertEqual(first["deduplicated_features"], 1)
        self.assertEqual(second["deduplicated_features"], 0)
        self.assertEqual(associations, [("eyes", "blue_eyes", associations[0][2])])
        self.assertEqual(evidence_count, 2)
        self.assertEqual(catalog_count, 1)

    def test_appearance_normalizer_resolves_hair_clip_alias_idempotently(self):
        from scripts.normalize_appearance_features import normalize
        from weeb_alexandria_mcp.owned_schema import SCHEMA_SQL, ensure_owned_schema

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "alias.sqlite"
            con = sqlite3.connect(path)
            con.executescript(SCHEMA_SQL)
            ensure_owned_schema(con)
            con.execute(
                """INSERT INTO character_appearance_sources(
                    source_site, source_kind, source_key, source_tier
                ) VALUES ('test', 'wiki', 'hair-clip', 1)"""
            )
            source_id = con.execute(
                "SELECT source_id FROM character_appearance_sources"
            ).fetchone()[0]
            con.execute(
                """INSERT INTO character_appearance_features(
                    appearance_key, facet, value, canonical_tag,
                    status, confidence
                ) VALUES ('fixture::default', 'hair_accessory', 'Hair clip',
                          'hair_clip', 'published', 'high')"""
            )
            feature_id = con.execute(
                "SELECT feature_id FROM character_appearance_features"
            ).fetchone()[0]
            con.execute(
                """INSERT INTO character_appearance_feature_sources(
                    feature_id, source_id, observed_tag, evidence_text
                ) VALUES (?, ?, 'hair_clip', 'Exact fixture evidence')""",
                (feature_id, source_id),
            )
            con.commit()
            con.close()

            first = normalize(path)
            second = normalize(path)
            con = sqlite3.connect(path)
            row = con.execute(
                """SELECT canonical_tag, facet, catalog_id FROM character_appearance_features"""
            ).fetchone()
            evidence = con.execute(
                """SELECT observed_tag, evidence_text
                   FROM character_appearance_feature_sources"""
            ).fetchone()
            catalog_tags = con.execute(
                "SELECT canonical_tag FROM appearance_feature_catalog ORDER BY canonical_tag"
            ).fetchall()
            con.close()

        self.assertEqual(first["canonical_tag_changes"], 1)
        self.assertEqual(first["merged_aliases"], 0)
        self.assertEqual(second["canonical_tag_changes"], 0)
        self.assertEqual(second["merged_aliases"], 0)
        self.assertEqual(row[0], "hairclip")
        self.assertEqual(row[1], "hair_accessory")
        self.assertIsNotNone(row[2])
        self.assertEqual(evidence, ("hair_clip", "Exact fixture evidence"))
        self.assertEqual(catalog_tags, [("hairclip",)])

    def test_appearance_candidate_builder_separates_sources_and_excludes_metadata(self):
        import json
        from scripts.build_appearance_candidates import build
        from weeb_alexandria_mcp.appearance_schema import infer_facet

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "source.sqlite"
            output_path = root / "character_appearance.sqlite"
            source = sqlite3.connect(source_path)
            source.executescript(
                """
                CREATE TABLE tags(
                    site TEXT NOT NULL, name TEXT NOT NULL,
                    category_name TEXT, post_count INTEGER,
                    aliases TEXT, nsfw INTEGER
                );
                CREATE TABLE wiki(site TEXT NOT NULL, title TEXT NOT NULL, body TEXT);
                INSERT INTO tags VALUES
                    ('danbooru', 'white_dress', 'general', 10, '', 0),
                    ('danbooru', 'red_dress', 'general', 8, '', 0),
                    ('danbooru', 'sunset', 'general', 20, '', 0),
                    ('danbooru', 'artist_name', 'artist', 100, '', 0),
                    ('danbooru', 'test_character', 'character', 100, '', 0),
                    ('danbooru', 'test_character_(outfit)', 'character', 5, '', 0);
                INSERT INTO wiki VALUES
                    ('danbooru', 'test_character_(outfit)', '[[white dress]] [[artist name]] [[sunset]]');
                INSERT INTO wiki VALUES
                    ('danbooru', 'testXcharacter_(wrong)', '[[white dress]]');
                """
            )
            source.commit()
            source.close()
            post_path = root / "danbooru_posts.jsonl"
            post_record = json.dumps({
                "id": 7,
                "tag_string_character": "test_character test_character_(outfit)",
                "tag_string_general": "white_dress red_dress",
                "tag_string_artist": "artist_name",
                "tag_string_meta": "official_art",
                "source_site": "danbooru",
            })
            post_path.write_text(
                post_record + "\n" + post_record + "\n", encoding="utf-8"
            )
            result = build(
                source_path,
                output_path,
                ["test_character"],
                [post_path],
            )
            con = sqlite3.connect(output_path)
            white = con.execute(
                """SELECT source_kind, support_count, sample_size
                   FROM appearance_tag_observations
                   WHERE observed_tag='white_dress'
                   ORDER BY source_kind"""
            ).fetchall()
            all_tags = {
                row[0] for row in con.execute(
                    "SELECT observed_tag FROM appearance_tag_observations"
                )
            }
            candidate_facets = {
                row[0] for row in con.execute(
                    "SELECT facet FROM appearance_candidates"
                )
            }
            wiki_white = next(row for row in white if row[0] == "wiki")
            integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
            con.close()
        self.assertGreaterEqual(result["observations"], 2)
        self.assertIn(("reference_post", 1, 1), white)
        self.assertEqual(tuple(wiki_white), ("wiki", 1, 1))
        self.assertNotIn("artist_name", all_tags)
        self.assertNotIn("official_art", all_tags)
        self.assertNotIn("", candidate_facets)
        self.assertEqual(integrity, "ok")
        self.assertEqual(infer_facet("hair_between_eyes"), "hair")

    def test_appearance_builder_rejects_ambiguous_post_variants(self):
        from scripts.build_appearance_candidates import build

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "source.sqlite"
            output_path = root / "character_appearance.sqlite"
            source = sqlite3.connect(source_path)
            source.executescript(
                """
                CREATE TABLE wiki(site TEXT NOT NULL, title TEXT NOT NULL, body TEXT);
                """
            )
            source.commit()
            source.close()
            post_path = root / "ambiguous_posts.jsonl"
            post_path.write_text(json.dumps({
                "id": 8,
                "tag_string_character": (
                    "test_character test_character_(a) test_character_(b)"
                ),
                "tag_string_general": "white_dress",
                "source_site": "danbooru",
            }) + "\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                build(source_path, output_path, ["test_character"], [post_path])

    def test_appearance_facet_normalizer_reclassifies_and_is_idempotent(self):
        from scripts.normalize_appearance_facets import normalize_facets
        from weeb_alexandria_mcp.owned_schema import SCHEMA_SQL, ensure_owned_schema

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "facets.sqlite"
            con = sqlite3.connect(path)
            con.executescript(SCHEMA_SQL)
            ensure_owned_schema(con)
            con.execute(
                """INSERT INTO character_appearance_sources(
                    source_site, source_kind, source_key, source_tier
                ) VALUES ('test', 'wiki', 'fixture', 1)"""
            )
            source_id = con.execute(
                "SELECT source_id FROM character_appearance_sources"
            ).fetchone()[0]
            con.executemany(
                """INSERT INTO character_appearance_features(
                    appearance_key, facet, value, canonical_tag,
                    status, confidence
                ) VALUES ('fixture::default', 'unclassified', ?, ?, 'published', 'high')""",
                [
                    ("Crystal wings", "crystal_wings"),
                    ("Dancer", "dancer"),
                    ("White wings", "white_wings"),
                ],
            )
            feature_ids = [
                row[0] for row in con.execute(
                    "SELECT feature_id FROM character_appearance_features ORDER BY feature_id"
                )
            ]
            con.executemany(
                """INSERT INTO character_appearance_feature_sources(
                    feature_id, source_id, evidence_text
                ) VALUES (?, ?, ?)""",
                [(feature_id, source_id, "Reviewed fixture evidence") for feature_id in feature_ids],
            )
            con.commit()
            con.close()

            first = normalize_facets(path)
            second = normalize_facets(path)
            con = sqlite3.connect(path)
            rows = con.execute(
                """SELECT facet, canonical_tag, facet_id
                   FROM character_appearance_features
                   ORDER BY canonical_tag"""
            ).fetchall()
            evidence_count = con.execute(
                "SELECT count(*) FROM character_appearance_feature_sources"
            ).fetchone()[0]
            schema_version = con.execute(
                "SELECT value FROM appearance_schema_metadata WHERE key='schema_version'"
            ).fetchone()[0]
            con.close()
        self.assertEqual(first["facet_changes"], 3)
        self.assertEqual(second["facet_changes"], 0)
        self.assertEqual(
            [(facet, tag) for facet, tag, _facet_id in rows],
            [("wings", "crystal_wings"), ("context", "dancer"), ("wings", "white_wings")],
        )
        self.assertTrue(all(facet_id is not None for _, _, facet_id in rows))
        self.assertEqual(evidence_count, 3)
        self.assertEqual(schema_version, "3")

    def test_appearance_runtime_exposes_facet_metadata_for_new_facets(self):
        from weeb_alexandria_mcp.appearance_schema import infer_facet

        self.assertEqual(infer_facet("angel_wings"), "wings")
        self.assertEqual(infer_facet("scar"), "markings")
        self.assertEqual(infer_facet("dancer"), "context")
        row = self.con.execute(
            """SELECT p.character_tag FROM character_appearance_profiles p
               JOIN character_appearance_features f
                 ON f.appearance_key=p.appearance_key
               WHERE p.status IN ('reviewed', 'published')
                 AND f.status IN ('reviewed', 'published')
                 AND f.facet='wings'
               ORDER BY p.character_tag LIMIT 1"""
        ).fetchone()
        self.assertIsNotNone(row)
        result = get_character_appearance(row[0], include_evidence=False)
        self.assertTrue(result["found"])
        profile = result["profiles"][0]
        self.assertIn("wings", profile["features"])
        self.assertEqual(profile["facet_metadata"]["wings"]["group"], "visual")
        self.assertTrue(profile["facet_metadata"]["wings"]["is_visual"])


if __name__ == "__main__":
    unittest.main()
