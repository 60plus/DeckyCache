"""Exercise clear-cache on disposable images, never on a user's cache."""
import json
import os
from pathlib import Path
import tempfile
import time

from opencas_cache import OpenCasCache
from cache_service import Manager, command, mounts, flatten, busy


def read_cold(path):
    with path.open("rb") as stream:
        os.posix_fadvise(stream.fileno(), 0, 0, os.POSIX_FADV_DONTNEED)
        return stream.read()


with tempfile.TemporaryDirectory(prefix="clear-probe-", dir="/home/deck/deckycache-opencas-probe-26.09") as tmp:
    base = Path(tmp)
    source, target, cache = base / "source.img", base / "library", base / "cache"
    target.mkdir()
    cache.mkdir()
    command("fallocate", "-l", 256 * 1024**2, source)
    origin = command("losetup", "--find", "--show", "--direct-io=on", source)
    lib = engine = None
    try:
        command("mkfs.ext4", "-q", "-F", "-E", "lazy_itable_init=0,lazy_journal_init=0", origin)
        uuid = command("blkid", "-s", "UUID", "-o", "value", origin)
        command("mount", origin, target)
        game = target / "Test Game"
        game.mkdir()
        data = b"original-HDD-data".ljust(4096, b"A") * 2048
        file = game / "data.bin"
        file.write_bytes(data)
        command("sync", "-f", target)
        lib = dict(id="clear-probe-" + str(os.getpid()), serial="disposable", uuid=uuid,
                   size=256 * 1024**2, path=str(target), fstype="ext4", options="rw,noatime", cas_id=15003)

        class State:
            config = {"cache": {"uuid": "disposable-cache", "serial": "disposable"}, "libraries": [lib]}
            runtime = {}
            def save_runtime(self): pass
            def game_folders(self, libraries): return []
            def games(self, libraries):
                return [dict(id="1", name="Test Game", steam=True, path=str(game), mapper="/dev/cas15003-1")]

        state = State()
        def fixture_tree():
            return [{"serial": "disposable", "children": [dict(path=origin, uuid=uuid, type="part", size=lib["size"])]}]

        engine = OpenCasCache(state, command, mounts, fixture_tree, flatten, busy, cache)
        engine.activate(lib)
        engine.sync_classes(lib)
        time.sleep(3)
        assert read_cold(file) == data
        before = engine.verify(lib)
        assert before["used"] > 0
        image_before = (engine.image(lib).stat().st_ino, engine.image(lib).stat().st_size)
        mount_before = command("findmnt", "-n", "-o", "ID,SOURCE,TARGET", "--target", target)
        manager = Manager.__new__(Manager)
        manager.config, manager.block, manager.active = state.config, engine, engine.active
        manager.clear_cache({"confirmed": True, "cache_uuid": "disposable-cache"})
        empty = engine.verify(lib)
        assert empty["used"] == 0, empty
        assert engine.cached_games([dict(lib, active=True)]) == []
        assert command("findmnt", "-n", "-o", "ID,SOURCE,TARGET", "--target", target) == mount_before
        assert (engine.image(lib).stat().st_ino, engine.image(lib).stat().st_size) == image_before

        engine.deactivate(lib, preserve=True)
        state.runtime = {}
        engine.activate(lib)
        assert state.runtime[lib["id"]]["warm_start"]
        assert engine.cached_games([dict(lib, active=True)]) == []
        assert read_cold(file) == data
        refill = engine.verify(lib)
        assert refill["used"] > empty["used"]

        patch = b"updated-on-original-after-clear".ljust(4096, b"P")
        with file.open("r+b") as stream:
            stream.write(patch)
            stream.flush()
            os.fsync(stream.fileno())
        expected = patch + data[4096:]
        assert read_cold(file) == expected
        engine.deactivate(lib, preserve=True)
        engine.mount_original(lib, origin)
        assert file.read_bytes() == expected
        result = {"result": "PASS", "before": before, "after_clear": empty, "refill": refill,
                  "same_cache_image": True, "mount_unchanged_during_clear": True,
                  "clear_survives_warm_load": True, "original_intact": True,
                  "update_after_clear_reaches_original": True}
    finally:
        command("umount", target, check=False)
        if engine is not None and lib is not None:
            if engine.table(lib):
                engine.verify_cache_device(lib)
                engine.cli("-T", "-i", engine.cid(lib))
            engine.free_loops(lib)
        command("losetup", "-d", origin)
    print(json.dumps(result), flush=True)
