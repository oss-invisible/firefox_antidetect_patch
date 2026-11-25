"""Every commit, tag and tagger of this repository carries a GitHub noreply address, and
the series' CI is red when one does not.

checks.yml (called by series.yml on pull requests and main, and by release.yml on every candidate)
judges them inline (a workflow a pull request starts may not call another repository's workflow);
noreply-identity.yml judges the branches and tags series.yml does not see. Both read the judge from
main of the core.

    python -m pytest tools/tests
"""
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import engine  # noqa: E402

WORKFLOWS = ROOT / ".github" / "workflows"


def _load(name):
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def _steps_text(job):
    return yaml.dump(job["steps"])


def test_a_workflow_that_exists_only_at_the_root_is_declared_so():
    """engine.py check looks for every other workflow in platform/ci/src."""
    in_series = {p.name for p in engine.WORKFLOWS_SERIES.glob("*.yml")}
    only_here = {p.name for p in WORKFLOWS.glob("*.yml")} - in_series
    assert only_here <= engine.ROOT_ONLY_WORKFLOWS, only_here - engine.ROOT_ONLY_WORKFLOWS
    assert {"series.yml", "noreply-identity.yml"} <= engine.ROOT_ONLY_WORKFLOWS


def test_series_yml_gate_waits_for_the_checks_that_hold_the_identity_check_and_always_runs():
    doc = _load("series.yml")
    gate = doc["jobs"]["gate"]
    assert gate["if"] == "always()"
    assert set(gate["needs"]) == {"checks"}
    assert doc["jobs"]["checks"]["uses"] == "./.github/workflows/checks.yml"
    assert "noreply-identity" in _load("checks.yml")["jobs"]
    script = _steps_text(gate)
    for job in gate["needs"]:
        assert 'needs.%s.result }}" = "success"' % job in script, job


def test_the_identity_job_of_checks_yml_is_inline_and_reads_the_judge_from_main_of_the_core():
    job = _load("checks.yml")["jobs"]["noreply-identity"]
    assert "uses" not in job
    assert job["runs-on"] == "ubuntu-latest" and job["timeout-minutes"] == 10
    checkouts = [s["with"] for s in job["steps"] if s.get("uses", "").startswith("actions/checkout@")]
    assert checkouts[0]["fetch-depth"] == 0
    # Commits and tags only: the full clone of this repository did not fit the job.
    assert checkouts[0]["filter"] == "tree:0"
    assert checkouts[0]["sparse-checkout"].split() == ["/.github/"]
    assert checkouts[0]["sparse-checkout-cone-mode"] is False
    judge = [c for c in checkouts if c.get("repository") == "oss-invisible/core"]
    assert len(judge) == 1 and judge[0]["ref"] == "main"
    assert judge[0]["path"] == ".noreply-judge" and judge[0]["persist-credentials"] is False
    # No bootstrap: a judge missing from main of the core is an error, not a pass.
    assert "BOOTSTRAP" not in _steps_text(job)
    assert "exit 1" in _steps_text(job)


def test_branches_and_tags_series_yml_does_not_see_are_judged_by_the_core_workflow():
    doc = _load("noreply-identity.yml")
    on = doc.get(True, doc.get("on"))
    assert set(on) == {"push"}, "a pull_request trigger would break the rule against `uses:`"
    assert on["push"]["branches-ignore"] == ["main"] and on["push"]["tags"] == ["**"]
    # the core's reusable workflow, pinned to a core commit (actions pinned by commit SHA: tools/tests/test_every_action_is_pinned_by_commit_sha.py)
    assert re.fullmatch(r"oss-invisible/core/\.github/workflows/noreply-identity\.yml@[0-9a-f]{40}", doc["jobs"]["noreply-identity"]["uses"])
