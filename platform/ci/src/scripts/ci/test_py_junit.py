#!/usr/bin/env python3
"""scripts/ci/py_junit.py: which python tests of ours the `checks` job runs with pytest.

Red cases first: a Mozilla test of the tree is not ours and is not listed, a file of ours that the tree does not have is not listed, a script with nothing for
pytest to collect is not listed, scripts/ci/ is left out, a series with none of ours exits 1 (a `checks` step with no test must not be green).

    python3 scripts/ci/test_py_junit.py
"""
from __future__ import annotations

import contextlib
import io
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import py_junit as pj  # noqa: E402


def put(root: Path, rel: str, text: str = "def test_x():\n    pass\n") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def cases() -> list:
    out = []

    def add(name, ok):
        out.append(("py_junit: " + name, bool(ok)))

    with tempfile.TemporaryDirectory() as tmp:
        series, tree = Path(tmp) / "series", Path(tmp) / "tree"
        for rel in ("modules/libpref/test/test_stealth_a.py", "scripts/test_b.py", "scripts/ci/test_c.py",
                    "modules/libpref/test/test_not_in_tree.py", "scripts/test_main_only.py"):
            put(series / "grp" / "fold" / "src", rel, "import sys\nassert True\n" if rel.endswith("main_only.py") else "def test_x():\n    pass\n")
            if "not_in_tree" not in rel:
                put(tree, rel)
        put(tree, "browser/components/x/marionette/test_mozilla.py")
        put(series / "grp" / "other" / "src", "tools/test_class_style.py", "class TestIt:\n    def test_a(self):\n        pass\n")
        put(tree, "tools/test_class_style.py")
        put(series / "fingerprint" / "area" / "deep" / "src", "tools/test_three_deep.py")
        put(tree, "tools/test_three_deep.py")
        add("the tests of ours with something to collect are listed, sorted, as paths in the tree (a feature three deep too)",
            pj.ours(series, tree) == ["modules/libpref/test/test_stealth_a.py", "scripts/test_b.py", "tools/test_class_style.py",
                                      "tools/test_three_deep.py"])
        add("scripts/ci/ is left out", not any(p.startswith(pj.SKIPPED) for p in pj.ours(series, tree)))
        add("a Mozilla test of the tree (not in the series' src) is not listed", "browser/components/x/marionette/test_mozilla.py" not in pj.ours(series, tree))
        add("a file of ours that the tree does not have, and a script with no `def test_`, are not listed",
            "modules/libpref/test/test_not_in_tree.py" not in pj.ours(series, tree) and "scripts/test_main_only.py" not in pj.ours(series, tree))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = pj.main(["list", "--series", str(series), "--tree", str(tree)])
        add("main prints the list and exits 0", code == 0 and buf.getvalue().split() == pj.ours(series, tree))

    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "series" / "g" / "f" / "src").mkdir(parents=True)
        with contextlib.redirect_stderr(io.StringIO()):
            code = pj.main(["list", "--series", str(Path(tmp) / "series"), "--tree", str(Path(tmp))])
        add("a series with no python test of ours exits 1 (a step with no test is not green)", code == 1)

    # --- `ran`: the junit of the checks' pytest holds a test that ran
    def junit(body: str) -> str:
        return '<?xml version="1.0"?><testsuites><testsuite name="pytest">%s</testsuite></testsuites>' % body

    err = '<testcase classname="" name="scripts.test_a"><error message="collection failure">ModuleNotFoundError: No module named fontTools</error></testcase>'
    passed = '<testcase classname="scripts.test_b" name="test_x"/>'
    failed = '<testcase classname="scripts.test_b" name="test_y"><failure message="assert 1 == 2">boom</failure></testcase>'
    with tempfile.TemporaryDirectory() as tmp:
        def run(body=None):
            path = Path(tmp) / "t.xml"
            if path.exists():
                path.unlink()
            if body is not None:
                path.write_text(junit(body), encoding="utf-8")
            err_out = io.StringIO()
            with contextlib.redirect_stderr(err_out):
                code = pj.main(["ran", str(path)])
            return code, err_out.getvalue()

        code, msg = run(err + err.replace("test_a", "test_c"))
        add("ran: only collection errors is red, and the message names them", code == 1 and "scripts.test_a" in msg and "scripts.test_c" in msg and "fontTools" in msg)
        add("ran: a junit with no testcase is red", run("")[0] == 1)
        add("ran: one passed test among the errors is green", run(err + passed)[0] == 0)
        add("ran: a failed test is green, it ran (its verdict is the judge's)", run(failed)[0] == 0 and run(err + failed)[0] == 0)
        add("ran: a missing file is red", run(None)[0] == 1)
    return out


if __name__ == "__main__":
    results = cases()
    for label, ok in results:
        print(("ok    " if ok else "FAIL  ") + label)
    print("%d/%d cases as expected" % (sum(ok for _, ok in results), len(results)))
    sys.exit(0 if all(ok for _, ok in results) else 1)
