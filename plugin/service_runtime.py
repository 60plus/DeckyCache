"""Keep the storage runtime available while Decky replaces the plugin directory."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import time

STATE = Path("/home/.deckycache")
RUNTIME = STATE / "runtime"
CURRENT = RUNTIME / "current"
OWNER = RUNTIME / "owner.json"
INTENT = STATE / "update-handoff.json"
SERVICE = Path("/etc/systemd/system/deckycache.service")
FILES = ("cache_service.py", "block_cache.py", "opencas_cache.py",
         "resident_games.py", "compatibility.py", "service_runtime.py", "steam_shortcuts.py", "package.json")


def atomic_json(path, value):
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w") as stream:
        json.dump(value, stream)
        stream.flush()
        os.fsync(stream.fileno())
    tmp.replace(path)


def install_runtime(source):
    import fcntl
    RUNTIME.mkdir(parents=True, mode=0o700, exist_ok=True)
    with (RUNTIME / "install.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _install_runtime(source)


def _install_runtime(source):
    source = Path(source).resolve()
    files = [Path(name) for name in FILES]
    files += sorted(p.relative_to(source) for p in (source / "bin/opencas").rglob("*") if p.is_file())
    digest = hashlib.sha256()
    for name in files:
        digest.update(name.as_posix().encode() + b"\0")
        digest.update(hashlib.sha256((source / name).read_bytes()).digest())
    target = RUNTIME / digest.hexdigest()
    RUNTIME.mkdir(parents=True, mode=0o700, exist_ok=True)
    if not target.exists():
        stage = RUNTIME / (digest.hexdigest() + ".tmp")
        stage.mkdir(mode=0o700, exist_ok=True)
        for name in files:
            destination = stage / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / name, destination)
            with destination.open("rb") as stream:
                os.fsync(stream.fileno())
        stage.rename(target)
    temporary = RUNTIME / "current.new"
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(target, target_is_directory=True)
    temporary.replace(CURRENT)
    atomic_json(OWNER, {"plugin": str(source)})
    fd = os.open(RUNTIME, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return target


def arm_update(artifact, version, digest, source_version):
    atomic_json(INTENT, {"artifact": str(artifact), "version": version, "sha256": digest,
                        "source_version": source_version, "expires": time.time() + 1800,
                        "boot": Path("/proc/sys/kernel/random/boot_id").read_text().strip()})


def preserve_for_install(source_version):
    try:
        intent = json.loads(INTENT.read_text())
        artifact = Path(intent["artifact"])
        return (CURRENT.is_dir() and intent["source_version"] == source_version
                and intent["expires"] > time.time()
                and intent["boot"] == Path("/proc/sys/kernel/random/boot_id").read_text().strip()
                and artifact.parent == STATE / "updates"
                and hashlib.sha256(artifact.read_bytes()).hexdigest() == intent["sha256"])
    except (OSError, ValueError, KeyError, TypeError):
        return False


def finish_update(version):
    try:
        intent = json.loads(INTENT.read_text())
        if intent.get("version") == version or intent.get("expires", 0) < time.time():
            INTENT.unlink(missing_ok=True)
    except (OSError, ValueError, TypeError):
        pass


def owner_missing():
    try:
        owner = Path(json.loads(OWNER.read_text())["plugin"])
        return not (owner / "plugin.json").is_file()
    except (OSError, ValueError, KeyError):
        return False


def cleanup_service(run):
    """Remove only our integration after cache detachment succeeds."""
    run("systemctl", "disable", "deckycache.service")
    SERVICE.unlink(missing_ok=True)
    rule = Path("/etc/udev/rules.d/99-deckycache.rules")
    rule.unlink(missing_ok=True)
    override = rule.with_name("99-steamos-automount.rules")
    if override.exists() and override.read_text().startswith("# Managed by DeckyCache:"):
        override.unlink()
    for action in ("reboot", "poweroff", "halt"):
        path = SERVICE.parent / ("plymouth-" + action + ".service.d") / "90-deckycache-shutdown-order.conf"
        if path.exists() and path.read_text().startswith("# Managed by DeckyCache:"):
            path.unlink()
    run("udevadm", "control", "--reload-rules")
    run("systemctl", "daemon-reload")
