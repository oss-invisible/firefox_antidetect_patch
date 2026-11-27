"""series-02: the range-diff of a port. What the move to a new Mozilla tag did to every folder of the series, in one file.

    python tools/engine.py range-diff --source <repo with the tags> [--old-series <git ref>] [--fetch] [--write | --check]
    python tools/engine.py range-diff --decide [--old-series <git ref>]        is this a port? (the CI job asks before it fetches anything)

The old series is the one at `--old-series` (default origin/main), on its own `mozilla_tag`; the new one is this repository's, on its own.
Each is built as a layer stack (`engine.build_stack`: the tag, then one commit per folder of SERIES), and

    git range-diff <old tag>..<old stack> <new tag>..<new stack>

says, folder by folder, which layers are the same patch (`=`), which changed (`!`, with what changed in the patch: the context lines
Mozilla moved, a hook that was rewritten) and which are new or gone. It is written to ONE file, `ports/range-diff.txt`, whose first line
is `<OLD_TAG>..<NEW_TAG>`; every port replaces it (`--write`), and the job `range-diff` of checks.yml regenerates it on a port pull
request and is red when it is missing, stale, or for another pair of tags (`--check`). Nothing else is written, and the same input gives
the same bytes on every machine: the layers are dated with their tag's commit date (engine.build_stack), the commit ids are shown
with a fixed number of digits, and no configuration of the machine reaches git (no color, no renames, one diff algorithm).

NO TREE IS MATERIALIZED. `--fetch` makes --source a partial clone of Mozilla's repository (tools/churn.py does the same for the churn):
each of the two tags one commit deep, with its trees and no file content (`--filter=blob:none`), and then the content of the files the
series patches at their tag, by the shas the trees give: the files of the two series' hooks.patch, nothing else. That is every blob the
stack reads: `apply --cached` reads the files it patches (a bare repository takes no attributes from the files it does not have),
`read-tree` and `commit-tree` read trees, `write-tree --missing-ok` does not look for the blobs of the files it does not touch (without the
flag it asks for the blob of every file of each directory it rewrites), and `range-diff` reads the patched files at their tag and the new
ones the stack wrote itself. GIT_NO_LAZY_FETCH is set while the stack is built: an object the repository lacks is an error that names the
fix, never a fetch of one blob at a time.
Each stack is checked against the series that made it: the tree of its last layer is the `exported_tree` of that series' UPSTREAM.json
(`engine.py materialize` checks the same), so a tag that is not the release the series was exported on is red here.

Without `--fetch` a repository that already has the tags (a full one) is only read.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import churn  # noqa: E402
import folders  # noqa: E402
from failure import fail  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = "ports/range-diff.txt"
ABBREV = "12"          # digits of a commit id in the file: fixed, not the repository's own count of objects
RULE_ID = "series-02-every-folder-states-its-relation-to-mozilla"


class RangeDiffError(Exception):
    """Something the caller can fix: a missing tag, a missing file, a series that does not apply."""


def failed(where: str, what: str, fix: str):
    """One problem of the range-diff as a Failure (where, what, fix, rule: tools/failure.py), which prints as FAIL where: what. Fix: fix. Rule: path."""
    return fail(where, what, fix, RULE_ID)


class Series:
    """One side of the range-diff: a series root (a directory), its tag and the tree it declares for it."""

    def __init__(self, root, label: str):
        self.root, self.label = Path(root), label
        try:
            up = json.loads((self.root / "UPSTREAM.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RangeDiffError(failed("%s UPSTREAM.json" % label, "it cannot be read (%s)" % exc, "restore it: the series names its tag there"))
        self.tag, self.tree = up.get("mozilla_tag"), up.get("exported_tree")
        self.url = up.get("mozilla_repository")
        if folders.release_version(self.tag) is None or not self.tree:
            raise RangeDiffError(failed("%s UPSTREAM.json" % label, "mozilla_tag and exported_tree are both needed (%r, %r)" % (self.tag, self.tree),
                                     "run python tools/engine.py export: it writes exported_tree"))
        self.folders = folders.series_folders(self.root)

    def patched(self) -> list:
        """The Mozilla files of every hooks.patch of the series."""
        found = set()
        for folder in self.folders:
            patch = self.root / folder / "hooks.patch"
            if patch.is_file():
                found.update(fd["path"] for fd in churn.parse_patch(patch.read_bytes()))
        return sorted(found)

    def paths(self) -> list:
        """What the stack reads at the tag: the patched files."""
        return self.patched()


# --------------------------------------------------------------------------- the old series, from a git ref
def _git(root, *args, input_bytes=None) -> bytes:
    done = subprocess.run(["git", "-C", str(root), *args], capture_output=True, input=input_bytes)
    if done.returncode:
        raise RangeDiffError(failed("git %s" % " ".join(args), done.stderr.decode(errors="replace").strip() or "it failed",
                                 "give --old-series a ref this repository has (git fetch --depth=1 origin +refs/heads/main:refs/remotes/origin/main)"))
    return done.stdout


def read_ref_file(root, ref: str, path: str) -> bytes:
    return _git(root, "show", "%s:%s" % (ref, path))


def extract_ref(root, ref: str, into: Path) -> Path:
    """The files of the series at `ref` that the stack reads (SERIES, UPSTREAM.json, and per folder hooks.patch, MANIFEST.json and src/),
    read from the git objects byte for byte (no archive: no conversion of line endings), written into the directory `into`."""
    listed = read_ref_file(root, ref, "SERIES").decode("utf-8").split()
    shas = {}
    for rec in _git(root, "ls-tree", "-r", "-z", ref).split(b"\0"):
        meta, _, name = rec.partition(b"\t")
        parts = meta.split()
        if len(parts) != 3 or parts[1] != b"blob":
            continue
        path = name.decode("utf-8")
        if path in ("SERIES", "UPSTREAM.json") or any(path in (f + "/hooks.patch", f + "/MANIFEST.json") or path.startswith(f + "/src/")
                                                      for f in listed):
            shas[path] = parts[2].decode()
    order = sorted(shas)
    blob = _git(root, "cat-file", "--batch", input_bytes=("\n".join(shas[p] for p in order) + "\n").encode())
    at = 0
    for p in order:
        end = blob.index(b"\n", at)
        size = int(blob[at:end].split()[2])
        data = blob[end + 1:end + 1 + size]
        at = end + 1 + size + 1
        target = Path(into) / p
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return Path(into)


# --------------------------------------------------------------------------- the fetch
def fetch(source, series: "Series", old: "Series", url=None, say_=lambda m: print(m, file=sys.stderr), sleep=time.sleep) -> None:
    """Fills `source` (a bare repository of its own, made when it is not one yet) with what the stacks read: each tag one commit deep
    without file content, then the files `Series.paths` names at their tag. What is there is not fetched."""
    url = url or series.url
    if (Path(source) / ".git").exists():
        raise RangeDiffError(failed("%s" % source, "--fetch would make a working repository a partial clone of Mozilla's",
                                 "give --fetch a directory of its own (a bare repository is made there); a repository that already has the tags needs no --fetch"))
    churn.partial_clone(source, url)
    for side in (old, series):
        if churn.commit_of(source, side.tag) is None:
            began = time.monotonic()
            churn.fetch_tag(source, side.tag, url, say_, sleep)
            say_("%s: fetched in %.0f s" % (side.tag, time.monotonic() - began))
        else:
            say_("%s: in the repository" % side.tag)
        churn.fetch_blobs(source, [side.tag], side.paths(), say_, sleep)


# --------------------------------------------------------------------------- the stacks
@contextlib.contextmanager
def no_lazy_fetch():
    """No fetch of an object by git behind our back while a stack is built (the same switch as churn.git's)."""
    before = os.environ.get("GIT_NO_LAZY_FETCH")
    os.environ["GIT_NO_LAZY_FETCH"] = "1"
    try:
        yield
    finally:
        if before is None:
            del os.environ["GIT_NO_LAZY_FETCH"]
        else:
            os.environ["GIT_NO_LAZY_FETCH"] = before


def require_content(source, side: "Series") -> None:
    """The tag is in `source`, and every file the stack reads at it has its content: where / what / fix / rule."""
    where = "%s (%s)" % (source, side.label)
    if churn.commit_of(source, side.tag) is None:
        raise RangeDiffError(failed(where, "the repository lacks the tag %s" % side.tag,
                                 "python tools/engine.py range-diff --source %s --fetch --old-series <ref> (it fetches both tags, one commit deep, "
                                 "and the files the two series patch)" % source))
    blobs = churn.tree_blobs(source, [side.tag], side.paths())
    gone = churn.missing_blobs(source, blobs.values())
    lost = sorted(p for (_, p), sha in blobs.items() if sha in gone)
    if lost:
        raise RangeDiffError(failed(where, "%d file(s) of %s have no content in the repository (first: %s): it was fetched for another set of files"
                                 % (len(lost), side.tag, lost[0]),
                                 "python tools/engine.py range-diff --source %s --fetch (it fetches the content of every file the series patch)" % source))


def stack(source, side: "Series", build_stack) -> tuple:
    """(commit of the tag, commit of the last layer) of the series on its tag, from objects only; the last layer's tree must be the one the
    series declares."""
    require_content(source, side)
    try:
        with no_lazy_fetch():
            layers = build_stack(Path(source), side.tag, root=side.root, missing_ok=True)
    except SystemExit as exc:
        raise RangeDiffError(failed("%s of %s" % (side.label, side.tag), str(exc.code).strip(),
                                 "the series does not apply on that tag: it is not the release it was exported on, or an object is missing "
                                 "(--fetch)"))
    except subprocess.CalledProcessError as exc:
        raise RangeDiffError(failed("%s of %s" % (side.label, side.tag), (exc.stderr or b"").decode(errors="replace").strip() or str(exc),
                                 "an object the stack reads is not in the repository: python tools/engine.py range-diff --source %s --fetch" % source))
    if layers[-1][2] != side.tree:
        raise RangeDiffError(failed("%s UPSTREAM.json of %s" % (side.label, side.tag),
                                 "the series applied on the tag %s of %s gives the tree %s, UPSTREAM.json declares %s"
                                 % (side.tag, source, layers[-1][2], side.tree),
                                 "the repository's tag is not the release the series was exported on (a retag, another repository), or the "
                                 "series was not exported after its last change: python tools/engine.py export"))
    return layers[0][1], layers[-1][1]


GIT_FIXED = ("-c", "safe.bareRepository=all", "-c", "color.ui=never", "-c", "diff.renames=false", "-c", "diff.algorithm=default", "-c", "diff.context=3",
             "-c", "diff.interHunkContext=0", "-c", "diff.indentHeuristic=true", "-c", "core.quotepath=off", "-c", "core.abbrev=" + ABBREV,
             "-c", "i18n.logOutputEncoding=UTF-8")


def git_range_diff(source, old_tag: str, old_head: str, new_tag: str, new_head: str) -> bytes:
    env = dict(os.environ, GIT_NO_LAZY_FETCH="1", GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_PAGER="cat", LC_ALL="C")
    done = subprocess.run(["git", "-C", str(source), *GIT_FIXED, "range-diff", "--no-color", "%s..%s" % (old_tag, old_head),
                           "%s..%s" % (new_tag, new_head)], capture_output=True, env=env)
    if done.returncode:
        raise RangeDiffError(failed("git range-diff in %s" % source, done.stderr.decode(errors="replace").strip() or "it failed",
                                 "an object a layer needs is not in the repository: python tools/engine.py range-diff --source %s --fetch" % source))
    return done.stdout


def first_line(old_tag: str, new_tag: str) -> str:
    return "%s..%s" % (old_tag, new_tag)


def compute(series: "Series", old: "Series", source, build_stack) -> bytes:
    """The bytes of ports/range-diff.txt: `<OLD>..<NEW>`, a newline, and git's range-diff of the two stacks."""
    old_tag, old_head = stack(source, old, build_stack)
    new_tag, new_head = stack(source, series, build_stack)
    return (first_line(old.tag, series.tag) + "\n").encode("utf-8") + git_range_diff(source, old_tag, old_head, new_tag, new_head)


# --------------------------------------------------------------------------- the file and the check
def decide(old_tag: str, new_tag: str) -> tuple:
    """(is a port, the sentence that says why): a pull request is a port when it moves mozilla_tag away from main's."""
    if old_tag == new_tag:
        return False, "not a port: mozilla_tag is %s on both sides, there is nothing to compare" % new_tag
    return True, "a port: mozilla_tag moves from %s to %s, ports/range-diff.txt must be for %s" % (old_tag, new_tag, first_line(old_tag, new_tag))


def check(root, expected: bytes, old_tag: str, new_tag: str) -> list:
    """The problems of the committed ports/range-diff.txt against what the two series give now (`expected`); [] when it is that, byte for byte."""
    path = Path(root) / OUT
    if not path.is_file():
        return [failed(OUT, "the file is missing: a port carries the range-diff of the series",
                    "python tools/engine.py range-diff --source <repo> --old-series origin/main --write, and commit it")]
    have = path.read_bytes()
    want_first = first_line(old_tag, new_tag)
    head = have.split(b"\n", 1)[0].decode("utf-8", "replace").rstrip("\r")
    if head != want_first:
        return [failed(OUT, "its first line is %r, the pair of tags of this port is %r (main's tag, this series' tag)" % (head, want_first),
                    "python tools/engine.py range-diff --source <repo> --old-series origin/main --write: the file is replaced at every port")]
    if have == expected:
        return []
    old_lines, new_lines = have.decode("utf-8", "replace").split("\n"), expected.decode("utf-8", "replace").split("\n")
    differ = [i for i in range(max(len(old_lines), len(new_lines)))
              if (old_lines[i] if i < len(old_lines) else None) != (new_lines[i] if i < len(new_lines) else None)]
    shown = ["  line %d: committed %r, now %r" % (i + 1, old_lines[i] if i < len(old_lines) else None, new_lines[i] if i < len(new_lines) else None)
             for i in differ]
    return [failed(OUT, "the file is stale: it is not what the two series give now (%d lines differ, all below)\n%s" % (len(differ), "\n".join(shown)),
                   "python tools/engine.py range-diff --source <repo> --old-series origin/main --write, and commit it")]


def main(argv, build_stack) -> int:
    ap = argparse.ArgumentParser(prog="engine.py range-diff", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", type=Path, help="a repository that has the two Mozilla tags (--fetch makes it, a bare repository of its own)")
    ap.add_argument("--old-series", default="origin/main", help="the git ref of the old series (default origin/main)")
    ap.add_argument("--series", type=Path, default=ROOT, help="the series root (default: this repository)")
    ap.add_argument("--fetch", action="store_true", help="fetch the two tags and the files the stacks read into --source (a partial clone)")
    ap.add_argument("--write", action="store_true", help="write ports/range-diff.txt (else print the file's bytes)")
    ap.add_argument("--check", action="store_true", help="red unless ports/range-diff.txt is what the two series give now, byte for byte")
    ap.add_argument("--decide", action="store_true", help="print `port=true|false` and the reason: a port moves mozilla_tag away from the old series'")
    a = ap.parse_args(argv)
    try:
        if a.decide:
            old_tag = json.loads(read_ref_file(a.series, a.old_series, "UPSTREAM.json").decode("utf-8")).get("mozilla_tag")
            new_tag = folders.mozilla_tag(a.series)
            port, why = decide(old_tag, new_tag)
            print("port=%s" % ("true" if port else "false"))
            print("decision=%s" % why)
            return 0
        if a.source is None:
            print(fail("python tools/engine.py range-diff", "--source is not given",
                       "add --source <repo>, a repository that has the two Mozilla tags (--fetch makes it)", RULE_ID), file=sys.stderr)
            return 2
        import tempfile
        # a scratch directory that cannot be removed (a file in it is still held by a scanner, an indexer, another git: Windows refuses) is
        # left behind; it is never the reason the file that was computed is given up
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            old_root = extract_ref(a.series, a.old_series, Path(tmp) / "old")
            series, old = Series(a.series, "this series"), Series(old_root, "the old series (%s)" % a.old_series)
            if a.fetch:
                fetch(a.source, series, old)
            data = compute(series, old, a.source, build_stack)
        if a.check:
            found = check(a.series, data, old.tag, series.tag)
            for p in found:
                print(p, file=sys.stderr)
            if not found:
                print("ok: %s is the range-diff of %s" % (OUT, first_line(old.tag, series.tag)))
            return 1 if found else 0
        if a.write:
            target = Path(a.series) / OUT
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            print("wrote %s (%s, %d bytes)" % (OUT, first_line(old.tag, series.tag), len(data)))
            return 0
        sys.stdout.buffer.write(data)
        return 0
    except (RangeDiffError, churn.ChurnError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
