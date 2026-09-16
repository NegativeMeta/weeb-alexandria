import json
from pathlib import Path
import tempfile
import unittest

from scripts import promote_appearance


class LegacyPromotionGuardTests(unittest.TestCase):
    def test_legacy_cli_is_blocked_for_character_owned_by_worker_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "worker_state.json"
            state_path.write_text(
                json.dumps({
                    "scope": "general_appearance",
                    "run_id": "run-52",
                    "phase": "reviewing",
                    "selected": ["alice"],
                }),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(RuntimeError, "use general_appearance_worker.py --publish"):
                promote_appearance._guard_legacy_cli("alice", state_path)

            promote_appearance._guard_legacy_cli("bob", state_path)


if __name__ == "__main__":
    unittest.main()
