"""The tools never assume where the Firefox source repository, the node-gate tree or Node live on a machine.

The source repository comes from --source or FIREFOX_SOURCE, the node-gate tree from ENGINE_NODE_GATE_TREE, Node from ENGINE_NODE
or the PATH. A command that needs one that was not named stops with a message that says what to set; the others do not ask.

    python -m pytest -q tools/tests/test_source_is_named.py
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1]
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))
import export_gate  # noqa: E402


def run(*args, extra_env=None):
    env = {k: v for k, v in os.environ.items() if k not in ("FIREFOX_SOURCE", "ENGINE_SOURCE", "ENGINE_NODE_GATE_TREE")}
    env.update(extra_env or {})
    return subprocess.run([sys.executable, str(TOOLS / "engine.py"), *args], cwd=ROOT, env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=600)


@pytest.mark.parametrize("command", ["export", "status"])
def test_a_command_that_reads_the_source_names_how_to_give_it(command):
    done = run(command)
    assert done.returncode != 0
    message = done.stdout + done.stderr
    assert "--source" in message and "FIREFOX_SOURCE" in message and "needs the source repository" in message, message


def test_check_without_against_does_not_ask_for_the_source():
    message = (lambda d: d.stdout + d.stderr)(run("check"))
    assert "needs the source repository" not in message, message


def test_check_against_a_tag_needs_the_source():
    done = run("check", "--against", "FIREFOX_X")
    assert "--source" in done.stderr and "FIREFOX_SOURCE" in done.stderr, done.stdout + done.stderr


def test_prebuild_without_a_source_names_how_to_give_it():
    env = {k: v for k, v in os.environ.items() if k not in ("FIREFOX_SOURCE", "ENGINE_SOURCE")}
    done = subprocess.run([sys.executable, str(TOOLS / "prebuild.py")], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    assert done.returncode != 0
    assert "--source" in done.stderr and "FIREFOX_SOURCE" in done.stderr, done.stderr


def test_the_export_gate_without_a_tree_refuses_naming_the_variable(monkeypatch):
    monkeypatch.delenv("ENGINE_NODE_GATE_TREE", raising=False)
    with pytest.raises(SystemExit, match="ENGINE_NODE_GATE_TREE"):
        export_gate.gate(Path("src"), "head")


def test_the_export_refuses_before_it_writes_when_the_tree_is_not_named(tmp_path):
    done = run("export", "--source", str(tmp_path))
    assert done.returncode != 0 and "ENGINE_NODE_GATE_TREE" in done.stderr, done.stdout + done.stderr


def test_no_tool_names_a_path_of_one_machine():
    skip = (TOOLS / "tests" / "data", Path(__file__).resolve())
    found = []
    for path in TOOLS.rglob("*"):
        if not path.is_file() or "__pycache__" in path.parts or path in skip or any(s in path.parents for s in skip):
            continue
        data = path.read_bytes()
        for needle in (b"C:/ff", b"C:/Users", b"C:" + bytes([92]) + b"ff", b"C:" + bytes([92]) + b"Users"):
            if needle in data:
                found.append("%s: %s" % (path.relative_to(ROOT), needle.decode().replace(chr(92), "/")))
    assert not found, found
