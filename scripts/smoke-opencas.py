"""Scoped Open CAS adapter check. Uses disposable images, never game files."""
import json
import os
from pathlib import Path
import tempfile
import time

from opencas_cache import OpenCasCache
from cache_service import command, mounts, flatten, busy

def read_cold(path):
    with path.open("rb") as f:
        os.posix_fadvise(f.fileno(), 0, 0, os.POSIX_FADV_DONTNEED)
        return f.read()

with tempfile.TemporaryDirectory(prefix="adapter-probe-", dir="/home/deck/deckycache-opencas-probe-26.09") as tmp:
    base = Path(tmp)
    source, target, cache = base/"source.img", base/"library", base/"cache"
    target.mkdir();cache.mkdir()
    command("fallocate", "-l", 256*1024**2, source)
    origin = command("losetup", "--find", "--show", "--direct-io=on", source)
    cid = 15002
    lib = None
    engine = None
    result = {}
    try:
        command("mkfs.ext4", "-q", "-F", "-E", "lazy_itable_init=0,lazy_journal_init=0", origin)
        uuid = command("blkid", "-s", "UUID", "-o", "value", origin)
        command("mount", origin, target)
        game = target/"Test Game";game.mkdir()
        data = b"original-data".ljust(4096,b"A")*2048
        (game/"data.bin").write_bytes(data)
        command("sync","-f",target)
        lib = dict(id="adapter-probe-"+str(os.getpid()),serial="disposable",uuid=uuid,
                   size=256*1024**2,path=str(target),fstype="ext4",options="rw,noatime",cas_id=cid)
        class State:
            config={"cache":{"uuid":"disposable-cache","serial":"disposable"},"libraries":[lib]}
            runtime={}
            def save_runtime(self):pass
            def game_folders(self, libraries):return []
            def games(self, libraries):return [dict(id="1",name="Test Game",steam=True,path=str(game),mapper="/dev/cas15002-1")]
        state=State()
        def fixture_tree():
            return [{"serial":"disposable","children":[dict(path=origin,uuid=uuid,type="part",size=lib["size"])]}]
        engine=OpenCasCache(state,command,mounts,fixture_tree,flatten,busy,cache)
        engine.activate(lib)
        engine.sync_classes(lib)
        time.sleep(3)
        before=engine.verify(lib)
        assert read_cold(game/"data.bin")==data
        assert read_cold(game/"data.bin")==data
        after=engine.verify(lib)
        assert after["used"]>0 and after["hits"]>before["hits"],(before,after)
        assert engine.cached_games([dict(lib,active=True)])[0]["id"]=="1"
        # Direct I/O must remain cached, regardless of per-game attribution.
        hits=after["hits"]
        command("dd","if="+str(game/"data.bin"),"of=/dev/null","iflag=direct","bs=1M","status=none")
        assert engine.verify(lib)["hits"]>hits
        used=engine.verify(lib)["used"]
        inode=engine.image(lib).stat().st_ino
        engine.deactivate(lib,preserve=True)
        assert str(target) not in mounts() and engine.seal_path(lib).exists()
        state.runtime={}
        engine.activate(lib)
        assert state.runtime[lib["id"]]["warm_start"] and engine.image(lib).stat().st_ino==inode
        warm=engine.verify(lib)
        assert warm["used"]>=used,(warm,used)
        assert read_cold(game/"data.bin")==data
        in_place=b"patched-existing-cache-line".ljust(4096,b"P")
        with (game/"data.bin").open("r+b") as f:
            f.write(in_place);f.flush();os.fsync(f.fileno())
        assert read_cold(game/"data.bin").startswith(in_place)
        engine.deactivate(lib,preserve=True)
        engine.activate(lib)
        assert read_cold(game/"data.bin").startswith(in_place)
        replacement=b"updated-on-HDD".ljust(4096,b"B")*2048
        (target/"download.tmp").write_bytes(replacement)
        os.replace(target/"download.tmp",game/"data.bin")
        command("sync","-f",target)
        assert read_cold(game/"data.bin")==replacement
        assert engine.verify(lib)["dirty"]==0
        engine.deactivate(lib,preserve=True)
        engine.activate(lib)
        assert state.runtime[lib["id"]]["warm_start"]
        assert (game/"data.bin").read_bytes()==replacement
        engine.deactivate(lib,preserve=True)
        engine.mount_original(lib,origin)
        assert (game/"data.bin").read_bytes()==replacement
        updated_without_cache=b"changed-on-original".ljust(4096,b"C")*2048
        (game/"data.bin").write_bytes(updated_without_cache)
        command("sync","-f",target)
        command("umount",target)
        engine.activate(lib)
        assert not state.runtime[lib["id"]]["warm_start"]
        assert read_cold(game/"data.bin")==updated_without_cache
        engine.deactivate(lib)
        result={"result":"PASS","cold":before,"warm":warm,
                "buffered_and_direct_hits":True,"game_class_stats":True,
                "stop_load":True,"steam_style_replacement_on_origin":True,"in_place_update":True,
                "source_change_invalidates_cache":True}
    finally:
        command("umount",target,check=False)
        if engine is not None and lib is not None:
            if engine.table(lib):
                engine.verify_cache_device(lib)
                engine.cli("-T","-i",str(cid))
            engine.free_loops(lib)
        command("losetup","-d",origin)
    print(json.dumps(result),flush=True)
