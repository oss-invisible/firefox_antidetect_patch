"""Every check that guards main runs, with the same code, in the round before the merge (decision ci-07).

The checks are ONE reusable workflow, checks.yml (written in the source repository, exported). The two rounds that come before a merge call it and
run no check of their own:

    series.yml    pull_request and push to main
    release.yml   every candidate (a push to main, the weekly run, a dispatch from a latitude/* branch) and every release; the build node needs it

so a check is never first run on main: births.py ran first on the release pull request of firefox-69 and was red there.

This file reads the three workflows and fails when
  (a) series.yml or release.yml runs a check itself (any command of checks.yml, or a test script, pytest or `node --test`, in any step);
  (b) series.yml does not call checks.yml on a pull request and on a push to main, or release.yml does not call it for every candidate with no `if`,
      or the node does not wait for it, or a job of checks.yml can be skipped;
  (c) checks.yml lacks a job, or a command, of the checks series.yml and release.yml's plan and checks jobs ran before it existed.

    python -m pytest tools/tests
"""
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
CALL = "./.github/workflows/checks.yml"

# The jobs of checks.yml and the command each one runs (a substring of a step's `run`). Written by hand, so that a check dropped from checks.yml is a red
# test and not a shorter list: add a command here when a check is added there.
# The one workflow a job of checks.yml may call: the resolver of its Python packages (ci-03).
PY_DEPS = "./.github/workflows/py-deps.yml"

CHECK_COMMANDS = {
    # series.yml's `rules`
    "rules": ["pytest -q tools/tests", "tools/engine.py check"],
    # series.yml's `rebuilds`: the tree the series makes is the declared one (the CI form of `engine.py verify`: materialize stops on another tree),
    # the births, the core's checks that read the tree
    "rebuilds": ["engine.py materialize --into source", "tools/births.py --tree source", "tools/backport_replay.py check --source source",
                 "tests/test_pref_types.py", "tests/test_prefs_surface.py", "tests/test_juggler_contract.py", "tests/test_juggler_protocol_mirror.py",
                 "tests/test_webgl_extensions_follow_the_engine.py"],
    # port-07: tools/churn.json is what the series and the Mozilla tags give now (the tags of its own: no tree)
    "churn": ["tools/churn.py --cache-key", 'churn-tags.git" --fetch', 'churn-tags.git" --check', "tools/tests/test_churn.py"],
    # series-02: on a port, ports/range-diff.txt is what the two series give (the job decides first, and is green on any run that is not a port)
    "range-diff": ["tools/engine.py range-diff --decide", "tools/engine.py range-diff --source"],
    # the core the wrapper pins, resolved once for the wheelhouse and the checkout of rebuilds (ci-05)
    "core-ref": ["--resolve-core-ref --wrapper-ref", 'release_plan.py "${args[@]}"'],
    # series.yml's `noreply-identity`
    "noreply-identity": ["ci_noreply_identity.py"],
    # release.yml's plan (its own tests) and checks
    "tree": ["engine.py materialize --into .", "py_junit.py list", "py_junit.py ran", "scripts/test_release_plan.py", "scripts/ci/test_ci.py",
             "scripts/ci/test_stealth_download_watchdog.py", "scripts/ci/test_objects_first.py", "scripts/ci/test_stealth_build_tools.py",
             "scripts/check_release_naming.py", "scripts/check_upstream_source.py --online", "build/stealth_check_sources.py",
             "build/stealth_check_build_files.py", "node --test", "juggler/tests/*.test.mjs", "scripts/ci/gate_legs.py --required",
             "scripts/validate_release.py --selftest", "scripts/test_make_seal.py", "scripts/test_check_upstream_source.py",
             "scripts/test_toolchain_parity.py", "scripts/test_upstream_toolchain.py", "scripts/test_memory_watch.py", "scripts/test_cpu_watch.py",
             "scripts/test_workflow_cache_rules.py"],
}
# What series.yml and release.yml may run themselves: `materialize --into .` is the plan's (it needs the tree to plan), the guard is the release's.
NOT_CHECKS = {"engine.py materialize --into ."}
# A check by its shape: a test script, pytest, `node --test`. In the two callers it is a check first run in the wrong place.
SHAPE = re.compile(r"\bpytest\b|\bnode\s+--test\b|(?:^|[\s/])test_\w+\.py\b|\bcheck_\w+\.py\b|\bvalidate_release\.py\b|\bstealth_check_\w+\.py\b")
OLD_SERIES_JOBS = ("rules", "rebuilds", "noreply-identity")


def _doc(text):
    return yaml.safe_load(text)


def _events(doc):
    on = doc.get(True, doc.get("on"))
    return {on: None} if isinstance(on, str) else (on if isinstance(on, dict) else {e: None for e in on})


def _runs(job):
    return "\n".join(str(s.get("run", "")) for s in job.get("steps") or [])


def problems(series, release, checks):
    """What is wrong with the three workflows (parsed documents), as a list of sentences; [] when every check runs in both rounds."""
    out = []
    check_commands = {c for cmds in CHECK_COMMANDS.values() for c in cmds if c not in NOT_CHECKS}

    # (a) the callers run no check of their own
    for name, doc in (("series.yml", series), ("release.yml", release)):
        for job_name, job in doc["jobs"].items():
            text = _runs(job)
            for command in sorted(c for c in check_commands if c in text):
                out.append("%s: job %s runs %r itself: a check goes in checks.yml, called by both rounds" % (name, job_name, command))
            for hit in SHAPE.findall(text):
                if not any(c in text for c in check_commands):
                    out.append("%s: job %s runs %r, a check by its shape: it goes in checks.yml" % (name, job_name, hit.strip().lstrip("/")))
    if set(series["jobs"]) != {"checks", "gate"}:
        out.append("series.yml has the jobs %s; it is the call of checks.yml and the gate, nothing else" % sorted(series["jobs"]))

    # (b) series.yml calls it on the pull request and on a push to main; release.yml for every candidate; the node waits; nothing inside is skipped
    events = _events(series)
    if "pull_request" not in events:
        out.append("series.yml does not run on pull_request")
    if "push" not in events or "main" not in ((events["push"] or {}).get("branches") or []):
        out.append("series.yml does not run on a push to main")
    call = series["jobs"].get("checks") or {}
    if call.get("uses") != CALL or "if" in call:
        out.append("series.yml: the job `checks` is not an unconditional call of %s" % CALL)
    if (series["jobs"].get("gate") or {}).get("needs") != ["checks"]:
        out.append("series.yml: the gate does not wait for `checks` alone")
    events = _events(release)
    for needed in ("push", "workflow_dispatch", "schedule"):
        if needed not in events:
            out.append("release.yml does not run on %s: a candidate of that kind would not run the checks" % needed)
    call = release["jobs"].get("checks") or {}
    if call.get("uses") != CALL:
        out.append("release.yml: the job `checks` is not a call of %s" % CALL)
    if "if" in call:
        out.append("release.yml: the call of checks.yml has an `if` (%r): a candidate it skips is first checked on main" % call["if"])
    if "checks" not in (release["jobs"].get("node") or {}).get("needs", []):
        out.append("release.yml: the node does not wait for `checks`: a server would be rented before the checks are green")
    if "node" not in (release["jobs"].get("build") or {}).get("needs", []):
        out.append("release.yml: the build does not wait for the node")
    if set(_events(checks)) != {"workflow_call"}:
        out.append("checks.yml runs on %s; it is called, never started" % sorted(_events(checks)))
    for job_name, job in checks["jobs"].items():
        # A job may wait for another job of checks.yml (a red one fails the call) and call only the resolver of its packages (ci-03); never an
        # `if` or continue-on-error, which skip or pass a check.
        if "if" in job or job.get("continue-on-error") or ("uses" in job and job["uses"] != PY_DEPS):
            out.append("checks.yml: the job %s can be skipped or passed (if, continue-on-error, or a call of something but %s)" % (job_name, PY_DEPS))

    # (c) nothing of what the two files checked before is missing
    for job_name in OLD_SERIES_JOBS + ("tree",):
        if job_name not in checks["jobs"]:
            out.append("checks.yml has no job %s" % job_name)
    for job_name, commands in CHECK_COMMANDS.items():
        text = _runs(checks["jobs"].get(job_name) or {})
        for command in commands:
            if command not in text:
                out.append("checks.yml, job %s: the command %r is missing" % (job_name, command))
    return out


def _real():
    return (_doc((WORKFLOWS / "series.yml").read_text(encoding="utf-8")), _doc((WORKFLOWS / "release.yml").read_text(encoding="utf-8")),
            _doc((WORKFLOWS / "checks.yml").read_text(encoding="utf-8")))


def test_every_check_runs_in_the_round_before_the_merge_and_in_the_candidate():
    series, release, checks = _real()
    assert problems(series, release, checks) == []


def test_the_candidate_s_plan_and_checks_jobs_hold_no_test_script():
    """release.yml's plan used to run five test scripts and its checks job the rest: both now plan, and call."""
    _, release, _ = _real()
    for job in ("plan", "checks"):
        assert not SHAPE.search(_runs(release["jobs"][job])), job


# ---------------------------------------------------------------------------------------------------------------- red on what was
def test_a_check_run_by_series_yml_itself_is_red():
    series, release, checks = _real()
    series["jobs"]["births"] = {"runs-on": "ubuntu-latest", "steps": [{"run": "python tools/births.py --tree source"}]}
    found = problems(series, release, checks)
    assert any("series.yml: job births runs 'tools/births.py --tree source' itself" in p for p in found)
    assert any("series.yml has the jobs" in p for p in found)


def test_a_test_script_added_to_the_plan_of_release_yml_is_red():
    series, release, checks = _real()
    release["jobs"]["plan"]["steps"].append({"run": "python3 scripts/test_something_new.py"})
    assert any("release.yml: job plan runs 'test_something_new.py', a check by its shape" in p for p in problems(series, release, checks))


def test_a_call_that_skips_a_candidate_is_red():
    series, release, checks = _real()
    release["jobs"]["checks"]["if"] = "github.event_name == 'pull_request'"
    assert any("a candidate it skips is first checked on main" in p for p in problems(series, release, checks))
    series, release, checks = _real()
    release["jobs"]["node"]["needs"] = ["plan"]
    assert any("the node does not wait for `checks`" in p for p in problems(series, release, checks))
    series, release, checks = _real()
    checks["jobs"]["rebuilds"]["if"] = "github.event_name == 'pull_request'"
    assert any("the job rebuilds can be skipped" in p for p in problems(series, release, checks))
    series, release, checks = _real()
    checks["jobs"]["rebuilds"]["uses"] = "./.github/workflows/gate.yml"
    assert any("the job rebuilds can be skipped" in p for p in problems(series, release, checks))


def test_a_series_yml_that_does_not_run_on_a_pull_request_is_red():
    series, release, checks = _real()
    del series[True]["pull_request"]
    assert any("series.yml does not run on pull_request" in p for p in problems(series, release, checks))


def test_a_check_dropped_from_checks_yml_is_red():
    series, release, checks = _real()
    for step in checks["jobs"]["rebuilds"]["steps"]:
        step["run"] = str(step.get("run", "")).replace("tools/births.py --tree source", "true")
    assert any("job rebuilds: the command 'tools/births.py --tree source' is missing" in p for p in problems(series, release, checks))
    series, release, checks = _real()
    del checks["jobs"]["noreply-identity"]
    assert any("checks.yml has no job noreply-identity" in p for p in problems(series, release, checks))


def test_the_workflows_as_they_were_before_checks_yml_are_red():
    """series.yml with its own jobs and release.yml with its plan and checks jobs: the shapes this decision replaced."""
    series, release, checks = _real()
    old_series = {"on": {"push": {"branches": ["main"]}, "pull_request": {"branches": ["main"]}},
                  "jobs": {"rules": {"runs-on": "ubuntu-latest", "steps": [{"run": "python -m pytest -q tools/tests"}, {"run": "python tools/engine.py check"}]},
                           "rebuilds": {"runs-on": "ubuntu-latest", "steps": [{"run": "python .series/tools/engine.py materialize --into source"},
                                                                              {"run": "python .series/tools/births.py --tree source"}]},
                           "noreply-identity": {"runs-on": "ubuntu-latest", "steps": [{"run": "python3 .noreply-judge/scripts/ci_noreply_identity.py"}]},
                           "gate": {"needs": ["rules", "rebuilds", "noreply-identity"], "steps": []}}}
    found = problems(old_series, release, checks)
    assert any("series.yml: job rebuilds runs 'tools/births.py --tree source' itself" in p for p in found)
    assert any("series.yml has the jobs" in p for p in found) and any("is not an unconditional call" in p for p in found)
    old_release = {"on": release["on"] if "on" in release else release[True],
                   "jobs": {"plan": {"steps": [{"run": "python3 scripts/test_release_plan.py"}]},
                            "checks": {"steps": [{"run": "python3 scripts/check_release_naming.py"}, {"run": "node --test juggler/tests/*.test.mjs"}]},
                            "node": {"needs": ["plan", "checks"]}, "build": {"needs": ["plan", "node"]}}}
    found = problems(series, old_release, checks)
    assert any("release.yml: job checks runs 'scripts/check_release_naming.py' itself" in p for p in found)
    assert any("release.yml: the job `checks` is not a call" in p for p in found)
