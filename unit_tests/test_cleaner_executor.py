from pathlib import Path
from types import SimpleNamespace

from functions.cleaner.executor import build_change_plan, default_published_path


def test_change_plan_executes_unmerge_values_then_merge():
    state = {
        "value_overrides": {
            "S!B2": {"sheet": "S", "target": "B2", "action": "SET_VALUE", "value": "new"},
            "S!A1": {"sheet": "S", "target": "A1", "action": "CLEAR_CELL", "value": None},
        },
        "merge_operations": [
            {"action": "MERGE_RANGE", "sheet": "S", "target": "C1:D1"},
            {"action": "UNMERGE_RANGE", "sheet": "S", "target": "E1:F1"},
        ],
    }
    plan = build_change_plan(state)
    assert [x.kind for x in plan] == ["UNMERGE_RANGE", "CLEAR_CELL", "SET_VALUE", "MERGE_RANGE"]
    assert [x.target for x in plan] == ["E1:F1", "A1", "B2", "C1:D1"]


def test_default_published_path_preserves_workbook_extension(tmp_path):
    run = SimpleNamespace(
        workbook={"path": r"C:\\Reports\\AZD.xlsm"},
        run_dir=tmp_path,
    )
    path = default_published_path(run)
    assert path.parent == tmp_path
    assert path.name == "AZD_CLEANED_LOGBOOK.xlsm"


class _FakeCells:
    def __init__(self, cells):
        self._cells = list(cells)
        self.Count = len(self._cells)

    def Item(self, index):
        return self._cells[index - 1]

    def __call__(self, *args):
        if len(args) == 1:
            return self.Item(args[0])
        if len(args) == 2:
            return self.Item(args[0])
        raise TypeError(args)


class _FakeCell:
    def __init__(self, address, value=None, *, merge_anchor=None):
        self.Address = address
        self.Value2 = value
        self._merge_anchor = merge_anchor

    @property
    def MergeCells(self):
        return self._merge_anchor is not None

    @property
    def MergeArea(self):
        anchor = self._merge_anchor or self
        return type("MergeArea", (), {"Cells": _FakeCells([anchor])})()


class _FakeRange:
    def __init__(self, address, cells):
        self.Address = address
        self.Cells = _FakeCells(cells)


def test_logical_multi_cell_target_resolves_unique_reviewed_old_value():
    from functions.cleaner.executor import WorkbookChange, _resolve_value_anchor

    cells = [
        _FakeCell("$E$19", "meeting 04/02/22"),
        _FakeCell("$E$20", None),
        _FakeCell("$E$21", None),
        _FakeCell("$E$22", None),
    ]
    rng = _FakeRange("$E$19:$E$22", cells)
    change = WorkbookChange(
        kind="SET_VALUE",
        sheet="230KV SS",
        target="E19:E22",
        value="meeting 1404/02/22",
        expected_old_value="meeting 04/02/22",
    )

    anchor = _resolve_value_anchor(rng, change)
    assert anchor.Address == "$E$19"


def test_logical_multi_cell_target_still_refuses_ambiguous_old_value():
    import pytest
    from functions.cleaner.executor import WorkbookChange, _resolve_value_anchor

    cells = [
        _FakeCell("$E$19", "same"),
        _FakeCell("$E$20", "same"),
    ]
    rng = _FakeRange("$E$19:$E$20", cells)
    change = WorkbookChange(
        kind="SET_VALUE",
        sheet="S",
        target="E19:E20",
        value="new",
        expected_old_value="same",
    )

    with pytest.raises(RuntimeError, match="multiple physical anchors"):
        _resolve_value_anchor(rng, change)


def test_logical_multi_cell_target_resolves_one_merged_physical_anchor():
    from functions.cleaner.executor import WorkbookChange, _resolve_value_anchor

    anchor = _FakeCell("$H$11", "note 04/06/03")
    cells = [
        _FakeCell("$H$11", merge_anchor=anchor),
        _FakeCell("$H$12", merge_anchor=anchor),
    ]
    rng = _FakeRange("$H$11:$H$12", cells)
    change = WorkbookChange(
        kind="SET_VALUE",
        sheet="S",
        target="H11:H12",
        value="note 1404/06/03",
        expected_old_value="note 04/06/03",
    )

    resolved = _resolve_value_anchor(rng, change)
    assert resolved.Address == "$H$11"
