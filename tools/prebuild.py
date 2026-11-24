"""Pre-build static checks of the engine tree: the questions a failed build answers an hour later,
answered in seconds from git objects, with no checkout and no compiler.

    python tools/prebuild.py --source <path> --head <branch> [--base <branch>] [--folder <f> ...] [--json out.json]

--source is the Firefox repository; it may be given by the environment variable FIREFOX_SOURCE instead, and has no default.

Reads the tree of --head (and the Mozilla tag of UPSTREAM.json, and --base when given) straight from the
objects of the source repository. A line per problem, the style of `engine.py check`:

    FAIL <where>: <what>; <how to fix>
    WARN <where>: cannot tell: <what>          (does not change the exit code)

Exit code 1 when any FAIL. "Ours" is every file of the head the tag does not have; "Mozilla's" is every file
the head changes. HOOKS.json (the series, --series, default this repository) is read for its hand fields:
`own_function` (names of ours to link-check besides Stealth*), `renamed` (a renamed Mozilla body besides
*_Mozilla), `exception` (a Mozilla line changed with pm approval), `calls_mozilla` (a direct call of a
renamed body that is allowed).

    1  HOOK LINK        a hook calls a function of ours: declared, included by the host, defined and built,
                        argument count, namespace
    2  RENAME           every `<Name>_Mozilla`: its declaration renamed, the original name defined by us with
                        the same parameters, no direct caller in a Mozilla file
    3  MOZILLA TOKENS   the Mozilla lines the series rewrites or removes, against the forms HOOKS.json records
    4  EQUIVALENCE      (--base) per file: identical | include-order | changed, token by token
    5  RESTORED         (--base) a Mozilla file the base changed and the head no longer does: byte-identical
                        to the tag, and nothing references what its old hunk introduced
    6  OUR FILES        every source of ours is compiled or shipped by a build file; no two share a basename
    7  GTEST FILTER     every gtest suite of ours is matched by the default `gtest_filter` of release.yml
    8  REMOVED LINES    (--base) rule G51: per Mozilla file, the lines the head removes or rewrites (`-` lines of the
                        diff against the tag) are not more than the base's, unless a HOOKS.json entry of the file
                        carries `"replaces": [...]` (one rewritten line standing for several hooks)

The checks are textual (no preprocessor, no templates, no overload resolution): where the text does not
decide, the check says WARN and does not guess.
"""
from __future__ import annotations

import argparse
import bisect
import difflib
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hook_contract as hc  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
C_EXT = {"cpp", "cc", "cxx", "c", "h", "hpp", "mm", "m"}
C_SOURCE_EXT = {"cpp", "cc", "cxx", "c", "mm"}
JS_EXT = {"js", "mjs", "jsm", "jsx"}
RS_EXT = {"rs"}
HEADER_EXT = {"h", "hpp"}
KEYWORDS = {"return", "else", "new", "delete", "case", "throw", "co_return", "co_yield", "co_await", "goto",
            "sizeof", "and", "or", "not", "typeof", "do", "if", "while", "for", "switch", "using", "typedef"}
FAIL, WARN = "FAIL", "WARN"


@dataclass
class Finding:
    level: str
    check: int
    where: str
    what: str
    fix: str = ""

    def line(self) -> str:
        if self.level == WARN:
            return "WARN %s: cannot tell: %s" % (self.where, self.what)
        return "FAIL %s: %s; %s" % (self.where, self.what, self.fix) if self.fix else "FAIL %s: %s" % (self.where, self.what)

    def as_dict(self) -> dict:
        return {"level": self.level, "check": self.check, "where": self.where, "what": self.what, "fix": self.fix}


def ext_of(path: str) -> str:
    base = path.rsplit("/", 1)[-1]
    return base.rsplit(".", 1)[-1].lower() if "." in base.lstrip(".") else ""


def base_of(path: str) -> str:
    return path.rsplit("/", 1)[-1]


def dir_of(path: str) -> str:
    return path.rsplit("/", 1)[0] if "/" in path else ""


# ============================================================================================ trees
class Tree:
    """A tree of files: read(path) is the text (LF), None when the file is not there."""
    name = "?"

    def read_bytes(self, path: str):
        raise NotImplementedError

    def read(self, path: str):
        b = self.read_bytes(path)
        if b is None:
            return None
        return b.decode("utf-8", "replace").replace("\r\n", "\n")

    def exists(self, path: str) -> bool:
        return self.read_bytes(path) is not None

    def listdir(self, path: str) -> list:
        raise NotImplementedError

    def all_paths(self) -> list:
        raise NotImplementedError

    def contains_names(self, names) -> set:
        """The names of `names` that some source file of this tree contains as a whole word."""
        names = set(names)
        if not names:
            return set()
        rx = re.compile(r"\b(?:%s)\b" % "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True)))
        found: set = set()
        for q in self.all_paths():
            if ext_of(q) in C_EXT | JS_EXT | RS_EXT | {"idl", "webidl", "ipdl", "ipdlh"} and found != names:
                found.update(rx.findall(self.read(q) or ""))
        return found


class GitTree(Tree):
    """A ref of a git repository, read from its objects through one `git cat-file --batch`."""

    def __init__(self, source, ref: str):
        self.source, self.ref, self.name = str(source), ref, ref
        self._proc = None
        self._cache: dict = {}

    def _batch(self):
        if self._proc is None or self._proc.poll() is not None:
            self._proc = subprocess.Popen(["git", "-C", self.source, "cat-file", "--batch"],
                                          stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        return self._proc

    def read_bytes(self, path: str):
        if path in self._cache:
            return self._cache[path]
        p = self._batch()
        p.stdin.write(("%s:%s\n" % (self.ref, path)).encode("utf-8"))
        p.stdin.flush()
        head = p.stdout.readline().decode("utf-8", "replace").split()
        if len(head) < 3 or head[1] != "blob":
            if len(head) >= 3 and head[1] in ("tree", "commit", "tag"):    # a directory: read and drop the listing
                p.stdout.read(int(head[2]) + 1)
            data = None
        else:
            data = p.stdout.read(int(head[2]))
            p.stdout.read(1)
        self._cache[path] = data
        return data

    def listdir(self, path: str) -> list:
        key = "ls:" + path
        if key not in self._cache:
            r = subprocess.run(["git", "-C", self.source, "ls-tree", "--name-only", "%s:%s" % (self.ref, path) if path else self.ref],
                               capture_output=True)
            self._cache[key] = r.stdout.decode("utf-8", "replace").splitlines() if r.returncode == 0 else []
        return [x for x in self._cache[key] if x]

    def all_paths(self) -> list:
        if "all" not in self._cache:
            self._cache["all"] = self.git("ls-tree", "-r", "--name-only", "-z", self.ref).decode("utf-8", "replace").split("\0")
        return self._cache["all"]

    def contains_names(self, names) -> set:
        """One `git grep -q` per name (it stops at the first file that has the name), a few at a time."""
        from concurrent.futures import ThreadPoolExecutor
        specs = ["*.%s" % e for e in sorted(C_EXT | JS_EXT | RS_EXT | {"idl", "webidl", "ipdl", "ipdlh"})]

        def has(n):
            r = subprocess.run(["git", "-C", self.source, "grep", "-q", "-w", "-F", "-e", n, self.ref, "--", *specs],
                               capture_output=True)
            return r.returncode == 0
        names = sorted(set(names))
        with ThreadPoolExecutor(max_workers=4) as pool:
            return {n for n, ok in zip(names, pool.map(has, names)) if ok}

    def close(self):
        if self._proc is not None:
            try:
                self._proc.stdin.close()
                self._proc.wait(timeout=5)
            except Exception:
                self._proc.kill()
            self._proc = None

    def git(self, *args) -> bytes:
        r = subprocess.run(["git", "-C", self.source, "-c", "core.quotepath=off", *args], capture_output=True)
        if r.returncode:
            raise SystemExit("git %s failed: %s" % (" ".join(args[:3]), r.stderr.decode("utf-8", "replace")[:300]))
        return r.stdout


class MemTree(Tree):
    """A tree held in memory (tests)."""

    def __init__(self, files: dict, name="mem"):
        self.files = {k: (v.encode("utf-8") if isinstance(v, str) else v) for k, v in files.items()}
        self.name = name

    def read_bytes(self, path: str):
        return self.files.get(path)

    def all_paths(self) -> list:
        return sorted(self.files)

    def listdir(self, path: str) -> list:
        pre = path + "/" if path else ""
        return sorted({k[len(pre):].split("/")[0] for k in self.files if k.startswith(pre)})


def diff_trees(old: Tree, new: Tree):
    """-> (status, patch): status maps a path to A/M/D (no renames); patch is the -U0 diff of the modified
    files, in git's format."""
    if isinstance(old, GitTree) and isinstance(new, GitTree):
        raw = old.git("diff", "--no-renames", "--name-status", "-z", old.ref, new.ref).split(b"\0")
        status = {}
        for i in range(0, len(raw) - 1, 2):
            status[raw[i + 1].decode("utf-8", "replace")] = raw[i].decode()[:1]
        patch = old.git("diff", "--no-renames", "--diff-filter=M", "-U0", "--no-color", old.ref, new.ref)
        return status, patch.decode("utf-8", "replace")
    status, chunks = {}, []
    for path in sorted(set(old.files) | set(new.files)):
        a, b = old.files.get(path), new.files.get(path)
        if a == b:
            continue
        status[path] = "A" if a is None else ("D" if b is None else "M")
        if a is not None and b is not None:
            al = a.decode("utf-8", "replace").split("\n")
            bl = b.decode("utf-8", "replace").split("\n")
            body = list(difflib.unified_diff(al, bl, "a/" + path, "b/" + path, n=0, lineterm=""))
            chunks.append("diff --git a/%s b/%s\n%s\n" % (path, path, "\n".join(body)))
    return status, "".join(chunks)


# ============================================================================================ project
class Project:
    """The tag, the head, the base (or None) and what the checks share: the changed files, the hunks of
    each, the HOOKS.json entries of the series, the files read and scanned once."""

    def __init__(self, tag: Tree, head: Tree, base: Tree | None = None, series: Path | None = None,
                 scope: set | None = None, hooks_entries: list | None = None):
        self.tag, self.head, self.base = tag, head, base
        self.scope = scope                       # None: every file; else the files of the folders asked for
        self.series = Path(series) if series else None
        self._status = self._patch = None
        self._hunks: dict = {}
        self._scans: dict = {}
        self._hooks = hooks_entries
        self.stats: dict = {}
        self._backports = None

    # -- what changed between the tag and the head
    def _load(self):
        if self._status is None:
            self._status, patch = diff_trees(self.tag, self.head)
            self._patch = {f["file"]: f for f in hc.parse_patch(patch)}

    @property
    def status(self) -> dict:
        self._load()
        return self._status

    @property
    def own(self) -> list:
        return sorted(p for p, s in self.status.items() if s == "A")

    @property
    def mozilla(self) -> list:
        """The files of the tag the head changes (modified, not deleted)."""
        return sorted(p for p, s in self.status.items() if s == "M")

    @property
    def deleted(self) -> list:
        return sorted(p for p, s in self.status.items() if s == "D")

    def in_scope(self, path: str) -> bool:
        return self.scope is None or path in self.scope

    def hunks(self, path: str) -> list:
        self._load()
        f = self._patch.get(path)
        return f["hunks"] if f else []

    def added_lines(self, path: str) -> list:
        """[(line number in the head, text)] of the lines the head adds to the Mozilla file."""
        out = []
        for h in self.hunks(path):
            n = h["new_start"]
            for tag, text in h["lines"]:
                if tag == "+":
                    out.append((n, text))
                    n += 1
        return out

    # -- reading
    def read(self, path: str):
        return self.head.read(path)

    def cscan(self, path: str):
        """The CppScan of a file of the head."""
        if path not in self._scans:
            text = self.head.read(path)
            self._scans[path] = None if text is None else CppScan(path, text)
        return self._scans[path]

    # -- HOOKS.json
    def hook_entries(self) -> list:
        if self._hooks is None:
            self._hooks = load_hooks(self.series) if self.series else []
        return self._hooks

    def own_function_names(self) -> set:
        return {n for e in self.hook_entries() for n in _as_list(e.get("own_function"))}

    def renamed_names(self) -> set:
        return {n for e in self.hook_entries() for n in _as_list(e.get("renamed"))}

    def backport_files(self) -> set:
        """The Mozilla files a backport folder of the series owns (upstream code, outside the hook contract)."""
        if self._backports is None:
            self._backports = set()
            if self.series and (self.series / "SERIES").is_file():
                for f in (self.series / "SERIES").read_text(encoding="utf-8").split():
                    if (self.series / f / "BACKPORT.json").is_file() and (self.series / f / "MANIFEST.json").is_file():
                        data = json.loads((self.series / f / "MANIFEST.json").read_text(encoding="utf-8"))
                        self._backports.update(data.get("modified", []))
                        self._backports.update(data.get("removed", []))
        return self._backports


def _as_list(v) -> list:
    return [] if not v else ([v] if isinstance(v, str) else list(v))


def load_hooks(series: Path) -> list:
    """Every entry of every HOOKS.json of the series, each with its `folder`."""
    out = []
    series = Path(series)
    for p in sorted(series.glob("*/**/HOOKS.json")) + sorted(series.glob("*/HOOKS.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        folder = p.parent.relative_to(series).as_posix()
        top_names = []
        if isinstance(data, dict):
            top_names = _as_list(data.get("own_function"))
            data = data.get("hooks", [])
        for e in data:
            e = dict(e)
            e["folder"] = folder
            if top_names and not e.get("own_function"):
                e["own_function"] = top_names
            out.append(e)
    seen, uniq = set(), []
    for e in out:
        k = (e["folder"], e.get("file"), hc.norm(e.get("line", "")), hc.norm(e.get("removed", "")))
        if k not in seen:
            seen.add(k)
            uniq.append(e)
    return uniq


def folder_scope(series: Path, folders: list) -> set:
    """The paths a folder owns: the Mozilla files it modifies and the files it adds, from its MANIFEST.json."""
    scope = set()
    for f in folders:
        m = Path(series) / f / "MANIFEST.json"
        if not m.is_file():
            raise SystemExit("--folder %s: no %s" % (f, m))
        data = json.loads(m.read_text(encoding="utf-8"))
        scope.update(data.get("modified", []))
        scope.update(data.get("added", {}))
        scope.update(data.get("removed", []))
    return scope


# ============================================================================================ text
CLEAN_C = re.compile(
    r'''//[^\n]*|/\*.*?\*/|(?:u8|u|U|L)?R"([^()\\\s]{0,16})\(.*?\)\1"|"(?:\\.|[^"\\\n])*"'''
    r"""|'(?:\\[^\n]{1,8}?|[^'\\\n])'|^[ \t]*\#(?:\\\n|[^\n])*""", re.S | re.M)
CLEAN_JS = re.compile(r'''//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'|`(?:\\.|[^`\\])*`''', re.S)


def _blank_match(m) -> str:
    s = m.group(0)
    return " " * len(s) if "\n" not in s else re.sub(r"[^\n]", " ", s)


def blank(text: str, rx=CLEAN_C) -> str:
    """The text with comments, string and character literals and preprocessor lines turned to spaces,
    every offset and every newline where it was."""
    return rx.sub(_blank_match, text)


CLEAN_RS = re.compile(r'//[^\n]*|/\*.*?\*/|r(#*)".*?"\1|"(?:\\.|[^"\\])*"', re.S)


def blank_for(path: str, text: str) -> str:
    e = ext_of(path)
    return blank(text, CLEAN_JS if e in JS_EXT else (CLEAN_RS if e in RS_EXT else CLEAN_C))


def line_starts(text: str) -> list:
    out, p = [0], 0
    while True:
        p = text.find("\n", p)
        if p < 0:
            return out
        p += 1
        out.append(p)


def skip_template(s: str, i: int):
    """s[i] is '<' right after an identifier: the index after its matching '>' when what lies between looks
    like template arguments, else None."""
    d, j, n = 0, i, len(s)
    while j < n and j - i < 400:
        c = s[j]
        if c == "<":
            d += 1
        elif c == ">":
            d -= 1
            if d == 0:
                return j + 1
        elif not (c.isalnum() or c in "_:, *&.\n\t"):
            return None
        j += 1
    return None


def balanced(s: str, open_idx: int, limit: int = 30000):
    """s[open_idx] is '(': the index of its matching ')' or None."""
    d, n = 0, min(len(s), open_idx + limit)
    for j in range(open_idx, n):
        c = s[j]
        if c in "([{":
            d += 1
        elif c in ")]}":
            d -= 1
            if d == 0:
                return j if c == ")" else None
    return None


def split_args(s: str) -> list:
    """The top-level comma-separated parts of an argument or parameter list (empty list for none)."""
    parts, cur, d, i, n = [], [], 0, 0, len(s)
    while i < n:
        c = s[i]
        if c in "([{":
            d += 1
        elif c in ")]}":
            d -= 1
        elif c == "<" and i > 0 and (s[i - 1].isalnum() or s[i - 1] == "_") and d == 0:
            j = skip_template(s, i)
            if j:
                cur.append(s[i:j])
                i = j
                continue
        elif c == "," and d == 0:
            parts.append("".join(cur))
            cur = []
            i += 1
            continue
        cur.append(c)
        i += 1
    last = "".join(cur)
    if last.strip() or parts:
        parts.append(last)
    return [p.strip() for p in parts]


def param_range(params: str):
    """(min, max) number of arguments a parameter list takes; max None for a variadic one."""
    ps = split_args(params)
    if len(ps) == 1 and ps[0] in ("", "void"):
        return 0, 0
    lo = hi = 0
    for p in ps:
        if "..." in p:
            return lo, None
        hi += 1
        if not _has_default(p):
            lo = hi
    return lo, hi


def _has_default(p: str) -> bool:
    d = 0
    for i, c in enumerate(p):
        if c in "([{<":
            d += 1
        elif c in ")]}>":
            d -= 1
        elif c == "=" and d == 0 and p[i - 1:i + 1] not in ("==", "<=", ">=", "!=") and p[i + 1:i + 2] != "=":
            return True
    return False


# ============================================================================================ the C++ scan
@dataclass
class Frame:
    kind: str            # ns | class | extern
    names: list
    start: int
    end: int


@dataclass
class Decl:
    name: str
    kind: str                         # func | class | macro
    file: str
    line: int
    scope: list = field(default_factory=list)     # enclosing namespaces and classes, outermost first
    qual: list = field(default_factory=list)      # the qualifier written before the name (Foo:: of Foo::Bar)
    params: str = ""
    nmin: int = 0
    nmax: int | None = 0
    is_def: bool = False
    tail: str = ""                    # what follows the parameter list, up to ; or {


_ns_re = re.compile(r"(?:^|[\s;)}])(?:inline\s+)?namespace\s*(?:\[\[[^\]]*\]\]\s*)?([\w:]*)\s*$")
_extern_re = re.compile(r"(?:^|[\s;)}])extern\s*$")
_class_kw = re.compile(r"\b(class|struct|union)\s+")
_label_re = re.compile(r"^\s*(?:(?:public|private|protected)\s*:|case\b[^:]*:|default\s*:)\s*")


def _classify(stmt: str):
    s = re.sub(r"\s+", " ", stmt).strip()
    m = _ns_re.search(s)
    if m:
        return "ns", [x for x in m.group(1).split("::") if x] or [""]
    if _extern_re.search(s):
        return "extern", []
    if re.search(r"\benum\b", s):
        return "body", []
    ms = list(_class_kw.finditer(s))
    if ms:
        rest = s[ms[-1].end():]
        head = rest.split(":")[0]
        if "(" not in head.replace("::", "") and "=" not in head:
            n = re.match(r"(?:\w+(?:\([^)]*\))?\s+)*?(\w+)\s*(?:<[^{]*>\s*)?(?:final\s*)?(?::[^{;]*)?$", rest)
            return "class", [n.group(1) if n else ""]
    return "body", []


class CppScan:
    """The structure of a C/C++ file read from its text: the namespace and class blocks, the function bodies
    (skipped), `using namespace` lines, namespace aliases, includes and macros. Offsets are into `clean`."""

    def __init__(self, path: str, text: str):
        self.path, self.text = path, text
        self.clean = blank(text)
        self.lines = line_starts(text)
        self.includes = re.findall(r'^[ \t]*#[ \t]*include[ \t]*["<]([^">]+)[">]', text, re.M)
        self.macros = {m.group(1): m.group(3) for m in
                       re.finditer(r"^[ \t]*#[ \t]*define[ \t]+(\w+)(\(([^)]*)\))?", text, re.M)}
        self.frames: list = []
        self.bodies: list = []
        self._body_starts: list = []
        self._frames()
        self.usings = [(m.start(), [x for x in m.group(1).replace(" ", "").split("::") if x])
                       for m in re.finditer(r"\busing\s+namespace\s+([\w:\s]+?)\s*;", self.clean)]
        self.aliases = {m.group(1): [x for x in m.group(2).replace(" ", "").split("::") if x]
                        for m in re.finditer(r"\bnamespace\s+(\w+)\s*=\s*([\w:\s]+?)\s*;", self.clean)}
        self.using_decls = {m.group(2) for m in re.finditer(r"\busing\s+((?:\w+\s*::\s*)+)(\w+)\s*;", self.clean)}

    def _frames(self):
        c = self.clean
        stack, pos, depth, bstart = [], 0, 0, 0
        for m in re.finditer(r"[{};]", c):
            ch, i = m.group(), m.start()
            if depth:
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        self.bodies.append((bstart, i))
                        pos = i + 1
                continue
            if ch == ";":
                pos = i + 1
            elif ch == "{":
                kind, names = _classify(c[pos:i])
                if kind == "body":
                    depth, bstart = 1, i
                else:
                    f = Frame(kind, names, i, len(c))
                    stack.append(f)
                    self.frames.append(f)
                    pos = i + 1
            else:
                if stack:
                    stack.pop().end = i
                pos = i + 1
        self._body_starts = [b[0] for b in self.bodies]

    def line_of(self, off: int) -> int:
        return bisect.bisect_right(self.lines, off)

    def offset_of(self, line: int) -> tuple:
        a = self.lines[line - 1] if 0 < line <= len(self.lines) else len(self.clean)
        b = self.lines[line] if line < len(self.lines) else len(self.clean)
        return a, b

    def body_at(self, off: int):
        k = bisect.bisect_right(self._body_starts, off) - 1
        if k >= 0 and self.bodies[k][0] < off < self.bodies[k][1]:
            return self.bodies[k]
        return None

    def scope_at(self, off: int) -> list:
        names = []
        for f in self.frames:
            if f.start < off < f.end:
                names += f.names
        return [n for n in names if n]

    def namespaces_at(self, off: int) -> list:
        names = []
        for f in self.frames:
            if f.kind == "ns" and f.start < off < f.end:
                names += f.names
        return [n for n in names if n]

    def stmt_start(self, off: int) -> int:
        c = self.clean
        return max(c.rfind(";", 0, off), c.rfind("{", 0, off), c.rfind("}", 0, off)) + 1

    def prefix_at(self, off: int) -> str:
        s = self.clean[self.stmt_start(off):off]
        return _label_re.sub("", s)

    def enclosing_qualifier(self, off: int) -> list:
        """The qualifier of the function whose body holds off (Foo of Foo::Bar), [] when there is none."""
        b = self.body_at(off)
        if not b:
            return []
        s = self.clean[self.stmt_start(b[0]):b[0]]
        m = re.search(r"((?:~?\w+\s*(?:<[^<>]*>)?\s*::\s*)+)~?\w+\s*\(", s)
        return [x for x in re.findall(r"\w+", m.group(1))] if m else []


def split_qual(q: str) -> list:
    """`gfx::Foo::` -> ['gfx', 'Foo'] (templates dropped); a leading :: gives '::' first."""
    q = re.sub(r"<[^<>]*>", "", q)
    parts = [x for x in re.split(r"\s*::\s*", q.strip()) if x]
    return (["::"] if q.strip().startswith("::") else []) + parts


def _decl_at(scan: CppScan, qual_text: str, name: str, name_off: int):
    """The Decl for `name(` found at name_off at container level (None: a variable initialiser or not one)."""
    c = scan.clean
    prefix = scan.prefix_at(name_off - len(qual_text) if qual_text else name_off)
    if "=" in re.sub(r"[=!<>]=|operator\s*\S+", "", prefix):
        return None
    po = c.find("(", name_off)
    pc = balanced(c, po)
    if pc is None:
        return None
    params = c[po + 1:pc]
    m = re.search(r"[;{]", c[pc:pc + 2000])
    tail = c[pc + 1:pc + m.start()] if m else c[pc + 1:pc + 200]
    is_def = bool(m and m.group() == "{") or bool(re.search(r"=\s*default\b", tail))
    lo, hi = param_range(params)
    qual = [x for x in split_qual(qual_text) if x != "::"]
    return Decl(name, "func", scan.path, scan.line_of(name_off), scan.scope_at(name_off), qual, params,
                lo, hi, is_def, re.sub(r"\s+", " ", tail).strip())


def find_decls(scan: CppScan, names, only_lines: set | None = None) -> list:
    """Every declaration or definition, at namespace or class level, of the functions `names`; the classes and
    macros of those names too. only_lines: keep the functions on those lines only."""
    out = []
    if not names:
        return out
    alt = "|".join(sorted((re.escape(n) for n in names), key=len, reverse=True))
    c = scan.clean
    rx = re.compile(r"(?<![\w.])((?:(?:::)?\w+(?:<[^<>;{}()]*>)?\s*::\s*)*)(%s)\s*\(" % alt)
    for m in rx.finditer(c):
        off = m.start(2)
        k = m.start() - 1
        while k >= 0 and c[k] in " \t\n":
            k -= 1
        if k >= 1 and c[k - 1:k + 1] == "->":
            continue
        if scan.body_at(off):
            continue
        d = _decl_at(scan, m.group(1), m.group(2), off)
        if d and (only_lines is None or d.line in only_lines):
            out.append(d)
    for m in re.finditer(r"\b(?:class|struct|union)\s+(?:\w+(?:\([^)]*\))?\s+)*?(%s)\b\s*(?:final\s*)?[:{;]" % alt, c):
        if only_lines is None or scan.line_of(m.start(1)) in only_lines:
            out.append(Decl(m.group(1), "class", scan.path, scan.line_of(m.start(1)), scan.scope_at(m.start(1))))
    for n, p in scan.macros.items():
        if n in names:
            out.append(Decl(n, "macro", scan.path, 0))
    return out


# ============================================================================================ declarations index
class DeclIndex:
    """The declarations of the functions a set of calls names, from the files of ours of the head."""

    def __init__(self, proj: Project, names: set):
        self.names = names
        self.by_name: dict = {}
        self.js_by_name: dict = {}
        if not names:
            return
        rx = re.compile(r"\b(?:%s)\b" % "|".join(re.escape(n) for n in names))
        for p in proj.own:
            e = ext_of(p)
            if e in C_EXT:
                text = proj.read(p)
                if text is None or not rx.search(text):
                    continue
                for d in find_decls(proj.cscan(p), names):
                    self.by_name.setdefault(d.name, []).append(d)
            elif e in JS_EXT:
                text = proj.read(p)
                if text is None or not rx.search(text):
                    continue
                for d in js_decls(p, text, names):
                    self.js_by_name.setdefault(d.name, []).append(d)

    def add(self, d: Decl):
        self.by_name.setdefault(d.name, []).append(d)

    def get(self, name: str) -> list:
        return self.by_name.get(name, [])


JS_DECL = [
    r"(?:export\s+)?(?:async\s+)?function\s*\*?\s*(%s)\s*\(([^)]*)\)",
    r"(?:export\s+)?(?:const|let|var)\s+(%s)\s*=\s*(?:async\s*)?\(([^)]*)\)\s*=>",
    r"(?:export\s+)?(?:const|let|var)\s+(%s)\s*=\s*(?:async\s+)?function\s*\*?\s*\w*\s*\(([^)]*)\)",
    r"(?<![\w.$])(%s)\s*:\s*(?:async\s+)?function\s*\*?\s*\w*\s*\(([^)]*)\)",
    r"^[ \t]+(?:static\s+)?(?:async\s+)?(%s)\s*\(([^)]*)\)\s*\{",
]


def js_decls(path: str, text: str, names) -> list:
    clean = blank(text, CLEAN_JS)
    alt = "|".join(re.escape(n) for n in names)
    out = []
    for pat in JS_DECL:
        for m in re.finditer(pat % alt, clean, re.M):
            lo, hi = param_range(m.group(2))
            out.append(Decl(m.group(1), "func", path, clean.count("\n", 0, m.start()) + 1, [], [], m.group(2), lo, hi, True))
    for m in re.finditer(r"(?:export\s+)?class\s+(%s)\b" % alt, clean):
        out.append(Decl(m.group(1), "class", path, clean.count("\n", 0, m.start()) + 1))
    return out


# ============================================================================================ build files
class BuildIndex:
    """Which build file names a source: the moz.build and jar.mn of its directory and of every directory above,
    and the .mozbuild files of ours beside them. A text check: a quoted name, a name in parentheses of jar.mn."""

    def __init__(self, proj: Project):
        self.proj = proj
        self._text: dict = {}
        self._included: set | None = None

    def texts(self, d: str) -> str:
        if d not in self._text:
            parts = []
            for n in self.proj.head.listdir(d):
                if n in ("moz.build", "jar.mn") or n.endswith((".build", ".mozbuild", ".gyp", ".gypi")):
                    t = self.proj.read((d + "/" if d else "") + n)
                    if t:
                        parts.append(t)
            self._text[d] = "\n".join(parts)
        return self._text[d]

    def named_by(self, path: str):
        """The build file text that names the file, or None."""
        d, rel = dir_of(path), base_of(path)
        pat_tail = r"(?![\w.\-])"
        while True:
            t = self.texts(d)
            if t and re.search(r"(?<![\w.\-])" + re.escape(rel) + pat_tail, t):
                return (d + "/" if d else "") + "moz.build"
            if not d:
                return None
            rel = base_of(d) + "/" + rel
            d = dir_of(d)

    def included_by_source(self, path: str) -> bool:
        """A file that another file of ours, or a Mozilla file the head changes, #includes (the C++ include, or the
        preprocessor's `#include init/x.js`) is built or shipped with it."""
        if self._included is None:
            self._included = set()
            for p in list(self.proj.own) + list(self.proj.mozilla):
                if ext_of(p) in C_EXT | JS_EXT | {"cpp", "in", "inc", "css", "html", "xhtml", "yaml"} or base_of(p) == "all.js":
                    t = self.proj.read(p)
                    if t:
                        for inc in re.findall(r'^[ \t]*[#%][ \t]*include[ \t]+["<]?([^\s">]+)', t, re.M):
                            self._included.add(base_of(inc))
        return base_of(path) in self._included

    def compiled(self, path: str) -> bool:
        return self.named_by(path) is not None or self.included_by_source(path)


# ============================================================================================ includes
class IncludeGraph:
    """What a file reaches by #include, through the files whose text we hold: ours and the Mozilla files the
    head changes (a header of Mozilla's the head leaves alone cannot include ours)."""

    def __init__(self, proj: Project):
        self.proj = proj
        known = set(proj.own) | set(proj.mozilla)
        self.known = known
        self.by_base: dict = {}
        self._by_base_all = None
        for p in known:
            self.by_base.setdefault(base_of(p), []).append(p)

    def resolve(self, includer: str, inc: str) -> list:
        if inc in self.known:
            return [inc]
        rel = (dir_of(includer) + "/" if dir_of(includer) else "") + inc
        if rel in self.known:
            return [rel]
        return list(self.by_base.get(base_of(inc), []))

    def reaches(self, host: str, targets, cap: int = 30000):
        """True / False: can the host see one of the target files by #include? First through the files whose text we
        hold; then through every header of the head, an include resolved by its basename (every file of that name:
        an over-approximation, so False is certain and True is not)."""
        targets = set(targets)
        if targets & self.reach(host):
            return True
        if self._by_base_all is None:
            self._by_base_all = {}
            for q in self.proj.head.all_paths():
                if ext_of(q) in C_EXT or ext_of(q) in ("inc", "tbl"):
                    self._by_base_all.setdefault(base_of(q), []).append(q)
        seen, todo = {host}, [host]
        while todo and len(seen) < cap:
            p = todo.pop()
            text = self.proj.read(p)
            if text is None:
                continue
            for inc in re.findall(r'^\s*#\s*include\s*["<]([^">]+)[">]', text, re.M):
                for q in self.resolve(p, inc) + self._by_base_all.get(base_of(inc), []):
                    if q in targets:
                        return True
                    if q not in seen:
                        seen.add(q)
                        todo.append(q)
        return False

    def reach(self, path: str) -> set:
        seen, todo = {path}, [path]
        while todo:
            p = todo.pop()
            if ext_of(p) not in C_EXT:
                continue
            scan = self.proj.cscan(p)
            if not scan:
                continue
            for inc in scan.includes:
                for q in self.resolve(p, inc):
                    if q not in seen:
                        seen.add(q)
                        todo.append(q)
        return seen


# ============================================================================================ 1. hook links
def call_regex(extra: set) -> re.Pattern:
    more = "".join("|" + re.escape(n) for n in sorted(extra))
    return re.compile(r"(?<![\w$])(?P<q>(?:::)?(?:[A-Za-z_]\w*(?:<[^<>()]*>)?\s*::\s*)*)"
                      r"(?P<n>(?:nr_)?[Ss]tealth\w*" + more + r")\s*\(")


@dataclass
class Site:
    host: str
    line: int
    name: str
    qual: list
    member: bool
    kind: str            # call | decl | skip
    argc: int | None
    off: int


def collect_sites(proj: Project, host: str, rx) -> list:
    """The calls of ours the head adds to a Mozilla file, and (as kind decl) the declarations of ours it adds."""
    text = proj.read(host)
    if text is None:
        return []
    added = proj.added_lines(host)
    if not any(rx.search(t) for _, t in added):
        return []
    scan = proj.cscan(host)
    c = scan.clean
    out = []
    for ln, _ in added:
        a, b = scan.offset_of(ln)
        for m in rx.finditer(c, a, b):
            off, qs = m.start("n"), m.start()
            k = qs - 1
            while k >= 0 and c[k] in " \t\n":
                k -= 1
            member = k >= 0 and (c[k] == "." or (k >= 1 and c[k - 1:k + 1] == "->"))
            prefix = scan.prefix_at(qs)
            po = c.find("(", off)
            pc = balanced(c, po)
            argc = None if pc is None else len(split_args(c[po + 1:pc]))
            if scan.body_at(off) is None:
                kind = "skip" if "=" in re.sub(r"[=!<>]=", "", prefix) else "decl"
            else:
                p = prefix.strip()
                words = re.findall(r"\w+", p)
                vardecl = (bool(words) and not member and words[-1] not in KEYWORDS
                           and re.fullmatch(r"[\w:<>,\s*&]+", p) is not None)
                kind = "skip" if vardecl else "call"
            out.append(Site(host, ln, m.group("n"), split_qual(m.group("q")), member, kind, argc, off))
    return out


def _namespace_resolves(decl_scope: list, qual: list, scan: CppScan, off: int) -> bool:
    """Can `qual::name` written at off reach a declaration whose scope is decl_scope?"""
    absolute = qual[:1] == ["::"]
    q = [x for x in qual if x != "::"]
    if q and q[0] in scan.aliases:
        q = scan.aliases[q[0]] + q[1:]
    if absolute:
        return decl_scope == q
    enclosing = scan.namespaces_at(off) + scan.enclosing_qualifier(off)
    cands = [enclosing[:i] for i in range(len(enclosing), -1, -1)]
    for uo, u in scan.usings:
        if uo < off:
            cands.append(u)
            cands += [enclosing[:i] + u for i in range(len(enclosing), -1, -1)]
    return any(s + q == decl_scope for s in cands)


def check_hook_links(proj: Project) -> list:
    out = []
    extra = proj.own_function_names()
    rx = call_regex(extra)
    hosts = [p for p in proj.mozilla if proj.in_scope(p)]
    sites = []
    graph = IncludeGraph(proj)
    c_hosts = [p for p in hosts if ext_of(p) in C_EXT]
    js_hosts = [p for p in hosts if ext_of(p) in JS_EXT]
    for p in c_hosts:
        for s in collect_sites(proj, p, rx):
            sites.append(s)
    calls = [s for s in sites if s.kind == "call"]
    proj.stats[1] = "%d calls and %d declarations of ours in %d host files" % (
        len(calls), sum(1 for s in sites if s.kind == "decl"), len({s.host for s in sites}))
    # the declarations the head adds to Mozilla files count as declarations of ours
    names = {s.name for s in sites}
    idx = DeclIndex(proj, names)
    for p in c_hosts:
        lines = {ln for ln, _ in proj.added_lines(p)}
        if any(s.host == p and s.kind == "decl" for s in sites):
            scan = proj.cscan(p)
            for d in find_decls(scan, {s.name for s in sites if s.host == p and s.kind == "decl"}, only_lines=lines):
                idx.add(d)
    builds = BuildIndex(proj)
    seen = set()
    for s in calls:
        key = (s.host, s.name, s.line)
        if key in seen:
            continue
        seen.add(key)
        out += _link_one(proj, idx, graph, builds, s)
    out += _check_added_includes(proj, c_hosts, graph)
    out += _check_js_links(proj, js_hosts, extra)
    return out


def _link_one(proj, idx, graph, builds, s: Site) -> list:
    out = []
    where = "%s:%d" % (s.host, s.line)
    decls = idx.get(s.name)
    funcs = [d for d in decls if d.kind == "func"]
    classes = [d for d in decls if d.kind in ("class", "macro")]
    declarations = [d for d in funcs if not d.qual or not d.is_def or d.file == s.host]
    if not decls:
        out.append(Finding(FAIL, 1, where, "%s is called and no declaration of it exists in a header or source of ours" % s.name,
                           "declare it in a header of ours and include the header in the host file, or fix the name"))
        return out
    if classes and not funcs:
        return out                      # a class or macro of that name: constructor or expansion, not checked further
    if not declarations:
        out.append(Finding(FAIL, 1, where, "%s has a definition (%s) and no declaration: Mozilla's file cannot see it" % (s.name, os_path(funcs[0])),
                           "declare it in a header of ours and include the header in the host file"))
        return out
    # (b) the host reaches a declaration (a member call reaches its class through the object)
    if not s.member:
        files = sorted({d.file for d in declarations})
        if s.host not in files:
            if not graph.reaches(s.host, files):
                out.append(Finding(FAIL, 1, where, "%s is declared in %s and the host file does not include it (directly, or through a header it includes)"
                                   % (s.name, ", ".join(files[:3])),
                                   'add `#include "%s"  // STEALTH-HOOK(<folder>)` to the host file' % base_of(files[0])))
    # (c) a definition, built
    defs = [d for d in funcs if d.is_def]
    if not defs:
        out.append(Finding(FAIL, 1, where, "%s has a declaration but no body in a file of ours" % s.name,
                           "write the body in a .cpp of ours or inline in its header"))
    else:
        ok = False
        unbuilt = []
        for d in defs:
            if d.file == s.host or ext_of(d.file) in HEADER_EXT or d.file in proj.mozilla:
                ok = True
            elif ext_of(d.file) in C_SOURCE_EXT:
                if builds.compiled(d.file):
                    ok = True
                else:
                    unbuilt.append(d.file)
            else:
                ok = True
        if not ok:
            out.append(Finding(FAIL, 1, where, "%s is defined only in %s, which no moz.build names" % (s.name, ", ".join(sorted(set(unbuilt))[:3])),
                               "add the file to SOURCES or UNIFIED_SOURCES of its directory's moz.build"))
    # (d) the argument count
    if s.argc is None:
        out.append(Finding(WARN, 1, where, "the arguments of %s do not close (unbalanced parentheses in the text)" % s.name))
    elif funcs:
        argc = 0 if s.argc == 1 and _empty_args(proj, s) else s.argc
        okc = any(d.nmin <= argc and (d.nmax is None or argc <= d.nmax) for d in funcs)
        if not okc:
            sig = "; ".join(sorted({"%s takes %s" % (os_path(d), _rng(d)) for d in funcs}))
            out.append(Finding(FAIL, 1, where, "%s is called with %d argument(s) and no declaration takes that many (%s)" % (s.name, argc, sig),
                               "fix the call or the declaration"))
    # (e) the namespace
    if not s.member and funcs:
        scan = proj.cscan(s.host)
        dscopes = [d.scope for d in declarations if not d.qual] or [d.scope for d in funcs]
        if not any(_namespace_resolves(sc, s.qual, scan, s.off) for sc in dscopes):
            adl = not s.qual and _args_may_adl(proj, s)
            where_decl = "::".join(dscopes[0]) or "the global namespace"
            if adl:
                out.append(Finding(WARN, 1, where, "%s lives in %s, which the call site neither names, encloses nor opens; argument-dependent lookup may still find it"
                                   % (s.name, where_decl)))
            else:
                out.append(Finding(FAIL, 1, where, "%s lives in %s, which the call site neither names, encloses nor opens with `using`" % (s.name, where_decl),
                                   "qualify the call (%s::%s) or open the namespace" % (where_decl, s.name)))
    return out


def os_path(d: Decl) -> str:
    return "%s:%d" % (d.file, d.line)


def _rng(d: Decl) -> str:
    if d.nmax is None:
        return "%d or more" % d.nmin
    return str(d.nmin) if d.nmin == d.nmax else "%d to %d" % (d.nmin, d.nmax)


def _args_text(proj: Project, s: Site) -> str:
    scan = proj.cscan(s.host)
    po = scan.clean.find("(", s.off)
    pc = balanced(scan.clean, po)
    return "" if pc is None else scan.clean[po + 1:pc]


def _empty_args(proj: Project, s: Site) -> bool:
    return not _args_text(proj, s).strip()


def _args_may_adl(proj: Project, s: Site) -> bool:
    """Argument-dependent lookup can find a function in the namespace of an argument's class: only when some
    argument names something (a variable, a call), not when they are all literals."""
    t = re.sub(r"\b(?:true|false|nullptr|NULL|sizeof|static_cast|reinterpret_cast|int|long|float|double|char|bool)\b", " ", _args_text(proj, s))
    t = re.sub(r"\b\d[\w.']*", " ", t)
    return re.search(r"[A-Za-z_]", t) is not None


def _check_added_includes(proj: Project, hosts: list, graph: IncludeGraph) -> list:
    """An include of ours the head adds to a Mozilla file must name a header that exists in the head."""
    out = []
    for p in hosts:
        for ln, t in proj.added_lines(p):
            m = re.match(r'^\s*#\s*include\s*"([^"]+)"', t)
            if not m:
                continue
            inc = m.group(1)
            if not re.match(r"(?:nr_)?[Ss]tealth|Test[Ss]tealth", base_of(inc)) and base_of(inc) not in graph.by_base:
                continue
            if not graph.resolve(p, inc) and not proj.head.exists(inc):
                out.append(Finding(FAIL, 1, "%s:%d" % (p, ln), 'the added include "%s" names no file of ours in the head' % inc,
                                   "add the header or fix the include path"))
    return out


def _check_js_links(proj: Project, hosts: list, extra: set) -> list:
    out = []
    rx = re.compile(r"(?<![\w$.])(?P<n>(?:[Ss]tealth\w*%s))\s*\(" % "".join("|" + re.escape(n) for n in sorted(extra)))
    rxm = re.compile(r"(?<![\w$])(?:\w+\s*\.\s*)+(?P<n>[Ss]tealth\w*)\s*\(")
    own_js = [p for p in proj.own if ext_of(p) in JS_EXT]
    for p in hosts:
        text = proj.read(p)
        if text is None:
            continue
        clean = blank(text, CLEAN_JS)
        ls = line_starts(text)
        for ln, raw in proj.added_lines(p):
            if not re.search(r"[Ss]tealth", raw):
                continue
            a = ls[ln - 1] if ln - 1 < len(ls) else len(clean)
            b = ls[ln] if ln < len(ls) else len(clean)
            for m in rx.finditer(clean, a, b):
                n = m.group("n")
                where = "%s:%d" % (p, ln)
                prefix = clean[max(0, clean.rfind("\n", 0, m.start()) + 1):m.start()]
                if re.search(r"\bfunction\s*\*?\s*$", prefix):
                    continue
                po = m.end() - 1
                pc = balanced(clean, po)
                argc = None if pc is None else len(split_args(clean[po + 1:pc]))
                decls = [d for q in own_js for d in js_decls(q, proj.read(q) or "", {n})]
                local = js_decls(p, text, {n})
                imported = re.search(r"(?<![\w$])%s\b(?!\s*\()" % re.escape(n), re.sub(r"\n", " ", clean[:a] + " " + clean[b:])) is not None
                if not decls and not local:
                    out.append(Finding(FAIL, 1, where, "%s is called and no module of ours declares it" % n, "declare and export it in a module of ours"))
                    continue
                if not local and not imported:
                    out.append(Finding(FAIL, 1, where, "%s is called and the host module neither imports nor declares it" % n,
                                       "import it (import { %s } or ChromeUtils.importESModule) in the host module" % n))
                allds = decls + local
                if argc is not None and not any(d.kind == "class" or (d.nmin <= argc and (d.nmax is None or argc <= d.nmax)) for d in allds):
                    out.append(Finding(FAIL, 1, where, "%s is called with %d argument(s) and no declaration takes that many" % (n, argc),
                                       "fix the call or the declaration"))
            for m in rxm.finditer(clean, a, b):
                n = m.group("n")
                if not any(js_decls(q, proj.read(q) or "", {n}) for q in own_js):
                    out.append(Finding(WARN, 1, "%s:%d" % (p, ln), "%s is called as a member and no module of ours declares a function of that name" % n))
    return out


# ============================================================================================ 2. rename consistency
def _norm_params(params: str) -> tuple:
    """(full, types only) of a parameter list: whitespace squeezed, defaults dropped; the second without the names."""
    full, types = [], []
    for p in split_args(params):
        d = p
        k = _default_at(p)
        if k is not None:
            d = p[:k]
        d = re.sub(r"\s+", " ", d).strip()
        d = re.sub(r"\s*([*&,<>:])\s*", r"\1", d)
        full.append(d)
        m = re.match(r"^(.*?[\w>*&\]])\s*(?<![*&:])\b(\w+)$", d) if d else None
        t = d
        if m and m.group(2) not in ("int", "char", "long", "short", "bool", "float", "double", "void", "unsigned",
                                    "signed", "auto", "const", "size_t", "string") and m.group(1).strip() not in ("unsigned", "signed", "const", "struct", "class", "enum"):
            t = m.group(1).strip()
        types.append(t)
    if full == ["void"]:
        full, types = [], []
    return tuple(full), tuple(types)


def _default_at(p: str):
    d = 0
    for i, c in enumerate(p):
        if c in "([{<":
            d += 1
        elif c in ")]}>":
            d -= 1
        elif c == "=" and d == 0 and p[i - 1:i + 1] not in ("==", "<=", ">=", "!=") and p[i + 1:i + 2] != "=":
            return i
    return None


def _tail_flags(tail: str) -> set:
    return {w for w in re.findall(r"\bconst\b|\bnoexcept\b|\boverride\b|&&|&", tail) if w}


def _params_same(a: Decl, b: Decl) -> bool:
    fa, ta = _norm_params(a.params)
    fb, tb = _norm_params(b.params)
    if not (fa == fb or ta == tb):
        return False
    ka, kb = _tail_flags(a.tail), _tail_flags(b.tail)
    if a.is_def or b.is_def:
        ka.discard("override")
        kb.discard("override")
    return ka == kb


def check_rename(proj: Project) -> list:
    out = []
    renamed = proj.renamed_names()
    hosts = [p for p in proj.mozilla if proj.in_scope(p) and ext_of(p) in C_EXT]
    rx = re.compile(r"(?<![\w.])(?P<q>(?:(?:::)?\w+(?:<[^<>;{}()]*>)?\s*::\s*)*)(?P<n>\w+_Mozilla%s)\s*\(" %
                    "".join("|" + re.escape(n) for n in sorted(renamed)))
    defs, calls, decls = [], [], []
    allow = {(e.get("file"), hc.norm(e.get("line", ""))) for e in proj.hook_entries() if e.get("calls_mozilla")}
    for p in hosts:
        added = proj.added_lines(p)
        if not any(rx.search(t) for _, t in added):
            continue
        scan = proj.cscan(p)
        c = scan.clean
        lines = dict(added)
        for ln, _ in added:
            a, b = scan.offset_of(ln)
            for m in rx.finditer(c, a, b):
                off = m.start("n")
                k = m.start() - 1
                while k >= 0 and c[k] in " \t\n":
                    k -= 1
                if (k >= 0 and c[k] == ".") or (k >= 1 and c[k - 1:k + 1] == "->"):
                    calls.append((p, ln, m.group("n"), lines[ln]))
                    continue
                if scan.body_at(off):
                    calls.append((p, ln, m.group("n"), lines[ln]))
                    continue
                d = _decl_at(scan, m.group("q"), m.group("n"), off)
                if d is None:
                    continue
                (defs if d.is_def else decls).append(d)
    # direct callers in Mozilla files
    for p, ln, n, text in calls:
        if (p, hc.norm(text)) in allow:
            continue
        out.append(Finding(FAIL, 2, "%s:%d" % (p, ln), "%s, the renamed body of a Mozilla function, is called from a Mozilla file" % n,
                           "call the original name (ours wraps it), or record the exception in HOOKS.json (`calls_mozilla`)"))
    own_index = DeclIndex(proj, {d.name[:-len("_Mozilla")] if d.name.endswith("_Mozilla") else d.name for d in defs + decls})
    headers = [q for q in proj.mozilla if ext_of(q) in HEADER_EXT]
    for d in defs:
        orig = d.name[:-len("_Mozilla")] if d.name.endswith("_Mozilla") else d.name
        where = "%s:%d" % (d.file, d.line)
        cls = d.qual[-1] if d.qual else None
        # (a) the declaration in the class header is renamed too
        if cls:
            found = False
            for hp in headers:
                scan = proj.cscan(hp)
                if scan and d.name in scan.clean:
                    for hd in find_decls(scan, {d.name}):
                        if hd.scope and hd.scope[-1] == cls:
                            found = True
            if not found:
                out.append(Finding(FAIL, 2, where, "%s::%s is defined and no changed Mozilla header declares %s in class %s" % (cls, d.name, d.name, cls),
                                   "rename the declaration in the class header too (and declare %s there once, for ours)" % orig))
        # (b) ours defines the original name with the same parameters
        cands = [x for x in own_index.get(orig) if x.kind == "func" and (not cls or (x.qual and x.qual[-1] == cls) or (x.scope and x.scope[-1] == cls))
                 and x.file not in proj.mozilla]
        if not cands:
            out.append(Finding(FAIL, 2, where, "%s is renamed %s and no file of ours defines %s%s" % (orig, d.name, (cls + "::") if cls else "", orig),
                               "define %s in a file of ours with the parameters of the Mozilla body" % orig))
        elif not any(_params_same(d, x) for x in cands):
            out.append(Finding(FAIL, 2, where, "%s(%s)%s differs from ours %s(%s)%s (%s)" % (
                d.name, re.sub(r"\s+", " ", d.params).strip(), (" " + d.tail) if d.tail else "", orig,
                re.sub(r"\s+", " ", cands[0].params).strip(), (" " + cands[0].tail) if cands[0].tail else "", os_path(cands[0])),
                "make the parameter list and the trailing const/noexcept of ours equal to Mozilla's"))
    return out


# ============================================================================================ 3. Mozilla tokens
THREE_FORMS = ("wrap-expression", "wrap-function", "declared-value")


def _code_norm(line: str) -> str:
    code, mk, _ = hc.marker_split(line)
    return hc.norm(code if mk is not None else line)


def mozilla_line_changes(proj: Project) -> list:
    """Every Mozilla line the head rewrites or removes: dicts (file, old_line, text, allowed, why)."""
    proj._load()
    # the contract's own reading of the head's diff gives the form of each rewrite
    allowed: dict = {}
    for p in proj.mozilla:
        f = proj._patch.get(p)
        if not f:
            continue
        text = "diff --git a/%s b/%s\n--- a/%s\n+++ b/%s\n" % (p, p, p, p)
        for h in f["hunks"]:
            text += "@@ -%d,%d +%d,%d @@ %s\n" % (h["old_start"], h["old_len"], h["new_start"], h["new_len"], h["section"])
            text += "".join("%s%s\n" % (t, x) for t, x in h["lines"])
        try:
            hooks, _ = hc.analyse_patch("head", text)
        except Exception:                                    # the contract's parser failing is not a finding of ours
            continue
        for hk in hooks:
            if hk.kind == "rewrite" and hk.form in THREE_FORMS and hk.removed:
                for r in hk.removed.split("\n"):
                    allowed[(p, hc.norm(r))] = hk.form
    recorded: dict = {}
    exceptions: dict = {}
    for e in proj.hook_entries():
        key = (e.get("file"), hc.norm(e.get("removed", "") or ""))
        if e.get("kind") == "rewrite" and e.get("form") in THREE_FORMS and key[1]:
            recorded[key] = e["form"]
        if e.get("exception"):
            exceptions[key] = e["exception"]
    out = []
    for p in proj.mozilla:
        for h in proj.hunks(p):
            rem = [x for t, x in h["lines"] if t == "-"]
            add = [x for t, x in h["lines"] if t == "+"]
            if not rem:
                continue
            rn, an = [_code_norm(x) for x in rem], [_code_norm(x) for x in add]
            sm = difflib.SequenceMatcher(None, rn, an, autojunk=False)
            kept = set()
            for tag, i1, i2, _, _ in sm.get_opcodes():
                if tag == "equal":
                    kept.update(range(i1, i2))
            for i, x in enumerate(rem):
                if i in kept:
                    continue
                key = (p, hc.norm(x))
                why = ""
                form = ""
                if key in allowed or key in recorded:
                    form, why = recorded.get(key) or allowed[key], "form"
                elif key in exceptions:
                    form, why = "exception", "exception"
                out.append({"file": p, "old_line": h["old_start"] + i, "text": x.strip(), "allowed": why,
                            "form": form, "exception": exceptions.get(key, "")})
    for p in proj.deleted:
        if not proj.in_scope(p):
            continue
        t = proj.tag.read(p) or ""
        n = t.count("\n") + (1 if t and not t.endswith("\n") else 0)
        ex = {(e.get("file")): e["exception"] for e in proj.hook_entries() if e.get("exception") and e.get("kind") in ("file", "delete")}
        out.append({"file": p, "old_line": 1, "text": "<whole file deleted: %d lines>" % n, "allowed": "exception" if p in ex else "",
                    "form": "exception" if p in ex else "", "exception": ex.get(p, ""), "lines": n})
    skipped = proj.backport_files()
    proj.stats[3] = "%d Mozilla files of backport folders left out" % len(skipped & set(proj.mozilla + proj.deleted)) if skipped else ""
    return [o for o in out if proj.in_scope(o["file"]) and o["file"] not in skipped]


def check_mozilla_tokens(proj: Project):
    """-> (findings, changes): the findings for the lines no form or exception covers, and every line changed."""
    changes = mozilla_line_changes(proj)
    out = []
    for c in changes:
        if c["allowed"] == "form":
            continue
        where = "%s:%d" % (c["file"], c["old_line"])
        if c["allowed"] == "exception":
            if not re.search(r"\bpm\b", c["exception"], re.I):
                out.append(Finding(FAIL, 3, where, "the exception on this line does not say the pm approved it (`%s`)" % c["exception"][:60],
                                   "write the approval into the `exception` field of HOOKS.json"))
            continue
        out.append(Finding(FAIL, 3, where, "Mozilla line changed or removed: %s" % c["text"][:100],
                           "keep Mozilla's line as it is and put the hook beside it (wrap-expression, wrap-function or declared-value), or record an exception with the pm's approval"))
    return out, changes


# ============================================================================================ 4. equivalence
_C_FAMILY = {"cpp", "cc", "cxx", "c", "h", "hpp", "mm", "m", "js", "mjs", "jsm", "jsx", "ts", "java", "kt", "idl", "ipdl",
             "ipdlh", "webidl", "css", "glsl", "vert", "frag", "comp", "go", "swift", "rs"}
_HASH_FAMILY = {"py", "build", "mozbuild", "toml", "yaml", "yml", "sh", "cfg", "conf", "gitignore", "mozconfig", "in",
                "ini", "mk", "cmake", "configure", "gyp", "gypi", "list", "inc"}
_TOK_C = re.compile(r'''(?P<c>//[^\n]*|/\*.*?\*/)|(?P<s>(?:u8|u|U|L)?R"(?P<d>[^()\\\s]{0,16})\(.*?\)(?P=d)"|"(?:\\.|[^"\\\n])*"'''
                    r"""|'(?:\\[^\n]{1,8}?|[^'\\\n])'|`(?:\\.|[^`\\])*`)|(?P<w>[A-Za-z_$][\w$]*|\d[\w.]*)|(?P<o>\S)""", re.S)
_TOK_HASH = re.compile(r'''(?P<c>\#[^\n]*)|(?P<s>\'\'\'.*?\'\'\'|""".*?"""|"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*')|(?P<w>[A-Za-z_$][\w$]*|\d[\w.]*)|(?P<o>\S)''', re.S)
_INC_C = re.compile(r"^[ \t]*#[ \t]*(?:include|import)\b[^\n]*$", re.M)
_INC_JS = re.compile(r"^[ \t]*import\b[^;]*?\bfrom\s*[\"'][^\"']+[\"'][ \t]*;?|^[ \t]*import[ \t]*[\"'][^\"']+[\"][ \t]*;?|^[^\n]*ChromeUtils\.(?:importESModule|import)\([^\n]*$", re.M)
_INC_RS = re.compile(r"^[ \t]*(?:pub(?:\([^)]*\))?[ \t]+)?(?:use[ \t][^;]*|mod[ \t]+\w+[ \t]*|extern[ \t]+crate[ \t]+[^;]*);", re.M)
_INC_PY = re.compile(r"^[ \t]*(?:import|from)[ \t]+[^\n]*$", re.M)


def family(path: str) -> str:
    e = ext_of(path)
    if base_of(path) == "moz.build":
        return "hash"
    if e in _C_FAMILY:
        return "c"
    if e in _HASH_FAMILY:
        return "hash"
    return "words"


def tokens(path: str, text: str, drop_includes: bool = False) -> list:
    fam, e = family(path), ext_of(path)
    if drop_includes:
        if e in ("js", "mjs", "jsm", "jsx", "ts"):
            text = _INC_JS.sub("", text)
        elif e == "rs":
            text = _INC_RS.sub("", text)
        elif e == "py":
            text = _INC_PY.sub("", text)
        elif fam == "c":
            text = _INC_C.sub("", text)
    if fam == "words":
        return text.split()
    rx = _TOK_C if fam == "c" else _TOK_HASH
    return [m.group(0) for m in rx.finditer(text) if m.lastgroup not in ("c", "d")]


def classify_pair(path: str, a: str | None, b: str | None) -> dict:
    """The class of one file's change between two trees."""
    if a is None:
        return {"file": path, "class": "added", "runs": 0, "tokens": len(tokens(path, b or ""))}
    if b is None:
        return {"file": path, "class": "removed", "runs": 0, "tokens": len(tokens(path, a))}
    if "\0" in a or "\0" in b:
        return {"file": path, "class": "changed", "runs": 1, "tokens": 0, "binary": True}
    ta, tb = tokens(path, a), tokens(path, b)
    if ta == tb:
        return {"file": path, "class": "identical", "runs": 0, "tokens": len(tb)}
    if tokens(path, a, True) == tokens(path, b, True):
        return {"file": path, "class": "include-order", "runs": 0, "tokens": len(tb)}
    i = 0
    while i < len(ta) and i < len(tb) and ta[i] == tb[i]:
        i += 1
    j = 0
    while j < len(ta) - i and j < len(tb) - i and ta[-1 - j] == tb[-1 - j]:
        j += 1
    sa, sb = ta[i:len(ta) - j], tb[i:len(tb) - j]
    if len(sa) * len(sb) > 4_000_000:
        runs = 1
    else:
        runs = sum(1 for t, *_ in difflib.SequenceMatcher(None, sa, sb, autojunk=False).get_opcodes() if t != "equal")
    return {"file": path, "class": "changed", "runs": max(runs, 1), "tokens": len(tb)}


def check_equivalence(proj: Project) -> list:
    """Per file that differs between base and head: its class. Needs proj.base."""
    status, _ = diff_trees(proj.base, proj.head)
    tag_has = lambda p: proj.tag.exists(p)       # noqa: E731
    rows = []
    for p in sorted(status):
        if not proj.in_scope(p):
            continue
        a, b = proj.base.read(p), proj.head.read(p)
        if (a is not None and b is not None) and (proj.base.read_bytes(p) is None or proj.head.read_bytes(p) is None):
            continue
        row = classify_pair(p, a, b)
        row["owner"] = "mozilla" if tag_has(p) else "ours"
        row["status"] = status[p]
        rows.append(row)
    return rows


# ============================================================================================ 5. restored files
_IDENT = re.compile(r"[A-Za-z_]\w{3,}")


OURS_NAME = re.compile(r"^(?:Stealth|stealth_|nr_stealth_)")


def check_restored(proj: Project) -> list:
    """A Mozilla file the base changed and the head leaves alone is the tag's, byte for byte; and nothing in the
    head uses a name only the old hunk of that file introduced."""
    out = []
    status, patch = diff_trees(proj.tag, proj.base)
    base_patch = {f["file"]: f for f in hc.parse_patch(patch)}
    restored = [p for p, s in sorted(status.items())
                if s in ("M", "D") and proj.in_scope(p) and proj.head.read_bytes(p) == proj.tag.read_bytes(p)]
    introduced: dict = {}
    for p in restored:
        have = set(_IDENT.findall(proj.tag.read(p) or ""))
        names = set()
        for h in (base_patch.get(p) or {"hunks": []})["hunks"]:
            for t, x in h["lines"]:
                if t == "+":
                    names.update(_IDENT.findall(blank_for(p, x)))
        for n in names - have:
            introduced.setdefault(n, []).append(p)
    proj.stats[5] = "%d restored files, %d names their old hunks introduced" % (len(restored), len(introduced))
    if not introduced:
        return out
    names = set(introduced)
    texts = {}
    for q in list(proj.own) + list(proj.mozilla):
        if q in restored or ext_of(q) not in C_EXT | JS_EXT | RS_EXT:
            continue
        t = proj.read(q)
        if t:
            texts[q] = blank_for(q, t)
    uses: dict = {}
    for q, t in texts.items():
        for n in set(_IDENT.findall(t)) & names:
            uses.setdefault(n, []).append(q)
    # Only names of ours: Stealth-named, or in no line of Mozilla's tag (a name the tag already contains, such as
    # nsPresContext or CanvasUtils, is Mozilla's whatever the old hunk of the restored file did with it).
    maybe = {n for n in uses if not OURS_NAME.match(n)}
    for n in proj.tag.contains_names(maybe):
        del uses[n]
    own = set(proj.own)
    for n, files in sorted(uses.items()):
        pat = re.compile(r"\b(?:class|struct|enum|union|namespace|using|typedef)\s+(?:\w+\s+)*%(n)s\b|#\s*define\s+%(n)s\b|"
                         r"(?:^|[\s*&>~:])%(n)s\s*\([^;{}]*\)\s*(?:const\s*)?(?:noexcept\s*)?(?:override\s*)?[;{]|"
                         r"[\w>*&]\s+%(n)s\s*(?:=[^=]|;|\[|\{)|\b(?:function|const|let|var|fn)\s+%(n)s\b" % {"n": re.escape(n)}, re.M)
        if any(pat.search(texts[q]) for q in files if q in own):
            continue                      # a file of ours defines it: the old hunk's declaration is no longer needed
        for q in files:
            out.append(Finding(FAIL, 5, q, "uses `%s`, which only the old hunk of %s introduced; that file is the tag's again and no file of ours defines `%s`"
                               % (n, ", ".join(introduced[n][:2]), n),
                               "define it in a file of ours, or remove the use"))
    return out


# ============================================================================================ 6. our files

def check_our_files(proj: Project, tree_path: str | None = None) -> list:
    out = []
    builds = BuildIndex(proj)
    own = [p for p in proj.own]
    for p in own:
        if not proj.in_scope(p):
            continue
        e = ext_of(p)
        parts = p.split("/")
        if parts[0] in ("scripts", ".github", "tools"):       # CI and repository tooling: run by scripts, not by the build
            continue
        in_tests = any(x in ("tests", "test", "gtest", "testing") for x in parts[:-1])
        if e in C_SOURCE_EXT:
            if not builds.compiled(p):
                out.append(Finding(FAIL, 6, p, "no moz.build names this source and nothing of ours #includes it", "add it to SOURCES or UNIFIED_SOURCES in the moz.build of its directory"))
        elif e == "rs":
            if base_of(p) in ("lib.rs", "main.rs", "build.rs") or builds.named_by(p):
                continue
            stem = base_of(p)[:-3]
            sibs = [(dir_of(p) + "/" + n) for n in proj.head.listdir(dir_of(p)) if n.endswith(".rs") and n != base_of(p)]
            parent_mod = (dir_of(p) + ".rs") if dir_of(p) else ""
            cands = sibs + ([parent_mod] if parent_mod else [])
            if not any(re.search(r"\bmod\s+%s\s*;" % re.escape(stem), blank_for(q, proj.read(q) or "")) for q in cands):
                out.append(Finding(FAIL, 6, p, "no `mod %s;` in a file next to it and no moz.build names it" % stem, "declare the module in lib.rs or mod.rs"))
        elif e in ("mjs", "js", "jsm", "jsx"):
            if in_tests or base_of(p).endswith((".test.mjs", ".test.js")):
                continue
            if not builds.compiled(p):
                out.append(Finding(FAIL, 6, p, "no moz.build or jar.mn ships this module and no file #includes it", "list it in EXTRA_JS_MODULES, FINAL_TARGET_FILES or the jar.mn of its directory"))
    # rule G19: no two files of ours share a basename
    by: dict = {}
    for p in own:
        if ext_of(p) in C_EXT | JS_EXT | RS_EXT and base_of(p) not in ("lib.rs", "mod.rs", "main.rs", "build.rs"):
            by.setdefault(base_of(p), []).append(p)
    for b, ps in sorted(by.items()):
        if len(ps) > 1 and any(proj.in_scope(p) for p in ps):
            out.append(Finding(FAIL, 6, ps[0], "rule G19: %d files of ours are named %s (%s)" % (len(ps), b, ", ".join(ps[1:3])), "rename one of them"))
    # the in-tree checker overlaps the build-list part
    if tree_path:
        script = Path(tree_path) / "build" / "stealth_check_build_files.py"
        if script.is_file():
            r = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, cwd=str(tree_path))
            for ln in (r.stdout + r.stderr).splitlines():
                if ln.strip() and r.returncode:
                    out.append(Finding(FAIL, 6, "build/stealth_check_build_files.py", ln.strip()[:200], "see the script"))
    return out


# ============================================================================================ 7. gtest filter
GTEST_RE = re.compile(r"\bTEST(?:_F)?\s*\(\s*(\w+)\s*,\s*(\w+)\s*\)")


def default_gtest_filter(text: str):
    """The default of the `gtest_filter` input of a workflow file, or None."""
    lines = text.split("\n")
    for i, ln in enumerate(lines):
        if re.match(r"^\s*gtest_filter:\s*$", ln):
            for ln2 in lines[i + 1:i + 14]:
                m = re.match(r"""^\s*default:\s*(["'])(.*)\1\s*$""", ln2)
                if m:
                    return m.group(2)
            return None
    return None


def gtest_matches(flt: str, full: str) -> bool:
    pos, _, neg = flt.partition("-")

    def hit(pats):
        return any(re.fullmatch(".*".join(re.escape(x) for x in p.split("*")).replace("\\?", "."), full) or
                   re.fullmatch(re.escape(p).replace("\\*", ".*").replace("\\?", "."), full) for p in pats.split(":") if p)
    return hit(pos or "*") and not hit(neg)


def check_gtest_filter(proj: Project) -> list:
    out = []
    wf = proj.head.read(".github/workflows/release.yml")
    if wf is None and proj.series:
        p = proj.series / ".github" / "workflows" / "release.yml"
        wf = p.read_text(encoding="utf-8") if p.is_file() else None
    flt = default_gtest_filter(wf) if wf else None
    if flt is None:
        return [Finding(FAIL, 7, ".github/workflows/release.yml", "no default of the gtest_filter input found", "keep the long default under `gtest_filter: default:`")]
    suites: dict = {}
    proj.stats[7] = "filter of %d patterns" % (flt.count(":") + 1)
    for p in proj.own:
        if ext_of(p) not in C_EXT or not proj.in_scope(p):
            continue
        t = proj.read(p)
        if not t or "TEST" not in t:
            continue
        for s, n in GTEST_RE.findall(blank(t)):
            suites.setdefault(s, []).append((n, p))
    for s, tests in sorted(suites.items()):
        hits = [n for n, _ in tests if gtest_matches(flt, "%s.%s" % (s, n))]
        if not hits:
            out.append(Finding(FAIL, 7, tests[0][1], "gtest suite %s (%d tests) is matched by no pattern of the default gtest_filter of release.yml" % (s, len(tests)),
                               "add `%s.*` to the default of gtest_filter in the workflow's source" % s))
        elif len(hits) < len(tests):
            miss = [n for n, _ in tests if n not in hits]
            out.append(Finding(FAIL, 7, tests[0][1], "gtest suite %s: the filter runs %d of %d tests (misses %s)" % (s, len(hits), len(tests), ", ".join(miss[:3])),
                               "make the pattern `%s.*`" % s))
    return out


# ============================================================================================ 8. removed lines
def removed_counts(old: Tree, new: Tree) -> dict:
    """{path: number of `-` lines of the diff old -> new}: the lines of a Mozilla file rewritten or removed (a
    deleted file counts all its lines). Files the diff does not remove a line from are left out."""
    out: dict = {}
    if isinstance(old, GitTree) and isinstance(new, GitTree):
        raw = old.git("diff", "--numstat", "--no-renames", "-z", old.ref, new.ref).split(b"\0")
        for rec in raw:
            parts = rec.decode("utf-8", "replace").lstrip("\n").split("\t", 2)
            if len(parts) == 3 and parts[1].isdigit() and int(parts[1]):
                out[parts[2]] = int(parts[1])
        return out
    status, patch = diff_trees(old, new)
    for f in hc.parse_patch(patch):
        n = sum(1 for h in f["hunks"] for t, _ in h["lines"] if t == "-")
        if n:
            out[f["file"]] = n
    for path, st in status.items():
        if st == "D":
            t = old.read(path) or ""
            n = t.count("\n") + (1 if t and not t.endswith("\n") else 0)
            if n:
                out[path] = n
    return out


def removed_rows(proj: Project) -> list:
    """[(file, base, head, replaces)] for every Mozilla file whose count of rewritten or removed lines differs
    between the base and the head, inside the scope of the folders asked for (all files when none)."""
    base = removed_counts(proj.tag, proj.base)
    head = removed_counts(proj.tag, proj.head)
    replaces: dict = {}
    for e in proj.hook_entries():
        if e.get("replaces"):
            replaces.setdefault(e.get("file"), []).extend(_as_list(e["replaces"]))
    rows = []
    for p in sorted(set(base) | set(head)):
        if not proj.in_scope(p) or base.get(p, 0) == head.get(p, 0):
            continue
        rows.append((p, base.get(p, 0), head.get(p, 0), replaces.get(p, [])))
    return rows


def check_removed_lines(proj: Project) -> list:
    out = []
    for p, b, h, rep in removed_rows(proj):
        if h > b and not rep:
            out.append(Finding(FAIL, 8, p, "Mozilla lines rewritten or removed grew: %d on the base, %d on the head" % (b, h),
                               "rewrite no more Mozilla lines than the base does, or record in HOOKS.json the entry of this file with `replaces` listing the hooks one rewritten line stands for"))
    return out


# ============================================================================================ run
CHECK_NAMES = {1: "hook link", 2: "rename consistency", 3: "Mozilla tokens untouched", 4: "mechanical equivalence",
               5: "restored files", 6: "our files built and unique", 7: "gtest filter", 8: "removed lines not more than the base"}


def run(proj: Project, checks=(1, 2, 3, 4, 5, 6, 7), tree_path: str | None = None) -> dict:
    res = {"findings": [], "times": {}, "equivalence": [], "mozilla_lines": None}
    for n in checks:
        t0 = time.time()
        if n == 1:
            f = check_hook_links(proj)
        elif n == 2:
            f = check_rename(proj)
        elif n == 3:
            f, changes = check_mozilla_tokens(proj)
            res["mozilla_lines"] = {"total": sum(c.get("lines", 1) for c in changes),
                                    "by_form": sum(1 for c in changes if c["allowed"] == "form"),
                                    "by_exception": sum(1 for c in changes if c["allowed"] == "exception"),
                                    "unexplained": sum(c.get("lines", 1) for c in changes if not c["allowed"]),
                                    "lines": changes}
        elif n == 4:
            if proj.base is None:
                f = []
            else:
                res["equivalence"] = check_equivalence(proj)
                f = []
        elif n == 5:
            f = check_restored(proj) if proj.base is not None else []
        elif n == 6:
            f = check_our_files(proj, tree_path)
        elif n == 8:
            f = check_removed_lines(proj) if proj.base is not None else []
        else:
            f = check_gtest_filter(proj)
        res["findings"] += f
        res["times"][n] = round(time.time() - t0, 2)
    return res


def _out(text: str):
    sys.stdout.buffer.write(text.encode("utf-8"))
    sys.stdout.buffer.flush()


def report(res: dict, proj: Project, checks) -> str:
    lines = []
    for f in res["findings"]:
        lines.append(f.line())
    for n in checks:
        fs = [f for f in res["findings"] if f.check == n]
        extra = "; " + proj.stats[n] if proj.stats.get(n) else ""
        if n == 3 and res["mozilla_lines"]:
            m = res["mozilla_lines"]
            extra += "; Mozilla lines the series changes: %d (%d by a recorded form, %d by exception, %d unexplained)" % (
                m["total"], m["by_form"], m["by_exception"], m["unexplained"])
        if n == 4:
            if proj.base is None:
                lines.append("prebuild 4 %s: skipped (needs --base)" % CHECK_NAMES[4])
                continue
            counts: dict = {}
            for r in res["equivalence"]:
                counts[r["class"]] = counts.get(r["class"], 0) + 1
            extra += "; %d files differ: %s" % (len(res["equivalence"]), ", ".join("%s %d" % kv for kv in sorted(counts.items())))
        if n in (5, 8) and proj.base is None:
            lines.append("prebuild %d %s: skipped (needs --base)" % (n, CHECK_NAMES[n]))
            continue
        lines.append("prebuild %d %s: %d FAIL, %d WARN%s (%.1fs)" % (
            n, CHECK_NAMES[n], sum(1 for f in fs if f.level == FAIL), sum(1 for f in fs if f.level == WARN), extra, res["times"].get(n, 0)))
    if 4 in checks and proj.base is not None and res["equivalence"]:
        lines.append("")
        lines.append("%-14s %-8s %5s  %s" % ("class", "owner", "runs", "file"))
        order = {"changed": 0, "added": 1, "removed": 2, "include-order": 3, "identical": 4}
        for r in sorted(res["equivalence"], key=lambda r: (order.get(r["class"], 9), r["file"])):
            lines.append("%-14s %-8s %5d  %s" % (r["class"], r["owner"], r["runs"], r["file"]))
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    up = json.loads((ROOT / "UPSTREAM.json").read_text(encoding="utf-8"))
    ap.add_argument("--source", default=os.environ.get("FIREFOX_SOURCE") or None,
                    help="the Firefox repository (read only); or the environment variable FIREFOX_SOURCE; no default")
    ap.add_argument("--head", default=up["source_branch"], help="the source branch to check")
    ap.add_argument("--base", help="the source branch before the rework (checks 4, 5 and 8)")
    ap.add_argument("--tag", help="the Mozilla tag (default: UPSTREAM.json)")
    ap.add_argument("--series", type=Path, default=ROOT, help="the series repository whose HOOKS.json and MANIFEST.json to read")
    ap.add_argument("--folder", action="append", default=[], help="only the files of this series folder (repeatable)")
    ap.add_argument("--tree", help="a full checkout: also run its build/stealth_check_build_files.py (check 6)")
    ap.add_argument("--checks", default="1,2,3,4,5,6,7", help="which checks, e.g. 1,3 (8 is only run when asked for)")
    ap.add_argument("--json", type=Path, help="write the findings, the Mozilla lines and the per-file classes here")
    a = ap.parse_args(argv)
    if not a.source:
        raise SystemExit("prebuild needs the source repository: pass --source <path> or set FIREFOX_SOURCE")
    tag = a.tag or up["mozilla_tag"]
    checks = tuple(int(x) for x in a.checks.split(","))
    t0 = time.time()
    scope = folder_scope(a.series, a.folder) if a.folder else None
    proj = Project(GitTree(a.source, tag), GitTree(a.source, a.head), GitTree(a.source, a.base) if a.base else None,
                   a.series, scope)
    res = run(proj, checks, a.tree)
    text = report(res, proj, checks)
    elapsed = time.time() - t0
    text += "prebuild: %d FAIL, %d WARN in %.1fs\n" % (sum(1 for f in res["findings"] if f.level == FAIL),
                                                       sum(1 for f in res["findings"] if f.level == WARN), elapsed)
    _out(text)
    if a.json:
        data = {"head": a.head, "base": a.base, "tag": tag, "findings": [f.as_dict() for f in res["findings"]],
                "mozilla_lines": res["mozilla_lines"], "equivalence": res["equivalence"], "seconds": round(elapsed, 1)}
        a.json.write_bytes((json.dumps(data, indent=1, ensure_ascii=False) + "\n").encode("utf-8"))
    for t in (proj.tag, proj.head, proj.base):
        if isinstance(t, GitTree):
            t.close()
    return 1 if any(f.level == FAIL for f in res["findings"]) else 0


if __name__ == "__main__":
    sys.exit(main())
