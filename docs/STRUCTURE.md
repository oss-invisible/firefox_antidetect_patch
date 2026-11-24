# Structure

Where each kind of change goes. The engine is Firefox as a patch series on a Mozilla tag (`UPSTREAM.json`): one folder per feature, applied in the order of `SERIES`.

## The layers

| Layer | What it is | Where | Registered in |
|---|---|---|---|
| Our own files | `Stealth*` code and its tests, stored byte for byte | `<folder>/src/<tree path>` | `layout.OWN_FILES` (first match wins) |
| Hooks | One-line changes to Mozilla files, each with `STEALTH-HOOK(<folder>)` on the line | `<folder>/hooks.patch` | `tools/inventory.json` (one record per Mozilla file) and `layout.FEATURES` |
| Backports | Upstream code carried until the tag has it | `platform/backports/<name>/` (a Mozilla commit); vendored code under `third_party/rust/` in the folder that needs it | `BACKPORT.json` in the folder |

A folder holds `hooks.patch`, `src/`, `MANIFEST.json`, `FEATURE.md` and `HOOKS.json`; a folder with a `BACKPORT.json` has no `HOOKS.json`. Rule: [backport-01](decisions/backport-01-upstream-code-as-is.md).

## Which folder

| The change is | Folder |
|---|---|
| What a page can observe | `fingerprint/<surface>/<name>` |
| What the automation protocol needs from Gecko | `automation/<name>` |
| Proxies, SOCKS, DNS over HTTPS | `network/<name>` |
| A service turned off at birth ([stillborn-01](decisions/stillborn-01-only-what-changes-the-installed-browser.md)) | `stillborn/<name>` |
| The build, branding, CI, repository tooling | `platform/<name>` |
| A Mozilla commit carried ahead | `platform/backports/<name>/` |
| A fix tied to one Firefox version, with its reason to expire | `port/<name>` |

The groups are the order the series is applied in (`layout.GROUP_ORDER`). A new Mozilla file we modify needs an inventory record and a `layout.FEATURES` entry; a new file of ours needs a `layout.OWN_FILES` pattern. `export` stops until both exist.

## Which rung

Take the first that gives the same result.

| Rung | What | Mozilla files touched |
|---|---|---|
| 1 | A pref Firefox already reads, a value declared by the core, a build option | none |
| 2 | Our own code | one registration line |
| 3 | A guard or a notice at the top of a function | one line |
| 4 | A wrap of a function or of an expression | one line rewritten |
| 5 | An anchor inside a function, only for a value Mozilla computes halfway | one line, with `anchor` and `why` in `HOOKS.json` |

Rules: [hook-01](decisions/hook-01-own-code-first.md), [hook-02](decisions/hook-02-shape-and-contract.md).

## Hook forms

The value of `form` in `HOOKS.json`. Any other shape is a contract violation.

| Form | Where | Looks like |
|---|---|---|
| `guard` | First statement of a function | `if (StealthX(this, aArg, &rv)) return rv;` |
| `notice` | First statement of a function | `StealthX(this, aArg);` |
| `wrap-expression` | The line where the value is born | Mozilla's expression, unchanged, inside our call: `return StealthX(<expression>);` |
| `wrap-function` | The signature line | Mozilla's `Foo` becomes `Foo_Mozilla`; our `Foo` calls it and treats the result |
| `wrap-call` | The line of a call | The called `Foo` becomes `StealthFoo`, same arguments; or one argument of ours is added |
| `declared-value` | The line that gives a default | The value on Mozilla's line is replaced |
| `registration` | Includes, build files, declarative files | `#include "StealthX.h"` in a block of ours after Mozilla's; `VAR += ["StealthX.cpp"]` after the closing `]` of a `moz.build`; one line in `.ipdl`, `.webidl`, `components.conf`, `jar.mn` |
| `member` | A Mozilla class | One declaration after an existing member, never the last in the block |
| `shadow` | Top of a function | `const auto GetX = StealthGetX;` |
| `anchor` | Right after a named Mozilla statement | `StealthX(this, &locale);` or `if (StealthX(this)) return rv;` |

The numbered rules C1-C11 are in [hook-02](decisions/hook-02-shape-and-contract.md); `tools/hook_contract.py` enforces them.

## HOOKS.json

One per folder without `BACKPORT.json`, beside `hooks.patch`, one entry per hook. `check` fails when it differs from what the series generates: a hook lost in a merge does not pass silently.

| Fields | Written by | Meaning |
|---|---|---|
| `file`, `function`, `kind`, `form`, `line`, `removed` | `export` or `hooks-list` | The Mozilla file, the host function, `add` / `rewrite` / `delete` / `file`, the form, the added line, the Mozilla line it replaces |
| `test` | Hand | The test that proves the hook (grammar below); a hook with none is debt T1 |
| `anchor`, `why` | Hand | Form `anchor` only: the Mozilla statement it follows, and why a guard or a wrap is not enough (debt T2) |
| `own_function`, `renamed`, `calls_mozilla` | Hand | Read by `prebuild`: our functions to link-check besides `Stealth*`, a renamed Mozilla body besides `*_Mozilla`, a direct call of a renamed body that is allowed |
| `exception`, `untestable`, `replaces` | Hand | A declared exception to the contract, a hook that cannot be tested, one rewritten line standing for several hooks; the first two count only together with the `pm` field |

A hook is identified by file, function, kind and normalized text. A hook whose text changes loses its hand fields and `check` asks for them again.

| `test` | Names | Checked by `check` |
|---|---|---|
| `gtest:<Suite>.<Name>` | A `TEST` or `TEST_F` under some folder's `src/` | It exists |
| `node:<path>[#<title>]` | A node test of the tree, with its title | The file exists, the title is in it |
| `py:<path>::<name>` | A python test of ours (`::invariant:<name>` and `::case:<name>` for a check that is not a function) | The file exists and defines the name |
| `wrapper:<path>::<test>` | A test of the wrapper | The format only |
| `cargo:<crate>::<test path>` | A rust test of a crate of ours | The format only |
| `xpcshell:<path>#<test>` | An xpcshell test | The file exists, the title is in it |

A test no round runs is debt T3. Rule: [hook-04](decisions/hook-04-one-test-per-hook.md).

## Budgets and debt

Rule: [hook-03](decisions/hook-03-budgets-and-debt-only-go-down.md).

| File | Counts | Moves by |
|---|---|---|
| `tools/hook-budget.json` | Our lines per Mozilla file | `shrink-budget` lowers it; a raise above `origin/main` needs a row in `tools/hook-budget-raises.json` |
| `tools/removed-budget.json` | Mozilla lines removed or rewritten per file; a missing file counts 0 | `shrink-budget` |
| `tools/hook-debt.json` | Each place that breaks the contract today, keyed by rule, folder, file, function and a hash of the text (no line number) | `hook-debt` drops resolved entries and never adds one; `--summary` counts them |
| `tools/hook-names.json` | Existing function names a hook may call without the `Stealth` prefix | Fixed; a new function is named `Stealth<What>` |
| `tools/birth-ledger.json` | Every place the tree creates a network request, with its verdict ([port-03](decisions/port-03-births-ledger.md)) | Hand, with `tools/births.py` |

## tools

| File | What it is |
|---|---|
| `tools/engine.py` | The commands: `export`, `verify`, `check`, `port` and the rest |
| `tools/layout.py` | `GROUP_ORDER`; `FEATURES`: inventory feature name to folder; `OWN_FILES`: path pattern of a file of ours to folder |
| `tools/inventory.json` | One record per Mozilla file we modify: file, category, feature, prefs, added / removed / hunk counts, anchor, notes. `check` compares the counts with `hooks.patch` |
| `tools/hook_contract.py`, `tools/hooks_list.py` | The contract and the `HOOKS.json` generator |
| `tools/prebuild.py`, `tools/births.py` | Static checks before a build; the birth-point scan |
| `tools/tests/` | The tests of the series itself |

## Who writes what

| File | Written by |
|---|---|
| `<folder>/hooks.patch`, `<folder>/src/`, `<folder>/MANIFEST.json` | `export` |
| A folder that owns nothing any more | `export` removes it |
| `SERIES` | `export` |
| `UPSTREAM.json`: `exported_from`, `exported_tree` | `export` |
| `HOOKS.json`: machine fields | `export`, `hooks-list` |
| `.github/workflows/*.yml` at the root | `export`: copies of `platform/ci/src/.github/workflows/`, except `series.yml` and `noreply-identity.yml`; `check` requires them identical |
| `<folder>/FEATURE.md` | `export` creates it once from the inventory; then by hand |
| `HOOKS.json`: hand fields | By hand |
| `<folder>/BACKPORT.json` and the upstream diff beside it | By hand |
| `UPSTREAM.json`: `mozilla_tag`, `source_branch` | By hand |
| `tools/layout.py`, `tools/inventory.json`, `tools/hook-budget-raises.json`, `tools/hook-names.json`, `tools/birth-ledger.json` | By hand |
| `tools/hook-budget.json`, `tools/removed-budget.json` | By hand, downward; `shrink-budget` |
| `tools/hook-debt.json` | `hook-debt` only |
| `.github/workflows/series.yml`, `.github/workflows/noreply-identity.yml` | By hand |
| `AGENTS.md`, `docs/` | By hand |

## Every change

1. In the source repository, on the source branch: the change, its test, the commit.
2. Here: `export`. It first runs the node tests, the tree's python tests and `tools/tests`, and writes nothing if one is red.
3. `verify`: it must say `identical`.
4. `hook-debt` drops the resolved debt; `shrink-budget` after logic moved; a Mozilla file new to the series needs its row in `tools/hook-budget.json` (at most 5 lines).
5. Fill the hand fields of the touched `HOOKS.json` (`test`; `anchor` and `why` for an anchor) and the `Test:` line of `FEATURE.md`.
6. `check`, and `python -m pytest -q tools/tests`.
7. Commit here with the same title as the source commit.
