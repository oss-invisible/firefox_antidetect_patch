"""The engine as a patch series: export it from a Firefox tree, rebuild a tree from it.

    python tools/engine.py           the front door (also --help): the state of the series, every command, and "next:", the command to run now

Every command that stops (non-zero exit) ends with `next: <the exact command to run>`.

    python tools/engine.py status    did the source move since the last export?
    python tools/engine.py export    write the series from the source tree
    python tools/engine.py verify    rebuild the tree from the series, compare
    python tools/engine.py check     the series' own rules, offline (also in CI)
    python tools/engine.py hooks-list   write every folder's HOOKS.json from its hooks.patch (the export does it too)
    python tools/engine.py gtest-list [--write]   tools/gtest-suites.json: the gtest suites the hooks name (the export writes it too)
    python tools/engine.py hook-debt    drop the entries of tools/hook-debt.json that no longer occur
                                        (--init writes the list from scratch, --summary only counts it)
    python tools/engine.py apply --head <branch>   the series as a branch: tag + one commit per folder
    python tools/engine.py materialize --into <dir> CI: fetch the tag, apply, check out the tree
    python tools/engine.py drift --to <tag>   our patched Mozilla files that Mozilla changed
    python tools/engine.py port --to <tag>    every folder merged three-way onto the new tag,
                                              all conflicts in one run, branch port/<tag>, UPSTREAM.json
                                              written (mozilla_tag, source_branch), then the birth points
                                              of the new tag against the ledger
    python tools/engine.py prebuild --head <branch> [--base <branch>]   what a failed build would tell an hour later, from git objects,
                                              in seconds (tools/prebuild.py)
    python tools/engine.py births --tree <dir>   every place the tree makes a network request, against
                                              tools/birth-ledger.json (tools/births.py says how)
    python tools/engine.py range-diff --source <repo> [--old-series <ref>] [--fetch] [--write | --check]
                                              the layers of the old series on its tag against the new series on its
                                              tag, in ports/range-diff.txt, on a partial clone (tools/range_diff.py)

The Mozilla tag, the source branch and the commit last exported are in UPSTREAM.json: `port` writes
mozilla_tag and source_branch (the tag it moved to, the branch it made), `export` writes exported_from
and exported_tree; nobody types them. --base / --head override them. The source repository has no default: the commands that read
it (status, apply, export, verify, drift, port, check --against) take --source <path> or the
environment variable FIREFOX_SOURCE, and stop with a message when neither is given.

export   writes one folder per feature (tools/layout.py says which):
           hooks.patch    our changes to Mozilla's files, as a git diff against the tag: a file several folders patch is split by
                          marker (tools/split.py), each folder holding the lines its STEALTH-HOOK(<folder>) names
           src/<path>     the files we add to the tree, byte for byte
           MANIFEST.json  what the folder owns (regenerated on every export): `modified`, `added` (path -> mode), `sha256` (path -> the
                          hash of the file under src/), `inventory` (the records of the folder's modified files)
           FEATURE.md     the feature's description, created once and then edited by hand
           HOOKS.json     the folder's hooks, one entry per hook (tools/hooks_list.py); the hand fields
                          (test, anchor, why) of the committed file are kept
         SERIES, the order the folders are applied in, and UPSTREAM.json's
         "exported_from". A folder that no longer owns anything is removed.
         It also writes what it can compute (repo-06): the `added`, `removed`, `hunks` and `inline_logic_lines` of every record of
         the `inventory` of each folder's MANIFEST.json (one per file and folder, the one place that has it) from the folder's hooks.patch (the hand fields stay; a (file, folder) with no record
         gets one with its counts, category, feature and hookable, and an empty anchor and notes for a hand), the entry of tools/hook-budget.json
         and tools/removed-budget.json (keyed <file>|<folder>) of a (file, folder) patched for the first time, at the counted value, and
         tools/gtest-suites.json. A line no folder owns stops the export before it writes anything. The owner of a file of ours is the
         folder that holds it under src/; a new file that no folder holds is placed once with `--own <path>=<folder>`.

verify   rebuilds the tree from the series on top of the tag, in a throwaway git index
         (no checkout of Firefox, works in a bare repository), and compares it with the
         source head's tree. Identical trees mean the series IS the engine.

hook contract (tools/hook_contract.py): every line a hooks.patch adds to a Mozilla file is a hook of one of
         the forms of STRUCTURE.md (one line, the marker on it, no logic, a Stealth<What> call, never inside a
         list, no Mozilla line changed but the one of a rewriting form). `check` refuses a violation that is not in
         tools/hook-debt.json, an entry that no longer occurs, and (against origin/main) an entry main's list does
         not have: the debt only shrinks. `hook-debt` removes the entries that are gone; it never adds one.

hooks list (tools/hooks_list.py): each non-backport folder has a HOOKS.json generated from its hooks.patch. `check`
         fails when it differs from the generation (a hook missing or extra, a field changed) and when an entry's
         `test` names a test that does not exist; a hook with no test (rule T1), an anchor without its anchor
         and why (T2) or a test no round runs (T3) is debt in tools/hook-debt.json. A hook with `exception` and
         `pm: "approvato"` in its entry is a declared exception (G35): left out of the contract, counted by `check`; one with
         `untestable` and that `pm` has no T1 and is counted too.

folders  (tools/folders.py, series-02) every SERIES folder without a BACKPORT.json has one FOLDER.json, by hand: relation product,
         or defect with upstream not-filed or a Mozilla bug URL, and for a defect an optional fixed_in release; `check` fails a
         missing file, another shape, a backport that has one, a FOLDER.json outside SERIES and a fixed_in at or before the tag;
         `port` stops, before it merges, when a fixed_in is at or before the new tag.

check    needs no Firefox: SERIES lists exactly the folders that exist, every folder has
         its MANIFEST and FEATURE.md, every file of ours is listed and present, each
         hooks.patch touches only the Mozilla files its MANIFEST owns, and no Mozilla file in a folder
         carries more of our lines than tools/hook-budget.json allows (per <file>|<folder>), nor loses or has
         rewritten more of its own lines than tools/removed-budget.json allows. Both
         budgets only go down (a hook budget goes above main's only with the row the branch adds to
         tools/hook-budget-raises.json, a register that only grows: from main's budget to the new one,
         with its folder, reason, who decided, date and test; the removed budget the same way, with `budget: "removed"`): logic belongs in our own files, Mozilla's files get hooks,
         and Mozilla's lines stay as Mozilla wrote them (a removed or rewritten line
         conflicts at a port like an added one, and a copy of it in a file of ours
         stops following Mozilla). A Mozilla file outside vendored code can be a backport (category
         backport, no budget) only as the diff of one commit of Mozilla's own repository, in a folder of
         platform/backports/ of its own: its BACKPORT.json names the commit and the sha256 of the diff, the diff is in the folder, and
         hooks.patch carries it byte for byte; with --against <tag> (and in a port) a tag that
         already holds the change fails. Vendored code (third_party/rust, Cargo.lock) is carried as the ordered
         list of upstream and our commits stored in the folder (BACKPORT.json, commits/*.patch, port-04): the
         record, the sha256 of every commit file and the absence of any path outside the series are checked
         offline; with --against <tag> the vendored part of hooks.patch, its checksum lines and the new files
         must equal the replay of the commits on the revision the tag vendors (tools/backport_replay.py).
         Every STEALTH-HOOK(<folder>) tag in a hooks.patch names a folder of SERIES, and the added, removed and hunk
         counts of each inventory record are those of its file in the hooks.patch of its folder (`export` writes them; a hand edit fails
         and the message names `export`); a record whose anchor or notes is empty, or whose hookable is none of the three values, fails too. An inventory record has no `evidence` field: the lines are the hooks.patch itself (repo-07). The MANIFEST of a folder has the sha256 of every file under its src/, and each file has those bytes.
         tools/gtest-suites.json is what `gtest-list --write` writes. A C++ file of ours has no control character (a carriage return inside a
         string literal ended the literal and broke the build of a test) and no byte outside ASCII inside a
         string or character literal: write them as escapes. No file of ours has a carriage return: not under
         <folder>/src/ (a binary file, with a NUL byte, apart) and not in a line a hooks.patch adds to a Mozilla
         file (Mozilla's own lines may carry one; ours may only where the context of their hunk does).
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import backport_replay  # noqa: E402
import births  # noqa: E402
import export_paths  # noqa: E402
import folders  # noqa: E402
import gtest_list  # noqa: E402
import hook_contract  # noqa: E402
import hooks_list  # noqa: E402
import layout  # noqa: E402
import split  # noqa: E402
from failure import fail  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
# The names of what the export writes are tools/export_paths.py's (the series rule «export commits are named export:» reads them there).
UPSTREAM = ROOT / export_paths.UPSTREAM
BUDGET = ROOT / export_paths.BUDGET
REMOVED_BUDGET = ROOT / export_paths.REMOVED_BUDGET
HOOK_DEBT = ROOT / "tools" / "hook-debt.json"
# Declared raises of a hook budget above main's (a hook that is a wanted growth, decided by the pm):
# the register only grows, and a branch raises a budget only with the row it adds (budget_raise_problems).
RAISES = ROOT / "tools" / "hook-budget-raises.json"
# The workflows live in the series (the tree's tests read them beside scripts/), and
# GitHub runs them from this repository's root: export copies them there and check
# requires the two identical. series.yml and noreply-identity.yml are the root's own.
WORKFLOWS_SERIES = ROOT / export_paths.WORKFLOWS_SERIES
WORKFLOWS_ROOT = ROOT / export_paths.WORKFLOWS_ROOT
ROOT_ONLY_WORKFLOWS = set(export_paths.ROOT_ONLY_WORKFLOWS)

# The decisions that own the checks of this file (repo-04: every failure names one).
R_SERIES = "series-01-export-is-the-only-writer"
R_FOLDERS = "series-02-every-folder-states-its-relation-to-mozilla"
R_PORT = "port-01-one-run"
R_BIRTHS = "port-03-births-ledger"
R_VENDORED = "port-04-backport-as-commits"
R_BACKPORT = "backport-01-upstream-code-as-is"
R_HOOK = "hook-02-shape-and-contract"
R_BUDGET = "hook-03-budgets-and-debt-only-go-down"
R_ONE_FACT = "repo-07-one-fact-one-place"
R_TOOL_WRITES = "repo-06-what-a-tool-can-write-a-tool-writes"
R_BUILD = "ci-01-builds-from-main-or-latitude-branches"



def command(*parts: str) -> str:
    """The exact command line a `next:` names: `python tools/engine.py <parts>`. The source repository is always written
    `<source>` (the path is the one the reader gave with --source or FIREFOX_SOURCE)."""
    return " ".join(["python tools/engine.py"] + [shlex.quote(p) if p and not re.fullmatch(r"[\w./:@=<>+-]+", p) else p for p in parts])


def halt(failure, next_command: str) -> str:
    """What a command that stops prints (repo-05): the failure, then `next: <the exact command to run>`."""
    return "%s\nnext: %s" % (failure, next_command)


def stop_if_not_marked(error: SystemExit, next_command: str) -> SystemExit:
    """The SystemExit of a stop that names no next step yet gets one (a message built by a helper that does not know the command)."""
    code = error.code
    # Only a message that is already a failure gets the line: every SystemExit with text in these tools is raised as str(fail(...)) or
    # halt(fail(...)), with its own rule (the scan of tools/tests/test_failure_messages.py finds any other); this adds `next:`, no message.
    if isinstance(code, str) and "\nnext: " not in code:
        return SystemExit("%s\nnext: %s" % (code, next_command))
    return error


def git(source: Path, *args: str, env=None, input_bytes=None) -> bytes:
    return subprocess.run(["git", "-C", str(source), "-c", "safe.bareRepository=all", *args], check=True,
                          capture_output=True, env=env, input=input_bytes).stdout


def upstream() -> dict:
    return json.loads(UPSTREAM.read_text(encoding="utf-8"))


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def series_folders() -> list:
    return (ROOT / "SERIES").read_text(encoding="utf-8").split()


def existing_folders() -> list:
    return layout.folders_on_disk(ROOT)


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


def inventory_records() -> list:
    """The inventory of the series: one record per (file, folder), each in the `inventory` of the MANIFEST.json of its folder (the one place
    that has it), the folders in SERIES order. `export` writes them: the computed fields from the folder's hooks.patch, the hand fields
    kept from the committed record."""
    found = []
    for folder in sorted(existing_folders(), key=layout.folder_sort_key):
        found += json.loads((ROOT / folder / "MANIFEST.json").read_text(encoding="utf-8")).get("inventory", [])
    return found


def legacy_inventory() -> Path:
    """The file the inventory used to be kept in, as a second copy of the MANIFEST ones: it must not exist (repo-07)."""
    return ROOT / "tools" / "inventory.json"


def record_where(record: dict) -> str:
    """Where an inventory record lives: the MANIFEST.json of its folder."""
    folder = record_folder(record)
    return "%s/MANIFEST.json" % folder if folder else "the MANIFEST.json of the folder of the feature %s" % record.get("feature")


def records_by_file(records: list) -> dict:
    """{file: [records]}: one record per (file, folder), the folder being the one the record's `feature` maps to (layout.feature_folder)."""
    found = defaultdict(list)
    for r in records:
        found[r["file"]].append(r)
    return found


def record_folder(record: dict):
    """The folder of an inventory record (its feature's), or None when the feature has no folder."""
    try:
        return layout.feature_folder(record["feature"])
    except KeyError:
        return None


def known_folders(plan: dict) -> set:
    """The folders a marker may name: those of the features, those on disk, and those a new file of ours places now."""
    return set(layout.FEATURES.values()) | set(existing_folders()) | set(plan)


def owners(source: Path, base: str, head: str, declared: dict | None = None):
    """-> (plan, by_file, split_plan). plan: folder -> {"modified": [paths], "added": [(path, mode)]}. A file of ours belongs to the folder that
    holds it under src/ (layout.own_file_folder); `declared` (`export --own`) places the files that no folder holds yet. A modified Mozilla
    file goes to every folder that owns lines of it (tools/split.py: the folder its marker names); a file of category backport, or one git
    calls binary, goes whole to the folder of its inventory feature. `by_file` is the inventory by file, `split_plan` is split.make_plan's.
    A line no folder owns stops the export with the failure of each."""
    by_file = records_by_file(inventory_records())
    plan = defaultdict(lambda: {"modified": [], "added": []})
    held = layout.src_owners(ROOT)[0]
    unowned = []
    modified = {}          # path -> (folder of its inventory feature, category)
    again = command("export", "--source", "<source>", "--head", head)
    for status, mode, path in changed_files(source, base, head):
        try:
            if status in ("M", "D"):   # D: a Mozilla file we delete is ours to own like any change
                if path not in by_file:
                    raise SystemExit(halt(fail(
                        "the `inventory` of the MANIFEST.json files", "the modified file %s has no record: its category (backport or not) and its feature, "
                        "which the export cannot derive (a backport has no markers, a binary file or a removal with no marker has no folder)" % path,
                        "add its record (feature, category, anchor, hookable, notes) to the `inventory` of the MANIFEST.json of its folder, then run the "
                        "export again; export writes its counts and keeps the rest", R_SERIES), again))
                recs = by_file[path]
                folder = min((layout.feature_folder(r["feature"]) for r in recs), key=layout.folder_sort_key)
                modified[path] = (folder, "backport" if any(r["category"] == "backport" for r in recs) else recs[0]["category"])
            elif status == "A":
                plan[layout.own_file_folder(path, held, declared)]["added"].append((path, mode))
            else:
                raise SystemExit(halt(fail(
                    "git diff %s %s" % (base, head), "status %s for %s is not one export handles (M, D and A are)" % (status, path),
                    "make the change on the source branch an addition, a modification or a deletion of a file, then run the export again",
                    R_SERIES), again))
        except KeyError as unowned_file:       # layout.py: a feature with no folder, a file of ours that no folder holds
            if status != "A":
                raise SystemExit(halt(unowned_file.args[0], again)) from None
            unowned.append(path)
    if unowned:
        raise SystemExit(halt(fail(
            "python tools/engine.py export", "no folder owns our new %s: %s (under no folder's src/ yet)"
            % ("file" if len(unowned) == 1 else "files", ", ".join(unowned)),
            "name the folder of each once with --own <path or dir/>=<folder> (a folder of SERIES, or a new one under %s); "
            "the export writes the file under that folder's src/ and it is owned from then on" % "/".join(layout.GROUP_ORDER), R_SERIES),
            command("export", "--source", "<source>", "--head", head, *[part for p in unowned for part in ("--own", "%s=<folder>" % p)])))
    backports = {f for f in existing_folders() if (ROOT / f / BACKPORT).exists()}
    split_plan = split.make_plan(source, base, head, modified, known_folders(plan), backports)
    reds = [p for owned in split_plan.values() if not isinstance(owned, str) for p in owned.problems]
    if reds:
        raise SystemExit(halt("\n".join(str(p) for p in reds), again))
    for path, owned in sorted(split_plan.items()):
        for folder in ([owned] if isinstance(owned, str) else owned.folders):
            plan[folder]["modified"].append(path)
    return plan, by_file, split_plan


def require_descends(source: Path, base: str, head: str) -> None:
    """The branch must be built on the tag: a diff between unrelated commits would
    export Mozilla's own changes as ours."""
    if subprocess.run(["git", "-C", str(source), "merge-base", "--is-ancestor", base, head],
                      capture_output=True).returncode:
        raise SystemExit(halt(fail(
            "%s in the source repository" % head, "%s does not descend from %s: the series is the difference from the tag" % (head, base),
            "build the branch on the tag: `%s` makes it from the series" % command("apply", "--source", "<source>", "--head", head, "--force"),
            R_SERIES), command("apply", "--source", "<source>", "--head", head, "--force")))


KEY_SEP = "|"


def budget_key(path: str, folder: str) -> str:
    """The key of a budget: `<file>|<folder>`. A hook budget and a removed budget are per (file, folder): the lines of one folder in one
    Mozilla file (tools/split.py gives each folder the lines its marker names)."""
    return "%s%s%s" % (path, KEY_SEP, folder)


def key_file(key: str) -> str:
    """The Mozilla file of a budget key (a key with no folder, the shape of main's budgets before the split, is the file itself)."""
    return key.split(KEY_SEP, 1)[0]


def key_folder(key: str):
    """The folder of a budget key, None for a key with no folder."""
    return key.split(KEY_SEP, 1)[1] if KEY_SEP in key else None


def new_budgets(diffs: dict, records: dict, say=print) -> tuple:
    """The budget entries the hooks.patch files need and the budgets do not have yet: (hook, removed), each {"<file>|<folder>": count}.
    `diffs` is {"<file>|<folder>": file_diffs entry}. A (file, folder) the series patches for the first time gets its entry at the counted
    value (hook budget: our lines; removed budget: Mozilla's lines it loses, only when there are some). An entry keeps its value
    (`shrink-budget` lowers it, a raise is a row in tools/hook-budget-raises.json), and upstream code (category backport) has none.
    A budget still keyed by file (before the split of a file by folder) is converted once, for the files some hooks.patch carries: each of the
    file's keys is at its counted value, no slack is kept, and `say` prints, per file, the slack that goes (the old ceiling minus the sum of the new counts, when above 0)."""
    hook = json.loads(BUDGET.read_text(encoding="utf-8"))
    removed = json.loads(REMOVED_BUDGET.read_text(encoding="utf-8"))
    for table, field, label in ((hook, "added", "hook"), (removed, "removed", "removed")):
        for path in sorted(k for k in table if KEY_SEP not in k and any(key_file(d) == k for d in diffs)):
            counts = {k: d[field] for k, d in sorted(diffs.items()) if key_file(k) == path and (d[field] or field == "added")}
            old = table.pop(path)
            if old > sum(counts.values()):
                say("budget slack removed, %s budget of %s: %d, the ceilings are now the counts %s (sum %d)"
                    % (label, path, old - sum(counts.values()), ", ".join("%s %d" % (key_folder(k), n) for k, n in counts.items()) or "none",
                       sum(counts.values())))
            table.update(counts)
    for key, diff in sorted(diffs.items()):
        if records.get(key_file(key), {}).get("category") == "backport":
            continue
        if key not in hook:
            hook[key] = diff["added"]
        if diff["removed"] and key not in removed:
            removed[key] = diff["removed"]
    return dict(sorted(hook.items())), dict(sorted(removed.items()))


def inventory_features(folder: str) -> list:
    """The features of tools/layout.py that map to `folder`, in the order of FEATURES."""
    return [f for f, mapped in layout.FEATURES.items() if mapped == folder]


def feature_of_folder(folder: str, records: list) -> str:
    """The `feature` of a new inventory record of `folder`: the one most of the folder's records already have, else the first feature of
    layout.FEATURES that maps to the folder."""
    named = [r["feature"] for r in records if record_folder(r) == folder]
    if named:
        return max(sorted(set(named), key=named.index), key=named.count)
    features = inventory_features(folder)
    if not features:
        raise KeyError(str(fail(
            "tools/layout.py FEATURES", "no feature maps to the folder %s, which owns lines of a Mozilla file" % folder,
            "add a feature that maps to %s to FEATURES in tools/layout.py, then export again" % folder, R_SERIES)))
    return features[0]


def part_hooks(folder: str, patch: bytes, path: str) -> list:
    """The hooks of one folder's part of one file: hook_contract's reading of that file's section of the folder's hooks.patch."""
    section = file_section(patch, path)
    return hook_contract.analyse_patch(folder, section.decode("utf-8", errors="replace"))[0] if section else []


def inline_logic_of(folder: str, patch: bytes, path: str) -> int:
    """repo-06: `inline_logic_lines` of the record of (path, folder): the added or rewritten lines of the folder's part of the file that are
    no hook form (hook_contract reads them as unknown). A tool writes it for every record of a Mozilla file that is not a backport."""
    return sum(1 for h in part_hooks(folder, patch, path) if h.form == "unknown" and h.kind in ("add", "rewrite"))


def derived_record(path: str, folder: str, diff: dict, category: str, feature: str, patch: bytes) -> dict:
    """The record of a (file, folder) the inventory does not have: what a tool can write. The counts come from the folder's part of the
    file; `category` is the file's (a property of the file); `feature` is the folder's; `hookable` is `already-hook` when every line of
    the part is a hook form (no line hook_contract reads as unknown, no deletion), else empty. `anchor` and `notes` are empty: the check
    refuses them until a hand writes them. inline_logic_lines is the number of added lines that are no hook form."""
    hooks = part_hooks(folder, patch, path)
    inline = inline_logic_of(folder, patch, path)
    all_forms = bool(hooks) and all(h.form != "unknown" and h.kind in ("add", "rewrite") for h in hooks)
    return computed_record({"file": path, "category": category, "feature": feature, "prefs": [], "inline_logic_lines": inline,
                            "hookable": "already-hook" if all_forms else "", "anchor": "", "notes": ""}, diff)


def inventory_after(old: list, modified: dict, diffs: dict, patches: dict, say=print) -> tuple:
    """-> (the new inventory, {(file, folder): record}). `old` is the inventory of the MANIFEST.json files before the export; `modified` {file: [folders that own lines of it]};
    `diffs` {(file, folder): file_diffs entry}; `patches` {folder: hooks.patch bytes}. One record per (file, folder). The record of the
    folder that held a file keeps its hand fields (anchor, notes, verifier, prefs, hookable, ...) and takes the counts of its folder's part.
    A record whose folder owns no line of its file any more moves, hand fields and all, to the one folder that now owns the lines no old
    record covers; two or more such folders: a failure. A (file, folder) with no record gets a derived one (derived_record)."""
    by_file = records_by_file(old)
    fresh, carried, born = {}, {}, defaultdict(list)
    for path, folders_of in sorted(modified.items()):
        records = by_file[path]
        category = "backport" if any(r["category"] == "backport" for r in records) else records[0]["category"]
        split_file = len(folders_of) > 1
        uncovered = [f for f in folders_of if not any(record_folder(r) == f for r in records)]
        orphans = [r for r in records if record_folder(r) not in folders_of]
        for r in records:
            f = record_folder(r)
            if f in folders_of:
                record = computed_record(r, diffs[(path, f)])
                if record["category"] != "backport":
                    record["inline_logic_lines"] = inline_logic_of(f, patches[f], path)
                fresh[(path, f)], carried[id(r)] = record, record
        if orphans and len(uncovered) > 1:
            raise SystemExit(halt(fail(
                "the `inventory` of the MANIFEST.json files, the record of %s" % path,
                "its folder %s owns no line of the file any more, and the lines are now the folders' %s: the record cannot say which keeps it"
                % (", ".join(sorted({record_folder(r) or r["feature"] for r in orphans})), ", ".join(uncovered)),
                "set the `feature` of the record to one that maps to the folder that keeps it (tools/layout.py FEATURES), then run the export again",
                R_SERIES), command("export", "--source", "<source>")))
        for r in orphans:
            if not uncovered:
                say("inventory: the record of %s in %s is dropped: the folder owns no line of the file and every folder that does has its record"
                    % (path, record_folder(r) or r["feature"]))
                continue
            target = uncovered.pop(0)
            record = computed_record({**r, "feature": feature_of_folder(target, old)}, diffs[(path, target)])
            if record["category"] != "backport":
                record["inline_logic_lines"] = inline_logic_of(target, patches[target], path)
            say("inventory: the record of %s moved from %s to %s (its markers name %s)" % (path, record_folder(r) or r["feature"], target, target))
            fresh[(path, target)], carried[id(r)] = record, record
        for f in uncovered:
            fresh[(path, f)] = derived_record(path, f, diffs[(path, f)], category, feature_of_folder(f, old), patches[f])
            born[path].append((f, fresh[(path, f)]))
    out, last = [], {}
    for r in old:
        if id(r) in carried:
            out.append(carried[id(r)])
        elif r["file"] not in modified:
            out.append(r)
        else:
            continue
        last[r["file"]] = len(out)
    for path in sorted(born, key=lambda p: -last.get(p, len(out))):
        at = last.get(path, len(out))
        out[at:at] = [rec for _f, rec in sorted(born[path], key=lambda item: layout.folder_sort_key(item[0]))]
    return out, fresh


def export(source: Path, base: str, head: str, declared: dict | None = None) -> None:
    """Writes the series from the head. What a tool can write, a tool writes (repo-06): besides the folders, SERIES and UPSTREAM.json, it
    writes the `added`, `removed` and `hunks` of every inventory record from its hooks.patch (the hand fields stay), the budget
    entries of the (file, folder) pairs patched for the first time, and the sha256 of every file under src/ in the folder's MANIFEST.json.
    A modified Mozilla file is split by tag into every folder that owns lines of it (tools/split.py): each folder's hooks.patch is its
    files' patches in path order, made so that the folders applied in SERIES order give the head byte for byte; a file of category
    backport stays whole in its inventory feature's folder. A line no folder owns stops the export before anything is written.
    `declared` is `--own`: {path or dir/: folder} for the new files no folder holds yet."""
    require_descends(source, base, head)
    plan, by_file, split_plan = owners(source, base, head, declared)
    series = sorted(plan, key=layout.folder_sort_key)
    committed_inventory = inventory_records()       # before a folder is removed or a MANIFEST.json written: the hand fields come from here
    patches = split.folder_patches(source, base, head, split_plan, series)
    if patches.problems:
        raise SystemExit(halt("\n".join(str(p) for p in patches.problems), command("export", "--source", "<source>", "--head", head)))
    pool = hooks_list.committed_entries(ROOT)       # the hand fields of every committed HOOKS.json, before a folder is removed or written
    for gone in sorted(set(existing_folders()) - set(series)):
        shutil.rmtree(ROOT / gone)
        print("removed %s: it owns nothing any more" % gone)
    diffs, shas = {}, {}
    for folder in series:
        out = ROOT / folder
        out.mkdir(parents=True, exist_ok=True)
        owned = plan[folder]
        patch = out / "hooks.patch"
        if owned["modified"]:
            patch.write_bytes(patches[folder])
        elif patch.exists():
            patch.unlink()
        if (out / "src").exists():
            shutil.rmtree(out / "src")
        sha256 = {}
        for path, mode in owned["added"]:
            target = out / "src" / path
            target.parent.mkdir(parents=True, exist_ok=True)
            data = git(source, "cat-file", "blob", "%s:%s" % (head, path))
            target.write_bytes(data)
            sha256[path] = hashlib.sha256(data).hexdigest()
        shas[folder] = sha256
        for path, diff in (_diffs_of(patch) if patch.exists() else {}).items():
            diffs[(path, folder)] = diff
    modified = defaultdict(list)
    for folder in series:
        for path in plan[folder]["modified"]:
            modified[path].append(folder)
    inventory, fresh = inventory_after(committed_inventory, modified, diffs, patches)
    for folder in series:
        owned = plan[folder]
        manifest = {
            "modified": sorted(owned["modified"]),
            "added": {path: mode for path, mode in sorted(owned["added"])},
            "sha256": dict(sorted(shas[folder].items())),
            "inventory": [fresh[(p, folder)] for p in sorted(owned["modified"])],
        }
        write_json(ROOT / folder / "MANIFEST.json", manifest)
        feature_md = ROOT / folder / "FEATURE.md"
        if not feature_md.exists():
            feature_md.write_text(describe(folder, manifest), encoding="utf-8", newline="\n")
    hook_budget, removed_budget = new_budgets({budget_key(p, f): d for (p, f), d in diffs.items()}, {r["file"]: r for r in inventory})
    write_json(BUDGET, hook_budget)
    write_json(REMOVED_BUDGET, removed_budget)
    (ROOT / "SERIES").write_text("\n".join(series) + "\n", encoding="utf-8", newline="\n")
    print(write_hooks_list(pool))
    print(write_gtest_list())
    sync_workflows()
    up = upstream()
    up["exported_from"] = git(source, "rev-parse", head).decode().strip()
    up["exported_tree"] = git(source, "rev-parse", "%s^{tree}" % head).decode().strip()
    write_json(UPSTREAM, up)
    print("exported %d folders: %d modified files, %d added files, from %s"
          % (len(series), len(modified), sum(len(plan[f]["added"]) for f in series), up["exported_from"][:10]))


@contextlib.contextmanager
def rebased(root: Path):
    """Inside the block every module path under ROOT (ROOT itself, UPSTREAM, INVENTORY, the budgets, the workflow folders, ...) is
    the same path under `root`: the code of this module reads and writes another checkout. Every path is found by what it is, not
    from a list, so a constant added later follows. Restored on exit."""
    module = sys.modules[__name__]
    old = dict(vars(module))
    here = module.ROOT
    moved = {name: root / value.relative_to(here) for name, value in old.items()
             if isinstance(value, Path) and (value == here or here in value.parents)}
    vars(module).update(moved)
    try:
        yield root
    finally:
        vars(module).update({name: old[name] for name in moved})


def export_into(root: Path, source: Path, base: str, head: str, declared: dict | None = None) -> None:
    """`export` writing into the checkout at `root` (the scratch copy of the gate) instead of this one."""
    with rebased(root):
        export(source, base, head, declared)


def write_hooks_list(pool: dict | None = None) -> str:
    """Every folder's HOOKS.json from its hooks.patch (the export and `hooks-list` both come here). `pool` (the export gives it): the hand
    fields of every HOOKS.json that was committed before this run, so a hook whose line moved to another folder keeps them."""
    return "HOOKS.json: " + hooks_list.summary_line(hooks_list.write_all(ROOT, pool))


def write_gtest_list() -> str:
    """tools/gtest-suites.json from the HOOKS.json files and the sources (the export and `gtest-list --write` both come here)."""
    return gtest_list.write(ROOT)


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
        raise SystemExit(halt(fail(
            "branch %s in %s" % (branch, source), "%s already exists" % branch,
            "pass --force to rebuild it (its commits are lost unless exported first), or export it before you do",
            R_SERIES), command("apply", "--source", "<source>", "--head", branch, "--force")))
    layers = build_stack(source, base)
    parent, tree = layers[-1][1], layers[-1][2]
    git(source, "update-ref", ref, parent)
    print("%s: %s on top of %s, %d layers (tree %s)"
          % (branch, parent[:10], base, len(series_folders()), tree[:12]))
    return tree


def add_files(source: Path, folder: str, manifest: dict, env: dict, root: Path | None = None) -> None:
    """Puts the files a folder adds (`manifest["added"]`, path -> mode) into the index of
    `env`, with a fixed number of git processes whatever their count: one `hash-object`
    for all the bytes (--no-filters: stored verbatim, as --stdin did) and one
    `update-index` for all the entries. Per file it was two processes and a rewrite of
    the whole index (775 files over 79 folders: 261-388 s of "apply" on GitHub's Windows
    runner, 27 s batched)."""
    added = manifest["added"]
    if not added:
        return
    paths = [str((ROOT if root is None else Path(root)) / folder / "src" / path) for path in added]
    shas = git(source, "hash-object", "-w", "--no-filters", "--stdin-paths",
               input_bytes=("\n".join(paths) + "\n").encode()).decode().split()
    if len(shas) != len(paths):
        raise SystemExit(halt(fail(
            "%s/src" % folder, "git hash-object returned %d objects for %d files" % (len(shas), len(paths)),
            "look for a file name with a newline or a file that is not readable under %s/src, then run the command again" % folder,
            R_SERIES), command("check")))
    lines = "".join("%s %s\t%s\n" % (mode, sha, path) for (path, mode), sha in zip(added.items(), shas))
    git(source, "update-index", "--add", "--index-info", env=env, input_bytes=lines.encode())


def build_stack(source: Path, base: str, root: Path | None = None, missing_ok: bool = False) -> list:
    """The series on `base`, as [(folder, commit, tree)] in SERIES order (the first entry
    is the tag itself, folder None). Writes objects only, moves no ref.

    `root` is the series to apply (default: this repository's; the old series of `range-diff` is another directory).
    `missing_ok` is for a partial clone (tools/range_diff.py): the trees are all there and the blobs only of the files the
    series patches, so `write-tree` must not look for the blob of every file of a directory it rewrites."""
    root = ROOT if root is None else Path(root)
    listed = (root / "SERIES").read_text(encoding="utf-8").split()
    parent = git(source, "rev-parse", "%s^{commit}" % base).decode().strip()
    layers = [(None, parent, git(source, "rev-parse", "%s^{tree}" % parent).decode().strip())]
    # Every layer is dated with the tag's own commit date: the same series on the same
    # tag gives the same commits, byte for byte, on any machine. That makes the commit
    # a seal records (source_commit) reproducible by anyone who has main and the tag,
    # although it lives on no remote.
    when = git(source, "log", "-1", "--format=%cI", parent).decode().strip()
    # The commits are the result: a scratch file Windows will not remove (a scanner or another process still holds it) is left behind,
    # it does not make the stack an error.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        env = dict(os.environ, GIT_INDEX_FILE=str(Path(tmp) / "index"), **IDENTITY,
                   GIT_AUTHOR_DATE=when, GIT_COMMITTER_DATE=when)
        git(source, "read-tree", parent, env=env)
        for folder in listed:
            patch = root / folder / "hooks.patch"
            if patch.exists():
                done = subprocess.run(["git", "-C", str(source), "-c", "safe.bareRepository=all", "apply", "--cached", "--whitespace=nowarn",
                                       str(patch)], capture_output=True, env=env)
                if done.returncode:
                    raise SystemExit(halt(fail(
                        "%s/hooks.patch" % folder, "it does not apply on %s: %s" % (base, done.stderr.decode(errors="replace").strip()),
                        "port the series to this tag (`%s`), or build on the tag the series was exported from (UPSTREAM.json: mozilla_tag)"
                        % command("port", "--to", base, "--source", "<source>"), R_PORT), command("status", "--source", "<source>")))
            manifest = json.loads((root / folder / "MANIFEST.json").read_text(encoding="utf-8"))
            add_files(source, folder, manifest, env, root)
            tree = git(source, "write-tree", *(["--missing-ok"] if missing_ok else []), env=env).decode().strip()
            parent = git(source, "commit-tree", tree, "-p", parent, "-m", folder, env=env).decode().strip()
            layers.append((folder, parent, tree))
    return layers


def port(source: Path, old: str, new: str, branch: str, force: bool, check_births: bool = False,
         record_upstream: Path | None = None) -> int:
    """Moves the series from Mozilla tag `old` to tag `new` in one run, every folder
    merged three-way, and reports every conflict instead of stopping at the first.

    The series is applied to `old`, where it applies cleanly, giving layers L1..Ln.
    Then each layer is replayed on `new`: Ni = merge(base L(i-1), ours N(i-1), theirs Li)
    with `git merge-tree`, so each folder's own change meets what Mozilla changed.
    A conflicted folder still gets its commit (files with conflict markers) and the
    run goes on. The result is branch `branch` in the source repository: resolve the
    markers there, commit, then export. Both tags must be in the source repository
    (the blobs of `old` are the base of every merge).

    With `record_upstream` (the command line gives UPSTREAM.json) the port writes what it knows into it: `mozilla_tag` is `new`
    and `source_branch` is `branch`, so the export that follows needs no hand edit (the library call of a test does not write)."""
    for tag in (old, new):
        if subprocess.run(["git", "-C", str(source), "rev-parse", "-q", "--verify", "%s^{commit}" % tag],
                          capture_output=True).returncode:
            raise SystemExit(halt(fail(
                "tag %s in the source repository" % tag, "the tag is not in %s" % source,
                "fetch it: git -C %s fetch --depth 1 %s refs/tags/%s:refs/tags/%s" % (source, upstream()["mozilla_repository"], tag, tag),
                R_PORT), command("port", "--to", new, "--source", "<source>")))
    if old == new:
        raise SystemExit(halt(fail(
            "UPSTREAM.json mozilla_tag", "it is already %s, the tag to port to: a port ran here before, and `port` writes the tag it moved to" % new,
            "name the tag the series came from with --base, and --force to rebuild the branch",
            R_PORT), command("port", "--to", new, "--source", "<source>", "--base", "<old-tag>", "--force")))
    # series-02: a folder that says Mozilla ships its fix at the new tag or before is a decision to take before anything is merged.
    stops = folders.fixed_in_stops(ROOT, new)
    if stops:
        raise SystemExit(halt(fail(
            "FOLDER.json of %d folder(s)" % len(stops),
            "port stopped before it merged anything: %d folder(s) say Mozilla ships their fix in %s or before:\n%s"
            % (len(stops), new, "\n".join("  %s: fixed_in %s" % s for s in stops)),
            "decide each one in the source repository, then run the port again: drop the folder (remove its change on the source branch, "
            "then `%s`, which removes the folder with its FOLDER.json) or rebase it onto Mozilla's fix and change "
            "or delete its fixed_in; read what Mozilla shipped before you decide (the bug is in its FOLDER.json)"
            % command("export", "--source", "<source>"), R_FOLDERS), command("port", "--to", new, "--source", "<source>")))
    ref = "refs/heads/%s" % branch
    if subprocess.run(["git", "-C", str(source), "rev-parse", "-q", "--verify", ref],
                      capture_output=True).returncode == 0 and not force:
        raise SystemExit(halt(fail(
            "branch %s in %s" % (branch, source), "%s already exists" % branch,
            "pass --force to rebuild it (its commits are lost), or --head <branch> to make another",
            R_PORT), command("port", "--to", new, "--source", "<source>", "--head", branch, "--force")))
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
            raise SystemExit(halt(fail(
                "git merge-tree on %s" % folder, "it failed: %s" % done.stderr.decode(errors="replace").strip(),
                "port needs git 2.40 or later (`git merge-tree --write-tree --merge-base`): update git, or read the error and repair the source repository",
                R_PORT), command("port", "--to", new, "--source", "<source>")))
        tree, conflicts = lines[0].strip(), sorted({l for l in lines[1:] if l.strip()})
        title = folder if not conflicts else "%s (CONFLICT: %s)" % (folder, ", ".join(conflicts))
        current = git(source, "commit-tree", tree, "-p", current, "-m", title, env=env).decode().strip()
        report.append((folder, conflicts))
    # The vendored code of a backport is not merged: its commits are replayed on the revision the new tag vendors, and
    # the result replaces what the merge made of those paths (port-04). A conflict is a commit to rebase onto that revision.
    replay_bad = []
    for backport in backport_replay.backport_folders(ROOT):
        name = backport_replay.label(backport, ROOT)
        try:
            current, replayed = backport_replay.apply_to_commit(source, new, backport, current, when=when)
        except backport_replay.Stop as stop:
            replay_bad.append((name + " (replay of its commits)", [str(stop)]))
            continue
        # what the merge left in conflict among the vendored paths the replay has just written is resolved
        report = [(f, [c for c in cs if not backport_replay.in_scope(c)] if f == name else cs) for f, cs in report]
        print("REPLAY %s: %s, %d commits already in the revision (python tools/backport_replay.py record writes "
              "them to BACKPORT.json)" % (name, replayed.vendors(short=True), len(replayed.dropped)))
    git(source, "update-ref", ref, current)
    if record_upstream is not None:
        record_port(record_upstream, new, branch)
    bad = [(f, c) for f, c in report if c]
    for folder, conflicts in bad + replay_bad:
        print("CONFLICT %s: %s" % (folder, ", ".join(conflicts)))
    already = backport_in_tag_problems(source, new)
    for problem in already:
        print(problem)
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
    stopped = bool(bad or replay_bad or already or status == 1)
    if stopped:
        # repo-05: the stop ends with the command that follows the work it asks for.
        print(fail("branch %s in %s" % (branch, source),
                   "the port is red: %d folders with conflicts, %d replays that stopped, %d backports already in the tag, births %s"
                   % (len(bad), len(replay_bad), len(already), "red" if status == 1 else "clean"),
                   "resolve the markers on the branch (git -C %s worktree add <dir> %s), commit there, take out each backport the tag has, "
                   "and fix each birth with `%s`; then export" % (source, branch, command("births", "--repo", "<source>", "--rev", branch)),
                   R_PORT))
        print("next: %s" % command("export", "--source", "<source>"))
    return 1 if stopped else 0


def record_port(path: Path, new: str, branch: str) -> None:
    """What a port knows and UPSTREAM.json says (`mozilla_tag`, `source_branch`): written by the port, never typed. The other
    fields (`exported_from`, `exported_tree`) are the export's."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    data["mozilla_tag"], data["source_branch"] = new, branch
    write_json(Path(path), data)
    print("UPSTREAM.json: mozilla_tag %s, source_branch %s" % (new, branch))


def drift(source: Path, old: str, new: str) -> int:
    """Which Mozilla files we patch did Mozilla change between the two tags: the files
    a port has to look at, whether or not they conflict. A file several folders patch is listed with each of them: the port merges
    the folders one after the other, and the conflict is reported for the folder whose lines it touches."""
    ours = sorted({r["file"] for r in inventory_records()})
    held = defaultdict(list)
    for folder in series_folders():
        manifest = ROOT / folder / "MANIFEST.json"
        if manifest.is_file():
            for path in json.loads(manifest.read_text(encoding="utf-8")).get("modified", []):
                held[path].append(folder)
    out = git(source, "diff", "--name-status", "--no-renames", old, new, "--", *ours).decode()
    rows = [l.split("	", 1) for l in out.splitlines() if l.strip()]
    for status, path in rows:
        print("%s %s%s" % ({"M": "changed", "D": "DELETED by Mozilla", "A": "added"}.get(status, status), path,
                           " (%s)" % ", ".join(held[path]) if held.get(path) else ""))
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
        raise OSError(fail(
            "refs/tags/%s in the node's mirror" % tag, "the node's fetch has no commit for it",
            "nothing to do: the leg fetches the tag from GitHub itself (a mirror that is always empty is a node to look at)", R_BUILD))
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
        raise SystemExit(halt(fail(
            "UPSTREAM.json exported_tree", "the series applied to %s gives tree %s, UPSTREAM.json declares %s" % (tag, tree, expected),
            "export the series again from the source branch (the series or UPSTREAM.json was edited by hand, or the tag moved)", R_SERIES),
            command("export", "--source", "<source>")))
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


def rebuilt_tree(source: Path, base: str) -> str:
    """The tree the series makes on `base`, in a throwaway index (verify and the front door both ask)."""
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ, GIT_INDEX_FILE=str(Path(tmp) / "index"))
        git(source, "read-tree", base, env=env)
        for folder in series_folders():
            patch = ROOT / folder / "hooks.patch"
            if patch.exists():
                git(source, "apply", "--cached", "--whitespace=nowarn", str(patch), env=env)
            manifest = json.loads((ROOT / folder / "MANIFEST.json").read_text(encoding="utf-8"))
            add_files(source, folder, manifest, env)
        return git(source, "write-tree", env=env).decode().strip()


def verify(source: Path, base: str, head: str) -> int:
    require_descends(source, base, head)
    built = rebuilt_tree(source, base)
    expected = git(source, "rev-parse", "%s^{tree}" % head).decode().strip()
    if built == expected:
        print("identical: the series rebuilds %s exactly (tree %s)" % (head, built))
        return 0
    diff = git(source, "diff", "--stat", expected, built).decode()
    print("DIFFERENT: rebuilt tree %s, %s is %s\n%s" % (built, head, expected, diff))
    print(fail("the series against %s" % head, "the series rebuilds tree %s, the head is tree %s" % (built, expected),
               "the series is written by export only: export it again from the head (a hand edit of the series is erased by it)", R_SERIES))
    print("next: %s" % command("export", "--source", "<source>", "--head", head))
    return 1


PATCH_FILE = re.compile(r"^diff --git a/(\S+) b/")


def file_diffs(patch_text: str) -> dict:
    """Mozilla file -> {"added", "removed", "hunks"} of its diff in a hooks.patch. Counted only inside hunks, so the ---/+++
    header is never a line, and a line that itself starts with -- or ++ is."""
    out, current, in_hunk = {}, None, False
    for line in patch_text.splitlines():
        m = PATCH_FILE.match(line)
        if m:
            current, in_hunk = m.group(1), False
            out[current] = {"added": 0, "removed": 0, "hunks": 0}
        elif line.startswith("@@") and current:
            in_hunk = True
            out[current]["hunks"] += 1
        elif current and in_hunk and line[:1] in ("+", "-"):
            out[current]["added" if line[0] == "+" else "removed"] += 1
    return out


def _diffs_of(patch: Path) -> dict:
    return file_diffs(patch.read_text(encoding="utf-8", errors="replace"))


def added_lines(patch: Path) -> dict:
    """Mozilla file -> lines we add to it, read from a hooks.patch."""
    return {path: d["added"] for path, d in _diffs_of(patch).items()}


def removed_lines(patch: Path) -> dict:
    """Mozilla file -> lines of Mozilla's we remove or rewrite, read from a hooks.patch."""
    return {path: d["removed"] for path, d in _diffs_of(patch).items()}


def hunk_counts(patch: Path) -> dict:
    """Mozilla file -> hunks of its diff, read from a hooks.patch."""
    return {path: d["hunks"] for path, d in _diffs_of(patch).items()}


RECORD_ORDER = ("file", "category", "feature", "prefs", "added", "removed", "hunks", "inline_logic_lines", "hookable", "anchor",
                "notes", "verifier")


def computed_record(record: dict, diff: dict) -> dict:
    """The record with the three fields of its hooks.patch (`added`, `removed`, `hunks`) as the diff has them. The hand fields
    (feature, category, anchor, hookable, notes, verifier, ...) are the record's own. It never has an `evidence` field: the lines are the
    hooks.patch itself (repo-07), so one that comes in with the record is dropped. Keys are in RECORD_ORDER, the rest after them."""
    fresh = {k: v for k, v in record.items() if k != "evidence"}
    fresh.update(added=diff["added"], removed=diff["removed"], hunks=diff["hunks"])
    return {**{k: fresh[k] for k in RECORD_ORDER if k in fresh}, **{k: v for k, v in fresh.items() if k not in RECORD_ORDER}}


HOOK_TAG = re.compile(r"STEALTH-HOOK\(([^)\n]*)\)")      # one line: git's hunk header can end in the first half of another folder's marker


def hook_tag_problems(folders: set, patches: dict) -> list:
    """A STEALTH-HOOK(<folder>) tag names the folder that owns the hook; one that names
    nothing in SERIES (a folder deleted or renamed since) sends whoever greps it to a place
    that is not there. Looked at: every line of every hooks.patch (`patches`: folder -> text)."""
    found = []
    for folder, text in sorted(patches.items()):
        for tag in sorted(set(HOOK_TAG.findall(text))):
            if tag not in folders:
                found.append(fail(
                    "%s/hooks.patch" % folder, "it carries STEALTH-HOOK(%s), and %s is not a folder of SERIES" % (tag, tag),
                    "retag the hook in the source with the folder that owns it, then export", R_HOOK))
    return found


def record_count_problems(records: list, diffs: dict) -> list:
    """Each inventory record says how many lines of ours (added), of Mozilla's (removed) and how many hunks its folder's part of its file
    has: those of its file in the hooks.patch of its folder (`diffs`: (file, folder) -> file_diffs entry; the folder is the one the record's
    feature maps to). The three fields are written by `export` (computed_record); one that differs was edited by hand or not refreshed, and
    reads as truth to whoever sizes a hook from it. A record has no `evidence`."""
    found = []
    for r in records:
        diff = diffs.get((r["file"], record_folder(r)), diffs.get(r["file"]))
        if diff is None:
            continue
        again = command("export", "--source", "<source>")
        have = (r.get("added"), r.get("removed"), r.get("hunks"))
        real = (diff["added"], diff["removed"], diff["hunks"])
        if have != real:
            found.append(fail(
                record_where(r), "the record of %s in %s says added %s, removed %s, hunks %s; its hooks.patch has %d, %d, %d"
                % ((r["file"], record_folder(r) or r.get("feature")) + have + real),
                "do not edit a count: `%s` writes added, removed and hunks of every record from its hooks.patch" % again, R_SERIES))
    return found


def record_inline_problems(records: list, diffs: dict, patches: dict) -> list:
    """repo-06: `inline_logic_lines` of each record of a Mozilla file that is not a backport is the number `export` computes from the
    hooks.patch of its folder (inline_logic_of); a hand value, or one that was not refreshed after a hunk moved, differs and is refused.
    `patches`: folder -> hooks.patch bytes; `diffs` as for record_count_problems."""
    found = []
    for r in records:
        folder = record_folder(r)
        if r.get("category") == "backport" or folder not in patches or diffs.get((r["file"], folder)) is None:
            continue
        real = inline_logic_of(folder, patches[folder], r["file"])
        if r.get("inline_logic_lines") != real:
            found.append(fail(
                record_where(r), "the record of %s in %s says inline_logic_lines %s; the folder's part of the file in its hooks.patch has %d"
                % (r["file"], folder, r.get("inline_logic_lines"), real),
                "do not edit inline_logic_lines: `%s` writes it from the hooks.patch of the folder" % command("export", "--source", "<source>"), R_TOOL_WRITES))
    return found


INVENTORY_HOOKABLE = ("already-hook", "movable", "hard")
INVENTORY_HAND_FIELDS = ("anchor", "notes")      # text a hand writes; `hookable` is one of INVENTORY_HOOKABLE


def inventory_hand_problems(records: list, diffs: dict) -> list:
    """An inventory record of a (file, folder) a hooks.patch carries has its hand fields: `anchor` and `notes` are text that is not empty and
    `hookable` is one of already-hook, movable, hard (`export` writes a record it has to derive with them empty: the counts, the
    category, the feature and `hookable` where every line of the part is a hook form). `diffs` as for record_count_problems: only the
    records whose (file, folder) a hooks.patch carries are judged."""
    found = []
    for r in records:
        if diffs.get((r["file"], record_folder(r)), diffs.get(r["file"])) is None:
            continue
        for field in INVENTORY_HAND_FIELDS:
            if not (isinstance(r.get(field), str) and r[field].strip()):
                found.append(fail(
                    "%s, the record of %s in %s" % (record_where(r), r["file"], record_folder(r) or r.get("feature")),
                    "its `%s` is empty: the text of an inventory record is written by hand" % field,
                    "write `%s` in the record (what the hook is, in words; read the folder's part of the file in its hooks.patch)" % field, R_ONE_FACT))
        if r.get("hookable") not in INVENTORY_HOOKABLE:
            found.append(fail(
                "%s, the record of %s in %s" % (record_where(r), r["file"], record_folder(r) or r.get("feature")),
                "its `hookable` is %r, not one of %s" % (r.get("hookable"), ", ".join(INVENTORY_HOOKABLE)),
                "set `hookable` to `already-hook` when every line of the folder's part is a hook form, `movable` when the logic can move into a "
                "file of ours, `hard` when it cannot", R_ONE_FACT))
    return found


def evidence_problems(where: str, records: list) -> list:
    """repo-07: an inventory record (in the `inventory` of a MANIFEST.json) has no `evidence` field. The lines it
    quoted are the lines of the hooks.patch of its folder, which is the one place that has them."""
    return [fail("%s, the record of %s" % (where, r.get("file")), "it has an `evidence` field, a second copy of the lines its hooks.patch adds and removes",
                 "delete the field: the lines are the hooks.patch itself (`git diff` shows them; `%s` writes the record without it)" % command("export", "--source", "<source>"),
                 R_ONE_FACT) for r in records if "evidence" in r]


def manifest_hash_problems(folder: str, d: Path, manifest: dict) -> list:
    """The MANIFEST.json of a folder carries the sha256 of every file under its src/ (written by `export`): one missing, one left over for
    a file the folder no longer has, or a file whose bytes are not the recorded ones (a hand edit of src/, a merge that took one side)."""
    found = []
    hashes = manifest.get("sha256")
    again = command("export", "--source", "<source>")
    if not isinstance(hashes, dict):
        hashes = {}
        if manifest["added"]:
            found.append(fail("%s/MANIFEST.json" % folder, "it has no `sha256` map for the %d files it adds" % len(manifest["added"]),
                              "do not write it by hand: `%s` records the sha256 of every file under src/" % again, R_SERIES))
            return found
    for path in sorted(set(manifest["added"]) - set(hashes)):
        found.append(fail("%s/MANIFEST.json" % folder, "it has no sha256 for %s" % path,
                          "do not write it by hand: `%s` records the sha256 of every file under src/" % again, R_SERIES))
    for path in sorted(set(hashes) - set(manifest["added"])):
        found.append(fail("%s/MANIFEST.json" % folder, "it has a sha256 for %s, which the folder does not add" % path,
                          "do not edit the manifest: `%s` writes it" % again, R_SERIES))
    for path in sorted(set(manifest["added"]) & set(hashes)):
        file = d / "src" / path
        if file.is_file() and hashlib.sha256(file.read_bytes()).hexdigest() != hashes[path]:
            found.append(fail("%s/src/%s" % (folder, path), "its bytes are not the sha256 its MANIFEST.json records",
                              "src/ is written by the export only: `%s` writes it again from the source (a hand edit is made in the source)" % again, R_SERIES))
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
        return [fail("%s/%s" % (folder, BACKPORT), "it lacks %s" % ", ".join(missing),
                         "add the missing fields: commit, bug, date, files, drop_when", R_BACKPORT)]
    if not re.fullmatch(r"[0-9a-f]{40}", str(data["commit"])):
        found.append(fail("%s/%s" % (folder, BACKPORT), "commit %r is not a full sha" % data["commit"],
                              "name the commit of %s the diff comes from, as 40 hex digits" % MOZILLA_REPO, R_BACKPORT))
    ours = patch.read_bytes() if patch.exists() else b""
    for path in files:
        entry = (data["files"] if isinstance(data["files"], dict) else {}).get(path)
        if not isinstance(entry, dict) or not entry.get("diff") or not entry.get("sha256"):
            found.append(fail("%s/%s" % (folder, BACKPORT), "files has no diff and sha256 for %s" % path,
                                  "add both for the file: the stored diff of the commit and its sha256", R_BACKPORT))
            continue
        stored = ROOT / folder / entry["diff"]
        if not stored.is_file():
            found.append(fail("%s/%s" % (folder, BACKPORT), "the diff %s of %s is not in the folder" % (entry["diff"], path),
                                  "store the diff of the commit at that path, as Mozilla's repository has it", R_BACKPORT))
            continue
        theirs = normalized_diff(file_section(stored.read_bytes(), path))
        if not theirs:
            found.append(fail("%s/%s" % (folder, entry["diff"]), "it does not hold a diff of %s" % path,
                                  "store the diff of the commit for that file: run `git show --format= %s -- %s` in a clone of %s and save its output as %s/%s"
                                  % (data["commit"], path, MOZILLA_REPO, folder, entry["diff"]), R_BACKPORT))
        elif hashlib.sha256(theirs).hexdigest() != entry["sha256"]:
            found.append(fail("%s/%s" % (folder, entry["diff"]),
                                  "it is not the diff that BACKPORT.json declares for %s (sha256 differs)" % path,
                                  "restore the diff of the commit, unedited, from Mozilla's repository", R_BACKPORT))
        elif normalized_diff(file_section(ours, path)) != theirs:
            found.append(fail("%s/hooks.patch" % folder, "it changes %s differently from commit %s" % (path, data["commit"]),
                                  "make the file the diff of that commit byte for byte, not a diff touched by hand: export it from the source branch",
                                  R_BACKPORT))
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
    outside = [fail(folder, "%s is category backport outside vendored code (%s)" % (p, ", ".join(VENDORED)),
                        "make it the diff of one Mozilla commit in a folder of %s<name>, or take it out of category backport" % MOZILLA_BACKPORTS,
                        R_BACKPORT) for p in foreign]
    record = ROOT / folder / BACKPORT
    if not record.exists():
        return outside + [fail(folder, "it carries upstream code (%s) with no %s" % (sorted(upstream_code)[0], BACKPORT),
                                   "write %s: name the upstream, the vendored revision and the commits" % BACKPORT, R_BACKPORT)]
    data = json.loads(record.read_text(encoding="utf-8"))
    found = []
    if foreign:
        if not folder.startswith(MOZILLA_BACKPORTS):
            found += outside + [fail(
                folder, "it carries %s as the diff of a commit of %s outside %s<name>" % (foreign[0], MOZILLA_REPO, MOZILLA_BACKPORTS),
                "move the backport of a Mozilla commit to a folder of its own in %s, beside no logic of ours" % MOZILLA_BACKPORTS, R_BACKPORT)]
        elif is_mozilla_upstream(data.get("upstream")):
            found += mozilla_backport_problems(folder, foreign, data, patch)
        else:
            found += outside + [fail(
                "%s/%s" % (folder, BACKPORT), "upstream %r is not %s, the only upstream a file outside vendored code can be carried from"
                % (data.get("upstream"), MOZILLA_REPO), "set upstream to %s, or carry the file as vendored code if it is under third_party/rust/" % MOZILLA_REPO,
                R_BACKPORT)]
    if vendored:
        missing = [k for k in ("upstream", "vendored", "commits", "drop_when") if not data.get(k)]
        if missing:
            return found + [fail("%s/%s" % (folder, BACKPORT), "it lacks %s" % ", ".join(missing),
                                     "add the missing fields: upstream, vendored, commits, drop_when", R_BACKPORT)]
        # A crate vendored as a release (`vendored_crate`) has its revision in the crate's own .cargo_vcs_info.json, which the
        # hooks.patch does not touch: there `check --against <tag>` compares it with the tag's (backport_replay.folder_problems).
        if (not backport_replay.crate_spec(data)
                and data["vendored"] not in patch.read_text(encoding="utf-8", errors="replace")):
            found.append(fail(
                "%s/%s" % (folder, BACKPORT), "it says the vendored revision is %s, which its hooks.patch does not patch: Mozilla vendors another one now"
                % data["vendored"], "drop what upstream has and pick the rest again on the new revision (`%s` replays the commits)"
                % command("port", "--to", "<tag>", "--source", "<source>"), R_VENDORED))
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
                found.append(fail(
                    folder, "the tag %s already contains the backport of %s (commit %s)" % (tag, path, data.get("commit")),
                    "take the backport out of the series: restore its files to the tag's (`git checkout %s -- %s`), delete its record "
                    "from the `inventory` of its folder's MANIFEST.json, and export" % (tag, path), R_BACKPORT))
    return found


def vendored_backports() -> list:
    """[(folder, record)] of the folders whose BACKPORT.json is vendored code from an upstream that is not Mozilla's repository."""
    found = []
    for folder in existing_folders():
        record = ROOT / folder / BACKPORT
        if record.exists():
            data = json.loads(record.read_text(encoding="utf-8"))
            if not is_mozilla_upstream(data.get("upstream")):
                found.append((folder, data))
    return found


def backport_record_problems() -> list:
    """The offline half of port-04: each vendored backport's record is the object form, every commit file is in the folder
    with the sha256 the record gives, nothing points outside the series."""
    found = []
    for folder, data in vendored_backports():
        found += backport_replay.record_problems(ROOT / folder, data)
    return found


def backport_replay_problems(source: Path, tag: str) -> list:
    """The other half: the vendored part of each backport folder (hooks.patch, checksum lines, new files) against the replay of
    its commits on the revision `tag` vendors. Needs the tag's tree in `source`."""
    found = []
    for folder, data in vendored_backports():
        if backport_replay.record_problems(ROOT / folder, data):
            continue            # reported by backport_record_problems; there is nothing to replay
        try:
            found += backport_replay.folder_problems(backport_replay.replay(source, tag, ROOT / folder, data),
                                                     ROOT / folder, data)
        except backport_replay.Stop as stop:
            found.append(fail(folder, "the replay of its commits stopped: %s" % stop,
                                  "rebase the commit that does not apply onto the revision the tag vendors, then run "
                                  "`python tools/backport_replay.py report` until it has no conflict", R_VENDORED))
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
    hits = []
    i, n, line = 0, len(text), 1
    while i < n:
        c = text[i]
        two = text[i:i + 2]
        if two == "//":
            while i < n and text[i] != "\n":
                if ord(text[i]) < 32 and text[i] not in "\t\r":
                    hits.append((line, "control character %r in a comment" % text[i]))
                i += 1
            continue
        if two == "/*":
            end = text.find("*/", i + 2)
            end = n if end < 0 else end + 2
            for ch in text[i:end]:
                if ch == "\n":
                    line += 1
                elif ord(ch) < 32 and ch not in "\t\r":
                    hits.append((line, "control character %r in a comment" % ch))
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
                    hits.append((line, "a %s literal that does not end on its line (a raw control character may have ended it)"
                                  % ("string" if quote == '"' else "character")))
                    break
                if ord(ch) < 32 and ch != "\t":
                    hits.append((line, "control character %r inside a literal: write it as an escape" % ch))
                elif ord(ch) > 127:
                    hits.append((line, "character %r outside ASCII inside a literal: write it as an escape" % ch))
                j += 1
            i = j + 1
            continue
        if c == "\n":
            line += 1
        elif ord(c) < 32 and c not in "\t\r":
            hits.append((line, "control character %r" % c))
        elif c == "\r" and text[i + 1:i + 2] != "\n":
            hits.append((line, "a carriage return that is not part of a line ending"))
        i += 1
    return hits


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
                found.append(fail("%s/src/%s" % (folder, p.relative_to(src).as_posix()), "it is not valid UTF-8 (%s)" % err,
                                      "write the file as UTF-8 in the source, then export", R_SERIES))
                continue
            for line, what in cxx_byte_problems(text):
                found.append(fail("%s/src/%s:%d" % (folder, p.relative_to(src).as_posix(), line), what,
                                      "write the byte as an escape or remove it in the source, then export", R_SERIES))
    return found


def _cr_line(data: bytes) -> int:
    return data.count(b"\n", 0, data.index(b"\r")) + 1


def own_cr_problems() -> list:
    """A carriage return in a file of ours: every file under <folder>/src/, whatever its extension. Not judged: a
    binary file (it holds a NUL byte) and a file the folder's MANIFEST lists as category backport (upstream code
    carried as it is keeps the line endings of its origin)."""
    found = []
    for folder in existing_folders():
        src = ROOT / folder / "src"
        if not src.is_dir():
            continue
        manifest = json.loads((ROOT / folder / "MANIFEST.json").read_text(encoding="utf-8"))
        upstream_code = {r["file"] for r in manifest.get("inventory", []) if r["category"] == "backport"}
        for p in sorted(src.rglob("*")):
            rel = p.relative_to(src).as_posix()
            if not p.is_file() or rel in upstream_code:
                continue
            data = p.read_bytes()
            if b"\r" not in data or b"\0" in data:
                continue
            name = "%s/src/%s" % (folder, rel)
            found.append(fail(name, "%s has %d carriage return(s), the first on line %d: a file of ours ends its lines with LF only"
                                  % (name, data.count(b"\r"), _cr_line(data)),
                                  "write it with LF (open(path, \"w\", newline=\"\") and \"\\n\"), never through a text-mode "
                                  "stdout on Windows, then export", R_SERIES))
    return found


def patch_cr_problems(folder: str, data: bytes) -> list:
    """A carriage return in a line a hooks.patch adds to a Mozilla file (`data`: the bytes of the patch). The lines
    around ours are Mozilla's and may carry one if Mozilla's file does; a line of ours may end in CR only when every
    context line of its hunk does (the file is CRLF and the line keeps its ending)."""
    found, target, hunk, in_hunk = [], None, [], False

    def close():
        context = [text for _, kind, text in hunk if kind == b" "]
        crlf = bool(context) and all(text.endswith(b"\r") for text in context)
        for no, kind, text in hunk:
            if kind == b"+" and b"\r" in text and not (crlf and text.endswith(b"\r") and text.count(b"\r") == 1):
                found.append(fail(
                    "%s/hooks.patch:%d (adds to %s)" % (folder, no, target),
                    "the line has a carriage return, and %s: a line of ours ends with LF, with CRLF only in a hunk "
                    "whose context lines are CRLF (the file's own ending)"
                    % ("it is not a plain CRLF line" if crlf else "the context of its hunk is not CRLF"),
                    "write the patch with LF (open(path, \"w\", newline=\"\") and \"\\n\"), never through a text-mode stdout on Windows, "
                    "then export", R_SERIES))
        hunk.clear()

    for no, line in enumerate(data.split(b"\n"), 1):
        m = PATCH_FILE.match(line.decode("utf-8", errors="replace"))
        if m:
            close()
            target, in_hunk = m.group(1), False
        elif line.startswith(b"@@"):
            close()
            in_hunk = True
        elif in_hunk and line[:1] in (b"+", b" ", b"-"):
            hunk.append((no, line[:1], line[1:]))
    close()
    return found


def problems() -> list:
    """Every rule of the series that is broken now, as sentences."""
    found = []
    listed, present = series_folders(), existing_folders()
    if sorted(listed) != present:
        found.append(fail("SERIES", "SERIES and the folders differ: only in SERIES %s, only on disk %s"
                              % (sorted(set(listed) - set(present)), sorted(set(present) - set(listed))),
                              "export the series again from the source branch: it writes SERIES and the folders together", R_SERIES))
    if listed != sorted(listed, key=layout.folder_sort_key):
        found.append(fail("SERIES", "it is not in layout.GROUP_ORDER order",
                              "export the series again: it writes SERIES in the order of tools/layout.py", R_SERIES))
    budget = json.loads(BUDGET.read_text(encoding="utf-8"))
    removed_budget = json.loads(REMOVED_BUDGET.read_text(encoding="utf-8"))
    for path, first, second in layout.src_owners(ROOT)[1]:
        found.append(fail(path, "it is under the src/ of both %s and %s" % (first, second),
                          "a file of ours has one owner: export again with --own %s=<folder> naming the one that keeps it" % path, R_SERIES))
    seen = set()          # the budget keys (<file>|<folder>) some hooks.patch touches
    for folder in present:
        d = ROOT / folder
        if not (d / "FEATURE.md").exists():
            found.append(fail(folder, "it has no FEATURE.md", "write %s/FEATURE.md: what the feature does, its Test: line" % folder, R_SERIES))
        manifest = json.loads((d / "MANIFEST.json").read_text(encoding="utf-8"))
        for path in manifest["added"]:
            if not (d / "src" / path).is_file():
                found.append(fail("%s/MANIFEST.json" % folder, "it lists %s, src/ does not have it" % path,
                                      "export the series again: the manifest and src/ are written together", R_SERIES))
        if (d / "src").exists():
            on_disk = {str(p.relative_to(d / "src")).replace("\\", "/")
                       for p in (d / "src").rglob("*") if p.is_file()}
            for extra in sorted(on_disk - set(manifest["added"])):
                found.append(fail("%s/src/%s" % (folder, extra), "it is not in the MANIFEST of its folder",
                                      "export the series again: the manifest lists every file under src/", R_SERIES))
        found += manifest_hash_problems(folder, d, manifest)
        found += evidence_problems("%s/MANIFEST.json" % folder, manifest.get("inventory", []))
        found += [fail("%s/MANIFEST.json" % folder, "the record of %s (feature %s) belongs to the folder %s, not to this one" % (r["file"], r.get("feature"), record_folder(r)),
                       "move the record to the `inventory` of the MANIFEST.json of the folder its feature maps to (tools/layout.py FEATURES)", R_ONE_FACT)
                  for r in manifest.get("inventory", []) if record_folder(r) != folder]
        patch = d / "hooks.patch"
        touched = added_lines(patch) if patch.exists() else {}
        removed = removed_lines(patch) if patch.exists() else {}
        if sorted(touched) != sorted(manifest["modified"]):
            found.append(fail("%s/hooks.patch" % folder, "it touches %s, MANIFEST owns %s" % (sorted(touched), manifest["modified"]),
                                  "export the series again: hooks.patch and MANIFEST.json are written together", R_SERIES))
        upstream_code = {r["file"] for r in manifest.get("inventory", []) if r["category"] == "backport"}
        found += backport_problems(folder, upstream_code, patch)
        for path, n in touched.items():
            key = budget_key(path, folder)
            seen.add(key)
            if path in upstream_code:
                if key in budget or key in removed_budget:
                    found.append(fail("%s (%s)" % (path, folder), "it is upstream code (category backport) and has a hook or removed budget",
                                          "take it out of tools/hook-budget.json and tools/removed-budget.json", R_BACKPORT))
                continue
            allowed = budget.get(key)
            if allowed is None:
                found.append(fail("%s (%s)" % (path, folder), "it is a Mozilla file with no hook budget: a new hook is at most 5 lines",
                                      "add %s to tools/hook-budget.json with its real count, at most 5" % key, R_BUDGET))
            elif n > allowed:
                found.append(fail("%s (%s)" % (path, folder), "it carries %d of our lines, its budget is %d" % (n, allowed),
                                      "move the logic into a file of ours and leave a hook (never raise the budget)", R_BUDGET))
            r, r_allowed = removed.get(path, 0), removed_budget.get(key, 0)
            if r > r_allowed:
                found.append(fail("%s (%s)" % (path, folder), "it loses or has rewritten %d of Mozilla's lines, its removed budget is %d"
                                      % (r, r_allowed), "leave Mozilla's lines as they are and put the hook beside them", R_BUDGET))
    for key in sorted(set(budget) - seen):
        found.append(fail("tools/hook-budget.json", "it still lists %s, which no patch touches" % key,
                              "remove it from the file (`%s` lowers budgets, it does not remove a file)" % command("shrink-budget"), R_BUDGET))
    for key in sorted(set(removed_budget) - seen):
        found.append(fail("tools/removed-budget.json", "it still lists %s, which no patch touches" % key,
                              "remove it from the file (`%s` lowers budgets, it does not remove a file)" % command("shrink-budget"), R_BUDGET))
    patches = {f: (ROOT / f / "hooks.patch").read_text(encoding="utf-8", errors="replace")
               for f in present if (ROOT / f / "hooks.patch").exists()}
    records = inventory_records()
    if legacy_inventory().exists():
        found.append(fail("tools/inventory.json", "the file exists: it is a second copy of the `inventory` of the MANIFEST.json files, which are the one place that has the records",
                          "delete tools/inventory.json: the inventory lives in each folder's MANIFEST.json (`export` writes it, a hand edits only the hand fields there)", R_ONE_FACT))
    found += hook_tag_problems(set(listed), patches)
    diffs = {}
    for f in present:
        patch = ROOT / f / "hooks.patch"
        if patch.exists():
            diffs.update({(path, f): d for path, d in _diffs_of(patch).items()})
    found += record_count_problems(records, diffs)
    found += inventory_hand_problems(records, diffs)      # the text a hand writes in a record the export derived: every caller of problems() sees it
    found += record_inline_problems(records, diffs, {f: (ROOT / f / "hooks.patch").read_bytes() for f in present if (ROOT / f / "hooks.patch").exists()})
    found += own_cxx_problems()
    found += own_cr_problems()
    for f in present:
        if (ROOT / f / "hooks.patch").exists():
            found += patch_cr_problems(f, (ROOT / f / "hooks.patch").read_bytes())
    found += hooks_list.problems(ROOT)
    found += gtest_list.problems(ROOT)       # repo-06: tools/gtest-suites.json is what `gtest-list --write` writes
    found += backport_record_problems()
    found += births.ledger_problems(births.load_ledger(), set(listed))
    series_wf = {p.name: p.read_bytes() for p in WORKFLOWS_SERIES.glob("*.yml")}
    root_wf = {p.name: p.read_bytes() for p in WORKFLOWS_ROOT.glob("*.yml")}
    for name in sorted(set(series_wf) | set(root_wf) - ROOT_ONLY_WORKFLOWS):
        if series_wf.get(name) != root_wf.get(name):
            found.append(fail(".github/workflows/%s" % name, "%s differs from the series' copy (platform/ci/src/.github/workflows)" % name,
                                  "edit the workflow in the source, then export: the root copy is written by the export", R_SERIES))
    return found


MAIN_REF = "refs/remotes/origin/main"


def main_budget_text(name: str) -> str | None:
    """tools/<name> as origin/main has it, never from the branch; None if main does not resolve."""
    done = subprocess.run(["git", "-C", str(ROOT), "show", "origin/main:tools/" + name],
                          capture_output=True)
    return done.stdout.decode("utf-8") if done.returncode == 0 else None


def ensure_main_ref() -> None:
    """origin/main resolves, or it is fetched once (depth 1); SystemExit if it still does not."""
    def resolves():
        return subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--verify", "-q", "origin/main"],
                              capture_output=True).returncode == 0
    if not resolves():
        subprocess.run(["git", "-C", str(ROOT), "fetch", "--no-tags", "--depth=1", "origin",
                        "+refs/heads/main:" + MAIN_REF], capture_output=True)
    if not resolves():
        raise SystemExit(halt(fail("origin/main in this repository", "it does not resolve, and a fetch of it did not make it",
                                   "fetch it: git fetch --no-tags --depth=1 origin +refs/heads/main:%s" % MAIN_REF, R_BUDGET),
                              command("check")))


def load_main_budgets() -> tuple[dict, dict]:
    """Main's hook and removed budgets. Fetches origin/main once if it is not there yet."""
    ensure_main_ref()
    texts = [main_budget_text("hook-budget.json"), main_budget_text("removed-budget.json")]
    if None in texts:
        raise SystemExit(halt(fail("tools/hook-budget.json and tools/removed-budget.json on origin/main", "main has no such file",
                                   "fetch origin main (it must carry both budgets): git fetch --no-tags --depth=1 origin +refs/heads/main:%s" % MAIN_REF,
                                   R_BUDGET), command("check")))
    return json.loads(texts[0]), json.loads(texts[1])


def load_main_debt() -> list | None:
    """Main's hook-debt list, or None while main has none yet."""
    ensure_main_ref()
    text = main_budget_text("hook-debt.json")
    return json.loads(text) if text is not None else None


RAISE_FIELDS = ("file", "from", "to", "folder", "reason", "decided_by", "date", "test")
RAISE_BUDGETS = ("hook", "removed")              # what a row raises: our lines (the default) or the removed lines of Mozilla's
RAISE_TEXT_FIELDS = ("reason", "decided_by")      # free text: may be reworded; every other field of a row is fixed


def raise_key(row) -> str:
    """A row of the register without its free-text fields: what identifies it against main's copy."""
    if not isinstance(row, dict):
        return repr(row)
    return json.dumps({k: v for k, v in row.items() if k not in RAISE_TEXT_FIELDS}, sort_keys=True)


def load_main_raises() -> list | None:
    """The register of declared hook budget raises as origin/main has it (never the branch's); None while
    main has none yet. Call after load_main_budgets, which makes sure origin/main is there."""
    text = main_budget_text("hook-budget-raises.json")
    return json.loads(text) if text is not None else None


def raises_list_problems(rows: list, main_rows: list | None) -> list:
    """tools/hook-budget-raises.json only grows: every row of main's register is on the branch with the same
    fields but the free text (RAISE_TEXT_FIELDS: none removed, none changed), and every row has its eight
    fields, `from` and `to` whole numbers with `to` above `from`, the others text that is not empty, `date`
    as YYYY-MM-DD."""
    found = []
    for r in rows:
        name = r.get("file") if isinstance(r, dict) else None
        if not isinstance(r, dict) or set(r) not in (set(RAISE_FIELDS), set(RAISE_FIELDS) | {"budget"}):
            found.append(fail("tools/hook-budget-raises.json", "a row of %s does not have exactly the fields %s (and, to raise the removed budget, `budget`)"
                                  % (name or "no file", ", ".join(RAISE_FIELDS)), "give the row exactly the fields %s, and `budget` only to raise the removed budget" % ", ".join(RAISE_FIELDS), R_BUDGET))
            continue
        if r.get("budget", "hook") not in RAISE_BUDGETS:
            found.append(fail("tools/hook-budget-raises.json", "the row of %s has the budget %r" % (name, r["budget"]),
                                  "write `budget` as %s" % " or ".join(RAISE_BUDGETS), R_BUDGET))
            continue
        if not all(isinstance(r[k], str) and r[k].strip() for k in RAISE_FIELDS if k not in ("from", "to")):
            found.append(fail("tools/hook-budget-raises.json", "the row of %s has an empty field" % name,
                                  "say file, folder, reason, decided_by, date and test", R_BUDGET))
        elif not re.fullmatch(r"\d{4}-\d{2}-\d{2}", r["date"]):
            found.append(fail("tools/hook-budget-raises.json", "the row of %s has the date %r, not YYYY-MM-DD" % (name, r["date"]),
                                  "write the date as YYYY-MM-DD", R_BUDGET))
        if not (type(r["from"]) is int and type(r["to"]) is int and 0 <= r["from"] < r["to"]):
            found.append(fail("tools/hook-budget-raises.json", "the row of %s raises from %r to %r" % (name, r["from"], r["to"]),
                                  "write `from` and `to` as two whole numbers, `to` above `from`", R_BUDGET))
    keys = {raise_key(r) for r in rows}
    for m in main_rows or ():
        if raise_key(m) not in keys:
            found.append(fail("tools/hook-budget-raises.json", "main's row of %s (%r to %r) is gone or changed" % (m.get("file"), m.get("from"), m.get("to")),
                                  "restore the row as main has it: the register only grows", R_BUDGET))
    return found


def new_raise_rows(rows: list, main_rows: list | None) -> list:
    """The rows of the branch's register that main's does not have (compared without the free text): the
    raises this branch declares. While main has no register (None) nothing can be declared: the door must be
    on main before it is used."""
    if main_rows is None:
        return []
    main_keys = {raise_key(m) for m in main_rows}
    return [r for r in rows if raise_key(r) not in main_keys]


def budget_units(branch: dict, main_hook: dict) -> dict:
    """{unit: value} of a branch budget, the unit being what main's budget is compared with. A key is `<file>|<folder>`. While main's budget
    is still keyed by file (`main_hook` has the file), the unit is the file and its value the sum of the branch's keys of that file: a file
    cannot gain a line by moving it from a folder to another. Where main has the key itself, or has nothing for the file, the unit is
    the key."""
    units = {}
    for key, n in branch.items():
        file = key_file(key)
        unit = file if file in main_hook else key
        units[unit] = units.get(unit, 0) + n
    return units


def raise_unit(row: dict, main_hook: dict) -> str:
    """The unit (budget_units) a row of the register raises: the file while main's budget is keyed by file, else the key `<file>|<folder>`."""
    file = row.get("file")
    if not isinstance(file, str) or file in main_hook or KEY_SEP in file:
        return file
    return budget_key(file, row.get("folder"))


def budget_raise_problems(hook: dict, removed: dict, main_hook: dict, main_removed: dict,
                          raises: list | None = None) -> list:
    """Budgets only go down: a value above main's, or a new key's hook above 5 lines, is a failure. A budget is per `<file>|<folder>`; while
    main's is still per file (no `|`), the keys of a file are compared as a sum with main's ceiling of the file (budget_units), so the
    split never loosens one. raises are the rows the branch ADDS to tools/hook-budget-raises.json (new_raise_rows): a hook budget
    of a key (a file, while main's is per file) main patches may go above main's only with one such row, `from` main's budget and `to` the
    branch's; a row that raises nothing, or one of a key main does not patch, is a failure too. A row with
    `budget: "removed"` does the same for the removed budget: `from` main's removed budget (0 when it has none),
    `to` the branch's; one raise per key and budget."""
    found = []
    declared = {}
    declared_removed = {}
    hook_units, removed_units = budget_units(hook, main_hook), budget_units(removed, main_hook)
    for r in raises or ():
        path = raise_unit(r, main_hook)
        is_removed = r.get("budget", "hook") == "removed"
        table = declared_removed if is_removed else declared
        if path in table:
            found.append(fail("tools/hook-budget-raises.json", "there are two rows for %s" % path,
                                  "keep one raise per file, budget and branch", R_BUDGET))
            continue
        table[path] = r
        if path not in main_hook:
            found.append(fail("tools/hook-budget-raises.json", "the row of %s is for a file main does not patch: a new file has its 5 lines, no raise" % path,
                                  "delete the row and keep the hook within 5 lines", R_BUDGET))
        elif is_removed:
            if r.get("from") != main_removed.get(path, 0) or r.get("to") != removed_units.get(path):
                found.append(fail("tools/hook-budget-raises.json", "the row of %s raises the removed budget from %r to %r, but main's is %d and the branch's %s"
                                      % (path, r.get("from"), r.get("to"), main_removed.get(path, 0), removed_units.get(path)),
                                      "set `from` to main's budget and `to` to the new one", R_BUDGET))
        elif r.get("from") != main_hook[path] or r.get("to") != hook_units.get(path):
            found.append(fail("tools/hook-budget-raises.json", "the row of %s raises from %r to %r, but main's budget is %d and the branch's %s"
                                  % (path, r.get("from"), r.get("to"), main_hook[path], hook_units.get(path)),
                                  "set `from` to main's budget and `to` to the new one", R_BUDGET))
    for path, n in sorted(hook_units.items()):
        if path in main_hook:
            limit, what = main_hook[path], "main's %d" % main_hook[path]
        else:
            limit, what = 5, "5"
        if n > limit and path in declared:
            continue          # declared: its row is judged above
        if n > limit:
            if path in main_hook or what != "5":
                found.append(fail("%s in tools/hook-budget.json" % path, "hook budget %d is above %s" % (n, what),
                                      "budgets only go down: move the logic into our files", R_BUDGET))
            else:
                found.append(fail("%s in tools/hook-budget.json" % path, "hook budget %d for a file new to the series" % n,
                                      "a new hook is at most 5 lines: move the logic into our files", R_BUDGET))
    for path, n in sorted(removed_units.items()):
        if path in main_hook:
            limit, what = main_removed.get(path, 0), "main's %d" % main_removed.get(path, 0)
        else:
            limit, what = 5, "5"
        if n > limit and path in declared_removed:
            continue          # declared: its row is judged above
        if n > limit:
            if path in main_hook or what != "5":
                found.append(fail("%s in tools/removed-budget.json" % path, "removed budget %d is above %s" % (n, what),
                                      "budgets only go down: leave Mozilla's lines as they are", R_BUDGET))
            else:
                found.append(fail("%s in tools/removed-budget.json" % path, "removed budget %d for a file new to the series" % n,
                                      "a new file may lose at most 5 of Mozilla's lines: leave the rest as they are", R_BUDGET))
    return found


def contract_problems(against_main: bool = False, base=None) -> tuple[list, int, int]:
    """The hook contract against tools/hook-debt.json (and, against_main, against main's list):
    the problems, the number of hooks and the number of violations. `base` (hook_contract.git_base_reader): C16 reads the
    locals of Mozilla's functions from the base files, not only from the lines the hunks show."""
    hooks = hook_contract.series_hooks(ROOT)
    violations = hook_contract.contract_violations(ROOT)
    if base is not None:
        violations = ([v for v in violations if v.rule not in ("C16", "C17")] + hook_contract.locals_violations(ROOT, base)
                      + hook_contract.namespace_violations(ROOT, unqualified=True))
    # port-07 (C18): where Mozilla is quiet; offline (tools/churn.json and UPSTREAM.json), never debt. Its own function, not part of
    # contract_violations: that one is judged on any series root, this one needs the series' churn file.
    violations = violations + hook_contract.churn_violations(ROOT)
    if not HOOK_DEBT.is_file():
        return [fail("tools/hook-debt.json", "it is missing", "write it once from every violation of now: `%s`" % command("hook-debt", "--init"),
                         R_BUDGET)], len(hooks), len(violations)
    return (hook_contract.debt_problems(violations, hook_contract.load_debt(HOOK_DEBT),
                                        load_main_debt() if against_main else None),
            len(hooks), len(violations))


def declared_exceptions() -> int:
    """How many hooks are declared exceptions (G35: `exception` and `pm: "approvato"` in their HOOKS.json entry)."""
    return len(hooks_list.declared_exceptions(ROOT)) if (ROOT / "SERIES").is_file() else 0


def untestable_hooks() -> int:
    """How many hooks the pm declared untestable (`untestable` and `pm: "approvato"` in their HOOKS.json entry)."""
    return len(hooks_list.untestable_hooks(ROOT)) if (ROOT / "SERIES").is_file() else 0


def folder_diffs() -> dict:
    """{(file, folder): file_diffs entry} of every hooks.patch of the series."""
    found = {}
    for folder in existing_folders():
        patch = ROOT / folder / "hooks.patch"
        if patch.exists():
            found.update({(path, folder): d for path, d in _diffs_of(patch).items()})
    return found


def check(source: Path | None = None, tag: str | None = None, against_main: bool = False) -> int:
    found = problems()
    found += folders.problems(ROOT)       # series-02: every folder states its relation to Mozilla (tools/folders.py)
    if against_main:      # the CLI does; it needs git and origin/main, problems() and the tests' fakes do not
        main_hook, main_removed = load_main_budgets()
        main_raises = load_main_raises()
        raises = json.loads(RAISES.read_text(encoding="utf-8")) if RAISES.is_file() else []
        found += raises_list_problems(raises, main_raises)
        found += budget_raise_problems(json.loads(BUDGET.read_text(encoding="utf-8")),
                                       json.loads(REMOVED_BUDGET.read_text(encoding="utf-8")),
                                       main_hook, main_removed, new_raise_rows(raises, main_raises))
    base = hook_contract.git_base_reader(source, tag) if source is not None and tag else None
    contract, n_hooks, n_violations = (contract_problems(against_main, base) if base is not None
                                       else contract_problems(against_main))
    found += contract
    if source is not None and tag:
        found += backport_in_tag_problems(source, tag)
        found += backport_replay_problems(source, tag)
    for p in found:
        print(p)
    if found:
        print("next: %s" % command(*(["check", "--source", "<source>", "--against", tag] if source is not None and tag else ["check"])))
    if not found:
        total = sum(json.loads(BUDGET.read_text(encoding="utf-8")).values())
        gone = sum(json.loads(REMOVED_BUDGET.read_text(encoding="utf-8")).values())
        print("ok: %d folders, %d of our lines in Mozilla files, %d of Mozilla's lines removed "
              "or rewritten" % (len(series_folders()), total, gone))
        print("hook contract: %d hooks, %d violations, all in tools/hook-debt.json"
              % (n_hooks, n_violations))
        print("declared exceptions: %d" % declared_exceptions())
        print("untestable hooks: %d" % untestable_hooks())
    return 1 if found else 0


def shrink_budget() -> None:
    """Lowers each budget (one per `<file>|<folder>`) to the lines that folder's hooks.patch carries in that file now. Never raises one."""
    budget = json.loads(BUDGET.read_text(encoding="utf-8"))
    removed_budget = json.loads(REMOVED_BUDGET.read_text(encoding="utf-8"))
    for folder in existing_folders():
        patch = ROOT / folder / "hooks.patch"
        for path, n in (added_lines(patch) if patch.exists() else {}).items():
            key = budget_key(path, folder)
            if key in budget and n < budget[key]:
                print("%s: %d -> %d" % (key, budget[key], n))
                budget[key] = n
        for path, n in (removed_lines(patch) if patch.exists() else {}).items():
            key = budget_key(path, folder)
            if key in removed_budget and n < removed_budget[key]:
                print("%s: %d -> %d removed" % (key, removed_budget[key], n))
                removed_budget[key] = n
    write_json(BUDGET, dict(sorted(budget.items())))
    # A file that no longer removes anything leaves the removed budget: 0 is the default.
    write_json(REMOVED_BUDGET, {p: n for p, n in sorted(removed_budget.items()) if n})


def hook_debt(init: bool = False, summary: bool = False) -> int:
    """Writes tools/hook-debt.json: without --init only the entries that still occur stay (the list
    never grows by itself); --summary prints the per-rule and per-folder counts and writes nothing."""
    violations = hook_contract.contract_violations(ROOT)
    debt = hook_contract.load_debt(HOOK_DEBT)
    if summary:
        print(hook_contract.debt_summary(debt))
        return 0
    if not HOOK_DEBT.is_file() and not init:
        raise SystemExit(halt(fail("tools/hook-debt.json", "it does not exist",
                                   "write it once from every violation of now: `%s`" % command("hook-debt", "--init"), R_BUDGET),
                              command("hook-debt", "--init")))
    kept = hook_contract.update_debt(debt, violations, init)
    hook_contract.write_debt(HOOK_DEBT, kept)
    print("tools/hook-debt.json: %d entries (%d before), %d violations now"
          % (len(kept), len(debt), len(violations)))
    return 0


def hook_locals(source: Path, tag: str) -> int:
    """C16 (hook-02 point 3) and C17 (point 7) with the whole function and the enclosing namespaces read from the Mozilla tag in
    `source`, not only from the lines a hunk shows: a hook that is not an anchor and passes a local of Mozilla's function, or that
    names a function of ours in a top-level namespace that is not `mozilla`, is red. Reads the tag's objects only."""
    base = hook_contract.git_base_reader(source, tag)
    found = hook_contract.locals_violations(ROOT, base) + hook_contract.namespace_violations(ROOT, unqualified=True)
    for v in found:
        print(hook_contract.violation_failure(v))
    if not found:
        print("ok: no hook passes a local of Mozilla's function or sits in a namespace that is not ours (read from %s)" % tag)
    else:
        print("next: %s" % command("export", "--source", "<source>"))
    return 1 if found else 0


def status(source: Path, head: str) -> int:
    up = upstream()
    now = git(source, "rev-parse", head).decode().strip()
    if now == up.get("exported_from"):
        print("in step: the series is %s at %s" % (head, now[:10]))
        return 0
    behind = git(source, "log", "--oneline", "%s..%s" % (up["exported_from"], head)).decode()
    print(fail("%s in the source repository" % head,
               "it is %s, the series was exported from %s; the source moved:\n%s" % (now, up["exported_from"], behind.rstrip()),
               "run export, then verify", R_SERIES))
    print("next: %s" % command("export", "--source", "<source>", "--head", head))
    return 1


SOURCE_COMMANDS = ("status", "apply", "export", "verify", "drift", "port", "hook-locals")     # check needs it only with --against

# The front door's list: every command with one line (a test requires each choice of the parser to be here).
COMMAND_LINES = (
    ("status", "did the source move since the last export?"),
    ("export", "write the series from the source tree (the node tests run first)"),
    ("verify", "rebuild the tree from the series and compare it with the source head"),
    ("check", "the series' own rules, offline (also in CI)"),
    ("apply", "the series as a branch of the source: the tag and one commit per folder"),
    ("drift", "our patched Mozilla files that Mozilla changed between the tag and --to"),
    ("port", "move the series to the tag --to: every conflict in one run, then UPSTREAM.json is written"),
    ("hooks-list", "write every folder's HOOKS.json from its hooks.patch (the export does it too)"),
    ("gtest-list", "the gtest suites the hooks name, in tools/gtest-suites.json (--write writes it, without it only compares; the export writes it too)"),
    ("hook-debt", "drop the entries of tools/hook-debt.json that no longer occur (--summary only counts)"),
    ("hook-locals", "hooks that pass a local of Mozilla's function, read from the tag in the source"),
    ("shrink-budget", "lower the budgets to the lines the patches carry now"),
    ("materialize", "CI: fetch the tag, apply the series, check out the tree (--into)"),
    ("prebuild", "what a failed build would say an hour later, in seconds (tools/prebuild.py)"),
    ("births", "every place the tree makes a network request, against the ledger (tools/births.py)"),
    ("docs", "the sections of the docs that the tables generate (--write rewrites them, --check compares)"),
    ("range-diff", "the layers of the old series against the new one, in ports/range-diff.txt (tools/range_diff.py)"),
)
COMMAND_NAMES = [name for name, _ in COMMAND_LINES]


class Parser(argparse.ArgumentParser):
    """A wrong command line is a failure like any other: where, what, fix, rule, and the next command."""

    def error(self, message):
        self.exit(2, "%s\nnext: %s\n" % (fail(
            "python tools/engine.py", "the command line is wrong: %s" % message,
            "run it with no argument: it prints every command, one line each, and the state of the series", R_SERIES), command()))


def build_parser() -> argparse.ArgumentParser:
    ap = Parser(prog="python tools/engine.py", description="The engine as a patch series (the first lines of tools/engine.py say how each command works).",
                add_help=False)
    ap.add_argument("command", nargs="?", choices=COMMAND_NAMES, metavar="command", help="one of: " + ", ".join(COMMAND_NAMES))
    ap.add_argument("-h", "--help", action="store_true", help="the front door: the state of the series, every command, the next one")
    ap.add_argument("--to", help="drift/port: the Mozilla tag to move to (a stable release, never a beta)")
    ap.add_argument("--into", type=Path, default=Path("."), help="materialize: the directory to make the tree")
    ap.add_argument("--shared", type=Path, default=None,
                    help="materialize: a directory every leg of this machine reaches; the tag is fetched "
                         "and the series applied there once, and each leg borrows the objects")
    ap.add_argument("--source", type=Path, default=Path(os.environ["FIREFOX_SOURCE"]) if os.environ.get("FIREFOX_SOURCE") else None,
                    help="the Firefox source repository (or the environment variable FIREFOX_SOURCE); no default")
    ap.add_argument("--against", help="check: also try the backports of Mozilla commits against this tag, "
                                      "found in --source (a port does it by itself)")
    ap.add_argument("--own", action="append", default=[], metavar="PATH=FOLDER",
                    help="export: the folder of a new file of ours that no folder holds yet (PATH ends with / for every new file under it); "
                         "a file already under a folder's src/ needs none")
    ap.add_argument("--write", action="store_true", help="gtest-list: write tools/gtest-suites.json (without it the file is only compared)")
    ap.add_argument("--init", action="store_true", help="hook-debt: write the list from every violation of now (once)")
    ap.add_argument("--summary", action="store_true", help="hook-debt: count the list per rule and folder, write nothing")
    ap.add_argument("--base", help="the Mozilla tag the series is on (default: mozilla_tag of UPSTREAM.json)")
    ap.add_argument("--head", help="the source branch (default: source_branch of UPSTREAM.json; apply: the branch it creates; port: the branch it makes)")
    ap.add_argument("--force", action="store_true", help="apply/port: rebuild an existing branch")
    return ap


def declared_owners(values: list) -> dict:
    """`--own PATH=FOLDER` (repeated) as {path or dir/: folder}; a value that is not that shape, or names a folder outside the groups, stops."""
    declared = {}
    for value in values:
        path, equals, folder = value.partition("=")
        if not (path and equals and folder) or folder.split("/")[0] not in layout.GROUP_ORDER or folder.count("/") < 1:
            raise SystemExit(halt(fail(
                "python tools/engine.py export --own %s" % value, "it is not <path or dir/>=<folder>, with a folder under one of %s" % ", ".join(layout.GROUP_ORDER),
                "write --own dom/base/StealthX.cpp=fingerprint/js-surface/stack-frames (a folder of SERIES, or a new one under a group)", R_SERIES),
                command("export", "--source", "<source>")))
        declared[path] = folder
    return declared


def head_verdict(source: Path, base: str, head: str) -> str:
    """Would `verify` pass: the series rebuilt on the tag against the tree of the source head, said in a sentence (nothing is written)."""
    try:
        if subprocess.run(["git", "-C", str(source), "merge-base", "--is-ancestor", base, head], capture_output=True).returncode:
            return "verify would stop: %s does not descend from %s" % (head, base)
        built = rebuilt_tree(source, base)
        expected = git(source, "rev-parse", "%s^{tree}" % head).decode().strip()
    except (subprocess.CalledProcessError, OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
        return "verify cannot run here: %s" % (exc.stderr.decode(errors="replace").strip() if getattr(exc, "stderr", None) else exc)
    if built == expected:
        return "verify would pass: the series rebuilds the head exactly (tree %s)" % built[:12]
    return "verify would fail: the series rebuilds tree %s, the head is tree %s" % (built[:12], expected[:12])


def front_door(source: Path | None, head: str | None = None, base: str | None = None) -> int:
    """repo-05, `python tools/engine.py` with no argument and `--help`: the state of the series, every command with one line, and the
    most likely next command for that state."""
    up = upstream()
    base, head = base or up["mozilla_tag"], head or up["source_branch"]
    print("series: mozilla_tag %s, source_branch %s, exported_from %s" % (up["mozilla_tag"], up["source_branch"], up.get("exported_from", "(never)")))
    if source is None:
        print("source: not given (--source <path>, or the environment variable FIREFOX_SOURCE): what moved cannot be read")
        following = command("status", "--source", "<source>")
    else:
        try:
            now = git(source, "rev-parse", "%s^{commit}" % head).decode().strip()
        except (subprocess.CalledProcessError, OSError):
            print("source: %s has no branch %s" % (source, head))
            following = command("apply", "--source", "<source>", "--head", head)
        else:
            same = now == up.get("exported_from")
            print("source: %s is %s, %s exported_from" % (head, now[:10], "equal to" if same else "not"))
            verdict = head_verdict(source, base, head)
            print("source: " + verdict)
            following = command("check") if same and verdict.startswith("verify would pass") else command("export", "--source", "<source>", "--head", head)
    print("commands:")
    width = max(len(name) for name in COMMAND_NAMES)
    for name, line in COMMAND_LINES:
        print("  %s  %s" % (name.ljust(width), line))
    print()
    print(build_parser().format_help().rstrip())
    print()
    print("next: %s" % following)
    return 0


def entry() -> int:
    """The command line: `main()` with every stop ending in `next:` (repo-05)."""
    again = command(*sys.argv[1:])
    try:
        return main()
    except SystemExit as stopped:
        raise stop_if_not_marked(stopped, again) from None
    except subprocess.CalledProcessError as exc:
        raise SystemExit(halt(fail(
            "git %s" % " ".join(str(x) for x in exc.cmd[1:]),
            "it exited %s: %s" % (exc.returncode, (exc.stderr or b"").decode(errors="replace").strip() or "no message"),
            "run `%s` by hand to see git's message, then by case: `not a git repository` means --source (or FIREFOX_SOURCE) is not the Firefox repository: "
            "pass the folder that holds its .git; `unknown revision` or `bad object` means the branch or tag is missing: run `git -C <source> fetch --tags origin`, "
            "or pass --head with a branch it has; `index.lock` exists means an earlier git run left it: delete that file once no git process is running; "
            "then run the command again" % " ".join(str(x) for x in exc.cmd),
            R_SERIES), again)) from None


def main() -> int:
    if sys.argv[1:2] == ["docs"]: return hook_contract.docs_main(ROOT, sys.argv[2:])      # --write | --check: the sections the tables generate
    if len(sys.argv) > 1 and sys.argv[1] == "births":
        return births.main(sys.argv[2:])      # its own options: --tree, --repo/--rev, --skeleton, --accept-changed, --prune, --tsv
    if len(sys.argv) > 1 and sys.argv[1] == "prebuild":
        import prebuild
        return prebuild.main(sys.argv[2:])    # its own options: --head, --base, --folder, --checks, --json (tools/prebuild.py)
    if len(sys.argv) > 1 and sys.argv[1] == "range-diff":
        import range_diff
        return range_diff.main(sys.argv[2:], build_stack)    # its own options: --source, --old-series, --fetch, --write, --check, --decide
    a = build_parser().parse_args()
    up = upstream()
    base, head = a.base or up["mozilla_tag"], a.head or up["source_branch"]
    if a.command is None or a.help:
        return front_door(a.source, a.head, a.base)
    if a.command in SOURCE_COMMANDS or (a.command == "check" and a.against):
        if a.source is None:
            raise SystemExit(halt(fail(
                "python tools/engine.py %s" % a.command, "it needs the source repository, and none is given",
                "pass --source <path> of the Firefox repository, or set the environment variable FIREFOX_SOURCE",
                R_SERIES), command(*([a.command] + (["--to", a.to or "<tag>"] if a.command in ("drift", "port") else []) + (["--against", a.against] if a.against else [])
                                     + ["--source", "<source>"]))))
    if a.command in ("drift", "port"):
        if not a.to:
            raise SystemExit(halt(fail(
                "python tools/engine.py %s" % a.command, "it needs --to <Mozilla tag>",
                "name the stable release tag to move to, e.g. FIREFOX_160_0_1_RELEASE (never a beta)", R_PORT),
                command(a.command, "--to", "<tag>", "--source", "<source>")))
        if a.command == "drift":
            return drift(a.source, base, a.to)
        return port(a.source, base, a.to, a.head if a.head else "port/%s" % a.to, a.force, check_births=True, record_upstream=UPSTREAM)
    if a.command == "materialize":
        materialize(a.into, shared=a.shared)
        return 0
    if a.command == "apply":
        apply(a.source, base, head, a.force)
        return 0
    if a.command == "check":
        return check(a.source, a.against or None, against_main=True)
    if a.command == "hook-debt":
        return hook_debt(a.init, a.summary)
    if a.command == "hook-locals":
        return hook_locals(a.source, a.against or base)
    if a.command == "hooks-list":
        print(write_hooks_list())
        return 0
    if a.command == "gtest-list":
        if a.write:
            print(write_gtest_list())
            return 0
        found = gtest_list.problems(ROOT)
        for p in found:
            print(p)
        if found:
            print("next: %s" % command("gtest-list", "--write"))
        else:
            print("ok: " + gtest_list.FILE + " is what gtest-list --write writes")
        return 1 if found else 0
    if a.command == "shrink-budget":
        shrink_budget()
        return 0
    if a.command == "status":
        return status(a.source, head)
    if a.command == "export":
        # The tests the build job runs, on the head's tree and on the series about to be written; the checkout takes the series
        # only if they are green (tools/export_gate.py). The write is not reachable from here except through the gate.
        import export_gate
        declared = declared_owners(a.own)
        export_gate.gate(a.source, head, lambda scratch: export_into(scratch, a.source, base, head, declared), ROOT)
        return 0
    return verify(a.source, base, head)


if __name__ == "__main__":
    sys.exit(entry())
