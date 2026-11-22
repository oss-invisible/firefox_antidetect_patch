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
    # as check judges them: main's budgets, main's realignment list, and the raises this branch declares
    main_raises = engine.load_main_raises()
    raises = json.loads(engine.RAISES.read_text(encoding="utf-8")) if engine.RAISES.is_file() else []
    assert engine.budget_raise_problems(hook, removed, main_hook, main_removed, engine.load_main_realign(),
                                        engine.new_raise_rows(raises, main_raises)) == []


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
    assert len(rows) == 51 and len({(r["file"], r["kind"]) for r in rows}) == 51
    for r in rows:
        assert set(r) == {"file", "kind", "main", "line", "cause", "ref"} and r["kind"] in ("hook", "removed")
        assert r["line"] >= r["main"] and r["cause"] and r["ref"], r
    main_hook, main_removed = engine.load_main_budgets()
    main_rows = engine.load_main_realign()
    assert engine.realign_list_problems(rows, main_rows) == []
    hook = json.loads(engine.BUDGET.read_text(encoding="utf-8"))
    removed = json.loads(engine.REMOVED_BUDGET.read_text(encoding="utf-8"))
    raises = json.loads(engine.RAISES.read_text(encoding="utf-8")) if engine.RAISES.is_file() else []
    assert engine.budget_raise_problems(hook, removed, main_hook, main_removed, main_rows,
                                        engine.new_raise_rows(raises, engine.load_main_raises())) == []


# The register of declared raises: tools/hook-budget-raises.json, read from main, only grows.
RAISE = {"file": "a/A.cpp", "from": 4, "to": 6, "folder": "f/x", "reason": "a hook that is a wanted growth",
         "decided_by": "pm", "date": "2026-11-22", "test": "wrapper:tests/test_a.py::test_b"}


def _raised(hook, branch_rows, main_rows):
    return (engine.raises_list_problems(branch_rows, main_rows)
            + engine.budget_raise_problems(hook, MAIN_REMOVED, MAIN_HOOK, MAIN_REMOVED, None,
                                           engine.new_raise_rows(branch_rows, main_rows)))


def test_a_raise_with_the_row_the_branch_adds_is_fine():
    assert _raised({"a/A.cpp": 6}, [RAISE], []) == []


def test_a_raise_without_a_row_fails():
    found = _raised({"a/A.cpp": 6}, [], [])
    assert len(found) == 1 and "above main's 4" in found[0], found


def test_a_row_whose_from_or_to_do_not_match_fails():
    for row, hook in ((dict(RAISE, **{"from": 3}), 6), (dict(RAISE, to=7), 6), (RAISE, 5), (RAISE, 7)):
        found = _raised({"a/A.cpp": hook}, [row], [])
        assert any("raises from" in p and "main's budget is 4" in p for p in found), (row, hook, found)


def test_a_row_with_an_empty_or_missing_field_or_a_bad_value_fails():
    for field in ("file", "folder", "reason", "decided_by", "date", "test"):
        found = engine.raises_list_problems([dict(RAISE, **{field: " "})], [])
        assert any("empty field" in p for p in found), (field, found)
    missing = dict(RAISE)
    del missing["test"]
    assert any("exactly the fields" in p for p in engine.raises_list_problems([missing], []))
    assert any("YYYY-MM-DD" in p for p in engine.raises_list_problems([dict(RAISE, date="22/11")], []))
    for frm, to in ((6, 6), (6, 4), ("4", 6), (4, 6.0), (-1, 2)):
        found = engine.raises_list_problems([dict(RAISE, **{"from": frm, "to": to})], [])
        assert any("two whole numbers" in p for p in found), (frm, to, found)


def test_a_row_of_main_removed_or_changed_fails():
    found = _raised({"a/A.cpp": 4}, [], [RAISE])
    assert len(found) == 1 and "gone or changed" in found[0], found
    found = _raised({"a/A.cpp": 4}, [dict(RAISE, reason="another")], [RAISE])
    assert any("gone or changed" in p for p in found), found


def test_a_row_main_already_has_opens_nothing_on_the_branch():
    # main's row was its own raise: once on main, it lifts nothing more
    found = _raised({"a/A.cpp": 6}, [RAISE], [RAISE])
    assert len(found) == 1 and "above main's 4" in found[0], found


def test_main_without_the_register_lets_no_row_open_the_door():
    found = _raised({"a/A.cpp": 6}, [RAISE], None)
    assert len(found) == 1 and "above main's 4" in found[0], found


def test_two_rows_for_one_file_a_row_for_a_file_main_does_not_patch_and_a_row_that_raises_nothing_fail():
    second = dict(RAISE, reason="again")
    assert any("two rows" in p for p in _raised({"a/A.cpp": 6}, [RAISE, second], []))
    assert any("main does not patch" in p for p in _raised({"a/A.cpp": 4, "b/B.cpp": 3}, [dict(RAISE, file="b/B.cpp", **{"from": 0, "to": 3})], []))
    assert any("raises from" in p for p in _raised({"a/A.cpp": 4}, [RAISE], []))


def test_today_s_uses_stay_green_with_the_register():
    rows = [RAISE]
    # budgets equal to or below main's, with or without a row of main
    assert _raised({"a/A.cpp": 4}, rows, rows) == [] and _raised({"a/A.cpp": 3}, [], []) == []
    # the realignment list that shrinks is judged as before
    row = {"file": "a/A.cpp", "kind": "hook", "main": 4, "line": 6, "cause": "c", "ref": "r"}
    assert engine.realign_list_problems([], [row]) == []
    assert engine.budget_raise_problems({"a/A.cpp": 6}, MAIN_REMOVED, MAIN_HOOK, MAIN_REMOVED, [row], []) == []


def test_the_register_as_committed_is_well_formed_and_only_grows_against_main():
    rows = json.loads(engine.RAISES.read_text(encoding="utf-8"))
    engine.load_main_budgets()
    assert isinstance(rows, list) and engine.raises_list_problems(rows, engine.load_main_raises()) == []
