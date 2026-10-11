"""Small checks for folder admission boundaries."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugin"))
from cache_scope import scope_rows, NO_MATCH, directory_rule

class FolderScope(unittest.TestCase):
    def test_drive_mode_preserves_ids_and_ordinary_read_cache(self):
        saved, rows = scope_rows([{"id": 7, "path": "/games/A"}], {"/games/A": []}, "drives", [])
        self.assertEqual(saved, [{"id": 7, "path": "/games/A"}])
        self.assertEqual(rows[0], [0, "unclassified", 255, 1])

    def test_folder_mode_excludes_games_outside_scope(self):
        saved = [{"id": 1, "path": "/games/A"}, {"id": 2, "path": "/archives/B"}]
        updated, rows = scope_rows(saved, {"/games/A": [], "/archives/B": []}, "folders", ["/games"])
        self.assertEqual(updated[:2], saved)
        self.assertEqual(rows[0], [0, "unclassified", 255, 0])
        self.assertEqual(rows[2][1], NO_MATCH)
        self.assertIn("directory:/games/A", rows[1][1])
        self.assertEqual(rows[3][1], "directory:/games")

    def test_selected_subfolder_does_not_enable_whole_parent_game(self):
        _, rows = scope_rows([{"id": 1, "path": "/game"}], {"/game": []}, "folders", ["/game/data"])
        self.assertIn("directory:/game/data", rows[1][1])
        self.assertNotIn("directory:/game&", rows[1][1])

    def test_empty_scope_and_full_slots_do_not_fall_back_to_all_reads(self):
        _, rows = scope_rows([{"id": 1, "path": "/game"}], {"/game": []}, "folders", [])
        self.assertEqual(rows[0][-1], 0)
        self.assertEqual(rows[1][1], NO_MATCH)
        with self.assertRaisesRegex(RuntimeError, "no free"):
            scope_rows([{"id": n, "path": "/old/" + str(n)} for n in range(1,33)], {}, "folders", ["/new"])

    def test_invalid_rule_paths_are_refused(self):
        for value in ("/bad,folder", "/bad&folder", "/bad" + chr(10) + "folder", "relative"):
            with self.assertRaises(RuntimeError):directory_rule([value])

if __name__ == "__main__": unittest.main()
