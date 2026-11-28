#!/usr/bin/env python3
"""objects_first.py: the compile-only step, against the inputs it exists for.

  1. the compilers' error lines, as mach prints them (a time in front, absolute paths, clang's file:line:col and clang-cl's file(line,col)),
     become one row per file and line; warnings and repeats do not;
  2. the directories come from the files that differ from the Mozilla tag: a header and a build file count, a script and a font do not, a source
     a parent's moz.build lists belongs to the parent, a directory this build does not configure is not a target, and the top of the tree never is;
  3. mach stops at the first directory that fails: the step then runs each directory on its own, and every error of every directory is reported;
  4. the whole step on a real git history (a tag commit and the series on it): the list, the summary, the exit code, the events;
  5. every suite of our own files is in the gtest filter, and the suites that exist on one platform only are known to gtest_run.py.

    python3 scripts/ci/test_objects_first.py        (or python -m pytest scripts/ci/test_objects_first.py)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import gtest_run  # noqa: E402
import objects_first as o  # noqa: E402
import phase  # noqa: E402
import release_plan  # noqa: E402

ROOT = "/home/runner/work/engine/engine"
CLANG = " 0:45.12 %s/dom/base/Foo.cpp:12:3: error: use of undeclared identifier 'foo'" % ROOT
CLANG_CL = "gfx/thebes/Bar.cpp(7,2): error: no member named 'baz' in 'Qux'"
FATAL = "%s/netwerk/test/gtest/TestStealthX.cpp:3:10: fatal error: 'Missing.h' file not found" % ROOT

# Every suite of our own files, from `git grep -hoE "TEST(_F)?\((Stealth...|Idwr...|...Stealth...)," release/firefox-69` and the ones of ours in a
# Mozilla directory's gtest (StealthStartupCache, TestStealthStartupCache.cpp): the candidate's filter must run all of them.
OUR_SUITES = """Idwr Intl_Locale_StealthSystemLocales StealthAudioNoise StealthBirthOrder StealthBundleHooks StealthBundledCollection StealthCanvasProjection
StealthDebugger StealthDeclaredNetwork StealthDocumentLanguage StealthFallbackNames StealthFcBundleFonts StealthFcFontList StealthFontList
StealthFontListHooks StealthFontMetrics StealthFrameCrash StealthFullscreen StealthGLMultisample StealthGfxFeatureStatus StealthGlyphCoverage
StealthIceResolverContext StealthInputEventBirth StealthJugglerEventId StealthKeyBirthScope StealthMediaDeclaration StealthNrSocketBirth
StealthOwnBinaries StealthPcProxyConfig StealthPcUdpProxyKinds StealthPrefSanitize StealthQuotaEstimate StealthScaleDeclaration StealthSessionUdpProxy
StealthSocksUdpPool StealthTcpProxyRoad StealthTextQuality StealthTtcFace StealthUdpProxyBirth StealthWebGPUAdapter StealthWebGPUBundledVulkan
StealthWebGLParams StealthWebGPUDeclaration StealthWebGPUExternalTexture StealthWebGPUInstanceEnv StealthWindowGeometry StealthWindowInputDesktop
StealthExclusivePort StealthScreenToReal StealthChromeOffset
StealthBranding StealthCanvasUtils StealthDragGesture StealthHttp3Socks StealthJugglerCoalesce StealthJugglerMouseAck StealthMouseEventCopy
StealthMouseEventIPC StealthNsProxyInfoKinds StealthSocksUdpLayer StealthStackFrames StealthStartupCache StealthTimezone
TestStealthDocShellDefaults TestStealthLinkClickAfter TestStealthLoadInfo TestStealthSessionResolver TestStealthSocksCredentials TestStealthTRRContext""".split()


# ── 1. the errors ───────────────────────────────────────────────────────────────────────────

def test_errors_of_clang_and_clang_cl_are_rows():
    found, other = o.parse_errors([CLANG, CLANG_CL, FATAL], ROOT)
    assert found == [("dom/base/Foo.cpp", 12, "use of undeclared identifier 'foo'"),
                     ("gfx/thebes/Bar.cpp", 7, "no member named 'baz' in 'Qux'"),
                     ("netwerk/test/gtest/TestStealthX.cpp", 3, "'Missing.h' file not found")]
    assert other == 0


def test_warnings_and_repeats_are_not_rows_and_a_failure_with_no_file_is_counted():
    lines = ["%s/a/B.cpp:1:1: warning: unused variable 'x'" % ROOT, CLANG, CLANG, "gmake[4]: *** [Makefile:1: Foo.o] Error 1"]
    found, other = o.parse_errors(lines, ROOT)
    assert [f[0] for f in found] == ["dom/base/Foo.cpp"] and other == 1


def test_paths_lose_the_checkout_and_the_objdirs_dots():
    assert o.clean_path("../../../dom/base/Foo.cpp", ROOT) == "dom/base/Foo.cpp"
    assert o.clean_path("%s/dom/Foo.cpp" % ROOT, ROOT) == "dom/Foo.cpp"
    assert o.clean_path("C:\\src\\x\\a.cpp", "C:\\src\\x") == "a.cpp"


def test_summary_lists_the_errors_by_file_and_says_red():
    text = o.render("linux-x86_64", ["dom/base"], [("dom/base/Foo.cpp", 12, "bad | pipe")], ["dom/base"], [])
    assert text.startswith("❌ **linux-x86_64** objects: 1 directories, 1 errors in 1 files")
    assert "| `dom/base/Foo.cpp` | 12 | bad \\| pipe |" in text
    green = o.render("win-x86_64", ["dom/base"], [], [], [])
    assert green.startswith("✅")
    assert o.annotations([("a.cpp", 2, "100% bad")]) == ["::error file=a.cpp,line=2::100%25 bad"]


# ── 2. the directories ──────────────────────────────────────────────────────────────────────

def test_directories_come_from_the_files_that_are_compiled():
    made = {"dom/base", "dom/base/test/gtest", "gfx/thebes", "toolkit/library"}
    files = ["dom/base/Foo.cpp", "dom/base/nsFoo.h", "dom/base/test/gtest/TestStealthA.cpp", "dom/base/test/gtest/moz.build",
             "gfx/thebes/sub/deep/Parent.cpp",            # listed by gfx/thebes's moz.build: the parent's object
             "dom/system/windows/Win.cpp",                # a directory this build does not configure: climbs to a parent that has one, none here
             "gfx/thebes/data.json", "browser/fonts/a.ttf", "scripts/x.py", "toolkit/library/rust/shared/lib.rs",
             "toolkit/library/gkrust.mozbuild", "moz.build", "Foo.cpp"]
    dirs, outside = o.touched_dirs(files, made.__contains__)
    assert dirs == ["dom/base", "dom/base/test/gtest", "gfx/thebes", "toolkit/library"]
    assert outside == ["Foo.cpp", "dom/system/windows/Win.cpp", "moz.build"]


def test_a_deleted_file_still_names_the_directory_that_exists():
    assert o.touched_dirs(["gfx/gone/Old.cpp"], {"gfx"}.__contains__) == (["gfx"], [])


# ── 3. mach stops at the first directory that fails ─────────────────────────────────────────

class FakeMach:
    """`./mach build`: runs the targets in order and stops at the first that fails, as building.py does."""

    def __init__(self, broken):
        self.broken, self.calls = broken, []

    def __call__(self, args, log):
        self.calls.append(list(args))
        lines = []
        assert args[:2] == ["-C", "."], "the directories are top-level targets of the compile graph, so they keep their dependencies"
        for target in args[2:]:
            d = target.rsplit("/", 1)[0]
            if d in self.broken:
                lines.append("%s/%s/File.cpp:%d:1: error: %s" % (ROOT, d, len(d), self.broken[d]))
                return 2, lines
        return 0, lines


def test_a_green_batch_is_one_mach_run():
    mach = FakeMach({})
    assert o.build_objects(["a", "b", "c"], mach, None)[:2] == (0, [])
    assert mach.calls == [["-C", ".", "a/target-objects", "b/target-objects", "c/target-objects"]]


def test_a_failing_directory_does_not_hide_the_others():
    mach = FakeMach({"b": "first", "c": "second"})
    code, failed, lines = o.build_objects(["a", "b", "c"], mach, None)
    assert code == 1 and [d for d, _ in failed] == ["b", "c"]
    found, _ = o.parse_errors(lines, ROOT)
    assert {(f[0], f[2]) for f in found} == {("b/File.cpp", "first"), ("c/File.cpp", "second")}
    # the batch, then each directory alone
    assert mach.calls[0] == ["-C", ".", "a/target-objects", "b/target-objects", "c/target-objects"] and len(mach.calls) == 4


# ── 4. the whole step, on a git history ─────────────────────────────────────────────────────

def git(where, *args):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    return subprocess.run(["git", "-C", str(where), *args], check=True, capture_output=True, text=True, env=env).stdout


def write(path: Path, text="x\n"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def make_tree(root: Path, tagged: bool, nodes_of=("dom/base", "dom/base/test/gtest", "gfx/thebes")):
    """The Mozilla tag's commit, then the series on it: ours (a gtest, a source) and Mozilla's (a header, a script)."""
    git(root, "init", "-q")
    write(root / "dom/base/Old.cpp")
    write(root / "gfx/thebes/Keep.cpp")
    write(root / "toolkit/x.py")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "tag")
    if tagged:
        git(root, "tag", "FIREFOX_X_RELEASE")
    write(root / "dom/base/Old.cpp", "changed\n")
    write(root / "dom/base/test/gtest/TestStealthA.cpp")
    write(root / "gfx/thebes/nsB.h")
    write(root / "toolkit/x.py", "changed\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "series")
    write(root / ".series/UPSTREAM.json", json.dumps({"mozilla_tag": "FIREFOX_X_RELEASE"}))
    # The backend's root.mk: the compile graph's nodes (a directory with no objects has none), the value on continuation lines as the backend writes long ones.
    nodes = ["%s/target-objects" % d for d in nodes_of] + ["layout/base/target-objects", "dom/base/target"]
    write(root / "obj-rel/root.mk", "pre_compile_targets := a/pre-compile\ncompile_targets := %s \\\n  %s\nsyms_targets := x/syms\n"
          % (" ".join(nodes[:2]), " ".join(nodes[2:])))


def run_step(broken=None, tagged=True, export_code=0, series_empty=False, strict=True, nodes_of=("dom/base", "dom/base/test/gtest", "gfx/thebes")):
    """(exit code, summary text, events, the targets mach was given) of main() on a fresh tree."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        make_tree(root, tagged, nodes_of)
        summary = root / "summary.md"
        old = (Path.cwd(), phase.EVENTS, phase.LOGS, os.environ.get("GITHUB_STEP_SUMMARY"), os.environ.get("CI_LEG"))
        os.chdir(root)
        phase.EVENTS, phase.LOGS = root / "events.jsonl", root / "logs"
        os.environ["GITHUB_STEP_SUMMARY"], os.environ["CI_LEG"] = str(summary), "linux-x86_64"
        mach = FakeMach(broken or {})
        calls = []

        def wrapped(args, log):
            calls.append(list(args))
            if args == ["pre-export", "export"]:
                return export_code, ["export failed"] if export_code else []
            return mach(args, log)

        try:
            args = (["--base", "HEAD"] if series_empty else []) + (["--strict"] if strict else [])
            code = o.main(args, mach=wrapped)
            text = summary.read_text(encoding="utf-8") if summary.exists() else ""
            events = [json.loads(l) for l in (root / "events.jsonl").read_text(encoding="utf-8").splitlines()]
        finally:
            os.chdir(old[0])
            phase.EVENTS, phase.LOGS = old[1], old[2]
            for key, value in (("GITHUB_STEP_SUMMARY", old[3]), ("CI_LEG", old[4])):
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
        return code, text, events, calls


def test_the_step_compiles_the_directories_the_series_touches_and_is_green():
    code, text, events, calls = run_step()
    assert code == 0 and text.startswith("✅ **linux-x86_64** objects: 3 directories")
    # the export tier first; then one run for the directories of the series (Mozilla's dom/base and gfx/thebes, our gtest directory), never toolkit (a script)
    assert calls == [["pre-export", "export"],
                     ["-C", ".", "dom/base/target-objects", "dom/base/test/gtest/target-objects", "gfx/thebes/target-objects"]]
    assert [e["event"] for e in events] == ["start", "end"] and events[-1]["exit"] == 0


def test_the_tags_commit_is_found_without_a_ref_for_the_tag():
    """On a node that shares the fetch there is no refs/tags/<tag>: the root of the tree's history is the same commit."""
    code, _, _, calls = run_step(tagged=False)
    assert code == 0 and calls[1][2] == "dom/base/target-objects"


def test_every_error_of_every_directory_is_in_the_summary_and_the_step_fails():
    code, text, events, calls = run_step({"dom/base": "one", "gfx/thebes": "two"})
    assert code == 1
    assert "dom/base/File.cpp" in text and "gfx/thebes/File.cpp" in text and "❌" in text
    assert "dom/base/test/gtest/File.cpp" not in text            # a directory that compiled is not an error
    assert events[-1]["event"] == "end" and events[-1]["exit"] == 1 and len(events[-1]["errors"]) == 2
    assert len(calls) == 1 + 1 + 3                              # the tiers, the batch, each of the three alone


def test_a_failed_export_stops_the_step_red_with_nothing_compiled():
    code, text, events, calls = run_step(export_code=2)
    assert code == 1 and calls == [["pre-export", "export"]] and "❌" in text


def test_a_series_that_changes_no_directory_is_an_error_and_not_a_green_nothing():
    code, _, _, calls = run_step(series_empty=True)
    assert code == 1 and calls == [["pre-export", "export"]]


def test_the_tiers_are_the_two_the_build_runs_before_it_compiles():
    """`export` alone left dist/include empty (run 44942834683): pre-export installs it (Makefile.in:55-59), then export adds the generated headers, in that order."""
    _, _, _, calls = run_step()
    assert calls[0] == ["pre-export", "export"]


def test_a_directory_with_no_objects_is_not_a_target_and_is_said():
    """gfx/thebes has no node in this graph: its header climbs to a parent that has none either, and the file is listed as outside."""
    code, text, _, calls = run_step(nodes_of=("dom/base", "dom/base/test/gtest"))
    assert code == 0 and calls[1] == ["-C", ".", "dom/base/target-objects", "dom/base/test/gtest/target-objects"]
    assert "gfx/thebes/nsB.h" in text


def test_root_mk_compile_targets_are_read_across_continuation_lines():
    with tempfile.TemporaryDirectory() as tmp:
        write(Path(tmp) / "root.mk", "compile_targets := a/target-objects b/target \\\n  c/target-objects\nother := d/target-objects\n")
        assert o.compile_targets(Path(tmp)) == {"a/target-objects", "b/target", "c/target-objects"}
        write(Path(tmp) / "root.mk", "nothing := 1\n")
        try:
            o.compile_targets(Path(tmp))
        except SystemExit:
            pass
        else:
            raise AssertionError("an objdir without compile_targets must refuse")


def test_a_whole_candidate_never_loses_the_leg_to_this_step_and_the_compile_only_one_does():
    errors = {"dom/base": "one"}
    code, text, events, _ = run_step(errors, strict=False)
    assert code == 0 and "dom/base/File.cpp" in text and "does not fail the leg" in text
    assert events[-1]["exit"] == 0 and events[-1]["found"] == 1
    code, text, events, _ = run_step(errors, strict=True)
    assert code == 1 and "does not fail the leg" not in text and events[-1]["exit"] == 1
    # a failed export or an empty list is the same: reported, and only --strict fails
    assert run_step(export_code=2, strict=False)[0] == 0 and run_step(export_code=2, strict=True)[0] == 1
    assert run_step(series_empty=True, strict=False)[0] == 0


def test_annotations_are_warnings_when_the_step_does_not_fail():
    assert o.annotations([("a.cpp", 2, "bad")], "warning") == ["::warning file=a.cpp,line=2::bad"]


# ── 5. the gtest filter and the platforms ───────────────────────────────────────────────────

def test_every_suite_of_ours_is_in_the_candidates_filter():
    named = set(release_plan.DEFAULT_GTEST_FILTER.split(":"))
    assert [s for s in OUR_SUITES if "%s.*" % s not in named] == []
    assert "StealthStartupCache.*" in named and "StartupCache.WritesNeverLowerIOPriority" not in named


def test_suites_of_one_platform_are_not_missing_on_the_other():
    listing = ["StealthFcFontList", "StealthFontMetrics", "StealthMediaDeclaration"]
    on_linux = gtest_run.missing_suites(release_plan.DEFAULT_GTEST_FILTER, listing + ["Idwr"], "linux")
    assert "StealthFcFontList" not in on_linux and "StealthBundledCollection" not in on_linux and "StealthOwnBinaries" not in on_linux
    assert "StealthExclusivePort" not in on_linux  # Windows only: TestStealthExclusivePort.cpp is built there only
    on_win = gtest_run.missing_suites(release_plan.DEFAULT_GTEST_FILTER, ["StealthBundledCollection", "StealthOwnBinaries"], "win")
    assert "StealthFcFontList" not in on_win and "StealthFontMetrics" not in on_win and "StealthBundledCollection" not in on_win
    assert "StealthMediaDeclaration" in on_win               # a suite both platforms build, absent: that is the error


def main() -> int:
    failures = 0
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    for name, fn in tests:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            print("FAIL  %s: %s: %s" % (name, type(exc).__name__, exc))
            failures += 1
        else:
            print("ok    %s" % name)
    print("%d/%d cases as expected" % (len(tests) - failures, len(tests)))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
