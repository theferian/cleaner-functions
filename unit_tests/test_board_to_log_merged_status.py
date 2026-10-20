"""GENERAL_DOCUMENT: a merged status applies to each overlapping receive event.

Regression for YSK ysk_20261016T212108: E427, E461 and E473.
"""

import pytest

from functions.board_to_log.extractor import _pair_statuses, extract_board_to_log


def _slot(address, row, col, value, *, last_row=None):
    last_row = row if last_row is None else last_row
    return {
        "address": address,
        "row_offset_start": row,
        "row_offset_end": last_row,
        "col_start": col,
        "col_end": col,
        "merged": row != last_row,
        "value": value,
    }


class _Run:
    profile_name = "YSK"
    run_id = "ysk_regression"
    workbook = {"name": "YSK.xlsx"}

    def __init__(self, card, document_name):
        self.card = card
        self.document_name = document_name

    def state(self):
        return {"value_overrides": {}}

    def document_regions(self):
        return {"sheets": {"Yasookand": {"regions": [{
            "record_index": 1,
            "sheet": "Yasookand",
            "fields": {"name": {"value": self.document_name}, "wbs": {"value": "1.6.1"}},
        }]}}}

    def card_maps(self):
        return {"sheets": {"Yasookand": {"data_start_col": 4, "cards": [self.card]}}}

    def slot_schema(self):
        return {"sheets": {"Yasookand": {
            "data_start_col": 4,
            "block_width": 3,
            "roles_by_offset": {"0": "send_date", "1": "receive_date", "2": "status"},
            "roles_by_slot": {
                "0:TOP": "send_date", "0:BOTTOM": "reference",
                "1:TOP": "receive_date", "1:BOTTOM": "reference", "2:FULL": "status",
            },
            "status_values": ["A", "A.N", "CM"],
            "columns": [
                {"column": 4, "headers": ["Send (Rev Z)"]},
                {"column": 5, "headers": ["Receive (Rev Z)"]},
                {"column": 6, "headers": ["Status"]},
            ],
        }}}


@pytest.mark.parametrize("name,first_row,status,send_dates,receive_dates", [
    (
        "CCTV LAYOUT", 425, "A.N",
        ("1401/05/18", None), ("1401/05/30", "1401/06/12"),
    ),
    (
        "EQUIPMENT STEEL STRUCTURE CALCULATION", 459, "A",
        ("1401/03/18", "1400/12/04"), ("1401/04/06", "1400/12/16"),
    ),
    (
        "BUILDING STRUCTURES CALCULATION", 471, "A",
        ("1400/10/26", "1401/02/12"), ("1400/11/18", "1401/03/01"),
    ),
])
def test_ysk_four_row_merged_status_covers_both_receives(
    name, first_row, status, send_dates, receive_dates,
):
    rows = [first_row + i for i in range(4)]
    slots = [
        _slot(f"E{rows[0]}", 0, 5, receive_dates[0]),
        _slot(f"E{rows[1]}", 1, 5, "179509/28634"),
        _slot(f"E{rows[2]}", 2, 5, receive_dates[1]),
        _slot(f"E{rows[3]}", 3, 5, "179509/29719"),
        _slot(f"F{rows[0]}:F{rows[3]}", 0, 6, status, last_row=3),
    ]
    if send_dates[1] is None:
        slots.extend([
            _slot(f"D{rows[0]}:D{rows[1]}", 0, 4, send_dates[0], last_row=1),
            _slot(f"D{rows[2]}:D{rows[3]}", 2, 4, "1401/ES/S/2308", last_row=3),
        ])
    else:
        slots.extend([
            _slot(f"D{rows[0]}", 0, 4, send_dates[0]),
            _slot(f"D{rows[1]}", 1, 4, "1401/ES/S/1569"),
            _slot(f"D{rows[2]}", 2, 4, send_dates[1]),
            _slot(f"D{rows[3]}", 3, 4, "1401/ES/S/4104"),
        ])
    card = {
        "record_index": 1, "start_row": first_row, "end_row": first_row + 3,
        "slots": slots,
    }
    result = extract_board_to_log(_Run(card, name), project_id="YSK")
    receives = [record for record in result.records if record.side == "receive"]
    assert len(receives) == 2
    assert [record.doc_status for record in receives] == [status, status]
    assert [record.status_source for record in receives] == [
        f"F{rows[0]}:F{rows[3]}", f"F{rows[0]}:F{rows[3]}",
    ]
    assert not result.issues, [issue.to_dict() for issue in result.issues]


def test_status_not_reused_outside_merged_span():
    dates = [
        {"slot": _slot("E3", 0, 5, "1405/01/01")},
        {"slot": _slot("E5", 2, 5, "1405/02/01")},
        {"slot": _slot("E7", 4, 5, "1405/03/01")},
    ]
    status = {"slot": _slot("F3:F6", 0, 6, "A", last_row=3)}
    paired = _pair_statuses(dates, [status])
    assert paired == {id(dates[0]): status, id(dates[1]): status}


def test_individual_unmerged_statuses_keep_one_to_one_pairing():
    dates = [
        {"slot": _slot("E3", 0, 5, "1405/01/01")},
        {"slot": _slot("E5", 2, 5, "1405/02/01")},
    ]
    statuses = [
        {"slot": _slot("F3", 0, 6, "A")},
        {"slot": _slot("F5", 2, 6, "CM")},
    ]
    paired = _pair_statuses(dates, statuses)
    assert paired[id(dates[0])] is statuses[0]
    assert paired[id(dates[1])] is statuses[1]
