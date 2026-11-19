# fupi

A brute-force shortcut to fix Python import hell. Acronym standing for... um, "Fixing-Up Python Imports." Sure, let's go with that.

> **Not a best practice.** fupi edits `sys.path` so peer folders in a POC or demo can import each other without packaging. For real projects, use a proper package layout and `pip install -e .`. fupi is for when you just want the demo to run.

> **Breaking change from v1.** fupi 2.0.0 is a rewrite. `ManualFupi`, `shortest_path`, `FUPI_ADD_DIR_NAMES` and CWD-based scanning are gone. See [Migrating from 1.x](#migrating-from-1x).

## Usage

```python
import fupi
```

That's it. Everything is relative to the **directory of the file containing `import fupi`** (not your CWD), so the script behaves the same no matter where you run it from. A bare `import fupi` adds:

- that directory,
- all of its subdirectories (recursively, minus [skipped ones](#skip-patterns)),
- its parent directory (just the parent, not the parent's other children).

Paths are appended to the end of `sys.path` (so the stdlib and installed packages are never shadowed), deduplicated and sorted. `fupi.paths_added` lists what was added; referencing it also keeps "unused import" linters quiet:

```python
import fupi
print(fupi.paths_added)
```

### Exception: no file (REPL, notebook, `python -c`)

With no file to anchor to, for example in the interactive `python` prompt (the REPL), a Jupyter notebook, or `python -c`, fupi uses the **current working directory** instead. In that case a bare `import fupi` is more conservative. It adds only:

- the CWD,
- its immediate subdirectories (one level, not recursive),
- its parent directory.

That's the `up1_down1` shortcut. It keeps `import fupi` safe even if you start Python from `/` or your home folder. For the full file-style default from the CWD, import the shortcut explicitly:

```python
import fupi.up1_down     # CWD, its whole subtree, and its parent
```

## Shortcuts

Want different folders? Import a shortcut instead:

```python
import fupi.up2          # parent and grandparent
import fupi.up1down2     # parent, its children, and their children
```

A shortcut **replaces** the bare default; it is not added on top of it.

A name is made of **steps**. `upN` climbs N levels and `down`/`downK` descends K levels (unlimited without a number), adding every folder it passes. Steps run left to right, each starting where the previous one ended. Groups separated by `_` each start fresh at your file's directory, and the result is the union of every group. Your file's directory is always included.

| Name | Adds (A = your file's directory, P = parent, G = grandparent) |
|---|---|
| `up1` | P |
| `up2` | P, G |
| `up` | every ancestor of A, stopping below the filesystem root |
| `down` | every subdirectory of A, at any depth |
| `down1` | A's children |
| `up1down2` | P, P's children (A and its siblings), and their children |
| `up2down1` | P, G, and G's children |
| `down2_up1` | A's children and grandchildren, plus P alone |
| `up1down2_up3` | the `up1down2` result, plus P, G and the great-grandparent |
| `down_up1` or `up1_down` | what bare `import fupi` does from a file |
| `up1_down1` | what bare `import fupi` does with no file (REPL, notebook) |

Rules:
- Numbers are optional for both steps: bare `up` climbs every ancestor (stopping below the filesystem root), and bare `down` descends the whole tree. A number given must be at least 1. Invalid names (`up0`, `down0`, `up1__down`, ...) raise `ModuleNotFoundError`.
- Running out of folders is fine: `up100` stops below the filesystem root (which is never added), and `down100` stops at the bottom of the tree.
- A step that finds folders but none of them are new emits a `UserWarning`, because the name can be simplified. For example, `down2up1` climbs back onto folders `down2` already added.

### Sanity limit

One import may select at most `FUPI_DIR_LIMIT` folders (default `1000`). Names like `up100down` would otherwise put a large part of your disk on `sys.path`. Going over raises `fupi.FupiLimitError` before `sys.path` is touched. Narrow the name, or set a higher limit before importing:

```bash
FUPI_DIR_LIMIT=5000 python my_script.py
```

## Skip patterns

Descent skips (and never enters) folders whose **name** fully matches one of these regexes:

```python
fupi.FUPI_DEFAULT_SKIP_DIR_PATTERNS
# (r"\..*", r"_.*", r"venv.*", r"env", r".*\.egg-info", r"node_modules", r"old.*", r"(bkup|backup).*")
```

- Matching uses `re.fullmatch` on each folder name. **This changed from 1.x**, which used prefix matching: `doc` no longer skips `docs`, so write `doc.*` instead.
- Folders chosen explicitly (your file's directory, its parent and other ancestors) are never tested, so a project under `~/old_work/src/` still works.
- **Add patterns for every run** with a comma-separated env var, which appends to the defaults (commas inside a regex aren't supported):
  ```bash
  FUPI_SKIP_DIR_PATTERNS="build, dist, doc.*"
  ```
- **Change them in code**, then call `fupi.refresh()`. Changing the patterns does nothing by itself. `refresh()` re-runs every fupi import so far (the bare one and any shortcuts) with the current patterns, replacing the paths fupi added. That works in both directions: newly skipped folders are removed, and folders you stop skipping come back.
  ```python
  import fupi
  fupi.skip_dir_patterns.append("build")       # add to the defaults
  fupi.refresh()
  ```
  You can also assign a list, tuple, set or single string, which replaces everything, including the defaults:
  ```python
  fupi.skip_dir_patterns = ["build", "dist"]   # .git, venv, ... are no longer skipped
  fupi.refresh()
  fupi.skip_dir_patterns = fupi.FUPI_DEFAULT_SKIP_DIR_PATTERNS   # reset
  fupi.refresh()
  ```
  Shortcut imports that run after a change use the new patterns automatically; no `refresh()` needed.

## Migrating from 1.x

| 1.x | 2.0 |
|---|---|
| Scanned from the CWD for `src`, `app`, `main`, `test`, `tests`, `mcp` | Anchors at the importing file; adds it, its subtree and its parent |
| `FUPI_ADD_DIR_NAMES` | Removed. Use a shortcut such as `import fupi.up1down2` |
| `ManualFupi(...)`, `from fupi import ManualFupi` | Removed. Use shortcuts, `fupi.skip_dir_patterns` and `fupi.refresh()` |
| `shortest_path`, `sys_path_history`, rollback | Removed |
| Skip patterns prefix-matched (`re.match`) | Skip patterns must fully match the folder name (`re.fullmatch`) |
| Paths could be inserted anywhere | Always appended, sorted, deduplicated |

Requires Python 3.11+, standard library only.
