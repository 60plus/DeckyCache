"""Match live ext4 file extents against a checked copy of dm-cache metadata.

Only file metadata is inspected. Never suspend a mapper, read game contents,
run cache_dump on a live device, or treat previous observations as residency.
"""
import fcntl
import os
from pathlib import Path
import shutil
import stat
import struct
import tempfile
import time
import xml.etree.ElementTree as ET
from block_cache import META_BYTES, parse_status

FIEMAP = 0xC020660B
EXTENTS = 128
# Physical data must be initialized, directly mapped, and block aligned.
UNSUPPORTED = 0x2 | 0x4 | 0x8 | 0x80 | 0x100 | 0x200 | 0x400 | 0x800


class ScanChanged(RuntimeError):
    pass


def mapping_key(text):
    parse_status(text)  # Reject unhealthy/non-writethrough mappings.
    fields = text.split()
    s = fields[3:]
    # Reads do not change file extents. Writes, promotions and demotions do.
    return tuple(fields[:3] + s[2:4] + s[6:11] + s[11:])


class BlockSet:
    """One bit per origin block; memory does not grow with XML object count."""
    def __init__(self, limit):
        self.limit, self.count = limit, 0
        self.bits = bytearray((limit + 7) // 8)

    def __bool__(self):
        return bool(self.count)

    def add(self, block):
        if not 0 <= block < self.limit:
            raise ValueError("Cache mapping is outside the device.")
        byte, bit = divmod(block, 8)
        mask = 1 << bit
        if self.bits[byte] & mask:
            raise ValueError("Duplicate cache mapping.")
        self.bits[byte] |= mask
        self.count += 1


def overlap(blocks, begin, end, block_bytes):
    if begin < 0 or end <= begin or not blocks:
        return False
    first, last = begin // block_bytes, min((end - 1) // block_bytes, blocks.limit - 1)
    if first > last:
        return False
    a, b = first // 8, last // 8
    left, right = 0xff << (first % 8), (1 << (last % 8 + 1)) - 1
    if a == b:
        return bool(blocks.bits[a] & left & right)
    return bool(blocks.bits[a] & left or blocks.bits[b] & right
                or any(memoryview(blocks.bits)[a + 1:b]))


def parse_mappings(source, status, origin_bytes, deadline=None):
    fields = status.split()[3:]
    used, capacity = map(int, fields[3].split("/"))
    blocks, slots, block_bytes, had_mappings = None, None, None, False
    parents = []
    try:
        for index, (event, item) in enumerate(ET.iterparse(source, events=("start", "end"))):
            if deadline is not None and index % 16384 == 0 and time.monotonic() >= deadline:
                raise ScanChanged("Game inspection will retry.")
            if event == "start":
                if not parents:
                    block_bytes = int(item.attrib["block_size"]) * 512
                    if (item.tag != "superblock" or block_bytes != int(fields[2]) * 512
                            or int(item.attrib["nr_cache_blocks"]) != capacity):
                        raise ScanChanged("Cache layout changed during inspection.")
                    blocks, slots = BlockSet(origin_bytes // block_bytes), BlockSet(capacity)
                elif item.tag == "mappings" and len(parents) == 1:
                    had_mappings = True
                parents.append(item)
                continue
            if len(parents) == 3 and parents[-2].tag == "mappings":
                if item.tag != "mapping":
                    raise ValueError("Unsupported cache mapping record.")
                slots.add(int(item.attrib["cache_block"]))
                blocks.add(int(item.attrib["origin_block"]))
            parents.pop()
            if parents:
                parents[-1].remove(item)
            item.clear()
    except (ET.ParseError, KeyError) as error:
        raise ValueError("Invalid cache metadata dump.") from error
    if not had_mappings:
        raise ValueError("Cache mapping list is missing.")
    if blocks.count != used:
        raise ScanChanged("Cache residency changed during inspection.")
    return blocks, block_bytes

def metadata_snapshot(manager, lib, deadline):
    name = manager.block.name(lib)
    get_status = lambda: manager.block.run("dmsetup", "status", name)
    before = get_status()  # dm-cache commits metadata for a normal status query.
    meta = manager.block.cache / "blocks" / lib["id"] / "metadata"
    if meta.stat().st_size != META_BYTES:
        raise ValueError("Unexpected cache metadata size.")
    scratch = manager.block.cache.parent  # /run: never write the copy to the cache itself.
    used = int(before.split()[6].split("/")[0])
    if shutil.disk_usage(scratch).free < 2 * META_BYTES + 200 * used:
        raise RuntimeError("Not enough temporary space to inspect cached games.")
    with meta.open("rb") as source, tempfile.TemporaryDirectory(prefix="games-snapshot-", dir=scratch) as temp:
        header = source.read(4096)
        source.seek(0)
        snapshot = Path(temp) / "metadata"
        with snapshot.open("wb") as output:
            shutil.copyfileobj(source, output, length=1024 * 1024)
        source.seek(0)
        with snapshot.open("rb") as copied:
            stable = header == source.read(4096) == copied.read(4096)
        if not stable or mapping_key(before) != mapping_key(get_status()):
            raise ScanChanged("Cache changed while copying metadata.")
        if time.monotonic() >= deadline:
            raise ScanChanged("Game inspection will retry.")
        # The tool sees a private, immutable file, never active cache metadata.
        xml = Path(temp) / "mappings.xml"
        manager.block.run("cache_dump", "-o", xml, snapshot, timeout=max(1, min(10, deadline - time.monotonic())))
        blocks, block_bytes = parse_mappings(xml, before, lib["size"], deadline)
    if mapping_key(before) != mapping_key(get_status()):
        raise ScanChanged("Cache changed while reading mappings.")
    return blocks, block_bytes, mapping_key(before)


def signature(st):
    return st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns


def file_has_blocks(path, root, device, blocks, block_bytes, deadline):
    # Symlinks and nested mounts cannot attribute another game's data to this one.
    if not path.resolve().is_relative_to(root):
        return False
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_dev != device or not before.st_size:
            return False
        start, found = 0, False
        while start < before.st_size:
            if time.monotonic() >= deadline:
                raise ScanChanged("Game inspection will retry.")
            buf = bytearray(32 + 56 * EXTENTS)
            # No SYNC flag: inspecting the list must not flush a running game.
            struct.pack_into("=QQIIII", buf, 0, start, before.st_size - start, 0, 0, EXTENTS, 0)
            fcntl.ioctl(fd, FIEMAP, buf, True)
            count = struct.unpack_from("=I", buf, 20)[0]
            if count > EXTENTS:
                raise ValueError("Invalid file extent count.")
            if not count:
                break
            end, last = start, False
            for i in range(count):
                logical, physical, length, _, _, flags, *_ = struct.unpack_from("=QQQQQIIII", buf, 32 + 56 * i)
                if not length:
                    raise ValueError("Invalid empty file extent.")
                end = max(end, logical + length)
                last = bool(flags & 1)
                if not flags & UNSUPPORTED and logical < before.st_size:
                    size = min(length, before.st_size - logical)
                    found |= overlap(blocks, physical, physical + size, block_bytes)
            if found or last:
                break
            if end <= start:
                raise ValueError("File extent lookup did not advance.")
            start = end
        if signature(before) != signature(os.fstat(fd)) or signature(before) != signature(path.stat(follow_symlinks=False)):
            raise ScanChanged("A game file changed during inspection.")
        return found
    finally:
        os.close(fd)


def game_has_blocks(game, lib, device, blocks, block_bytes, deadline):
    root = Path(game["path"])
    base = Path(lib["path"]).resolve()
    if root.is_symlink():
        return False
    root = root.resolve()
    if not root.is_relative_to(base) or not root.is_dir() or root.stat().st_dev != device:
        return False
    def walk_error(error):
        raise ScanChanged("The game folder changed during inspection.") from error
    for directory, dirs, files in os.walk(root, followlinks=False, onerror=walk_error):
        if time.monotonic() >= deadline:
            raise ScanChanged("Game inspection will retry.")
        dirs[:] = [d for d in dirs if not (Path(directory) / d).is_symlink()
                   and (Path(directory) / d).stat().st_dev == device]
        for name in files:
            path = Path(directory) / name
            if path.is_symlink():
                continue
            if file_has_blocks(path, root, device, blocks, block_bytes, deadline):
                return True
    return False


def resident_games(manager, libraries, catalog):
    """Return only current positive matches; retry instead of returning stale games."""
    deadline = time.monotonic() + 15
    for attempt in range(2):
        try:
            result = {}
            for lib in libraries:
                if not lib["active"]:
                    continue
                manager.block.verify(lib)
                blocks, block_bytes, key = metadata_snapshot(manager, lib, deadline)
                device = os.stat(manager.block.mapper(lib)).st_rdev
                # Different Steam app IDs can share one installation directory.
                matched = {}
                for game in catalog:
                    if game["mapper"] != manager.block.mapper(lib):
                        continue
                    path = game["path"]
                    if path not in matched:
                        matched[path] = bool(blocks) and game_has_blocks(game, lib, device, blocks, block_bytes, deadline)
                    if matched[path]:
                        result[game["id"]] = {k: game[k] for k in ("id", "name", "steam")}
                after = manager.block.run("dmsetup", "status", manager.block.name(lib))
                if mapping_key(after) != key:
                    raise ScanChanged("Cache or game files changed during inspection.")
            return sorted(result.values(), key=lambda game: game["name"].casefold())
        except ScanChanged:
            if attempt or time.monotonic() >= deadline:
                raise
    return []
