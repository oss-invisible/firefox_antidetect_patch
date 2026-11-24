# port-01: one run

**Rule.** Moving to a new Mozilla tag is two commands, run with `--source <source repository>` (or `FIREFOX_SOURCE`), the source repository holding both tags:
- `python tools/engine.py drift --to <tag>` lists the Mozilla files we patch that Mozilla changed between the two tags;
- `python tools/engine.py port --to <tag>` applies the series on the old tag, then replays each folder on the new one with a three-way merge, and lists every conflict in one run. It makes the branch `port/<tag>` (`--head` names another, `--force` rebuilds it); a conflicted folder still gets its commit, with conflict markers. At the end it checks the backports against the tag ([backport-01](backport-01-upstream-code-as-is.md)) and the births ([port-03](port-03-births-ledger.md)).

Then: resolve the markers on that branch, change `mozilla_tag` in `UPSTREAM.json`, and export.

**Why.** Stopping at the first conflict makes a port a loop of one-hour rounds. One run gives the whole size of the job and the files to read before any code is written. A measured move from `FIREFOX_159_0_RELEASE` to `FIREFOX_160_0_1_RELEASE` gave 794 hunks in 339 Mozilla files: 401 intact, 341 moved clean, 39 merged and 13 in conflict (1.64%), in six folders, each with a Mozilla change within 3 lines.

**Files.** `tools/engine.py` (`drift`, `port`), `UPSTREAM.json`, [NEXT.md](../NEXT.md) (that measure).

**Don't.**
- Port by hand file by file, or stop at the first conflict.
- Skip the final checks: a hook lost in a merge, or a new network birth, is found there.
- Hand-edit the exported files on the port branch ([series-01](series-01-export-is-the-only-writer.md)).
