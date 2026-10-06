from dev.review_findings import _review_targets, _selection_address_for_item


def structure_item():
    return {
        "source": {"test_id": "DOCUMENT_STRUCTURE"},
        "location": {"sheet": "230KV SS", "target": "3:4"},
        "evidence": {
            "structure_pattern": {
                "pattern_id": "STRUCT_TEST",
                "row_count": 2,
                "transaction_start_col": 4,
                "merges": [
                    [0, 1, 2, 2],
                    [0, 1, 3, 3],
                    [0, 0, 4, 27],
                    [1, 1, 4, 26],
                ],
            },
            "representative_targets": ["3:4", "5:6", "7:8"],
            "all_targets": ["3:4", "5:6", "7:8", "9:10"],
        },
    }


def test_structure_row_target_expands_to_full_pattern_width():
    item = structure_item()
    assert _selection_address_for_item(item, "3:4") == "A3:AA4"
    assert _selection_address_for_item(item, "9:10") == "A9:AA10"


def test_normal_excel_targets_are_not_rewritten():
    item = structure_item()
    assert _selection_address_for_item(item, "C43") == "C43"
    assert _selection_address_for_item(item, "B9:X10") == "B9:X10"


def test_structure_target_uses_used_range_when_geometry_has_no_merges():
    item = structure_item()
    item["evidence"]["structure_pattern"]["merges"] = []
    assert _selection_address_for_item(item, "3:4", used_max_col=24) == "A3:X4"


def test_all_pattern_examples_are_available_in_source_order():
    item = structure_item()
    assert _review_targets(item) == ["3:4", "5:6", "7:8", "9:10"]


def test_non_pattern_item_has_single_location_target():
    item = {
        "location": {"sheet": "63KV SS", "target": "C43"},
        "evidence": {},
    }
    assert _review_targets(item) == ["C43"]

from dev.review_findings import build_parameters, reopen_item_for_edit


def test_set_value_locks_finding_target_by_default(monkeypatch):
    item = {
        "location": {"sheet": "63KV SS", "target": "H13"},
        "source": {"test_id": "FIELD_VALIDATION"},
        "evidence": {},
    }
    answers = iter(["1404/08/10"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))

    params = build_parameters("SET_VALUE", item)

    assert params == {
        "sheet": "63KV SS",
        "target": "H13",
        "value": "1404/08/10",
    }


def test_set_value_target_can_be_explicitly_unlocked(monkeypatch):
    item = {
        "location": {"sheet": "63KV SS", "target": "H13"},
        "source": {"test_id": "FIELD_VALIDATION"},
        "evidence": {},
    }
    answers = iter(["63KV SS", "H15", "1404/08/10"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))

    params = build_parameters("SET_VALUE", item, allow_target_edit=True)

    assert params["sheet"] == "63KV SS"
    assert params["target"] == "H15"
    assert params["value"] == "1404/08/10"


def test_reopen_resolved_item_for_edit_by_queue_number():
    old_decision = {
        "action": "SET_VALUE",
        "parameters": {"sheet": "63KV SS", "target": "1404/08/10", "value": "1404/08/10"},
    }
    queue = {
        "items": [
            {
                "review_id": "FIELD_VALIDATION_63KV_SS_H13_abc",
                "review_state": "RESOLVED",
                "decision": old_decision,
            }
        ]
    }

    index, item, previous = reopen_item_for_edit(queue, "1")

    assert index == 0
    assert item["review_state"] == "PENDING"
    assert "decision" not in item
    assert previous == old_decision


def test_explicit_target_edit_rejects_value_mistyped_as_cell(monkeypatch):
    item = {
        "location": {"sheet": "63KV SS", "target": "H13"},
        "source": {"test_id": "FIELD_VALIDATION"},
        "evidence": {},
    }
    # sheet, bad target (looks like a date/value), corrected target, new value
    answers = iter(["63KV SS", "1404/08/10", "H13", "1404/08/10"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))

    params = build_parameters("SET_VALUE", item, allow_target_edit=True)

    assert params["target"] == "H13"
    assert params["value"] == "1404/08/10"


def test_navigator_captures_foreground_window_for_return(monkeypatch):
    import ctypes
    from dev.review_findings import ExcelReviewNavigator

    class FakeUser32:
        def GetForegroundWindow(self):
            return 4242

    class FakeWindll:
        user32 = FakeUser32()

    monkeypatch.setattr(ctypes, "windll", FakeWindll(), raising=False)
    assert ExcelReviewNavigator._capture_foreground_window() == 4242


def test_navigator_returns_focus_to_captured_window(monkeypatch):
    import ctypes
    from dev.review_findings import ExcelReviewNavigator

    calls = []

    class FakeUser32:
        def IsWindow(self, hwnd):
            calls.append(("is_window", hwnd))
            return 1

        def BringWindowToTop(self, hwnd):
            calls.append(("bring_top", hwnd))
            return 1

        def SetForegroundWindow(self, hwnd):
            calls.append(("foreground", hwnd))
            return 1

    class FakeWindll:
        user32 = FakeUser32()

    monkeypatch.setattr(ctypes, "windll", FakeWindll(), raising=False)
    nav = object.__new__(ExcelReviewNavigator)
    nav.return_hwnd = 4242
    nav._return_focus_to_console()

    assert ("foreground", 4242) in calls
