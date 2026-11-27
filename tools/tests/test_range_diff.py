"""series-02, the range-diff of a port (docs/decisions/series-02-every-folder-states-its-relation-to-mozilla.md): `engine.py range-diff`
builds the layer stack of the old series on its tag and of this series on its tag, writes `git range-diff` of the two to ONE file,
ports/range-diff.txt, whose first line is `<OLD_TAG>..<NEW_TAG>`, and reads only a partial clone of Mozilla's repository.

Shown on a small Mozilla repository with two release tags and a series with two folders, one of which patches a file whose neighbouring
lines the new tag changed. The tests prove
  (a) the file: first line, one `!` layer and one `=` layer, one file written and nothing else, the same bytes every time and on every
      repository that has the tags (a full one, a partial clone, with any git configuration);
  (b) `--check` is red when the file is missing, stale, or for another pair of tags, and green when it is what the two series give;
  (c) `--decide`: a pull request that does not move mozilla_tag is not a port, and one that does is;
  (d) the partial clone: the files the stacks read are there, the others are not, and a file that is missing is an error that names the fix;
  (e) the old series is read from its git objects byte for byte, a tag that is not the release the series was exported on is red.

    python -m pytest tools/tests/test_range_diff.py
"""
import difflib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import churn  # noqa: E402
import engine  # noqa: E402
import range_diff  # noqa: E402

OLD, NEW = "FIREFOX_158_0_RELEASE", "FIREFOX_159_0_RELEASE"
IDENTITY = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}


def git(repo, *args, env=None):
    done = subprocess.run(["git", "-C", str(repo), "-c", "core.autocrlf=false", *args], capture_output=True, env=dict(os.environ, **IDENTITY, **(env or {})))
    assert done.returncode == 0, done.stderr.decode()
    return done.stdout.decode().strip()


def lines(n, prefix):
    return ["%s%d;" % (prefix, i) for i in range(1, n + 1)]


def tree_at(tag):
    """The files of the small Mozilla repository at a tag: a.cpp (the series patches it), b.cpp and c.cpp (it does not), and attribute files above them."""
    a = lines(30, "int a")
    if tag == NEW:
        a[8] = "int a9_changed_by_mozilla;"          # a line of the hook's context: the patch changes
        a.insert(0, "// a new first line")           # and every line number moves
    return {".gitattributes": ["*.md text"], "dom/.gitattributes": ["*.cpp whitespace=trailing-space"], "dom/a.cpp": a,
            "dom/b.cpp": lines(30, "int b") if tag == OLD else lines(30, "int b") + ["int b31;"], "dom/c.cpp": lines(30, "int c"),
            "other/x.txt": lines(5, "x")}


@pytest.fixture()
def mozilla(tmp_path):
    repo = tmp_path / "mozilla"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "uploadpack.allowFilter", "true")
    git(repo, "config", "uploadpack.allowAnySHA1InWant", "true")
    for tag in (OLD, NEW):
        for name, content in tree_at(tag).items():
            (repo / name).parent.mkdir(parents=True, exist_ok=True)
            (repo / name).write_bytes(("\n".join(content) + "\n").encode())
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", tag)
        git(repo, "tag", tag)
    return repo


def patch_of(tag, hook):
    old = tree_at(tag)["dom/a.cpp"]
    at = old.index("int a10;")
    new = old[:at + 1] + [hook] + old[at + 1:]
    body = list(difflib.unified_diff(old, new, "a/dom/a.cpp", "b/dom/a.cpp", n=3, lineterm=""))
    return "diff --git a/dom/a.cpp b/dom/a.cpp\n%s\n" % "\n".join(body)


def write_series(root, source, tag, hook="StealthA(); // STEALTH-HOOK(fingerprint/a)", own=b"// ours\n", repo_url=None):
    """The series of the small repository on `tag`: fingerprint/a (the hook, and a file of ours) and platform/b (a file of ours); UPSTREAM.json
    declares the tree the stack gives, computed on a repository that has everything."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "SERIES").write_text("platform/b\nfingerprint/a\n", encoding="utf-8")
    a, b = root / "fingerprint" / "a", root / "platform" / "b"
    (a / "src" / "dom").mkdir(parents=True, exist_ok=True)
    (b / "src").mkdir(parents=True, exist_ok=True)
    (a / "hooks.patch").write_bytes(patch_of(tag, hook).encode())
    (a / "src" / "dom" / "StealthA.cpp").write_bytes(own)
    (a / "MANIFEST.json").write_text(json.dumps({"modified": ["dom/a.cpp"], "added": {"dom/StealthA.cpp": "100644"}}), encoding="utf-8")
    (b / "src" / "tool.py").write_bytes(b"print(1)\r\n")                # a CRLF file of ours: the old series must come back with it
    (b / "MANIFEST.json").write_text(json.dumps({"modified": [], "added": {"tool.py": "100755"}}), encoding="utf-8")
    tree = engine.build_stack(source, tag, root=root)[-1][2]
    (root / "UPSTREAM.json").write_text(json.dumps({"mozilla_repository": repo_url or source.as_uri(), "mozilla_tag": tag, "exported_tree": tree}),
                                        encoding="utf-8")


@pytest.fixture()
def world(tmp_path, mozilla):
    """The series repository: committed on OLD (main), and the working tree is the series on NEW (the pull request)."""
    root = tmp_path / "series"
    write_series(root, mozilla, OLD)
    git(root, "init", "-q")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "main")
    git(root, "branch", "-M", "main")
    write_series(root, mozilla, NEW)
    return root


def run(world, source, *extra, old="main"):
    return range_diff.main(["--series", str(world), "--source", str(source), "--old-series", old, *extra], engine.build_stack)


def generated(world, source, capsys, *extra):
    capsys.readouterr()
    assert run(world, source, *extra) == 0
    return capsys.readouterr().out


# ---------------------------------------------------------------------------------------------------------------- the file
def test_the_file_says_the_pair_of_tags_first_and_which_layer_changed(world, mozilla, capsys):
    out = generated(world, mozilla, capsys)
    first, *rest = out.split("\n")
    assert first == "%s..%s" % (OLD, NEW)
    text = "\n".join(rest)
    assert any(l.split()[:1] == ["1:"] and " = " in l and l.endswith("platform/b") for l in rest), text       # a layer that did not move
    assert any(l.split()[:1] == ["2:"] and " ! " in l and l.endswith("fingerprint/a") for l in rest), text   # the hook whose lines Mozilla moved
    assert "int a9_changed_by_mozilla" in text, "what changed in the patch is shown"


def test_write_writes_one_file_and_nothing_else(world, mozilla, capsys):
    before = {p for p in world.rglob("*") if p.is_file() and ".git" not in p.parts}
    assert run(world, mozilla, "--write") == 0
    after = {p for p in world.rglob("*") if p.is_file() and ".git" not in p.parts}
    assert after - before == {world / "ports" / "range-diff.txt"} and before <= after
    written = (world / "ports" / "range-diff.txt").read_bytes()
    assert written.split(b"\n", 1)[0] == ("%s..%s" % (OLD, NEW)).encode() and b"\r\n" not in written.split(b"\n", 1)[0]
    assert written.decode() == generated(world, mozilla, capsys), "writing and printing are the same bytes"


def test_regeneration_is_byte_identical_whatever_the_machine_has_configured(world, mozilla, tmp_path, monkeypatch, capsys):
    base = generated(world, mozilla, capsys)
    assert generated(world, mozilla, capsys) == base
    # a user's configuration (another diff algorithm, no prefix, short ids, color) reaches neither the stacks nor the range-diff
    config = tmp_path / "gitconfig"
    config.write_text("[diff]\n\talgorithm = patience\n\tnoprefix = true\n\trenames = copies\n[core]\n\tabbrev = 5\n[color]\n\tui = always\n", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    assert generated(world, mozilla, capsys) == base
    # ... nor the repository it is read from: a partial clone gives the same bytes
    assert generated(world, tmp_path / "cache.git", capsys, "--fetch") == base
    assert generated(world, tmp_path / "cache.git", capsys, "--fetch") == base          # a second fetch, from what the first left: the same


# ---------------------------------------------------------------------------------------------------------------- the check
def test_check_is_green_on_the_file_the_two_series_give(world, mozilla, capsys):
    assert run(world, mozilla, "--write") == 0
    capsys.readouterr()
    assert run(world, mozilla, "--check") == 0
    assert "ok: ports/range-diff.txt is the range-diff of %s..%s" % (OLD, NEW) in capsys.readouterr().out


def test_check_is_red_when_the_file_is_missing(world, mozilla, capsys):
    capsys.readouterr()
    assert run(world, mozilla, "--check") == 1
    err = capsys.readouterr().err
    assert "ports/range-diff.txt: the file is missing" in err and "Fix: python tools/engine.py range-diff" in err and "Rule: docs/decisions/series-02-" in err


def test_check_is_red_when_the_file_is_stale(world, mozilla, capsys):
    assert run(world, mozilla, "--write") == 0
    # a hook that changed since the file was written
    write_series(world, mozilla, NEW, hook="StealthA2(); // STEALTH-HOOK(fingerprint/a)")
    capsys.readouterr()
    assert run(world, mozilla, "--check") == 1
    err = capsys.readouterr().err
    assert "the file is stale" in err and "StealthA" in err and "Fix: python tools/engine.py range-diff" in err
    # and the same file is green again once it is written again
    assert run(world, mozilla, "--write") == 0 and run(world, mozilla, "--check") == 0


def test_check_is_red_when_one_byte_differs(world, mozilla, capsys):
    assert run(world, mozilla, "--write") == 0
    path = world / "ports" / "range-diff.txt"
    path.write_bytes(path.read_bytes() + b"\n")
    capsys.readouterr()
    assert run(world, mozilla, "--check") == 1 and "the file is stale" in capsys.readouterr().err


def test_check_is_red_when_the_first_line_is_another_pair_of_tags(world, mozilla, capsys):
    assert run(world, mozilla, "--write") == 0
    path = world / "ports" / "range-diff.txt"
    body = path.read_bytes().split(b"\n", 1)[1]
    for wrong in ("%s..%s" % (NEW, OLD), "FIREFOX_157_0_RELEASE..%s" % NEW, ""):
        path.write_bytes(wrong.encode() + b"\n" + body)
        capsys.readouterr()
        assert run(world, mozilla, "--check") == 1
        err = capsys.readouterr().err
        assert "its first line is %r" % wrong in err and "%s..%s" % (OLD, NEW) in err and "main's tag, this series' tag" in err


# ---------------------------------------------------------------------------------------------------------------- port or not
def test_a_pull_request_that_does_not_move_the_tag_is_not_a_port(world, capsys):
    assert range_diff.decide(OLD, OLD)[0] is False and range_diff.decide(OLD, NEW)[0] is True
    assert "%s..%s" % (OLD, NEW) in range_diff.decide(OLD, NEW)[1] and "not a port" in range_diff.decide(OLD, OLD)[1]
    capsys.readouterr()
    assert range_diff.main(["--series", str(world), "--old-series", "main", "--decide"], engine.build_stack) == 0
    assert capsys.readouterr().out.splitlines()[0] == "port=true"             # the working tree is on NEW, main is on OLD
    git(world, "stash", "-q", "-u")                                            # the working tree is main again: the same tag on both sides
    assert range_diff.main(["--series", str(world), "--old-series", "main", "--decide"], engine.build_stack) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "port=false" and out[1].startswith("decision=not a port: mozilla_tag is %s on both sides" % OLD)


# ---------------------------------------------------------------------------------------------------------------- the partial clone
def test_the_partial_clone_has_the_files_the_stacks_read_and_not_the_others(world, mozilla, tmp_path, capsys):
    into = tmp_path / "cache.git"
    out = generated(world, into, capsys, "--fetch")
    assert out.startswith("%s..%s\n" % (OLD, NEW))
    paths = range_diff.Series(world, "this").paths()
    assert paths == ["dom/a.cpp"]
    for tag in (OLD, NEW):
        read = churn.tree_blobs(into, [tag], paths)
        assert len(read) == 1 and churn.missing_blobs(into, read.values()) == []               # what the stack reads is there
        others = churn.tree_blobs(into, [tag], ["dom/b.cpp", "dom/c.cpp", "other/x.txt", ".gitattributes", "dom/.gitattributes"])
        assert len(others) == 5 and set(churn.missing_blobs(into, others.values())) == set(others.values())    # the rest of the tree is not
        assert churn.commit_of(into, tag) == git(mozilla, "rev-parse", tag + "^{commit}")


def test_a_second_fetch_takes_nothing_it_has(world, mozilla, tmp_path, capsys):
    into = tmp_path / "cache.git"
    generated(world, into, capsys, "--fetch")
    again = subprocess.run([sys.executable, str(Path(range_diff.__file__).parent / "engine.py"), "range-diff", "--series", str(world), "--source", str(into),
                            "--old-series", "main", "--fetch", "--check"], capture_output=True, env=dict(os.environ))
    said = again.stderr.decode()      # progress goes to stderr: stdout is the file
    assert said.count("in the repository") == 2 and "0 fetched" in said, said


def test_a_file_the_stack_needs_that_is_not_there_is_an_error_that_names_the_fix(world, mozilla, tmp_path, capsys):
    """The repository was fetched for another set of files (the series patched fewer): no fetch of one blob at a time behind git's back, no
    trace of a Python error: where / what / fix / rule."""
    into = tmp_path / "old-cache.git"
    churn.partial_clone(into, mozilla.as_uri())
    for tag in (OLD, NEW):
        churn.fetch_tag(into, tag, mozilla.as_uri(), say=lambda *_: None)
        churn.fetch_blobs(into, [tag], ["dom/c.cpp"], say=lambda *_: None)          # a.cpp was not a hook file then
    capsys.readouterr()
    assert run(world, into) == 2
    err = capsys.readouterr().err
    assert "have no content in the repository (first: dom/a.cpp)" in err and "--fetch" in err and "Rule: docs/decisions/series-02-" in err
    assert "Traceback" not in err
    assert run(world, into, "--fetch") == 0                       # the fetch for the right set repairs it


def test_the_stack_is_built_with_no_lazy_fetch_and_without_the_blobs_of_the_files_it_does_not_touch(world, mozilla, tmp_path):
    """Any object the stack needs beyond the patched files would be fetched by git one at a time; with GIT_NO_LAZY_FETCH it
    is an error instead. The stack is built on a clone that has only those files."""
    into = tmp_path / "cache.git"
    assert run(world, into, "--fetch") == 0
    series = range_diff.Series(world, "this")
    seen = []
    real = engine.build_stack

    def watched(*a, **k):
        seen.append(os.environ.get("GIT_NO_LAZY_FETCH"))
        return real(*a, **k)

    tag_commit, head = range_diff.stack(into, series, watched)
    assert seen == ["1"], "the stack is built with the switch on"
    assert os.environ.get("GIT_NO_LAZY_FETCH") != "1", "and the switch is put back"
    assert git(into, "log", "--format=%s", "%s..%s" % (tag_commit, head)).splitlines() == ["fingerprint/a", "platform/b"]
    # without the switch git would ask Mozilla for a missing blob; with it, a build that needs one stops
    assert subprocess.run(["git", "-C", str(into), "cat-file", "-p", git(into, "rev-parse", "%s:dom/b.cpp" % NEW)], capture_output=True,
                          env=dict(os.environ, GIT_NO_LAZY_FETCH="1")).returncode != 0


# ---------------------------------------------------------------------------------------------------------------- the old series, the tags
def test_the_old_series_is_read_from_the_git_objects_byte_for_byte(world, tmp_path):
    into = range_diff.extract_ref(world, "main", tmp_path / "old")
    tool = into / "platform" / "b" / "src" / "tool.py"
    assert tool.read_bytes() == b"print(1)\r\n", "no conversion of line endings"
    assert sorted(p.relative_to(into).as_posix() for p in into.rglob("*") if p.is_file()) == [
        "SERIES", "UPSTREAM.json", "fingerprint/a/MANIFEST.json", "fingerprint/a/hooks.patch", "fingerprint/a/src/dom/StealthA.cpp",
        "platform/b/MANIFEST.json", "platform/b/src/tool.py"]
    assert json.loads((into / "UPSTREAM.json").read_text(encoding="utf-8"))["mozilla_tag"] == OLD, "main's tag, not the working tree's"


def test_an_old_series_ref_that_does_not_exist_is_an_error_not_a_trace(world, mozilla, capsys):
    capsys.readouterr()
    assert run(world, mozilla, old="origin/nowhere") == 2
    err = capsys.readouterr().err
    assert "give --old-series a ref this repository has" in err and "Traceback" not in err


def test_a_tag_that_is_not_the_release_the_series_was_exported_on_is_red(world, mozilla, tmp_path, capsys):
    """The tree the stack gives must be the one UPSTREAM.json declares: a retagged release or another repository cannot give a file that
    looks right."""
    up = json.loads((world / "UPSTREAM.json").read_text(encoding="utf-8"))
    up["exported_tree"] = "0" * 40
    (world / "UPSTREAM.json").write_text(json.dumps(up), encoding="utf-8")
    capsys.readouterr()
    assert run(world, mozilla, "--write") == 2
    err = capsys.readouterr().err
    assert "UPSTREAM.json declares " + "0" * 40 in err and "export" in err and not (world / "ports").exists()


def test_a_repository_without_the_tag_is_told_how_to_fetch_it(world, tmp_path, capsys):
    empty = tmp_path / "empty.git"
    subprocess.run(["git", "init", "-q", "--bare", str(empty)], check=True)
    capsys.readouterr()
    assert run(world, empty) == 2
    err = capsys.readouterr().err
    assert "the repository lacks the tag %s" % OLD in err and "range-diff --source" in err and "--fetch" in err


def test_fetch_never_turns_a_working_repository_into_a_partial_clone(world, mozilla, capsys):
    capsys.readouterr()
    assert run(world, mozilla, "--fetch") == 2
    assert "partial clone" in capsys.readouterr().err
    assert "partialclone" not in git(mozilla, "config", "--local", "--list").lower()


# ---------------------------------------------------------------------------------------------------------------- what the machine does around the command
def test_a_scratch_directory_that_cannot_be_removed_does_not_decide_the_result(world, mozilla, monkeypatch, capsys):
    """The old series is written to a scratch directory for the length of the command. On Windows a file there that a scanner, an indexer or
    another git still holds open makes the removal of the directory fail; the file the command computed is right and is not given up for it."""
    base = generated(world, mozilla, capsys)
    held, scratch = [], []
    real = range_diff.compute

    def computing(series, old, source, build_stack):
        held.append(open(old.root / "SERIES", "rb"))        # another process has the file open while the command ends
        scratch.append(old.root.parent)
        return real(series, old, source, build_stack)

    monkeypatch.setattr(range_diff, "compute", computing)
    try:
        assert run(world, mozilla) == 0
        assert capsys.readouterr().out.encode() == base.encode()
    finally:
        for handle in held:
            handle.close()
        for left in scratch:
            shutil.rmtree(left, ignore_errors=True)


def test_the_layer_stack_does_not_give_up_its_commits_for_a_scratch_file_it_cannot_remove(world, mozilla, monkeypatch):
    """engine.build_stack keeps its index in a scratch directory; the commits it wrote are the result, whatever the directory's removal does."""
    expected = engine.build_stack(mozilla, NEW, root=world)
    held, scratch = [], []
    real = engine.add_files

    def adding(source, folder, manifest, env, root=None):
        scratch.append(Path(env["GIT_INDEX_FILE"]).parent)
        held.append(open(scratch[-1] / "held", "wb"))      # a file of the scratch directory is held open by another process
        return real(source, folder, manifest, env, root)

    monkeypatch.setattr(engine, "add_files", adding)
    try:
        assert engine.build_stack(mozilla, NEW, root=world) == expected
    finally:
        for handle in held:
            handle.close()
        for left in scratch:
            shutil.rmtree(left, ignore_errors=True)


def test_the_result_does_not_depend_on_the_users_git_configuration_for_a_bare_repository(world, mozilla, tmp_path, monkeypatch, capsys):
    """The repository of the tags that --fetch makes is a bare one of its own; a machine whose git refuses to find a bare repository by
    itself (safe.bareRepository=explicit) gets the same file."""
    base = generated(world, mozilla, capsys)
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "safe.bareRepository")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "explicit")
    assert generated(world, tmp_path / "cache.git", capsys, "--fetch") == base
    assert generated(world, tmp_path / "cache.git", capsys, "--fetch") == base
