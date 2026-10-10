"""Small checks for real-block attribution, eviction and concurrent changes."""
import io
import os
from pathlib import Path
import struct
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugin"))
if os.name != "posix":
    sys.modules.setdefault("fcntl", types.SimpleNamespace(ioctl=lambda *_: None))
import resident_games as r

STATUS = "0 32768 cache 8 10/100 512 1/64 0 0 0 0 0 1 0 2 metadata2 writethrough 2 migration_threshold 2048 smq 0 rw -"
XML = '<superblock block_size="512" nr_cache_blocks="64"><mappings><mapping cache_block="0" origin_block="8" dirty="false"/></mappings></superblock>'


class ResidentCheck(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.file = self.root / "game.dat"
        self.file.write_bytes(bytes(4096))
        self.physical = 8 * 262144
        self.flags = 1

    def ioctl(self, fd, op, buf, mutate):
        self.assertEqual(struct.unpack_from("=I", buf, 16)[0], 0, "Must not request an fsync")
        struct.pack_into("=I", buf, 20, 1)
        struct.pack_into("=QQQQQIIII", buf, 32, 0, self.physical, 4096, 0, 0, self.flags, 0, 0, 0)

    def blockset(self, items):
        result = r.BlockSet(64)
        for item in items:
            result.add(item)
        return result

    def has(self, blocks):
        with patch.object(r.fcntl, "ioctl", self.ioctl), \
             patch.object(os, "O_NOFOLLOW", getattr(os, "O_NOFOLLOW", 0), create=True), \
             patch.object(os, "O_NONBLOCK", getattr(os, "O_NONBLOCK", 0), create=True):
            return r.file_has_blocks(self.file, self.root, self.file.stat().st_dev, self.blockset(blocks), 262144, time.monotonic() + 5)

    def test_eviction_and_updated_file_remove_a_previous_match(self):
        self.assertTrue(self.has([8]))
        self.assertFalse(self.has([9]), "A previous cached game must disappear after eviction")
        self.physical = 9 * 262144  # Steam replaced the file at a different extent.
        self.assertFalse(self.has([8]), "Old cache blocks must not match an updated game file")
        self.assertTrue(self.has([9]))

    def test_unwritten_extents_are_not_cached_game_data(self):
        self.flags = 1 | 0x800
        self.assertFalse(self.has([8]))

    def test_partial_blocks_and_exclusive_end(self):
        self.assertTrue(r.overlap(self.blockset([8]), 8 * 262144 + 4096, 8 * 262144 + 8192, 262144))
        self.assertFalse(r.overlap(self.blockset([9]), 8 * 262144, 9 * 262144, 262144))
        self.assertFalse(r.overlap(self.blockset([]), 0, 4096, 262144))

    def test_metadata_layout_count_and_duplicate_validation(self):
        blocks, size = r.parse_mappings(io.StringIO(XML), STATUS, 32768 * 512)
        self.assertEqual((blocks.count, size), (1, 262144))
        self.assertTrue(r.overlap(blocks, 8 * size, 9 * size, size))
        with self.assertRaises(r.ScanChanged):
            r.parse_mappings(io.StringIO(XML), STATUS.replace("1/64", "2/64"), 32768 * 512)
        with self.assertRaises(ValueError):
            r.parse_mappings(io.StringIO(XML.replace('</mappings>', '<mapping cache_block="0" origin_block="9"/></mappings>')), STATUS, 32768 * 512)
        with self.assertRaises(ValueError):
            r.parse_mappings(io.StringIO('<broken'), STATUS, 32768 * 512)

    def test_reads_do_not_invalidate_snapshot_but_writes_and_evictions_do(self):
        read = STATUS.replace("1/64 0 0 0 0 0 1", "1/64 99 77 0 0 0 1")
        written = STATUS.replace("1/64 0 0 0 0 0 1", "1/64 0 0 1 0 0 1")
        evicted = STATUS.replace("1/64 0 0 0 0 0 1", "1/64 0 0 0 0 1 1")
        self.assertEqual(r.mapping_key(STATUS), r.mapping_key(read))
        self.assertNotEqual(r.mapping_key(STATUS), r.mapping_key(written))
        self.assertNotEqual(r.mapping_key(STATUS), r.mapping_key(evicted))


if __name__ == "__main__":
    unittest.main()
