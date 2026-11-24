# backport-01: upstream code as it is

**Rule.** Code Mozilla does not have yet comes as the upstream code itself, never as a rewrite of ours. There are two kinds, and each leaves when the tag has it.
- **Vendored code** (only under `third_party/rust/` and `Cargo.lock`): the upstream code, with the `.cargo-checksum.json` of the touched crates updated. The folder's `BACKPORT.json` has `upstream`, `vendored` (the revision Mozilla vendors), `commits` (ours last) and `drop_when`. `check` ties it to the revision: when Mozilla vendors another one it fails, and the port takes Mozilla's file and keeps only what upstream still lacks.
- **A Mozilla commit** (any other file): the diff of one commit of `mozilla-firefox/firefox`, in its own folder `platform/backports/<name>/`, with no logic of ours beside it. `BACKPORT.json` has `upstream`, the full `commit` sha, `bug`, `date`, `title`, `files` (for each file the stored `diff` and its `sha256`) and `drop_when`. `hooks.patch` carries the diff byte for byte, and `check` rejects an edited one.

A backport has no hook budget and no `HOOKS.json`. `port` and `check --against <tag>` fail when the tag already contains the commit (the diff applies backwards); then the folder is taken out of the series.

**Why.** Upstream code is not our logic: carrying it unchanged lets the next tag replace it cleanly, and a private rewrite would hide the day Mozilla ships the real one. The hash and the stored diff make a change to a backport visible.

**Files.** `platform/backports/<name>/BACKPORT.json`, `upstream-<sha>.diff`, `tools/engine.py` (`backport_problems`, `mozilla_backport_problems`, `backport_in_tag_problems`); [STRUCTURE.md](../STRUCTURE.md).

**Don't.**
- Put our own logic in a backport folder, or retouch its diff.
- Carry a Mozilla commit outside `platform/backports/`, or vendored code outside `third_party/rust/` and `Cargo.lock`, as category backport.
- Keep a backport after the tag has it.
