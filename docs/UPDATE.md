# Moving the series to another Firefox version

For whoever does the next move, an engineer or an LLM agent. No script does it: each conflict is a decision about what Mozilla changed and where our line belongs now. This file gives the order of work, the commands, and what each kind of break means.

`OLD` is `mozilla_tag` in `UPSTREAM.json`, `NEW` the target tag (the commands below read them as shell variables, `OLD=FIREFOX_...`). `<source>` is the source repository (`--source`, or the environment variable `FIREFOX_SOURCE`). Commands run in the root of this repository. `<R>` is the number of the engine release: the last published `firefox-<R-1>` plus one. It counts our releases, not Firefox versions.

Rules behind it: [port-01](decisions/port-01-one-run.md), [port-02](decisions/port-02-stable-retail-of-the-target.md), [port-03](decisions/port-03-births-ledger.md), [hook-02](decisions/hook-02-shape-and-contract.md), [backport-01](decisions/backport-01-upstream-code-as-is.md), [ci-01](decisions/ci-01-builds-from-main-or-latitude-branches.md). The hook forms are in [STRUCTURE.md](STRUCTURE.md).

## What can break, and what tells you

| Layer | Breaks when | You learn it from |
|---|---|---|
| Hooks (`hooks.patch`) | Mozilla changed the lines next to ours, or removed the code | `port`: the list of conflicts |
| Function wraps and our own code that calls Mozilla APIs | A renamed body (`<Name>_Mozilla`) or a Mozilla function we call changed its signature | `prebuild` (seconds), then the compile-only candidate |
| Backports of a Mozilla commit | The tag already contains the commit | `port`, and `check --against <NEW>` |
| Vendored backports (`third_party/rust/`) | Mozilla vendors another revision, or regenerated a checksum | `check` (the vendored revision is no longer in the patch), then `port` |
| Behaviour | A hook applies and compiles, but the value is now born somewhere else | The hook's own test, which has a negative control (`HOOKS.json`, rule [hook-04](decisions/hook-04-one-test-per-hook.md)) |
| Network births | Mozilla added a place that creates a request, or changed the context handling around one | `births.py`: NEW, CHANGED, MOVED, GONE |
| Values pinned to the old retail | The retail of the new version gives another value | The re-measure of step 10, and the retail parity checks of the build |

## 1. Choose the tag

Only an official stable release tag: `FIREFOX_<major>_<minor>_RELEASE` or `FIREFOX_<major>_<minor>_<patch>_RELEASE`, digits only. Never a beta (`b<k>` in the name) and never an ESR tag. The series is the retail of that version.

You need a clone of the source repository that has both tags. CI fetches the tag from `mozilla_repository` of `UPSTREAM.json`, so it must exist there. To add a tag:

```
git -C <source> fetch --depth 1 <mozilla_repository> refs/tags/$NEW:refs/tags/$NEW
```

`port` needs git 2.40 or later (`git merge-tree --write-tree --merge-base`).

## 2. Measure before changing anything

```
python tools/engine.py drift --to $NEW --source <source>
```

It prints one line per file we patch that Mozilla changed between the two tags (`changed`, `DELETED by Mozilla`, `added`), then `N of our M patched Mozilla files changed between OLD and NEW`. Only those files can conflict. It reads `tools/inventory.json`, so it does not see a Mozilla function our own code calls: step 6 does.

## 3. Port: one run, every conflict

```
python tools/engine.py port --to $NEW --source <source>
```

- It applies the series on `OLD`, then replays each folder in the order of `SERIES` on `NEW` with a three-way merge (`git merge-tree`, the old layer as the base). A conflicted folder still gets its commit, titled `<folder> (CONFLICT: <files>)`, with markers in the files, and the run goes on.
- The result is the branch `port/<NEW>` in `<source>`: one commit per folder. `--head <branch>` names it otherwise. A branch that exists is refused unless you pass `--force`, which rebuilds it (its commits are lost).
- It prints `CONFLICT <folder>: <files>` per conflict and a total: `N folders moved from OLD to NEW, N clean, N with conflicts (N files)`.
- A backport of a Mozilla commit whose change the tag already holds is printed as `FAIL <folder>: the tag NEW already contains the backport of <file> (commit <sha>): take the backport out of the series`. Take it out in step 4.
- It ends with the births of the new tag against `tools/birth-ledger.json` (step 7). Exit code 1 for a conflict, a backport already in the tag, or a red birth scan.

## 4. Resolve, on `port/<NEW>`

The branch is written without a checkout. Check it out where you can work:

```
git -C <source> worktree add <dir> port/<NEW>
```

Resolve each file listed as a conflict, `git add`, commit on the branch. A folder's own files (`<folder>/src/`) rarely conflict, because Mozilla has no file at their path; one that does is renamed on our side. Where Mozilla renamed a file we patch, the new file needs an inventory record and a `tools/layout.py` entry; `export` stops until both exist.

| What Mozilla did | What to do |
|---|---|
| Edited a line next to ours (a guard, a notice, an include, a member, a `moz.build` list) | Take Mozilla's line and put ours back as it was: a guard or notice stays the first statement of the function, an include stays in our block after Mozilla's, a `VAR += [...]` stays after the closing `]` |
| Added a line at the same spot as our registration | Keep both: ours in a block of its own after Mozilla's, separated by an empty line; in a `moz.build`, after the closing `]` of the list |
| Renamed what our line names (the host function, a member, a parameter, a type) | Follow the rename in our line and in our function, then in `HOOKS.json` if it names the field |
| Changed the expression we wrap (`wrap-expression`) | Read the new expression. Wrap it, unchanged inside our call, only if the value is still born there |
| Changed the signature of a function we wrap (`wrap-function`) | Follow it in the renamed body `<Name>_Mozilla` and in our `<Name>`, which keeps the same parameters; `prebuild` check 2 compares them |
| Changed the line that gives a default (`declared-value`) | Take Mozilla's line; put our value back on it only if that line still gives the default. A pref is declared once |
| Changed the statement an `anchor` hook follows | Read the statement named in `anchor` in `HOOKS.json`; put the hook right after it, or after what replaced it. If a guard or a wrap now says the same, use that form |
| Removed or moved the code the hook sits in | Find where the value is born now and hook there; the folder's `FEATURE.md` says why the value mattered. If nothing decides it any more, the hook goes and its test tells whether the feature still holds. A folder that owns nothing is removed by `export` |
| A vendored backport (`third_party/rust/`) | Take Mozilla's file. Keep only what upstream still lacks, as upstream code. Set `vendored` in `BACKPORT.json` to the revision Mozilla vendors now ([backport-01](decisions/backport-01-upstream-code-as-is.md)) |
| A `.cargo-checksum.json` | Regenerate, never merge: take Mozilla's file and replace, in its `files` map, the sha256 of each file of the crate we changed; leave `package` as Mozilla has it |
| A backport of a Mozilla commit the tag already has | Restore its files to the tag's (`git checkout <NEW> -- <file>`) so the branch no longer changes them, and delete its record from `tools/inventory.json`. `export` removes the folder |
| A numbered space (flag bits, enums, IDL constants) now uses a value of ours | Move our constant in our own file to a value Mozilla leaves free, and keep its test ([hook-05](decisions/hook-05-no-values-in-mozilla-numbered-spaces.md)) |

Never grow a hook to make it fit: the extra lines go into the folder's own files. Never copy Mozilla's new lines into our files: a copy stops following Mozilla, and nothing conflicts the next time. Never raise a budget.

## 5. Export and prove

In `UPSTREAM.json`, by hand: `mozilla_tag` to `NEW`, `source_branch` to the branch of step 4. Do this first: `export` takes the tag as its base and refuses a head that does not descend from it. Then:

```
python tools/engine.py export --source <source> --head port/$NEW
python tools/engine.py verify --source <source> --head port/$NEW
python tools/engine.py hook-debt
python tools/engine.py shrink-budget
python tools/engine.py check --source <source> --against $NEW
python -m pytest -q tools/tests
```

- `export` first runs, on the whole tree of the head, the Juggler node tests, the python tests of our files in the tree and `tools/tests`, and writes nothing if one is red (`tools/export_gate.py`; it needs Node, `ENGINE_NODE` if it is not on the path, and `ENGINE_NODE_GATE_TREE` set to the path of a worktree of the source repository, made there the first time, a quarter of an hour). Fix the test in the source and run it again. It then writes every folder, `SERIES`, the `HOOKS.json` files, the workflow copies and `exported_from` and `exported_tree`.
- `verify` must print `identical`.
- A hook whose text changed lost its hand fields. `check` asks for them: fill `test` (and `anchor` and `why` for an anchor) in the `HOOKS.json` of the folder, and the `Test:` line of its `FEATURE.md`. `python tools/engine.py hooks-list` rewrites every `HOOKS.json` from the `hooks.patch` files alone.
- `tools/inventory.json` records, for each Mozilla file, how many lines of ours it has, how many of Mozilla's it removes and how many hunks. `check` names each record that differs from the new `hooks.patch`: rewrite the numbers by hand.
- `hook-debt` drops the entries that are resolved and never adds one; a violation that is not in `tools/hook-debt.json` is a failure. `shrink-budget` lowers the budgets to what the patches carry. A budget above `origin/main`'s needs a row in `tools/hook-budget-raises.json`: you do not raise one in a move.
- `check --against <NEW>` also tries each backport of a Mozilla commit against the tag and fails if the tag has it. `check` reads `origin/main` for the budgets and fetches it once if it is missing.

## 6. Before any build: `prebuild`

```
python tools/prebuild.py --source <source> --head port/$NEW
```

It answers in seconds, from git objects, with no checkout and no compiler, what a failed build says an hour later. `--tag` defaults to `mozilla_tag`, so run it after step 5. One line per problem: `FAIL <where>: <what>; <how to fix>`, or `WARN <where>: cannot tell: <what>` where the text does not decide (a WARN does not change the exit code). Exit code 1 if any FAIL.

| Check | What it proves |
|---|---|
| 1 hook link | Each hook calls a function of ours that is declared, included by the host file, defined, built, with the right number of arguments and namespace |
| 2 rename | Each `<Name>_Mozilla`: the declaration is renamed, the original name is defined by us with the same parameters, no Mozilla file calls the renamed body directly |
| 3 Mozilla tokens | The Mozilla lines the series rewrites or removes are the ones the recorded forms allow |
| 6 our files | Every source of ours is compiled or shipped by a build file; no two share a name. `--tree <full checkout>` also runs that tree's build-file check |
| 7 gtest filter | Every gtest suite of ours is in the default `gtest_filter` of `release.yml` |

Checks 4, 5 and 8 (`--base`) compare the head with a branch on the same tag, the form of a rework between two exports. Across two tags they would list everything Mozilla changed, so leave `--base` out. Fix a FAIL in our own files; the hook stays one line.

## 7. Births, before the pull request

```
python tools/births.py --repo <source> --rev port/$NEW
```

(`--tree <dir>` scans a tree on disk instead.) Every place the tree creates a channel, a socket, a lookup or a speculative connection must be in `tools/birth-ledger.json` with a verdict reviewed by hand. The output lists:

| State | Meaning | What to do |
|---|---|---|
| `NEW` | A site the ledger does not have | `--skeleton` prints a ledger entry for each, verdict `review`. Read the code, decide `ok`, `hooked`, `accepted`, `dead` or `fix` with its reason, and write it into the ledger by hand |
| `CHANGED` | Same site, but its statement or its context handling changed | Read the function; if the verdict still holds, `--accept-changed` rewrites the signature of every changed entry (read each one first) |
| `MOVED` | Same statement and context in another file | Copy the verdict after reading it |
| `GONE` | A ledger entry with no site | `--prune` |
| `INVALID` | An entry that breaks the grammar, or a `hooked` verdict whose hook is gone | Fix the entry or restore the hook |

Set `tag` in the ledger to `NEW`. Exit 0 is clean, 1 is a problem, 2 means only open items (`fix`) remain. `series.yml` runs it only on pull requests and pushes to `main`, so run it now: `port` ran it on a branch that still had conflict markers.

## 8. The compile-only candidate

Push the series to a branch born from `main` and named `latitude/<name>`; only `main` and `latitude/*` branches run builds ([ci-01](decisions/ci-01-builds-from-main-or-latitude-branches.md)), and a branch not born from `main` compiles with no cache. Then:

```
gh workflow run release.yml --ref latitude/<name> -f kind=candidate -f stop_after=objects
```

Both legs (Linux and Windows x86_64) compile the objects of every directory the series touches, then stop: no link, no package, no gtest, no gate. All the errors of all the directories come out in one run, listed by file in the summary. The plan refuses `stop_after` for a release and anywhere outside `latitude/*`. Fix each error in our files; if a hook is the cause, in its form, never by adding lines to it. Push again; a newer push cancels the older run.

## 9. The core of the new version

The core is the package that declares the identity values the engine reads. It follows the engine, so the same move happens there, on a branch of its own:

- **The engine it serves.** Until its own seal exists, a port branch of the core carries a declaration file at its root naming the engine commit and the upstream version. The tests that read the engine's source use it; a test refuses the file once the seal pins that engine.
- **The seal** (`seal.json` in the core's package directory). It pairs the core with one engine build, is generated by `scripts/make_seal.py` in the release, and is copied in with `gh release download firefox-<R> -p seal.json`. Never edit it by hand. The version, the binary name and the user agent derive from it.
- **The branding** (`branding/SOURCE.json` and the archives). The core regenerates them from Mozilla's tree: `python scripts/gen_branding_archives.py --mozilla <checkout with the tag> --tag $NEW`. A test fails while `SOURCE.json` names another tag than the engine's.
- **The WebGL extension lists.** The core's tests hold the official lists per Firefox version, and `WebGLExtensionID` order (`dom/canvas/WebGLTypes.h`) that `getSupportedExtensions()` follows. Edit them by hand from a measurement of the new retail, in a page, on a real Windows machine: the set the retail reports for WebGL and WebGL2, in the engine's order.
- **The graphics device data** (`_fpforge/data/win_gfx_devices.json`): the blocklist outcome the official build gives each device, measured on the official build of the new version.
- **The language list.** The core builds the default language list per locale from `locale_service_default_accept_languages` (`intl/locale/rust/locale_service_glue/src/lib.rs`). Compare that function between the tags and update the core's table where it changed.
- **The pin in `series.yml`.** The `rebuilds` job checks out the core at a commit and runs its checks against the tree this repository materializes. Move that commit to the core commit made for the new version, by hand, before the pull request.

Run the full candidate (step 11) with `core_ref` set to that core branch and `wrapper_ref` to a wrapper ref that pins the version of the core.

## 10. Re-measure what was pinned to the old retail

The series is the retail of the new version. Each of these is a value measured once on the old retail. Measure it again on the official build of the new version, with a fresh profile and no automation, and change it only where it differs.

| What | Where | How measured |
|---|---|---|
| The retail's source: `version`, `repo`, `changeset` | `platform/release/src/browser/config/upstream_source.txt` | From Mozilla's build record of the release (`archive.mozilla.org/pub/firefox/candidates/<version>-candidates/build<N>/.../firefox-<version>.json`: `moz_source_repo`, `moz_source_stamp`). `python scripts/check_upstream_source.py --online`, run in the materialized tree and by `release.yml` before the build, refuses another version and compares the values with that record |
| The retail's rustc and PGO profile | `scripts/upstream_toolchain.py` | Derived from `upstream_source.txt` through Mozilla's own task index: nothing to type. After the build, `scripts/toolchain_parity.py` compares compilers and code-generation options with the retail's `about:buildconfig`; a difference that stays goes in `toolchain_parity_exceptions.json` with its reason |
| The retail's files a page can read | `scripts/stock_parity.py` | Downloads the complete MAR of the same version and platform and verifies it against the release's `SHA256SUMS`, then compares every file a page can load. A difference a page cannot see goes in `stock_parity_exceptions.json` with its measurement; a stale declaration fails |
| Archive names `firefox-<version>-stealth-*` | `scripts/linux_release.sh`, `scripts/make_release.sh`, and the core's version from the seal | `python scripts/check_release_naming.py` (run by `release.yml`) lists each name that is not the version of `browser/config/version_display.txt` |
| The xpcshell lock of unmodified Mozilla files | `scripts/ci/xpcshell_support.json` | `python scripts/ci/xpcshell_run.py lock --git <source> --series <this repository> --out scripts/ci/xpcshell_support.json`, from the source tree, then commit it on the source branch and export again. Its sha256 are those of the files at the new tag |
| WebGPU features and limits | `fingerprint/webgpu/adapter-declaration/FEATURE.md` (declared by the core, clamped to the real adapter by the engine) | `adapter.features` and `adapter.limits` on the retail, headed, on Windows 11; compare with the Linux answer the engine gives |
| Graphics feature statuses | `platform/declaration-gate/FEATURE.md` and the core's device data | Mozilla's `MOZ_GFX_SPOOF_*` variables on the official build, then `nsIGfxInfo.getFeatureStatus` for each live feature of `widget/GfxInfoFeatureDefs.inc` |
| First-run prefs (terms of use, data-reporting notice) | `platform/prefs/FEATURE.md`, the core's declaration, the test `tools/tests/test_first_run_is_the_cores.py` | A fresh profile on the retail: whether a modal or a notice appears, and the minimum terms-of-use version the retail reads |
| Storage quota | `fingerprint/hardware/storage-quota/FEATURE.md` (the hook sits in `EstimateOp::GetResponse`) | `navigator.storage.estimate().quota` on the retail, and whether the function the hook sits in changed |
| Canvas text hashes | `fingerprint/fonts/idwr/FEATURE.md` (the wrapper's canvas text test) | The RGBA hashes of the canvas text cases on the retail, per case |
| Speech voices | `fingerprint/media/speech-voices/FEATURE.md` (the wrapper's voices test) | `speechSynthesis.getVoices()` on the retail: names, order, the default |
| Popup position | `fingerprint/screen-window/popup-position/FEATURE.md` | `screenX` and `screenY` of a popup opened with no position, at three display scales |
| Window frame | `fingerprint/screen-window/geometry/FEATURE.md` (the frame is declared by the core) | `outerWidth - innerWidth` and the content origin of a popup and of a maximized window on the retail |
| Media decode and encode answers, WebRTC codecs, system colours | the core's data | `decodingInfo` for the codecs the core declares, and the system colour keywords, on the retail |
| `tag` of the birth ledger | `tools/birth-ledger.json` | Set by hand (step 7) |

## 11. Full candidate, merge, release

On the `latitude/<name>` branch, the whole run, with the gtests:

```
gh workflow run release.yml --ref latitude/<name> -f kind=candidate -f core_ref=<core branch> -f wrapper_ref=<wrapper ref> -f gtests=true
```

It builds both legs, runs the gtests (the default `gtest_filter` is every suite of ours), the retail parity checks of step 10 and the drive gate with the core and the wrapper you named. It publishes nothing: the gate seals the binary with a local seal named `firefox-<R>-candidate`. Every red is read; a red that depends on the binary is fixed in the engine, one that does not, where it is.

Then merge: a pull request from the series branch into `main`, with `series.yml` green (its `gate` job requires `rules`, `rebuilds` and `noreply-identity`). A push to `main` also starts a candidate with the gtests.

The release runs only from `main`, never from a tag:

```
gh workflow run release.yml --ref main -f kind=release -f release_tag=firefox-<R>
```

It builds, gates, makes `seal.json` and the draft release `firefox-<R>`. Copy that `seal.json` into the core (step 9), remove the core's engine declaration file, and release the core and the wrapper against it.

## 12. Close

- `FEATURE.md` of every folder whose hook moved or changed.
- [NEXT.md](NEXT.md) rewritten with the measure of the version after this one (the output of step 2 for it), or emptied.
- `docs/` describes only what is now: a decision that changed is rewritten in its place.
