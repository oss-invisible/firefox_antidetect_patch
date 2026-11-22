#!/usr/bin/env python3
"""The named hook tests judge: every test a HOOKS.json names exists in this run's results and passed.

Each folder of the series has a HOOKS.json, and each hook of it names the test that proves it (`test`, the grammar of tools/hooks_list.py). The candidate used to
run only the gtests of its filter and the wrapper suites of ci/required-suites.json, so a hook whose test nobody ran, or whose test had been renamed away, was green
(red team H1a and H1b, 2026-11-22). This script reads the list the series carries and the RESULTS OF THIS RUN, and is red for every named test that

  - is not in any result of the run (a name that does not exist, a test removed from a leg, a gtest renamed, a leg that did not report), or
  - is skipped, or did not pass in some result that has it, or
  - (gtest) is not matched by the candidate's gtest filter: it could not have run (the static check).

A hook that the pm declared untestable (`untestable` with `pm: "approvato"`, no test) has nothing to judge. A hook with no test is the debt of `hooks_list.py check`
(rule T1), not of this judge; but a series that names no test at all is red, because a judge that judged nothing is not a verdict (--min-named).

The results it reads, all of this run's own artifacts, no network:

  --results DIR          result-<suite>-<os>/*.xml        the junit of the gate's wrapper legs (pytest, xunit2): wrapper:<path>::<test>
  --gtest-reports DIR    gtest-reports-<leg>/<Suite>.json the gtest json of each suite (platform/ci/src/scripts/ci/gtest_run.py): gtest:<Suite>.<Name>
  --junit DIR            junit-node/<tree path>.xml       node --test, one file per test file (the `checks` job): node:<path>#<title>
                         junit-py/*.xml                   a tree python test:                                     py:<path>::<name>
                         junit-xpcshell/*.xml             an xpcshell test:                                       xpcshell:<path>#<test>
                         junit-cargo/*.xml                a cargo test:                                           cargo:<crate>::<test path>
                         (junit-py, junit-xpcshell and junit-cargo are read when a run has them; no leg writes them today, so a test of those kinds is red)

`wrapper:` and `py:` accept `::invariant:<name>` and `::case:<name>`: the case is looked for as the test name or as the id of its parameter.

    python3 tools/hook_tests_judge.py --series .series --results results --gtest-reports gtest-reports --junit junit \\
        --gtest-filter "$FILTER" --gtests true [--gtest-run PATH] [--min-named 1] [--summary FILE]

Its cases: tools/tests/test_hook_tests_judge.py. Stdlib only; it imports nothing of the Firefox tree (the one file it loads, gtest_run.py, is read for its NOT_ON table only).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

PM_APPROVED = "approvato"
PLATFORMS = ("linux", "win")
PASSED = "passed"


# --------------------------------------------------------------------------- the list
def series_folders(series: Path) -> list:
    """The folders of the series that carry a HOOKS.json: those SERIES names (it is the list the engine applies), and, in a checkout with no
    SERIES, every HOOKS.json outside a src/ tree."""
    series = Path(series)
    listed = series / "SERIES"
    if listed.is_file():
        names = listed.read_text(encoding="utf-8").split()
    else:
        names = [p.parent.relative_to(series).as_posix() for p in sorted(series.rglob("HOOKS.json"))]
    seen, out = set(), []
    for name in names:
        if name not in seen and "/src/" not in "/%s/" % name and (series / name / "HOOKS.json").is_file():
            seen.add(name)
            out.append(name)
    return out


def is_untestable(entry: dict) -> bool:
    """The pm declared the hook untestable: a reason, `pm: "approvato"`, no test (as tools/hooks_list.py)."""
    return (isinstance(entry.get("untestable"), str) and bool(entry["untestable"].strip()) and entry.get("pm") == PM_APPROVED
            and not entry.get("test"))


def collect(series: Path):
    """-> (named, unnamed, untestable, problems): named is [(folder, hook file, test ref)] without repeats (the first hook of a folder that names it
    stands for the others), the other two are counts of hooks, problems are the HOOKS.json that cannot be read."""
    named, seen, unnamed, untestable, problems = [], set(), 0, 0, []
    for folder in series_folders(series):
        path = Path(series) / folder / "HOOKS.json"
        try:
            entries = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            problems.append("%s cannot be read: %s" % (path.as_posix(), exc))
            continue
        if not isinstance(entries, list):
            problems.append("%s is not a list" % path.as_posix())
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                problems.append("%s has an entry that is not an object" % path.as_posix())
                continue
            ref = entry.get("test")
            if isinstance(ref, str) and ref.strip():
                key = (folder, str(entry.get("file", "?")), ref.strip())
                if key not in seen:
                    seen.add(key)
                    named.append(key)
            elif is_untestable(entry):
                untestable += 1
            else:
                unnamed += 1
    return named, unnamed, untestable, problems


# --------------------------------------------------------------------------- the results
def junit_outcome(case) -> str:
    tags = {child.tag for child in case}
    if "error" in tags:
        return "error"
    if "failure" in tags:
        return "failed"
    if "skipped" in tags:
        return "skipped"
    return PASSED


def parse_junit(path: Path):
    """-> [(classname, name, outcome)] of every testcase of a junit file."""
    root = ET.parse(str(path)).getroot()
    return [(case.get("classname") or "", case.get("name") or "", junit_outcome(case)) for case in root.iter("testcase")]


def node_id(classname: str, name: str) -> str:
    """`tests.test_x` + `test_y[p]` -> `tests/test_x.py::test_y[p]`; a capitalised segment is a class and goes after the file
    (the same reading as the wrapper's scripts/ci_verdict.py)."""
    parts = [p for p in classname.split(".") if p]
    module, klass = [], []
    for i, part in enumerate(parts):
        if part[:1].isupper() and module:
            klass = parts[i:]
            break
        module.append(part)
    if not module:
        return name
    return "::".join(["/".join(module) + ".py"] + klass + [name])


class Results:
    def __init__(self):
        self.gtest = {}        # (suite, name) -> {platform: [outcome]}
        self.gtest_legs = set()  # the platforms that have a gtest-reports-<leg> folder
        self.pytest = []       # (source, node id, outcome): source is "wrapper" or "py"
        self.node = {}         # tree path -> [(name, outcome)]
        self.xpcshell = []     # (classname, name, outcome)
        self.cargo = []        # (classname, name, outcome)
        self.files = 0         # result files read
        self.problems = []


def gtest_outcome(case: dict) -> str:
    if case.get("failures"):
        return "failed"
    result = str(case.get("result", "")).upper()
    status = str(case.get("status", "")).upper()
    if result == "SKIPPED":
        return "skipped"
    if status != "RUN" or result in ("SUPPRESSED", "NOTRUN"):
        return "not run (disabled or filtered out)"
    return PASSED if result in ("COMPLETED", "") else result.lower()


def read_gtest(res: Results, folder: Path) -> None:
    if not folder.is_dir():
        return
    for leg in sorted(p for p in folder.iterdir() if p.is_dir()):
        match = re.search(r"(linux|win)", leg.name)
        if not leg.name.startswith("gtest-reports") or not match:
            continue
        platform = match.group(1)
        res.gtest_legs.add(platform)
        for path in sorted(leg.rglob("*.json")):
            try:
                report = json.loads(path.read_text(encoding="utf-8"))
                suites = report["testsuites"]
            except (OSError, ValueError, KeyError, TypeError) as exc:
                res.problems.append("%s cannot be read as a gtest report: %s" % (path.as_posix(), exc))
                continue
            res.files += 1
            for suite in suites if isinstance(suites, list) else []:
                for case in suite.get("testsuite", []) if isinstance(suite, dict) else []:
                    key = (str(suite.get("name", "")), str(case.get("name", "")))
                    res.gtest.setdefault(key, {}).setdefault(platform, []).append(gtest_outcome(case))


def read_wrapper(res: Results, folder: Path) -> None:
    if not folder.is_dir():
        return
    for path in sorted(folder.rglob("*.xml")):
        try:
            cases = parse_junit(path)
        except (OSError, ET.ParseError) as exc:
            res.problems.append("%s cannot be read as junit: %s" % (path.as_posix(), exc))
            continue
        res.files += 1
        res.pytest += [("wrapper", node_id(c, n), o) for c, n, o in cases]


def read_junit(res: Results, folder: Path) -> None:
    if not folder.is_dir():
        return
    for art in sorted(p for p in folder.iterdir() if p.is_dir()):
        kind = art.name.split("-", 1)[1] if art.name.startswith("junit-") else ""
        for path in sorted(art.rglob("*.xml")):
            try:
                cases = parse_junit(path)
            except (OSError, ET.ParseError) as exc:
                res.problems.append("%s cannot be read as junit: %s" % (path.as_posix(), exc))
                continue
            res.files += 1
            if kind == "node":
                tree_path = path.relative_to(art).as_posix()[:-len(".xml")]
                res.node.setdefault(tree_path, []).extend((n, o) for _c, n, o in cases)
            elif kind == "py":
                res.pytest += [("py", node_id(c, n), o) for c, n, o in cases]
            elif kind == "xpcshell":
                res.xpcshell += cases
            elif kind == "cargo":
                res.cargo += cases
            else:
                res.problems.append("%s is in %s, which is not a kind of junit this judge knows (node, py, xpcshell, cargo)" % (path.as_posix(), art.name))


def read_results(results=None, gtest_reports=None, junit=None) -> Results:
    res = Results()
    if gtest_reports:
        read_gtest(res, Path(gtest_reports))
    if results:
        read_wrapper(res, Path(results))
    if junit:
        read_junit(res, Path(junit))
    return res


# --------------------------------------------------------------------------- the gtest filter
def _glob(pattern: str):
    return re.compile("".join(".*" if c == "*" else "." if c == "?" else re.escape(c) for c in pattern))


def filter_matches(gtest_filter: str, full_name: str) -> bool:
    """gtest's own rule: `positive:patterns-negative:patterns`, `*` and `?`, no positive pattern means all."""
    positive, _, negative = gtest_filter.partition("-")
    pos = [p for p in positive.split(":") if p] or ["*"]
    neg = [p for p in negative.split(":") if p]
    return any(_glob(p).fullmatch(full_name) for p in pos) and not any(_glob(p).fullmatch(full_name) for p in neg)


def load_not_on(path):
    """NOT_ON of gtest_run.py: the suites that do not exist on a platform. From the copy the gtest jobs ran (--gtest-run), else the one of the series this script lives in."""
    path = Path(path) if path else Path(__file__).resolve().parents[1] / "platform" / "ci" / "src" / "scripts" / "ci" / "gtest_run.py"
    spec = importlib.util.spec_from_file_location("gtest_run_for_judge", str(path))
    module = importlib.util.module_from_spec(spec)
    keep, sys.dont_write_bytecode = sys.dont_write_bytecode, True  # reading a table leaves no __pycache__ in the series
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = keep
    return {k: set(v) for k, v in module.NOT_ON.items()}


# --------------------------------------------------------------------------- judging one reference
def _worst(outcomes: list):
    """None if every outcome passed, else the sorted set of those that did not."""
    bad = sorted({o for o in outcomes if o != PASSED})
    return ", ".join(bad) if bad else None


def judge_gtest(rest: str, res: Results, ctx: dict) -> str:
    suite, dot, name = rest.partition(".")
    if not (suite and dot and name):
        return "gtest:<Suite>.<Name> expected"
    if ctx["gtests"] != "true":
        return "the run did not run the gtests (gtests=%s): nothing proves %s.%s" % (ctx["gtests"], suite, name)
    if not filter_matches(ctx["gtest_filter"], "%s.%s" % (suite, name)):
        return "%s.%s is not matched by the gtest filter of this run: it cannot have run" % (suite, name)
    legs = [p for p in PLATFORMS if suite not in ctx["not_on"].get(p, ())]
    if not legs:
        return "the suite %s exists on no platform (NOT_ON of gtest_run.py)" % suite
    reports = res.gtest.get((suite, name), {})
    for platform in legs:
        if platform not in res.gtest_legs:
            return "the gtest report of the %s leg is not in the run" % platform
        outcomes = reports.get(platform)
        if not outcomes:
            return "%s.%s is in no gtest report of the %s leg (renamed, removed or not run)" % (suite, name, platform)
        bad = _worst(outcomes)
        if bad:
            return "%s.%s on the %s leg: %s" % (suite, name, platform, bad)
    return ""


def _base(segment: str) -> str:
    return segment.split("[", 1)[0]


def _params(segment: str) -> str:
    return segment[segment.index("[") + 1:segment.rindex("]")] if "[" in segment and segment.endswith("]") else ""


def pytest_outcomes(cases, source: str, path: str, test: str) -> list:
    """The outcomes of the tests of `path` that `test` names: the node id, or the node id without its parameters, or the function without its class;
    `invariant:<x>` and `case:<x>` also match the id of a parameter, or a test whose name is exactly `<x>`."""
    found = []
    wanted_param = test.split(":", 1)[1] if test.startswith(("invariant:", "case:")) else None
    for src, nid, outcome in cases:
        if src != source:
            continue
        parts = nid.split("::")
        file, rest = parts[0], parts[1:]
        if not (file == path or file.endswith("/" + path)) or not rest:
            continue
        full = "::".join(rest)
        names = {full, _base(full), rest[-1], _base(rest[-1])}
        params = _params(rest[-1])
        if test in names or (wanted_param is not None and (params in (test, wanted_param) or wanted_param in names)):
            found.append(outcome)
    return found


def judge_pytest(kind: str, rest: str, res: Results, _ctx: dict) -> str:
    path, sep, test = rest.partition("::")
    if not (path and sep and test):
        return "%s:<path>::<test> expected" % kind
    outcomes = pytest_outcomes(res.pytest, kind, path, test)
    if not outcomes:
        return "%s is in no %s junit of the run (a name that does not exist, a test removed from a leg, or no leg that runs it)" % (rest, kind)
    bad = _worst(outcomes)
    return "%s: %s" % (rest, bad) if bad else ""


def judge_node(rest: str, res: Results, _ctx: dict) -> str:
    path, _, title = rest.partition("#")
    if not path:
        return "node:<path>[#<title>] expected"
    cases = res.node.get(path)
    if cases is None:
        return "no node junit of %s in the run (the `checks` job runs juggler/tests/*.test.mjs and keeps junit-node)" % path
    mine = [o for n, o in cases if n == title] if title else [o for _n, o in cases]
    if not mine:
        return "%s has no test titled %r in the junit" % (path, title) if title else "%s ran no test" % path
    bad = _worst(mine)
    return "%s: %s" % (rest, bad) if bad else ""


def judge_xpcshell(rest: str, res: Results, _ctx: dict) -> str:
    path, sep, title = rest.partition("#")
    if not (path and sep and title):
        return "xpcshell:<path>#<test> expected"
    base = path.rsplit("/", 1)[-1]
    mine = [o for c, n, o in res.xpcshell if n == title and (path in c or base in c)]
    if not mine:
        return "%s is in no xpcshell junit of the run (no leg runs xpcshell)" % rest
    bad = _worst(mine)
    return "%s: %s" % (rest, bad) if bad else ""


def judge_cargo(rest: str, res: Results, _ctx: dict) -> str:
    crate, sep, test = rest.partition("::")
    if not (crate and sep and test):
        return "cargo:<crate>::<test path> expected"
    # the FULL test path only, as `cargo test` prints it: the same final name in another module is another test
    mine = [o for c, n, o in res.cargo if (crate in c or crate in n) and n in (test, "%s::%s" % (crate, test))]
    if not mine:
        return "%s is in no cargo junit of the run (no leg runs cargo tests)" % rest
    bad = _worst(mine)
    return "%s: %s" % (rest, bad) if bad else ""


def judge_ref(ref: str, res: Results, ctx: dict) -> str:
    """'' when the named test exists in the run and passed, else why not."""
    kind, _, rest = ref.partition(":")
    if kind == "gtest":
        return judge_gtest(rest, res, ctx)
    if kind in ("wrapper", "py"):
        return judge_pytest(kind, rest, res, ctx)
    if kind == "node":
        return judge_node(rest, res, ctx)
    if kind == "xpcshell":
        return judge_xpcshell(rest, res, ctx)
    if kind == "cargo":
        return judge_cargo(rest, res, ctx)
    return "unknown test reference %r: gtest:, node:, py:, xpcshell:, wrapper: or cargo:" % ref


# --------------------------------------------------------------------------- the verdict
def judge(series, results=None, gtest_reports=None, junit=None, gtest_filter="", gtests="true", gtest_run=None, min_named=1):
    """-> (rows, problems, counts): rows are [(folder, hook file, test, status)] with status "PASS" or "FAIL: why", the FAIL rows first."""
    named, unnamed, untestable, problems = collect(Path(series))
    res = read_results(results, gtest_reports, junit)
    problems = problems + res.problems
    ctx = {"gtest_filter": gtest_filter, "gtests": str(gtests).lower(), "not_on": {}}
    if any(ref.startswith("gtest:") for _f, _h, ref in named):
        try:
            ctx["not_on"] = load_not_on(gtest_run)
        except Exception as exc:  # noqa: BLE001 - a judge that cannot read its table is red, not green
            problems.append("NOT_ON of gtest_run.py cannot be read: %s" % exc)
    memo, rows = {}, []
    for folder, hook_file, ref in named:
        if ref not in memo:
            memo[ref] = judge_ref(ref, res, ctx)
        rows.append((folder, hook_file, ref, "FAIL: " + memo[ref] if memo[ref] else "PASS"))
    if len(memo) < min_named:
        problems.append("the series names %d test(s), fewer than the %d the judge needs: a judge that judged nothing is not a verdict "
                        "(%d hook(s) have no test, %d are declared untestable)" % (len(memo), min_named, unnamed, untestable))
    rows.sort(key=lambda r: (not r[3].startswith("FAIL"),))
    counts = {"tests": len(memo), "failed": sum(1 for v in memo.values() if v), "hooks_without_test": unnamed, "untestable": untestable,
              "result_files": res.files}
    return rows, problems, counts


def render(rows, problems, counts) -> str:
    red = bool(problems) or counts["failed"] > 0
    out = ["## Named hook tests: %s" % ("RED" if red else "GREEN"), "",
           "%d named test(s), %d failed; %d hook(s) with no test (the debt of `hooks_list.py check`), %d declared untestable; %d result file(s) read."
           % (counts["tests"], counts["failed"], counts["hooks_without_test"], counts["untestable"], counts["result_files"]), ""]
    for p in problems:
        out.append("- **PROBLEM** %s" % p)
    if problems:
        out.append("")
    out += ["| folder | hook file | test | status |", "|---|---|---|---|"]
    for folder, hook_file, ref, status in rows:
        out.append("| %s | %s | `%s` | %s |" % (folder, hook_file, ref, status.replace("|", "/")))
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--series", required=True, help="the series checkout: <folder>/HOOKS.json")
    ap.add_argument("--results", help="the gate's result-* artifacts (junit of the wrapper legs)")
    ap.add_argument("--gtest-reports", help="the gtest-reports-* artifacts")
    ap.add_argument("--junit", help="the junit-* artifacts (node, py, xpcshell, cargo)")
    ap.add_argument("--gtest-filter", default=os.environ.get("GTEST_FILTER_INPUT", ""), help="the filter of this run's gtests")
    ap.add_argument("--gtests", default="true", help="'true' when this run ran the gtests")
    ap.add_argument("--gtest-run", help="the gtest_run.py the gtest jobs ran (its NOT_ON); default: the one of the series this script lives in")
    ap.add_argument("--min-named", type=int, default=1, help="fewer named tests than this is red")
    ap.add_argument("--summary", default=os.environ.get("GITHUB_STEP_SUMMARY", ""), help="where the table goes (the step summary)")
    ns = ap.parse_args(argv)
    rows, problems, counts = judge(ns.series, ns.results, ns.gtest_reports, ns.junit, ns.gtest_filter, ns.gtests, ns.gtest_run, ns.min_named)
    text = render(rows, problems, counts)
    if ns.summary:
        with open(ns.summary, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
    for p in problems:
        print("HOOK TESTS RED: %s" % p)
    for folder, hook_file, ref, status in rows:
        if status.startswith("FAIL"):
            print("HOOK TESTS RED: %s (%s) %s %s" % (folder, hook_file, ref, status))
    red = bool(problems) or counts["failed"] > 0
    print("HOOK TESTS %s: %d named test(s), %d failed, %d hook(s) without a test, %d untestable, %d result file(s)"
          % ("RED" if red else "GREEN", counts["tests"], counts["failed"], counts["hooks_without_test"], counts["untestable"], counts["result_files"]))
    return 1 if red else 0


if __name__ == "__main__":
    sys.exit(main())
