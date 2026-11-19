"""fupi 2.0 tests. Every fupi import runs in a fresh subprocess, so sys.path never leaks between tests."""
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"

PROBE = """\
import json, sys, warnings
before = list(sys.path)
with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
{body}
import fupi
print(json.dumps({{"new": [p for p in sys.path if p not in before], "sys_path": sys.path,
                   "paths_added": fupi.paths_added, "warnings": [str(w.message) for w in caught]}}))
"""


def run(where, body, cwd=None, env=None, check=True):
    """Write a probe script into `where`, run it from `cwd`, return (parsed JSON or None, CompletedProcess)."""
    script = where / "probe_script.py"
    script.write_text(PROBE.format(body=textwrap.indent(textwrap.dedent(body).strip(), "    ")))
    full_env = {k: v for k, v in os.environ.items() if not k.startswith("FUPI_")}
    full_env.update(PYTHONPATH=str(SRC), **(env or {}))
    proc = subprocess.run([sys.executable, str(script)], cwd=cwd or where.anchor, env=full_env,
                          capture_output=True, text=True)
    if check:
        assert proc.returncode == 0, proc.stderr
    return (json.loads(proc.stdout) if proc.returncode == 0 else None), proc


def selected(where, body, **kw):
    """The set of folders a run selected: everything it added, plus the anchor (already sys.path[0])."""
    out, _ = run(where, body, **kw)
    assert out["new"] == sorted(out["new"]), "paths must be appended in sorted order"
    assert len(out["sys_path"]) == len(set(out["sys_path"])), "sys.path has duplicates"
    return set(out["new"]) | {str(where)}


@pytest.fixture
def tree(tmp_path):
    """r/GGG/GG/G/P/A, with children: A{c1/g1/gg1, c2, .git/h, node_modules/m, venv_x}, P{S/s1/s1a}, G{U}, GG{V}."""
    r = tmp_path.resolve() / "r"
    GG = r / "GGG" / "GG"
    G = GG / "G"
    P = G / "P"
    A = P / "A"
    d = {"r": r, "GGG": r / "GGG", "GG": GG, "G": G, "P": P, "A": A,
         "c1": A / "c1", "g1": A / "c1" / "g1", "gg1": A / "c1" / "g1" / "gg1", "c2": A / "c2",
         "git": A / ".git", "nm": A / "node_modules", "venv": A / "venv_x",
         "S": P / "S", "s1": P / "S" / "s1", "s1a": P / "S" / "s1" / "s1a", "U": G / "U", "V": GG / "V"}
    for path in [*d.values(), A / ".git" / "h", A / "node_modules" / "m"]:
        path.mkdir(parents=True, exist_ok=True)
    return {k: v if k == "A" else str(v) for k, v in d.items()}


def S(t, *names):
    return {str(t["A"])} | {t[n] for n in names}


# 1, 2: bare import, CWD independence
def test_bare_import(tree):
    got = selected(tree["A"], "import fupi")
    assert got == S(tree, "c1", "g1", "gg1", "c2", "P")
    assert tree["S"] not in got and tree["G"] not in got  # parent's other children / grandparent excluded


@pytest.mark.parametrize("cwd", ["/", "P", "c1", "U"])
def test_bare_import_cwd_independent(tree, cwd):
    where = cwd if cwd == "/" else tree[cwd]
    assert selected(tree["A"], "import fupi", cwd=where) == S(tree, "c1", "g1", "gg1", "c2", "P")


# 3: names above the anchor are never skip-tested
def test_ancestor_names_do_not_matter(tmp_path):
    anchor = tmp_path.resolve() / "old_work" / "src" / "_proj" / "A"
    (anchor / "child").mkdir(parents=True)
    got = selected(anchor, "import fupi")
    assert got == {str(anchor), str(anchor / "child"), str(anchor.parent)}


# 4: every step form
@pytest.mark.parametrize("name, expected", [
    ("up1", ["P"]),
    ("up2", ["P", "G"]),
    ("down", ["c1", "g1", "gg1", "c2"]),
    ("down1", ["c1", "c2"]),
    ("down100", ["c1", "g1", "gg1", "c2"]),
    ("up1down2", ["P", "S", "c1", "c2", "s1"]),
    ("down2up1", ["c1", "c2", "g1"]),
    ("down2up3", ["c1", "c2", "g1", "P"]),
    ("up2down1", ["P", "G", "U"]),
    ("down2_up1", ["c1", "c2", "g1", "P"]),
    ("up1down2_up3", ["P", "S", "c1", "c2", "s1", "G", "GG"]),
    ("down_up1", ["c1", "g1", "gg1", "c2", "P"]),
])
def test_step_forms(tree, name, expected):
    assert selected(tree["A"], f"import fupi.{name}") == S(tree, *expected)


def test_up100_stops_below_root(tree):
    out, proc = run(tree["A"], "import fupi.up100")
    assert out["warnings"] == [] and "Warning" not in proc.stderr
    assert tree["r"] in out["new"] and str(Path(tree["r"]).parents[-2]) in out["new"]
    assert not any(p == str(Path(p).parent) for p in out["new"]), "filesystem root added"


# 4a: traversal equivalences
@pytest.mark.parametrize("a, b", [("up", "up100"), ("updown1", "up100down1"), ("down2up1", "down2"), ("down2up3", "down2_up1"), ("down_up1", "")])
def test_equivalences(tree, a, b):
    rhs = f"import fupi.{b}" if b else "import fupi"
    assert selected(tree["A"], f"import fupi.{a}") == selected(tree["A"], rhs)


# 4b: groups are a union from a fresh anchor, order-independent, no duplicates
def test_multi_group_union(tree):
    groups = ["up2down1", "up4down1", "up6down1"]
    union = set().union(*(selected(tree["A"], f"import fupi.{g}") for g in groups))
    assert selected(tree["A"], "import fupi." + "_".join(groups)) == union
    assert selected(tree["A"], "import fupi." + "_".join(reversed(groups))) == union
    assert selected(tree["A"], "import fupi.up1_down2_up1_down1") == selected(tree["A"], "import fupi.down2_up1")


# 4c: redundancy warnings
@pytest.mark.parametrize("name, warns", [("down2up1", True), ("down2up3", False), ("up1down2", False)])
def test_redundancy_warning(tree, name, warns):
    out, _ = run(tree["A"], f"import fupi.{name}")
    expected = [f"fupi: step 'up1' in '{name}' selected no new folders"] if warns else []
    assert out["warnings"] == expected


def test_reimport_does_not_warn(tree):
    out, _ = run(tree["A"], "import fupi.up1down2\nimport fupi.up1down2\nimport importlib, fupi\n"
                            "importlib.import_module('fupi.up1down2')")
    assert out["warnings"] == []


def test_redundancy_warning_points_at_user_import(tree):
    (tree["A"] / "plain.py").write_text("import fupi.down2up1\n")
    env = {**os.environ, "PYTHONPATH": str(SRC)}
    proc = subprocess.run([sys.executable, str(tree["A"] / "plain.py")], env=env, capture_output=True, text=True)
    assert "plain.py:1: UserWarning: fupi: step 'up1'" in proc.stderr


# 4d: sanity limit
@pytest.fixture
def small(tmp_path):
    """P/A/c plus 5 siblings of A: bare import selects 3 folders, `up1down` selects 9."""
    anchor = tmp_path.resolve() / "P" / "A"
    (anchor / "c").mkdir(parents=True)
    for i in range(5):
        (anchor.parent / f"sib{i}").mkdir()
    return anchor


LIMIT_BODY = """
import fupi, sys
snapshot = list(sys.path)
try:
    import fupi.up1down
except fupi.FupiLimitError as e:
    print("LIMIT:" + json.dumps(str(e)), file=sys.stderr)
    assert sys.path == snapshot, "sys.path changed after a failed run"
"""


def test_limit_exceeded(small):
    out, proc = run(small, LIMIT_BODY, env={"FUPI_DIR_LIMIT": "5"})
    msg = json.loads(proc.stderr.split("LIMIT:")[1])
    assert "fupi.up1down" in msg and str(small) in msg and "limit of 5" in msg  # what happened
    assert "slows every import" in msg and "collisions" in msg  # why it is bad
    assert "FUPI_DIR_LIMIT" in msg and "down2" in msg  # what to do
    assert str(small.parent / "sib0") not in out["sys_path"]


def test_limit_raised_lets_it_succeed(small):
    out, proc = run(small, LIMIT_BODY, env={"FUPI_DIR_LIMIT": "9"})
    assert "LIMIT:" not in proc.stderr
    assert str(small.parent / "sib0") in out["sys_path"]


def test_limit_default_is_1000(small):
    out, proc = run(small, "import fupi\nprint('LIMIT', fupi._limit(), file=sys.stderr)")
    assert "LIMIT 1000" in proc.stderr


@pytest.mark.parametrize("value", ["abc", "0", "-3", "1.5", ""])
def test_limit_invalid_value(small, value):
    _, proc = run(small, "import fupi", env={"FUPI_DIR_LIMIT": value}, check=False)
    assert proc.returncode != 0 and "ValueError" in proc.stderr and "FUPI_DIR_LIMIT" in proc.stderr


# 4e: a step that finds nothing is silent and leaves the endpoints unchanged
def test_empty_step_is_silent(tree):
    leaf = Path(tree["c2"])
    out, _ = run(leaf, "import fupi.down1")
    assert out["warnings"] == [] and out["new"] == []
    assert selected(leaf, "import fupi.down1up1") == {tree["c2"], str(tree["A"])}


# 5: shortcuts replace the bare run
def test_shortcut_replaces_bare_run(tree):
    out, _ = run(tree["A"], "import fupi\nimport fupi.up1\nimport fupi.up1")
    assert out["new"] == [tree["P"]] and out["paths_added"] == [tree["P"]]


def test_bare_paths_already_on_sys_path_are_kept(tree):
    body = f"sys.path.append({tree['c1']!r})\nimport fupi.up1"
    out, _ = run(tree["A"], body)
    assert tree["c1"] in out["sys_path"] and tree["g1"] not in out["sys_path"]


def test_two_shortcuts_accumulate(tree):
    out, _ = run(tree["A"], "import fupi.up1\nimport fupi.down1\nimport fupi.up1")
    assert set(out["new"]) == {tree["P"], tree["c1"], tree["c2"]}
    assert len(out["sys_path"]) == len(set(out["sys_path"]))


# 6: invalid names
@pytest.mark.parametrize("name", ["up0", "down0", "upp1", "sideways", "up1__down", "_up1", "up1_", "up1down0"])
def test_invalid_names(tree, name):
    body = f"import importlib\ntry:\n    importlib.import_module('fupi.{name}')\nexcept ModuleNotFoundError:\n" \
           "    print('MNF', file=sys.stderr)"
    _, proc = run(tree["A"], body)
    assert "MNF" in proc.stderr


# 7: skip patterns
def test_default_skip_patterns(tree):
    out, _ = run(tree["A"], "import fupi\nassert isinstance(fupi.FUPI_DEFAULT_SKIP_DIR_PATTERNS, tuple)\n"
                            "assert fupi.skip_dir_patterns == list(fupi.FUPI_DEFAULT_SKIP_DIR_PATTERNS)")
    assert not {tree["git"], tree["nm"], tree["venv"]} & set(out["new"])


@pytest.mark.parametrize("value", ["'c1'", "('c1', 'x')", "{'c1'}", "['c1']"])
def test_skip_assignment_replaces_everything(tree, value):
    got = selected(tree["A"], f"import fupi\nfupi.skip_dir_patterns = {value}\nimport fupi.down")
    assert tree["c1"] not in got and tree["g1"] not in got and tree["c2"] in got
    assert tree["git"] in got  # defaults were replaced, not extended


def test_skip_reset_to_default(tree):
    body = "import fupi\nfupi.skip_dir_patterns = 'c1'\nfupi.skip_dir_patterns = fupi.FUPI_DEFAULT_SKIP_DIR_PATTERNS\n" \
           "import fupi.down"
    got = selected(tree["A"], body)
    assert tree["c1"] in got and tree["git"] not in got


def test_skip_env_appends(tree):
    env = {"FUPI_SKIP_DIR_PATTERNS": " 'c1' , ,\"c2\" "}
    got = selected(tree["A"], "import fupi\nassert fupi.skip_dir_patterns[-2:] == ['c1', 'c2'], fupi.skip_dir_patterns",
                   env=env)
    assert got == S(tree, "P")


@pytest.mark.parametrize("pattern, skipped", [("c", False), ("c.*", True), ("1", False), (".1", True)])
def test_skip_uses_fullmatch(tree, pattern, skipped):
    got = selected(tree["A"], "import fupi", env={"FUPI_SKIP_DIR_PATTERNS": pattern})
    assert (tree["c1"] not in got) is skipped


# 8: no __file__ (REPL / notebook / -c) falls back to the CWD
def no_file_run(module, cwd):
    """Run `import <module>` via -c and via stdin (no __file__ either way); return the added paths."""
    code = f"import sys, json; before = list(sys.path); import {module}; " \
           "print(json.dumps([p for p in sys.path if p not in before]))"
    env = {k: v for k, v in os.environ.items() if not k.startswith("FUPI_")}
    env["PYTHONPATH"] = str(SRC)
    results = []
    for argv in ([sys.executable, "-c", code], [sys.executable, "-"]):
        proc = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True,
                              input=code if argv[-1] == "-" else None)
        assert proc.returncode == 0, proc.stderr
        results.append(set(json.loads(proc.stdout)))
    assert results[0] == results[1]
    return results[0]


@pytest.mark.parametrize("module, expected", [
    ("fupi", ["c1", "c2", "P"]),  # no-file bare default is up1_down1, not the whole subtree
    ("fupi.down1", ["c1", "c2"]),
    ("fupi.up1_down", ["c1", "g1", "gg1", "c2", "P"]),  # opt back into the file-style default
])
def test_no_file_falls_back_to_cwd(tree, module, expected):
    assert no_file_run(module, tree["A"]) == S(tree, *expected)


@pytest.mark.parametrize("cwd", ["/", str(Path.home())])
def test_no_file_bare_import_from_big_folders_stays_under_limit(cwd):
    no_file_run("fupi", cwd)  # previously hit FUPI_DIR_LIMIT from / with the unlimited default


# symlinked script anchors at its real location
def test_symlinked_script_resolves(tree, tmp_path):
    (tree["A"] / "real.py").write_text("import sys, fupi\nprint(fupi.paths_added)")
    link_dir = tmp_path.resolve() / "elsewhere"
    link_dir.mkdir()
    (link_dir / "link.py").symlink_to(tree["A"] / "real.py")
    env = {**os.environ, "PYTHONPATH": str(SRC)}
    proc = subprocess.run([sys.executable, str(link_dir / "link.py")], env=env, capture_output=True, text=True)
    assert tree["c1"] in proc.stdout and tree["P"] in proc.stdout


# fupi.refresh(): re-run every fupi import with the current skip patterns
def test_refresh_after_append_removes_newly_skipped(tree):
    out, _ = run(tree["A"], "import fupi\nfupi.skip_dir_patterns.append('c1')\nfupi.refresh()")
    assert set(out["new"]) == {tree["c2"], tree["P"]} and out["paths_added"] == out["new"]


def test_refresh_after_removing_a_pattern_adds_folders_back(tree):
    body = "import fupi\nfupi.skip_dir_patterns.remove(r'\\..*')\nfupi.refresh()"
    out, _ = run(tree["A"], body)
    assert tree["git"] in out["new"] and str(Path(tree["git"]) / "h") in out["new"]


def test_refresh_reset_to_default(tree):
    body = "import fupi\nfupi.skip_dir_patterns = 'c.*'\nfupi.refresh()\n" \
           "fupi.skip_dir_patterns = fupi.FUPI_DEFAULT_SKIP_DIR_PATTERNS\nfupi.refresh()"
    assert selected(tree["A"], body) == selected(tree["A"], "import fupi")


def test_refresh_reruns_every_shortcut(tree):
    body = "import fupi.up1down2\nimport fupi.up2\nfupi.skip_dir_patterns.append('S')\nfupi.refresh()"
    assert selected(tree["A"], body) == S(tree, "P", "G", "c1", "c2")


def test_shortcut_after_refresh_still_replaces_bare_run(tree):
    body = "import fupi\nfupi.skip_dir_patterns.remove(r'\\..*')\nfupi.refresh()\nimport fupi.up1"
    out, _ = run(tree["A"], body)  # refresh added .git; the shortcut must remove it too
    assert out["new"] == [tree["P"]] and out["paths_added"] == [tree["P"]]


def test_refresh_does_not_repeat_warnings(tree):
    out, _ = run(tree["A"], "import fupi.down2up1\nimport fupi\nfupi.refresh()")
    assert len(out["warnings"]) == 1


def test_refresh_over_limit_leaves_sys_path_unchanged(small):
    (small / "_h1").mkdir()
    (small / "_h2").mkdir()
    body = """
    import fupi
    snapshot = list(sys.path)
    fupi.skip_dir_patterns = []
    try:
        fupi.refresh()
    except fupi.FupiLimitError:
        print("LIMIT", file=sys.stderr)
    assert sys.path == snapshot
    """
    _, proc = run(small, body, env={"FUPI_DIR_LIMIT": "3"})
    assert "LIMIT" in proc.stderr
