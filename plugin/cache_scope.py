"""Build bounded directory admission rules while retaining cached class identities."""
from pathlib import PurePosixPath as Path

NO_MATCH = "request_size:eq:0&done"


def directory_rule(paths, done=True):
    paths = sorted(set(paths))
    if not paths:
        return NO_MATCH
    for path in paths:
        if not Path(path).is_absolute() or any(c in path for c in "&|,\r\n"):
            raise RuntimeError("This folder path cannot be represented by Open CAS.")
    if len(paths) == 1 and done:
        rule = "directory:" + paths[0] + "&file_size:gt:0&done"
    else:
        rule = "|".join("directory:" + path for path in paths) + ("&done" if done else "")
    if len(rule.encode()) >= 1024:
        raise RuntimeError("The selected folder paths are too long for Open CAS.")
    return rule


def intersection(game, roots):
    base = Path(game)
    if any(base.is_relative_to(Path(root)) for root in roots):
        return [game]
    return [root for root in roots if Path(root).is_relative_to(base)]


def scope_rows(saved, current, mode, roots):
    saved = [dict(row) for row in saved]
    roots = sorted(set(roots))
    def add(path, folder=False, required=False):
        if any(row["path"] == path for row in saved):
            return
        available = sorted(set(range(1, 33)) - {row["id"] for row in saved})
        if not available:
            if required:
                raise RuntimeError("Open CAS has no free tracking slot for this folder. Keep Entire selected drives or choose an already tracked folder.")
            return
        row = {"id": available[0], "path": path}
        if folder:
            row["scope_folder"] = True
        saved.append(row)
    if mode == "folders":
        for root in roots:
            directory_rule([root], done=False)
            add(root, folder=root not in current, required=True)
    for path in sorted(current):
        if mode == "drives" or intersection(path, roots):
            add(path)
    rows = [[0, "unclassified", 255, 1 if mode == "drives" else 0]]
    for row in sorted(saved, key=lambda item: item["id"]):
        path = row["path"]
        if path in current and not row.get("scope_folder"):
            selected = [path] if mode == "drives" else intersection(path, roots)
            rule = directory_rule(selected)
        elif mode == "folders" and path in roots:
            rule = directory_rule([path], done=False)
        else:
            rule = NO_MATCH
        rows.append([row["id"], rule, 255, 1])
    return saved, rows
