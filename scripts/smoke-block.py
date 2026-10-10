"""Small real dm-cache check using disposable image files, not a game partition."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from block_cache import BlockCache, parse_status
from cache_service import command, mounts, flatten, busy

parser = argparse.ArgumentParser()
parser.add_argument("--cache-root", required=True)
args = parser.parse_args()
cache = Path(args.cache_root)
with tempfile.TemporaryDirectory(prefix="deckycache-block-check-", dir="/home/deck/deckycache-lab") as temporary:
    base = Path(temporary)
    origin_file, target = base / "origin.img", base / "library"
    with origin_file.open("wb") as f:
        f.truncate(128 * 1024**2)
    target.mkdir()
    origin = command("losetup", "--find", "--show", origin_file)
    identifier = "smoke-" + str(os.getpid())
    name = "deckycache-" + identifier
    try:
        command("mkfs.ext4", "-F", "-q", origin)
        uuid = command("blkid", "-s", "UUID", "-o", "value", origin)
        command("mount", origin, target)
        content = os.urandom(8 * 1024**2)
        (target / "game.dat").write_bytes(content)
        command("sync", "-f", target)
        lib = {"id": identifier, "serial": "disposable-smoke", "uuid": uuid, "size": 128 * 1024**2,
               "path": str(target), "fstype": "ext4", "options": "rw,noatime"}
        class State:
            config = {"libraries": [lib]}
            runtime = {}
            def save_runtime(self):
                pass
        state = State()
        def fixture_tree():
            return [{"serial": lib["serial"], "children": [{"uuid": uuid, "type": "part", "size": lib["size"], "path": origin}]}]
        engine = BlockCache(state, command, mounts, fixture_tree, flatten, busy, cache)
        engine.activate(lib)
        before = engine.verify(lib)
        # Direct reads avoid mistaking RAM page-cache hits for SSD block-cache hits.
        for _ in range(4):
            command("dd", "if=" + str(target / "game.dat"), "of=/dev/null", "bs=256K", "iflag=direct", "status=none")
            time.sleep(0.2)
        after = engine.verify(lib)
        assert after["used"] > 0 and after["hits"] > before["hits"], (before, after)
        allocation = cache / "blocks" / identifier / "data"
        inode = allocation.stat().st_ino
        engine.deactivate(lib, preserve=True)
        assert str(target) not in mounts()
        assert engine.seal_path(lib).exists()
        # Losing /run state mirrors a new boot: only SSD metadata may be reused.
        state.runtime = {}
        engine = BlockCache(state, command, mounts, fixture_tree, flatten, busy, cache)
        engine.activate(lib)
        warm = engine.verify(lib)
        assert state.runtime[identifier]["warm_start"] is True
        assert warm["used"] >= after["used"] and allocation.stat().st_ino == inode, (after, warm)
        assert not engine.seal_path(lib).exists()
        command("dd", "if=" + str(target / "game.dat"), "of=/dev/null", "bs=256K", "iflag=direct", "status=none")
        assert engine.verify(lib)["hits"] > warm["hits"]
        # Exercise writes into blocks that were already warm, then atomic rename.
        in_place = b"UPDATED CACHED BLOCKS\n" * 10000
        with (target / "game.dat").open("r+b") as f:
            f.write(in_place)
            f.flush()
            os.fsync(f.fileno())
        engine.deactivate(lib, preserve=True)
        engine.activate(lib)
        assert (target / "game.dat").read_bytes().startswith(in_place)
        replacement = b"STEAM UPDATE\n" * 10000
        (target / "download.tmp").write_bytes(replacement)
        os.replace(target / "download.tmp", target / "game.dat")
        command("sync", "-f", target)
        assert engine.verify(lib)["dirty"] == 0
        engine.deactivate(lib, preserve=True)
        engine.activate(lib)
        assert state.runtime[identifier]["warm_start"] is True
        assert (target / "game.dat").read_bytes() == replacement
        engine.deactivate(lib, preserve=True)
        # Even if a clean marker exists, a writable bypass mount invalidates it.
        engine.mount_original(lib, origin)
        assert (target / "game.dat").read_bytes() == replacement
        # Work directly on HDD between activations must not resurrect old cache data.
        direct = b"UPDATED WHILE CACHE OFF\n" * 10000
        (target / "game.dat").write_bytes(direct)
        command("sync", "-f", target)
        command("umount", target)
        engine.activate(lib)
        assert state.runtime[identifier]["warm_start"] is False
        assert (target / "game.dat").read_bytes() == direct
        engine.deactivate(lib)
        print(json.dumps({"result": "PASS", "before": before, "after": after,
                          "warm_restore": warm, "warm_in_place_update": True,
                          "atomic_update_on_original": True, "direct_source_change_after_detach": True}))
    finally:
        command("umount", target, check=False)
        command("dmsetup", "remove", name, check=False)
        for suffix in ("data", "metadata", "clean.json", "clean.tmp"):
            path = cache / "blocks" / identifier / suffix
            for line in command("losetup", "-j", path, check=False).splitlines():
                command("losetup", "-d", line.split(":", 1)[0])
            path.unlink(missing_ok=True)
        directory = cache / "blocks" / identifier
        if directory.exists():
            directory.rmdir()
        command("losetup", "-d", origin)
