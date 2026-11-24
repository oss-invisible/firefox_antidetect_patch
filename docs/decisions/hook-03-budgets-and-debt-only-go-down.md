# hook-03: budgets and debt only go down

**Rule.** Three files only shrink, each compared with `origin/main`, never with the branch:
- `tools/hook-budget.json`: our lines per Mozilla file. A budget above main's fails.
- `tools/removed-budget.json`: Mozilla lines removed or rewritten per file; a missing file counts 0. A value above main's fails.
- `tools/hook-debt.json`: each place that breaks the contract today. `check` refuses a violation not in the list, an entry that no longer occurs, and an entry main's list does not have.

A Mozilla file new to the series gets at most 5 hook lines and 5 removed lines. After logic moves into our files, `python tools/engine.py shrink-budget` lowers the budgets. `python tools/engine.py hook-debt` removes the entries that no longer occur and adds none (`--summary` counts them; `--init` rewrites the list from every violation of now, and the comparison with main still refuses the entries main does not have).

A budget rises above main's only when the branch adds a row to `tools/hook-budget-raises.json`: a register that only grows, one row per file and branch, with `file`, `from` (main's budget), `to`, `folder`, `reason`, `decided_by`, `date` and `test`. A row that raises nothing, or one for a file main does not patch, fails.

**Why.** A hook line is a place that can conflict at each tag, so the total only buys more risk when it grows. Fixing the ceiling per file forces the next change to move logic into our files instead of adding lines. Comparing with main stops a branch from raising its own limit.

**Files.** `tools/hook-budget.json`, `tools/removed-budget.json`, `tools/hook-debt.json`, `tools/hook-budget-raises.json`, `tools/engine.py` (`check`, `shrink-budget`, `hook-debt`), `tools/hook_contract.py`; table in [STRUCTURE.md](../STRUCTURE.md).

**Don't.**
- Raise a budget by editing it; move the logic, or declare the raise with its row.
- Add an entry to the debt list by hand.
- Remove a Mozilla line to make room: keep it and put the hook beside it ([hook-02](hook-02-shape-and-contract.md)).
