#!/usr/bin/env python3
"""Which python tests of OURS the `checks` job runs with pytest, for the junit the named hook tests judge reads (`junit-py`, nodes `py:<path>::<name>`).

The tree the job materializes holds Mozilla's python tests (marionette, mach, ...) and ours; only ours are run. Ours are the files the series ADDS: the
`test_*.py` of `<group>/<folder>/src/<path in the tree>`. Left out, on purpose: scripts/ci/ (the CI's own cases, run by test_ci.py, with their own runners). A file with no `def test_` / `class Test` has nothing for pytest to collect (its checks
run in `__main__`), so it is not listed: a hook cannot name a test it does not have.

    python3 scripts/ci/py_junit.py list --series .series --tree .

Prints the paths in the tree, one per line, sorted.

    python3 scripts/ci/py_junit.py ran junit-py/checks/tree-tests.xml

Exits 1 when the junit of the pytest run has no test that ran: the file is missing, it has no testcase, or every testcase is a collection error (pytest
cannot import a file and, without --continue-on-collection-errors, stops there; run 45025164169 wrote one error and no test). A test that FAILED ran: its
verdict is the judge's. Names the errors.
"""
from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

#: Folders of the tree whose python tests are not for pytest in `checks` (see the docstring).
SKIPPED = ("scripts/ci/",)
HAS_TESTS = re.compile(r"^(?:def test_|async def test_|class Test)", re.M)


def ours(series: Path, tree: Path) -> list:
    """The python tests of ours that exist in `tree`, collectable by pytest, as paths in the tree."""
    found = set()
    for src in sorted(set(Path(series).glob("*/*/src")) | set(Path(series).glob("*/*/*/src"))):  # folders two or three deep
        for path in src.rglob("test_*.py"):
            rel = path.relative_to(src).as_posix()
            if rel.startswith(SKIPPED) or not (Path(tree) / rel).is_file():
                continue
            if HAS_TESTS.search(path.read_text(encoding="utf-8", errors="replace")):
                found.add(rel)
    return sorted(found)


def ran(junit: Path) -> tuple:
    """-> (True, "") when a testcase of `junit` ran (passed, failed or skipped); else (False, why, naming the errors)."""
    path = Path(junit)
    if not path.is_file():
        return False, "%s does not exist: pytest wrote no junit" % path
    try:
        cases = list(ET.parse(path).getroot().iter("testcase"))
    except ET.ParseError as exc:
        return False, "%s is not a junit file: %s" % (path, exc)
    if not cases:
        return False, "%s has no testcase: no test of the tree ran" % path
    errors = [c for c in cases if c.find("error") is not None]
    if len(errors) == len(cases):
        lines = []
        for case in errors:
            node = case.find("error")
            text = [x.strip() for x in (node.text or "").strip().splitlines() if x.strip()]
            lines.append("  %s: %s | %s" % (case.get("name") or "?", node.get("message") or "error", text[-1] if text else ""))
        return False, "%s has only errors (%d), no test ran:\n%s" % (path, len(errors), "\n".join(lines))
    return True, ""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    ls = sub.add_parser("list")
    ls.add_argument("--series", required=True, type=Path)
    ls.add_argument("--tree", required=True, type=Path)
    rn = sub.add_parser("ran")
    rn.add_argument("junit", type=Path)
    args = ap.parse_args(argv)
    if args.cmd == "ran":
        ok, why = ran(args.junit)
        if not ok:
            print("py_junit: " + why, file=sys.stderr)
        return 0 if ok else 1
    files = ours(args.series, args.tree)
    for rel in files:
        print(rel)
    if not files:
        print("py_junit: no python test of ours in %s" % args.series, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
