# The engine as a patch series

This repository is a Firefox engine kept as a patch series on a Mozilla tag: one folder per feature,
applied in the order of `SERIES`. The tag and the source branch are in `UPSTREAM.json`.
The series is exported from a Firefox repository (the source repository: `--source`, or the
environment variable `FIREFOX_SOURCE`) and rebuilt on the tag by `verify` and by CI. `export`
also needs `ENGINE_NODE_GATE_TREE` (a worktree of the source repository for its test gate) and
Node (`ENGINE_NODE` or the PATH).

Start from `docs/README.md`. Every rule lives in `docs/` only.

## Commands

```
python tools/engine.py status          # has the source branch moved since the last export?
python tools/engine.py apply --head <branch> [--force]   # in the source repository: the tag plus one commit per folder
python tools/engine.py export          # write the series from the source branch
python tools/engine.py verify          # rebuild the tree from the series and compare: "identical" or red
python tools/engine.py check [--against <tag>]   # the series' own rules, offline; --against also tries the backports on a tag
python tools/engine.py materialize --into <dir>  # CI: the tag, the series applied, the tree checked out
python tools/engine.py hooks-list      # rewrite every HOOKS.json from the series (export does it too)
python tools/engine.py hook-debt [--summary]     # drop resolved entries of tools/hook-debt.json; --summary counts them
python tools/engine.py shrink-budget   # lower the budgets to the lines the patches carry now
python tools/engine.py drift --to <tag>          # our patched Mozilla files that Mozilla changed up to the new tag
python tools/engine.py port --to <tag>           # every folder merged three-way onto the new tag, then the birth points
python tools/engine.py births --tree <dir>       # same as tools/births.py: birth points against tools/birth-ledger.json
python tools/births.py --tree <dir> [--skeleton | --accept-changed | --prune | --tsv out.tsv]   # birth-point scan and ledger upkeep
python tools/prebuild.py --head <branch> [--base <branch>] [--folder <folder>] [--checks 1,3] [--json out.json]   # static checks before a build (also `engine.py prebuild`)
python -m pytest -q tools/tests        # the tests of the series itself
```
