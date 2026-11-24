# docs

Read this first; open a decision only when your change touches it.

## Files

| File | What it holds |
|---|---|
| [STRUCTURE.md](STRUCTURE.md) | Where each kind of change goes: layers, hook forms, `HOOKS.json`, budgets, who writes what |
| [UPDATE.md](UPDATE.md) | Moving the series to a new Mozilla tag |
| [NEXT.md](NEXT.md) | Firefox 160.0.1 measured against the series |
| `decisions/` | One file per rule, listed below |

## Decisions

| Id | Rule |
|---|---|
| [series-01](decisions/series-01-export-is-the-only-writer.md) | The series is generated from the source branch by `export` and proven by `verify`; only the hand-edited files are changed here directly. |
| [product-01](decisions/product-01-no-value-from-the-host.md) | No value a page can read comes from the host: it is declared by the core or computed by Firefox's own code, and a host dependency is removed where Firefox reads the host. |
| [product-02](decisions/product-02-same-seed-same-bytes.md) | The same seed gives the same bytes on every machine (Windows and Linux x86_64): text, canvas, WebGL, audio, media. |
| [product-03](decisions/product-03-windows-retail-is-the-reference.md) | The reference is retail Firefox on Windows; Linux converges to Windows, never the reverse. |
| [hook-01](decisions/hook-01-own-code-first.md) | Logic lives in our own `Stealth*` files; a Mozilla file carries only hooks, and a hook comes after a pref, a declared value or a build option. |
| [hook-02](decisions/hook-02-shape-and-contract.md) | A hook is one line of a fixed form that calls our function, with `STEALTH-HOOK(<folder>)` on the line; Mozilla's lines stay as Mozilla wrote them. |
| [hook-03](decisions/hook-03-budgets-and-debt-only-go-down.md) | Per-file budgets and the hook debt only go down against `origin/main`; a new Mozilla file gets at most 5 hook lines and 5 removed. |
| [hook-04](decisions/hook-04-one-test-per-hook.md) | Every hook names in `HOOKS.json` a behaviour test with a negative control. |
| [hook-05](decisions/hook-05-no-values-in-mozilla-numbered-spaces.md) | Our constants never take a value in a Mozilla numbered space (flag bits, enums, IDL constants). |
| [backport-01](decisions/backport-01-upstream-code-as-is.md) | Code Mozilla does not have yet comes as the upstream code or Mozilla commit, byte for byte, with `BACKPORT.json`, and leaves when the tag contains it. |
| [port-01](decisions/port-01-one-run.md) | Moving to a new tag is `drift --to` and `port --to`: one three-way merge per folder, every conflict listed in one run. |
| [port-02](decisions/port-02-stable-retail-of-the-target.md) | The series moves only to an official stable release tag and is the retail of that version; values pinned to the old retail are measured again. |
| [port-03](decisions/port-03-births-ledger.md) | Every point where the tree creates a network request is in `tools/birth-ledger.json` with a verdict reviewed by hand. |
| [prefs-01](decisions/prefs-01-every-spoof-through-a-pref.md) | Every spoof goes through a `zoom.stealth.*` / `stealthfox.*` pref; the names are the contract with the core and are never renamed. |
| [stillborn-01](decisions/stillborn-01-only-what-changes-the-installed-browser.md) | `stillborn/` turns off at birth only what would change the installed browser; the requests a real Firefox makes stay. |
| [repo-01](decisions/repo-01-noreply-identity.md) | Commits use the noreply identity, enforced by `noreply-identity.yml`. |
| [repo-02](decisions/repo-02-no-studied-system-names.md) | No name of a studied detection system, fingerprinting service, test site or competing browser anywhere in the repository; describe the check instead. |
| [ci-01](decisions/ci-01-builds-from-main-or-latitude-branches.md) | Engine builds run only on `main` or a `latitude/<name>` branch born from `main`; a release runs only from `main`. |
