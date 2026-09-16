from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

from scripts import cleanup_legacy_scripts as cleanup
from scripts import general_appearance_worker as worker


class GeneralAppearanceAutomationTests(unittest.TestCase):
    def _state(self, run_id: str = "run-auto") -> dict:
        return {
            "schema_version": 1,
            "scope": "general_appearance",
            "run_id": run_id,
            "batch_number": 56,
            "phase": "reviewing",
            "selected": ["alice", "bob"],
            "ranking": [],
            "source_snapshot": {"size": 1, "sha256": "source"},
            "candidate_snapshot": {"observations": 1, "candidates": 1},
            "candidate_final": None,
            "posts_jsonl": [],
            "decisions": {
                "alice": {
                    "decision": "published",
                    "seed_path": "C:/repo/alice.json",
                    "reason": "",
                    "recorded_at": "old",
                },
                "bob": {
                    "decision": "published",
                    "seed_path": "C:/repo/bob.json",
                    "reason": "",
                    "recorded_at": "old",
                },
            },
            "promotion": None,
            "backup_path": None,
            "exclusions_added": [],
            "next_queue": [],
            "mcp_probe": None,
            "canonical_metrics": None,
            "commands": [],
            "last_error": "",
        }

    def test_auto_resolve_defers_only_invalid_seeds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            state = self._state()
            with mock.patch.object(worker, "STATE_PATH", state_path), \
                    mock.patch.object(
                        worker,
                        "_strict_validate_seeds",
                        return_value={
                            "errors_by_seed": {
                                "C:/repo/alice.json": [
                                    "alice.json: CANDIDATE_FAIL hair/blue_hair"
                                ],
                                "C:/repo/bob.json": [],
                            },
                            "metrics_by_seed": {},
                        },
                    ):
                worker.create_state_exclusive(state)
                result = worker.auto_resolve("run-auto")
                updated = worker.load_state()

            self.assertEqual(result["deferred"], ["alice"])
            self.assertEqual(updated["decisions"]["alice"]["decision"], "deferred")
            self.assertIsNone(updated["decisions"]["alice"]["seed_path"])
            self.assertIn("CANDIDATE_FAIL", updated["decisions"]["alice"]["reason"])
            self.assertEqual(
                updated["decisions"]["alice"]["auto_resolution"]["previous_decision"],
                "published",
            )
            self.assertEqual(updated["decisions"]["bob"]["decision"], "published")

    def test_auto_resolve_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            with mock.patch.object(worker, "STATE_PATH", state_path), \
                    mock.patch.object(
                        worker,
                        "_strict_validate_seeds",
                        return_value={
                            "errors_by_seed": {
                                "C:/repo/alice.json": ["alice.json: profile shape invalid"],
                                "C:/repo/bob.json": [],
                            },
                            "metrics_by_seed": {},
                        },
                    ):
                worker.create_state_exclusive(self._state())
                first = worker.auto_resolve("run-auto")
                second = worker.auto_resolve("run-auto")
                updated = worker.load_state()

            self.assertEqual(first["deferred"], ["alice"])
            self.assertEqual(second["deferred"], [])
            self.assertEqual(len(updated["auto_resolutions"]), 1)

    def test_auto_resolve_refuses_canonical_fingerprint_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            with mock.patch.object(worker, "STATE_PATH", state_path), \
                    mock.patch.object(
                        worker,
                        "source_fingerprint",
                        return_value={"size": 2, "sha256": "new"},
                    ):
                worker.create_state_exclusive(self._state())
                with self.assertRaisesRegex(RuntimeError, "fingerprint changed"):
                    worker._strict_validate_seeds(self._state())

    def test_reconcile_requires_exact_run_id_and_clears_after_ready(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            state = self._state("run-reconcile")
            state["phase"] = "aborted"
            state["promotion"] = None
            with mock.patch.object(worker, "STATE_PATH", state_path), \
                    mock.patch.object(worker, "DB", Path(directory) / "tag.sqlite"), \
                    mock.patch.object(worker, "REPORT", Path(directory) / "report.md"), \
                    mock.patch.object(worker, "source_fingerprint", return_value={"size": 1, "sha256": "new"}), \
                    mock.patch.object(worker, "_backup_reconciliation_database", return_value=Path(directory) / "backup.sqlite"), \
                    mock.patch.object(worker, "_canonical_metrics", return_value={
                        "integrity": "ok", "foreign_key_errors": 0,
                        "evidence_gaps": 0, "duplicate_active_assignments": 0,
                        "missing_facet_links": 0, "active_unclassified": 0,
                        "unjoined_evidence_links": 0,
                    }), \
                    mock.patch.object(worker, "_build_derived", return_value={"observations": 1, "candidates": 1}), \
                    mock.patch.object(worker, "_probe_runtime", return_value={"status": "ok"}), \
                    mock.patch.object(worker, "_reconciliation_indexes_fresh", return_value=True), \
                    mock.patch.object(worker, "_reconcile_latest_report"), \
                    mock.patch.object(worker, "_preflight", return_value=(True, "state=READY")):
                worker.create_state_exclusive(state)
                with self.assertRaisesRegex(RuntimeError, "run_id mismatch"):
                    worker.reconcile_aborted("wrong-run")
                result = worker.reconcile_aborted("run-reconcile")
                self.assertIsNone(worker.load_state())

            self.assertEqual(result["run_id"], "run-reconcile")
            self.assertEqual(result["database_mutated"], False)

    def test_tick_dry_run_does_not_reserve_a_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            with mock.patch.object(worker, "STATE_PATH", state_path), \
                    mock.patch.object(worker, "gate", return_value=0) as gate:
                self.assertEqual(worker.tick(dry_run=True), 0)
            gate.assert_called_once_with(dry_run=True)
            self.assertFalse(state_path.exists())

    def test_tick_does_not_clear_an_aborted_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            state = self._state("run-aborted")
            state["phase"] = "aborted"
            with mock.patch.object(worker, "STATE_PATH", state_path):
                worker.create_state_exclusive(state)
                self.assertEqual(worker.tick(), 0)
                self.assertEqual(worker.load_state()["phase"], "aborted")

    def test_tick_continues_complete_review_through_publish_and_close(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            state = self._state("run-tick")
            with mock.patch.object(worker, "STATE_PATH", state_path), \
                    mock.patch.object(worker, "auto_resolve", return_value={"deferred": []}) as resolve, \
                    mock.patch.object(worker, "publish", return_value=0) as publish, \
                    mock.patch.object(worker, "close", return_value=0) as close:
                worker.create_state_exclusive(state)
                self.assertEqual(worker.tick(), 0)

            resolve.assert_called_once_with("run-tick")
            publish.assert_called_once_with("run-tick")
            close.assert_called_once_with("run-tick")

    def test_archive_moves_only_published_seeds_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            seed_dir = root / "seeds" / "appearance"
            archive_dir = root / "seeds" / "archive"
            data_dir = root / "data"
            seed_dir.mkdir(parents=True)
            data_dir.mkdir()
            db_path = root / "tag_library.sqlite"
            alice_seed = seed_dir / "alice.json"
            bob_seed = seed_dir / "bob.json"
            source = {
                "id": "test:wiki:alice",
                "source_site": "test",
                "source_kind": "wiki",
                "source_key": "alice",
                "source_tier": 1,
            }
            profile = {
                "appearance_key": "alice::default",
                "variant_tag": "alice",
                "status": "published",
                "features": [],
            }
            alice_seed.write_text(json.dumps({
                "character_tag": "alice",
                "sources": [source],
                "profiles": [profile],
            }), encoding="utf-8")
            bob_seed.write_text("{\"pending\": true}\n", encoding="utf-8")
            con = sqlite3.connect(db_path)
            try:
                con.execute(
                    "CREATE TABLE character_appearance_profiles("
                    "appearance_key TEXT, character_tag TEXT, status TEXT)"
                )
                con.execute(
                    "INSERT INTO character_appearance_profiles VALUES (?, ?, ?)",
                    ("alice::default", "alice", "published"),
                )
                con.commit()
            finally:
                con.close()

            state = self._state("run-archive")
            state["phase"] = "archiving"
            state["selected"] = ["alice", "bob"]
            state["decisions"] = {
                "alice": {
                    "decision": "published",
                    "seed_path": str(alice_seed),
                    "reason": "",
                    "recorded_at": "now",
                },
                "bob": {
                    "decision": "deferred",
                    "seed_path": None,
                    "reason": "pending review",
                    "recorded_at": "now",
                },
            }
            state_path = data_dir / "state.json"
            manifest_path = data_dir / "appearance_seed_archive_manifest.json"
            patches = [
                mock.patch.object(worker, "ROOT", root),
                mock.patch.object(worker, "SEEDS", seed_dir),
                mock.patch.object(worker, "SEED_ARCHIVE", archive_dir),
                mock.patch.object(worker, "ARCHIVE_MANIFEST_PATH", manifest_path),
                mock.patch.object(worker, "DB", db_path),
                mock.patch.object(worker, "STATE_PATH", state_path),
            ]
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
                worker.create_state_exclusive(state)
                first = worker._archive_seeds_after_close(worker.load_state())
                second = worker._archive_seeds_after_close(worker.load_state())
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

            destination = archive_dir / "run-archive" / "alice.json"
            self.assertEqual(first["status"], "complete")
            self.assertEqual(second["status"], "complete")
            self.assertEqual([item["character"] for item in first["items"]], ["alice"])
            self.assertFalse(alice_seed.exists())
            self.assertTrue(bob_seed.exists())
            self.assertTrue(destination.exists())
            self.assertEqual(
                first["items"][0]["sha256_before"],
                hashlib.sha256(destination.read_bytes()).hexdigest(),
            )
            self.assertEqual(manifest["runs"][0]["run_id"], "run-archive")
            self.assertEqual(manifest["runs"][0]["status"], "complete")

    def test_close_archives_published_seed_before_releasing_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            seed_dir = root / "seeds" / "appearance"
            archive_dir = root / "seeds" / "archive"
            data_dir = root / "data"
            seed_dir.mkdir(parents=True)
            data_dir.mkdir()
            db_path = root / "tag_library.sqlite"
            report_path = root / "report.md"
            seed = seed_dir / "alice.json"
            seed.write_text(json.dumps({
                "character_tag": "alice",
                "sources": [{"id": "test:wiki:alice"}],
                "profiles": [{
                    "appearance_key": "alice::default",
                    "variant_tag": "alice",
                    "status": "published",
                    "features": [],
                }],
            }), encoding="utf-8")
            con = sqlite3.connect(db_path)
            try:
                con.execute(
                    "CREATE TABLE character_appearance_profiles("
                    "appearance_key TEXT, character_tag TEXT, status TEXT)"
                )
                con.execute(
                    "INSERT INTO character_appearance_profiles VALUES (?, ?, ?)",
                    ("alice::default", "alice", "published"),
                )
                con.commit()
            finally:
                con.close()
            report_path.write_text("# Appearance queue\n", encoding="utf-8")
            state = self._state("run-close-archive")
            state["phase"] = "promoted"
            state["selected"] = ["alice"]
            state["decisions"] = {
                "alice": {
                    "decision": "published",
                    "seed_path": str(seed),
                    "reason": "",
                    "recorded_at": "now",
                },
            }
            canonical_snapshot = worker.source_fingerprint(db_path)
            real_fingerprint = worker.source_fingerprint
            original_db = worker.DB
            def fingerprint(path: Path = original_db) -> dict[str, object]:
                if Path(path).resolve() in {original_db.resolve(), db_path.resolve()}:
                    return canonical_snapshot
                return real_fingerprint(path)
            state["source_snapshot"] = canonical_snapshot
            state["canonical_after_promotion"] = canonical_snapshot
            state["candidate_snapshot"] = {"observations": 1, "candidates": 1}
            state_path = data_dir / "state.json"
            manifest_path = data_dir / "appearance_seed_archive_manifest.json"
            metrics = {
                "published_profiles": 1,
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
            with mock.patch.object(worker, "ROOT", root), \
                    mock.patch.object(worker, "SEEDS", seed_dir), \
                    mock.patch.object(worker, "SEED_ARCHIVE", archive_dir), \
                    mock.patch.object(worker, "ARCHIVE_MANIFEST_PATH", manifest_path), \
                    mock.patch.object(worker, "STATE_PATH", state_path), \
                    mock.patch.object(worker, "REPORT", report_path), \
                    mock.patch.object(worker, "DB", db_path), \
                    mock.patch.object(worker, "source_fingerprint", side_effect=fingerprint), \
                    mock.patch.object(worker, "_probe_runtime", return_value={"status": "ok"}), \
                    mock.patch.object(worker, "_build_derived", return_value={"observations": 1, "candidates": 1}), \
                    mock.patch.object(worker, "_validate_canonical", return_value=metrics), \
                    mock.patch.object(worker, "_rank", return_value=[]), \
                    mock.patch.object(worker, "_preflight", return_value=(True, "state=READY")):
                worker.create_state_exclusive(state)
                self.assertEqual(worker.close("run-close-archive"), 0)
                self.assertIsNone(worker.load_state())

            destination = archive_dir / "run-close-archive" / "alice.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertFalse(seed.exists())
            self.assertTrue(destination.exists())
            self.assertEqual(manifest["runs"][0]["status"], "complete")
            self.assertEqual(manifest["runs"][0]["items"][0]["character"], "alice")

    def test_archive_conflict_keeps_source_and_manifest_recoverable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            seed_dir = root / "seeds" / "appearance"
            archive_dir = root / "seeds" / "archive"
            data_dir = root / "data"
            seed_dir.mkdir(parents=True)
            data_dir.mkdir()
            db_path = root / "tag_library.sqlite"
            seed = seed_dir / "alice.json"
            seed.write_text(json.dumps({
                "character_tag": "alice",
                "sources": [{"id": "test:wiki:alice"}],
                "profiles": [{
                    "appearance_key": "alice::default",
                    "variant_tag": "alice",
                    "status": "published",
                    "features": [],
                }],
            }), encoding="utf-8")
            con = sqlite3.connect(db_path)
            try:
                con.execute(
                    "CREATE TABLE character_appearance_profiles("
                    "appearance_key TEXT, character_tag TEXT, status TEXT)"
                )
                con.execute(
                    "INSERT INTO character_appearance_profiles VALUES (?, ?, ?)",
                    ("alice::default", "alice", "published"),
                )
                con.commit()
            finally:
                con.close()
            destination = archive_dir / "run-conflict" / "alice.json"
            destination.parent.mkdir(parents=True)
            destination.write_text("wrong destination\n", encoding="utf-8")
            state = self._state("run-conflict")
            state["phase"] = "archiving"
            state["selected"] = ["alice"]
            state["decisions"] = {
                "alice": {
                    "decision": "published",
                    "seed_path": str(seed),
                    "reason": "",
                    "recorded_at": "now",
                },
            }
            state_path = data_dir / "state.json"
            manifest_path = data_dir / "appearance_seed_archive_manifest.json"
            with mock.patch.object(worker, "ROOT", root), \
                    mock.patch.object(worker, "SEEDS", seed_dir), \
                    mock.patch.object(worker, "SEED_ARCHIVE", archive_dir), \
                    mock.patch.object(worker, "ARCHIVE_MANIFEST_PATH", manifest_path), \
                    mock.patch.object(worker, "DB", db_path), \
                    mock.patch.object(worker, "STATE_PATH", state_path):
                worker.create_state_exclusive(state)
                with self.assertRaisesRegex(RuntimeError, "destination exists"):
                    worker._archive_seeds_after_close(worker.load_state())
                self.assertTrue(seed.exists())
                self.assertTrue(worker.load_state())


class CleanupLegacyScriptsTests(unittest.TestCase):
    def test_inventory_and_quarantine_preserve_hashes_and_protected_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            (root / "data").mkdir()
            (root / "seeds" / "appearance").mkdir(parents=True)
            (root / "backups").mkdir()
            legacy = root / "fix_state.py"
            legacy.write_text("temporary repair\n", encoding="utf-8")
            legacy_script = root / "scripts" / "_complete_close_b53.py"
            legacy_script.write_text("batch repair\n", encoding="utf-8")
            protected = root / "scripts" / "general_appearance_worker.py"
            protected.write_text("operational\n", encoding="utf-8")
            (root / "data" / "general_appearance_worker_state.json").write_text("{}", encoding="utf-8")
            (root / "seeds" / "appearance" / "alice.json").write_text("{}", encoding="utf-8")
            (root / "backups" / "recent.sqlite").write_bytes(b"backup")
            quarantine = Path(directory).parent / f"{root.name}-quarantine"

            entries = cleanup.inventory(root)
            self.assertEqual(
                {entry["relative_path"] for entry in entries},
                {"fix_state.py", "scripts/_complete_close_b53.py"},
            )
            manifest_path = cleanup.apply_quarantine(root, quarantine, entries)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

            self.assertFalse(legacy.exists())
            self.assertFalse(legacy_script.exists())
            self.assertTrue(protected.exists())
            self.assertTrue((root / "data" / "general_appearance_worker_state.json").exists())
            self.assertTrue((root / "seeds" / "appearance" / "alice.json").exists())
            self.assertTrue((root / "backups" / "recent.sqlite").exists())
            self.assertEqual(len(manifest["moved"]), 2)
            for item in manifest["moved"]:
                quarantined = Path(item["quarantine_path"])
                self.assertEqual(
                    item["sha256"],
                    hashlib.sha256(quarantined.read_bytes()).hexdigest(),
                )


if __name__ == "__main__":
    unittest.main()
