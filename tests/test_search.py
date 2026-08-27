import sqlite3
import unittest
from pathlib import Path

from weeb_alexandria_mcp.server import (
    _tag_rows,
    _tag_suggestions,
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
        suggestions = _tag_suggestions(self.con, "swalow", "tag", 5)
        self.assertTrue(any(row["name"] == "swallowing" for row in suggestions))

    def test_get_tag_normalizes_human_spacing(self):
        result = get_tag_knowledge("closed mouth")
        self.assertTrue(result["found"])
        self.assertTrue(any(row["name"] == "closed_mouth" for row in result["tags"]))

    def test_active_alias_is_recommended(self):
        suggestions = _tag_suggestions(self.con, "fingers_in_mouth", "tag", 5)
        self.assertTrue(any(row["name"] == "finger_in_own_mouth" and row["match_type"] == "alias"
                            for row in suggestions))


if __name__ == "__main__":
    unittest.main()
