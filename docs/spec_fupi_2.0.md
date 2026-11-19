 
# fupi 2.0.0 — redesign spec
**Task:** rewrite fupi from scratch as a breaking 2.0.0 release. Read the existing `src/fupi/` only for context; the old API is being removed, not kept compatible (breaking change).
 
## Purpose and constraints
 
- fupi is a one-line shortcut that puts nearby directories on `sys.path`, so POCs and demos don't hit Python import errors between peer directories. It is knowingly not a best practice, and the README should say so up front.
- **Keep it tiny.** Target roughly 100 lines of source, standard library only, Python >= 3.11. Prefer less code over more features.
- The primary usage is two words: `import fupi`.

## Core behavior
 
**Anchor.** Everything is relative to the directory of the *importing file* (the file containing the `import fupi` line), never the CWD.
- Find it by walking frames from the import call and skipping frames from the fupi package and from `importlib` internals. Use the first frame's `__file__`, resolved with symlinks followed.
- If there is no file (REPL, notebook, `python -c`, or a `__file__` that is not a real file such as `'<stdin>'`), fall back to the CWD.
- Do not parse source text, and do not guess the import style from source lines.
**Always included:** the anchor directory itself.
 
**Bare `import fupi` adds:** the anchor, all of its subdirectories (recursive), and its parent directory (the parent only, not the parent's other children). Implement it with the same traversal engine as the shortcuts: it is the name `down_up1`.

**Exception: no file.** When the anchor fell back to the CWD, bare `import fupi` uses `up1_down1` instead (the CWD, its immediate subdirectories, and its parent), so starting a REPL in `/` or `~` cannot hit the limit. Users who want the file-style default from the CWD write `import fupi.up1_down`. The README must call this exception out.
 
**Path rules:**
- Append to `sys.path` and never insert at the front, so stdlib and installed packages are not shadowed.
- No duplicates, with a deterministic order (sorted).
- Store absolute, resolved string paths.
**Public attribute `fupi.paths_added`:** a list of the paths this process added. Telling users to reference it also silences "unused import" linters.
 
## Shortcut modules (dynamic, via import hook)
 
Shortcuts are submodules: `import fupi.up1`, `import fupi.up2down2_up3`, and so on.
 
**Grammar:** a name is one or more *groups* joined by `_`, with no limit on the number of groups (`up2down1_up4down1_up6down1` is valid; only the `FUPI_DIR_LIMIT` path limit applies). A group is one or more *steps* concatenated with no separator, in any order, and a step is `up<N>` or `down[<K>]`. Parse by splitting on `_`, applying `re.fullmatch(r"(?:up\d+|down\d*)+", group)` to each group, and tokenising it with `re.findall(r"(up|down)(\d*)", group)`. `N` and `K` must be >= 1 when given, so `up0`, `down0` and a bare `up` are invalid. Examples: `up1`, `down`, `down1`, `up1down2`, `down2up1`, `up1down2_up3`, `down2_up1`.
 
**Semantics: a traversal.** `up` and `down` are symmetric steps. Each step walks folders from where the previous step ended, adding every folder it passes to `sys.path`, until it hits its limit (N levels up, K levels down).
- Each group starts fresh at the anchor. The anchor is always selected. The result is the union of all groups, and group order does not change it.
- Inside a group, steps run left to right. Each step starts from the previous step's *endpoints* (initially just the anchor):
  - `upN` adds every ancestor of each endpoint, from the parent up to the Nth ancestor (the directories themselves only, not their other children). Its new endpoints are the Nth ancestors. **Running out is not an error:** if fewer than N ancestors exist, it adds what exists and stops (`up100` is fine) with no error and no warning. Never add the filesystem root itself (`/` or a drive root), because that would make every top-level folder importable. If a step finds nothing at all, its endpoints stay unchanged so later steps continue from where it was.
  - `downK` adds descendants of each endpoint, level by level, to depth K (unlimited with no number), skipping directories that match the skip patterns. Its new endpoints are the directories at the deepest level it reached. **Running out is not an error:** if the tree is shallower than K, it adds what exists and stops (`down100` is fine) with no error and no warning. If it finds nothing at all (no subdirectories), its endpoints stay unchanged.
- Worked examples (anchor `A`, parent `P`, grandparent `G`):
  - `up1down2`: add `P`, then all of `P`'s children (`A` and its siblings), then all of their children. `A`'s own subtree is included to that depth.
  - `down2_up1`: group 1 adds `A`'s children and grandchildren, and group 2 starts fresh and adds `P` alone (not its other children).
  - `down2up1`: add `A`'s children and grandchildren, then go up one from the grandchildren, which lands on the children again. That step adds nothing new, so it warns (below).
  - `down2up3`: add `A`'s children and grandchildren, then climb from the grandchildren to the children, then `A`, then `P`. Only `P` is new, so this does not warn. The result equals `down2_up1`, which is the cleaner way to write it.
  - `up1down2_up3`: the `up1down2` result plus `P`, `G` and the great-grandparent.
  - `down_up1`: `A` and all its descendants, plus `P` alone. This is exactly what bare `import fupi` does from a file.
- Descent is never the default. It happens only when `down` is named.
- Names that don't match the grammar must raise a normal `ModuleNotFoundError`.
**Redundancy warning.** Track the set of paths selected so far across the whole name (starting with the anchor). If a step *found* folders but none of them are new (they were all already selected), emit `warnings.warn("fupi: step '<step>' in '<name>' selected no new folders", UserWarning, stacklevel=3)` (adjust the stack level so it points near the user's import) and carry on. A step that finds no folders at all because the tree or ancestor chain ran out is silent, never a warning. This is a warning, never an error. Do not compare against the pre-existing `sys.path` for this, or repeat imports would warn.
 
**Hook:** a small `importlib.abc.MetaPathFinder`, registered once in `sys.meta_path` from `fupi/__init__.py`.
- It handles only the fullname `fupi.<name>` where `<name>` matches the grammar.
- It returns a spec whose loader runs the path-adding logic on `exec_module`.
- It returns `None` for everything else, so normal imports are untouched.
- Use only documented stdlib APIs.
**Catch to handle: importing `fupi.up1` first runs `fupi/__init__.py`, which performs the bare-import behavior.** Do not sniff the import statement to avoid it. Instead, track exactly which paths the bare run added. When a shortcut module runs, first remove those bare-run paths that were not already on `sys.path` before fupi ran, then apply the shortcut. A shortcut therefore *replaces* the bare default and is never added on top of it. Add a test for this.
 
## Sanity limit
 
- Environment variable `FUPI_DIR_LIMIT` sets the maximum number of paths one `import fupi` / `import fupi.<name>` may select (the whole name, all groups, including the anchor). It defaults to `1000` when missing. Read it at run time, so `os.environ` set before the import works. A value that is not an integer >= 1 raises `ValueError` naming the variable.
- Purpose: names like `updown` or `up100down100` would otherwise put nearly every directory on the machine on `sys.path`.
- Enforce it **incrementally while walking**: raise as soon as the selection exceeds the limit, so the walk never crawls a whole disk first. Raise before modifying `sys.path`, so a failed run changes nothing.
- Raise a `FupiLimitError` (a small `RuntimeError` subclass defined in the package) whose message explains, in plain words:
  1. what happened (the name, the anchor, and that the limit of N was exceeded);
  2. why it is a problem (huge `sys.path` slows every import, makes module-name collisions and wrong-module imports likely, and usually means the name is broader than intended);
  3. what to do: narrow the name (for example `down2` instead of `down`), or raise the limit by setting `FUPI_DIR_LIMIT` (for example `FUPI_DIR_LIMIT=5000`) before importing fupi.

## Skip patterns
 
- `fupi.FUPI_DEFAULT_SKIP_DIR_PATTERNS`: a public, never-mutated tuple of regexes. It covers:
  - dot-prefixed and underscore-prefixed names (`\..*`, `_.*`)
  - `venv.*`, `env`, `.*\.egg-info`, `node_modules`
  - the old defaults `old.*`, `bkup*|backup*`
  - use raw strings (the old list had an invalid-escape `SyntaxWarning`)
- `fupi.skip_dir_patterns`: the active value. At package init it is `list(DEFAULT) + env patterns`.
- Users may assign a list, tuple or set, or a single string, which is treated as a one-item list. Normalize at *use time*, not with property magic. Assigning replaces everything, and `fupi.skip_dir_patterns = fupi.FUPI_DEFAULT_SKIP_DIR_PATTERNS` resets.
- Env var `FUPI_SKIP_DIR_PATTERNS` is comma-separated and **appends** to the defaults. Strip whitespace and surrounding quotes, and ignore blank entries. Document that commas inside a regex are not supported.
- Match with `re.fullmatch` against each directory name (not full paths and never ancestors above the anchor). This changes the old prefix-match behavior, so call it out in the README.
- Prune skipped directories during the walk (`os.walk` with in-place `dirnames` filtering) so `.git`, `node_modules` and the like are never descended into.
- Directories that are chosen explicitly (the anchor, the parent, an ancestor) are never skip-tested.
- Known limitation to document: an in-code override of `skip_dir_patterns` only affects shortcut imports that run afterward, because the bare run happens during `import fupi`. The env var affects everything.


## Removed in 2.0.0
 
`ManualFupi`, `sys_path_history` and rollback, `shortest_path`, `FUPI_ADD_DIR_NAMES`, the `add_dir_names` and `skip_dir_patterns` constructor args, the default `src/test/app/main/mcp` name-matching, and all CWD-based scanning.
 
## Repo housekeeping
 
- Bump the version to `2.0.0` in `pyproject.toml`.
- Delete the old tests and `test/fupi.env`, and add new tests (below).
- Rewrite the README short: the 2-word usage, the shortcut grammar table, skip patterns, the "not a best practice" note, and a migration note from 1.x.  Add "breaking change from v1" note.
- Fix `publish.sh`: remove the stray `setop` line, stop hard-coding `~/Dev/fupi`, and drop the `setuptools<68` pin that conflicts with `pyproject.toml`.

## Tests
 
Use tmp directory trees, and run scripts via `subprocess` from **different working directories** to prove CWD independence. Cover:
1. Bare import: the anchor, its subdirectories and the parent are added, and the parent's siblings are not.
2. The same result when the script is run from a different CWD.
3. Ancestor names such as `old_work` or `src` above the anchor do not affect results.
4. Each step and group form (`up1`, `up2` including that the parent is added too, `down`, `down1`, `up1down2`, `down2up1`, `down2up3`, `up2down1`), plus `down100` and `up100` (no error, no warning, and the filesystem root is never added).
   4a. Traversal semantics: `up1down2` selects `P`, its children and their children; `down2up1` selects exactly the same folders as `down2` (the anchor, children and grandchildren); `down2up3` selects the same set as `down2_up1`; and `down_up1` selects the same set as bare `import fupi` from a file.
   4b. Multi-group names are unioned from a fresh anchor per group (`down2_up1`, `up1down2_up3`, and a three-group name such as `up2down1_up4down1_up6down1`; there is no cap on group count). Group order does not change the result, and overlaps produce no duplicate `sys.path` entries.
   4c. Warnings (use `pytest.warns` / `warnings.catch_warnings`): `down2up1` warns, `down2up3` does not, `up1down2` does not, and re-importing the same shortcut does not warn.
   4d. Sanity limit: with `FUPI_DIR_LIMIT` set small (for example 5) on a tmp tree, an over-limit name raises `FupiLimitError`; the message mentions what happened, why it is bad, and `FUPI_DIR_LIMIT`; `sys.path` is unchanged after the failure; raising the variable lets the same name succeed; the default is 1000 when unset; a non-integer or `0` value raises `ValueError`.
   4e. A step that finds nothing (`down1` in a leaf folder) is silent and later steps still run from the unchanged endpoints (`down1up1` in a leaf folder adds the parent).
5. A shortcut replaces the bare-run paths, and importing it twice causes no duplicates.
6. Invalid names (`up0`, `down0`, `up`, `sideways`, `up1__down`, `_up1`, `up1_`) raise `ModuleNotFoundError`.
7. Skip patterns: defaults, string assignment, tuple/set assignment, the reset-to-default idiom, env append, and `fullmatch` semantics.
8. The REPL/no-`__file__` fallback: bare `import fupi` selects `up1_down1` from the CWD (also from `/` and `~` without hitting the limit), and `import fupi.up1_down` restores the full subtree.
Run the tests in subprocesses or isolate `sys.path`, so the old test-order dependence cannot return.
 
## Open questions (proposed defaults in parentheses)
 
- Whether to keep a tiny explicit function such as `fupi.add(...)` (no; out of scope for 2.0).
- Whether anchoring at a symlinked script resolves to the real path (yes).
 