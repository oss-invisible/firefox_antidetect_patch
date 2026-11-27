"""The churn of every hunk of the series: in how many of the last eight Mozilla releases did a line change near it.

A hunk of a hooks.patch touches a span of Mozilla lines (a pure insertion touches the two lines it sits
between). Its REGION is that span plus PAD lines on each side. The region is first put in the coordinates
of the pure Mozilla file at the base tag (lines added by the earlier folders of SERIES in the same file are
not Mozilla's and are skipped), then walked back through `git diff -U0` of every pair of consecutive
release tags: an interval counts when some diff hunk overlaps the region, and the region is moved into the
older file's coordinates before the next interval. A file that does not exist in the older release counts
as changed in the interval where it appears. The churn of a hunk is the number of intervals that count.

    python tools/churn.py --source <firefox repo> --base FIREFOX_159_0_RELEASE [--releases <tag,...>] [--write]
    python tools/churn.py --source <firefox repo> --check          the committed tools/churn.json is what the series gives now
    python tools/churn.py --source <repo> --fetch                  what the churn reads, into <repo>: the nine tags one commit deep without file
                                                                   content, then the content of the files the series patches (tens of megabytes)
    python tools/churn.py --cache-key                              the key of the commits and of those files (a cache's)

--releases is the chain of release tags, oldest first, ending with the base: eight intervals are nine tags
(default: the eight releases before the base, `FIREFOX_<N>_0_RELEASE`). The tags must exist in --source; a
missing one is named with the command that fetches it, nothing is fetched by the compute (`--fetch` does it). The compute reads the trees of
the tags and the content of the files the series patches, nothing else; a file that is in a tag's tree and whose content the repository lacks is an
error, never an absent file and never a churn of 0 (the repository was fetched for another set of files: `--fetch`).
Every tag is also a commit: tools/churn.json records it, and a tag of the source that resolves to another commit
(a moved tag, another repository) is red, in the compute, in `--check` and in `--fetch`.

--check recomputes at the base and the tags the committed file names and compares the bytes; a difference is red and
names the hunks that differ (a port, a hook moved or added, a constant changed: `--write` and commit).

tools/churn.json: {"base", "releases": [{tag, commit}], "band", "hooks": [{key, folder, file, hunk, churn, which}]}
sorted by folder, file, hunk; the same input gives the same bytes on every machine. The key is the one of
tools/hook_contract.py (rule|folder|file|function|sha1(normalized text)[:12]) with the rule `H` and the
changed lines of the hunk as the text: no line number, so a hunk that only moved keeps its key. A hunk of a
backport folder is in the file with its folder (it is not a hook). `band`: a hunk is in the band when its
churn is at least that many (BAND_MIN_CHURN).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hook_contract  # noqa: E402
from failure import fail  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RULE_ID = "port-07-quiet-anchors"
OUTPUT = ROOT / "tools" / "churn.json"
PAD = 3                  # lines of Mozilla's code either side of a hunk that count as "near" it
WINDOW = 8               # releases (intervals) looked back from the base
BAND_MIN_CHURN = 2       # a hunk is in the band when this many of the intervals changed near it

HUNK_HEADER = re.compile(rb"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@ ?(.*)$")
TAG = re.compile(r"^FIREFOX_(\d+(?:_\d+)*)_RELEASE$")
PATH_BATCH = 24000       # bytes of paths on one command line
FETCH_WAITS = (5, 15, 45)   # seconds before each new try of a fetch from Mozilla's repository
BLOB_BATCH = 300         # files asked for in one fetch


class ChurnError(Exception):
    """Something the caller can fix: a missing tag, a patch that does not apply. Its text is the text of a fail()."""


def failed(where: str, what: str, fix: str):
    """One problem of the churn as a Failure (where, what, fix, rule: tools/failure.py), which prints as FAIL where: what. Fix: fix. Rule: path.

    The lines `say(...)` of the fetch (`the fetch of the files failed, again in 5 s`) and the `warning:` lines of --check are WARN-level
    progress and notes: the run goes on after each, so they are not failures and are not built here."""
    return fail(where, what, fix, RULE_ID)


# --------------------------------------------------------------------------- tags
def release_label(tag: str) -> str:
    """FIREFOX_152_0_RELEASE -> 152, FIREFOX_160_0_1_RELEASE -> 160.0.1"""
    m = TAG.match(tag)
    if not m:
        return tag
    parts = m.group(1).split("_")
    if len(parts) > 1 and parts[-1] == "0" and len(parts) == 2:
        parts = parts[:1]
    return ".".join(parts)


def default_releases(base: str) -> list:
    """The chain of the eight releases before `base`, base last: FIREFOX_151_0_RELEASE .. FIREFOX_159_0_RELEASE."""
    m = re.match(r"^FIREFOX_(\d+)_0_RELEASE$", base)
    if not m:
        raise ChurnError(failed("tools/churn.py --base %s" % base, "the earlier releases of %s cannot be derived: it is not FIREFOX_<N>_0_RELEASE" % base,
                                "pass --releases <tag,...>, the chain of release tags oldest first, ending with the base"))
    n = int(m.group(1))
    return ["FIREFOX_%d_0_RELEASE" % i for i in range(n - WINDOW, n + 1)]


def git(source, *args, check=True, input_bytes=None) -> subprocess.CompletedProcess:
    # GIT_NO_LAZY_FETCH: the repository of the tags holds the commits and trees of the nine tags and the files the series patches, nothing
    # else; an object it lacks is an error here, never a silent fetch (and never a file that reads as absent).
    done = subprocess.run(["git", "--literal-pathspecs", "-C", str(source), "-c", "core.quotepath=off", "-c", "safe.bareRepository=all",
                           *args], capture_output=True, input=input_bytes, env=dict(os.environ, GIT_NO_LAZY_FETCH="1"))
    if check and done.returncode:
        raise ChurnError(failed("git %s in %s" % (" ".join(args), source), "git exited with %d: %s"
                                % (done.returncode, done.stderr.decode(errors="replace").strip()),
                                "run the same git command by hand in that repository and read its error; if an object is missing, python "
                                "tools/churn.py --source %s --fetch fetches the tags and the files the churn reads" % source))
    return done


def mozilla_repository(root=None) -> str:
    try:
        return json.loads((Path(root or ROOT) / "UPSTREAM.json").read_text(encoding="utf-8"))["mozilla_repository"]
    except (OSError, ValueError, KeyError):
        return "<the Mozilla repository>"


def check_tags(source, tags: list) -> None:
    """Every tag must be in the source; says which are not and how to fetch them, fetches nothing."""
    missing = [t for t in tags
               if git(source, "rev-parse", "-q", "--verify", "refs/tags/%s^{commit}" % t, check=False).returncode]
    if missing:
        url = mozilla_repository()
        raise ChurnError(failed(str(source), "the source repository lacks the tags: %s" % ", ".join(missing),
                                "fetch each with: git -C %s fetch --depth=1 %s refs/tags/<tag>:refs/tags/<tag>, or python tools/churn.py --source %s "
                                "--fetch (a directory of its own) for all of them" % (source, url, source)))


def commit_of(source, tag: str):
    """The commit a tag resolves to in the source, or None."""
    done = git(source, "rev-parse", "-q", "--verify", "refs/tags/%s^{commit}" % tag, check=False)
    return done.stdout.decode().strip() if done.returncode == 0 else None


def check_commits(source, expected: dict) -> None:
    """Every tag the file records resolves, in the source, to the commit recorded: a tag does not move, so another commit is
    another repository or a retagged release, and every number computed on it would be meaningless."""
    found = {t: commit_of(source, t) for t in expected}
    wrong = [(t, c, found[t]) for t, c in expected.items() if found[t] not in (None, c)]
    if wrong:
        raise ChurnError(failed("tools/churn.json", "the tags of the source are not the releases it recorded: %s"
                                % "; ".join("%s is %s in the source, %s in tools/churn.json" % (t, got, c) for t, c, got in wrong),
                                "use a --source that is a clone of the Mozilla repository the series names (a tag does not move: another commit is another "
                                "repository or a retagged release), and never --write over it"))


def recorded(data: dict) -> dict:
    """tag -> commit of the releases of a churn.json (its `releases` is [{tag, commit}])."""
    try:
        return {r["tag"]: r["commit"] for r in data["releases"]}
    except (TypeError, KeyError):
        raise ChurnError(failed("tools/churn.json", "the `releases` is not a list of {tag, commit}",
                                "python tools/churn.py --source <repo with the tags> --write, and commit the file"))


def load_committed(path=None):
    """The committed tools/churn.json (or the file at `path`) as data."""
    path = Path(path or OUTPUT)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        raise ChurnError(failed("tools/churn.json", "the file is missing", "python tools/churn.py --source <repo> --base <tag> --write, and commit it"))
    except ValueError as exc:
        raise ChurnError(failed("tools/churn.json", "the file is not JSON (%s)" % exc,
                                "python tools/churn.py --source <repo with the tags> --write rewrites it, and commit the file"))


def series_paths(root) -> list:
    """The Mozilla files whose content the churn reads: every file of every hooks.patch of SERIES (so a new hook file is covered) and
    every file tools/churn.json lists (so is one a hook left)."""
    root, paths = Path(root), set()
    for folder in series_folders(root):
        patch = root / folder / "hooks.patch"
        if patch.is_file():
            paths.update(fd["path"] for fd in parse_patch(patch.read_bytes()))
    try:
        paths.update(h["file"] for h in json.loads((root / "tools" / "churn.json").read_text(encoding="utf-8"))["hooks"])
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return sorted(paths)


def cache_key(data: dict, paths: list) -> str:
    """A key for what the repository of the tags holds: the commits, in the order of the chain (not the names of the tags), and the
    set of files whose content it has: a new hook file is another key."""
    text = "\n".join(r["commit"] for r in data["releases"]) + "\n--\n" + "\n".join(sorted(set(paths)))
    return hashlib.sha256(text.encode()).hexdigest()[:32]


def tree_blobs(source, tags: list, paths: list) -> dict:
    """(tag, path) -> blob sha of every file of `paths` that is in the tree of the tag: from the trees alone, no content."""
    out = {}
    paths = sorted(set(paths))
    for tag in tags:
        batch, size = [], 0
        for p in paths + [None]:
            if p is None or size + len(p) + 1 > PATH_BATCH:
                if batch:
                    for rec in git(source, "ls-tree", "-r", "-z", tag, "--", *batch).stdout.split(b"\0"):
                        meta, _, name = rec.partition(b"\t")
                        parts = meta.split()
                        if len(parts) == 3 and parts[1] == b"blob":
                            out[(tag, name.decode("utf-8", "replace"))] = parts[2].decode()
                batch, size = [], 0
            if p is not None:
                batch.append(p)
                size += len(p) + 1
    return out


def missing_blobs(source, shas) -> list:
    """The shas, of those given, whose object the repository does not have."""
    shas = sorted(set(shas))
    if not shas:
        return []
    rows = git(source, "cat-file", "--batch-check", input_bytes=("\n".join(shas) + "\n").encode()).stdout.decode().splitlines()
    return [sha for sha, row in zip(shas, rows) if row.endswith(" missing")]


def require_present(source, blobs: dict) -> None:
    """Every file of the tags the churn reads has its content in the repository: where / what / fix / rule. A file whose content is
    absent must never read as 'not there' (it would count as a change and give a churn that is not Mozilla's)."""
    gone = set(missing_blobs(source, blobs.values()))
    lost = sorted("%s:%s" % k for k, sha in blobs.items() if sha in gone)
    if lost:
        raise ChurnError(failed(str(source), "%d file(s) of the Mozilla tags have no content in the repository (first: %s): the repository was fetched "
                                "for another set of files" % (len(lost), lost[0]),
                                "python tools/churn.py --source %s --fetch (it fetches the content of every file the series patches)" % source))


def batches(items: list, size: int):
    """`items` in lists of at most `size`."""
    for i in range(0, len(items), size):
        yield items[i:i + size]


REMOTE = "mozilla"       # the remote of the repository of the tags: a partial clone of it (promisor), so that a file can be asked for by its sha


def partial_clone(source, url: str) -> None:
    """Makes `source` a partial clone of `url` (made bare when it is not a repository yet): git accepts the objects it asks for by sha
    (`fetch --stdin`) only from a promisor remote. Idempotent."""
    source = Path(source)
    if not (source / "objects").is_dir() and not (source / ".git").exists():
        source.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-q", "--bare", str(source)], check=True)
    for key, value in (("core.repositoryformatversion", "1"), ("extensions.partialclone", REMOTE), ("remote.%s.url" % REMOTE, url),
                       ("remote.%s.promisor" % REMOTE, "true"), ("remote.%s.partialclonefilter" % REMOTE, "blob:none"),
                       ("remote.%s.fetch" % REMOTE, "+refs/heads/*:refs/remotes/%s/*" % REMOTE)):
        git(source, "config", key, value)


def fetch_blobs(source, tags: list, paths: list, say=print, sleep=time.sleep) -> None:
    """The content of `paths` at every tag, by the shas the trees give, from the remote; what is there is not fetched."""
    blobs = tree_blobs(source, tags, paths)
    need = missing_blobs(source, blobs.values())
    began = time.monotonic()
    for batch in batches(need, BLOB_BATCH):
        for attempt in range(len(FETCH_WAITS) + 1):
            done = git(source, "-c", "fetch.negotiationAlgorithm=noop", "fetch", "-q", REMOTE, "--no-tags", "--no-write-fetch-head",
                       "--recurse-submodules=no", "--filter=blob:none", "--stdin", check=False, input_bytes=("\n".join(batch) + "\n").encode())
            if done.returncode == 0:
                break
            if attempt == len(FETCH_WAITS):
                raise ChurnError(failed("git fetch %s in %s" % (REMOTE, source), "the fetch of %d files failed after %d tries: %s"
                                        % (len(batch), len(FETCH_WAITS) + 1, done.stderr.decode(errors="replace").strip()),
                                        "check the network and the mozilla_repository of UPSTREAM.json, then run python tools/churn.py --source %s "
                                        "--fetch again (what is already fetched is kept)" % source))
            say("the fetch of the files failed, again in %d s" % FETCH_WAITS[attempt])
            sleep(FETCH_WAITS[attempt])
    require_present(source, blobs)
    say("%d files of %d tags: %d fetched in %.0f s, %d were there" % (len({v for v in blobs.values()}), len(tags), len(need), time.monotonic() - began,
                                                                  len(set(blobs.values())) - len(need)))


def fetch_tag(source, tag: str, url: str, say=print, sleep=time.sleep) -> None:
    """One release tag of the remote into `source` (a partial clone, see `partial_clone`): its commit one deep and its trees, no file
    content, tried again after FETCH_WAITS. The caller says which commit it must be (`churn.fetch` against tools/churn.json,
    tools/range_diff.py against the tree the series declares)."""
    for attempt in range(len(FETCH_WAITS) + 1):
        done = git(source, "fetch", "-q", "--depth=1", "--no-tags", "--filter=blob:none", REMOTE,
                   "refs/tags/%s:refs/tags/%s" % (tag, tag), check=False)
        if done.returncode == 0:
            return
        if attempt == len(FETCH_WAITS):
            raise ChurnError(failed("git fetch %s %s" % (url, tag), "the fetch of the tag failed after %d tries: %s"
                                    % (len(FETCH_WAITS) + 1, done.stderr.decode(errors="replace").strip()),
                                    "check the network and the mozilla_repository of UPSTREAM.json, then run python tools/churn.py --source %s "
                                    "--fetch again (what is already fetched is kept)" % source))
        say("%s: the fetch failed, again in %d s" % (tag, FETCH_WAITS[attempt]))
        sleep(FETCH_WAITS[attempt])


def fetch(source, data: dict, paths: list, url=None, say=print, sleep=time.sleep) -> None:
    """Fills `source` (a repository, made bare when it is not one yet) with what the churn reads, from `url` (default: the Mozilla
    repository of UPSTREAM.json): every release tag of `data` as a commit and its trees, one commit deep and without file content, each
    required to be the commit recorded; then the content of `paths` at every tag, and nothing else (a few tens of megabytes, not the
    gigabyte of a whole tree). What is already there is not fetched: a restored cache costs a `rev-parse` per tag and a `cat-file`."""
    source = Path(source)
    url = url or mozilla_repository()
    partial_clone(source, url)
    for tag, commit in recorded(data).items():
        have = commit_of(source, tag)
        if have == commit:
            say("%s: in the repository" % tag)
            continue
        if have is not None:
            raise ChurnError(failed(str(source), "%s is %s there, tools/churn.json recorded %s" % (tag, have, commit),
                                    "use a --source directory of its own for --fetch (a repository whose tag is another commit cannot be reused), "
                                    "or restore tools/churn.json if Mozilla's release is the one in the repository"))
        began = time.monotonic()
        fetch_tag(source, tag, url, say, sleep)
        got = commit_of(source, tag)
        if got != commit:
            raise ChurnError(failed(url, "%s is %s there, tools/churn.json recorded %s" % (tag, got, commit),
                                    "the mozilla_repository of UPSTREAM.json is not the repository the churn was written from (a retag, another "
                                    "repository): point it at the right one, or rewrite tools/churn.json from the right one with --write"))
        say("%s: fetched in %.0f s" % (tag, time.monotonic() - began))
    fetch_blobs(source, list(recorded(data)), paths, say, sleep)


# --------------------------------------------------------------------------- reading a hooks.patch
def lines_of(data: bytes) -> list:
    parts = data.split(b"\n")
    out = [l + b"\n" for l in parts[:-1]]
    if parts[-1]:
        out.append(parts[-1])
    return out


def parse_patch(text: bytes) -> list:
    """-> [dict(path, deleted, hunks=[dict(os, oc, section, lines=[(tag, bytes)])])]; the bytes of a line keep
    their newline (and a carriage return), so they compare equal to the lines of the file."""
    files, cur, i = [], None, 0
    rows = text.split(b"\n")
    if rows and rows[-1] == b"":
        rows.pop()
    n = len(rows)
    while i < n:
        raw = rows[i]
        if raw.startswith(b"diff --git "):
            _, path = hook_contract._split_diff_header(raw[len(b"diff --git "):].decode("utf-8", "replace"))
            cur = {"path": path, "deleted": False, "hunks": []}
            files.append(cur)
            i += 1
            continue
        if cur is None:
            i += 1
            continue
        if not cur["hunks"] and raw.startswith(b"deleted file mode"):
            cur["deleted"] = True
        m = HUNK_HEADER.match(raw)
        if not m:
            i += 1
            continue
        oc = int(m.group(2)) if m.group(2) is not None else 1
        nc = int(m.group(4)) if m.group(4) is not None else 1
        hunk = {"os": int(m.group(1)), "oc": oc, "section": m.group(5).decode("utf-8", "replace").strip(), "lines": []}
        cur["hunks"].append(hunk)
        i += 1
        ro, rn = oc, nc
        while (ro > 0 or rn > 0) and i < n:
            raw = rows[i]
            tag = raw[:1]
            if tag == b"\\":
                i += 1
                continue
            if tag == b"+":
                rn -= 1
            elif tag == b"-":
                ro -= 1
            elif tag == b" " or raw == b"":
                ro -= 1
                rn -= 1
                tag = b" "
            else:
                break
            hunk["lines"].append((tag, raw[1:] + b"\n"))
            i += 1
        while i < n and rows[i].startswith(b"\\"):       # "\ No newline at end of file" belongs to the line before
            if hunk["lines"]:
                t, c = hunk["lines"][-1]
                hunk["lines"][-1] = (t, c[:-1] if c.endswith(b"\n") else c)
            i += 1
    return files


def sides(h: dict):
    return ([c for t, c in h["lines"] if t in (b" ", b"-")], [c for t, c in h["lines"] if t in (b" ", b"+")])


def start_index(h: dict) -> int:
    """0-based index in the old file where the old side of the hunk starts (`-N,0` names the line BEFORE the insertion)."""
    return h["os"] if h["oc"] == 0 else h["os"] - 1


def touched_span(h: dict):
    """(lo, hi): old-side line numbers (1-based) of the lines the hunk changes; an insertion: its two neighbours."""
    ln = start_index(h) + 1
    lo = hi = None
    for t, _ in h["lines"]:
        if t == b" ":
            ln += 1
        elif t == b"-":
            lo = ln if lo is None else lo
            hi = ln
            ln += 1
        else:
            lo = ln - 1 if lo is None else lo
            hi = max(hi or 0, ln)
    return lo, hi


def locate(content: list, h: dict):
    """Index in `content` where the old side of the hunk matches: the expected place, else the nearest."""
    old, _ = sides(h)
    expected = start_index(h)
    if content[expected:expected + len(old)] == old:
        return expected
    best = None
    for p in range(0, len(content) - len(old) + 1):
        if content[p:p + len(old)] == old and (best is None or abs(p - expected) < abs(best - expected)):
            best = p
    return best


def hunk_key(folder: str, path: str, h: dict) -> str:
    text = "\n".join(t.decode() + c.decode("utf-8", "replace").rstrip("\n") for t, c in h["lines"] if t != b" ")
    return hook_contract._key("H", folder, path, h["section"], text)


def keyed_hunks(folder: str, fd: dict) -> list:
    """[(number, hunk, key)] of one file of a hooks.patch: two hunks with one key are told apart by `#2`, `#3`."""
    seen, out = Counter(), []
    for no, h in enumerate(fd["hunks"], 1):
        key = hunk_key(folder, fd["path"], h)
        seen[key] += 1
        out.append((no, h, key if seen[key] == 1 else "%s#%d" % (key, seen[key])))
    return out


def hunk_keys(root) -> dict:
    """(folder, file, hunk number) -> key, of every hunk of every hooks.patch of SERIES: what tools/churn.json says about it."""
    root, out = Path(root), {}
    for folder in series_folders(root):
        patch = root / folder / "hooks.patch"
        if patch.is_file():
            for fd in parse_patch(patch.read_bytes()):
                for no, _, key in keyed_hunks(folder, fd):
                    out[(folder, fd["path"], no)] = key
    return out


# --------------------------------------------------------------------------- the regions of the series at the base tag
def series_folders(root: Path) -> list:
    return (Path(root) / "SERIES").read_text(encoding="utf-8").split()


def regions(root, base_blob, warn=None) -> list:
    """The hunks of every hooks.patch of SERIES, in SERIES order, each with its region in the coordinates of the
    pure Mozilla file at the base: [dict(folder, file, hunk, key, region)]; region is None when the file is not at
    the base (a file the series adds). `base_blob(path)` -> bytes or None, the file at the base tag.
    The folders are layered: a folder's hunks are located in the file as the folders before it left it."""
    root = Path(root)
    warn = warn if warn is not None else []
    content, mapping, out = {}, {}, []
    for folder in series_folders(root):
        patch = root / folder / "hooks.patch"
        if not patch.is_file():
            continue
        for fd in parse_patch(patch.read_bytes()):
            path = fd["path"]
            if path not in content:
                blob = base_blob(path)
                if blob is None:
                    content[path], mapping[path] = None, []
                    warn.append("%s: not in the base tag" % path)
                else:
                    content[path] = lines_of(blob)
                    mapping[path] = list(range(1, len(content[path]) + 1))
            body, m = content[path] or [], mapping[path]
            absent = content[path] is None
            newc, newm, cursor = [], [], 0
            for no, h, key in keyed_hunks(folder, fd):
                p = locate(body, h)
                if p is None:
                    warn.append("%s %s hunk %d: the old side is not in the layered file" % (folder, path, no))
                    p = start_index(h)
                elif p != start_index(h):
                    warn.append("%s %s hunk %d: offset %d" % (folder, path, no, p - start_index(h)))
                lo, hi = touched_span(h)
                shift = p - start_index(h)
                lo, hi = lo + shift, hi + shift
                region = None
                if not absent:
                    mapped = [m[x - 1] for x in range(max(1, lo - PAD), min(len(m), hi + PAD) + 1) if m[x - 1] is not None]
                    if mapped:
                        region = (min(mapped), max(mapped))
                    else:                       # every neighbour was added by an earlier folder: the nearest Mozilla line
                        below = [m[x] for x in range(max(0, lo - 1), -1, -1) if m[x] is not None][:1]
                        above = [m[x] for x in range(max(0, lo - 1), len(m)) if m[x] is not None][:1]
                        near = (below or above or [1])[0]
                        region = (near, near)
                        warn.append("%s %s hunk %d: every neighbour is added by an earlier folder, anchored at %d" % (folder, path, no, near))
                    if fd["deleted"]:
                        region = (1, max([x for x in m if x is not None] or [1]))
                out.append({"folder": folder, "file": path, "hunk": no, "key": key, "region": region})
                # the layered file after this hunk: Mozilla's lines keep their number, a line of ours has none
                newc.extend(body[cursor:p])
                newm.extend(m[cursor:p])
                old, _ = sides(h)
                kept, oi = m[p:p + len(old)], 0
                for t, c in h["lines"]:
                    if t == b" ":
                        newc.append(c)
                        newm.append(kept[oi] if oi < len(kept) else None)
                        oi += 1
                    elif t == b"-":
                        oi += 1
                    else:
                        newc.append(c)
                        newm.append(None)
                cursor = p + len(old)
            newc.extend(body[cursor:])
            newm.extend(m[cursor:])
            if not absent:
                content[path], mapping[path] = newc, newm
    return out


# --------------------------------------------------------------------------- the walk through the releases
def overlaps_new(hs: list, lo: int, hi: int) -> bool:
    """Does some diff hunk (a, b, c, d) = -a,b +c,d touch [lo, hi] of the NEW file."""
    for _, _, c, d in hs:
        if d > 0:
            if c <= hi and c + d - 1 >= lo:
                return True
        elif lo - 1 <= c <= hi:
            return True
    return False


def map_new_to_old(hs: list, lo: int, hi: int):
    """A region [lo, hi] of the new file -> the same region of the old one."""
    def one(x, left):
        delta = 0
        for a, b, c, d in hs:
            if d > 0:
                if x > c + d - 1:
                    delta += d - b
                    continue
                if x >= c:                              # inside the new range of the hunk
                    if b > 0:
                        return a if left else a + b - 1
                    return a + 1 if left else a
                break
            if x > c:
                delta += d - b
                continue
            break
        return x - delta
    nl, nh = one(lo, True), one(hi, False)
    if nl > nh:
        nl = nh = max(1, min(nl, nh))
    return max(1, nl), max(1, nh)


class Releases:
    """The files of a chain of release tags in a repository: existence, and `git diff -U0` between neighbours."""

    def __init__(self, source, tags: list, paths: list):
        self.source, self.tags = source, tags
        self._exists, self._diff, self._rename = {}, {}, {}
        paths = sorted(set(paths))
        blobs = tree_blobs(source, tags, paths)
        require_present(source, blobs)          # a file that is in a tag and whose content is not here is red, never 'absent'
        for t in tags:
            for p in paths:
                self._exists[(t, p)] = (t, p) in blobs
        self.paths = paths

    def exists(self, k: int, path: str) -> bool:
        return self._exists.get((self.tags[k], path), False)

    def blob(self, k: int, path: str):
        done = git(self.source, "show", "%s:%s" % (self.tags[k], path), check=False)
        return done.stdout if done.returncode == 0 else None

    @staticmethod
    def _parse(out: bytes) -> dict:
        files, path = {}, None
        for row in out.split(b"\n"):
            if row.startswith(b"diff --git "):
                m = re.match(rb"diff --git a/(.*) b/(.*)$", row)
                path = m.group(2).decode("utf-8", "replace")
                files[path] = []
                continue
            m = HUNK_HEADER.match(row)
            if m and path is not None:
                files[path].append((int(m.group(1)), int(m.group(2)) if m.group(2) is not None else 1,
                                    int(m.group(3)), int(m.group(4)) if m.group(4) is not None else 1))
        return files

    def _interval(self, k: int) -> dict:
        """The hunks of every file present in both tags of the interval k (tags[k] -> tags[k+1]), by path."""
        if k not in self._diff:
            both = [p for p in self.paths if self.exists(k, p) and self.exists(k + 1, p)]
            flags = ["diff", "-U0", "--no-color", "--no-renames", "--no-ext-diff", "--no-textconv",
                     "--src-prefix=a/", "--dst-prefix=b/", self.tags[k], self.tags[k + 1], "--"]
            got, batch, size = {}, [], 0
            for p in both + [None]:
                if p is None or size + len(p) + 1 > PATH_BATCH:
                    if batch:
                        got.update(self._parse(git(self.source, *flags, *batch).stdout))
                    batch, size = [], 0
                if p is not None:
                    batch.append(p)
                    size += len(p) + 1
            self._diff[k] = got
        return self._diff[k]

    def hunks(self, k: int, old_path: str, new_path: str) -> list:
        if old_path == new_path:
            return self._interval(k).get(new_path, [])
        key = (k, old_path, new_path)
        if key not in self._diff:
            done = git(self.source, "diff", "-U0", "--no-color", "--no-renames", "--no-ext-diff", "--no-textconv",
                       "%s:%s" % (self.tags[k], old_path), "%s:%s" % (self.tags[k + 1], new_path), check=False)
            self._diff[key] = self._hunks_of_blobs(done.stdout)
        return self._diff[key]

    @staticmethod
    def _hunks_of_blobs(out: bytes) -> list:
        hs = []
        for row in out.split(b"\n"):
            m = HUNK_HEADER.match(row)
            if m:
                hs.append((int(m.group(1)), int(m.group(2)) if m.group(2) is not None else 1,
                           int(m.group(3)), int(m.group(4)) if m.group(4) is not None else 1))
        return hs

    def renamed_from(self, k: int, new_path: str):
        """The path in tags[k] of a file that is `new_path` in tags[k+1] and has the same content under another name (git -M100%: the
        trees' shas alone, no content is read), or None."""
        if k not in self._rename:
            names = {}
            for row in git(self.source, "diff", "--name-status", "-M100%", self.tags[k], self.tags[k + 1]).stdout.decode("utf-8", "replace").splitlines():
                parts = row.split("\t")
                if parts[0].startswith("R") and len(parts) == 3:
                    names[parts[2]] = parts[1]
            self._rename[k] = names
        return self._rename[k].get(new_path)


def walk(rel: Releases, path: str, lo: int, hi: int) -> list:
    """The intervals (as the index of their newer tag) in which something changed within [lo, hi] of `path` at the
    last tag, newest first."""
    changed, cur = [], path
    for k in range(len(rel.tags) - 2, -1, -1):          # the interval tags[k] -> tags[k+1]; `cur` is the path in tags[k+1]
        if not rel.exists(k + 1, cur):
            break
        old = cur
        if not rel.exists(k, cur):
            old = rel.renamed_from(k, cur)
            if not old or not rel.exists(k, old):       # the file appears in this interval
                changed.append(k + 1)
                break
        hs = rel.hunks(k, old, cur)
        if overlaps_new(hs, lo, hi):
            changed.append(k + 1)
        lo, hi = map_new_to_old(hs, lo, hi)
        cur = old
    return changed


# --------------------------------------------------------------------------- the result
def in_band(churn: int) -> bool:
    return churn >= BAND_MIN_CHURN


def compute(root, source, base: str, releases: list | None = None, warn=None, expected: dict | None = None) -> dict:
    """The data of tools/churn.json for the series in `root`, the Mozilla tags in `source`. `expected` (tag -> commit): the
    commits the tags must resolve to (check_commits); the commits found are recorded in the result."""
    releases = list(releases) if releases else default_releases(base)
    if releases[-1] != base:
        raise ChurnError(failed("tools/churn.py --releases", "the chain of releases must end with the base %s and it ends with %s" % (base, releases[-1]),
                                "pass --releases <tag,...> oldest first, ending with %s, or leave it out for the eight releases before the base" % base))
    if len(set(releases)) != len(releases) or len(releases) < 2:
        raise ChurnError(failed("tools/churn.py --releases", "the releases are not a chain of at least two distinct tags: %s" % ", ".join(releases),
                                "pass --releases <tag,...>, distinct tags oldest first, ending with the base"))
    check_tags(source, releases)
    check_commits(source, {t: c for t, c in (expected or {}).items() if t in releases})
    warn = warn if warn is not None else []
    last = len(releases) - 1
    paths = set()
    for folder in series_folders(root):
        patch = Path(root) / folder / "hooks.patch"
        if patch.is_file():
            paths.update(fd["path"] for fd in parse_patch(patch.read_bytes()))
    rel = Releases(source, releases, list(paths))
    found = regions(root, lambda p: rel.blob(last, p) if rel.exists(last, p) else None, warn)
    labels = [release_label(t) for t in releases]
    hooks = []
    for r in found:
        which = [] if r["region"] is None else [labels[k] for k in walk(rel, r["file"], *r["region"])]
        which.sort(key=labels.index)
        hooks.append({"key": r["key"], "folder": r["folder"], "file": r["file"], "hunk": r["hunk"],
                      "churn": len(which), "which": which})
    hooks.sort(key=lambda h: (h["folder"], h["file"], h["hunk"], h["key"]))
    return {"base": base, "releases": [{"tag": t, "commit": commit_of(source, t)} for t in releases], "band": BAND_MIN_CHURN,
            "hooks": hooks}


def render(data: dict) -> bytes:
    """The bytes of tools/churn.json: fixed key order, one-space indent, `\\n`, UTF-8, a final newline."""
    return (json.dumps(data, indent=1, ensure_ascii=False) + "\n").encode("utf-8")


def distribution(data: dict) -> dict:
    return dict(sorted(Counter(h["churn"] for h in data["hooks"]).items()))


def summary(data: dict) -> str:
    dist = distribution(data)
    top = max(list(dist) + [len(data["releases"]) - 1])
    banded = sum(1 for h in data["hooks"] if in_band(h["churn"]))
    return "\n".join(["%d hunks, base %s, %d intervals" % (len(data["hooks"]), data["base"], len(data["releases"]) - 1),
                      "churn: " + "  ".join("%d:%d" % (c, dist.get(c, 0)) for c in range(top + 1)),
                      "in the band (churn >= %d): %d" % (data["band"], banded)])


def describe(h: dict) -> str:
    return "%s %s hunk %d" % (h["folder"], h["file"], h["hunk"])


def differences(old: dict, new: dict) -> list:
    """What differs between a committed churn.json and the one computed now, one failure each, the hunks by name."""
    out = []
    fix = "python tools/churn.py --source <repo with the tags> --write, and commit the file"
    for field in ("base", "band"):
        if old.get(field) != new[field]:
            out.append(failed("tools/churn.json", "%s is %r in the file, %r now" % (field, old.get(field), new[field]), fix))
    if old.get("releases") != new["releases"]:
        out.append(failed("tools/churn.json", "releases: the tags or their commits differ", fix))
    before = {h["key"]: h for h in old.get("hooks", [])}
    now = {h["key"]: h for h in new["hooks"]}
    for key in sorted(set(before) - set(now)):
        out.append(failed(describe(before[key]), "in tools/churn.json (churn %s), no longer in the series" % before[key].get("churn"), fix))
    for key in sorted(set(now) - set(before)):
        out.append(failed(describe(now[key]), "in the series (churn %d), not in tools/churn.json" % now[key]["churn"], fix))
    for key in sorted(set(now) & set(before)):
        o, n = before[key], now[key]
        if o != n:
            out.append(failed(describe(n), "churn %s %s in tools/churn.json, churn %d %s now" % (o.get("churn"), o.get("which"), n["churn"], n["which"]), fix))
    return out


def check(series: Path, source: Path, warn=None) -> list:
    """`--check`: recompute at the base and the tags the committed file names, and compare the bytes. -> the problems ([] = same)."""
    path = Path(series) / "tools" / "churn.json"
    committed = load_committed(path)
    data = compute(series, source, committed.get("base", ""), [r["tag"] for r in committed["releases"]], warn, recorded(committed))
    found = []
    try:
        pinned = json.loads((Path(series) / "UPSTREAM.json").read_text(encoding="utf-8")).get("mozilla_tag")
    except (OSError, ValueError):
        pinned = None
    if pinned and committed.get("base") != pinned:
        found.append(failed("tools/churn.json", "base: the file is for %s, the series is on %s" % (committed.get("base"), pinned),
                            "python tools/churn.py --source <repo with the tags> --write, and commit the file (a port rewrites it)"))
    found += differences(committed, data)
    if not found and render(data) != path.read_bytes():
        found.append(failed("tools/churn.json", "the bytes differ and no hunk does: the file was not written by tools/churn.py",
                            "python tools/churn.py --source <repo with the tags> --write, and commit the file; do not edit it by hand"))
    return found


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", type=Path, help="a repository that has the Mozilla release tags")
    ap.add_argument("--base", help="the Mozilla tag of the series, the last of the chain (default: the mozilla_tag of UPSTREAM.json)")
    ap.add_argument("--releases", help="the tags, oldest first, comma separated, ending with the base (default: the eight before it)")
    ap.add_argument("--write", action="store_true", help="write tools/churn.json (else only print the summary)")
    ap.add_argument("--check", action="store_true", help="red unless tools/churn.json is what the series gives now (byte for byte)")
    ap.add_argument("--fetch", action="store_true", help="fetch the tags tools/churn.json lists into --source, one commit deep, and verify them")
    ap.add_argument("--cache-key", action="store_true", help="print the key of the commits tools/churn.json lists")
    ap.add_argument("--series", type=Path, default=ROOT, help="the series root (default: this repository)")
    a = ap.parse_args(argv)
    out_path = a.series / "tools" / "churn.json"
    warn = []
    try:
        if a.cache_key:
            print(cache_key(load_committed(out_path), series_paths(a.series)))
            return 0
        if a.source is None:
            print(failed("python tools/churn.py", "--source is not given", "add --source <repo>, a repository that has the Mozilla release tags (--fetch fills it)"),
                  file=sys.stderr)
            return 2
        if a.fetch:
            fetch(a.source, load_committed(out_path), series_paths(a.series), mozilla_repository(a.series))
            return 0
        if a.check:
            found = check(a.series, a.source, warn)
            for w in warn:
                print("warning: " + w, file=sys.stderr)
            if found:
                print("\n".join(found), file=sys.stderr)
                return 1
            print("ok: tools/churn.json is what the series gives now")
            return 0
        base = a.base
        if not base:
            base = json.loads((a.series / "UPSTREAM.json").read_text(encoding="utf-8"))["mozilla_tag"]
        try:
            before = recorded(load_committed(out_path))
        except ChurnError:
            before = {}
        data = compute(a.series, a.source, base, a.releases.split(",") if a.releases else None, warn, before)
    except ChurnError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    for w in warn:
        print("warning: " + w, file=sys.stderr)
    print(summary(data))
    if a.write:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(render(data))
        print("wrote tools/churn.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
