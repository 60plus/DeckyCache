"""Small Decky bridge. The storage worker runs in the system mount namespace."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import decky

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from compatibility import compatibility, plugin_version
from updates import check_update, download_update
SERVICE = Path("/etc/systemd/system/deckycache.service")
UDEV_RULE = Path("/etc/udev/rules.d/99-deckycache.rules")


def system_env():
    env = os.environ.copy()
    for key in ("LD_LIBRARY_PATH", "LD_PRELOAD", "PYTHONHOME", "PYTHONPATH"):
        env.pop(key, None)
    env["PATH"] = "/usr/bin:/usr/sbin:/bin:/sbin"
    env["LC_ALL"] = "C"
    return env


class Plugin:
    def __init__(self):
        self._candidate = None
        self._update_lock = asyncio.Lock()

    async def _main(self):
        try:
            await asyncio.to_thread(self._install_service)
        except Exception:
            # Keep the panel and updater available even if storage cannot start.
            decky.logger.exception("DeckyCache service could not start")

    async def check_updates(self):
        async with self._update_lock:
            try:
                self._candidate = None
                self._candidate = await asyncio.to_thread(check_update, plugin_version())
                return {"ok": True, "data": {"installed": plugin_version(),
                        "compatibility": compatibility(), "candidate": self._candidate}}
            except Exception as error:
                return {"ok": False, "error": str(error)}

    async def prepare_update(self):
        async with self._update_lock:
            try:
                if not self._candidate:
                    raise RuntimeError("Check for a compatible update first.")
                candidate = dict(self._candidate)
                data = await asyncio.to_thread(download_update, candidate)
                folder = Path("/home/.deckycache/updates")
                folder.mkdir(mode=0o700, parents=True, exist_ok=True)
                target = folder / ("DeckyCache-" + candidate["version"] + "-" + candidate["sha256"][:16] + ".zip")
                temporary = target.with_suffix(".tmp")
                with temporary.open("wb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.chmod(temporary, 0o600)
                temporary.replace(target)
                # Verification happens before changing the running cache.
                result = await self.request({"action": "prepare-update"})
                if not result.get("ok"):
                    raise RuntimeError(result["error"])
                return {"ok": True, "data": {"artifact": "file://" + str(target),
                        "version": candidate["version"], "sha256": candidate["sha256"]}}
            except Exception as error:
                return {"ok": False, "error": str(error)}

    def _install_service(self):
        unit = (
            "[Unit]\nDescription=DeckyCache block cache\nAfter=local-fs.target\nRequiresMountsFor=/home\nBefore=display-manager.service user@1000.service udisks2.service\n"
            "[Service]\nType=simple\n"
            f'ExecStartPre=/usr/bin/python3 "{HERE / "cache_service.py"}" restore\n'
            f'ExecStart=/usr/bin/python3 "{HERE / "cache_service.py"}" watch\n'
            f'ExecStop=/usr/bin/python3 "{HERE / "cache_service.py"}" checkpoint\n'
            "Restart=on-failure\nRestartSec=5\nTimeoutStartSec=180\nTimeoutStopSec=180\n"
            "[Install]\nWantedBy=multi-user.target\n"
        )
        if not SERVICE.exists() or SERVICE.read_text() != unit:
            SERVICE.write_text(unit)
        self._request({"action": "rules"})
        subprocess.run(["systemctl", "daemon-reload"], check=True, env=system_env())
        subprocess.run(["systemctl", "enable", "deckycache.service"], check=True, env=system_env())
        config_path = Path("/home/.deckycache/config.json")
        config = json.loads(config_path.read_text()) if config_path.exists() else {}
        verb = "restart" if config.get("enabled") is False else "start"
        subprocess.run(["systemctl", verb, "deckycache.service"], check=True, env=system_env())

    async def request(self, payload):
        try:
            return await asyncio.to_thread(self._request, payload)
        except Exception as e:
            decky.logger.exception("DeckyCache request failed")
            return {"ok": False, "error": str(e)}

    def _request(self, payload):
        p = subprocess.run(
            ["nsenter", "-t", "1", "-m", "--", "/usr/bin/python3", str(HERE / "cache_service.py"), "request"],
            input=json.dumps(payload) + "\n", text=True, capture_output=True, timeout=240, env=system_env())
        if p.returncode:
            raise RuntimeError(p.stderr.strip() or "Could not read cache status.")
        return json.loads(p.stdout)

    async def _unload(self):
        # The independent worker keeps active game paths intact on a Decky reload.
        pass

    async def _uninstall(self):
        subprocess.run(["systemctl", "stop", "deckycache.service"], check=False, env=system_env())
        result = await self.request({"action": "stop"})
        if result.get("ok"):
            subprocess.run(["systemctl", "disable", "deckycache.service"], check=False, env=system_env())
            SERVICE.unlink(missing_ok=True)
            UDEV_RULE.unlink(missing_ok=True)
            override = UDEV_RULE.with_name("99-steamos-automount.rules")
            if override.exists() and override.read_text().startswith("# Managed by DeckyCache:"):
                override.unlink()
            for action in ("reboot", "poweroff", "halt"):
                path = SERVICE.parent / ("plymouth-" + action + ".service.d") / "90-deckycache-shutdown-order.conf"
                if path.exists() and path.read_text().startswith("# Managed by DeckyCache:"):
                    path.unlink()
            subprocess.run(["udevadm", "control", "--reload-rules"], check=True, env=system_env())
            subprocess.run(["systemctl", "daemon-reload"], check=False, env=system_env())
        else:
            subprocess.run(["systemctl", "start", "deckycache.service"], check=False, env=system_env())
            raise RuntimeError(result["error"])
