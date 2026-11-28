#!/usr/bin/env python3
"""What a run of release.yml or republish.yml is, and what comes out of it.

The ONE place that knows. Every job reads the plan's outputs instead of
deciding again from the event and the inputs.

  candidate  a manual run that builds and gates and publishes NOTHING: no
             seal, no draft, no tag. It has no release tag, and one given to
             it is refused rather than ignored. Its archives are the run's
             `asset-*` artifacts; if they are the ones to ship, republish.yml
             publishes them from this run's id, without a rebuild. The gate
             seals the binary with a LOCAL seal named `firefox-N-candidate`, N
             being the engine this candidate would become: the last published
             `firefox-N` plus one (`--last-release`, read from the tags by the
             workflow). The wrapper's tests ask the engine's number (a property of
             the UDP line is for firefox-63 or later), and a tag with no number
             (`local`) does not say which engine it is: they fail on it.
  release    a manual run with kind=release, or a republish: the seal and the
             DRAFT under a `firefox-N` tag, the tag checked here before any build
             starts.

A candidate can stop early (`stop_after=objects`): the compile-only run. It builds the objects of every
directory the series touches (scripts/ci/objects_first.py) and stops there: no link, no package, no gtest
run, no gate. Only a candidate by hand, on a `latitude/*` branch (the branches the proofs run on); the
plan refuses it anywhere else, and it turns the gtests off, as a run that does not link has none to run.

The compile cache (`compile_cache`) is decided here too, for the same reason.
Every run compiles through sccache with GitHub's Actions cache behind it, so a
run after a fix recompiles only what the fix touched instead of the whole tree
(a cold leg is 1-2 hours; a port to a new Firefox needs many runs). Releases too,
since 2026-11-03 (Federico's decision): the cache's keys are the hash of the
preprocessed source, the arguments and the compiler. `--compile-cache off` asks
for a cold build.

Who compiles is no choice: the two legs, Linux and Windows x86_64, on a build node,
every run, candidates and releases alike (scripts/ci/latitude_node.py); gates and tests
always on GitHub. No linux-arm64 from firefox-56 on (Federico, 2026-11-04), and which
legs a run builds is no choice either: always both. So the plan has no say.

Where a run starts from is checked here too (`--ref-type`, release.yml's own). An
actions/cache entry belongs to its ref, and a run reads only its own ref's and the
default branch's: what a run from a tag saves, nothing after it can read. So no build
runs from a tag, and a release is dispatched from main, where every later run finds
its cache.

Why a plan and not a convention. Until 2026-10-17 a manual run decided only at
its END what it was: a candidate dispatched with a release_tag that was not
`firefox-N` built three legs and passed three gates in about two hours, then
died in publish-draft-release on make_seal.py's tag check, so every candidate
run finished "failure" by construction (twice in two days, for B322). A red
that is always there stops being read. The tag rule itself stays make_seal.py's
(`check_release_tag`): this file asks it, it does not repeat it.

    python3 scripts/release_plan.py --event <event> --kind <kind> \\
        --release-tag <tag> --ref-name <ref> [--compile-cache gha|off] \\
        [--ref-type branch|tag]

prints the outputs as `key=value` lines for $GITHUB_OUTPUT, or exits 1 naming
what is wrong. Its known-bad inputs: scripts/test_release_plan.py.

The core a run uses (ci-05). The engine, the core and the wrapper of a run are one set that pins itself: the wrapper at wrapper_ref pins
`invisible_core==X.Y.Z` in its pyproject.toml, and the core must be that one. Every event and kind: an empty core_ref is `v<X.Y.Z>`, the release
tag of the core the wrapper pins (the tag must exist); a given core_ref is read for the version it BUILDS (the core's own formula, below) and kept
only when that is X.Y.Z, else the plan stops naming both versions. No path falls back to `main`: a push to main ran the wrapper's main (pinned
invisible_core==68.80.0) against the core's main (69.82.0) and every wrapper e2e leg died at import ("invisible-core version mismatch", run
45348928499). A pin that cannot be read, is not exactly one `invisible_core==X.Y.Z`, whose tag is missing, or a core whose version cannot be read
or does not follow the formula is a refused plan, never a guess. The core's version at a ref is `<N>.<CORE_REVISION>.0`: N from the `tag`
(`firefox-N`) of src/invisible_core/seal.json, CORE_REVISION the one `CORE_REVISION = <int>` line of src/invisible_core/_version.py, which must
still carry the derivation from the seal (`core_version_at`). The reading is the caller's (injected into plan()): the decision stays pure and is
tested offline. The refs are resolved once the inputs themselves are valid, still before any build. `python3 scripts/release_plan.py
--resolve-core-ref --wrapper-ref <ref> [--core-ref <ref>]` prints `core_ref=<resolved>` for another workflow, or `PLAN REFUSED: ...` and exit 1.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))

from make_seal import SealBuildError, check_release_tag  # noqa: E402

KINDS = ("candidate", "release")
# A candidate's seal tag: the number of the engine it would become, then "-candidate". It is not a release tag
# (the core reads it as a local seal), and the wrapper's tests read the number from it.
CANDIDATE_SEAL_TAG = "firefox-{n}-candidate"
# What the compile_cache output can say. "gha" is sccache on the GitHub Actions
# cache; "off" is a cold build. Anything else is refused.
COMPILE_CACHES = ("gha", "off")
# The only branch a release's cache is readable from afterwards.
RELEASE_BRANCH = "main"
# The events that run a candidate by themselves, from main, with the gtests: a push
# to main and the weekly timer. They keep main's compile cache warm (GitHub keeps a
# cache per branch and drops it after seven days unused; a cold release was 75 min
# against 43 warm, measured 2026-11-07).
AUTOMATIC_EVENTS = ("push", "schedule")
# What an automatic candidate runs, and what a run by hand runs when its input is
# empty: the same list as release.yml's gtest_filter default.
DEFAULT_GTEST_FILTER = ("StealthGfxFeatureStatus.*:StealthWebGPUAdapter.*:"
                        "StealthWebGPUDeclaration.*:StealthWebGPUBundledVulkan.*:"
                        "StealthWebGPUInstanceEnv.*:StealthFullscreen.*:"
                        "StealthScaleDeclaration.*:StealthWindowGeometry.*:"
                        "StealthGLMultisample.*:StealthWebGLParams.*:StealthFrameCrash.*:"
                        "StealthJugglerEventId.*:StealthSessionUdpProxy.*:StealthDeclaredNetwork.*:StealthSocksUdpPool.*:TestStealthTRRContext.*:TestStealthSocksCredentials.*:TestStealthSessionResolver.*:StealthIceResolverContext.*:StealthUdpProxyBirth.*:StealthNrSocketBirth.*:"
                        "StealthPcUdpProxyKinds.*:StealthTcpProxyRoad.*:StealthPcProxyConfig.*:"
                        "StealthInputEventBirth.*:StealthKeyBirthScope.*:StealthBirthOrder.*:StealthFcBundleFonts.*:"
                        "StealthAudioNoise.*:StealthBundledCollection.*:"
                        "StealthGlyphCoverage.*:StealthBundleHooks.*:StealthFontListHooks.*:StealthDebugger.*:StealthWindowInputDesktop.*:StealthPrefSanitize.*:TestStealthLinkClickAfter.*:TestStealthLoadInfo.*:TestStealthDocShellDefaults.*:"
                        "StealthCanvasProjection.*:StealthDocumentLanguage.*:StealthFallbackNames.*:StealthFcFontList.*:"
                        "StealthFontList.*:StealthFontMetrics.*:StealthMediaDeclaration.*:StealthOwnBinaries.*:"
                        "StealthQuotaEstimate.*:StealthTextQuality.*:StealthTtcFace.*:StealthWebGPUExternalTexture.*:"
                        "Intl_Locale_StealthSystemLocales.*:Idwr.*:"
                        "StealthBranding.*:StealthCanvasUtils.*:StealthDragGesture.*:StealthHttp3Socks.*:StealthJugglerCoalesce.*:"
                        "StealthJugglerMouseAck.*:StealthMouseEventCopy.*:StealthMouseEventIPC.*:StealthNsProxyInfoKinds.*:StealthSocksUdpLayer.*:StealthStackFrames.*:StealthStartupCache.*:StealthTimezone.*:StealthExclusivePort.*:StealthCallerObject.*:StealthSurfaceFlags.*:StealthMediaEnumeration.*:StealthCanvasPageSnapshot.*:TestStealthLookupLoadInfo.*:StealthScreenToReal.*:StealthChromeOffset.*")
DEFAULT_REF = "main"
# Where the wrapper's pin is read and the core's tags are looked up (the same repositories gate.yml checks out and installs).
WRAPPER_REPOSITORY = "oss-invisible/playwright"
CORE_REPOSITORY = "oss-invisible/core"
# The one quoted requirement string that names the core in the wrapper's pyproject.toml, either spelling.
CORE_REQUIREMENT = re.compile(r"""["']\s*(invisible[-_.]core(?![\w-])[^"']*)["']""", re.IGNORECASE)
CORE_PIN = re.compile(r"""invisible[-_.]core\s*==\s*([0-9]+\.[0-9]+\.[0-9]+)\s*(?:;[^"']*)?""", re.IGNORECASE)
# The core's own version formula, in src/invisible_core/_version.py (the one the release tooling uses): the lines that must be there, and the
# one hand-edited number.
CORE_VERSION_PY = "src/invisible_core/_version.py"
CORE_SEAL_JSON = "src/invisible_core/seal.json"
CORE_VERSION_DERIVATION = "__version__ = f\"{int(_seal['tag'].split('-')[1])}.{CORE_REVISION}.0\""
CORE_VERSION_SEAL_READ = 'pathlib.Path(__file__).with_name("seal.json")'
CORE_REVISION_LINE = re.compile(r"^CORE_REVISION = ([0-9]+)[ \t]*$", re.MULTILINE)
CORE_REVISION_ANY = re.compile(r"^\s*CORE_REVISION\s*[:=]", re.MULTILINE)
SEAL_TAG = re.compile(r"firefox-([0-9]+)")
# What `stop_after` can say: nothing (the whole run), or the objects of the touched directories.
STOP_AFTERS = ("", "objects")
# The only branches a compile-only run starts from: the ones the proofs run on.
STOP_AFTER_BRANCH_PREFIX = "latitude/"


class PlanError(ValueError):
    pass


def core_pin(pyproject: str) -> str:
    """The version X.Y.Z the wrapper's pyproject.toml pins, from its one `invisible_core==X.Y.Z` (or `invisible-core==X.Y.Z`) requirement."""
    found = [m.group(1).strip() for m in CORE_REQUIREMENT.finditer(pyproject)]
    if len(found) != 1:
        raise PlanError(f"the wrapper's pyproject.toml must name the core in exactly one requirement (invisible_core==X.Y.Z), found {len(found)}"
                        + (": " + ", ".join(repr(f) for f in found) if found else ""))
    match = CORE_PIN.fullmatch(found[0])
    if not match:
        raise PlanError(f"the wrapper's requirement on the core is not an exact X.Y.Z pin (invisible_core==X.Y.Z): {found[0]!r}")
    return match.group(1)


def core_version_at(ref: str, read_core_file: Callable[[str, str], str]) -> str:
    """The version `<N>.<CORE_REVISION>.0` the core at `ref` builds, by the core's own formula; PlanError when a file cannot be read or does not match."""
    try:
        version_py = read_core_file(ref, CORE_VERSION_PY)
        seal_text = read_core_file(ref, CORE_SEAL_JSON)
    except PlanError:
        raise
    except Exception as exc:  # a reader's own failure is a refusal, not a guess
        raise PlanError(f"the version of {CORE_REPOSITORY} at {ref!r} cannot be read: {exc}") from None
    where = f"{CORE_REPOSITORY} at {ref!r}"
    if CORE_VERSION_DERIVATION not in version_py or CORE_VERSION_SEAL_READ not in version_py:
        raise PlanError(f"{CORE_VERSION_PY} of {where} does not derive the version from seal.json and CORE_REVISION as expected: no version to compare")
    revisions = CORE_REVISION_LINE.findall(version_py)
    mentions = len(CORE_REVISION_ANY.findall(version_py))
    if len(revisions) != 1 or mentions != 1:
        raise PlanError(f"{CORE_VERSION_PY} of {where} must have exactly one `CORE_REVISION = <int>` line, found {mentions}")
    try:
        tag = json.loads(seal_text)["tag"]
    except (ValueError, KeyError, TypeError):
        raise PlanError(f"{CORE_SEAL_JSON} of {where} is not JSON with a `tag`") from None
    match = SEAL_TAG.fullmatch(tag) if isinstance(tag, str) else None
    if not match:
        raise PlanError(f"the tag in {CORE_SEAL_JSON} of {where} is not firefox-N: {tag!r}")
    return f"{int(match.group(1))}.{int(revisions[0])}.0"


def resolve_core_ref(wrapper_ref: str, core_ref: str, read_pyproject: Callable[[str], str], tag_exists: Callable[[str], bool],
                     read_core_file: Callable[[str, str], str]) -> str:
    """The core a run uses: `v<pin>` when core_ref is empty (the tag must exist in the core), the given core_ref when it builds the version the
    wrapper at wrapper_ref pins; PlanError otherwise, naming both versions. Never `main` by default."""
    pin = core_pin(read_pyproject(wrapper_ref))
    if not core_ref:
        tag = "v" + pin
        if not tag_exists(tag):
            raise PlanError(f"the wrapper at {wrapper_ref!r} pins the core {pin}, and {CORE_REPOSITORY} has no tag {tag}: "
                            f"no core to test it with (the plan does not fall back to {DEFAULT_REF})")
        return tag
    built = core_version_at(core_ref, read_core_file)
    if built != pin:
        raise PlanError(f"the wrapper at {wrapper_ref} pins invisible_core {pin}; core_ref {core_ref} builds {built}: "
                        f"one run is one set, so the wrapper and the core must agree (leave core_ref empty for v{pin})")
    return core_ref


def _github_contents(repository: str, path: str, ref: str) -> str:
    """A file of a repository at `ref` (a branch, a tag or a commit), from the contents API; GH_TOKEN is the runner's."""
    done = subprocess.run(["gh", "api", "-X", "GET", "-H", "Accept: application/vnd.github.raw+json", f"repos/{repository}/contents/{path}",
                           "-f", f"ref={ref}"], capture_output=True, text=True, timeout=120)
    if done.returncode != 0:
        raise PlanError(f"{path} of {repository} at {ref!r} cannot be read: {done.stderr.strip() or done.returncode}")
    return done.stdout


def github_pyproject(ref: str) -> str:
    """pyproject.toml of the wrapper at `ref`."""
    return _github_contents(WRAPPER_REPOSITORY, "pyproject.toml", ref)


def github_core_file(ref: str, path: str) -> str:
    """`path` of the core at `ref`."""
    return _github_contents(CORE_REPOSITORY, path, ref)


def github_tag_exists(tag: str) -> bool:
    """Is `tag` a tag of the (public) core repository? A lookup that fails is a PlanError, not an absent tag."""
    done = subprocess.run(["git", "ls-remote", "--tags", "--refs", f"https://github.com/{CORE_REPOSITORY}", f"refs/tags/{tag}"],
                          capture_output=True, text=True, timeout=120)
    if done.returncode != 0:
        raise PlanError(f"the tags of {CORE_REPOSITORY} cannot be read: {done.stderr.strip() or done.returncode}")
    return any(line.split("\t")[-1:] == [f"refs/tags/{tag}"] for line in done.stdout.splitlines())


def github_resolve(wrapper_ref: str, core_ref: str) -> str:
    """resolve_core_ref with the real readers (the API and the tags)."""
    return resolve_core_ref(wrapper_ref, core_ref, github_pyproject, github_tag_exists, github_core_file)


def plan(event: str, kind: str, release_tag: str, ref_name: str,
         compile_cache: str = "", ref_type: str = "", gtests: str = "",
         gtest_filter: str = "", core_ref: str = "", wrapper_ref: str = "",
         last_release: str = "", stop_after: str = "",
         core_ref_resolver: Callable[[str, str], str] | None = None) -> dict[str, str]:
    """The outputs of a run, or PlanError.

    compile_cache is the run's request: "" takes the default. ref_type is what the
    run started from; republish.yml builds nothing, passes none and is not asked.
    gtests, gtest_filter, core_ref and wrapper_ref are the run's inputs, empty on an
    automatic run: it is a candidate from main with the gtests and the defaults.
    last_release is the number N of the last published `firefox-N` (the workflow reads
    it from the tags): a candidate is the engine after it. stop_after is "" or "objects":
    only a candidate by hand on a `latitude/*` branch may stop after the objects.
    core_ref_resolver(wrapper_ref, core_ref) is the core the run uses (`resolve_core_ref`, see the top of this file): `v<pin>` for an empty core_ref,
    the given one when it builds the pinned version, else PlanError. Every event and kind asks it, once the inputs are valid; without it the plan is
    refused, never planned on `main`."""
    if event in AUTOMATIC_EVENTS:
        if ref_type != "branch" or ref_name != RELEASE_BRANCH:
            raise PlanError(f"a run by itself is a candidate from the branch {RELEASE_BRANCH}, "
                            f"not from {ref_name!r} ({ref_type or 'no ref type'})")
        if kind or release_tag or compile_cache or stop_after:
            raise PlanError("a run by itself takes no inputs: it is a candidate with the cache")
        kind, gtests = "candidate", "true"
    elif event != "workflow_dispatch":
        raise PlanError(f"release runs by hand, from main for a release, or by itself on "
                        f"{' and '.join(AUTOMATIC_EVENTS)} from {RELEASE_BRANCH}, not on {event!r}")
    wrapper_ref = wrapper_ref or DEFAULT_REF
    def core() -> str:
        if core_ref_resolver is None:
            raise PlanError("a run uses the core its wrapper pins, and no way to read the pin was given")
        return core_ref_resolver(wrapper_ref, core_ref)

    common = {"gtests": "true" if gtests == "true" else "false",
              "gtest_filter": gtest_filter or DEFAULT_GTEST_FILTER,
              "wrapper_ref": wrapper_ref}
    if kind not in KINDS:
        raise PlanError(f"kind must be one of {', '.join(KINDS)}, got {kind!r}")
    if stop_after not in STOP_AFTERS:
        raise PlanError(f"stop_after must be empty or one of {', '.join(STOP_AFTERS[1:])}, got {stop_after!r}")
    if stop_after:
        if kind != "candidate":
            raise PlanError(f"stop_after={stop_after} is for a candidate: a release is never cut short (kind={kind!r})")
        if ref_type != "branch" or not ref_name.startswith(STOP_AFTER_BRANCH_PREFIX):
            raise PlanError(f"stop_after={stop_after} runs from a {STOP_AFTER_BRANCH_PREFIX}* branch, "
                            f"not from {ref_name!r} ({ref_type or 'no ref type'})")
        # No link, so no gtest binary to run: the gtests are off whatever the input said.
        common["gtests"] = "false"
    if compile_cache and compile_cache not in COMPILE_CACHES:
        raise PlanError(f"compile_cache must be one of {', '.join(COMPILE_CACHES)}, "
                        f"got {compile_cache!r}")
    if ref_type == "tag":
        raise PlanError(f"a build from the tag {ref_name!r} would save cache entries nothing can read: "
                        f"dispatch it from a branch, a release from {RELEASE_BRANCH}")
    if kind == "release" and ref_type and ref_name != RELEASE_BRANCH:
        raise PlanError(f"a release is dispatched from {RELEASE_BRANCH}, whose cache every later run reads, "
                        f"not from {ref_name!r}")
    if kind == "candidate":
        if release_tag:
            raise PlanError(
                f"a candidate publishes nothing, so it takes no release tag (got "
                f"{release_tag!r}). To publish a draft from this run set kind=release; "
                f"to publish a candidate's archives later, run republish.yml with its "
                f"run id.")
        if not re.fullmatch(r"[0-9]+", last_release):
            raise PlanError(f"a candidate is sealed firefox-N-candidate, N being the engine after the last published "
                            f"release: the number of the last release is needed (got {last_release!r})")
        common["core_ref"] = core()
        return {"kind": "candidate", "tag": "", "num": "", "prevtag": "",
                "seal_tag": CANDIDATE_SEAL_TAG.format(n=int(last_release) + 1),
                "compile_cache": compile_cache or "gha", "stop_after": stop_after, **common}
    try:
        n = check_release_tag(release_tag)
    except SealBuildError as exc:
        raise PlanError(f"a release needs a firefox-N tag: {exc}") from None
    common["core_ref"] = core()
    return {"kind": "release", "tag": release_tag, "num": str(n),
            "prevtag": f"firefox-{n - 1}" if n > 0 else "", "seal_tag": release_tag,
            "compile_cache": compile_cache or "gha", "stop_after": "", **common}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="what a release run is")
    ap.add_argument("--event", default="")
    ap.add_argument("--kind", default="")
    ap.add_argument("--release-tag", default="")
    ap.add_argument("--ref-name", default="")
    ap.add_argument("--compile-cache", default="")
    ap.add_argument("--ref-type", default="")
    ap.add_argument("--gtests", default="")
    ap.add_argument("--gtest-filter", default="")
    ap.add_argument("--core-ref", default="")
    ap.add_argument("--wrapper-ref", default="")
    ap.add_argument("--stop-after", default="", help="objects: a compile-only candidate on a latitude/* branch")
    ap.add_argument("--last-release", default="", help="N of the last published firefox-N tag (a candidate is N+1)")
    ap.add_argument("--resolve-core-ref", action="store_true",
                    help="print core_ref=<the core to use> for --wrapper-ref [--core-ref] and nothing else (no other input needed)")
    a = ap.parse_args(argv)
    if a.resolve_core_ref:
        try:
            print(f"core_ref={github_resolve(a.wrapper_ref.strip() or DEFAULT_REF, a.core_ref.strip())}")
        except PlanError as exc:
            print(f"PLAN REFUSED: {exc}", file=sys.stderr)
            return 1
        return 0
    if not a.event:
        ap.error("--event is required (or --resolve-core-ref)")
    try:
        outputs = plan(a.event, a.kind, a.release_tag.strip(), a.ref_name,
                       a.compile_cache.strip(), a.ref_type.strip(), a.gtests.strip(),
                       a.gtest_filter.strip(), a.core_ref.strip(), a.wrapper_ref.strip(),
                       a.last_release.strip(), a.stop_after.strip(),
                       core_ref_resolver=github_resolve)
    except PlanError as exc:
        print(f"PLAN REFUSED: {exc}", file=sys.stderr)
        return 1
    for key, value in outputs.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
