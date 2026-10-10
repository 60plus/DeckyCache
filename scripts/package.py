"""Build the Open CAS Decky plugin with its offline user guide."""
from pathlib import Path
import json
import hashlib
import zipfile
ROOT = Path(__file__).resolve().parents[1]
version = json.loads((ROOT / "plugin/package.json").read_text())["version"]
output = ROOT / "build" / f"DeckyCache-{version}.zip"
output.parent.mkdir(exist_ok=True)
files = ["plugin.json", "package.json", "main.py", "cache_service.py", "block_cache.py", "resident_games.py", "opencas_cache.py", "compatibility.py", "updates.py", "service_runtime.py", "dist/index.js"]
bundles = list((ROOT / "plugin/bin/opencas").glob("*/manifest.json"))
if not bundles or not (ROOT / "plugin/bin/opencas/casadm").is_file():
    raise RuntimeError("Prepare the exact-kernel Open CAS bundle before packaging.")
with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as z:
    for name in files:
        z.write(ROOT / "plugin" / name, "DeckyCache/" + name.replace("\\", "/"))
    for asset in (ROOT / "plugin/bin/opencas").rglob("*"):
        if asset.is_file():
            z.write(asset, "DeckyCache/" + asset.relative_to(ROOT / "plugin").as_posix())
    z.write(ROOT / "LICENSE", "DeckyCache/LICENSE")
    z.write(ROOT / "README.md", "DeckyCache/README.md")
    for folder in ("docs", "images"):
        for asset in sorted((ROOT / folder).rglob("*")):
            if asset.is_file():
                z.write(asset, "DeckyCache/" + asset.relative_to(ROOT).as_posix())
    z.write(ROOT / "scripts/README-opencas-build.md", "DeckyCache/scripts/README-opencas-build.md")
digest = hashlib.sha256(output.read_bytes()).hexdigest()
(output.parent / "SHA256SUMS").write_text(digest + "  " + output.name + "\n", encoding="utf-8")
metadata = {"schema": 1, "version": version, "channel": "stable", "arch": "x86_64",
            "kernels": sorted(json.loads(p.read_text())["kernel"] for p in bundles),
            "asset": output.name, "sha256": digest}
(output.parent / "deckycache-update.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
print(output)
