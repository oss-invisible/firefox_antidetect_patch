#!/usr/bin/env python3
"""release.yml: what does not depend on the binary is checked BEFORE a node is turned on, a re-launched or newer run does not pay for a server it cannot use,
and a newer push replaces the old candidate (and never a release).

Three things, each red on the workflow as it was:

  * the job `checks`, a call of checks.yml (every check that guards main, the same file series.yml calls on a pull request): asset names, declared upstream
    source, Juggler's tests without a browser and the release scripts' known-bad inputs. They used to run in the build job, on the node, minutes after it
    had been ordered (run 43156862361: 7.9 minutes of a paid hour for «Juggler's tests without a browser»). The node needs `checks` as well as `plan`;
  * a `concurrency` group per branch, whose newer candidate cancels the older, and a group of their own for a release and a re-launch, so that no push cancels
    a release or the run a re-launch replaces (republish.yml has none);
  * the guard `scripts/ci/still_head.py`, last step of the job `still-head` (after `checks`, before the node): a candidate that was queued behind a newer push is cancelled before the node starts.

    python3 scripts/ci/test_release_checks.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import datetime as dt  # noqa: E402

import gh_expr  # noqa: E402
import reuse_run  # noqa: E402
import still_head  # noqa: E402

WORKFLOWS = HERE.parent.parent / ".github" / "workflows"
CHECKS = ("Check asset names match the version this tree builds",
          "Check the declared upstream source matches the version this tree builds",
          "Juggler's tests without a browser",
          "The release scripts refuse what they must")
SHA = "a" * 40
NEWER = "b" * 40


def load(name):
    import yaml

    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def pattern_downloads(doc):
    """The `actions/download-artifact` steps of a workflow document whose `with:` has a `pattern:` together with `run-id:` or `github-token:`, as "job / step"."""
    found = []
    for job_name, job in (doc.get("jobs") or {}).items():
        for step in job.get("steps") or []:
            with_ = step.get("with") or {}
            if "actions/download-artifact" in str(step.get("uses", "")) and "pattern" in with_ and ("run-id" in with_ or "github-token" in with_):
                found.append("%s / %s" % (job_name, step.get("name", step.get("id", "?"))))
    return found

#: A step that runs scripts/release_plan.py (scripts/test_release_plan.py is not one: the name before `release_plan` is a word character).
RELEASE_PLAN = re.compile(r"(?<![\w])release_plan\.py")


def release_plan_problems(docs: dict) -> list:
    """Every step of the workflows `docs` ({file name: document}) that runs release_plan.py without what the plan needs, as "file / job / step: what".

    The plan resolves the core from the wrapper's pin by reading the wrapper's pyproject.toml through the API (scripts/release_plan.py): it needs the
    `--wrapper-ref` it reads at, a `GH_TOKEN` for the API (the runner has none in its environment: `gh` refuses without it) and, when it plans a run
    (`--event`), the `--core-ref` of the run too (empty is the pin). `--resolve-core-ref` alone takes the core_ref as optional. republish.yml's plan ran
    without all three (run 45874749497: «cannot be read: set the GH_TOKEN environment variable»)."""
    problems = []
    for name, doc in sorted(docs.items()):
        for job_name, job in (doc.get("jobs") or {}).items():
            for step in job.get("steps") or []:
                run = "\n".join(l for l in str(step.get("run", "")).splitlines() if not l.strip().startswith("#"))
                if not RELEASE_PLAN.search(run):
                    continue
                where = "%s / %s / %s" % (name, job_name, step.get("name", step.get("id", "?")))
                if "--wrapper-ref" not in run:
                    problems.append("%s: no --wrapper-ref" % where)
                if "--event" in run and "--core-ref" not in run:
                    problems.append("%s: no --core-ref" % where)
                if "GH_TOKEN" not in (step.get("env") or {}):
                    problems.append("%s: no GH_TOKEN in the step's env" % where)
    return problems


def core_ref_problems(checks_doc: dict, release_doc: dict) -> list:
    """What keeps checks.yml's `core-ref` on the run's own core (candidate run 45956455761: «the wrapper pins the core 70.84.0, and the core has no tag v70.84.0»,
    while the plan of the same run had resolved the core_ref it was given).

    checks.yml declares the input `core_ref`; every job of it that runs `release_plan.py --resolve-core-ref` passes `--core-ref` from that input; and release.yml's
    call of checks.yml hands over the core its plan resolved (`needs.plan.outputs.core_ref`), after the plan. As "where: what"."""
    problems = []
    inputs = (((checks_doc.get(True) or checks_doc.get("on") or {}).get("workflow_call") or {}).get("inputs")) or {}
    if "core_ref" not in inputs:
        problems.append("checks.yml: no input core_ref")
    for job_name, job in (checks_doc.get("jobs") or {}).items():
        for step in job.get("steps") or []:
            run = "\n".join(l for l in str(step.get("run", "")).splitlines() if not l.strip().startswith("#"))
            if not (RELEASE_PLAN.search(run) and "--resolve-core-ref" in run):
                continue
            where = "checks.yml / %s / %s" % (job_name, step.get("name", step.get("id", "?")))
            if "--core-ref" not in run:
                problems.append("%s: no --core-ref" % where)
            if "inputs.core_ref" not in str((step.get("env") or {}).get("CORE_REF", "")) or "$CORE_REF" not in run:
                problems.append("%s: --core-ref is not read from the input core_ref (env CORE_REF: ${{ inputs.core_ref }})" % where)
    call = (release_doc.get("jobs") or {}).get("checks") or {}
    if (call.get("with") or {}).get("core_ref") != "${{ needs.plan.outputs.core_ref }}":
        problems.append("release.yml / checks: core_ref is not the plan's (${{ needs.plan.outputs.core_ref }})")
    needs = call.get("needs")
    if "plan" not in ([needs] if isinstance(needs, str) else needs or []):
        problems.append("release.yml / checks: does not wait for the plan, whose output it reads")
    return problems


#: Workflows that are Mozilla's, not ours: on no branch of ours, never run (test_release_builder.py), so they are not ours to annotate.
UPSTREAM_WORKFLOWS = ("pr-handler.yml",)
#: What makes a step a test or a judge, read from its `run` (comment lines left out) and its `uses`: a failure of it is a red, never hidden by `continue-on-error`.
TEST_OR_JUDGE = re.compile(r"pytest|node --test|\btest_\w+\.py|cargo test|cargo_oracles|cargo_junit|ci_verdict|hook_tests_judge|py_junit|gtest|xpcshell|verdict")
#: The line right above every `continue-on-error`: its reason, which is not a test.
COE_REASON = re.compile(r"^\s*# continue-on-error: \S.*$")


def is_test_or_judge(step_or_job) -> bool:
    """Whether a step (or a job: all its steps) runs a test or a judge, by `TEST_OR_JUDGE` on the commands and the actions it uses."""
    steps = step_or_job.get("steps") or [step_or_job]
    text = []
    for step in steps:
        run = "\n".join(l for l in str(step.get("run", "")).splitlines() if not l.strip().startswith("#"))
        text += [run, str(step.get("uses", ""))]
    text.append(str(step_or_job.get("uses", "")))
    return TEST_OR_JUDGE.search("\n".join(text)) is not None


def continue_on_error_violations(name: str, text: str) -> list:
    """Every `continue-on-error` of a workflow's text that breaks the rule, as "<file> / <job> / <step>: <why>".

    The rule (ci-04, one judge per suite): no `continue-on-error` on a step that runs tests or a judge, and every other one has a comment `# continue-on-error:
    <reason, not a test>` on the line right above it. Read from the text, because YAML drops comments."""
    import textwrap

    import yaml

    lines, found, job, step_at = text.splitlines(), [], None, None
    for i, line in enumerate(lines):
        if re.match(r"^\S", line):
            job, step_at = None, None
        elif re.match(r"^  [\w.-]+:\s*$", line) and any(l.startswith("jobs:") for l in lines[:i]):
            job, step_at = line.strip().rstrip(":"), None
        elif re.match(r"^      - ", line) and job:
            step_at = i
        if re.match(r"^\s*continue-on-error:", line) and job:
            indent = len(line) - len(line.lstrip())
            if indent == 8 and step_at is not None:
                end = next((j for j in range(i + 1, len(lines)) if re.match(r"^(      - |  \S|\S)", lines[j])), len(lines))
                step = yaml.safe_load(textwrap.dedent("\n".join(lines[step_at:end])).replace("- ", "  ", 1))
                what = "%s / %s / %s" % (name, job, step.get("name", step.get("id", "?")))
                test = is_test_or_judge(step)
            elif indent == 4:
                start = next(j for j in range(i, -1, -1) if re.match(r"^  [\w.-]+:\s*$", lines[j]))
                end = next((j for j in range(i + 1, len(lines)) if re.match(r"^(  \S|\S)", lines[j])), len(lines))
                body = yaml.safe_load("\n".join(lines[start:end])) or {}
                what = "%s / %s / (the job)" % (name, job)
                test = is_test_or_judge(next(iter(body.values())) or {})
            else:
                found.append("%s / %s: a continue-on-error at an indent this check does not read" % (name, job))
                continue
            if test:
                found.append("%s: continue-on-error on a step that runs a test or a judge" % what)
            if not COE_REASON.match(lines[i - 1]):
                found.append("%s: no `# continue-on-error: <reason>` on the line right above" % what)
    return found


def count_continue_on_error(text: str) -> int:
    """How many `continue-on-error` KEYS (not comments) a workflow's text has, to prove that `continue_on_error_violations` read every one."""
    return len(re.findall(r"^\s*continue-on-error:", text, re.M))


#: ci-03 (a list of packages is resolved once per state, by one job; the legs install from its result, offline, by name; no leg reads a mirror). The jobs it is
#: held over so far, by file: every job of checks.yml, package-ab.yml, gate.yml and verify-assets.yml, and the Linux gtest and build jobs of release.yml. The rule over every
#: workflow comes with the conversion of the node. A third-party download is checked by a hash pinned in a repository.
CI03_SCOPE = {"checks.yml": None, "package-ab.yml": None, "gate.yml": None, "verify-assets.yml": None, "release.yml": ("gtest-linux", "build")}
PIP_COMMAND = re.compile(r"\bpip3?\s+(install|download|wheel)\b|\buv\s+pip\b")
PLAYWRIGHT_INSTALL = re.compile(r"\bplaywright\s+install(-deps)?\b")
DOWNLOAD_COMMAND = re.compile(r"\b(curl|wget|Invoke-WebRequest|iwr)\b|urllib\.request\.urlopen")
APT_INSTALL = re.compile(r"\bapt(-get)?\b[^\n|;&]*\binstall\b")
APT_UPDATE = re.compile(r"\bapt(-get)?\b[^\n|;&]*\bupdate\b")


def ci03_problems(docs: dict, scope: dict = CI03_SCOPE) -> list:
    """Every place in the jobs of `scope` where a leg reads a mirror, as "<file> / <job>: <what>": a `pip install` (or download, wheel, uv pip) without --no-index
    and --find-links, a pip job that does not need a call of py-deps.yml and download its wheelhouse, an `apt-get install` without --no-download, an `apt-get update`
    that is not on the run's local repository ($APT), a `playwright install-deps` (an apt read), a `playwright install` that is not served from the loopback after a sha256 check
    against the wrapper's pin, and a download (curl, wget, urlopen) in a step that checks no sha256."""
    found = []
    for name, jobs_wanted in scope.items():
        for job_name, job in (docs[name].get("jobs") or {}).items():
            if jobs_wanted is not None and job_name not in jobs_wanted:
                continue
            need = job.get("needs")
            need = [need] if isinstance(need, str) else list(need or [])
            deps = [n for n in need if str(docs[name]["jobs"].get(n, {}).get("uses", "")) == "./.github/workflows/py-deps.yml"]
            fetched = [st for st in job.get("steps") or [] if str(st.get("uses", "")).startswith("actions/download-artifact")
                       and str((st.get("with") or {}).get("name", "")).startswith("py-deps-")]
            pips = 0
            for step in job.get("steps") or []:
                whole = str(step.get("run", ""))
                if DOWNLOAD_COMMAND.search(whole) and "hashlib.sha256" not in whole and "sha256sum" not in whole:
                    found.append("%s / %s: a step downloads from a third party and checks no sha256" % (name, job_name))
                run = re.sub(r"\\\n\s*", " ", str(step.get("run", "")))   # a line continued with a backslash is one command
                for line in (l.strip() for l in run.splitlines() if not l.strip().startswith("#")):
                    if PIP_COMMAND.search(line):
                        pips += 1
                        if "--no-index" not in line or "--find-links" not in line:
                            found.append("%s / %s: `%s` reads the index (no --no-index --find-links)" % (name, job_name, line))
                    if APT_INSTALL.search(line) and "--no-download" not in line:
                        found.append("%s / %s: `%s` can fetch from a mirror (no --no-download)" % (name, job_name, line))
                    if APT_UPDATE.search(line) and "$APT" not in line:
                        found.append("%s / %s: `%s` reads a mirror's lists (not on the local repository)" % (name, job_name, line))
                    m = PLAYWRIGHT_INSTALL.search(line)
                    if m and m.group(1):
                        found.append("%s / %s: `%s` installs from an apt mirror (use linux-deps.yml)" % (name, job_name, line))
                    elif m and not ('PLAYWRIGHT_DOWNLOAD_HOST="http://127.0.0.1:' in whole and "ci/py-lock/playwright-browsers.json" in whole
                                    and "hashlib.sha256" in whole and whole.index("hashlib.sha256") < whole.rindex(m.group(0))):
                        found.append("%s / %s: `%s` downloads a browser that only its Content-Length checks (no archive checked against the wrapper's pin first)" % (name, job_name, line))
            if pips and not (deps and fetched):
                found.append("%s / %s: it installs packages but does not need a py-deps.yml call and download its wheelhouse" % (name, job_name))
    return found


#: The command lines that run a test (pytest) or drive the browser from python.exe: what a python.exe crash can happen in (a comment line is not one).
PYTHON_TEST_STEP = re.compile(r"python\S* (-u )?-m pytest\b|scripts/ci_(drive_gate|suite_run)\.py")


def crash_dump_problems(doc: dict, jobs=("gate", "wrapper-e2e")) -> list:
    """One line per job of gate.yml that has a Windows leg and does not keep a full dump of a python.exe that crashes: Windows Error Reporting LocalDumps for python.exe
    (DumpType 2, a DumpCount, a DumpFolder in the runner's temp) set by a pwsh step that runs on Windows only and comes BEFORE the first step that runs pytest, and the folder
    uploaded with always() as crash-dumps-<...>, kept 14 days, nothing if there is none."""
    out = []
    for job_id in jobs:
        job = doc["jobs"][job_id]
        steps = job.get("steps") or []
        legs = (job.get("strategy") or {}).get("matrix", {}).get("include") or []
        if not any("win" in str(leg.get("runner", "")) or leg.get("os") == "windows" or leg.get("kind") == "win" for leg in legs):
            out.append("%s has no Windows leg in its matrix (the rule reads the wrong job)" % job_id)
            continue
        setting = [i for i, st in enumerate(steps) if "LocalDumps" in str(st.get("run", ""))]
        if not setting:
            out.append("%s: no step sets LocalDumps for python.exe" % job_id)
            continue
        i = setting[0]
        run = str(steps[i]["run"])
        what = "%s: the step %r" % (job_id, steps[i].get("name"))
        if steps[i].get("shell") != "pwsh":
            out.append("%s does not run in pwsh" % what)
        if "Windows" not in str(steps[i].get("if", "")):
            out.append("%s is not on `if: runner.os == 'Windows'`" % what)
        for needle in (r"LocalDumps\python.exe", "-Name DumpFolder -PropertyType ExpandString", "-Name DumpType -PropertyType DWord -Value 2 ",
                       "-Name DumpCount -PropertyType DWord", "-Name Disabled -PropertyType DWord -Value 0", "-Name DontShowUI -PropertyType DWord -Value 1", "RUNNER_TEMP", "Get-ItemProperty"):
            if needle not in run:
                out.append("%s does not have `%s`" % (what, needle))
        first_test = [k for k, st in enumerate(steps) if any(PYTHON_TEST_STEP.search(l) for l in str(st.get("run", "")).splitlines() if not l.lstrip().startswith("#"))]
        if first_test and i > first_test[0]:
            out.append("%s comes after the first step that runs a test (%r)" % (what, steps[first_test[0]].get("name")))
        ups = [st for st in steps if str(st.get("uses", "")).startswith("actions/upload-artifact@") and str((st.get("with") or {}).get("name", "")).startswith("crash-dumps-")]
        if len(ups) != 1:
            out.append("%s: %d crash-dumps upload steps, not one" % (job_id, len(ups)))
        else:
            w = ups[0].get("with") or {}
            if str(ups[0].get("if", "")).replace(" ", "") != "always()":
                out.append("%s: the crash-dumps upload is not on `if: always()`" % job_id)
            if "runner.temp" not in str(w.get("path", "")) or not str(w.get("path", "")).endswith("/crash-dumps"):
                out.append("%s: the crash-dumps upload does not take <runner temp>/crash-dumps" % job_id)
            if w.get("retention-days") != 14 or w.get("if-no-files-found") != "ignore":
                out.append("%s: the crash-dumps upload is not retention 14, if-no-files-found ignore" % job_id)
    return out


def group_of(doc, inputs, ref="refs/heads/main", run_id=7):
    """The concurrency group and cancel-in-progress GitHub gives a run, by the workflow's own expressions."""
    context = {"inputs": inputs, "github": {"ref": ref, "run_id": run_id}}
    block = doc["concurrency"]
    return gh_expr.render(block["group"], context), gh_expr.evaluate(block["cancel-in-progress"].strip()[3:-2].strip(), context)


def _cases() -> list:
    out = []
    doc = load("release.yml")
    jobs = doc["jobs"]
    checks, node, build, guard_job = jobs["checks"], jobs["node"], jobs["build"], jobs["still-head"]
    called = load("checks.yml")
    tree = called["jobs"]["tree"]
    names = [s.get("name") for s in tree["steps"]]

    # --- the job `checks`: a call of checks.yml, which holds every check ------------------------------------------------------------------------------
    out.append(("checks: a job of its own that CALLS checks.yml (no `if`: every candidate, a release, the weekly run and a dispatch from a latitude/* branch run it), "
                "after the plan, whose core it takes; the node waits for the plan, the checks and the guard",
                checks.get("uses") == "./.github/workflows/checks.yml" and checks.get("needs") == "plan" and "if" not in checks
                and node["needs"] == ["plan", "checks", "still-head"]
                and build["needs"] == ["plan", "node", "py-deps-build-core", "py-deps-build-mach", "py-deps-build-lavapipe"]))
    out.append(("checks: the call hands over the wrapper_ref the run has (main by default) and the core_ref the plan resolved, reads and nothing else",
                checks["with"] == {"wrapper_ref": "${{ inputs.wrapper_ref || 'main' }}", "core_ref": "${{ needs.plan.outputs.core_ref }}"} and checks["permissions"] == {"contents": "read"}
                and called[True]["workflow_call"]["inputs"]["wrapper_ref"]["default"] == "main"))
    out.append(("checks: the four checks that do not read the binary are in the job `tree` of checks.yml, in this order, none conditioned on a leg",
                [n for n in names if n in CHECKS] == list(CHECKS) and not any("matrix" in str(s.get("if", "")) for s in tree["steps"])))
    out.append(("checks: none of them is left in the build job, on the node, nor in the plan",
                not any(s.get("name") in CHECKS for s in build["steps"] + jobs["plan"]["steps"])))
    text = " ".join(s.get("run", "") for s in tree["steps"])
    out.append(("checks: what they run is what the build used to run",
                "scripts/check_release_naming.py" in text and "check_upstream_source.py --online" in text and "node --test" in text and "juggler/tests/*.test.mjs" in text
                and "validate_release.py --selftest" in text and "test_make_seal.py" in text and "test_workflow_cache_rules.py" in text))
    plan_text = " ".join(s.get("run", "") for s in jobs["plan"]["steps"])
    plans = ("scripts/test_release_plan.py", "scripts/ci/test_ci.py", "scripts/ci/test_stealth_download_watchdog.py", "scripts/ci/test_objects_first.py",
             "scripts/ci/test_stealth_build_tools.py")
    out.append(("checks: the plan's own tests moved from the plan to the job `tree`: there, once each; in the plan, none (it plans, `scripts/ci matrix` stays)",
                all(("python3 " + t) in text for t in plans) and not any(t in plan_text for t in plans) and 'scripts/ci matrix' in plan_text))
    out.append(("checks: the tree is materialized from the series before they run, on a GitHub runner",
                "engine.py materialize --into ." in str(next(st for st in tree["steps"] if "engine.py materialize" in str(st.get("run", ""))).get("run"))
                and tree["runs-on"] == "ubuntu-24.04"
                and names.index(CHECKS[0]) > names.index("The source tree, the Mozilla tag with our series applied (tools/engine.py)")))
    out.append(("checks: no secret and no environment in any job of checks.yml (the node job alone has them), and a token that only reads",
                "secrets." not in str(called) and not any("environment" in j for j in called["jobs"].values()) and called["permissions"] == {"contents": "read"}
                and not any("permissions" in j for j in called["jobs"].values())))
    out.append(("checks: the job `tree` has a limit", 0 < tree.get("timeout-minutes", 0) <= 30))
    out.append(("checks: the jobs the two rounds share, by name: rules, churn (port-07), range-diff (series-02), rebuilds, noreply-identity, tree, and the three that give them their packages "
                "(ci-03): py-deps-tools, core-ref, py-deps-core",
                list(called["jobs"]) == ["py-deps-tools", "core-ref", "py-deps-core", "rules", "churn", "range-diff", "rebuilds", "noreply-identity", "tree"]))
    # The series rule «export commits are named export:» is judged in the job `noreply-identity` (its checkout, its range of the event), not in a job of its own.
    noreply_steps = called["jobs"]["noreply-identity"]["steps"]
    rule_steps = [st for st in noreply_steps if "export_commit_names.py" in str(st.get("run", ""))]
    rule_run = str(rule_steps[0].get("run", "")) if rule_steps else ""
    rule_env = rule_steps[0].get("env", {}) if rule_steps else {}
    judge_index = next((i for i, st in enumerate(noreply_steps) if "ci_noreply_identity.py" in str(st.get("run", ""))), -1)
    out.append(("export rule: one step of the job `noreply-identity` runs scripts/ci/export_commit_names.py by its exported path, after the noreply judge, and no job of its own",
                len(rule_steps) == 1 and noreply_steps.index(rule_steps[0]) > judge_index >= 0
                and "platform/ci/src/scripts/ci/export_commit_names.py" in rule_run and "--repo ." in rule_run and '--range "$range"' in rule_run
                and not any("export_commit_names.py" in str(job.get("steps")) for name, job in called["jobs"].items() if name != "noreply-identity")))
    sparse = str(noreply_steps[0]["with"]["sparse-checkout"]).split()
    out.append(("export rule: the sparse checkout of the series holds the script and its classes (tools/export_paths.py) beside .github, in the same style, and still no tree",
                sparse == ["/.github/", "/platform/ci/src/scripts/ci/export_commit_names.py", "/tools/export_paths.py"] and noreply_steps[0]["with"]["filter"] == "tree:0"
                and noreply_steps[0]["with"]["fetch-depth"] == 0))
    out.append(("export rule: a pull request judges base..head, a push before..after (HEAD~1..HEAD when before is all zeros), a schedule or a dispatch what the ref adds to the default branch",
                '$BASE_SHA..$HEAD_SHA' in rule_run and '$BEFORE..$AFTER' in rule_run and "0000000000000000000000000000000000000000" in rule_run
                and "HEAD~1..HEAD" in rule_run and 'origin/$DEFAULT_BRANCH..$SHA' in rule_run
                and rule_env.get("BASE_SHA") == "${{ github.event.pull_request.base.sha }}" and rule_env.get("HEAD_SHA") == "${{ github.event.pull_request.head.sha }}"
                and rule_env.get("BEFORE") == "${{ github.event.before }}" and rule_env.get("AFTER") == "${{ github.event.after }}"
                and rule_env.get("SHA") == "${{ github.sha }}" and rule_env.get("EVENT") == "${{ github.event_name }}"))
    out.append(("export rule: a script that is missing is an error, not a pass, and the rule is written beside the step",
                'exit 1' in rule_run and "[ ! -f" in rule_run and "set -euo pipefail" in rule_run
                and "# RULE export commits are named export:" in (WORKFLOWS / "checks.yml").read_text(encoding="utf-8")))
    gnames = [s.get("name") for s in guard_job["steps"]]
    out.append(("guard: a job `still-head` of release.yml, after the checks (it needs nothing else), with the token that may cancel this very run and read; "
                "the guard that a newer push has not replaced the run is its LAST step, the one that can cancel",
                guard_job["needs"] == ["checks"] and guard_job["permissions"] == {"actions": "write", "contents": "read"} and "if" not in guard_job
                and gnames[-1] == "Still the head of the branch" and "gh run cancel" in guard_job["steps"][-1]["run"]
                and "sleep 240" in guard_job["steps"][-1]["run"] and "still_head.py" in guard_job["steps"][-1]["run"]))
    guard = guard_job["steps"][-1]
    out.append(("guard: it is not in checks.yml (a called workflow cannot cancel its caller: no `actions: write`, and it means nothing for a pull request)",
                "still_head" not in str(called)))
    out.append(("guard: the guard hands over the event, the ref, the commit, the kind and the re-launch, as the plan reads them",
                guard["env"]["EVENT"] == "${{ github.event_name }}" and guard["env"]["REF"] == "${{ github.ref }}" and guard["env"]["SHA"] == "${{ github.sha }}"
                and guard["env"]["KIND"] == "${{ inputs.kind }}" and guard["env"]["RELAUNCH_OF"] == "${{ inputs.relaunch_of }}"))
    run = guard["run"]
    out.append(("guard: only an exit of 1 cancels; the head that cannot be read (2) goes on",
                '[ "$CODE" = 1 ]' in run and run.rstrip().endswith("exit 0") and "set +e" in run))
    out.append(("node: still turned on only by the plan's attempt, and the permissions and steps the other tests hold it to are untouched",
                node["if"].startswith("needs.plan.outputs.attempt == github.run_attempt") and node["permissions"] == {"actions": "read", "contents": "read"}
                and all(s["if"] == "steps.closure.outputs.cache-hit != 'true'" for s in node["steps"] if "if" in s)))

    # --- the concurrency --------------------------------------------------------------------------------------------------------------------------
    push = group_of(doc, {})
    candidate = group_of(doc, {"kind": "candidate"})
    other = group_of(doc, {"kind": "candidate"}, run_id=8)
    elsewhere = group_of(doc, {"kind": "candidate"}, ref="refs/heads/latitude/x", run_id=9)
    release = group_of(doc, {"kind": "release"}, run_id=10)
    release2 = group_of(doc, {"kind": "release"}, run_id=11)
    relaunch = group_of(doc, {"kind": "candidate", "relaunch_of": "123"}, run_id=12)
    out.append(("concurrency: a push and a dispatch of a candidate on one branch share a group, and a newer run cancels the older one in it",
                push[0] == candidate[0] == other[0] == "candidate-refs/heads/main" and push[1] is True and candidate[1] is True and other[1] is True))
    out.append(("concurrency: another branch is another group", elsewhere[0] == "candidate-refs/heads/latitude/x" and elsewhere[0] != push[0]))
    out.append(("concurrency: a release has a group of its own, per run, and is never cancelled by a push; two releases do not share one",
                release[0] == "release-10" and release2[0] == "release-11" and release[1] is False and release[0] != push[0]))
    out.append(("concurrency: a re-launch has a group of its own too: it does not cancel the run it replaces, which is still reporting, and is not cancelled",
                relaunch[0] == "relaunch-12" and relaunch[1] is False))
    out.append(("concurrency: republish.yml, which publishes a run's archives, has none: no push touches it", "concurrency" not in load("republish.yml")))
    out.append(("concurrency: no other workflow of the build got one by mistake",
                all("concurrency" not in load(n) for n in ("gate.yml", "publish.yml"))))

    # --- the plan's inputs: every step that runs release_plan.py gives it the refs and a token (republish run 45874749497) -------------------------------
    every = {w.name: load(w.name) for w in sorted(WORKFLOWS.glob("*.yml"))}
    plan_files = {n for n, d in every.items() for j in (d.get("jobs") or {}).values() for s in j.get("steps") or [] if RELEASE_PLAN.search(str(s.get("run", "")))}
    plan_step = {"name": "Plan", "env": {"GH_TOKEN": "${{ github.token }}"},
                 "run": 'python3 scripts/release_plan.py --event workflow_dispatch --kind release --core-ref "$CORE_REF" --wrapper-ref "$WRAPPER_REF"'}
    bare = {"name": "Plan", "env": {"RELEASE_TAG": "x"}, "run": 'python3 scripts/release_plan.py --event workflow_dispatch --kind release --release-tag "$RELEASE_TAG"'}

    def one(step):
        return {"w.yml": {"jobs": {"plan": {"steps": [step]}}}}
    out.append(("plan inputs: every step of every workflow that runs release_plan.py gives it --wrapper-ref, --core-ref (a plan) and a GH_TOKEN; release.yml, republish.yml and checks.yml run it",
                release_plan_problems(every) == [] and {"release.yml", "republish.yml", "checks.yml"} <= plan_files))
    out.append(("plan inputs: red for a plan with neither ref nor token (republish.yml's plan step as it was), each one named; green for one with all three",
                release_plan_problems(one(bare)) == ["w.yml / plan / Plan: no --wrapper-ref", "w.yml / plan / Plan: no --core-ref", "w.yml / plan / Plan: no GH_TOKEN in the step's env"]
                and release_plan_problems(one(plan_step)) == []))
    out.append(("plan inputs: red for each one missing alone; scripts/test_release_plan.py is not a plan and a comment that names release_plan.py is not a step",
                release_plan_problems(one(dict(plan_step, env={}))) == ["w.yml / plan / Plan: no GH_TOKEN in the step's env"]
                and release_plan_problems(one(dict(plan_step, run=plan_step["run"].replace(' --core-ref "$CORE_REF"', "")))) == ["w.yml / plan / Plan: no --core-ref"]
                and release_plan_problems(one(dict(plan_step, run=plan_step["run"].replace(' --wrapper-ref "$WRAPPER_REF"', "")))) == ["w.yml / plan / Plan: no --wrapper-ref"]
                and release_plan_problems(one({"name": "t", "run": "python3 scripts/test_release_plan.py"})) == []
                and release_plan_problems(one({"name": "c", "run": "# release_plan.py says why\ntrue"})) == []))
    out.append(("plan inputs: --resolve-core-ref takes the wrapper's ref and the token and no core_ref (the job core-ref of checks.yml)",
                release_plan_problems(one({"name": "core", "env": {"GH_TOKEN": "t"}, "run": 'python3 release_plan.py --resolve-core-ref --wrapper-ref "$W"'})) == []))
    rep = load("republish.yml")
    out.append(("plan inputs: republish.yml's gate and publish take the refs the plan resolved, not the inputs: the core the gate installs is the one the plan checked against the pin",
                all(rep["jobs"]["gate"]["with"][k] == "${{ needs.plan.outputs.%s }}" % k for k in ("core_ref", "wrapper_ref"))
                and rep["jobs"]["publish"]["with"]["wrapper_ref"] == "${{ needs.plan.outputs.wrapper_ref }}"
                and set(rep["jobs"]["plan"]["outputs"]) >= {"core_ref", "wrapper_ref"}))

    # --- the core of checks.yml's `core-ref` is the run's, not the wrapper's pin (candidate run 45956455761) -----------------------------------------------
    resolve = {"name": "The core", "env": {"GH_TOKEN": "t", "CORE_REF": "${{ inputs.core_ref }}"},
               "run": 'args=(--resolve-core-ref --wrapper-ref "$W")\nif [ -n "$CORE_REF" ]; then args+=(--core-ref "$CORE_REF"); fi\npython3 .series/scripts/release_plan.py "${args[@]}"'}
    ok_checks = {True: {"workflow_call": {"inputs": {"core_ref": {}}}}, "jobs": {"core-ref": {"steps": [resolve]}}}
    ok_release = {"jobs": {"checks": {"needs": "plan", "with": {"core_ref": "${{ needs.plan.outputs.core_ref }}"}}}}
    old_step = dict(resolve, env={"GH_TOKEN": "t"}, run='python3 .series/scripts/release_plan.py --resolve-core-ref --wrapper-ref "$W"')
    out.append(("core of the run: checks.yml declares the input core_ref, every job of it that resolves the core passes --core-ref from it, and release.yml's call hands over "
                "the plan's core_ref after the plan",
                core_ref_problems(called, doc) == [] and any(RELEASE_PLAN.search(str(s.get("run", ""))) and "--resolve-core-ref" in str(s.get("run", ""))
                                                              for j in called["jobs"].values() for s in j.get("steps") or [])))
    out.append(("core of the run: red for checks.yml as it was (no input, a resolver without --core-ref) and release.yml's call as it was (no core_ref, no needs), each named",
                core_ref_problems({True: {"workflow_call": {"inputs": {"wrapper_ref": {}}}}, "jobs": {"core-ref": {"steps": [old_step]}}},
                                  {"jobs": {"checks": {"with": {"wrapper_ref": "main"}}}})
                == ["checks.yml: no input core_ref", "checks.yml / core-ref / The core: no --core-ref",
                    "checks.yml / core-ref / The core: --core-ref is not read from the input core_ref (env CORE_REF: ${{ inputs.core_ref }})",
                    "release.yml / checks: core_ref is not the plan's (${{ needs.plan.outputs.core_ref }})", "release.yml / checks: does not wait for the plan, whose output it reads"]
                and core_ref_problems(ok_checks, ok_release) == []))

    # --- the guard --------------------------------------------------------------------------------------------------------------------------------
    def head(value):
        return lambda repository, ref: value

    def judged(event="push", ref="refs/heads/main", sha=SHA, kind="", relaunch="", now=SHA, files=("dom/base/Foo.cpp",)):
        return still_head.judge(event, ref, sha, kind, relaunch, "o/r", head=head(now), changed=lambda repository, base, tip: None if files is None else list(files))

    out.append(("guard: the head is the commit the run builds: go on", judged()[0] == 0))
    code, said = judged(now=NEWER)
    out.append(("guard: a newer commit is the head: superseded, and it says which", code == 1 and NEWER[:12] in said and SHA[:12] in said))
    out.append(("guard: the weekly run and a dispatch of a candidate are judged the same",
                judged(event="schedule", now=NEWER)[0] == 1 and judged(event="workflow_dispatch", kind="candidate", now=NEWER)[0] == 1))
    out.append(("guard: a RELEASE is never judged, whatever the branch did after", judged(event="workflow_dispatch", kind="release", now=NEWER)[0] == 0))
    out.append(("guard: a re-launch is never judged", judged(event="workflow_dispatch", relaunch="123", now=NEWER)[0] == 0))
    out.append(("guard: a tag is not a branch: not judged", judged(ref="refs/tags/firefox-63", now=NEWER)[0] == 0))
    out.append(("guard: a branch whose pushes start no candidate (a latitude/<name> proof) is not judged: nobody would replace the run",
                judged(event="workflow_dispatch", kind="candidate", ref="refs/heads/latitude/proof", now=NEWER)[0] == 0))
    out.append(("guard: a newer head that touches only Markdown starts no candidate (paths-ignore): this run stays, it is not cancelled for nothing",
                judged(now=NEWER, files=("README.md", "docs/a.MD"))[0] == 0 and "Markdown" in judged(now=NEWER, files=("README.md",))[1]))
    out.append(("guard: a newer head with ONE other path among Markdown ones replaces the run",
                judged(now=NEWER, files=("README.md", "dom/base/Foo.cpp"))[0] == 1
                and judged(now=NEWER, files=("a.md", "b.md", "scripts/ci/x.py"))[0] == 1))
    out.append(("guard: when the paths of the newer head cannot be read the run goes on (2), and an empty list is not Markdown only",
                judged(now=NEWER, files=None)[0] == 2 and judged(now=NEWER, files=())[0] == 1))
    out.append(("guard: a compare of 300 files is never Markdown only",
                still_head.changed_files("o/r", SHA, NEWER, run=lambda cmd, **kw: type("D", (), {"returncode": 0, "stdout": '{"files": [%s]}' % ",".join(
                    '{"filename": "f%d.md"}' % i for i in range(300))})())[-1].startswith("<more than")))
    out.append(("guard: the compare API's answer is read for the file names; a failure, or a broken answer, is None",
                still_head.changed_files("o/r", SHA, NEWER, run=lambda cmd, **kw: type("D", (), {"returncode": 0, "stdout": '{"files": [{"filename": "a.md"}]}'})()) == ["a.md"]
                and still_head.changed_files("o/r", SHA, NEWER, run=lambda cmd, **kw: type("D", (), {"returncode": 1, "stdout": ""})()) is None
                and still_head.changed_files("o/r", SHA, NEWER, run=lambda cmd, **kw: type("D", (), {"returncode": 0, "stdout": "not json"})()) is None))
    out.append(("guard: a head that cannot be read is 2 and the run goes on", judged(now="")[0] == 2))
    asked = []
    still_head.judge("workflow_dispatch", "refs/heads/main", SHA, "release", "", "o/r", head=lambda r, f: asked.append(f) or NEWER)
    out.append(("guard: what it does not judge it does not ask the repository about", asked == []))

    import subprocess

    def hang(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 60)

    out.append(("guard: a `git ls-remote` that hangs past its timeout is a head that cannot be read (""), never a reason to cancel",
                still_head.head_of("o/r", "refs/heads/main", run=hang) == ""
                and still_head.judge("push", "refs/heads/main", SHA, "candidate", "", "o/r", head=lambda r, f: still_head.head_of(r, f, run=hang))[0] == 2))
    import contextlib
    import io

    def guard_main(**patches):
        saved = {k: getattr(still_head, k) for k in patches}
        for k, v in patches.items():
            setattr(still_head, k, v)
        buffer = io.StringIO()
        try:
            with contextlib.redirect_stdout(buffer):
                return still_head.main(["--event", "push", "--ref", "refs/heads/main", "--sha", SHA, "--kind", "candidate", "--relaunch-of", "", "--repository", "o/r"])
        finally:
            for k, v in saved.items():
                setattr(still_head, k, v)

    def boom(*args, **kw):
        raise RuntimeError("anything")

    out.append(("guard: main() never turns an unexpected failure into exit 1 (which cancels the run): it is 2", guard_main(judge=boom) == 2))

    class Done:
        def __init__(self, code, stdout):
            self.returncode, self.stdout = code, stdout

    ref = "refs/heads/main"
    out.append(("guard: the head is read from `git ls-remote` of the public repository, the line of the ref and no other",
                still_head.head_of("o/r", ref, run=lambda cmd, **kw: Done(0, "%s\trefs/heads/maintenance\n%s\t%s\n" % (NEWER, SHA, ref))) == SHA
                and still_head.head_of("o/r", ref, run=lambda cmd, **kw: Done(128, "")) == ""
                and still_head.head_of("o/r", ref, run=lambda cmd, **kw: Done(0, "")) == ""))
    out += _reuse_cases(doc)
    # --- publish.yml: every archive is downloaded by its artifact's name, never by a pattern (run 45278854452: a pattern saw the first 100 of 121) --
    pub_steps = load("publish.yml")["jobs"]
    pub_steps = [s for job in pub_steps.values() for s in job.get("steps", [])]
    by_pattern = [s for s in pub_steps if "download-artifact" in str(s.get("uses", "")) and "asset" in str((s.get("with") or {}).get("pattern", ""))]
    out.append(("publish: no build asset is downloaded by a pattern (a pattern sees one page of a run's artifacts; run 45278854452 lost asset-linux-x86_64)",
                by_pattern == []))
    by_name = [s for s in pub_steps if "actions/runs/$BUILD_RUN/artifacts?name=asset-$leg" in str(s.get("run", ""))]
    legs_run = str(by_name[0].get("run", "")) if by_name else ""
    out.append(("publish: each archive is downloaded by its name, asset-<leg>, for every leg of the tree (scripts/ci matrix), and a missing one is red",
                len(by_name) == 1 and "_src/scripts/ci matrix" in legs_run and "for leg in $LEGS" in legs_run and "exit 1" in legs_run))
    # --- no workflow downloads a run's artifacts by a pattern across runs (run 45381665911: hook-tests-judge listed one page of 100 of 125+ artifacts, did not find
    # gtest-reports-win-x86_64, and 189 hook tests went red though the win gtests had passed). With `run-id` or `github-token` the action lists the run's artifacts
    # through the REST API, one page of 100: a name is the only form that finds its artifact.
    import yaml

    bad = {}
    for path in sorted(WORKFLOWS.glob("*.yml")):
        offenders = pattern_downloads(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
        if offenders:
            bad[path.name] = offenders
    old_judge = {"jobs": {"judge": {"steps": [{"name": "The gtest reports of both legs", "uses": "actions/download-artifact@v4",
                                              "with": {"pattern": "gtest-reports-*", "path": "gtest-reports", "run-id": "1", "github-token": "t"}},
                                             {"name": "The junit", "uses": "actions/download-artifact@v4", "with": {"pattern": "junit-*", "path": "junit"}},
                                             {"name": "By name", "uses": "actions/download-artifact@v4", "with": {"name": "a", "run-id": "1", "github-token": "t"}}]}}}
    out.append(("no workflow downloads by `pattern:` together with `run-id:` or `github-token:` (one page of 100 artifacts; run 45381665911 lost gtest-reports-win-x86_64)%s"
                % ("" if not bad else ": " + "; ".join("%s: %s" % (f, ", ".join(o)) for f, o in bad.items())),
                not bad and pattern_downloads(old_judge) == ["judge / The gtest reports of both legs"]))
    # --- the Linux legs of the gate and of its xpcshell read no mirror (republish 45297517213: `playwright install-deps firefox` at 102 kB/s, a green
    # leg cancelled at its 25 minutes). Their apt reads only the run's linux-deps repository (linux-deps.yml): its own sources list, sources folder and
    # lists folder, and installs the roots by name with --no-download (wrapper PR #584: .deb files installed against another image build wanted a fetch).
    APT_LOCAL = "-o Dir::Etc::SourceList=/tmp/linux-deps-apt/sources.list -o Dir::Etc::SourceParts=/tmp/linux-deps-apt/parts -o Dir::State::Lists=/tmp/linux-deps-apt/lists -o Acquire::Languages=none"
    allowed = ("sudo apt-get $APT update", "sudo apt-get $APT install -y --no-download --no-install-recommends $(cat /tmp/linux-deps/roots.txt)")
    # --- the release path of the declared preference changes: the gate (a release's too) calls xpcshell.yml, whose prefs job applies the rows of the series' own
    # tools/prefs-declared.json (the checkout of the commit the run is on) to the published baseline before it allows zero differences, and is red on a STALE row: a release
    # whose published baseline already holds a row is red until the row is removed (xpcshell_run.py prefs-compare, its cases in test_xpcshell_run.py)
    prefs_steps = load("xpcshell.yml")["jobs"]["prefs"]["steps"]
    compare_runs = [str(st.get("run", "")) for st in prefs_steps if "prefs-compare prefs-out/published-1.json prefs-out/candidate.json" in str(st.get("run", ""))]
    series_checkout = [st.get("with") or {} for st in prefs_steps if str((st.get("with") or {}).get("path", "")) == "engine-series"]
    out.append(("release path: the gate calls xpcshell.yml, whose prefs job compares the published engine with the candidate after the rows of tools/prefs-declared.json of the run's own "
                "checkout of the series (a stale row, one the published baseline already holds, is red there until it is removed)",
                any(j.get("uses") == "./.github/workflows/xpcshell.yml" for j in load("gate.yml")["jobs"].values())
                and len(compare_runs) == 1 and "--declared engine-series/tools/prefs-declared.json" in compare_runs[0]
                and len(series_checkout) == 1 and series_checkout[0].get("ref") == "${{ github.sha }}" and "/tools/prefs-declared.json" in str(series_checkout[0].get("sparse-checkout"))))
    legs_of = {"gate.yml": ("gate", "wrapper-e2e"), "xpcshell.yml": ("xpcshell", "prefs")}
    for wf_name, job_names in legs_of.items():
        wf_jobs = load(wf_name)["jobs"]
        for job_name in job_names:
            job = wf_jobs.get(job_name) or {}
            text = "\n".join(str(st.get("run", "")) for st in job.get("steps", []))
            apt_lines = [l.strip() for l in text.splitlines() if "apt-get" in l or "apt install" in l or "apt update" in l]
            other = [l for l in apt_lines if l not in allowed]
            out.append(("%s %s: no `playwright install-deps`, and apt only on the run's linux-deps repository, the roots by name with --no-download (%s)"
                        % (wf_name, job_name, "; ".join(other) or "nothing else"),
                        bool(job) and "install-deps" not in text and not other and all(a in apt_lines for a in allowed)
                        and ('APT="%s"' % APT_LOCAL) in text and 'echo "deb [trusted=yes] file:/tmp/linux-deps ./" | sudo tee /tmp/linux-deps-apt/sources.list' in text
                        and "sudo cp /tmp/linux-deps/*.deb /var/cache/apt/archives/" in text))
            need = job.get("needs")
            need = [need] if isinstance(need, str) else list(need or [])
            deps_jobs = [n for n in need if str((wf_jobs.get(n) or {}).get("uses", "")) == "./.github/workflows/linux-deps.yml"]
            fetched = [st for st in job.get("steps", []) if "download-artifact" in str(st.get("uses", ""))
                       and str((st.get("with") or {}).get("name", "")) in ["${{ needs.%s.outputs.artifact }}" % n for n in deps_jobs]
                       and str((st.get("with") or {}).get("path", "")) == "/tmp/linux-deps"]
            installing = [i for i, st in enumerate(job.get("steps", [])) if allowed[1] in str(st.get("run", ""))]
            out.append(("%s %s: its repository is the artifact of a linux-deps.yml job it needs, downloaded to /tmp/linux-deps before the install" % (wf_name, job_name),
                        len(deps_jobs) == 1 and len(fetched) == 1 and len(installing) == 1 and job["steps"].index(fetched[0]) < installing[0]))
    deps_steps = load("linux-deps.yml")["jobs"]["debs"]["steps"]
    deps_run = "\n".join(str(st.get("run", "")) for st in deps_steps)
    out.append(("linux-deps.yml: a repository of the closure (Depends and Pre-Depends, recursively, what the image has included), its Packages index and its roots, "
                "every root checked in it, Playwright's roots read from its table",
                "apt-cache depends --recurse --no-recommends" in deps_run and "apt-get download" in deps_run and "apt-ftparchive packages . > Packages" in deps_run
                and "roots.txt" in deps_run and "is not in the repository" in deps_run and 'for group in ("tools", "firefox")' in deps_run
                and "--download-only" not in deps_run))
    # wrapper PR #585: libgtk-3-0 is a name libgtk-3-0t64 provides (a root check on Package: alone refused it), a key per image build missed the entry
    # run after run (the builds of one release are mixed in a run), and a closure read one package at a time took 13 minutes from a slow mirror.
    out.append(("linux-deps.yml: a root may be a name a package of the repository provides, the entry is per release of the image (not per build), "
                "the closure is downloaded 8 at a time and every package of it is checked",
                "Provides: (.*, )?$e" in deps_run and 'RELEASE="${ImageVersion%%.*}"' in deps_run and "$ImageVersion-$SHA" not in deps_run
                and "Reverse Provides:" in deps_run and "not by one package" in deps_run and "xargs -n 20 -P 8 apt-get download -qq -o Acquire::Retries=5" in deps_run and "of the closure was not downloaded" in deps_run and "MB in $((T1 - T0)) s" in deps_run
                and load("linux-deps.yml")["jobs"]["debs"]["timeout-minutes"] == 20))
    out.append(("linux-deps.yml: the archive is read only when the entry of this image and list is missing",
                all(st.get("if") == "steps.restore.outputs.cache-hit != 'true'" for st in deps_steps
                    if "apt-get" in str(st.get("run", "")) or str(st.get("uses", "")).startswith("actions/cache/save"))))

    # --- ci-03, for the files converted so far (checks.yml, package-ab.yml, and the gtest-linux job of release.yml): no leg reads a mirror --------------------------
    real = {n: load(n) for n in CI03_SCOPE}
    bad_pip = {"jobs": {"j": {"steps": [{"run": "pip install pytest pyyaml"}]}}}
    bad_pip2 = {"jobs": {"j": {"steps": [{"run": 'python -m pip install --quiet --no-index -r "$RUNNER_TEMP/py-deps/lock.txt"'}]}}}
    bad_apt = {"jobs": {"j": {"steps": [{"run": "sudo apt-get update\nsudo apt-get install -y xvfb gdb"}]}}}
    bad_needs = {"jobs": {"j": {"steps": [{"run": 'pip install --no-index --find-links "$RUNNER_TEMP/py-deps" -r lock.txt'}]}}}
    good = {"jobs": {"deps": {"uses": "./.github/workflows/py-deps.yml"},
                     "j": {"needs": "deps", "steps": [{"uses": "actions/download-artifact@x", "with": {"name": "py-deps-tools-linux", "path": "w"}},
                                                      {"run": 'python -m pip install --no-index --find-links "$RUNNER_TEMP/py-deps" --require-hashes -r "$RUNNER_TEMP/py-deps/lock.txt"\n'
                                                              'sudo apt-get $APT update\nsudo apt-get $APT install -y --no-download xvfb'}]}}}
    scope_x = {"x.yml": None}
    out.append(("ci-03 in checks.yml, package-ab.yml, gate.yml, verify-assets.yml and release.yml's gtest-linux and build: every `pip install` carries --no-index and --find-links and its job needs a py-deps.yml call and "
                "downloads its wheelhouse; every `apt-get install` carries --no-download and every `apt-get update` is on the local repository (%s)"
                % ("; ".join(ci03_problems(real)) or "none does otherwise"),
                ci03_problems(real) == []
                and any("reads the index" in p for p in ci03_problems({"x.yml": bad_pip}, scope_x))
                and any("reads the index" in p for p in ci03_problems({"x.yml": bad_pip2}, scope_x))
                and any("no --no-download" in p for p in ci03_problems({"x.yml": bad_apt}, scope_x))
                and any("reads a mirror's lists" in p for p in ci03_problems({"x.yml": bad_apt}, scope_x))
                and any("does not need a py-deps.yml call" in p for p in ci03_problems({"x.yml": bad_needs}, scope_x))
                and ci03_problems({"x.yml": good}, scope_x) == []
                and set(real["release.yml"]["jobs"]) >= {"gtest-linux", "linux-deps-gtest"}
                and all(real[n]["jobs"].get(j) for n, js in CI03_SCOPE.items() for j in (js or ()))))
    out.append(("ci-03: the jobs that install Python packages in those files are the ones that need a py-deps.yml call: rules, rebuilds and tree (checks.yml), package-ab (package-ab.yml), build (release.yml)",
                all(any(str(real[f]["jobs"][d].get("uses", "")) == "./.github/workflows/py-deps.yml"
                        for d in ([real[f]["jobs"][j]["needs"]] if isinstance(real[f]["jobs"][j]["needs"], str) else real[f]["jobs"][j]["needs"]))
                    for f, j in (("checks.yml", "rules"), ("checks.yml", "rebuilds"), ("checks.yml", "tree"), ("package-ab.yml", "package-ab"), ("release.yml", "build")))))
    # gate.yml, verify-assets.yml (ci-03): what the old files had, quoted, is red; the shape that replaced it is green
    old_gate = {"jobs": {"gate": {"steps": [{"run": 'python -m pip install --quiet "playwright==$(cat scripts/playwright_pin.txt)"'},
                                            {"run": 'CORE_GIT="git+https://github.com/oss-invisible/core@$CORE_REF"\npython -m pip install --quiet "$CORE_GIT"\n'
                                                    'python -m pip install --quiet ".[dev]"\npython -m pip install --quiet --force-reinstall "$CORE_GIT"'},
                                            {"run": 'python -m pip install --quiet "cryptography==44.0.3"'}]}}}
    old_browser = {"jobs": {"wrapper-e2e": {"steps": [{"run": 'python -m playwright install firefox'}]}}}
    old_deps = {"jobs": {"drive": {"steps": [{"run": 'sudo "$(which python)" -m playwright install-deps firefox'}]}}}
    old_curl = {"jobs": {"j": {"steps": [{"run": 'curl -fsSL https://example.org/browser.zip -o browser.zip'}]}}}
    old_urlopen = {"jobs": {"j": {"steps": [{"run": "python - <<'PY'\nimport urllib.request\nurllib.request.urlopen('https://example.org/x').read()\nPY\n"}]}}}
    served = ('export PLAYWRIGHT_DOWNLOAD_HOST="http://127.0.0.1:$PORT"\n'
              "python - <<'PY'\nimport hashlib\npin = 'ci/py-lock/playwright-browsers.json'\nhashlib.sha256(b'').hexdigest()\nPY\npython -m playwright install firefox\n")
    new_browser = {"jobs": {"wrapper-e2e": {"steps": [{"run": served}]}}}
    scope_y = {"x.yml": None}
    out.append(("ci-03 gate.yml and verify-assets.yml: the old steps are red, quoted: `pip install \"playwright==$(cat scripts/playwright_pin.txt)\"`, `pip install \"$CORE_GIT\"` and `.[dev]`, "
                "`pip install \"cryptography==44.0.3\"` read the index; `python -m playwright install firefox` has only a Content-Length for a check; "
                "`playwright install-deps firefox` is an apt mirror; a curl or an urlopen with no sha256 is an unchecked download; the served and hash-checked install is green",
                sum("reads the index" in p for p in ci03_problems({"x.yml": old_gate}, scope_y)) == 5
                and any("playwright==$(cat scripts/playwright_pin.txt)" in p for p in ci03_problems({"x.yml": old_gate}, scope_y))
                and any("it installs packages but does not need a py-deps.yml call" in p for p in ci03_problems({"x.yml": old_gate}, scope_y))
                and any("downloads a browser that only its Content-Length checks" in p for p in ci03_problems({"x.yml": old_browser}, scope_y))
                and any("installs from an apt mirror" in p for p in ci03_problems({"x.yml": old_deps}, scope_y))
                and any("downloads from a third party and checks no sha256" in p for p in ci03_problems({"x.yml": old_curl}, scope_y))
                and any("downloads from a third party and checks no sha256" in p for p in ci03_problems({"x.yml": old_urlopen}, scope_y))
                and ci03_problems({"x.yml": new_browser}, scope_y) == []
                and set(real["gate.yml"]["jobs"]) >= {"py-deps-gate", "playwright-firefox", "gate", "wrapper-e2e"}
                and set(real["verify-assets.yml"]["jobs"]) >= {"py-deps-assets", "linux-deps-assets", "drive"}))
    out.append(("ci-03: the jobs that install Python packages in gate.yml (gate, wrapper-e2e) and verify-assets.yml (drive) need a py-deps.yml call, and no job of those two files "
                "runs `pip install` without --no-index or `playwright install-deps`",
                all(any(str(real[f]["jobs"][d].get("uses", "")) == "./.github/workflows/py-deps.yml"
                        for d in ([real[f]["jobs"][j]["needs"]] if isinstance(real[f]["jobs"][j]["needs"], str) else real[f]["jobs"][j]["needs"]))
                    for f, j in (("gate.yml", "gate"), ("gate.yml", "wrapper-e2e"), ("verify-assets.yml", "drive")))
                and not any(re.search(r"\bpip3?\s+install\b(?!.*--no-index)|install-deps\b", l) and not l.lstrip().startswith("#")
                            for f in ("gate.yml", "verify-assets.yml") for job in real[f]["jobs"].values() for st in job.get("steps") or []
                            for l in str(st.get("run", "")).splitlines())))

    # --- no `continue-on-error` on a test or a judge (ci-04): the rule, over every workflow of ours --------------------------------------------------
    import yaml

    bad_coe, total_coe, parsed_coe = [], 0, 0
    for path in sorted(WORKFLOWS.glob("*.yml")):
        if path.name in UPSTREAM_WORKFLOWS:
            continue
        body = path.read_text(encoding="utf-8")
        bad_coe += continue_on_error_violations(path.name, body)
        total_coe += count_continue_on_error(body)
        for job in (yaml.safe_load(body).get("jobs") or {}).values():
            parsed_coe += sum(1 for item in [job] + list(job.get("steps") or []) if "continue-on-error" in item)
    out.append(("no workflow has a continue-on-error on a step that runs tests or a judge, and each has `# continue-on-error: <reason>` right above it%s"
                % ("" if not bad_coe else ": " + "; ".join(bad_coe)), not bad_coe and total_coe > 0))
    old_text = ("jobs:\n  tree:\n    steps:\n"
                "      - name: Our python tests of the tree, as junit\n        continue-on-error: true\n        run: python3 -m pytest scripts -q\n"
                "      - name: Both legs' junit\n        continue-on-error: true\n        run: python3 scripts/ci/cargo_junit.py a.log --out o\n"
                "      - name: The verdict\n        # continue-on-error: it is only a verdict\n        continue-on-error: true\n        run: python3 scripts/ci/ci_verdict.py\n")
    old = continue_on_error_violations("old.yml", old_text)
    out.append(("the rule is red on the old files: a pytest step, a junit converter and a verdict with continue-on-error are named, the first two with the missing reason too",
                len(old) == 5 and "old.yml / tree / Our python tests of the tree, as junit: continue-on-error on a step that runs a test or a judge" in old
                and "old.yml / tree / Our python tests of the tree, as junit: no `# continue-on-error: <reason>` on the line right above" in old
                and "old.yml / tree / Both legs' junit: continue-on-error on a step that runs a test or a judge" in old
                and "old.yml / tree / The verdict: continue-on-error on a step that runs a test or a judge" in old))
    fine = ("jobs:\n  junit:\n    steps:\n      - name: Both legs' junit\n        # continue-on-error: an optional download, not a test\n        continue-on-error: true\n"
            "        uses: actions/download-artifact@v4\n        with:\n          pattern: junitpart-cargo-*\n"
            "      - name: Compile\n        # continue-on-error: a compile step, not a test\n        continue-on-error: ${{ needs.plan.outputs.x != 'objects' }}\n"
            "        run: |\n          # the gtests' links, said in a comment\n          python3 scripts/ci objects\n")
    out.append(("the rule is green on a download and a compile step with their reason above (an expression too); a gtest named only in a comment is not a test",
                continue_on_error_violations("new.yml", fine) == [] and count_continue_on_error(fine) == 2))
    out.append(("the rule reads every continue-on-error key: as many in the text as the YAML parser finds (pr-handler.yml aside: Mozilla's, on no branch of ours)",
                total_coe == parsed_coe))
    # gate.yml: a python.exe that crashes on a Windows leg leaves a full dump in an artifact (the crash of a pytest worker is native: a Python stack alone does not say where)
    import copy

    gate_doc = load("gate.yml")
    wer_good = crash_dump_problems(gate_doc)

    def without(doc, keep):
        d = copy.deepcopy(doc)
        for job in d["jobs"].values():
            job["steps"] = [st for st in job.get("steps") or [] if keep(st)]
        return d

    def edited(doc, job_id, fn):
        d = copy.deepcopy(doc)
        for st in d["jobs"][job_id]["steps"]:
            fn(st)
        return d

    def move_last(doc, job_id):
        d = copy.deepcopy(doc)
        steps = d["jobs"][job_id]["steps"]
        k = next(n for n, st in enumerate(steps) if "LocalDumps" in str(st.get("run", "")))
        steps.append(steps.pop(k))
        return d

    old_gate = without(gate_doc, lambda st: "LocalDumps" not in str(st.get("run", "")) and not str((st.get("with") or {}).get("name", "")).startswith("crash-dumps-"))
    out.append(("gate.yml: the Windows legs of gate and wrapper-e2e set Windows Error Reporting LocalDumps for python.exe (DumpType 2, DumpCount, DumpFolder in the runner's temp) in a pwsh step "
                "on Windows only, before the first pytest step, and upload the folder with always() as crash-dumps-*, retention 14, nothing if none; red on the old gate.yml, on a DumpType 1, on a step "
                "that comes after the tests, on an upload without always() and on a step that is not limited to Windows%s" % ("" if not wer_good else ": " + "; ".join(wer_good)),
                wer_good == []
                and len(crash_dump_problems(old_gate)) == 2
                and any("DumpType" in p for p in crash_dump_problems(edited(gate_doc, "wrapper-e2e", lambda st: st.update(run=str(st.get("run", "")).replace("-Name DumpType -PropertyType DWord -Value 2 ", "-Name DumpType -PropertyType DWord -Value 1 ")))))
                and any("comes after the first step that runs a test" in p for p in crash_dump_problems(move_last(gate_doc, "wrapper-e2e")))
                and any("comes after the first step that runs a test" in p for p in crash_dump_problems(move_last(gate_doc, "gate")))
                and any("not on `if: always()`" in p for p in crash_dump_problems(edited(gate_doc, "gate", lambda st: st.pop("if", None) if str((st.get("with") or {}).get("name", "")).startswith("crash-dumps-") else None)))
                and any("is not on `if: runner.os == 'Windows'`" in p for p in crash_dump_problems(edited(gate_doc, "gate", lambda st: st.pop("if", None) if "LocalDumps" in str(st.get("run", "")) else None)))))
    return out


def _reuse_cases(doc) -> list:
    """A push to main whose tree a green run has already built does not turn a node on: the gate runs again on those bytes."""
    out = []
    jobs = doc["jobs"]
    plan_names = [s.get("name") for s in jobs["plan"]["steps"]]
    step = next(s for s in jobs["plan"]["steps"] if s.get("id") == "reuse")
    out.append(("reuse: the plan looks for a green run right after it has decided the kind, and hands the id on",
                plan_names.index(step["name"]) == plan_names.index("Plan") + 1 and jobs["plan"]["outputs"]["reuse_run_id"] == "${{ steps.reuse.outputs.reuse_run_id }}"
                and jobs["plan"]["permissions"] == {"actions": "read", "contents": "read"}))
    out.append(("reuse: it is told the event, the ref, the kind and the gtests the plan decided, and the tree object and the commit it materialized",
                step["env"]["KIND"] == "${{ steps.plan.outputs.kind }}" and step["env"]["GTESTS"] == "${{ steps.plan.outputs.gtests }}"
                and step["env"]["EVENT"] == "${{ github.event_name }}" and step["env"]["REF"] == "${{ github.ref }}"
                and "HEAD^{tree}" in step["run"] and "rev-parse HEAD" in step["run"] and '"$GITHUB_OUTPUT"' in step["run"]))
    out.append(("reuse: no node when a run is reused, and nothing else about the node's condition changed",
                jobs["node"]["if"] == "needs.plan.outputs.attempt == github.run_attempt && needs.plan.outputs.reuse_run_id == ''"))
    reuse_gate = jobs["gate-reuse"]
    out.append(("reuse: the gate runs again on the reused run's archives with the refs of today, and only when there is one",
                reuse_gate["if"] == "needs.plan.outputs.reuse_run_id != ''" and reuse_gate["uses"] == "./.github/workflows/gate.yml"
                and reuse_gate["with"]["build_run_id"] == "${{ needs.plan.outputs.reuse_run_id }}"
                and reuse_gate["with"]["wrapper_ref"] == "${{ needs.plan.outputs.wrapper_ref }}" and reuse_gate["with"]["core_ref"] == "${{ needs.plan.outputs.core_ref }}"
                and reuse_gate["with"]["seal_tag"] == "${{ needs.plan.outputs.seal_tag }}" and reuse_gate["needs"] == "plan"))
    out.append(("reuse: the ordinary gate still waits for the build (a run that built is judged on what it built)",
                jobs["gate"]["needs"] == ["plan", "build"] and jobs["gate"]["with"]["build_run_id"] == "${{ github.run_id }}"))
    out.append(("reuse: the report of the legs' events does not run for a run that built nothing", jobs["report"]["if"] == "always() && needs.build.result != 'skipped'"))
    record = next(x for x in jobs["build"]["steps"] if x.get("name") == "Record source commit (for auto release notes)")
    upload = next(x for x in jobs["build"]["steps"] if x.get("name") == "Upload source-commit artifact")
    out.append(("reuse: the build writes the TREE beside the commit, in the artifact a later run reads",
                "HEAD^{tree}" in record["run"] and "source-tree.txt" in record["run"] and "source-tree.txt" in upload["with"]["path"]
                and "source-commit.txt" in upload["with"]["path"] and "series-commit.txt" in upload["with"]["path"]))

    # --- scripts/ci/reuse_run.py ------------------------------------------------------------------------------------------------------------------
    now = dt.datetime(2026, 11, 12, 15, 0, tzinfo=dt.timezone.utc)
    TREE, COMMIT = "t" * 40, "c" * 40
    FILTER = "StealthA.*:StealthB.*"
    full = ["asset-linux-x86_64", "asset-win-x86_64", "source-commit", "gtest-reports-linux-x86_64", "gtest-reports-win-x86_64"]

    def iso(days):
        return (now - dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")

    def world(runs, arts=None, sources=None):
        """runs: [(id, days old)]; arts: {id: [names]} (a name with a leading ! is expired); sources: {id: {'commit': ..., 'tree': ...}}."""
        arts, sources = arts or {}, sources or {}
        run_list = [{"id": i, "created_at": iso(d), "event": "push", "head_branch": "main"} for i, d in runs]

        def artifacts_of(run_id):
            return [{"id": run_id * 10, "name": n.lstrip("!"), "expired": n.startswith("!")} for n in arts.get(run_id, full)]

        return run_list, artifacts_of, lambda artifact_id: sources.get(artifact_id // 10, {"commit": COMMIT, "tree": TREE, "gtest_filter": FILTER})

    def pick(runs, arts=None, sources=None, gtests=True, current=99, wanted=FILTER, counted=None):
        """`counted`: {artifact id // 10: tests counted in its reports}; by default every report holds 30 tests."""
        run_list, artifacts_of, source_of = world(runs, arts, sources)
        counted = counted or {}
        return reuse_run.choose(run_list, artifacts_of, source_of, TREE, COMMIT, now, current, gtests, gtest_filter=wanted,
                                tests_of=lambda artifact_id: counted.get(artifact_id // 10, 30))[0]

    other = {"commit": "x" * 40, "tree": "y" * 40, "gtest_filter": FILTER}
    out.append(("reuse_run: the newest green run with the same tree, its archives alive and its gtests done, is the one", pick([(5, 1), (4, 2)]) == "5"))
    out.append(("reuse_run: it is never the run that asks", pick([(99, 0), (4, 2)]) == "4"))
    out.append(("reuse_run: another tree is not reused", pick([(5, 1)], sources={5: other}) == ""))
    out.append(("reuse_run: the tree is the identity, not the commit: a run with another commit and the same tree is reused",
                pick([(5, 1)], sources={5: {"commit": "x" * 40, "tree": TREE, "gtest_filter": FILTER}}) == "5"))
    out.append(("reuse_run: a run from before the tree was written is compared by commit",
                pick([(5, 1)], sources={5: {"commit": COMMIT, "tree": "", "gtest_filter": FILTER}}) == "5"
                and pick([(5, 1)], sources={5: {"commit": "x" * 40, "tree": "", "gtest_filter": FILTER}}) == ""))
    out.append(("reuse_run: an expired archive is not reused, the next run is looked at",
                pick([(5, 1), (4, 2)], arts={5: ["!asset-linux-x86_64"] + full[1:]}) == "4"
                and pick([(5, 1)], arts={5: ["asset-linux-x86_64", "!asset-win-x86_64", "source-commit", "gtest-reports-linux-x86_64"]}) == ""))
    out.append(("reuse_run: a run that lacks an archive or the source record is not reused",
                pick([(5, 1)], arts={5: ["asset-linux-x86_64", "source-commit", "gtest-reports-linux-x86_64"]}) == ""
                and pick([(5, 1)], arts={5: ["asset-linux-x86_64", "asset-win-x86_64", "gtest-reports-linux-x86_64"]}) == ""))
    out.append(("reuse_run: when this run would run the gtests, the reused one must have run them, on BOTH legs",
                pick([(5, 1)], arts={5: full[:3]}) == "" and pick([(5, 1)], arts={5: full[:3]}, gtests=False) == "5"
                and pick([(5, 1)], arts={5: full[:4]}) == "" and pick([(5, 1)], arts={5: full[:3] + [full[4]]}) == ""))
    # --- which gtests the reused run ran (the proof candidate with a narrow filter that was fast-forwarded to main) ---------------------------------
    narrow = {"commit": COMMIT, "tree": TREE, "gtest_filter": "StealthA.*"}
    out.append(("reuse_run: a run whose gtests were a NARROWER filter than this run's is not reused, the next run is looked at",
                pick([(5, 1)], sources={5: narrow}) == "" and pick([(5, 1), (4, 2)], sources={5: narrow}) == "4"))
    out.append(("reuse_run: the same filter, a longer one that contains it, and `*` are reused; the order of the patterns does not matter",
                pick([(5, 1)], sources={5: {"commit": COMMIT, "tree": TREE, "gtest_filter": "StealthB.*:StealthA.*"}}) == "5"
                and pick([(5, 1)], sources={5: {"commit": COMMIT, "tree": TREE, "gtest_filter": FILTER + ":StealthC.*"}}) == "5"
                and pick([(5, 1)], sources={5: {"commit": COMMIT, "tree": TREE, "gtest_filter": "*"}}) == "5"))
    out.append(("reuse_run: a run with no record of its filter (a `source-commit` from before the file) is not reused",
                pick([(5, 1)], sources={5: {"commit": COMMIT, "tree": TREE, "gtest_filter": None}}) == ""
                and pick([(5, 1)], sources={5: {"commit": COMMIT, "tree": TREE}}) == ""
                and pick([(5, 1)], sources={5: {"commit": COMMIT, "tree": TREE, "gtest_filter": None}}, gtests=False) == ""))
    out.append(("reuse_run: a filter with an exclusion is covered only by the identical text",
                pick([(5, 1)], sources={5: {"commit": COMMIT, "tree": TREE, "gtest_filter": "*-StealthA.*"}}) == ""
                and pick([(5, 1)], sources={5: {"commit": COMMIT, "tree": TREE, "gtest_filter": "*-StealthA.*"}}, wanted="*-StealthA.*") == "5"))
    out.append(("reuse_run: reports that counted no test are not gtests that ran",
                pick([(5, 1)], counted={5: 0}) == "" and pick([(5, 1), (4, 2)], counted={5: 0}) == "4"))
    out.append(("reuse_run: covers(): a pattern of the wanted filter missing from the previous one is not covered, an empty side never is",
                reuse_run.covers("A.*:B.*", "A.*") and not reuse_run.covers("A.*", "A.*:B.*") and not reuse_run.covers("", "A.*")
                and not reuse_run.covers("A.*", "") and reuse_run.covers("*", "A.*:B.*")))
    out.append(("reuse_run: older than six days is not reused, whatever its artifacts (they are kept seven, the gate has to download them)",
                pick([(5, 6.5)]) == "" and pick([(5, 5.5)]) == "5"))
    asked = []
    old_run = [{"id": 1, "created_at": iso(7), "event": "push", "head_branch": "main"}]
    out.append(("reuse_run: it looks at nothing it does not need: past the age it stops and reads nothing",
                reuse_run.choose(old_run, lambda r: asked.append(r) or [], lambda a: asked.append(a) or {}, TREE, COMMIT, now, 99, True)[0] == "" and asked == []))
    out.append(("reuse_run: only the push to main of a candidate is judged: the weekly run, a dispatch, a release, a tag, another branch are not",
                reuse_run.applies("push", "refs/heads/main", "candidate") and not any(
                    reuse_run.applies(e, r, k) for e, r, k in (("schedule", "refs/heads/main", "candidate"), ("workflow_dispatch", "refs/heads/main", "candidate"),
                                                               ("push", "refs/heads/main", "release"), ("push", "refs/tags/firefox-63", "candidate"),
                                                               ("push", "refs/heads/latitude/x", "candidate")))))

    class Fake:
        def __init__(self, runs, fail=False):
            self.runs, self.fail, self.calls = runs, fail, 0

        def green_runs(self):
            self.calls += 1
            if self.fail:
                raise OSError("api down")
            return self.runs

        def artifacts(self, run_id):
            return [{"id": run_id * 10, "name": n, "expired": False} for n in full]

        def source(self, artifact_id):
            return {"commit": COMMIT, "tree": TREE, "gtest_filter": FILTER}

        def tests_counted(self, artifact_id):
            return 30

    import contextlib
    import io

    def run_main(event, fake, ref="refs/heads/main", kind="candidate"):
        buffer, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(err):
            code = reuse_run.main(["--event", event, "--ref", ref, "--kind", kind, "--gtests", "true", "--gtest-filter", FILTER, "--repository", "o/r",
                                   "--run-id", "99", "--tree", TREE, "--commit", COMMIT], github=fake, now=now)
        return code, buffer.getvalue().strip()

    runs = [{"id": 5, "created_at": iso(1), "event": "push", "head_branch": "main"}]
    out.append(("reuse_run: main() prints the id for the output file", run_main("push", Fake(runs)) == (0, "reuse_run_id=5")))
    schedule = Fake(runs)
    out.append(("reuse_run: the weekly run prints an empty id and does not even ask GitHub", run_main("schedule", schedule) == (0, "reuse_run_id=") and schedule.calls == 0))
    out.append(("reuse_run: a GitHub that does not answer is a run that builds, never a failure of the plan", run_main("push", Fake(runs, fail=True)) == (0, "reuse_run_id=")))

    class Slow(Fake):
        def green_runs(self):
            import subprocess
            raise subprocess.TimeoutExpired("gh api", 120)

    out.append(("reuse_run: a `gh api` that times out is a run that builds too, not a red plan", run_main("push", Slow(runs)) == (0, "reuse_run_id=")))
    out.append(("reuse_run: main() hands the filter of the plan to the choice: a run of a narrower filter is not reused through main() either",
                run_main("push", type("Narrow", (Fake,), {"source": lambda self, i: {"commit": COMMIT, "tree": TREE, "gtest_filter": "StealthA.*"}})(runs)) == (0, "reuse_run_id=")))
    # --- the workflow records and passes the filter ------------------------------------------------------------------------------------------------
    out.append(("reuse: the plan passes the plan's gtest filter to reuse_run.py", step["env"].get("GTEST_FILTER") == "${{ steps.plan.outputs.gtest_filter }}"
                and '--gtest-filter "$GTEST_FILTER"' in step["run"]))
    out.append(("reuse: the build records the filter it ran (empty without gtests) in the artifact a later run reads",
                record.get("env", {}).get("GTEST_FILTER") == "${{ needs.plan.outputs.gtest_filter }}" and record["env"].get("GTESTS") == "${{ needs.plan.outputs.gtests }}"
                and "gtest-filter.txt" in record["run"] and "gtest-filter.txt" in upload["with"]["path"]))
    return out


#: What orders or touches a Latitude server, read from a step's commands (comment lines left out): the API's address, its command line, a server order, or a
#: call of latitude_node's own functions from a snippet. Only `latitude_node.py up` may order a node, and it is the one that waits for the team's capacity.
LATITUDE_CALL = re.compile(r"api\.latitude\.sh|latitude\.sh/|\blatitude\s+servers\b|\bservers\s+create\b|\bLATITUDE_API_KEY\b.*\bcurl\b|\bcurl\b.*\bLATITUDE_API_KEY\b|"
                           r"\bimport\s+latitude_node\b|\bfrom\s+latitude_node\b|\blatitude_node\.(?:Latitude|bring_up|create)\b")
NODE_COMMAND = re.compile(r"latitude_node\.py\s+([a-z-]+)")
#: The subcommands of latitude_node.py a workflow may run; of them `up` alone orders a server.
NODE_COMMANDS = ("up", "prepare", "watch", "off", "sweep", "status")
#: Files outside latitude_node.py that may name the API's address: its cases.
LATITUDE_API_FILES = ("latitude_node.py", "test_latitude_node.py", "test_release_checks.py")


def node_provisioning_problems(docs: dict, scripts: dict) -> list:
    """Every place that orders a Latitude node outside `latitude_node.py up`, as "<file> / <job> / <step>: <why>". `docs` are the parsed workflows by file name,
    `scripts` the text of the scripts the workflows may call, by path. The rule (a run cannot fail for a third party's reason): the node job gets its server
    only through `up`, which waits for the team's capacity instead of asking every location in turn; a step that orders one another way (the API from curl, a
    CLI, a snippet that imports the module) would fail the run the day another run holds the account's servers."""
    found = []
    for name, doc in docs.items():
        for job_name, job in (doc.get("jobs") or {}).items():
            for step in job.get("steps") or []:
                where = "%s / %s / %s" % (name, job_name, step.get("name", step.get("id", "?")))
                run = re.sub(r"\\\n\s*", " ", str(step.get("run", "")))
                text = "\n".join(l for l in run.splitlines() if not l.strip().startswith("#"))
                for command in NODE_COMMAND.findall(text):
                    if command not in NODE_COMMANDS:
                        found.append("%s: `latitude_node.py %s` is no command of it" % (where, command))
                if LATITUDE_CALL.search(text):
                    found.append("%s: it reaches Latitude other than through `latitude_node.py`: a server ordered there does not wait for the team's capacity" % where)
                if "latitude" in str(step.get("uses", "")).lower():
                    found.append("%s: it uses an action of Latitude's: a server ordered there does not wait for the team's capacity" % where)
    for path, text in scripts.items():
        if Path(path).name not in LATITUDE_API_FILES and re.search(r"api\.latitude\.sh|latitude_node\.(?:Latitude|bring_up|create)\b", text):
            found.append("%s: it reaches Latitude other than through `latitude_node.py`" % path)
    return found


def node_orders_only_through_up(docs: dict) -> list:
    """The jobs of `docs` whose steps run `latitude_node.py up`, as "<file> / <job>": the ones that provision."""
    return ["%s / %s" % (name, job_name) for name, doc in docs.items() for job_name, job in (doc.get("jobs") or {}).items()
            if any(re.search(r"latitude_node\.py\s+up\b", str(step.get("run", ""))) for step in job.get("steps") or [])]


def _provisioning_cases() -> list:
    import yaml

    out = []
    docs = {p.name: yaml.safe_load(p.read_text(encoding="utf-8")) for p in sorted(WORKFLOWS.glob("*.yml"))}
    scripts = {str(p.relative_to(HERE.parent.parent)): p.read_text(encoding="utf-8", errors="replace")
               for pattern in ("*.py", "*.sh") for folder in (HERE, HERE.parent) for p in sorted(folder.glob(pattern))}
    out.append(("provisioning: no workflow step and no script orders a Latitude node except through `latitude_node.py up` (the capacity wait); every command of it a workflow runs exists",
                node_provisioning_problems(docs, scripts) == []))
    out.append(("provisioning: the node job of release.yml is the one that provisions, through `up`, and the scan has read the workflows (not an empty rule)",
                node_orders_only_through_up(docs) == ["release.yml / node"] and len(docs) >= 10 and len(scripts) >= 20))
    bypass = {"bad.yml": {"jobs": {"node": {"steps": [
        {"name": "order", "run": "curl -s -X POST https://api.latitude.sh/servers -H \"Authorization: Bearer $LATITUDE_API_KEY\" -d @server.json"},
        {"name": "snippet", "run": "python3 -c \"import latitude_node; latitude_node.Latitude('p', 'k').create('n', 'k')\""},
        {"name": "cli", "run": "latitude servers create --plan f4-metal-small"},
        {"name": "action", "uses": "someone/latitude-server@v1"},
        {"name": "typo", "run": "python3 scripts/ci/latitude_node.py create --run 1 --attempt 1"}]}}}}
    problems = node_provisioning_problems(bypass, {})
    out.append(("provisioning: red on a step that orders a node by the API's address, a snippet, a CLI, an action or a command `latitude_node.py` does not have: one problem each",
                len(problems) == 5 and all(p.startswith("bad.yml / node / ") for p in problems)))
    fine = {"ok.yml": {"jobs": {"node": {"steps": [
        {"name": "up", "run": "python3 .series/scripts/ci/latitude_node.py up \\\n  --run \"$GITHUB_RUN_ID\" --attempt 1 --work w"},
        {"name": "a comment about the API", "run": "# curl https://api.latitude.sh/servers is not run\npython3 scripts/ci/latitude_node.py off --run 1 --attempt 1"}]}}}}
    out.append(("provisioning: green on `up` (a line continued with a backslash too), `off` and a comment that names the API", node_provisioning_problems(fine, {}) == []))
    out.append(("provisioning: a script that reaches the API outside latitude_node.py is found",
                node_provisioning_problems({}, {"scripts/ci/order.py": "import urllib.request\nurllib.request.urlopen('https://api.latitude.sh/servers')"})
                == ["scripts/ci/order.py: it reaches Latitude other than through `latitude_node.py`"]))
    return out


def cases() -> list:
    """The cases; a workflow that does not have what they read is a FAIL that names it, not a crash of the caller."""
    try:
        return _cases() + _provisioning_cases()
    except (KeyError, IndexError, TypeError, AttributeError, StopIteration) as exc:
        return [("release checks: stopped on %s: %s (the workflow lacks what these cases read)" % (type(exc).__name__, exc), False)]


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
