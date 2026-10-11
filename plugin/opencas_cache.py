"""Open CAS write-around adapter. Only the selected cache image is initialized."""
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import platform

from block_cache import BlockCache, devno
from cache_scope import scope_rows

VERSION = "26.09.0.1102.release"
LINE_KIB = 64
ASSETS = Path(__file__).resolve().parent / "bin/opencas"


def csv_rows(text):
    return list(csv.DictReader(io.StringIO(text)))


def write_json(path, value):
    tmp = path.with_suffix(".tmp")
    with tmp.open("w") as f:
        json.dump(value, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(path)
    BlockCache.sync_directory(path.parent)


class OpenCasCache(BlockCache):
    def cli(self, *args, **kwargs):
        executable = ASSETS / "casadm"
        if not os.access(executable, os.X_OK):
            os.chmod(executable, 0o755)
        return self.run(executable, *args, **kwargs)

    def cid(self, lib):
        value = int(lib["cas_id"])
        if not 1 <= value <= 16384:
            raise RuntimeError("Invalid Open CAS instance ID.")
        return str(value)

    def mapper(self, lib):
        return "/dev/cas" + self.cid(lib) + "-1"

    def directory(self, lib):
        return self.cache / "opencas" / lib["id"]

    def image(self, lib):
        return self.directory(lib) / "cache"

    def seal_path(self, lib):
        return self.directory(lib) / "clean.json"

    def alias(self, lib, kind):
        return Path("/dev/disk/by-id") / ("deckycache-" + lib["id"] + "-" + kind)

    def link(self, lib, kind, device):
        path = self.alias(lib, kind)
        if path.is_symlink():
            if path.resolve() != Path(device).resolve():
                raise RuntimeError("A cache device alias points to a different device.")
        elif path.exists():
            raise RuntimeError("A cache device alias is already in use.")
        else:
            path.symlink_to(device)
        return str(path)

    def load_modules(self):
        bundle = ASSETS / platform.release()
        try:
            manifest = json.loads((bundle / "manifest.json").read_text())
        except FileNotFoundError:
            raise RuntimeError("Open CAS is unavailable for this SteamOS kernel. Games use the original drive.")
        if manifest["kernel"] != platform.release() or manifest["version"] != VERSION:
            raise RuntimeError("The Open CAS module package does not match this kernel.")
        cli_digest = hashlib.sha256((ASSETS / "casadm").read_bytes()).hexdigest()
        if cli_digest != manifest["sha256"]["casadm"]:
            raise RuntimeError("The Open CAS program failed its integrity check.")
        for name in ("cas_bd", "cas_cache"):
            loaded = Path("/sys/module") / name
            if loaded.exists():
                if (loaded / "version").read_text().strip() != VERSION:
                    raise RuntimeError("A different Open CAS module version is already loaded.")
                continue
            module = bundle / (name + ".ko")
            if hashlib.sha256(module.read_bytes()).hexdigest() != manifest["sha256"][name + ".ko"]:
                raise RuntimeError("The Open CAS module failed its integrity check.")
            if self.run("modinfo", "-F", "vermagic", module).split()[0] != platform.release():
                raise RuntimeError("The Open CAS module was built for a different kernel.")
            self.run("insmod", module)
        os.chmod(ASSETS / "casadm", 0o755)

    def table(self, lib):
        if not Path("/dev/cas_ctrl").exists():
            if Path(self.mapper(lib)).exists():
                raise RuntimeError("The cache device exists but its controller is unavailable.")
            return {}
        rows = csv_rows(self.cli("-L", "-o", "csv", "-b"))
        return next((r for r in rows if r.get("type") == "cache" and r.get("id") == self.cid(lib)), {})

    def stats(self, lib, *args):
        rows = csv_rows(self.cli("-P", "-i", self.cid(lib), *args, "-o", "csv", "-b"))
        if not rows:
            raise RuntimeError("Open CAS did not return cache statistics.")
        return rows[0]

    def verify_cache_device(self, lib):
        row = self.table(lib)
        state = self.m.runtime.get(lib["id"], {})
        if not row or not state.get("cache_loop"):
            raise RuntimeError("The cache instance has no matching saved device state.")
        loop = state["cache_loop"]
        if devno(row["disk"]) != devno(loop):
            raise RuntimeError("The Open CAS instance uses a different cache device.")
        backing = self.run("losetup", "--noheadings", "-O", "BACK-FILE", loop)
        if Path(backing).resolve() != self.image(lib).resolve():
            raise RuntimeError("The cache loop is backed by a different file.")
        if not self.run("losetup", "--noheadings", "-O", "DIO", loop).strip() == "1":
            raise RuntimeError("The cache backing file is not using direct I/O.")
        return row

    def verify(self, lib):
        self.verify_cache_device(lib)
        cache = self.stats(lib, "-f", "conf,usage,req")
        core = self.stats(lib, "-j", "1", "-f", "conf")
        if (cache.get("Write Policy") not in ("wt", "wa", "pt") or cache.get("Status") != "Running"
                or cache.get("Core Devices") != "1" or cache.get("Inactive Core Devices") != "0"
                or int(cache["Cache line size [KiB]"]) != LINE_KIB
                or core.get("Status") != "Active"
                or devno(core["Core Device"]) != devno(self.origin(lib))
                or core.get("Exported Object") != self.mapper(lib)
                or int(core["Core Size [4KiB Blocks]"]) * 4096 != lib["size"]):
            raise RuntimeError("The active Open CAS cache does not match the selected library.")
        return {
            "mode": cache["Write Policy"],
            "used": int(cache["Occupancy [4KiB Blocks]"]) * 4096,
            "total": int(cache["Cache Size [4KiB Blocks]"]) * 4096,
            "dirty": int(cache["Dirty [4KiB Blocks]"]) * 4096,
            "hits": int(cache["Read hits [Requests]"]),
            "misses": int(cache["Read full misses [Requests]"]) + int(cache["Read partial misses [Requests]"]),
        }

    def desired_mode(self):
        return "wa" if self.m.config.get("enabled", True) else "pt"

    def set_mode(self, lib, mode):
        if mode not in ("wa", "pt"):
            raise RuntimeError("Only write-around and bypass modes are supported.")
        stats = self.verify(lib)
        if stats["mode"] == mode:
            return
        if stats["dirty"]:
            raise RuntimeError("Cache has pending writes. Wait for writes to finish.")
        self.cli("-Q", "-i", self.cid(lib), "-c", mode, timeout=120)
        if self.verify(lib)["mode"] != mode:
            raise RuntimeError("Open CAS did not change to the requested mode.")

    def identity(self, lib, origin, data):
        record = super().identity(lib, origin, data)
        record.update(engine="opencas", format_version=VERSION, block_sectors=LINE_KIB * 2,
                      cas_id=int(self.cid(lib)))
        return record

    def free_loops(self, lib):
        if self.table(lib):
            raise RuntimeError("The cache instance is still using its backing file.")
        for loop in self.loops_for(self.image(lib)):
            self.run("losetup", "-d", loop)
        for kind in ("cas", "origin"):
            path = self.alias(lib, kind)
            if path.is_symlink():
                path.unlink()

    def prepare_files(self, lib, origin, allow_reuse):
        directory = self.directory(lib)
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.free_loops(lib)
        data = self.image(lib)
        reusable = False
        try:
            saved = json.loads(self.seal_path(lib).read_text())
            reusable = allow_reuse and saved == self.identity(lib, origin, data)
        except (OSError, ValueError, RuntimeError):
            pass
        self.invalidate(lib)
        if reusable:
            return data, True
        stat = os.statvfs(self.cache)
        count = max(1, len(self.m.config["libraries"]))
        size = min(stat.f_blocks * stat.f_frsize * 9 // 10 // count, lib["size"])
        size = size // (LINE_KIB * 1024) * (LINE_KIB * 1024)
        if size < 64 * 1024**2:
            raise RuntimeError("There is not enough space for an Open CAS cache.")
        # No force option is used. The only initialized device is this owned image.
        with data.open("wb") as f:
            f.truncate(size)
        os.chmod(data, 0o600)
        self.run("fallocate", "-l", size, data, timeout=120)
        write_json(directory / "classes.json", [])
        return data, False

    def checkpoint(self, lib, origin):
        directory = self.directory(lib)
        self.run("sync", "-f", directory)
        write_json(self.seal_path(lib), self.identity(lib, origin, self.image(lib)))

    def activate(self, lib):
        if self.active(lib):
            self.set_mode(lib, self.desired_mode())
            return
        if self.table(lib):
            self.set_mode(lib, self.desired_mode())
            if lib["path"] in self.mounts():
                raise RuntimeError("The library is mounted outside its existing cache.")
            self.run("mount", "-t", lib["fstype"], "-o", lib["options"], self.mapper(lib), lib["path"])
            return
        origin = self.origin(lib)
        current = self.mounts()
        row = current.get(lib["path"])
        if row and devno(row["source"].split("[", 1)[0]) != devno(origin):
            raise RuntimeError("A different drive is mounted at the library location.")
        for target, mount in current.items():
            if target.startswith(lib["path"] + "/"):
                raise RuntimeError("Disable nested mounts before enabling this drive.")
            if mount.get("uuid") == lib["uuid"] and target != lib["path"]:
                raise RuntimeError("This partition is mounted in more than one location.")
        holders = Path("/sys/class/block") / Path(origin).name / "holders"
        if holders.exists() and any(holders.iterdir()):
            raise RuntimeError("The library partition is already used by another storage layer.")
        if self.busy(lib["path"]):
            raise RuntimeError("Close games and wait for Steam updates before enabling this drive.")
        self.load_modules()
        state = dict(lib, engine="opencas")
        self.m.runtime[lib["id"]] = state
        self.m.save_runtime()
        try:
            if row:
                self.run("umount", lib["path"])
            if any(m.get("uuid") == lib["uuid"] for m in self.mounts().values()):
                raise RuntimeError("The library partition is still mounted.")
            data, reused = self.prepare_files(lib, origin, allow_reuse=not row)
            state["warm_start"] = reused
            state["cache_loop"] = self.run("losetup", "--find", "--show", "--direct-io=on", data)
            self.m.save_runtime()
            cache_alias = self.link(lib, "cas", state["cache_loop"])
            origin_alias = self.link(lib, "origin", origin)
            if reused:
                self.cli("-S", "-d", cache_alias, "--load", timeout=120)
            else:
                self.cli("-S", "-i", self.cid(lib), "-d", cache_alias, "-c", "pt", "-x", str(LINE_KIB), timeout=120)
                self.cli("-A", "-i", self.cid(lib), "-j", "1", "-d", origin_alias, timeout=60)
                self.cli("-X", "-n", "seq-cutoff", "-i", self.cid(lib), "-p", "never")
            self.run("udevadm", "settle", "--timeout=15")
            self.set_mode(lib, "pt")
            Path(lib["path"]).mkdir(parents=True, exist_ok=True)
            self.run("mount", "-t", lib["fstype"], "-o", lib["options"], self.mapper(lib), lib["path"])
            if not self.active(lib):
                raise RuntimeError("The library did not mount through Open CAS.")
        except Exception:
            if lib["path"] not in self.mounts():
                if self.table(lib):
                    self.verify_cache_device(lib)
                    self.cli("-T", "-i", self.cid(lib), timeout=120)
                self.free_loops(lib)
                self.m.runtime.pop(lib["id"], None)
                self.m.save_runtime()
                self.mount_original(lib, origin)
            raise

    def deactivate(self, lib, preserve=False):
        origin = self.origin(lib)
        self.invalidate(lib)
        had_mapping = bool(self.table(lib))
        if had_mapping:
            if self.verify(lib)["dirty"]:
                raise RuntimeError("The cache has pending writes and cannot be disconnected.")
            if self.busy(lib["path"]):
                raise RuntimeError("Close games and wait for Steam updates before disabling this drive.")
            mounted = self.mounts().get(lib["path"])
            if mounted:
                if not self.active(lib):
                    raise RuntimeError("The library mount does not match its cache.")
                self.run("umount", lib["path"])
            try:
                self.cli("-T", "-i", self.cid(lib), timeout=120)
            except Exception:
                if mounted and self.table(lib):
                    self.run("mount", "-t", lib["fstype"], "-o", lib["options"], self.mapper(lib), lib["path"])
                raise
        self.free_loops(lib)
        self.m.runtime.pop(lib["id"], None)
        self.m.save_runtime()
        if preserve and had_mapping:
            self.checkpoint(lib, origin)
        elif not preserve and lib["path"] not in self.mounts():
            self.mount_original(lib, origin)

    def clear(self, lib):
        """Invalidate cached blocks online; keep the origin, filesystem and image."""
        if self.verify(lib)["dirty"]:
            raise RuntimeError("Cache has pending writes. Try again when writes finish.")
        # Upstream purge flushes then invalidates mappings. It does not format,
        # remove a core, detach the library or discard sectors on the origin.
        self.cli("--script", "--purge-cache", "--cache-id", self.cid(lib), timeout=120)
        # Concurrent I/O may already refill cache: report measured occupancy,
        # never manufacture a zero counter or remove a game from the list.
        return self.verify(lib)

    def release_allocations(self):
        for directory in (self.cache / "opencas").glob("*"):
            data = directory / "cache"
            if data.exists():
                if self.loops_for(data):
                    raise RuntimeError("An Open CAS allocation is still in use.")
                (directory / "clean.json").unlink(missing_ok=True)
                self.sync_directory(directory)
                with data.open("wb"):
                    pass

    def class_plan(self, lib):
        """Keep old class IDs and restrict new reads to the selected scope."""
        catalog = self.m.catalog([dict(lib, active=True, enabled=True)])
        current = {}
        for game in catalog:
            path = Path(game["path"])
            try:
                if (not path.is_dir() or not path.resolve().is_relative_to(Path(lib["path"]).resolve())
                        or path.stat().st_dev != os.stat(self.mapper(lib)).st_rdev):
                    continue
            except OSError:
                continue
            # Directory I/O itself is metadata, not game file contents.
            # CAS file_size accepts only regular files, excluding directory reads.
            rule = "directory:" + str(path) + "&file_size:gt:0&done"
            if any(c in str(path) for c in "&|,\r\n") or len(rule.encode()) >= 1024:
                continue
            current.setdefault(str(path), []).append(game)
        record = self.directory(lib) / "classes.json"
        saved = json.loads(record.read_text()) if record.exists() else []
        roots = [folder["path"] for folder in self.m.config.get("cache_folders", [])
                 if folder["uuid"] == lib["uuid"]]
        saved, rows = scope_rows(saved, current, self.m.config.get("cache_scope", "drives"), roots)
        return saved, current, rows

    def sync_classes(self, lib):
        saved, current, rows = self.class_plan(lib)
        record = self.directory(lib) / "classes.json"
        output = io.StringIO()
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(["IO class id", "IO class name", "Eviction priority", "Allocation"])
        writer.writerows(rows)
        config = self.directory(lib) / "classes.csv"
        rules = output.getvalue()
        previous = config.read_text() if config.exists() else None
        # A restored CAS retains the rules, but a cold instance must receive them.
        signature = hashlib.sha256(rules.encode()).hexdigest()
        state = self.m.runtime[lib["id"]]
        if previous != rules or state.get("classes_signature") != signature:
            tmp = config.with_suffix(".tmp")
            tmp.write_text(rules)
            tmp.replace(config)
            write_json(record, saved)
            self.cli("--io-class", "--load-config", "-i", self.cid(lib), "-f", config)
            state["classes_signature"] = signature
            self.m.save_runtime()
        return saved, current

    def cached_games(self, libraries):
        return self.cached_usage(libraries)[0]

    def cached_usage(self, libraries):
        result, total, attributed = {}, 0, 0
        for lib in libraries:
            if not lib["active"]:
                continue
            saved, current = self.sync_classes(lib)
            rows = csv_rows(self.cli("-P", "-i", self.cid(lib), "-d", "-f", "conf,usage", "-o", "csv"))
            usage = {int(r["IO class ID"]): int(r["Occupancy [4KiB Blocks]"]) * 4096
                     for r in rows if r.get("IO class ID", "").isdigit()}
            total += sum(usage.values())
            by_path = {}
            for item in saved:
                by_path[item["path"]] = by_path.get(item["path"], 0) + usage.get(item["id"], 0)
            for path, used in by_path.items():
                matches = current.get(path, [])
                if used and matches:
                    attributed += used
                    for game in matches:
                        result[(game["id"], game["mapper"], game["path"])] = dict(game, cached_bytes=used)
        return sorted(result.values(), key=lambda game: game["name"].casefold()), max(0, total - attributed), total
