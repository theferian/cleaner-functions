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
