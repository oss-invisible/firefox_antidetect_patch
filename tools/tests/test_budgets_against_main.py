"""A budget is never higher than on main: the rule, each case shown failing on its input.

problems() checks the patches against the branch's own budgets, so a branch could raise a
budget in the same commit. budget_raise_problems compares with main's budgets (read from
origin/main, never from the branch).

    python -m pytest tools/tests
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import engine  # noqa: E402

MAIN_HOOK = {"a/A.cpp": 4}
MAIN_REMOVED = {"a/A.cpp": 2}


def _found(hook, removed):
    return engine.budget_raise_problems(hook, removed, MAIN_HOOK, MAIN_REMOVED)


def test_raising_an_existing_hook_budget_fails():
    found = _found({"a/A.cpp": 5}, {"a/A.cpp": 2})
    assert len(found) == 1 and "a/A.cpp" in found[0] and "above main's 4" in found[0], found


def test_lowering_or_removing_is_fine():
    assert _found({"a/A.cpp": 3}, {"a/A.cpp": 1}) == []
    assert _found({}, {}) == []
    assert _found({"a/A.cpp": 4}, {"a/A.cpp": 2}) == []


def test_a_new_file_hook_of_5_is_fine_6_fails():
    assert _found({"a/A.cpp": 4, "b/B.cpp": 5}, {"a/A.cpp": 2}) == []
    found = _found({"a/A.cpp": 4, "b/B.cpp": 6}, {"a/A.cpp": 2})
    assert len(found) == 1 and "b/B.cpp" in found[0] and "at most 5" in found[0], found


def test_raising_an_existing_removed_budget_fails():
    found = _found({"a/A.cpp": 4}, {"a/A.cpp": 3})
    assert len(found) == 1 and "removed budget 3 is above main's 2" in found[0], found


def test_a_new_removed_entry_for_a_file_already_patched_on_main_fails():
    main_removed = {}
    found = engine.budget_raise_problems({"a/A.cpp": 4}, {"a/A.cpp": 1}, MAIN_HOOK, main_removed)
    assert len(found) == 1 and "above main's 0" in found[0], found


def test_a_brand_new_file_removes_at_most_5():
    ok = {"b/B.cpp": 5}
    assert _found({"a/A.cpp": 4, "b/B.cpp": 5}, {**ok, "a/A.cpp": 2}) == []
    found = _found({"a/A.cpp": 4, "b/B.cpp": 5}, {"b/B.cpp": 6, "a/A.cpp": 2})
    assert len(found) == 1 and "b/B.cpp" in found[0] and "at most 5" in found[0], found


def test_the_budgets_as_committed_are_not_above_main():
    main_hook, main_removed = engine.load_main_budgets()
    hook = json.loads(engine.BUDGET.read_text(encoding="utf-8"))
    removed = json.loads(engine.REMOVED_BUDGET.read_text(encoding="utf-8"))
    assert engine.budget_raise_problems(hook, removed, main_hook, main_removed) == []


# The one-time realignment of the firefox-69 line: tools/budget-realign-69.json, read from main.
ROW = {"file": "a/A.cpp", "kind": "hook", "main": 4, "line": 6, "cause": "c", "ref": "r"}
ROW_REMOVED = {"file": "a/A.cpp", "kind": "removed", "main": 2, "line": 3, "cause": "c", "ref": "r"}


def _realigned(hook, removed, rows, main_hook=None, main_removed=None):
    return engine.budget_raise_problems(hook, removed, main_hook or MAIN_HOOK,
                                        main_removed or MAIN_REMOVED, rows)


def test_a_listed_hook_raise_up_to_the_value_is_ok_one_more_fails():
    assert _realigned({"a/A.cpp": 6}, {"a/A.cpp": 2}, [ROW]) == []
    found = _realigned({"a/A.cpp": 7}, {"a/A.cpp": 2}, [ROW])
    assert len(found) == 1 and "a/A.cpp" in found[0] and "above the realigned 6" in found[0], found


def test_a_listed_removed_raise_up_to_the_value_is_ok_one_more_fails():
    assert _realigned({"a/A.cpp": 4}, {"a/A.cpp": 3}, [ROW_REMOVED]) == []
    found = _realigned({"a/A.cpp": 4}, {"a/A.cpp": 4}, [ROW_REMOVED])
    assert len(found) == 1 and "removed budget 4 is above the realigned 3" in found[0], found


def test_a_row_of_one_kind_does_not_lift_the_other():
    found = _realigned({"a/A.cpp": 5}, {"a/A.cpp": 2}, [ROW_REMOVED])
    assert len(found) == 1 and "hook budget 5 is above main's 4" in found[0], found


def test_an_unlisted_raise_fails():
    other = {"file": "b/B.cpp", "kind": "hook", "main": 1, "line": 9, "cause": "c", "ref": "r"}
    found = _realigned({"a/A.cpp": 5}, {"a/A.cpp": 2}, [other])
    assert len(found) == 1 and "a/A.cpp" in found[0] and "above main's 4" in found[0], found
    assert len(_realigned({"a/A.cpp": 5}, {"a/A.cpp": 2}, None)) == 1


def test_a_row_is_read_from_main_a_row_added_on_the_branch_does_not_count():
    # main's list has no row for a/A.cpp: the branch's list, even with the row, lifts nothing ...
    assert len(_realigned({"a/A.cpp": 6}, {"a/A.cpp": 2}, [])) == 1
    # ... and the check on the list itself refuses the added row, and a raised value
    found = engine.realign_list_problems([ROW], [])
    assert len(found) == 1 and "a/A.cpp" in found[0] and "main's list does not have" in found[0], found
    found = engine.realign_list_problems([{**ROW, "line": 7}], [ROW])
    assert len(found) == 1 and "value 7 is above main's 6" in found[0], found
    assert engine.realign_list_problems([{**ROW, "kind": "removed"}], [ROW]) != []


def test_the_list_may_shrink_and_main_without_a_list_is_the_introduction():
    assert engine.realign_list_problems([], [ROW]) == []
    assert engine.realign_list_problems([{**ROW, "line": 5}], [ROW]) == []
    assert engine.realign_list_problems([ROW], [ROW]) == []
    assert engine.realign_list_problems([ROW], None) == []


def test_a_row_is_consumed_once_main_reaches_the_value():
    # after the 69, main's budget for the file is 6: the row no longer lifts anything, 7 fails,
    # and so does 6 -> 7 even though main's list still carries the row
    main_hook = {"a/A.cpp": 6}
    assert _realigned({"a/A.cpp": 6}, {"a/A.cpp": 2}, [ROW], main_hook) == []
    found = _realigned({"a/A.cpp": 7}, {"a/A.cpp": 2}, [ROW], main_hook)
    assert len(found) == 1 and "above main's 6" in found[0], found
    main_hook = {"a/A.cpp": 7}      # main already above the row's value: main's is the limit
    assert len(_realigned({"a/A.cpp": 8}, {"a/A.cpp": 2}, [ROW], main_hook)) == 1
    main_removed = {"a/A.cpp": 3}
    found = _realigned({"a/A.cpp": 4}, {"a/A.cpp": 4}, [ROW_REMOVED], None, main_removed)
    assert len(found) == 1 and "above main's 3" in found[0], found


def test_the_realignment_list_as_committed_is_well_formed_and_matches_main():
    rows = json.loads(engine.REALIGN.read_text(encoding="utf-8"))
    assert len(rows) == 50 and len({(r["file"], r["kind"]) for r in rows}) == 50
    for r in rows:
        assert set(r) == {"file", "kind", "main", "line", "cause", "ref"} and r["kind"] in ("hook", "removed")
        assert r["line"] >= r["main"] and r["cause"] and r["ref"], r
    main_hook, main_removed = engine.load_main_budgets()
    main_rows = engine.load_main_realign()
    assert engine.realign_list_problems(rows, main_rows) == []
    hook = json.loads(engine.BUDGET.read_text(encoding="utf-8"))
    removed = json.loads(engine.REMOVED_BUDGET.read_text(encoding="utf-8"))
    assert engine.budget_raise_problems(hook, removed, main_hook, main_removed, main_rows) == []
