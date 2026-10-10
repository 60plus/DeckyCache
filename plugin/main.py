"""Small Decky bridge. The storage worker runs in the system mount namespace."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import decky

HERE = Path(__file__).resolve().parent
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
    async def _main(self):
        await asyncio.to_thread(self._install_service)

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
        subprocess.run(["systemctl", "start", "deckycache.service"], check=True, env=system_env())

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
