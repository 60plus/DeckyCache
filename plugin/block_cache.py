"""Native dm-cache in writethrough mode; the original filesystem stays local."""
import hashlib
import json
import os
from pathlib import Path

BLOCK_SECTORS = 512  # 256 KiB, not whole files or games.
META_BYTES = 256 * 1024**2


def devno(path):
    device = os.stat(path).st_rdev
    return f"{os.major(device)}:{os.minor(device)}"


def parse_status(text):
    fields = text.split()
    if len(fields) < 17 or fields[2] != "cache":
        raise RuntimeError("The kernel cache is not healthy: " + text)
    s = fields[3:]
    features = s[12:12 + int(s[11])]
    if "writethrough" not in features or "writeback" in features:
        raise RuntimeError("The cache is not in writethrough mode.")
    used, total = map(int, s[3].split("/"))
    if "needs_check" in s or "ro" in s or "Fail" in s:
        raise RuntimeError("The cache metadata needs recovery. The library has not been remounted.")
    return {"used": used * int(s[2]) * 512, "total": total * int(s[2]) * 512,
            "hits": int(s[4]), "misses": int(s[5]), "dirty": int(s[10])}


class BlockCache:
    def __init__(self, manager, command, mounts, tree, flatten, busy, cache):
        self.m, self.run, self.mounts = manager, command, mounts
        self.tree, self.flatten, self.busy, self.cache = tree, flatten, busy, cache

    def name(self, lib):
        return "deckycache-" + lib["id"]

    def mapper(self, lib):
        return "/dev/mapper/" + self.name(lib)

    def origin(self, lib):
        for disk in self.tree():
            if disk.get("serial") == lib["serial"]:
                for part in disk.get("children", []):
                    if part.get("uuid") == lib["uuid"] and part["type"] == "part":
                        if part["size"] != lib["size"]:
                            raise RuntimeError("The library partition size has changed.")
                        return part["path"]
        raise RuntimeError("Connect the selected library drive.")

    def table(self, lib):
        return self.run("dmsetup", "table", self.name(lib), check=False).strip()

    def verify(self, lib):
        fields = self.table(lib).split()
        state = self.m.runtime.get(lib["id"], {})
        if (len(fields) != 12 or fields[:3] != ["0", str(lib["size"] // 512), "cache"]
                or fields[3:6] != [devno(state["meta_loop"]), devno(state["data_loop"]), devno(self.origin(lib))]
                or fields[6:] != [str(BLOCK_SECTORS), "2", "writethrough", "metadata2", "smq", "0"]):
            raise RuntimeError("The active cache does not match the selected drive.")
        return parse_status(self.run("dmsetup", "status", self.name(lib)))

    def active(self, lib):
        row = self.mounts().get(lib["path"])
        try:
            if not row or devno(row["source"].split("[", 1)[0]) != devno(self.mapper(lib)):
                return False
            self.verify(lib)
            return True
        except (OSError, RuntimeError, KeyError):
            return False

    def loops_for(self, path):
        return [line.split(":", 1)[0] for line in self.run("losetup", "-j", path, check=False).splitlines()]

    def free_loops(self, lib):
        directory = self.cache / "blocks" / lib["id"]
        for name in ("metadata", "data"):
            for loop in self.loops_for(directory / name):
                self.run("losetup", "-d", loop)

    def seal_path(self, lib):
        return self.cache / "blocks" / lib["id"] / "clean.json"

    def invalidate(self, lib):
        seal = self.seal_path(lib)
        if seal.exists():
            seal.unlink()
            self.sync_directory(seal.parent)

    @staticmethod
    def sync_directory(path):
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def identity(self, lib, origin, data):
        # ext4 changes this superblock on a normal writable mount, including
        # mount count/time, last write time and filesystem state. Raw-device
        # editing or restoring old filesystem snapshots is not supported.
        with open(origin, "rb", buffering=0) as f:
            f.seek(1024)
            superblock = f.read(1024)
        if len(superblock) != 1024 or superblock[56:58] != b"\x53\xef":
            raise RuntimeError("The library is no longer an ext4 filesystem.")
        return {"version": 1, "uuid": lib["uuid"], "serial": lib["serial"],
                "size": lib["size"], "cache": self.m.config.get("cache"),
                "block_sectors": BLOCK_SECTORS, "data_size": data.stat().st_size,
                "superblock": hashlib.sha256(superblock).hexdigest()}

    def checkpoint(self, lib, origin):
        directory = self.seal_path(lib).parent
        metadata, data = directory / "metadata", directory / "data"
        self.run("cache_check", "-q", metadata, timeout=120)
        record = self.identity(lib, origin, data)
        # Commit the cache backing files before publishing the clean marker.
        self.run("sync", "-f", directory)
        tmp = directory / "clean.tmp"
        with tmp.open("w") as f:
            json.dump(record, f)
            f.flush()
            os.fsync(f.fileno())
        tmp.replace(self.seal_path(lib))
        self.sync_directory(directory)

    def prepare_files(self, lib, origin, allow_reuse):
        directory = self.cache / "blocks" / lib["id"]
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.free_loops(lib)
        data, metadata = directory / "data", directory / "metadata"
        reusable = False
        try:
            saved = json.loads(self.seal_path(lib).read_text())
            reusable = (allow_reuse and metadata.stat().st_size == META_BYTES
                        and saved == self.identity(lib, origin, data))
            if reusable:
                self.run("cache_check", "-q", metadata, timeout=120)
        except (OSError, ValueError, RuntimeError):
            reusable = False
        # A running or crashed mapping must never leave a reusable clean marker.
        self.invalidate(lib)
        if reusable:
            return metadata, data, True
        stat = os.statvfs(self.cache)
        count = max(1, len(self.m.config["libraries"]))
        capacity = (stat.f_blocks * stat.f_frsize * 9 // 10) // count - META_BYTES
        capacity = min(capacity, lib["size"])
        capacity = capacity // (BLOCK_SECTORS * 512) * (BLOCK_SECTORS * 512)
        if capacity < 64 * 1024**2:
            raise RuntimeError("There is not enough space for a cache on this SSD.")
        for path, size in ((data, capacity), (metadata, META_BYTES)):
            with path.open("wb") as f:
                f.truncate(size)
            self.run("fallocate", "-l", str(size), path, timeout=120)
        with metadata.open("r+b") as f:
            f.write(bytes(4096))
            f.flush()
            os.fsync(f.fileno())
        return metadata, data, False

    def mount_original(self, lib, origin):
        Path(lib["path"]).mkdir(parents=True, exist_ok=True)
        self.run("mount", "-t", lib["fstype"], "-o", lib["options"], origin, lib["path"])

    def activate(self, lib):
        if self.active(lib):
            return
        if self.table(lib):
            self.verify(lib)
            row = self.mounts().get(lib["path"])
            if row:
                raise RuntimeError("The library is mounted outside its existing cache. Close Steam and retry.")
            self.run("mount", "-t", lib["fstype"], "-o", lib["options"], self.mapper(lib), lib["path"])
            return
        origin = self.origin(lib)
        current = self.mounts()
        row = current.get(lib["path"])
        if row and devno(row["source"].split("[", 1)[0]) != devno(origin):
            raise RuntimeError("A different drive is mounted at the library location.")
        for target, mount in current.items():
            if target.startswith(lib["path"] + "/"):
                raise RuntimeError("The library drive has nested mounts. Disable them before enabling cache.")
            if mount.get("uuid") == lib["uuid"] and target != lib["path"]:
                raise RuntimeError("This partition is mounted in more than one location.")
        holders = Path("/sys/class/block") / Path(origin).name / "holders"
        if holders.exists() and any(holders.iterdir()):
            raise RuntimeError("The library partition is already used by another storage layer.")
        if self.busy(lib["path"]):
            raise RuntimeError("Close games and wait for Steam updates before enabling this drive.")
        self.run("modprobe", "dm-cache")
        self.run("modprobe", "dm-cache-smq")
        state = dict(lib)
        self.m.runtime[lib["id"]] = state
        self.m.save_runtime()
        try:
            if row:
                self.run("umount", lib["path"])
            # Recheck after unmount; never cache an origin still mounted through an alias.
            if any(m.get("uuid") == lib["uuid"] for m in self.mounts().values()):
                raise RuntimeError("The library partition is still mounted.")
            metadata, data, reused = self.prepare_files(lib, origin, allow_reuse=not row)
            state["warm_start"] = reused
            for key, file in (("meta_loop", metadata), ("data_loop", data)):
                state[key] = self.run("losetup", "--find", "--show", "--direct-io=on", file)
                self.m.save_runtime()
            table = (f"0 {lib['size'] // 512} cache {state['meta_loop']} {state['data_loop']} "
                     f"{origin} {BLOCK_SECTORS} 2 writethrough metadata2 smq 0")
            self.run("dmsetup", "create", self.name(lib), "--table", table)
            self.run("udevadm", "settle")
            self.verify(lib)
            Path(lib["path"]).mkdir(parents=True, exist_ok=True)
            self.run("mount", "-t", lib["fstype"], "-o", lib["options"], self.mapper(lib), lib["path"])
            if not self.active(lib):
                raise RuntimeError("The library did not mount through the block cache.")
        except Exception as error:
            if lib["path"] not in self.mounts():
                if self.table(lib):
                    self.run("dmsetup", "remove", self.name(lib))
                self.free_loops(lib)
                self.m.runtime.pop(lib["id"], None)
                self.m.save_runtime()
                try:
                    self.mount_original(lib, origin)
                except Exception as restore_error:
                    raise RuntimeError(f"{error}; restoring the original mount also failed: {restore_error}") from error
            raise

    def deactivate(self, lib, preserve=False):
        origin = self.origin(lib)
        self.invalidate(lib)
        had_mapping = bool(self.table(lib))
        if self.table(lib):
            status = self.verify(lib)
            if status["dirty"]:
                raise RuntimeError("The cache has pending writes. It cannot be disconnected yet.")
            if self.busy(lib["path"]):
                raise RuntimeError("Close games and wait for Steam updates before disabling this drive.")
            mounted = self.mounts().get(lib["path"])
            if mounted:
                if not self.active(lib):
                    raise RuntimeError("The library mount does not match its cache.")
                self.run("umount", lib["path"])
            try:
                self.run("dmsetup", "remove", self.name(lib))
            except Exception:
                if mounted:
                    self.run("mount", "-t", lib["fstype"], "-o", lib["options"], self.mapper(lib), lib["path"])
                raise
        self.free_loops(lib)
        self.m.runtime.pop(lib["id"], None)
        self.m.save_runtime()
        if preserve:
            if had_mapping:
                self.checkpoint(lib, origin)
        elif lib["path"] not in self.mounts():
            self.mount_original(lib, origin)

    def release_allocations(self):
        # Called only after all our mappings have been removed.
        for directory in (self.cache / "blocks").glob("*"):
            if not directory.is_dir():
                continue
            (directory / "clean.json").unlink(missing_ok=True)
            self.sync_directory(directory)
            for name in ("data", "metadata"):
                path = directory / name
                if path.exists():
                    if self.loops_for(path):
                        raise RuntimeError("A cache allocation is still in use.")
                    with path.open("wb"):
                        pass
