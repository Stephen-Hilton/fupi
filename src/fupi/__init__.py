"""fupi: put nearby directories on sys.path with one line, `import fupi`.

A deliberate shortcut for POCs and demos, knowingly not a best practice.
Shortcuts such as `import fupi.up1` or `import fupi.up1down2_up3` pick other folders.
"""
import importlib.abc
import importlib.util
import inspect
import os
import re
import sys
import warnings
from pathlib import Path

__version__ = "2.0.0"
__all__ = ["refresh", "paths_added", "skip_dir_patterns", "FUPI_DEFAULT_SKIP_DIR_PATTERNS", "FupiLimitError"]

FUPI_DEFAULT_SKIP_DIR_PATTERNS = (r"\..*", r"_.*", r"venv.*", r"env", r".*\.egg-info",
                                  r"node_modules", r"old.*", r"(bkup|backup).*")
_env = (p.strip().strip("'\"").strip() for p in os.environ.get("FUPI_SKIP_DIR_PATTERNS", "").split(","))
skip_dir_patterns = list(FUPI_DEFAULT_SKIP_DIR_PATTERNS) + [p for p in _env if p]
paths_added: list[str] = []  # every path this process added to sys.path
_bare_added: list[str] = []  # paths added by the bare `import fupi` run (replaced by shortcuts)
_runs: list[tuple] = []  # (name, anchor, module) of each run, so refresh() can redo them
_GROUP = re.compile(r"(?:up\d*|down\d*)+")
_INTERNAL = (os.path.dirname(os.path.abspath(__file__)) + os.sep,
             os.path.dirname(importlib.util.__file__) + os.sep, "<frozen importlib")


class FupiLimitError(RuntimeError):
    """Raised when one fupi import would select more than FUPI_DIR_LIMIT directories."""


def _parse(name):
    """Return [[(kind, n), ...], ...] (one list per group) for a valid name, else None."""
    groups = []
    for group in name.split("_"):
        if not _GROUP.fullmatch(group):
            return None
        steps = [(k, int(n) if n else None) for k, n in re.findall(r"(up|down)(\d*)", group)]
        if any(n == 0 for _, n in steps):
            return None
        groups.append(steps)
    return groups


def _user_frame():
    """Return (first frame outside fupi/importlib, its warnings stacklevel relative to our caller)."""
    frame, level = inspect.currentframe().f_back, 1
    while frame and frame.f_code.co_filename.startswith(_INTERNAL):
        frame = frame.f_back
        if frame and "_bootstrap" not in frame.f_code.co_filename:  # warnings skips those itself
            level += 1
    return frame, level


def _limit():
    raw = os.environ.get("FUPI_DIR_LIMIT", "1000")
    if not raw.strip().isdigit() or int(raw) < 1:
        raise ValueError(f"FUPI_DIR_LIMIT must be an integer >= 1, got {raw!r}")
    return int(raw)


def _subdirs(directory, skip):
    names = next(os.walk(directory), (None, [], None))[1]
    return [(directory / n).resolve() for n in sorted(names) if not any(re.fullmatch(p, n) for p in skip)]


def _select(name, anchor, mod, level=None):
    """Return the set of folders `name` selects from `anchor`. Warns about redundant steps unless level is None."""
    limit, skip = _limit(), skip_dir_patterns
    skip = [skip] if isinstance(skip, str) else list(skip)
    selected = {anchor}

    def add(path):
        found.add(path)
        if path not in selected:
            selected.add(path)
            new.add(path)
            if len(selected) > limit:
                raise FupiLimitError(
                    f"'import {mod}' (anchor {anchor}) selected more than the limit of {limit} folders.\n"
                    "This is a problem: a huge sys.path slows every import, makes module-name collisions "
                    "and wrong-module imports likely, and usually means the name is broader than intended.\n"
                    "To fix: narrow the name (for example 'down2' instead of 'down'), or raise the limit by "
                    "setting FUPI_DIR_LIMIT (for example FUPI_DIR_LIMIT=5000) before importing fupi.")

    for group in _parse(name):
        ends = [anchor]  # every group starts fresh at the anchor
        for kind, n in group:
            found, new, next_ends = set(), set(), []
            if kind == "up":
                for path in ends:
                    for _ in range(n or sys.maxsize):  # bare `up`: climb until just below the root
                        if path.parent == path.parent.parent:  # never add the filesystem root
                            break
                        path = path.parent
                        add(path)
                    next_ends.append(path)
            else:
                level_dirs, depth = ends, 0
                while level_dirs and (n is None or depth < n):
                    deeper = []
                    for d in level_dirs:
                        for child in _subdirs(d, skip):
                            if child not in found:
                                add(child)
                                deeper.append(child)
                    level_dirs, depth = deeper, depth + 1
                    next_ends = deeper or next_ends
            if found and not new and level is not None:
                step = f"{kind}{n or ''}"
                warnings.warn(f"fupi: step '{step}' in '{name}' selected no new folders", UserWarning,
                              stacklevel=level)
            ends = list(dict.fromkeys(next_ends)) if found else ends
    return selected


def _apply(name, shortcut):
    """Select folders for `name` from the importing file's directory, then append them to sys.path."""
    global _bare_added
    frame, level = _user_frame()
    file = frame.f_globals.get("__file__") if frame else None
    file = file if file and os.path.isfile(file) else None  # e.g. `python -` sets __file__ = '<stdin>'
    anchor = Path(file).resolve().parent if file else Path.cwd().resolve()
    if not shortcut:  # bare default: whole subtree from a file, but only one level from a REPL/notebook CWD
        name = "down_up1" if file else "up1_down1"
    mod = f"fupi.{name}" if shortcut else "fupi"
    selected = _select(name, anchor, mod, level + 1)  # +1: warnings are raised one frame deeper, in _select
    if shortcut:  # a shortcut replaces the bare `import fupi` default rather than adding to it
        for p in _bare_added:
            if p in sys.path:
                sys.path.remove(p)
            if p in paths_added:
                paths_added.remove(p)
        _bare_added = []
        _runs[:] = [r for r in _runs if r[2] != "fupi"]
    _runs.append((name, anchor, mod))
    added = [p for p in sorted(map(str, selected)) if p not in sys.path]
    sys.path.extend(added)
    paths_added.extend(added)
    return added


def refresh():
    """Re-run every fupi import so far with the current skip_dir_patterns, replacing the paths fupi added."""
    global _bare_added
    selected = set().union(*(_select(*run) for run in _runs))  # raises before sys.path changes
    for p in paths_added:
        if p in sys.path:
            sys.path.remove(p)
    paths_added[:] = [p for p in sorted(map(str, selected)) if p not in sys.path]
    sys.path.extend(paths_added)
    if [r[2] for r in _runs] == ["fupi"]:  # still only the bare run, so a later shortcut must replace it
        _bare_added = list(paths_added)
    return list(paths_added)


class _ShortcutFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Serves `fupi.<name>` for any name matching the shortcut grammar."""

    def find_spec(self, fullname, path=None, target=None):
        pkg, _, name = fullname.partition(".")
        if pkg == __name__ and name and "." not in name and _parse(name):
            return importlib.util.spec_from_loader(fullname, self)
        return None

    def exec_module(self, module):
        module.paths_added = _apply(module.__name__.partition(".")[2], shortcut=True)


_bare_added = _apply(None, shortcut=False)
if not any(type(f).__name__ == "_ShortcutFinder" for f in sys.meta_path):
    sys.meta_path.append(_ShortcutFinder())
