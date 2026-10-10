"""Build the Open CAS Decky plugin with its offline user guide."""
from pathlib import Path
import json
import zipfile
ROOT = Path(__file__).resolve().parents[1]
version = json.loads((ROOT / "plugin/package.json").read_text())["version"]
output = ROOT / "build" / f"DeckyCache-{version}.zip"
output.parent.mkdir(exist_ok=True)
files = ["plugin.json", "package.json", "main.py", "cache_service.py", "block_cache.py", "resident_games.py", "opencas_cache.py", "dist/index.js"]
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
print(output)
