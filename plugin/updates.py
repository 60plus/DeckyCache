"""Select and verify public Stable releases before asking Decky to install."""
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import platform
import re
import stat
import ssl
import urllib.error
import urllib.parse
import urllib.request
import zipfile

REPO = "60plus/DeckyCache"
API = "https://api.github.com/repos/" + REPO
DOWNLOADS = "https://github.com/" + REPO + "/releases/download/"
MAX_ZIP = 128 * 1024 * 1024
MAX_EXPANDED = 512 * 1024 * 1024


def version_key(value):
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)(-dev(?:\.?\d+)?)?", value)
    if not match:
        raise ValueError("Unsupported release version.")
    return tuple(map(int, match.groups()[:3])) + (0 if match.group(4) else 1,)


def read_url(url, limit):
    if not (url.startswith(API + "/releases?") or url.startswith(DOWNLOADS)):
        raise RuntimeError("Update URL is outside the DeckyCache repository.")
    request = urllib.request.Request(url, headers={
        "User-Agent": "DeckyCache-updater", "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"})
    try:
        # Decky's embedded Python may have build-machine CA defaults.
        # Use SteamOS trust certificates without weakening TLS verification.
        trust = Path("/etc/ssl/cert.pem")
        context = ssl.create_default_context(cafile=str(trust) if trust.is_file() else None)
        with urllib.request.urlopen(request, timeout=30, context=context) as response:
            if int(response.headers.get("Content-Length", "0")) > limit:
                raise RuntimeError("Update download is too large.")
            data = response.read(limit + 1)
        if len(data) > limit:
            raise RuntimeError("Update download is too large.")
        return data
    except urllib.error.HTTPError as error:
        if error.code in (403, 429):
            raise RuntimeError("GitHub is limiting update checks. Try again later.") from error
        raise RuntimeError("Could not download the update from GitHub.") from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise RuntimeError("Cannot reach GitHub. Check the connection and try again.") from error


def asset_url(asset, tag):
    expected = DOWNLOADS + urllib.parse.quote(tag, safe="") + "/" + urllib.parse.quote(asset["name"], safe="")
    if asset["browser_download_url"] != expected:
        raise RuntimeError("The release asset is outside the expected release.")
    return expected


def check_update(installed, kernel=None):
    kernel = kernel or platform.release()
    releases = []
    # Search compatible releases, not just /latest, which may target another kernel.
    for page in (1, 2):
        batch = json.loads(read_url(API + "/releases?per_page=20&page=" + str(page), 2 * 1024**2))
        if not isinstance(batch, list):
            raise RuntimeError("GitHub returned an invalid release list.")
        releases.extend(batch)
        if len(batch) < 20:
            break
    candidates = []
    for release in releases:
        if release.get("draft") or release.get("prerelease"):
            continue
        try:
            key = version_key(release["tag_name"])
        except (ValueError, KeyError):
            continue
        if key <= version_key(installed) or key[-1] != 1:
            continue
        candidates.append((key, release))
    for _, release in sorted(candidates, key=lambda pair: pair[0], reverse=True):
        assets = {asset["name"]: asset for asset in release.get("assets", [])}
        metadata = assets.get("deckycache-update.json")
        if not metadata:
            continue
        tag = release["tag_name"]
        manifest = json.loads(read_url(asset_url(metadata, tag), 128 * 1024))
        version = tag.removeprefix("v")
        if (manifest.get("schema") != 1 or manifest.get("version") != version
                or manifest.get("channel") != "stable" or manifest.get("arch") != "x86_64"):
            continue
        if kernel not in manifest.get("kernels", []) or platform.machine() != "x86_64":
            continue
        name = "DeckyCache-" + version + ".zip"
        asset = assets.get(name)
        if not asset or manifest.get("asset") != name:
            continue
        digest = manifest.get("sha256", "")
        if not re.fullmatch(r"[a-f0-9]{64}", digest):
            continue
        if not isinstance(asset.get("size"), int) or not 0 < asset["size"] <= MAX_ZIP:
            continue
        if asset.get("digest") and asset["digest"] != "sha256:" + digest:
            raise RuntimeError("Release checksum metadata does not match GitHub.")
        return {"version": version, "kernel": kernel, "url": asset_url(asset, tag),
                "sha256": digest, "size": asset["size"]}
    return None


def verify_archive(data, candidate):
    if len(data) != candidate["size"] or hashlib.sha256(data).hexdigest() != candidate["sha256"]:
        raise RuntimeError("The update ZIP failed its checksum check.")
    if candidate["kernel"] != platform.release():
        raise RuntimeError("The running kernel changed. Check for updates again.")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            if len(infos) > 10000 or sum(item.file_size for item in infos) > MAX_EXPANDED:
                raise RuntimeError("The update ZIP is too large when extracted.")
            names = set()
            for item in infos:
                path = PurePosixPath(item.filename)
                if (not item.filename.startswith("DeckyCache/") or "\\" in item.filename
                        or ":" in item.filename or ".." in path.parts
                        or item.filename.rstrip("/") != path.as_posix()
                        or stat.S_ISLNK(item.external_attr >> 16) or item.filename in names):
                    raise RuntimeError("The update ZIP contains an unsafe path.")
                names.add(item.filename)
            prefix = "DeckyCache/"
            package = json.loads(archive.read(prefix + "package.json"))
            plugin = json.loads(archive.read(prefix + "plugin.json"))
            if package["version"] != candidate["version"] or plugin["name"] != "DeckyCache":
                raise RuntimeError("The update ZIP contains a different plugin or version.")
            if package.get("remote_binary") or plugin.get("remote_binary"):
                raise RuntimeError("Updates must include their binaries in the verified ZIP.")
            bundle = prefix + "bin/opencas/" + candidate["kernel"] + "/"
            manifest = json.loads(archive.read(bundle + "manifest.json"))
            if manifest["kernel"] != candidate["kernel"]:
                raise RuntimeError("The update has no matching kernel module.")
            for name in ("casadm", "cas_bd.ko", "cas_cache.ko"):
                path = prefix + "bin/opencas/casadm" if name == "casadm" else bundle + name
                if hashlib.sha256(archive.read(path)).hexdigest() != manifest["sha256"][name]:
                    raise RuntimeError("An update module failed its checksum check.")
            for name in ("main.py", "cache_service.py", "compatibility.py", "updates.py", "dist/index.js"):
                if prefix + name not in names:
                    raise RuntimeError("The update is missing required plugin files.")
            if archive.testzip():
                raise RuntimeError("The update ZIP is damaged.")
    except (zipfile.BadZipFile, KeyError, ValueError) as error:
        raise RuntimeError("The update ZIP has invalid package metadata.") from error


def download_update(candidate):
    data = read_url(candidate["url"], MAX_ZIP)
    verify_archive(data, candidate)
    return data
