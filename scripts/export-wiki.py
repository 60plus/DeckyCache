"""Copy the portable user guide into an existing, local wiki checkout. Does not push."""
from pathlib import Path
import argparse
import re
import shutil

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("destination", type=Path)
args = parser.parse_args()
destination = args.destination.resolve()
if not (destination / ".git").exists():
    parser.error("Destination must be an existing wiki Git checkout.")
source = ROOT / "docs/guide"
for page in source.glob("*.md"):
    text = page.read_text(encoding="utf-8")
    text = re.sub(r"\]\(([A-Za-z0-9-]+)\.md(#[^)]*)?\)", r"](\1\2)", text)
    text = text.replace("../../images/", "images/").replace("../images/", "images/")
    (destination / page.name).write_text(text, encoding="utf-8", newline="\n")
images = destination / "images"
images.mkdir(exist_ok=True)
for directory in (ROOT / "images", ROOT / "docs/images"):
    for asset in directory.iterdir():
        if asset.is_file():
            shutil.copy2(asset, images / asset.name)
sidebar = """## DeckyCache

- [Home](Home)
- [Installation](Installation)
- [First setup](Setup)
- [Everyday use](Daily-Use)
- [Compatibility](Compatibility)
- [Troubleshooting](Troubleshooting)
- [Uninstalling](Uninstalling)
- [How it works](How-It-Works)
"""
(destination / "_Sidebar.md").write_text(sidebar, encoding="utf-8", newline="\n")
(destination / "_Footer.md").write_text("DeckyCache · [User guide](Home) · [Compatibility](Compatibility)\n", encoding="utf-8", newline="\n")
print(f"Exported {len(list(source.glob('*.md')))} guide pages and images to {destination}")
