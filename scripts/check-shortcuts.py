"""Shortcut discovery boundaries; no real drives or Steam profiles are changed."""
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugin"))
from steam_shortcuts import read_shortcuts, shortcut_games


def vdf(obj):
    data = b""
    for key, value in obj.items():
        name = str(key).encode() + b"\0"
        if isinstance(value, dict):
            data += b"\0" + name + vdf(value)
        elif isinstance(value, int):
            data += b"\2" + name + struct.pack("<I", value & 0xffffffff)
        else:
            data += b"\1" + name + value.encode() + b"\0"
    return data + b"\10"


class Shortcuts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.steam = self.root / "Steam"
        self.file = self.steam / "userdata/123/config/shortcuts.vdf"
        self.file.parent.mkdir(parents=True)
        self.volume = self.root / "library"
        self.game = self.volume / "GAMES/Blood - Refreshed Supply"
        self.game.mkdir(parents=True)
        self.exe = self.game / "Blood.exe"
        self.exe.touch()
        self.libs = [{"path": str(self.volume), "active": True, "enabled": True, "mapper": "/dev/cas1001-1"}]
        self.row = {"AppName": "Blood - Refreshed Supply", "appid": 2558852213,
                    "Exe": '"' + str(self.exe) + '"', "StartDir": str(self.game),
                    "tags": {"0": "DRM-free"}}

    def save(self, row=None):
        self.file.write_bytes(vdf({"shortcuts": {"0": row or self.row}}))

    def test_binary_shortcut_is_discovered_without_steam_manifest(self):
        self.save()
        games = shortcut_games(self.steam, self.libs)
        self.assertEqual(len(games), 1)
        self.assertEqual(games[0]["app_id"], 2558852213)
        self.assertEqual(games[0]["id"], "shortcut:123:2558852213")
        self.assertEqual(games[0]["path"], str(self.game.resolve()))
        self.assertFalse(games[0]["steam"])
        self.assertEqual(games[0]["mapper"], "/dev/cas1001-1")

    def test_disabled_drive_or_missing_executable_is_excluded(self):
        self.save()
        for key in ("enabled", "active"):
            self.assertEqual(shortcut_games(self.steam, [dict(self.libs[0], **{key: False})]), [])
        self.exe.unlink()
        self.assertEqual(shortcut_games(self.steam, self.libs), [])

    def test_external_launcher_does_not_attribute_the_start_directory(self):
        wrapper = self.root / "launcher"
        wrapper.touch()
        self.save(dict(self.row, Exe=str(wrapper)))
        self.assertEqual(shortcut_games(self.steam, self.libs), [])

    def test_shared_start_directory_never_tracks_other_games(self):
        self.save(dict(self.row, StartDir=str(self.volume / "GAMES")))
        self.assertEqual(shortcut_games(self.steam, self.libs)[0]["path"], str(self.game.resolve()))
        broad = self.volume / "game.exe"
        broad.touch()
        self.save(dict(self.row, Exe=str(broad), StartDir=str(self.volume)))
        self.assertEqual(shortcut_games(self.steam, self.libs), [])

    def test_nested_executable_uses_its_dedicated_game_directory(self):
        binary = self.game / "Binaries/Win64/game.exe"
        binary.parent.mkdir(parents=True)
        binary.touch()
        self.save(dict(self.row, Exe=str(binary), StartDir='"' + str(self.game) + '"'))
        self.assertEqual(shortcut_games(self.steam, self.libs)[0]["path"], str(self.game.resolve()))

    def test_truncated_and_unsupported_files_do_not_hide_other_profiles(self):
        self.save()
        valid = self.file.read_bytes()
        other = self.steam / "userdata/456/config/shortcuts.vdf"
        other.parent.mkdir(parents=True)
        other.write_bytes(valid)
        for invalid in (valid[:-3], b"\x06field\0x\x08", b"\0shortcuts\0"):
            self.file.write_bytes(invalid)
            with self.assertRaises(ValueError):
                read_shortcuts(self.file)
            games = shortcut_games(self.steam, self.libs)
            self.assertEqual([game["id"] for game in games], ["shortcut:456:2558852213"])


if __name__ == "__main__":
    unittest.main()
