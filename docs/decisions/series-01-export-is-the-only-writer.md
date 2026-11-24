# series-01: export is the only writer

**Rule.** The series is generated from the source branch by `export` and proven identical by `verify`; CI rebuilds it the same way (`materialize`: Mozilla's tag, then the series, then the tree declared in `UPSTREAM.json`). A change to the engine is made in the source repository, on the source branch, with its test, then exported. Only these files are edited by hand here (the full table is "Who writes what" in [STRUCTURE.md](../STRUCTURE.md)):
- `FEATURE.md` after its first export, and the hand fields of `HOOKS.json` (`test`, `anchor`, `why`);
- `tools/layout.py`, `tools/inventory.json`, `tools/hook-names.json`, `tools/birth-ledger.json`;
- `tools/hook-budget.json` and `tools/removed-budget.json`, downward only; `tools/hook-budget-raises.json`;
- `UPSTREAM.json`: `mozilla_tag` and `source_branch`;
- `BACKPORT.json` with the upstream diff beside it, `AGENTS.md`, `docs/`, `tools/`, `series.yml`, `noreply-identity.yml`.

**Why.** A patch edited here and not in the source is erased by the next `export`, and the two trees then differ without anyone noticing. `verify` rebuilds the tree in a throwaway git index and compares it with the source head: "identical" is the proof that the series is the engine. The workflows at the root are copies of `platform/ci/src/.github/workflows/`, and `check` fails when a copy differs.

**Files.** `tools/engine.py` (`export`, `verify`, `materialize`, `check`), `tools/export_gate.py` (the tests `export` runs before it writes a byte), `UPSTREAM.json`, `SERIES`, [STRUCTURE.md](../STRUCTURE.md).

**Don't.**
- Edit `hooks.patch`, `src/`, `MANIFEST.json`, `SERIES`, the machine fields of `HOOKS.json` or a workflow copy by hand.
- Run `hook-debt --init` to hide a violation: the list only shrinks ([hook-03](hook-03-budgets-and-debt-only-go-down.md)).
- Commit a series that `verify` does not call identical.
