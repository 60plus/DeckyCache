"""Read bundle compatibility without loading modules or touching a drive."""
import json
from pathlib import Path
import platform

ROOT = Path(__file__).resolve().parent


def compatibility():
    kernel = platform.release()
    bundles = ROOT / "bin/opencas"
    kernels = sorted(p.parent.name for p in bundles.glob("*/manifest.json"))
    supported = False
    try:
        manifest = json.loads((bundles / kernel / "manifest.json").read_text())
        supported = (manifest["kernel"] == kernel and platform.machine() == "x86_64"
                     and all((bundles / kernel / (name + ".ko")).is_file()
                             for name in ("cas_bd", "cas_cache"))
                     and (bundles / "casadm").is_file())
    except (OSError, ValueError, KeyError):
        pass
    return {"kernel": kernel, "bundled_kernels": kernels, "supported": supported,
            "message": "" if supported else
            "No cache module for this kernel. Games use the original drive. Check for updates."}


def plugin_version():
    return json.loads((ROOT / "package.json").read_text())["version"]
