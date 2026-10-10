"""Read Steam non-store shortcuts without launching or changing them."""
from pathlib import Path
import shlex
import struct

MAX_SHORTCUT_BYTES = 4 * 1024**2
SHARED_FOLDERS = {"games", "roms", "steamapps", "common", "steamlibrary"}


def read_shortcuts(path):
    with Path(path).open("rb") as stream:
        data = stream.read(MAX_SHORTCUT_BYTES + 1)
    if len(data) > MAX_SHORTCUT_BYTES:
        raise ValueError("Steam shortcut file is too large.")
    position = 0

    def string():
        nonlocal position
        end = data.index(0, position)
        value = data[position:end].decode("utf-8", "replace")
        position = end + 1
        return value

    def obj(depth=0):
        nonlocal position
        if depth > 8:
            raise ValueError("Steam shortcut nesting is too deep.")
        result = {}
        while position < len(data):
            kind = data[position]
            position += 1
            if kind == 8:
                return result
            key = string().casefold()
            if kind == 0:
                value = obj(depth + 1)
            elif kind == 1:
                value = string()
            elif kind in (2, 3, 7, 10):
                fmt = {2: "<I", 3: "<f", 7: "<Q", 10: "<q"}[kind]
                value = struct.unpack_from(fmt, data, position)[0]
                position += struct.calcsize(fmt)
            else:
                raise ValueError("Unsupported Steam shortcut value.")
            result[key] = value
        raise ValueError("Incomplete Steam shortcut file.")

    try:
        shortcuts = obj().get("shortcuts", {})
    except (IndexError, struct.error) as error:
        raise ValueError("Incomplete Steam shortcut file.") from error
    if not isinstance(shortcuts, dict):
        raise ValueError("Invalid Steam shortcut list.")
    return [row for row in shortcuts.values() if isinstance(row, dict)]


def unquote(value):
    if not isinstance(value, str):
        return ""
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1]
    return value


def executable_path(value):
    if not isinstance(value, str) or not value:
        return None
    # A complete quoted/unquoted filename takes priority over command arguments.
    direct = Path(unquote(value))
    if direct.is_absolute() and direct.is_file():
        return direct.resolve()
    try:
        parts = shlex.split(value)
    except ValueError:
        return None
    if parts:
        target = Path(parts[0])
        if target.is_absolute() and target.is_file():
            return target.resolve()
    return None


def shortcut_games(steam, libraries):
    """Only assign direct launch targets inside active library volumes."""
    volumes = [(Path(lib["path"]).resolve(), lib["mapper"]) for lib in libraries
               if lib.get("enabled") and lib.get("active")]
    games = {}
    for file in sorted((Path(steam) / "userdata").glob("*/config/shortcuts.vdf")):
        account = file.parent.parent.name
        if not account.isdigit():
            continue
        try:
            entries = read_shortcuts(file)
        except (OSError, ValueError):
            # A concurrent Steam save or a bad profile must not hide other games.
            continue
        for entry in entries:
            try:
                name, appid = entry.get("appname"), entry.get("appid")
                if not isinstance(name, str) or not name.strip() or type(appid) is not int:
                    continue
                if not -(2**31) <= appid < 2**32:
                    continue
                executable = executable_path(entry.get("exe"))
                if executable is None:
                    continue
                matches = [(base, mapper) for base, mapper in volumes if executable.is_relative_to(base)]
                if not matches:
                    continue
                base, mapper = max(matches, key=lambda item: len(item[0].parts))
                folder = executable.parent
                start = Path(unquote(entry.get("startdir")))
                if (start.is_absolute() and start.is_dir() and start.resolve() != base
                        and start.resolve().is_relative_to(base) and executable.is_relative_to(start.resolve())
                        and start.name.casefold() not in SHARED_FOLDERS):
                    folder = start.resolve()
                # Never label an entire library or a shared container as one game.
                if folder == base or folder.name.casefold() in SHARED_FOLDERS:
                    continue
                appid &= 0xffffffff
                key = "shortcut:" + account + ":" + str(appid)
                games[key] = {"id": key, "app_id": appid, "name": name.strip(), "steam": False,
                              "path": str(folder), "mapper": mapper}
            except (OSError, ValueError, RuntimeError):
                continue
    return sorted(games.values(), key=lambda game: game["name"].casefold())
