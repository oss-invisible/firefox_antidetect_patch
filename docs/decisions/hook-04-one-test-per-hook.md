# hook-04: one test per hook

**Rule.** Every hook names in its `HOOKS.json` entry a test of behaviour with a negative control, and the name goes also on the `Test:` line of the folder's `FEATURE.md`.
- A hook that depends on whether the engine is on: the same test reads the value with the engine off (stock Firefox) and on (the declared value); the two must differ, and the declared value is one no runner has. The test fails if the hook is removed or inverted.
- A hook with no condition (something removed from the build for everyone): the test proves the effect, and `HOOKS.json` proves the hook is there.
- A rebuilt hook keeps the behaviour tests it had, untouched. One test may be named by several hooks, if it would fail without each of them.
- A test that reads source text (counts markers, looks for a hook's line, asserts a Mozilla file is absent) is not a test of behaviour: `HOOKS.json` already proves the presence. Rewrite it to assert the only entry ("the only place in the tree that builds X is under our guard", which fails when Mozilla adds a second one), or delete it.

The grammar of `test` (`gtest:`, `node:`, `py:`, `wrapper:`, `cargo:`, `xpcshell:`) is in [STRUCTURE.md](../STRUCTURE.md); `check` fails when the named test does not exist. A hook with no test is debt T1, an anchor without `anchor` and `why` is T2, and a test that no round runs is T3.

**Why.** A hook is one line, so removing it by mistake in a merge looks like nothing. Only a test that fails without it makes the loss visible. A test of the text of the source keeps passing when the behaviour is gone.

**Files.** `<folder>/HOOKS.json`, `<folder>/FEATURE.md`, `tools/hooks_list.py` (grammar), `tools/hook_tests_judge.py` (every named test exists in a run's results and passed), `tools/hook_contract.py` (T1-T3).

**Don't.**
- Name a test that passes with the hook removed.
- Name a test no round runs; it is debt T3.
- Write a test that only greps the source.
