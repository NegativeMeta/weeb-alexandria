from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

from scripts import general_appearance_worker as worker
from scripts.promote_appearance import promote_batch
from scripts.rank_general_queue import load_dynamic_exclusions
from weeb_alexandria_mcp.owned_schema import ensure_owned_schema


class GeneralAppearanceWorkerContractTests(unittest.TestCase):
    def test_manifest_creation_is_exclusive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            state = {
                "schema_version": 1,
                "run_id": "run-one",
                "phase": "reserved",
                "batch_number": 1,
                "selected": ["alice"],
            }
            with mock.patch.object(worker, "STATE_PATH", state_path):
                worker.create_state_exclusive(state)
                self.assertEqual(worker.load_state()["run_id"], "run-one")
                with self.assertRaises(FileExistsError):
                    worker.create_state_exclusive({**state, "run_id": "run-two"})

    def test_open_manifest_is_resumed_without_a_new_ranking(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            state = {
                "schema_version": 1,
                "run_id": "run-one",
                "phase": "prepared",
                "batch_number": 1,
                "selected": ["alice"],
            }
            with mock.patch.object(worker, "STATE_PATH", state_path):
                worker.create_state_exclusive(state)
                with mock.patch.object(worker, "_rank", side_effect=AssertionError("reranked")):
                    self.assertEqual(worker.gate(), 0)
                self.assertEqual(worker.load_state()["run_id"], "run-one")

    def test_aborted_manifest_is_only_cleared_explicitly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            state = {
                "schema_version": 1,
                "run_id": "run-one",
                "phase": "reserved",
                "batch_number": 1,
                "selected": ["alice"],
            }
            with mock.patch.object(worker, "STATE_PATH", state_path):
                worker.create_state_exclusive(state)
                worker.abort("run-one", "manual test")
                self.assertEqual(worker.load_state()["phase"], "aborted")
                worker.clear("run-one")
                self.assertIsNone(worker.load_state())

    def test_closed_manifest_retries_when_final_preflight_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            state = {
                "schema_version": 1,
                "run_id": "run-one",
                "phase": "closed",
                "batch_number": 1,
                "selected": ["alice"],
            }
            with mock.patch.object(worker, "STATE_PATH", state_path):
                worker.create_state_exclusive(state)
                with mock.patch.object(worker, "_preflight", return_value=(False, "blocked")):
                    self.assertEqual(worker.gate(), 0)
                self.assertEqual(worker.load_state()["phase"], "promoted")

    def test_dynamic_exclusions_are_strict_and_deduplicated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "exclusions.json"
            path.write_text(json.dumps(["alice", "alice", " bob "]), encoding="utf-8")
            self.assertEqual(load_dynamic_exclusions(path), {"alice", "bob"})
            path.write_text(json.dumps(["alice", 3]), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_dynamic_exclusions(path)

    def test_batch_validation_precedes_all_canonical_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = root / "tag_library.sqlite"
            valid_seed = root / "alice.json"
            invalid_seed = root / "bob.json"
            con = sqlite3.connect(db)
            try:
                ensure_owned_schema(con)
                con.execute(
                    """CREATE TABLE tags(
                        site TEXT NOT NULL, name TEXT NOT NULL,
                        category_name TEXT NOT NULL, post_count INTEGER DEFAULT 0,
                        aliases TEXT DEFAULT '', nsfw INTEGER DEFAULT 0
                    )"""
                )
                con.execute(
                    "INSERT INTO character_profiles(character_tag, display_name, display_name_normalized) "
                    "VALUES (?, ?, ?)",
                    ("alice", "Alice", "alice"),
                )
                con.execute(
                    "INSERT INTO tags(site, name, category_name) VALUES (?, ?, ?)",
                    ("danbooru", "alice", "character"),
                )
                con.commit()
            finally:
                con.close()

            source_id = "test:wiki:alice"
            source = {
                "id": source_id,
                "source_site": "test",
                "source_kind": "wiki",
                "source_key": "alice",
                "source_tier": 1,
                "source_url": "https://example.invalid/alice",
                "title": "Alice",
                "excerpt": "hair",
            }
            profile = {
                "appearance_key": "alice::default",
                "variant_tag": "alice",
                "appearance_kind": "default",
                "status": "published",
                "display_name": "Alice",
                "features": [{
                    "facet": "hair",
                    "canonical_tag": "long_hair",
                    "value": "Long hair",
                    "status": "published",
                    "source_refs": [source_id],
                    "evidence": {"text": "hair", "observed_tag": "long_hair"},
                }],
            }
            valid_seed.write_text(json.dumps({
                "character_tag": "alice", "sources": [source], "profiles": [profile]
            }), encoding="utf-8")
            invalid_seed.write_text(json.dumps({
                "character_tag": "bob", "sources": [source], "profiles": [profile]
            }), encoding="utf-8")

            with self.assertRaises(ValueError):
                promote_batch(db, [valid_seed, invalid_seed])

            con = sqlite3.connect(db)
            try:
                self.assertEqual(
                    con.execute("SELECT count(*) FROM character_appearance_profiles").fetchone()[0],
                    0,
                )
                self.assertEqual(
                    con.execute("SELECT count(*) FROM character_appearance_sources").fetchone()[0],
                    0,
                )
            finally:
                con.close()

            first = promote_batch(db, [valid_seed])
            second = promote_batch(db, [valid_seed])
            self.assertEqual(first["totals"]["profiles"], 1)
            self.assertEqual(first["totals"]["features"], 1)
            self.assertEqual(first["totals"]["evidence_links"], 1)
            self.assertEqual(second["totals"], first["totals"])
            con = sqlite3.connect(db)
            try:
                self.assertEqual(
                    con.execute("SELECT count(*) FROM character_appearance_profiles").fetchone()[0],
                    1,
                )
                self.assertEqual(
                    con.execute("SELECT count(*) FROM character_appearance_features").fetchone()[0],
                    1,
                )
                self.assertEqual(
                    con.execute("SELECT count(*) FROM character_appearance_feature_sources").fetchone()[0],
                    1,
                )
            finally:
                con.close()
    def test_close_writes_report_and_releases_manifest_only_after_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_path = root / "state.json"
            report_path = root / "report.md"
            db_path = root / "tag_library.sqlite"
            exclusions_path = root / "exclusions.json"
            db_path.write_bytes(b"testdb")
            report_path.write_text("# Appearance queue\n", encoding="utf-8")
            state = {
                "schema_version": 1,
                "scope": "general_appearance",
                "run_id": "run-close",
                "batch_number": 1,
                "phase": "promoted",
                "created_at": "now",
                "updated_at": "now",
                "selected": ["alice"],
                "ranking": [{"name": "alice", "total": 10, "danbooru": 10, "gelbooru": 0, "e621": 0}],
                "source_snapshot": {"size": 6, "sha256": "before"},
                "candidate_snapshot": {"observations": 1, "candidates": 1},
                "candidate_final": None,
                "posts_jsonl": [],
                "decisions": {"alice": {"decision": "deferred", "reason": "insufficient evidence", "seed_path": None}},
                "promotion": {"seeds": {}, "totals": {}},
                "backup_path": None,
                "exclusions_added": [],
                "next_queue": [],
                "mcp_probe": None,
                "canonical_metrics": None,
                "commands": [],
                "last_error": "",
                "canonical_after_promotion": {"size": 6, "sha256": "after"},
            }
            metrics = {
                "published_profiles": 0,
                "published_features": 0,
                "all_evidence_links": 0,
                "published_evidence_links": 0,
                "retired_evidence_links": 0,
                "unjoined_evidence_links": 0,
                "evidence_gaps": 0,
                "duplicate_active_assignments": 0,
                "missing_facet_links": 0,
                "active_unclassified": 0,
                "last_promoted_seed": "",
                "integrity": "ok",
                "foreign_key_errors": 0,
            }
            with mock.patch.object(worker, "STATE_PATH", state_path), \
                    mock.patch.object(worker, "REPORT", report_path), \
                    mock.patch.object(worker, "DB", db_path), \
                    mock.patch.object(worker, "EXCLUSION_PATH", exclusions_path), \
                    mock.patch.object(worker, "source_fingerprint", return_value={"size": 6, "sha256": "after"}), \
                    mock.patch.object(worker, "_probe_runtime", return_value={"status": "ok"}), \
                    mock.patch.object(worker, "_build_derived", return_value={"observations": 1, "candidates": 1}), \
                    mock.patch.object(worker, "_validate_canonical", return_value=metrics), \
                    mock.patch.object(worker, "_rank", return_value=[{"name": "next", "total": 1, "danbooru": 1, "gelbooru": 0, "e621": 0}]), \
                    mock.patch.object(worker, "_preflight", return_value=(True, "state=READY")):
                worker.create_state_exclusive(state)
                self.assertEqual(worker.close("run-close"), 0)
                self.assertIsNone(worker.load_state())

            self.assertEqual(json.loads(exclusions_path.read_text(encoding="utf-8")), ["alice"])
            report = report_path.read_text(encoding="utf-8")
            self.assertIn("## General appearance batch 1", report)
            self.assertIn("batch_close=complete", report)
            self.assertIn("canonical_db_size=6", report)


if __name__ == "__main__":
    unittest.main()
