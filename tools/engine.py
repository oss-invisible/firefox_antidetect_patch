"""The engine as a patch series: export it from a Firefox tree, rebuild a tree from it.

    python tools/engine.py status    did the source move since the last export?
    python tools/engine.py export    write the series from the source tree
    python tools/engine.py verify    rebuild the tree from the series, compare
    python tools/engine.py check     the series' own rules, offline (also in CI)
    python tools/engine.py apply --head <branch>   the series as a branch: tag + one commit per folder
    python tools/engine.py materialize --into <dir> CI: fetch the tag, apply, check out the tree
    python tools/engine.py drift --to <tag>   our patched Mozilla files that Mozilla changed
    python tools/engine.py port --to <tag>    every folder merged three-way onto the new tag,
                                              all conflicts in one run, branch port/<tag>, then the
                                              birth points of the new tag against the ledger
    python tools/engine.py births --tree <dir>   every place the tree makes a network request, against
                                              tools/birth-ledger.json (tools/births.py says how)

The Mozilla tag, the source branch and the commit last exported are in UPSTREAM.json;
--source / --base / --head override them (the source repository defaults to
C:/ff/source, or $ENGINE_SOURCE).

export   writes one folder per feature (tools/layout.py says which):
           hooks.patch    our changes to Mozilla's files, as a git diff against the tag
           src/<path>     the files we add to the tree, byte for byte
           MANIFEST.json  what the folder owns (regenerated on every export)
           FEATURE.md     the feature's description, created once and then edited by hand
         SERIES, the order the folders are applied in, and UPSTREAM.json's
         "exported_from". A folder that no longer owns anything is removed.

verify   rebuilds the tree from the series on top of the tag, in a throwaway git index
         (no checkout of Firefox, works in a bare repository), and compares it with the
         source head's tree. Identical trees mean the series IS the engine.

check    needs no Firefox: SERIES lists exactly the folders that exist, every folder has
         its MANIFEST and FEATURE.md, every file of ours is listed and present, each
         hooks.patch touches only the Mozilla files its MANIFEST owns, and no Mozilla file
         carries more of our lines than tools/hook-budget.json allows, nor loses or has
         rewritten more of its own lines than tools/removed-budget.json allows. Both
         budgets only go down (a hook budget goes above main's only with the row the branch adds to
         tools/hook-budget-raises.json, a register that only grows: from main's budget to the new one,
         with its folder, reason, who decided, date and test): logic belongs in our own files, Mozilla's files get hooks,
         and Mozilla's lines stay as Mozilla wrote them (a removed or rewritten line
         conflicts at a port like an added one, and a copy of it in a file of ours
         stops following Mozilla). A Mozilla file outside vendored code can be a backport (category
         backport, no budget) only as the diff of one commit of Mozilla's own repository, in a folder of
         platform/backports/ of its own: its BACKPORT.json names the commit and the sha256 of the diff, the diff is in the folder, and
         hooks.patch carries it byte for byte; with --against <tag> (and in a port) a tag that
         already holds the change fails. Every STEALTH-HOOK(<folder>) tag, in a hooks.patch and in the
         evidence of an inventory record, names a folder of SERIES, and the added, removed and hunk
         counts of each inventory record are those of its file in the hooks.patch. A C++ file of ours has no control character (a carriage return inside a
         string literal ended the literal and broke the build of a test) and no byte outside ASCII inside a
         string or character literal: write them as escapes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import births  # noqa: E402
import layout  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
INVENTORY = ROOT / "tools" / "inventory.json"
UPSTREAM = ROOT / "UPSTREAM.json"
BUDGET = ROOT / "tools" / "hook-budget.json"
REMOVED_BUDGET = ROOT / "tools" / "removed-budget.json"
REALIGN = ROOT / "tools" / "budget-realign-69.json"
# Declared raises of a hook budget above main's (a hook that is a wanted growth, decided by the pm):
# the register only grows, and a branch raises a budget only with the row it adds (budget_raise_problems).
RAISES = ROOT / "tools" / "hook-budget-raises.json"
# The workflows live in the series (the tree's tests read them beside scripts/), and
# GitHub runs them from this repository's root: export copies them there and check
# requires the two identical. series.yml and noreply-identity.yml are the root's own.
WORKFLOWS_SERIES = ROOT / "platform" / "ci" / "src" / ".github" / "workflows"
WORKFLOWS_ROOT = ROOT / ".github" / "workflows"
ROOT_ONLY_WORKFLOWS = {"series.yml", "noreply-identity.yml"}


def git(source: Path, *args: str, env=None, input_bytes=None) -> bytes:
    return subprocess.run(["git", "-C", str(source), *args], check=True,
                          capture_output=True, env=env, input=input_bytes).stdout


def upstream() -> dict:
    return json.loads(UPSTREAM.read_text(encoding="utf-8"))


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def series_folders() -> list:
    return (ROOT / "SERIES").read_text(encoding="utf-8").split()


def existing_folders() -> list:
    return sorted(str(p.parent.relative_to(ROOT)).replace("\\", "/")
                  for p in ROOT.glob("*/**/MANIFEST.json")
                  if p.relative_to(ROOT).parts[0] in layout.GROUP_ORDER and "src" not in p.relative_to(ROOT).parts)


def changed_files(source: Path, base: str, head: str):
    """(status, mode, path) for every file the head changes against the tag."""
    out = git(source, "diff", "--no-renames", "--raw", "-z", base, head)
    fields = out.split(b"\0")
    result = []
    for meta, path in zip(fields[0::2], fields[1::2]):
        if not meta:
            continue
        parts = meta.decode().lstrip(":").split()
        result.append((parts[4], parts[1], path.decode()))
    return result


def owners(source: Path, base: str, head: str):
    """folder -> {"modified": [paths], "added": [(path, mode)]}"""
    records = {r["file"]: r for r in json.loads(INVENTORY.read_text(encoding="utf-8"))}
    plan = defaultdict(lambda: {"modified": [], "added": []})
    for status, mode, path in changed_files(source, base, head):
        if status in ("M", "D"):   # D: a Mozilla file we delete is ours to own like any change
            if path not in records:
                raise SystemExit("modified file %s is not in the inventory: add its record to %s "
                                 "(feature, category, anchor, hookable, notes)" % (path, INVENTORY.name))
            plan[layout.feature_folder(records[path]["feature"])]["modified"].append(path)
        elif status == "A":
            plan[layout.own_file_folder(path)]["added"].append((path, mode))
        else:
            raise SystemExit("status %s for %s is not handled yet" % (status, path))
    return plan, records


def require_descends(source: Path, base: str, head: str) -> None:
    """The branch must be built on the tag: a diff between unrelated commits would
    export Mozilla's own changes as ours."""
    if subprocess.run(["git", "-C", str(source), "merge-base", "--is-ancestor", base, head],
                      capture_output=True).returncode:
        raise SystemExit("%s does not descend from %s: the series is the difference from the tag, "
                         "so the branch must be built on it (tools/engine.py apply)" % (head, base))


def export(source: Path, base: str, head: str) -> None:
    require_descends(source, base, head)
    plan, records = owners(source, base, head)
    series = sorted(plan, key=layout.folder_sort_key)
    for gone in sorted(set(existing_folders()) - set(series)):
        shutil.rmtree(ROOT / gone)
        print("removed %s: it owns nothing any more" % gone)
    for folder in series:
        out = ROOT / folder
        out.mkdir(parents=True, exist_ok=True)
        owned = plan[folder]
        patch = out / "hooks.patch"
        if owned["modified"]:
            patch.write_bytes(git(source, "diff", "--binary", "--full-index", "--no-renames",
                                  base, head, "--", *sorted(owned["modified"])))
        elif patch.exists():
            patch.unlink()
        if (out / "src").exists():
            shutil.rmtree(out / "src")
        for path, mode in owned["added"]:
            target = out / "src" / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(git(source, "cat-file", "blob", "%s:%s" % (head, path)))
        manifest = {
            "modified": sorted(owned["modified"]),
            "added": {path: mode for path, mode in sorted(owned["added"])},
            "inventory": [records[p] for p in sorted(owned["modified"])],
        }
        write_json(out / "MANIFEST.json", manifest)
        feature_md = out / "FEATURE.md"
        if not feature_md.exists():
            feature_md.write_text(describe(folder, manifest), encoding="utf-8", newline="\n")
    (ROOT / "SERIES").write_text("\n".join(series) + "\n", encoding="utf-8", newline="\n")
    sync_workflows()
    up = upstream()
    up["exported_from"] = git(source, "rev-parse", head).decode().strip()
    up["exported_tree"] = git(source, "rev-parse", "%s^{tree}" % head).decode().strip()
    write_json(UPSTREAM, up)
    print("exported %d folders: %d modified files, %d added files, from %s"
          % (len(series), sum(len(plan[f]["modified"]) for f in series),
             sum(len(plan[f]["added"]) for f in series), up["exported_from"][:10]))


def sync_workflows() -> None:
    WORKFLOWS_ROOT.mkdir(parents=True, exist_ok=True)
    for old in WORKFLOWS_ROOT.glob("*.yml"):
        if old.name not in ROOT_ONLY_WORKFLOWS:
            old.unlink()
    for wf in WORKFLOWS_SERIES.glob("*.yml"):
        (WORKFLOWS_ROOT / wf.name).write_bytes(wf.read_bytes())


def describe(folder: str, manifest: dict) -> str:
    """A first FEATURE.md, from the inventory. Edited by hand from then on."""
    recs = manifest["inventory"]
    prefs = sorted({p for r in recs for p in r.get("prefs") or []})
    categories = sorted({r["category"] for r in recs})
    lines = ["# %s" % folder, "",
             "Category: %s" % (", ".join(categories) or "own files only"),
             "Prefs: %s" % (", ".join(prefs) or "none read directly"),
             "Test: TODO", "",
             "## What it does", "", "TODO: one paragraph, from the notes below.", "",
             "## Hooks in Mozilla files", ""]
    for r in recs:
        lines.append("- `%s` (%s, %s): %s" % (r["file"], r.get("anchor") or "?", r["hookable"],
                                             (r.get("notes") or "").replace("\n", " ")[:400]))
    if manifest["added"]:
        lines += ["", "## Our own files", ""] + ["- `%s`" % p for p in manifest["added"]]
    return "\n".join(lines) + "\n"


IDENTITY = {"GIT_AUTHOR_NAME": "feder-cr", "GIT_COMMITTER_NAME": "feder-cr",
            "GIT_AUTHOR_EMAIL": "85809106+feder-cr@users.noreply.github.com",
            "GIT_COMMITTER_EMAIL": "85809106+feder-cr@users.noreply.github.com"}


def apply(source: Path, base: str, branch: str, force: bool) -> str:
    """Builds the engine in the source repository as branch `branch`: the Mozilla tag,
    then one commit per folder of SERIES, in order. No checkout: the branch is written
    with git plumbing, so it works in a bare repository and does not touch a worktree.
    The commit of a folder is titled with the folder, so `git log` is the layer stack."""
    ref = "refs/heads/%s" % branch
    exists = subprocess.run(["git", "-C", str(source), "rev-parse", "-q", "--verify", ref],
                            capture_output=True).returncode == 0
    if exists and not force:
        raise SystemExit("%s already exists in %s: pass --force to rebuild it (its commits are lost "
                         "unless exported first)" % (branch, source))
    layers = build_stack(source, base)
    parent, tree = layers[-1][1], layers[-1][2]
    git(source, "update-ref", ref, parent)
    print("%s: %s on top of %s, %d layers (tree %s)"
          % (branch, parent[:10], base, len(series_folders()), tree[:12]))
    return tree


def build_stack(source: Path, base: str) -> list:
    """The series on `base`, as [(folder, commit, tree)] in SERIES order (the first entry
    is the tag itself, folder None). Writes objects only, moves no ref."""
    parent = git(source, "rev-parse", "%s^{commit}" % base).decode().strip()
    layers = [(None, parent, git(source, "rev-parse", "%s^{tree}" % parent).decode().strip())]
    # Every layer is dated with the tag's own commit date: the same series on the same
    # tag gives the same commits, byte for byte, on any machine. That makes the commit
    # a seal records (source_commit) reproducible by anyone who has main and the tag,
    # although it lives on no remote.
    when = git(source, "log", "-1", "--format=%cI", parent).decode().strip()
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ, GIT_INDEX_FILE=str(Path(tmp) / "index"), **IDENTITY,
                   GIT_AUTHOR_DATE=when, GIT_COMMITTER_DATE=when)
        git(source, "read-tree", parent, env=env)
        for folder in series_folders():
            patch = ROOT / folder / "hooks.patch"
            if patch.exists():
                done = subprocess.run(["git", "-C", str(source), "apply", "--cached", "--whitespace=nowarn",
                                       str(patch)], capture_output=True, env=env)
                if done.returncode:
                    raise SystemExit("%s does not apply on %s:\n%s"
                                     % (folder, base, done.stderr.decode(errors="replace")))
            manifest = json.loads((ROOT / folder / "MANIFEST.json").read_text(encoding="utf-8"))
            for path, mode in manifest["added"].items():
                data = (ROOT / folder / "src" / path).read_bytes()
                sha = git(source, "hash-object", "-w", "--stdin", input_bytes=data).decode().strip()
                git(source, "update-index", "--add", "--cacheinfo", "%s,%s,%s" % (mode, sha, path),
                    env=env)
            tree = git(source, "write-tree", env=env).decode().strip()
            parent = git(source, "commit-tree", tree, "-p", parent, "-m", folder, env=env).decode().strip()
            layers.append((folder, parent, tree))
    return layers


def port(source: Path, old: str, new: str, branch: str, force: bool, check_births: bool = False) -> int:
    """Moves the series from Mozilla tag `old` to tag `new` in one run, every folder
    merged three-way, and reports every conflict instead of stopping at the first.

    The series is applied to `old`, where it applies cleanly, giving layers L1..Ln.
    Then each layer is replayed on `new`: Ni = merge(base L(i-1), ours N(i-1), theirs Li)
    with `git merge-tree`, so each folder's own change meets what Mozilla changed.
    A conflicted folder still gets its commit (files with conflict markers) and the
    run goes on. The result is branch `branch` in the source repository: resolve the
    markers there, commit, then export. Both tags must be in the source repository
    (the blobs of `old` are the base of every merge)."""
    for tag in (old, new):
        if subprocess.run(["git", "-C", str(source), "rev-parse", "-q", "--verify", "%s^{commit}" % tag],
                          capture_output=True).returncode:
            raise SystemExit("%s is not in %s: fetch it first, e.g. git -C %s fetch --depth 1 %s "
                             "refs/tags/%s:refs/tags/%s" % (tag, source, source, upstream()["mozilla_repository"], tag, tag))
    ref = "refs/heads/%s" % branch
    if subprocess.run(["git", "-C", str(source), "rev-parse", "-q", "--verify", ref],
                      capture_output=True).returncode == 0 and not force:
        raise SystemExit("%s already exists: pass --force to rebuild it" % branch)
    stack = build_stack(source, old)
    current = git(source, "rev-parse", "%s^{commit}" % new).decode().strip()
    when = git(source, "log", "-1", "--format=%cI", current).decode().strip()
    env = dict(os.environ, **IDENTITY, GIT_AUTHOR_DATE=when, GIT_COMMITTER_DATE=when)
    report = []
    for (_, base_commit, _), (folder, layer, _) in zip(stack, stack[1:]):
        done = subprocess.run(["git", "-C", str(source), "merge-tree", "--write-tree", "--name-only",
                               "--no-messages", "--merge-base=%s" % base_commit, current, layer],
                              capture_output=True)
        lines = done.stdout.decode(errors="replace").split("\n")
        if done.returncode not in (0, 1) or not lines[0].strip():
            raise SystemExit("merge-tree failed on %s: %s" % (folder, done.stderr.decode(errors="replace")))
        tree, conflicts = lines[0].strip(), sorted({l for l in lines[1:] if l.strip()})
        title = folder if not conflicts else "%s (CONFLICT: %s)" % (folder, ", ".join(conflicts))
        current = git(source, "commit-tree", tree, "-p", current, "-m", title, env=env).decode().strip()
        report.append((folder, conflicts))
    git(source, "update-ref", ref, current)
    bad = [(f, c) for f, c in report if c]
    for folder, conflicts in bad:
        print("CONFLICT %s: %s" % (folder, ", ".join(conflicts)))
    already = backport_in_tag_problems(source, new)
    for problem in already:
        print("FAIL %s" % problem)
    print("%s: %d folders moved from %s to %s, %d clean, %d with conflicts (%d files)"
          % (branch, len(report), old, new, len(report) - len(bad), len(bad), sum(len(c) for _, c in bad)))
    status = 0
    if check_births:
        # The birth points of the new tag: a call that Mozilla added, or whose arguments or context handling it changed, is red until it is in
        # the ledger. Read from the commit just made (no checkout). The rows of every site go to a file in the temporary directory, for the review.
        reader = births.Source(source, ref)
        if reader.is_firefox_tree():
            status = births.run(reader, series_folders(), title="birth points of %s:" % new,
                                tsv=Path(tempfile.gettempdir()) / ("births-port-%s.tsv" % new))
        else:
            print("birth points not scanned: %s is not a Firefox tree" % branch)
    return 1 if bad or already or status == 1 else 0


def drift(source: Path, old: str, new: str) -> int:
    """Which Mozilla files we patch did Mozilla change between the two tags: the files
    a port has to look at, whether or not they conflict."""
    ours = sorted(r["file"] for r in json.loads(INVENTORY.read_text(encoding="utf-8")))
    out = git(source, "diff", "--name-status", "--no-renames", old, new, "--", *ours).decode()
    rows = [l.split("\t", 1) for l in out.splitlines() if l.strip()]
    for status, path in rows:
        print("%s %s" % ({"M": "changed", "D": "DELETED by Mozilla", "A": "added"}.get(status, status), path))
    print("%d of our %d patched Mozilla files changed between %s and %s" % (len(rows), len(ours), old, new))
    return 0


def _init_repo(into: Path) -> None:
    into.mkdir(parents=True, exist_ok=True)
    if not (into / ".git").exists():
        git(into, "init", "-q")
    exclude = into / ".git" / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    rel = os.path.relpath(ROOT, into).replace("\\", "/")
    if not rel.startswith(".."):
        exclude.write_text("/%s/\n" % rel, encoding="utf-8")


#: Seconds before each new fetch. A build node in Dallas fetched at 2 MB/s for 50 min
#: and git gave up (exit 128): the leg died (candidate 41881364268, 04/11).
FETCH_WAITS = (30, 90)


def _fetch_tag(into: Path, up: dict, sleep=time.sleep) -> None:
    tag = up["mozilla_tag"]
    for attempt in range(len(FETCH_WAITS) + 1):
        try:
            git(into, "fetch", "-q", "--depth", "1", "--no-tags", up["mozilla_repository"],
                "refs/tags/%s:refs/tags/%s" % (tag, tag))
            return
        except subprocess.CalledProcessError as exc:
            if attempt == len(FETCH_WAITS):
                raise
            print("materialize: the fetch of %s failed (%s), again in %d s"
                  % (tag, (exc.stderr or b"").decode(errors="replace").strip()[-200:] or exc, FETCH_WAITS[attempt]))
            sleep(FETCH_WAITS[attempt])


def _borrow_tag(into: Path, mirror: Path, tag: str) -> None:
    """The tag from the node's own fetch without running git in it: the mirror is root's,
    and git refuses another user's repository ("dubious ownership"), even to fetch from,
    whatever -c safe.directory says (candidate 42004989128: the leg fell back to GitHub,
    418 s). Its objects by alternates, its ref and its shallow file read as files."""
    ref = mirror / "refs" / "tags" / tag
    sha = ref.read_text(encoding="utf-8").strip() if ref.exists() else ""
    if not sha:
        packed = (mirror / "packed-refs").read_text(encoding="utf-8") if (mirror / "packed-refs").exists() else ""
        sha = next((l.split()[0] for l in packed.splitlines() if l.endswith(" refs/tags/%s" % tag)), "")
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise OSError("the node's fetch has no commit for refs/tags/%s" % tag)
    alternates = into / ".git" / "objects" / "info" / "alternates"
    alternates.parent.mkdir(parents=True, exist_ok=True)
    alternates.write_text(str((mirror / "objects").resolve()) + "\n", encoding="utf-8")
    if (mirror / "shallow").exists():
        shutil.copyfile(mirror / "shallow", into / ".git" / "shallow")
    git(into, "update-ref", "refs/tags/%s" % tag, sha)


def _fetch_and_apply(into: Path, up: dict, branch: str, mirror: Path | None = None) -> str:
    if mirror is not None:
        _borrow_tag(into, mirror, up["mozilla_tag"])
    else:
        _fetch_tag(into, up)
    return apply(into, up["mozilla_tag"], branch, force=True)


#: How long the first leg waits for the node's own fetch of the tag before going to
#: GitHub itself. That fetch starts as soon as the node is prepared, before the runners
#: (latitude_node.py, prefetch), and took 110-180 s on 04/11.
MIRROR_WAIT_S = 20 * 60


def _wait_for_mirror(mirror: Path, tag: str, clock=time.monotonic, sleep=time.sleep) -> str | None:
    """The node's mirror of the tag once it is whole, or None: no mirror, its fetch
    failed, or it took longer than MIRROR_WAIT_S. None means GitHub, as before."""
    if not mirror.is_dir():
        return None
    began = clock()
    while clock() - began < MIRROR_WAIT_S:
        if (mirror / ("fetched-%s" % tag)).exists():
            return str(mirror)
        if (mirror / ("failed-%s" % tag)).exists():
            print("materialize: the node's own fetch of %s failed: from GitHub" % tag)
            return None
        sleep(5)
    print("materialize: the node's own fetch of %s took over %d s: from GitHub" % (tag, MIRROR_WAIT_S))
    return None


def _open_lock(path: Path) -> int:
    """The lock, read-only and world-readable: the other leg is another user, and flock
    needs no write access. Never O_CREAT on a file that exists: in a sticky, world-writable
    directory Linux refuses that on another user's file (fs.protected_regular), even to
    read it, and the second leg of candidate 41892772401 fetched its own tree for it."""
    try:
        return os.open(str(path), os.O_RDONLY)
    except FileNotFoundError:
        try:
            return os.open(str(path), os.O_RDONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError:  # the other leg made it in between
            return os.open(str(path), os.O_RDONLY)


def _shared_commit(shared: Path, up: dict, branch: str) -> Path:
    """The series applied once per machine, in `shared`, by whichever leg comes first;
    the others wait on the lock and take it. Returns the repository that holds it. A
    leg that dies holding the lock frees it with its process (flock), and the next one
    starts over: the commit is marked only once whole."""
    import fcntl  # the build nodes only, which are Linux
    key = (up.get("exported_tree") or up["mozilla_tag"])[:12]
    repo, mark = shared / key, shared / ("%s.commit" % key)
    shared.mkdir(parents=True, exist_ok=True)
    fd = _open_lock(shared / ("%s.lock" % key))
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        if not mark.exists():
            shutil.rmtree(repo, ignore_errors=True)
            _init_repo(repo)
            mirror = _wait_for_mirror(shared / "mozilla.git", up["mozilla_tag"])
            if mirror:
                print("materialize: the tag from the node's own fetch, %s" % mirror)
                try:
                    _fetch_and_apply(repo, up, branch, mirror=Path(mirror))
                except (OSError, subprocess.CalledProcessError) as exc:
                    print("materialize: the node's fetch could not be borrowed (%s): from GitHub" % exc)
                    shutil.rmtree(repo, ignore_errors=True)
                    _init_repo(repo)
                    _fetch_and_apply(repo, up, branch)
            else:
                _fetch_and_apply(repo, up, branch)
            commit = git(repo, "rev-parse", branch).decode().strip()
            mark.write_text(commit + "\n", encoding="utf-8")
            print("materialize: the series applied in %s, for every leg on this machine" % repo)
        else:
            print("materialize: the series was applied in %s by another leg" % repo)
    finally:
        os.close(fd)
    return repo


def materialize(into: Path, branch: str = "engine", shared: Path | None = None) -> str:
    """For CI: makes `into` the engine's source tree, exactly as a checkout of the old
    full-tree branch was. Fetches the Mozilla tag one commit deep from Mozilla's
    repository, applies the series as `branch`, checks it out, and requires the tree to
    be the one UPSTREAM.json declares. Prints the built commit.

    With `shared`, a directory every leg of the machine can reach: the fetch and the
    series happen once there, and `into` borrows its objects (git alternates) and checks
    out its own files. Both legs of a build node fetched the same tag from GitHub at the
    same time and applied the same series, 3 min each and 6.6 when GitHub was slow
    (04/11)."""
    up = upstream()
    _init_repo(into)
    tag = up["mozilla_tag"]
    # Each phase timed: on a build node the Linux leg took 5.8 min here twice, Windows
    # 2.4, both starting together (04/11), and nothing said which phase it was.
    began = time.monotonic()
    repo = None
    if shared is not None:
        try:
            repo = _shared_commit(shared, up, branch)
        except (OSError, subprocess.CalledProcessError) as exc:
            # A leg that cannot use the shared tree builds its own, as before: slower,
            # never wrong.
            print("materialize: the shared tree in %s failed (%s): this leg fetches its own" % (shared, exc))
            shared = None
    if shared is None:
        _fetch_tag(into, up)
        fetched = time.monotonic()
        tree = apply(into, tag, branch, force=True)
        applied = time.monotonic()
    else:
        fetched = time.monotonic()
        alternates = into / ".git" / "objects" / "info" / "alternates"
        alternates.parent.mkdir(parents=True, exist_ok=True)
        alternates.write_text(str((repo / ".git" / "objects").resolve()) + "\n", encoding="utf-8")
        # The tag came one commit deep: the borrowing repository must know where history
        # stops too, or `git log` looks for the tag's parent. The build asks for one
        # (config/milestone.txt's date, for the .rc files) and the Windows leg of
        # candidate 41912498170 died on "Could not read" that commit.
        shallow = repo / ".git" / "shallow"
        if shallow.exists():
            shutil.copyfile(shallow, into / ".git" / "shallow")
        commit = (shared / ("%s.commit" % repo.name)).read_text(encoding="utf-8").strip()
        git(into, "update-ref", "refs/heads/%s" % branch, commit)
        tree = git(into, "rev-parse", "%s^{tree}" % branch).decode().strip()
        applied = time.monotonic()
    expected = up.get("exported_tree")
    if expected and tree != expected:
        raise SystemExit("the series applied to %s gives tree %s, UPSTREAM.json declares %s"
                         % (tag, tree, expected))
    # The working tree follows the machine's git config (core.autocrlf), exactly as the
    # actions/checkout this replaces did: the Windows legs build what they built before.
    git(into, "checkout", "-q", "-f", branch)
    head = git(into, "rev-parse", "HEAD").decode().strip()
    done = time.monotonic()
    print("materialize: %s %.0f s, apply %.0f s, checkout %.0f s"
          % ("fetch" if shared is None else "shared (fetch and apply, or wait for them)",
             fetched - began, applied - fetched, done - applied))
    print("materialized %s: %s (tree %s)" % (into, head, tree[:12]))
    return head


def verify(source: Path, base: str, head: str) -> int:
    require_descends(source, base, head)
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ, GIT_INDEX_FILE=str(Path(tmp) / "index"))
        git(source, "read-tree", base, env=env)
        for folder in series_folders():
            patch = ROOT / folder / "hooks.patch"
            if patch.exists():
                git(source, "apply", "--cached", "--whitespace=nowarn", str(patch), env=env)
            manifest = json.loads((ROOT / folder / "MANIFEST.json").read_text(encoding="utf-8"))
            for path, mode in manifest["added"].items():
                data = (ROOT / folder / "src" / path).read_bytes()
                sha = git(source, "hash-object", "-w", "--stdin", input_bytes=data).decode().strip()
                git(source, "update-index", "--add", "--cacheinfo", "%s,%s,%s" % (mode, sha, path),
                    env=env)
        built = git(source, "write-tree", env=env).decode().strip()
    expected = git(source, "rev-parse", "%s^{tree}" % head).decode().strip()
    if built == expected:
        print("identical: the series rebuilds %s exactly (tree %s)" % (head, built))
        return 0
    diff = git(source, "diff", "--stat", expected, built).decode()
    print("DIFFERENT: rebuilt tree %s, %s is %s\n%s" % (built, head, expected, diff))
    return 1


PATCH_FILE = re.compile(r"^diff --git a/(\S+) b/")


def _patch_lines(patch: Path, sign: str) -> dict:
    # Counted only inside hunks, so the ---/+++ header is never a line, and a line
    # that itself starts with -- or ++ is.
    counts, current, in_hunk = {}, None, False
    for line in patch.read_text(encoding="utf-8", errors="replace").splitlines():
        m = PATCH_FILE.match(line)
        if m:
            current, in_hunk = m.group(1), False
            counts[current] = 0
        elif line.startswith("@@"):
            in_hunk = True
        elif current and in_hunk and line.startswith(sign):
            counts[current] += 1
    return counts


def added_lines(patch: Path) -> dict:
    """Mozilla file -> lines we add to it, read from a hooks.patch."""
    return _patch_lines(patch, "+")


def removed_lines(patch: Path) -> dict:
    """Mozilla file -> lines of Mozilla's we remove or rewrite, read from a hooks.patch."""
    return _patch_lines(patch, "-")


def hunk_counts(patch: Path) -> dict:
    """Mozilla file -> hunks of its diff, read from a hooks.patch."""
    counts, current = {}, None
    for line in patch.read_text(encoding="utf-8", errors="replace").splitlines():
        m = PATCH_FILE.match(line)
        if m:
            current = m.group(1)
            counts[current] = 0
        elif line.startswith("@@") and current:
            counts[current] += 1
    return counts


HOOK_TAG = re.compile(r"STEALTH-HOOK\(([^)]*)\)")


def hook_tag_problems(folders: set, records: list, patches: dict) -> list:
    """A STEALTH-HOOK(<folder>) tag names the folder that owns the hook; one that names
    nothing in SERIES (a folder deleted or renamed since) sends whoever greps it to a place
    that is not there. Looked at: the evidence of every inventory record, and every line of
    every hooks.patch (`patches`: folder -> text)."""
    found = []
    for r in records:
        for line in r.get("evidence") or []:
            for tag in HOOK_TAG.findall(line):
                if tag not in folders:
                    found.append("tools/inventory.json: the evidence of %s quotes STEALTH-HOOK(%s), and %s is not a "
                                 "folder of SERIES: regenerate the record from the code" % (r["file"], tag, tag))
    for folder, text in sorted(patches.items()):
        for tag in sorted(set(HOOK_TAG.findall(text))):
            if tag not in folders:
                found.append("%s/hooks.patch carries STEALTH-HOOK(%s), and %s is not a folder of SERIES: "
                             "retag the hook in the source" % (folder, tag, tag))
    return found


def record_count_problems(records: list, counts: dict) -> list:
    """Each inventory record says how many lines of ours (added), of Mozilla's (removed) and how
    many hunks its file has: the numbers of the file in its hooks.patch (`counts`: file ->
    (added, removed, hunks)). A record written once and never refreshed, or copied from another
    feature, reads as truth to whoever sizes a hook from it."""
    found = []
    for r in records:
        real = counts.get(r["file"])
        if real is None:
            continue
        have = (r.get("added"), r.get("removed"), r.get("hunks"))
        if have != tuple(real):
            found.append("tools/inventory.json: the record of %s says added %s, removed %s, hunks %s; its hooks.patch has "
                         "%d, %d, %d: rewrite the record from the diff against the tag" % ((r["file"],) + have + tuple(real)))
    return found


BACKPORT = "BACKPORT.json"
# Where upstream code lives in Firefox's tree: its vendored copies, and the lock and
# checksums Cargo checks them against.
VENDORED = ("third_party/rust/", "Cargo.lock")
# The other kind of backport: a commit of Mozilla's own repository carried before the
# tag has it, in the file it changes (not vendored code).
MOZILLA_REPO = "mozilla-firefox/firefox"
# Its folder: one per commit, beside no logic of ours.
MOZILLA_BACKPORTS = "platform/backports/"


def is_mozilla_upstream(url) -> bool:
    if not isinstance(url, str):
        return False
    url = url.strip().rstrip("/")
    url = url[:-4] if url.endswith(".git") else url
    return url == MOZILLA_REPO or url.endswith("github.com/" + MOZILLA_REPO)


def file_section(patch: bytes, path: str) -> bytes:
    """The diff of one file inside a patch: from its `diff --git` line to the next one
    (or the end), without a mail trailer (`-- ` and the version line) after the last."""
    out, inside = [], False
    for line in patch.split(b"\n"):
        if line.startswith(b"diff --git "):
            inside = line.startswith(b"diff --git a/" + path.encode() + b" b/")
        if inside:
            out.append(line)
    while out and (out[-1] == b"" or out[-1] == b"-- " or re.fullmatch(rb"\d+(\.\d+)+", out[-1])):
        out.pop()
    return b"\n".join(out) + b"\n" if out else b""


def normalized_diff(section: bytes) -> bytes:
    """What a diff says, apart from where it was made: the lines of its hunks, each hunk
    opened by a bare `@@`. Not the `index` line (the blobs of another tree), not the
    numbers of the hunk headers (the offset of another tree)."""
    out, in_hunk = [], False
    for line in section.split(b"\n"):
        if line.startswith(b"@@"):
            in_hunk = True
            out.append(b"@@")
        elif in_hunk:
            out.append(line)
    while out and out[-1] == b"":
        out.pop()
    return b"\n".join(out) + b"\n" if out else b""


def mozilla_backport_problems(folder: str, files: list, data: dict, patch: Path) -> list:
    """A Mozilla file carried ahead as the diff of one commit of Mozilla's repository. It
    is not ours, so it has no budget; what keeps it honest is that its diff here is the
    diff of the declared commit, byte for byte (BACKPORT.json: the sha256 of the commit's
    diff of the file, and the diff itself beside it to read again)."""
    found = []
    missing = [k for k in ("commit", "bug", "date", "files", "drop_when") if not data.get(k)]
    if missing:
        return ["%s/%s lacks %s" % (folder, BACKPORT, ", ".join(missing))]
    if not re.fullmatch(r"[0-9a-f]{40}", str(data["commit"])):
        found.append("%s/%s: commit %r is not a full sha: name the commit of %s the diff comes from"
                     % (folder, BACKPORT, data["commit"], MOZILLA_REPO))
    ours = patch.read_bytes() if patch.exists() else b""
    for path in files:
        entry = (data["files"] if isinstance(data["files"], dict) else {}).get(path)
        if not isinstance(entry, dict) or not entry.get("diff") or not entry.get("sha256"):
            found.append("%s/%s: files has no diff and sha256 for %s" % (folder, BACKPORT, path))
            continue
        stored = ROOT / folder / entry["diff"]
        if not stored.is_file():
            found.append("%s/%s: the diff %s of %s is not in the folder" % (folder, BACKPORT, entry["diff"], path))
            continue
        theirs = normalized_diff(file_section(stored.read_bytes(), path))
        if not theirs:
            found.append("%s/%s does not hold a diff of %s" % (folder, entry["diff"], path))
        elif hashlib.sha256(theirs).hexdigest() != entry["sha256"]:
            found.append("%s/%s is not the diff that BACKPORT.json declares for %s (sha256 differs): "
                         "the diff of the commit is not edited" % (folder, entry["diff"], path))
        elif normalized_diff(file_section(ours, path)) != theirs:
            found.append("%s/hooks.patch changes %s differently from commit %s: a backport is that diff "
                         "byte for byte, not a diff touched by hand" % (folder, path, str(data["commit"])[:12]))
    return found


def backport_problems(folder: str, upstream_code: set, patch: Path) -> list:
    """Upstream code carried ahead of Mozilla (category backport) is not ours, so it has
    no budget; what keeps it honest is its BACKPORT.json. Vendored code (third_party/rust):
    the upstream, the revision Mozilla vendors (the patch must apply on it), and the
    commits, ours last. Any other file: the commit of Mozilla's repository whose diff it is."""
    if not upstream_code:
        return []
    vendored = {p for p in upstream_code if p.startswith(VENDORED)}
    foreign = sorted(upstream_code - vendored)
    outside = ["%s: %s is category backport outside vendored code (%s)" % (folder, p, ", ".join(VENDORED))
               for p in foreign]
    record = ROOT / folder / BACKPORT
    if not record.exists():
        return outside + ["%s carries upstream code (%s) with no %s: name the upstream, the "
                          "vendored revision and the commits" % (folder, sorted(upstream_code)[0], BACKPORT)]
    data = json.loads(record.read_text(encoding="utf-8"))
    found = []
    if foreign:
        if not folder.startswith(MOZILLA_BACKPORTS):
            found += outside + ["%s carries %s as the diff of a commit of %s outside %s<name>: a backport "
                                "of a Mozilla commit has its own folder there, beside no logic of ours"
                                % (folder, foreign[0], MOZILLA_REPO, MOZILLA_BACKPORTS)]
        elif is_mozilla_upstream(data.get("upstream")):
            found += mozilla_backport_problems(folder, foreign, data, patch)
        else:
            found += outside + ["%s/%s: upstream %r is not %s, the only upstream a file outside vendored "
                                "code can be carried from" % (folder, BACKPORT, data.get("upstream"), MOZILLA_REPO)]
    if vendored:
        missing = [k for k in ("upstream", "vendored", "commits", "drop_when") if not data.get(k)]
        if missing:
            return found + ["%s/%s lacks %s" % (folder, BACKPORT, ", ".join(missing))]
        if data["vendored"] not in patch.read_text(encoding="utf-8", errors="replace"):
            found.append("%s/%s says the vendored revision is %s, which its hooks.patch does not "
                         "patch: Mozilla vendors another one now, so drop what upstream has and "
                         "pick the rest again" % (folder, BACKPORT, data["vendored"]))
    return found


def backport_in_tag_problems(source: Path, tag: str) -> list:
    """A commit carried ahead stops being ours the day the tag has it. Each file of a
    Mozilla-commit backport is tried against the tag: the patch applies backwards
    exactly when the tag already holds the change. (Needs the tag in `source`; a port, or
    `check --against`, runs it.)"""
    found = []
    for folder in existing_folders():
        record = ROOT / folder / BACKPORT
        if not record.exists():
            continue
        data = json.loads(record.read_text(encoding="utf-8"))
        if not is_mozilla_upstream(data.get("upstream")) or not isinstance(data.get("files"), dict):
            continue
        ours = (ROOT / folder / "hooks.patch").read_bytes()
        for path in sorted(data["files"]):
            blob = subprocess.run(["git", "-C", str(source), "show", "%s:%s" % (tag, path)], capture_output=True)
            section = file_section(ours, path)
            if blob.returncode or not section:
                continue
            with tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp) / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(blob.stdout)
                (Path(tmp) / "backport.patch").write_bytes(section)
                done = subprocess.run(["git", "apply", "--reverse", "--check", "backport.patch"],
                                      cwd=tmp, capture_output=True)
            if done.returncode == 0:
                found.append("%s: the tag %s already contains the backport of %s (commit %s): take the "
                             "backport out of the series" % (folder, tag, path, str(data.get("commit"))[:12]))
    return found


def _digit_separator(text: str, i: int) -> bool:
    """text[i] is an apostrophe: inside a number (1'000, 0x1'0000) and not the start of a character literal (u'|', L'x')."""
    j = i - 1
    while j >= 0 and (text[j].isalnum() or text[j] == "_"):
        j -= 1
    token = text[j + 1:i]
    return bool(token) and token[0].isdigit()


def cxx_byte_problems(text: str) -> list:
    """What in a C++ file of ours is not what it looks like: a control character anywhere (a carriage return is
    allowed only as the first half of a line ending), and a character outside ASCII inside a string or character
    literal (write it as an escape: the editor, the terminal and the compiler do not agree on what it is). Comments
    may say whatever they like. Returns [(line, what)]."""
    found = []
    i, n, line = 0, len(text), 1
    while i < n:
        c = text[i]
        two = text[i:i + 2]
        if two == "//":
            while i < n and text[i] != "\n":
                if ord(text[i]) < 32 and text[i] not in "\t\r":
                    found.append((line, "control character %r in a comment" % text[i]))
                i += 1
            continue
        if two == "/*":
            end = text.find("*/", i + 2)
            end = n if end < 0 else end + 2
            for ch in text[i:end]:
                if ch == "\n":
                    line += 1
                elif ord(ch) < 32 and ch not in "\t\r":
                    found.append((line, "control character %r in a comment" % ch))
            i = end
            continue
        raw = c == "R" and text[i + 1:i + 2] == '"' and not (i and (text[i - 1].isalnum() or text[i - 1] == "_"))
        if raw:
            paren = text.find("(", i + 2)
            delim = text[i + 2:paren] if paren > 0 else ""
            end = text.find(")" + delim + '"', paren)
            end = n if end < 0 else end + len(delim) + 2
            line += text.count("\n", i, end)
            i = end
            continue
        if c == '"' or (c == "'" and not _digit_separator(text, i)):
            quote, j = c, i + 1
            while j < n and text[j] != quote:
                ch = text[j]
                if ch == "\\":
                    j += 2
                    continue
                if ch == "\n":
                    found.append((line, "a %s literal that does not end on its line (a raw control character may have ended it)"
                                  % ("string" if quote == '"' else "character")))
                    break
                if ord(ch) < 32 and ch != "\t":
                    found.append((line, "control character %r inside a literal: write it as an escape" % ch))
                elif ord(ch) > 127:
                    found.append((line, "character %r outside ASCII inside a literal: write it as an escape" % ch))
                j += 1
            i = j + 1
            continue
        if c == "\n":
            line += 1
        elif ord(c) < 32 and c not in "\t\r":
            found.append((line, "control character %r" % c))
        elif c == "\r" and text[i + 1:i + 2] != "\n":
            found.append((line, "a carriage return that is not part of a line ending"))
        i += 1
    return found


def own_cxx_problems() -> list:
    found = []
    for folder in existing_folders():
        src = ROOT / folder / "src"
        if not src.is_dir():
            continue
        for p in sorted(src.rglob("*")):
            if p.suffix not in (".cpp", ".h", ".mm") or not p.is_file():
                continue
            try:
                text = p.read_bytes().decode("utf-8")
            except UnicodeDecodeError as err:
                found.append("%s/src/%s is not valid UTF-8 (%s)" % (folder, p.relative_to(src).as_posix(), err))
                continue
            for line, what in cxx_byte_problems(text)[:3]:
                found.append("%s/src/%s:%d: %s" % (folder, p.relative_to(src).as_posix(), line, what))
    return found


def problems() -> list:
    """Every rule of the series that is broken now, as sentences."""
    found = []
    listed, present = series_folders(), existing_folders()
    if sorted(listed) != present:
        found.append("SERIES and the folders differ: only in SERIES %s, only on disk %s"
                     % (sorted(set(listed) - set(present)), sorted(set(present) - set(listed))))
    if listed != sorted(listed, key=layout.folder_sort_key):
        found.append("SERIES is not in layout.GROUP_ORDER order")
    budget = json.loads(BUDGET.read_text(encoding="utf-8"))
    removed_budget = json.loads(REMOVED_BUDGET.read_text(encoding="utf-8"))
    seen = {}
    for folder in present:
        d = ROOT / folder
        if not (d / "FEATURE.md").exists():
            found.append("%s has no FEATURE.md" % folder)
        manifest = json.loads((d / "MANIFEST.json").read_text(encoding="utf-8"))
        for path in manifest["added"]:
            if not (d / "src" / path).is_file():
                found.append("%s: MANIFEST lists %s, src/ does not have it" % (folder, path))
        if (d / "src").exists():
            on_disk = {str(p.relative_to(d / "src")).replace("\\", "/")
                       for p in (d / "src").rglob("*") if p.is_file()}
            for extra in sorted(on_disk - set(manifest["added"])):
                found.append("%s: src/%s is not in its MANIFEST" % (folder, extra))
        patch = d / "hooks.patch"
        touched = added_lines(patch) if patch.exists() else {}
        removed = removed_lines(patch) if patch.exists() else {}
        if sorted(touched) != sorted(manifest["modified"]):
            found.append("%s: hooks.patch touches %s, MANIFEST owns %s"
                         % (folder, sorted(touched), manifest["modified"]))
        upstream_code = {r["file"] for r in manifest.get("inventory", []) if r["category"] == "backport"}
        found += backport_problems(folder, upstream_code, patch)
        for path, n in touched.items():
            if path in seen:
                found.append("%s is patched by both %s and %s" % (path, seen[path], folder))
            seen[path] = folder
            if path in upstream_code:
                if path in budget or path in removed_budget:
                    found.append("%s (%s) is upstream code (category backport): it has no hook or "
                                 "removed budget, take it out of both" % (path, folder))
                continue
            allowed = budget.get(path)
            if allowed is None:
                found.append("%s (%s) is a Mozilla file with no hook budget: a new hook is at most 5 "
                             "lines; add it to tools/hook-budget.json with its real count" % (path, folder))
            elif n > allowed:
                found.append("%s (%s) carries %d of our lines, its budget is %d: move the logic "
                             "into a file of ours and leave a hook" % (path, folder, n, allowed))
            r, r_allowed = removed.get(path, 0), removed_budget.get(path, 0)
            if r > r_allowed:
                found.append("%s (%s) loses or has rewritten %d of Mozilla's lines, its removed "
                             "budget is %d: leave Mozilla's lines as they are and put the hook "
                             "beside them" % (path, folder, r, r_allowed))
    for path in sorted(set(budget) - set(seen)):
        found.append("tools/hook-budget.json still lists %s, which no patch touches: remove it" % path)
    for path in sorted(set(removed_budget) - set(seen)):
        found.append("tools/removed-budget.json still lists %s, which no patch touches: remove it"
                     % path)
    patches = {f: (ROOT / f / "hooks.patch").read_text(encoding="utf-8", errors="replace")
               for f in present if (ROOT / f / "hooks.patch").exists()}
    records = json.loads(INVENTORY.read_text(encoding="utf-8"))
    found += hook_tag_problems(set(listed), records, patches)
    counts = {}
    for f in present:
        patch = ROOT / f / "hooks.patch"
        if patch.exists():
            added, removed, hunks = added_lines(patch), removed_lines(patch), hunk_counts(patch)
            counts.update({path: (added[path], removed.get(path, 0), hunks.get(path, 0)) for path in added})
    found += record_count_problems(records, counts)
    found += own_cxx_problems()
    found += births.ledger_problems(births.load_ledger(), set(listed))
    series_wf = {p.name: p.read_bytes() for p in WORKFLOWS_SERIES.glob("*.yml")}
    root_wf = {p.name: p.read_bytes() for p in WORKFLOWS_ROOT.glob("*.yml")}
    for name in sorted(set(series_wf) | set(root_wf) - ROOT_ONLY_WORKFLOWS):
        if series_wf.get(name) != root_wf.get(name):
            found.append(".github/workflows/%s differs from the series' copy (platform/ci/src): "
                         "edit it in the source, then export" % name)
    return found


MAIN_REF = "refs/remotes/origin/main"


def main_budget_text(name: str) -> str | None:
    """tools/<name> as origin/main has it, never from the branch; None if main does not resolve."""
    done = subprocess.run(["git", "-C", str(ROOT), "show", "origin/main:tools/" + name],
                          capture_output=True)
    return done.stdout.decode("utf-8") if done.returncode == 0 else None


def load_main_budgets() -> tuple[dict, dict]:
    """Main's hook and removed budgets. Fetches origin/main once if it is not there yet."""
    texts = [main_budget_text("hook-budget.json"), main_budget_text("removed-budget.json")]
    if None in texts:
        subprocess.run(["git", "-C", str(ROOT), "fetch", "--no-tags", "--depth=1", "origin",
                        "+refs/heads/main:" + MAIN_REF], capture_output=True)
        texts = [main_budget_text("hook-budget.json"), main_budget_text("removed-budget.json")]
    if None in texts:
        raise SystemExit("cannot read main's budgets: fetch origin main")
    return json.loads(texts[0]), json.loads(texts[1])


def load_main_realign() -> list | None:
    """The one-time realignment list as origin/main has it (never the branch's); None while main has
    none yet. Call after load_main_budgets, which makes sure origin/main is there."""
    text = main_budget_text("budget-realign-69.json")
    return json.loads(text) if text is not None else None


def realign_limits(rows) -> dict:
    """{(file, kind): line} of the rows of a realignment list."""
    return {(r["file"], r["kind"]): r["line"] for r in rows or ()}


def realign_list_problems(rows: list, main_rows: list | None) -> list:
    """The realignment list only shrinks: against main's list, a row added or a value raised fails.
    While main has no list yet (main_rows is None) the list is being introduced and is main's to review."""
    if main_rows is None:
        return []
    found = []
    now = realign_limits(main_rows)
    for r in rows:
        key = (r["file"], r["kind"])
        if key not in now:
            found.append("%s: a row of tools/budget-realign-69.json (%s) that main's list does not have: "
                         "the list only shrinks" % (r["file"], r["kind"]))
        elif r["line"] > now[key]:
            found.append("%s: tools/budget-realign-69.json %s value %d is above main's %d: the list only "
                         "shrinks" % (r["file"], r["kind"], r["line"], now[key]))
    return found


RAISE_FIELDS = ("file", "from", "to", "folder", "reason", "decided_by", "date", "test")


def load_main_raises() -> list | None:
    """The register of declared hook budget raises as origin/main has it (never the branch's); None while
    main has none yet. Call after load_main_budgets, which makes sure origin/main is there."""
    text = main_budget_text("hook-budget-raises.json")
    return json.loads(text) if text is not None else None


def raises_list_problems(rows: list, main_rows: list | None) -> list:
    """tools/hook-budget-raises.json only grows: every row of main's register is on the branch as main has
    it (none removed, none changed), and every row has its eight fields, `from` and `to` whole numbers with
    `to` above `from`, the others text that is not empty, `date` as YYYY-MM-DD."""
    found = []
    for r in rows:
        name = r.get("file") if isinstance(r, dict) else None
        if not isinstance(r, dict) or set(r) != set(RAISE_FIELDS):
            found.append("tools/hook-budget-raises.json: a row of %s does not have exactly the fields %s"
                         % (name or "no file", ", ".join(RAISE_FIELDS)))
            continue
        if not all(isinstance(r[k], str) and r[k].strip() for k in RAISE_FIELDS if k not in ("from", "to")):
            found.append("tools/hook-budget-raises.json: the row of %s has an empty field: file, folder, reason, "
                         "decided_by, date and test are all said" % name)
        elif not re.fullmatch(r"\d{4}-\d{2}-\d{2}", r["date"]):
            found.append("tools/hook-budget-raises.json: the row of %s has the date %r, not YYYY-MM-DD" % (name, r["date"]))
        if not (type(r["from"]) is int and type(r["to"]) is int and 0 <= r["from"] < r["to"]):
            found.append("tools/hook-budget-raises.json: the row of %s raises from %r to %r: two whole numbers, "
                         "`to` above `from`" % (name, r["from"], r["to"]))
    for m in main_rows or ():
        if m not in rows:
            found.append("tools/hook-budget-raises.json: main's row of %s (%r to %r) is gone or changed: the "
                         "register only grows" % (m.get("file"), m.get("from"), m.get("to")))
    return found


def new_raise_rows(rows: list, main_rows: list | None) -> list:
    """The rows of the branch's register that main's does not have: the raises this branch declares. While
    main has no register (None) nothing can be declared: the door must be on main before it is used."""
    if main_rows is None:
        return []
    return [r for r in rows if r not in main_rows]


def budget_raise_problems(hook: dict, removed: dict, main_hook: dict, main_removed: dict,
                          realign: list | None = None, raises: list | None = None) -> list:
    """Budgets only go down: a value above main's, or a new file's hook above 5 lines, is a failure.
    realign is MAIN's one-time realignment list: a file in it may reach its `line` value, no more; once
    main's own budget has reached that value the row has been consumed and main's value is the limit.
    raises are the rows the branch ADDS to tools/hook-budget-raises.json (new_raise_rows): a hook budget
    of a file main patches may go above main's only with one such row, `from` main's budget and `to` the
    branch's; a row that raises nothing, or one of a file main does not patch, is a failure too."""
    limits = realign_limits(realign)
    found = []
    declared = {}
    for r in raises or ():
        path = r.get("file")
        if path in declared:
            found.append("%s: two rows in tools/hook-budget-raises.json: one raise per file and branch" % path)
            continue
        declared[path] = r
        if path not in main_hook:
            found.append("%s: a row in tools/hook-budget-raises.json for a file main does not patch: a new file "
                         "has its 5 lines, no raise" % path)
        elif r.get("from") != main_hook[path] or r.get("to") != hook.get(path):
            found.append("%s: tools/hook-budget-raises.json raises from %r to %r, but main's budget is %d and the "
                         "branch's %s: `from` is main's, `to` the new one" % (path, r.get("from"), r.get("to"),
                                                                             main_hook[path], hook.get(path)))
    for path, n in sorted(hook.items()):
        if path in main_hook:
            limit, what = main_hook[path], "main's %d" % main_hook[path]
        else:
            limit, what = 5, "5"
        if (path, "hook") in limits and limits[(path, "hook")] > limit:
            limit, what = limits[(path, "hook")], "the realigned %d" % limits[(path, "hook")]
        if n > limit and path in declared:
            continue          # declared: its row is judged above
        if n > limit:
            if path in main_hook or what != "5":
                found.append("%s: hook budget %d is above %s: budgets only go down, move the "
                             "logic into our files" % (path, n, what))
            else:
                found.append("%s: hook budget %d for a file new to the series: a new hook is at most 5 "
                             "lines" % (path, n))
    for path, n in sorted(removed.items()):
        if path in main_hook:
            limit, what = main_removed.get(path, 0), "main's %d" % main_removed.get(path, 0)
        else:
            limit, what = 5, "5"
        if (path, "removed") in limits and limits[(path, "removed")] > limit:
            limit, what = limits[(path, "removed")], "the realigned %d" % limits[(path, "removed")]
        if n > limit:
            if path in main_hook or what != "5":
                found.append("%s: removed budget %d is above %s: budgets only go down, leave "
                             "Mozilla's lines as they are" % (path, n, what))
            else:
                found.append("%s: removed budget %d for a file new to the series: at most 5 of Mozilla's "
                             "lines, leave the rest as they are" % (path, n))
    return found


def check(source: Path | None = None, tag: str | None = None, against_main: bool = False) -> int:
    found = problems()
    if against_main:      # the CLI does; it needs git and origin/main, problems() and the tests' fakes do not
        main_hook, main_removed = load_main_budgets()
        main_realign = load_main_realign()
        main_raises = load_main_raises()
        raises = json.loads(RAISES.read_text(encoding="utf-8")) if RAISES.is_file() else []
        found += raises_list_problems(raises, main_raises)
        found += budget_raise_problems(json.loads(BUDGET.read_text(encoding="utf-8")),
                                       json.loads(REMOVED_BUDGET.read_text(encoding="utf-8")),
                                       main_hook, main_removed, main_realign, new_raise_rows(raises, main_raises))
        found += realign_list_problems(json.loads(REALIGN.read_text(encoding="utf-8")) if REALIGN.is_file() else [],
                                       main_realign)
    if source is not None and tag:
        found += backport_in_tag_problems(source, tag)
    for p in found:
        print("FAIL", p)
    if not found:
        total = sum(json.loads(BUDGET.read_text(encoding="utf-8")).values())
        gone = sum(json.loads(REMOVED_BUDGET.read_text(encoding="utf-8")).values())
        print("ok: %d folders, %d of our lines in Mozilla files, %d of Mozilla's lines removed "
              "or rewritten" % (len(series_folders()), total, gone))
    return 1 if found else 0


def shrink_budget() -> None:
    """Lowers each budget to the lines the patches carry now. Never raises one."""
    budget = json.loads(BUDGET.read_text(encoding="utf-8"))
    removed_budget = json.loads(REMOVED_BUDGET.read_text(encoding="utf-8"))
    for folder in existing_folders():
        patch = ROOT / folder / "hooks.patch"
        for path, n in (added_lines(patch) if patch.exists() else {}).items():
            if path in budget and n < budget[path]:
                print("%s: %d -> %d" % (path, budget[path], n))
                budget[path] = n
        for path, n in (removed_lines(patch) if patch.exists() else {}).items():
            if path in removed_budget and n < removed_budget[path]:
                print("%s: %d -> %d removed" % (path, removed_budget[path], n))
                removed_budget[path] = n
    write_json(BUDGET, dict(sorted(budget.items())))
    # A file that no longer removes anything leaves the removed budget: 0 is the default.
    write_json(REMOVED_BUDGET, {p: n for p, n in sorted(removed_budget.items()) if n})


def status(source: Path, head: str) -> int:
    up = upstream()
    now = git(source, "rev-parse", head).decode().strip()
    if now == up.get("exported_from"):
        print("in step: the series is %s at %s" % (head, now[:10]))
        return 0
    behind = git(source, "log", "--oneline", "%s..%s" % (up["exported_from"], head)).decode()
    print("the source moved: %s is %s, the series was exported from %s\n%s\nrun export, then verify"
          % (head, now[:10], up["exported_from"][:10], behind))
    return 1


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "births":
        return births.main(sys.argv[2:])      # its own options: --tree, --repo/--rev, --skeleton, --accept-changed, --prune, --tsv
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["status", "apply", "materialize", "export", "verify", "check",
                                        "shrink-budget", "drift", "port", "births"])
    ap.add_argument("--to", help="drift/port: the Mozilla tag to move to (a stable release, never a beta)")
    ap.add_argument("--into", type=Path, default=Path("."), help="materialize: the directory to make the tree")
    ap.add_argument("--shared", type=Path, default=None,
                    help="materialize: a directory every leg of this machine reaches; the tag is fetched "
                         "and the series applied there once, and each leg borrows the objects")
    ap.add_argument("--source", type=Path, default=Path(os.environ.get("ENGINE_SOURCE", "C:/ff/source")))
    ap.add_argument("--against", help="check: also try the backports of Mozilla commits against this tag, "
                                      "found in --source (a port does it by itself)")
    ap.add_argument("--base")
    ap.add_argument("--head", help="the source branch (apply: the branch it creates)")
    ap.add_argument("--force", action="store_true", help="apply: rebuild an existing branch")
    a = ap.parse_args()
    up = upstream()
    base, head = a.base or up["mozilla_tag"], a.head or up["source_branch"]
    if a.command in ("drift", "port"):
        if not a.to:
            raise SystemExit("%s needs --to <Mozilla tag>" % a.command)
        if a.command == "drift":
            return drift(a.source, base, a.to)
        return port(a.source, base, a.to, a.head if a.head else "port/%s" % a.to, a.force, check_births=True)
    if a.command == "materialize":
        materialize(a.into, shared=a.shared)
        return 0
    if a.command == "apply":
        apply(a.source, base, head, a.force)
        return 0
    if a.command == "check":
        return check(a.source, a.against or None, against_main=True)
    if a.command == "shrink-budget":
        shrink_budget()
        return 0
    if a.command == "status":
        return status(a.source, head)
    if a.command == "export":
        # The tests the build job runs first, on the whole tree of the head, before a byte is written (tools/export_gate.py).
        import export_gate
        export_gate.gate(a.source, head)
        export(a.source, base, head)
        return 0
    return verify(a.source, base, head)


if __name__ == "__main__":
    sys.exit(main())
