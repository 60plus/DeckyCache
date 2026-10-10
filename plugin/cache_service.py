"""Whole-partition writethrough cache; the original library remains on the HDD."""
from __future__ import annotations
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import subprocess
import sys
import time
from block_cache import BlockCache
from opencas_cache import OpenCasCache
from resident_games import resident_games, ScanChanged

STATE = Path("/home/.deckycache")
RUN = Path("/run/deckycache")
CACHE = RUN / "ssd"
HERE = Path(__file__).resolve().parent
USER = pwd.getpwnam("deck")
STEAM = Path(USER.pw_dir) / ".local/share/Steam"


def command(*args, timeout=30, input=None, check=True):
    p = subprocess.run([str(a) for a in args], input=input, text=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout,
                       env={**os.environ, "LC_ALL": "C"})
    if check and p.returncode:
        raise RuntimeError(p.stderr.strip() or p.stdout.strip() or f"{args[0]}: exit code {p.returncode}")
    return p.stdout.strip()


def read_json(path, default):
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        return default


def save_json(path, value):
    path = Path(path)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w") as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(path)
    BlockCache.sync_directory(path.parent)


def mounts():
    data = json.loads(command("findmnt", "-J", "-l", "-o", "TARGET,SOURCE,FSTYPE,UUID,OPTIONS"))
    return {m["target"]: m for m in data.get("filesystems", [])}


def backing(path):
    rows = json.loads(command("findmnt", "-J", "-T", path, "-o", "TARGET,SOURCE,FSTYPE,UUID"))
    return rows["filesystems"][0]


def tree():
    return json.loads(command("lsblk", "-J", "-b", "-o",
        "PATH,NAME,SIZE,TYPE,FSTYPE,LABEL,UUID,MOUNTPOINTS,MODEL,SERIAL,ROTA"))["blockdevices"]


def flatten(node):
    yield node
    for child in node.get("children", []):
        yield from flatten(child)


def disk_token(disk):
    value = "|".join(str(disk.get(k) or "") for k in ("path", "model", "serial", "size"))
    return hashlib.sha256(value.encode()).hexdigest()


def vdf_value(text, key):
    match = re.search(r'"' + re.escape(key) + r'"\s*"((?:\\.|[^"])*)"', text, re.I)
    return match.group(1).replace(r"\\", "\\").replace(r'\"', '"') if match else ""


def busy(path):
    """Do not put a new mount over files a running game/updater already opened."""
    prefix = str(path).rstrip("/") + "/"
    for proc in Path("/proc").glob("[0-9]*"):
        if proc.name == str(os.getpid()):
            continue
        try:
            refs = list((proc / "fd").iterdir()) + [proc / "cwd"]
            for ref in refs:
                try:
                    target = os.readlink(ref)
                    if target == str(path) or target.startswith(prefix):
                        return True
                except OSError:
                    pass
            for line in (proc / "maps").read_text().splitlines():
                fields = line.split(None, 5)
                if len(fields) == 6 and fields[5].startswith(prefix):
                    return True
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            pass
    return False


class Manager:
    def __init__(self):
        self.config = read_json(STATE / "config.json", {"version": 4, "engine": "opencas", "cache": None, "libraries": []})
        self.runtime = read_json(RUN / "mounts.json", {})
        self.errors = read_json(RUN / "errors.json", {})
        if self.config["version"] < 3:
            if self.runtime or (RUN / "server").exists():
                raise RuntimeError("Disable the previous NFS folder cache before upgrading.")
            self.config.update(version=3, libraries=[])
            self.config.pop("shaders", None)
        engine = OpenCasCache if self.config.get("engine") == "opencas" else BlockCache
        self.block = engine(self, command, mounts, tree, flatten, busy, CACHE)

    def save(self):
        save_json(STATE / "config.json", self.config)
        self.sync_rules()

    def save_runtime(self):
        save_json(RUN / "mounts.json", self.runtime)

    def sync_shutdown_order(self):
        # Plymouth otherwise takes the display while Gamescope is still exiting.
        # Wait for the user session and the clean cache checkpoint before showing
        # the shutdown splash. This does not alter the startup order or drivers.
        enabled = bool(self.config["libraries"]) and Path("/sys/module/nvidia").is_dir()
        marker = "# Managed by DeckyCache: finish session and cache before shutdown splash.\n"
        content = marker + "[Unit]\nAfter=user@" + str(USER.pw_uid) + ".service deckycache.service\n"
        changed = False
        for action in ("reboot", "poweroff", "halt"):
            path = Path("/etc/systemd/system") / ("plymouth-" + action + ".service.d") / "90-deckycache-shutdown-order.conf"
            old = path.read_text() if path.exists() else ""
            if enabled:
                if old and not old.startswith(marker):
                    raise RuntimeError("A custom shutdown-order file already exists. It has not been changed.")
                if old != content:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    tmp = path.with_suffix(".tmp")
                    tmp.write_text(content)
                    tmp.replace(path)
                    changed = True
            elif old.startswith(marker):
                path.unlink()
                changed = True
        if changed:
            command("systemctl", "daemon-reload")

    def sync_rules(self):
        self.sync_shutdown_order()
        rule = Path("/etc/udev/rules.d/99-deckycache.rules")
        vendor = Path("/usr/lib/udev/rules.d/99-steamos-automount.rules")
        override = Path("/etc/udev/rules.d/99-steamos-automount.rules")
        legacy = rule.with_name("99-zz-deckycache.rules")
        marker = "# Managed by DeckyCache: skip selected cache/library devices.\n"
        uuids = [lib["uuid"] for lib in self.config["libraries"]]
        if self.config["cache"]:
            uuids.append(self.config["cache"]["uuid"])
        # A fresh plugin with no selected disks must not alter automount rules
        # or replay block-device events. Existing managed rules still need sync.
        if (not uuids and not rule.exists() and not legacy.exists()
                and not (override.exists() and override.read_text().startswith(marker))):
            return
        # Clear properties left by an earlier selection, then protect selected
        # origins from UDisks automounting them before cache restoration.
        lines = ['SUBSYSTEM=="block", ENV{DECKYCACHE_MANAGED}=="1", ENV{UDISKS_IGNORE}="", ENV{DECKYCACHE_MANAGED}=""',
                 'SUBSYSTEM=="block", ENV{DM_NAME}=="deckycache-*", ENV{UDISKS_IGNORE}="1", ENV{DECKYCACHE_MANAGED}="1"']
        for lib in self.config['libraries']:
            if self.config.get('engine') == 'opencas' and lib.get('cas_id'):
                lines.append('SUBSYSTEM=="block", KERNEL=="cas' + str(int(lib['cas_id'])) + '-*", ENV{UDISKS_IGNORE}="1", ENV{DECKYCACHE_MANAGED}="1"')
        for uuid in sorted(set(uuids)):
            if not re.fullmatch(r"[a-fA-F0-9-]+", uuid):
                raise RuntimeError("Invalid filesystem UUID in the cache configuration.")
            lines.append('SUBSYSTEM=="block", ENV{ID_FS_UUID}=="' + uuid +
                         '", ENV{UDISKS_IGNORE}="1", ENV{DECKYCACHE_MANAGED}="1"')
        # Valve explicitly runs fsck + Mount even with UDISKS_IGNORE.
        # Keep the vendor rule intact except for one guard for our devices.
        override_changed = False
        if vendor.exists():
            old = override.read_text() if override.exists() else ""
            if old and not old.startswith(marker):
                raise RuntimeError("A custom SteamOS automount rule already exists. It has not been changed.")
            original = vendor.read_text()
            if 'LABEL="steamos_automount_end"' not in original:
                raise RuntimeError("This SteamOS automount rule version is not supported.")
            guarded = marker + 'ENV{DECKYCACHE_MANAGED}=="1", GOTO="steamos_automount_end"\n' + original
            override_changed = old != guarded
            if override_changed:
                override.write_text(guarded)
        content = "\n".join(lines) + "\n"
        if override_changed or not rule.exists() or rule.read_text() != content:
            rule.parent.mkdir(parents=True, exist_ok=True)
            rule.write_text(content)
            legacy.unlink(missing_ok=True)
            command("udevadm", "control", "--reload-rules")
            command("udevadm", "trigger", "--action=change", "--subsystem-match=block")
            command("udevadm", "settle")

    def devices(self):
        result = []
        source_uuids = {x["uuid"] for x in self.config["libraries"]}
        for d in tree():
            if d["type"] != "disk" or d.get("rota") or not d.get("serial"):
                continue
            nodes = list(flatten(d))
            reasons = []
            for n in nodes:
                for m in n.get("mountpoints", []):
                    if m and (m in ("/", "/home", "/var", "/boot", "/efi", "/esp", "[SWAP]")
                              or m.startswith(("/usr", "/etc", "/opt", "/root"))):
                        reasons.append("System drive")
                if n.get("uuid") in source_uuids:
                    reasons.append("This drive contains a selected library")
                holders = Path("/sys/class/block") / n["name"] / "holders"
                if holders.exists() and any(holders.iterdir()):
                    reasons.append("This drive is used by another storage layer")
            prepared = next((n for n in nodes if n.get("fstype") == "ext4"
                             and n.get("label") in ("deckycache", "DeckyCache")), None)
            result.append({"path": d["path"], "model": (d.get("model") or d["name"]).strip(),
                           "serial": d["serial"], "size": d["size"], "token": disk_token(d),
                           "blocked": "; ".join(sorted(set(reasons))),
                           "reusable": bool(prepared), "partition": prepared["path"] if prepared else None})
        return result

    def checked_disk(self, path, token):
        item = next((d for d in self.devices() if d["path"] == path), None)
        if not item or item["token"] != token:
            raise RuntimeError("The drive list has changed. Refresh the panel and select the drive again.")
        if item["blocked"]:
            raise RuntimeError(item["blocked"])
        return item

    def cache_partition(self):
        cfg = self.config["cache"]
        if not cfg:
            return None
        for d in tree():
            if d.get("serial") == cfg["serial"]:
                for n in flatten(d):
                    if n.get("uuid") == cfg["uuid"] and n.get("fstype") == "ext4":
                        return n["path"]
        return None

    def select_disk(self, path, token, erase=False):
        item = self.checked_disk(path, token)
        self.stop_all()
        nodes = list(flatten(next(d for d in tree() if d["path"] == path)))
        mounted = [m for n in nodes for m in n.get("mountpoints", []) if m]
        for m in sorted(mounted, key=len, reverse=True):
            if not m.startswith(("/run/media/", "/media/", str(CACHE))):
                raise RuntimeError(f"The drive is mounted at {m}. Unmount it before setup.")
            if busy(m):
                raise RuntimeError("The drive is in use. Close files or applications using it.")
            command("umount", m)
        self.checked_disk(path, token)
        if erase:
            command("wipefs", "--all", path)
            command("sfdisk", "--wipe", "always", path, input="label: gpt\n\n,,L\n")
            command("udevadm", "settle")
            current = next(d for d in tree() if d["path"] == path)
            parts = [n for n in current.get("children", []) if n["type"] == "part"]
            if len(parts) != 1:
                raise RuntimeError("Could not detect the new cache partition.")
            partition = parts[0]["path"]
            command("mkfs.ext4", "-F", "-m", "0", "-L", "deckycache", partition, timeout=180)
            command("udevadm", "settle")
        else:
            if not item["reusable"]:
                raise RuntimeError("This drive is not set up for cache. Select Format and use.")
            partition = item["partition"]
        uuid = command("blkid", "-s", "UUID", "-o", "value", partition)
        self.config["cache"] = {"uuid": uuid, "serial": item["serial"], "model": item["model"]}
        self.save()
        self.reconcile()

    def ensure_cache(self):
        part = self.cache_partition()
        if not part:
            raise RuntimeError("Connect the selected cache SSD/NVMe.")
        current = mounts().get(str(CACHE))
        if current and current["uuid"] != self.config["cache"]["uuid"]:
            raise RuntimeError("A different drive is mounted at the cache location.")
        if not current:
            CACHE.mkdir(exist_ok=True)
            command("mount", "-t", "ext4", "-o", "nosuid,nodev,noatime", part, CACHE)
        (CACHE / "blocks").mkdir(mode=0o700, exist_ok=True)
        (CACHE / ".deckycache-v3").touch()

    def active(self, lib):
        return self.block.active(lib)

    def activate(self, lib):
        self.block.activate(lib)

    def deactivate(self, lib):
        self.block.deactivate(lib)

    def stop_all(self, preserve=False):
        targets = dict(self.runtime)
        if not preserve:
            if self.config["cache"] and self.cache_partition():
                self.ensure_cache()
            targets.update({lib["id"]: lib for lib in self.config["libraries"]})
        for lib in list(targets.values()):
            self.block.deactivate(lib, preserve=preserve)
        if str(CACHE) in mounts():
            command("umount", CACHE)

    def volume_candidates(self):
        found = {}
        configured = {lib["uuid"]: lib for lib in self.config["libraries"]}
        for disk in tree():
            nodes = list(flatten(disk))
            if not disk.get("serial") or disk["type"] != "disk":
                continue
            if self.config["cache"] and disk["serial"] == self.config["cache"]["serial"]:
                continue
            if any(m and (m in ("/", "/home", "/var", "/boot", "/efi", "/esp", "[SWAP]")
                          or m.startswith(("/usr", "/etc", "/opt", "/root")))
                   for n in nodes for m in n.get("mountpoints", [])):
                continue
            for part in disk.get("children", []):
                # Start with ordinary ext4 data partitions; no system or multi-device filesystems.
                if part["type"] != "part" or part.get("fstype") != "ext4" or not part.get("uuid"):
                    continue
                previous = configured.get(part["uuid"])
                paths = [m for n in flatten(part) for m in n.get("mountpoints", [])
                         if m and m.startswith(("/run/media/", "/media/", "/mnt/"))]
                path = previous["path"] if previous else next(iter(paths), None)
                if not path:
                    continue
                row = mounts().get(path, {})
                found[part["uuid"]] = previous or {
                    "id": hashlib.sha256((disk["serial"] + ":" + part["uuid"]).encode()).hexdigest()[:16],
                    "uuid": part["uuid"], "serial": disk["serial"], "size": part["size"],
                    "path": path, "fstype": "ext4", "options": row.get("options", "rw,relatime"),
                    "kind": "volume", "name": part.get("label") or disk.get("model", "").strip() or Path(path).name,
                    "folders": [],
                }
        return list(found.values())

    def set_library(self, path, enabled):
        found = next((x for x in self.config["libraries"] if x["path"] == path), None)
        if not enabled and not found:
            return
        if enabled:
            lib = next((x for x in self.volume_candidates() if x["path"] == path), None)
            if not lib:
                raise RuntimeError("Choose an ext4 data partition on a separate drive. System drives cannot be cached.")
            if not self.config["cache"]:
                raise RuntimeError("Choose a cache SSD/NVMe first.")
            if found:
                return
        # Changing the selection redistributes SSD capacity. Stop only when idle.
        if any(busy(x["path"]) for x in self.config["libraries"]):
            raise RuntimeError("Close games and wait for Steam updates before changing cache drives.")
        for current in list(self.runtime.values()):
            self.deactivate(current)
        self.ensure_cache()
        self.block.release_allocations()
        if enabled:
            if self.config.get("engine") == "opencas":
                ids = {x.get("cas_id") for x in self.config["libraries"]}
                lib["cas_id"] = next(i for i in range(1001, 16385) if i not in ids)
            self.config["libraries"].append(lib)
        else:
            self.config["libraries"].remove(found)
        self.save()
        self.reconcile()

    def reconcile(self):
        self.errors = {}
        if not self.config["cache"]:
            return
        try:
            self.ensure_cache()
        except Exception as e:
            self.errors["cache"] = str(e)
            if not self.cache_partition():
                for lib in self.config["libraries"]:
                    try:
                        if not self.block.table(lib) and lib["path"] not in mounts():
                            self.block.mount_original(lib, self.block.origin(lib))
                    except Exception as fallback_error:
                        self.errors[lib["id"]] = str(fallback_error)
            save_json(RUN / "errors.json", self.errors)
            return
        for lib in self.config["libraries"]:
            try:
                self.activate(lib)
                if isinstance(self.block, OpenCasCache):
                    try:
                        self.block.sync_classes(lib)
                    except Exception as tracking_error:
                        print("Game classification: " + str(tracking_error), file=sys.stderr, flush=True)
            except Exception as e:
                self.errors[lib["id"]] = str(e)
                # Missing module/cache at boot must not make the HDD library disappear.
                try:
                    if not self.block.table(lib) and lib["path"] not in mounts():
                        self.block.mount_original(lib, self.block.origin(lib))
                except Exception as fallback_error:
                    self.errors[lib["id"]] += "; " + str(fallback_error)
        save_json(RUN / "errors.json", self.errors)

    def libraries(self):
        result = {x["uuid"]: dict(x, enabled=True, active=self.active(x),
                  error=self.errors.get(x["id"], "")) for x in self.config["libraries"]}
        for lib in self.volume_candidates():
            result.setdefault(lib["uuid"], dict(lib, enabled=False, active=False, error=""))
        return list(result.values())

    def game_folders(self, libraries):
        steam_roots = [STEAM / "steamapps"]
        try:
            content = (STEAM / "steamapps/libraryfolders.vdf").read_text()
            steam_roots += [Path(m.replace(r"\\", "\\")) / "steamapps"
                            for m in re.findall(r'"path"\s*"([^"]+)"', content)]
        except OSError:
            pass
        result = {}
        for lib in libraries:
            if not lib["active"]:
                continue
            base = Path(lib["path"])
            candidates = steam_roots + [base / "steamapps", base / "SteamLibrary/steamapps"]
            for path in candidates:
                if not path.is_dir() or not path.is_relative_to(base):
                    continue
                result[str(path)] = {"path": str(path), "kind": "steam" if path.name == "steamapps" else "folder",
                                     "active": True, "enabled": True, "mapper": self.block.mapper(lib)}
        return list(result.values())

    def games(self, libraries):
        games = []
        for lib in libraries:
            if not lib["enabled"] or not lib["active"]:
                continue
            root = Path(lib["path"])
            if lib["kind"] == "steam":
                for manifest in root.glob("appmanifest_*.acf"):
                    try:
                        content = manifest.read_text()
                        appid, name = vdf_value(content, "appid"), vdf_value(content, "name")
                        if not appid.isdigit() or not name or name.startswith(("Proton", "Steam Linux", "Steamworks")):
                            continue
                        if not (int(vdf_value(content, "StateFlags") or "0") & 4):
                            continue
                        install = vdf_value(content, "installdir")
                        if install:
                            games.append({"id": appid, "name": name, "steam": True,
                                          "path": str(root / "common" / install), "mapper": lib["mapper"]})
                    except (OSError, ValueError):
                        continue
        return sorted({g["id"]: g for g in games}.values(), key=lambda g: g["name"].casefold())

    def status(self, include_games=True):
        libs = self.libraries()
        usage = None
        if self.config["cache"] and str(CACHE) in mounts():
            stats = [self.block.verify(lib) for lib in libs if lib["active"]]
            if stats:
                usage = {"total": sum(x["total"] for x in stats), "used": sum(x["used"] for x in stats),
                         "hits": sum(x["hits"] for x in stats), "misses": sum(x["misses"] for x in stats)}
        games, games_state = [], "updating"
        if include_games:
            try:
                if isinstance(self.block, OpenCasCache):
                    games = self.block.cached_games(libs)
                else:
                    games = resident_games(self, libs, self.games(self.game_folders(libs)))
                games_state = "ready"
            except ScanChanged:
                pass  # Do not present an old list during a cache migration/update.
            except (OSError, ValueError, KeyError, RuntimeError, subprocess.TimeoutExpired) as error:
                print("Cached game inspection: " + str(error), file=sys.stderr, flush=True)
                games_state = "unavailable"
        return {"engine": self.config.get("engine", "dm-cache"),
                "cache": self.config["cache"], "devices": self.devices(), "usage": usage,
                "libraries": libs, "games": games, "games_state": games_state,
                "error": self.errors.get("cache", "")}

    def migrate_opencas(self):
        if isinstance(self.block, OpenCasCache):
            self.reconcile()
            return
        if any(busy(lib["path"]) for lib in self.config["libraries"]):
            raise RuntimeError("Close games and wait for Steam updates before changing the cache engine.")
        candidate = OpenCasCache(self, command, mounts, tree, flatten, busy, CACHE)
        # Verify the exact-kernel bundle before touching the old cache.
        candidate.load_modules()
        if self.config["cache"]:
            self.ensure_cache()
            for lib in self.config["libraries"]:
                self.block.deactivate(lib)
            self.block.release_allocations()
        self.config.update(version=4, engine="opencas")
        for index, lib in enumerate(self.config["libraries"], 1001):
            lib["cas_id"] = index
        self.block = candidate
        self.save()
        self.reconcile()

    def clear_cache(self, request):
        if request.get("confirmed") is not True:
            raise RuntimeError("Confirm clearing all cached data first.")
        cache = self.config.get("cache")
        if not cache or request.get("cache_uuid") != cache["uuid"]:
            raise RuntimeError("The cache drive changed. Open the confirmation again.")
        if not isinstance(self.block, OpenCasCache):
            raise RuntimeError("Clearing cache is supported by the Open CAS engine.")
        libraries = self.config["libraries"]
        if not libraries:
            raise RuntimeError("No active cache to clear.")
        # Check every selected partition before purging any of them.
        for lib in libraries:
            if not self.active(lib):
                raise RuntimeError("Connect all selected library drives before clearing cache.")
            if self.block.verify(lib)["dirty"]:
                raise RuntimeError("Cache has pending writes. Try again when writes finish.")
        cleared = 0
        for lib in libraries:
            try:
                self.block.clear(lib)
                cleared += 1
            except Exception as error:
                raise RuntimeError(
                    f"Cleared {cleared} of {len(libraries)} library caches. "
                    f"Could not finish clearing {lib.get('name', lib['id'])}: {error}"
                ) from error

    def action(self, request):
        action = request["action"]
        if action in ("format", "reuse"):
            self.select_disk(request["path"], request["token"], action == "format")
        elif action == "clear-cache":
            self.clear_cache(request)
        elif action == "library":
            self.set_library(request["path"], bool(request["enabled"]))
        elif action == "migrate-opencas":
            self.migrate_opencas()
        elif action == "reconcile":
            self.reconcile()
        elif action in ("stop", "checkpoint"):
            self.stop_all(preserve=action == "checkpoint")
        elif action == "rules":
            self.sync_rules()
        elif action != "status":
            raise RuntimeError("Unknown operation.")
        return self.status(include_games=action in ("status", "clear-cache"))


def locked_action(request):
    STATE.mkdir(mode=0o700, exist_ok=True)
    RUN.mkdir(mode=0o700, exist_ok=True)
    with (RUN / "lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        # A request may have waited behind checkpoint after watch checked the
        # marker. Recheck under the lock so it cannot remount a stopped cache.
        if request.get("action") in ("format", "reuse", "library", "reconcile", "migrate-opencas", "clear-cache") and (RUN / "stopping").exists():
            raise RuntimeError("Cache is stopping. Start the cache service before changing drives.")
        return Manager().action(request)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("watch", "request", "stop", "checkpoint", "restore", "rules"))
    args = parser.parse_args()
    if args.mode in ("stop", "checkpoint"):
        RUN.mkdir(mode=0o700, exist_ok=True)
        (RUN / "stopping").touch()
        locked_action({"action": args.mode})
    elif args.mode == "rules":
        locked_action({"action": "rules"})
    elif args.mode == "restore":
        RUN.mkdir(mode=0o700, exist_ok=True)
        (RUN / "stopping").unlink(missing_ok=True)
        locked_action({"action": "rules"})
        # Boot must finish restoration before Steam/user sessions are started.
        # Allow udev a bounded time to discover the configured disks.
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            manager = Manager()
            try:
                if not manager.config["cache"]:
                    break
                if manager.cache_partition():
                    for lib in manager.config["libraries"]:
                        manager.block.origin(lib)
                    break
            except RuntimeError:
                pass
            time.sleep(1)
        locked_action({"action": "reconcile"})
    elif args.mode == "watch":
        while True:
            try:
                if not (RUN / "stopping").exists():
                    locked_action({"action": "reconcile"})
            except Exception as e:
                print(str(e), file=sys.stderr, flush=True)
            time.sleep(10)
    else:
        try:
            print(json.dumps({"ok": True, "data": locked_action(json.loads(sys.stdin.readline()))}))
        except Exception as e:
            print(json.dumps({"ok": False, "error": str(e)}))
