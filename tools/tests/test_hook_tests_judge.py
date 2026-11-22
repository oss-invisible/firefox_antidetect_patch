#!/usr/bin/env python3
"""The named hook tests judge (tools/hook_tests_judge.py) is red for every named test that does not exist in the run, is skipped, did not pass or is
outside the gtest filter, and green when every named test passed (an approved untestable hook has nothing to judge); the job of release.yml that runs it
reads the judge from main and fails closed (that job comes with the firefox-69 line).

The cases build a fake series (SERIES, <folder>/HOOKS.json) and the fake results a run keeps (gtest json, pytest junit, node junit) in a temporary folder.

    python -m pytest -q tools/tests/test_hook_tests_judge.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
sys.path.insert(0, str(TOOLS))
import hook_tests_judge as hj  # noqa: E402

NOT_ON = {"linux": {"StealthWebGPUAdapter", "StealthFontList"}, "win": {"StealthWebGPUBundledVulkan"}}
FILTER = "StealthA.*:StealthB.*:StealthFontList.*"
OK_NAMES = {"gtest": "gtest:StealthA.Does", "wrapper": "wrapper:tests/e2e/test_x.py::test_y", "node": "node:juggler/tests/a.test.mjs#it works"}


def hook(test="", file="a/b.cpp", **extra) -> dict:
    return dict({"file": file, "function": "f", "kind": "add", "form": "guard", "line": "x", "test": test}, **extra)


def gtest_json(*suites) -> str:
    """suites: (name, [(test, result)]) -> the json GTEST_OUTPUT writes."""
    return json.dumps({"tests": 1, "testsuites": [
        {"name": n, "testsuite": [{"name": t, "status": "RUN" if r != "SUPPRESSED" else "NOTRUN", "result": r,
                                   **({"failures": [{"failure": "boom"}]} if r == "FAILED" else {})} for t, r in cases]} for n, cases in suites]})


def junit(*cases) -> str:
    """cases: (classname, name, outcome) with outcome passed|failed|skipped|error."""
    body = ""
    for c, n, o in cases:
        inner = {"passed": "", "failed": "<failure message='x'/>", "skipped": "<skipped message='x'/>", "error": "<error message='x'/>"}[o]
        body += "<testcase classname='%s' name='%s'>%s</testcase>" % (c, n, inner)
    return "<testsuites><testsuite name='s'>%s</testsuite></testsuites>" % body


class Fake:
    """A series and the results of a run, in a temporary folder."""

    def __init__(self, tmp: str, hooks: dict, gtest_linux=None, gtest_win=None, wrapper=None, node=None, extra_junit=None, not_on_tests=None):
        self.root = Path(tmp)
        self.series = self.root / "series"
        self.series.mkdir()
        (self.series / "SERIES").write_text("\n".join(hooks) + "\n", encoding="utf-8")
        for folder, entries in hooks.items():
            (self.series / folder).mkdir(parents=True)
            (self.series / folder / "HOOKS.json").write_text(json.dumps(entries), encoding="utf-8")
        # the table of platform-only suites is the gtest_run.py of the run: a stub of it here, so that no case depends on the table of the day
        self.gtest_run = self.root / "gtest_run.py"
        self.gtest_run.write_text("NOT_ON = %r" % NOT_ON + chr(10) + ("" if not_on_tests is None else "NOT_ON_TESTS = %r" % not_on_tests + chr(10)), encoding="utf-8")
        self.results, self.gtest, self.junit = self.root / "results", self.root / "gtest-reports", self.root / "junit"
        for leg, files in (("gtest-reports-linux-x86_64", gtest_linux), ("gtest-reports-win-x86_64", gtest_win)):
            if files is not None:
                (self.gtest / leg).mkdir(parents=True)
                for name, text in files.items():
                    (self.gtest / leg / name).write_text(text, encoding="utf-8")
        for leg, text in (wrapper or {}).items():
            (self.results / ("result-" + leg)).mkdir(parents=True)
            (self.results / ("result-" + leg) / (leg + ".xml")).write_text(text, encoding="utf-8")
            (self.results / ("result-" + leg) / (leg + ".json")).write_text("{}", encoding="utf-8")
        for path, text in (node or {}).items():
            target = self.junit / "junit-node" / (path + ".xml")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        for rel, text in (extra_junit or {}).items():
            target = self.junit / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")

    def run(self, gtest_filter=FILTER, gtests="true", min_named=1):
        return hj.judge(self.series, self.results, self.gtest, self.junit, gtest_filter, gtests, str(self.gtest_run), min_named)

    def cli(self, *more):
        summary = self.root / "summary.md"
        done = subprocess.run([sys.executable, str(TOOLS / "hook_tests_judge.py"), "--series", str(self.series), "--results", str(self.results),
                               "--gtest-reports", str(self.gtest), "--junit", str(self.junit), "--gtest-filter", FILTER, "--summary", str(summary), "--gtest-run", str(self.gtest_run),
                               *more], capture_output=True, text=True)
        return done, summary.read_text(encoding="utf-8") if summary.is_file() else ""


GOOD_GTEST = {"StealthA.json": gtest_json(("StealthA", [("Does", "COMPLETED"), ("Also", "COMPLETED")]), ("StealthB", [("One", "COMPLETED")]))}
GOOD_WRAPPER = {"wrapper.e2e.x-linux": junit(("tests.e2e.test_x", "test_y", "passed")),
                "wrapper.e2e.x-windows": junit(("tests.e2e.test_x", "test_y", "passed"))}
GOOD_NODE = {"juggler/tests/a.test.mjs": junit(("test", "it works", "passed"), ("test", "it also works", "passed"))}


def good_hooks(**more) -> dict:
    return dict({"fingerprint/x": [hook(OK_NAMES["gtest"]), hook(OK_NAMES["wrapper"], file="c/d.cpp"), hook(OK_NAMES["node"], file="e.js")]}, **more)


def fake(tmp, hooks=None, **kw):
    kw.setdefault("gtest_linux", GOOD_GTEST)
    kw.setdefault("gtest_win", GOOD_GTEST)
    kw.setdefault("wrapper", GOOD_WRAPPER)
    kw.setdefault("node", GOOD_NODE)
    return Fake(tmp, hooks if hooks is not None else good_hooks(), **kw)


def red_on(rows, problems, needle) -> bool:
    return any(needle in r[3] for r in rows if r[3].startswith("FAIL")) or any(needle in p for p in problems)


def cases() -> list:
    out = []

    def add(name, ok):
        out.append((name, bool(ok)))

    with tempfile.TemporaryDirectory() as tmp:
        f = fake(tmp)
        rows, problems, counts = f.run()
        add("judge: every named test passed in every result: green, one row per hook file and test%s" % ("" if not problems else ": %s" % problems),
            not problems and counts["failed"] == 0 and len(rows) == 3 and all(r[3] == "PASS" for r in rows))
        done, summary = f.cli()
        add("judge: the command exits 0, prints GREEN and writes the table to the step summary",
            done.returncode == 0 and "HOOK TESTS GREEN" in done.stdout and "| folder | hook file | test | status |" in summary and "Named hook tests: GREEN" in summary)

    # the cases the red team asked for
    with tempfile.TemporaryDirectory() as tmp:
        f = fake(tmp, wrapper={"wrapper.e2e.x-linux": junit(("tests.e2e.test_other", "test_y", "passed"))})
        rows, problems, _ = f.run()
        add("judge: a wrapper test removed from the legs (not in any junit) is red", red_on(rows, problems, "is in no wrapper junit"))
        done, summary = f.cli()
        add("judge: ... and the command exits 1 with the row FAIL in the table", done.returncode == 1 and "FAIL" in summary and "HOOK TESTS RED" in done.stdout)

    with tempfile.TemporaryDirectory() as tmp:
        renamed = {"StealthA.json": gtest_json(("StealthA", [("DoesIt", "COMPLETED")]), ("StealthB", [("One", "COMPLETED")]))}
        f = fake(tmp, gtest_linux=renamed, gtest_win=renamed)
        rows, problems, _ = f.run()
        add("judge: a gtest renamed (the report has another name) is red", red_on(rows, problems, "renamed, removed or not run"))

    with tempfile.TemporaryDirectory() as tmp:
        f = fake(tmp, wrapper={"wrapper.e2e.x-linux": junit(("tests.e2e.test_x", "test_y", "skipped"))})
        rows, problems, _ = f.run()
        add("judge: a skipped wrapper test is red", red_on(rows, problems, "skipped"))
    with tempfile.TemporaryDirectory() as tmp:
        skipped = {"StealthA.json": gtest_json(("StealthA", [("Does", "SKIPPED")]))}
        f = fake(tmp, gtest_linux=skipped)
        rows, problems, _ = f.run()
        add("judge: a skipped gtest is red", red_on(rows, problems, "skipped"))
    with tempfile.TemporaryDirectory() as tmp:
        disabled = {"StealthA.json": gtest_json(("StealthA", [("Does", "SUPPRESSED")]))}
        f = fake(tmp, gtest_win=disabled)
        rows, problems, _ = f.run()
        add("judge: a disabled gtest is red (not run)", red_on(rows, problems, "not run"))

    with tempfile.TemporaryDirectory() as tmp:
        hooks = {"fingerprint/x": [hook(OK_NAMES["gtest"]), hook("", file="u.cpp", untestable="no page can read it", pm="approvato")]}
        f = fake(tmp, hooks)
        rows, problems, counts = f.run()
        add("judge: an approved untestable hook without a test is green and counted apart%s" % ("" if not problems else ": %s" % problems),
            not problems and counts["failed"] == 0 and counts["untestable"] == 1 and counts["hooks_without_test"] == 0 and len(rows) == 1)
    with tempfile.TemporaryDirectory() as tmp:
        hooks = {"fingerprint/x": [hook(OK_NAMES["gtest"]), hook("", file="u.cpp", untestable="because", pm="forse")]}
        rows, problems, counts = fake(tmp, hooks).run()
        add("judge: an untestable that the pm did not approve is not an exemption (counted as a hook with no test)", counts["untestable"] == 0 and counts["hooks_without_test"] == 1)

    with tempfile.TemporaryDirectory() as tmp:
        hooks = {"fingerprint/x": [hook("gtest:StealthOutside.Does")]}
        f = fake(tmp, hooks, gtest_linux={"StealthOutside.json": gtest_json(("StealthOutside", [("Does", "COMPLETED")]))},
                 gtest_win={"StealthOutside.json": gtest_json(("StealthOutside", [("Does", "COMPLETED")]))})
        rows, problems, _ = f.run()
        add("judge: a gtest suite outside the filter is red even if a report has it (the static check)", red_on(rows, problems, "not matched by the gtest filter"))
        add("judge: the filter is read as gtest reads it (wildcards, negative patterns)",
            hj.filter_matches("A.*:B.x", "A.y") and not hj.filter_matches("A.*:B.x", "B.y") and not hj.filter_matches("A.*-A.y", "A.y")
            and hj.filter_matches("*", "Z.z") and hj.filter_matches("-A.*", "B.b") and hj.filter_matches("Intl_*.*", "Intl_Locale_X.y"))
        rows, problems, _ = f.run(gtest_filter="StealthOutside.*")
        add("judge: the same suite inside the filter is green", not problems and rows[0][3] == "PASS")
        rows, problems, _ = f.run(gtest_filter="StealthOutside.*", gtests="false")
        add("judge: a run that did not run the gtests (gtests=false) is red for every named gtest", red_on(rows, problems, "did not run the gtests"))

    # a failed test, a leg that did not report
    with tempfile.TemporaryDirectory() as tmp:
        f = fake(tmp, gtest_win={"StealthA.json": gtest_json(("StealthA", [("Does", "FAILED")]))})
        rows, problems, _ = f.run()
        add("judge: a gtest that failed on one leg is red, naming the leg", red_on(rows, problems, "on the win leg: failed"))
    with tempfile.TemporaryDirectory() as tmp:
        f = fake(tmp, gtest_win=None)
        rows, problems, _ = f.run()
        add("judge: a gtest leg with no report folder in the run is red", red_on(rows, problems, "report of the win leg is not in the run"))
    with tempfile.TemporaryDirectory() as tmp:
        f = fake(tmp, wrapper={"wrapper.e2e.x-linux": junit(("tests.e2e.test_x", "test_y", "passed")),
                               "wrapper.e2e.x-windows": junit(("tests.e2e.test_x", "test_y", "failed"))})
        rows, problems, _ = f.run()
        add("judge: a wrapper test that passed on Linux and failed on Windows is red", red_on(rows, problems, "failed"))
    with tempfile.TemporaryDirectory() as tmp:
        f = fake(tmp, wrapper={"wrapper.e2e.x-linux": junit(("tests.e2e.test_x", "test_y", "error"))})
        rows, problems, _ = f.run()
        add("judge: a wrapper test that errored is red", red_on(rows, problems, "error"))

    # platform-only suites are not asked of the other platform (NOT_ON of gtest_run.py)
    with tempfile.TemporaryDirectory() as tmp:
        win_only = gtest_json(("StealthFontList", [("Lists", "COMPLETED")]))
        f = fake(tmp, {"fonts/x": [hook("gtest:StealthFontList.Lists")]}, gtest_linux=GOOD_GTEST, gtest_win={"StealthFontList.json": win_only})
        rows, problems, _ = f.run()
        add("judge: a suite that exists on Windows only is asked of the Windows leg only%s" % ("" if not problems else ": %s" % problems), not problems and rows[0][3] == "PASS")

    # single tests that exist on one platform only inside a suite that exists on both (NOT_ON_TESTS of gtest_run.py)
    one_side = ("StealthA", [("Does", "COMPLETED"), ("LinuxOnly", "COMPLETED")])
    linux_json = {"StealthA.json": gtest_json(one_side)}
    win_json = {"StealthA.json": gtest_json(("StealthA", [("Does", "COMPLETED")]))}
    table = {"linux": set(), "win": {"StealthA.LinuxOnly"}}
    with tempfile.TemporaryDirectory() as tmp:
        f = fake(tmp, {"x": [hook("gtest:StealthA.LinuxOnly")]}, gtest_linux=linux_json, gtest_win=win_json, not_on_tests=table)
        rows, problems, _ = f.run()
        add("judge: a test listed in NOT_ON_TESTS for Windows is green when only the Linux report has it%s" % ("" if not problems else ": %s" % problems),
            not problems and rows[0][3] == "PASS")
    with tempfile.TemporaryDirectory() as tmp:
        f = fake(tmp, {"x": [hook("gtest:StealthA.LinuxOnly")]}, gtest_linux=linux_json, gtest_win=win_json)
        rows, problems, _ = f.run()
        add("judge: a test missing from the Windows report and not in NOT_ON_TESTS stays red", red_on(rows, problems, "in no gtest report of the win leg"))
    with tempfile.TemporaryDirectory() as tmp:
        f = fake(tmp, {"x": [hook("gtest:StealthA.LinuxOnly")]}, gtest_linux=linux_json, gtest_win=win_json, not_on_tests={"linux": {"StealthA.Other"}, "win": {"StealthA.LinuxOnly"}})
        rows, problems, _ = f.run()
        add("judge: a table that lists other tests does not excuse this one on the other platform", not problems and rows[0][3] == "PASS")
    with tempfile.TemporaryDirectory() as tmp:
        f = fake(tmp, {"x": [hook("gtest:StealthA.LinuxOnly")]}, gtest_linux=linux_json, gtest_win=win_json, not_on_tests={"linux": {"StealthA.LinuxOnly"}, "win": {"StealthA.LinuxOnly"}})
        rows, problems, _ = f.run()
        add("judge: a test listed as not on Linux that ran on Linux is red", red_on(rows, problems, "listed as not on the linux leg"))
    with tempfile.TemporaryDirectory() as tmp:
        f = fake(tmp, {"x": [hook("gtest:StealthA.Does")]}, not_on_tests={"linux": set(), "win": {"StealthA.Does"}})
        rows, problems, _ = f.run()
        add("judge: a table entry for a test that is in the Windows report is red, even if the report is green", red_on(rows, problems, "listed as not on the win leg"))
    with tempfile.TemporaryDirectory() as tmp:
        f = fake(tmp, {"x": [hook("gtest:StealthA.Does")]}, gtest_linux={"StealthA.json": gtest_json(("StealthA", [("Other", "COMPLETED")]))},
                 gtest_win={"StealthA.json": gtest_json(("StealthA", [("Other", "COMPLETED")]))}, not_on_tests={"linux": {"StealthA.Does"}, "win": {"StealthA.Does"}})
        rows, problems, _ = f.run()
        add("judge: a test listed as not on either platform is red", red_on(rows, problems, "exists on no platform"))
    with tempfile.TemporaryDirectory() as tmp:
        f = fake(tmp, {"x": [hook("gtest:StealthA.LinuxOnly")]}, gtest_linux=linux_json, gtest_win=win_json, not_on_tests=table)
        done, summary = f.cli()
        add("judge: the command exits 0 for a test that NOT_ON_TESTS puts on one platform", done.returncode == 0 and "GREEN" in summary)

    # node: the file is in the name of the junit, the title is in the testcase
    with tempfile.TemporaryDirectory() as tmp:
        f = fake(tmp, node={"juggler/tests/b.test.mjs": junit(("test", "it works", "passed"))})
        rows, problems, _ = f.run()
        add("judge: a node test of a file whose junit is not in the run is red", red_on(rows, problems, "no node junit of juggler/tests/a.test.mjs"))
    with tempfile.TemporaryDirectory() as tmp:
        f = fake(tmp, node={"juggler/tests/a.test.mjs": junit(("test", "another title", "passed"))})
        rows, problems, _ = f.run()
        add("judge: a node test whose title is not in its file's junit is red", red_on(rows, problems, "no test titled 'it works'"))
    with tempfile.TemporaryDirectory() as tmp:
        f = fake(tmp, node={"juggler/tests/a.test.mjs": junit(("test", "it works", "failed"))})
        rows, problems, _ = f.run()
        add("judge: a failed node test is red", red_on(rows, problems, "failed"))
    with tempfile.TemporaryDirectory() as tmp:
        f = fake(tmp, {"x": [hook("node:juggler/tests/a.test.mjs")]}, node={"juggler/tests/a.test.mjs": junit(("test", "t1", "passed"), ("test", "t2", "skipped"))})
        rows, problems, _ = f.run()
        add("judge: a node reference with no title is red if any test of the file did not pass", red_on(rows, problems, "skipped"))

    # pytest naming: a class, parameters, the invariant and case forms
    with tempfile.TemporaryDirectory() as tmp:
        hooks = {"x": [hook("wrapper:tests/e2e/test_x.py::test_p"), hook("wrapper:tests/e2e/test_x.py::TestK::test_m", file="k"),
                       hook("wrapper:tests/e2e/test_x.py::invariant:seed-zero", file="i"), hook("wrapper:tests/e2e/test_x.py::case:dpr-2", file="c")]}
        junit_ok = junit(("tests.e2e.test_x", "test_p[a]", "passed"), ("tests.e2e.test_x", "test_p[b]", "passed"), ("tests.e2e.test_x.TestK", "test_m", "passed"),
                         ("tests.e2e.test_x", "test_inv[seed-zero]", "passed"), ("tests.e2e.test_x", "test_cases[dpr-2]", "passed"))
        rows, problems, _ = fake(tmp, hooks, wrapper={"wrapper.e2e.x-linux": junit_ok}).run()
        add("judge: parametrized, class and invariant/case references find their tests%s" % ("" if not problems and all(r[3] == "PASS" for r in rows) else ": %s %s" % (rows, problems)),
            not problems and all(r[3] == "PASS" for r in rows))
    with tempfile.TemporaryDirectory() as tmp:
        hooks = {"x": [hook("wrapper:tests/e2e/test_x.py::test_p")]}
        bad = junit(("tests.e2e.test_x", "test_p[a]", "passed"), ("tests.e2e.test_x", "test_p[b]", "failed"))
        rows, problems, _ = fake(tmp, hooks, wrapper={"wrapper.e2e.x-linux": bad}).run()
        add("judge: a parametrized test with one failed parameter is red", red_on(rows, problems, "failed"))

    # the kinds no leg runs today
    with tempfile.TemporaryDirectory() as tmp:
        hooks = {"x": [hook("py:modules/libpref/test/test_stealth_x.py::test_a"), hook("xpcshell:dom/x/test_y.js#test_b", file="b"),
                       hook("cargo:wgpu-core::tests::it_ok", file="c")]}
        rows, problems, _ = fake(tmp, hooks).run()
        add("judge: py, xpcshell and cargo tests with no junit in the run are red, each saying so",
            len(rows) == 3 and all(r[3].startswith("FAIL") for r in rows) and "in no py junit" in rows[0][3]
            and "no leg runs xpcshell" in rows[1][3] and "no leg runs cargo" in rows[2][3])
    with tempfile.TemporaryDirectory() as tmp:
        hooks = {"x": [hook("py:modules/libpref/test/test_stealth_x.py::test_a"), hook("xpcshell:dom/x/test_y.js#test_b", file="b"),
                       hook("cargo:wgpu-core::tests::it_ok", file="c")]}
        extra = {"junit-py/p.xml": junit(("modules.libpref.test.test_stealth_x", "test_a", "passed")),
                 "junit-xpcshell/x.xml": junit(("xpcshell.dom/x/test_y.js", "test_b", "passed")),
                 "junit-cargo/c.xml": junit(("wgpu-core", "tests::it_ok", "passed"))}
        rows, problems, _ = fake(tmp, hooks, extra_junit=extra).run()
        add("judge: py, xpcshell and cargo tests are judged when a leg keeps their junit-* artifact%s" % ("" if not problems and all(r[3] == "PASS" for r in rows) else ": %s %s" % (rows, problems)),
            not problems and all(r[3] == "PASS" for r in rows))

    # invariant:/case: resolve on a testcase whose NAME is exactly <x> (one junit case per invariant or case), not only on a parameter id
    with tempfile.TemporaryDirectory() as tmp:
        hooks = {"x": [hook("wrapper:tests/e2e/test_x.py::invariant:fullscreen_is_the_screen"), hook("wrapper:tests/e2e/test_x.py::case:dpr_is_two", file="c")]}
        ok = junit(("tests.e2e.test_x", "fullscreen_is_the_screen", "passed"), ("tests.e2e.test_x", "dpr_is_two", "passed"))
        rows, problems, _ = fake(tmp, hooks, wrapper={"wrapper.e2e.x-linux": ok}).run()
        add("judge: invariant:<x> and case:<x> resolve on a testcase named exactly <x>%s" % ("" if not problems and all(r[3] == "PASS" for r in rows) else ": %s %s" % (rows, problems)),
            not problems and all(r[3] == "PASS" for r in rows))
    with tempfile.TemporaryDirectory() as tmp:
        hooks = {"x": [hook("wrapper:tests/e2e/test_x.py::invariant:fullscreen_is_the_screen")]}
        bad = junit(("tests.e2e.test_x", "fullscreen_is_the_screen", "failed"))
        rows, problems, _ = fake(tmp, hooks, wrapper={"wrapper.e2e.x-linux": bad}).run()
        add("judge: an invariant testcase named exactly <x> that failed is red", red_on(rows, problems, "failed"))
    with tempfile.TemporaryDirectory() as tmp:
        hooks = {"x": [hook("wrapper:tests/e2e/test_x.py::invariant:fullscreen_is_the_screen")]}
        other = junit(("tests.e2e.test_x", "fullscreen_is_something_else", "passed"))
        rows, problems, _ = fake(tmp, hooks, wrapper={"wrapper.e2e.x-linux": other}).run()
        add("judge: an invariant that no testcase is named for is red", red_on(rows, problems, "in no wrapper junit"))

    # cargo: the FULL test path only; the same final name in another module is another test
    cargo_ref = "cargo:webrender::render_backend::stealth_shared_fonts::tests::same_name"
    with tempfile.TemporaryDirectory() as tmp:
        other = {"junit-cargo/c.xml": junit(("webrender", "other_mod::tests::same_name", "passed"), ("webrender", "same_name", "passed"))}
        rows, problems, _ = fake(tmp, {"x": [hook(cargo_ref, file="c")]}, extra_junit=other).run()
        add("judge: a cargo test is not satisfied by a same-named test of another module, nor by its final name alone", red_on(rows, problems, "in no cargo junit"))
    with tempfile.TemporaryDirectory() as tmp:
        full = {"junit-cargo/c.xml": junit(("webrender", "render_backend::stealth_shared_fonts::tests::same_name", "passed"), ("webrender", "other_mod::tests::same_name", "failed"))}
        rows, problems, _ = fake(tmp, {"x": [hook(cargo_ref, file="c")]}, extra_junit=full).run()
        add("judge: a cargo test is judged on its full path (the other module's failure is not this test's)%s" % ("" if not problems and rows[0][3] == "PASS" else ": %s %s" % (rows, problems)),
            not problems and rows[0][3] == "PASS")

    # a judge that judged nothing, unreadable files, unknown kinds
    with tempfile.TemporaryDirectory() as tmp:
        rows, problems, counts = fake(tmp, {"x": [hook(""), hook("", file="b")]}).run()
        add("judge: a series that names no test at all is red (a judge that judged nothing is not a verdict)", any("judged nothing" in p for p in problems) and counts["hooks_without_test"] == 2)
    with tempfile.TemporaryDirectory() as tmp:
        f = fake(tmp)
        (f.series / "fingerprint/x/HOOKS.json").write_text("{not json", encoding="utf-8")
        rows, problems, _ = f.run()
        add("judge: a HOOKS.json that cannot be read is red", any("cannot be read" in p for p in problems))
    with tempfile.TemporaryDirectory() as tmp:
        rows, problems, _ = fake(tmp, {"x": [hook("selenium:whatever")]}).run()
        add("judge: a test reference of a kind it does not know is red", red_on(rows, problems, "unknown test reference"))
    with tempfile.TemporaryDirectory() as tmp:
        f = fake(tmp)
        (f.junit / "junit-node" / "juggler/tests/a.test.mjs.xml").write_text("<not xml", encoding="utf-8")
        rows, problems, _ = f.run()
        add("judge: a junit that does not parse is red, not skipped", any("cannot be read as junit" in p for p in problems))
    with tempfile.TemporaryDirectory() as tmp:
        f = fake(tmp, {"a": [hook(OK_NAMES["gtest"])], "b": [hook(OK_NAMES["gtest"], file="z")]})
        rows, problems, counts = f.run()
        add("judge: a test named by two folders is judged once and listed once per folder", len(rows) == 2 and counts["tests"] == 1)
    with tempfile.TemporaryDirectory() as tmp:
        f = fake(tmp, wrapper={"wrapper.e2e.x-linux": junit(("tests.e2e.test_x", "test_y", "passed"))}, gtest_win={})
        rows, problems, _ = f.run()
        add("judge: a leg folder with no report in it is red for its gtests", red_on(rows, problems, "in no gtest report of the win leg"))

    return out


@pytest.mark.parametrize("name,ok", cases(), ids=lambda v: v if isinstance(v, str) else None)
def test_case(name, ok):
    assert ok, name


def main() -> int:
    failures = 0
    found = cases()
    for name, ok in found:
        print(("ok    " if ok else "FAIL  ") + name)
        failures += not ok
    print("%d/%d cases as expected" % (len(found) - failures, len(found)))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
