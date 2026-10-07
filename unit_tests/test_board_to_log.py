import json
from pathlib import Path

from functions.cleaner.service import load_cleaner_run
from functions.board_to_log.extractor import build_issue_contexts, extract_board_to_log


def _write(path: Path, payload: dict):
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _make_run(tmp_path: Path):
    root = tmp_path
    run_dir = root / "runs" / "azd_test"
    run_dir.mkdir(parents=True)
    (root / "exceptions").mkdir()
    (root / "project_solutions").mkdir()

    _write(run_dir / "run_manifest.json", {
        "schema": "cleaner.run_manifest/0.1",
        "run_id": "azd_test",
        "profile_name": "AZD",
        "workbook": {"name": "AZD.xlsx", "path": "C:/AZD.xlsx"},
        "exception_registry": str(root / "exceptions" / "AZD.exceptions.json"),
        "project_solutions": str(root / "project_solutions" / "AZD.solutions.json"),
    })
    _write(run_dir / "resolved_state.json", {
        "schema": "cleaner.resolved_state/0.1",
        "run_id": "azd_test",
        "profile_name": "AZD",
        "workbook": {"name": "AZD.xlsx", "path": "C:/AZD.xlsx"},
        "stages": {
            "DOCUMENT_BOUNDARIES": {"status": "REVIEWED"},
            "CARD_MAP": {"status": "REVIEWED"},
            "SLOT_SCHEMA": {"status": "REVIEWED"},
        },
        "value_overrides": {
            "230KV SS!C3": {"sheet": "230KV SS", "target": "C3", "value": "1.5.1000"},
            "230KV SS!E3": {"sheet": "230KV SS", "target": "E3", "value": "1405/01/02"},
        },
    })
    _write(run_dir / "document_regions.json", {
        "schema": "cleaner.document_regions/0.1",
        "run_id": "azd_test",
        "sheets": {
            "230KV SS": {
                "regions": [{
                    "sheet": "230KV SS", "record_index": 1, "anchor_row": 3,
                    "start_row": 3, "end_row": 4,
                    "fields": {
                        "document_type": {"address": "A3", "value": "Engineering"},
                        "name": {"address": "B3", "value": "PROJECT CHART"},
                        "wbs": {"address": "C3", "value": "-"},
                    },
                }]
            }
        },
    })
    _write(run_dir / "card_maps.json", {
        "schema": "cleaner.card_map/0.1",
        "run_id": "azd_test",
        "sheets": {
            "230KV SS": {
                "data_start_col": 4, "data_end_col": 6,
                "cards": [{
                    "sheet": "230KV SS", "record_index": 1,
                    "anchor_row": 3, "start_row": 3, "end_row": 4,
                    "identifier_range": "A3:C4", "data_range": "D3:F4",
                    "data_start_col": 4, "data_end_col": 6,
                    "slots": [
                        {"address": "D3", "row_offset_start": 0, "row_offset_end": 0, "col_start": 4, "col_end": 4, "merged": False, "value": "1405/01/01"},
                        {"address": "D4", "row_offset_start": 1, "row_offset_end": 1, "col_start": 4, "col_end": 4, "merged": False, "value": "1405/ES/S/0001"},
                        {"address": "E3", "row_offset_start": 0, "row_offset_end": 0, "col_start": 5, "col_end": 5, "merged": False, "value": "140/01/02"},
                        {"address": "E4", "row_offset_start": 1, "row_offset_end": 1, "col_start": 5, "col_end": 5, "merged": False, "value": "1405/GF/R/0002"},
                        {"address": "F3:F4", "row_offset_start": 0, "row_offset_end": 1, "col_start": 6, "col_end": 6, "merged": True, "value": "A.N"},
                    ],
                }],
            }
        },
    })
    _write(run_dir / "slot_schema.json", {
        "schema": "cleaner.slot_schema/0.1",
        "run_id": "azd_test",
        "sheets": {
            "230KV SS": {
                "sheet": "230KV SS", "data_start_col": 4, "data_end_col": 6,
                "block_width": 3, "block_confidence": 1.0,
                "roles_by_offset": {"0": "send_date", "1": "receive_date", "2": "status"},
                "roles_by_slot": {"0:TOP": "send_date", "0:BOTTOM": "reference", "1:TOP": "receive_date", "1:BOTTOM": "reference", "2:FULL": "status"},
                "status_values": ["A", "A.N", "CM"],
                "columns": [
                    {"column": 4, "headers": ["Send (Rev A)"]},
                    {"column": 5, "headers": ["Receive (Rev A)"]},
                    {"column": 6, "headers": ["Status"]},
                ],
            }
        },
    })
    return run_dir


def test_board_to_log_consumes_cleaner_artifacts_and_resolved_state(tmp_path):
    run_dir = _make_run(tmp_path)
    run = load_cleaner_run(run_dir)
    result = extract_board_to_log(run)

    assert len(result.records) == 2
    send = next(x for x in result.records if x.side == "send")
    receive = next(x for x in result.records if x.side == "receive")

    assert send.revision == "A"
    assert send.document_name == "PROJECT CHART"
    assert send.document_wbs == "1.5.1000"
    assert send.letter_reference == "1405/ES/S/0001"
    assert send.date_source == "D3"

    assert receive.letter_date == "1405/01/02"
    assert receive.letter_reference == "1405/GF/R/0002"
    assert receive.doc_status == "A.N"
    assert receive.status_source == "F3:F4"


def test_board_to_log_is_not_cell_row_bound_for_document_identity(tmp_path):
    run_dir = _make_run(tmp_path)
    payload = json.loads((run_dir / "document_regions.json").read_text(encoding="utf-8"))
    region = payload["sheets"]["230KV SS"]["regions"][0]
    region["start_row"] = 27
    region["end_row"] = 28
    region["anchor_row"] = 27
    region["fields"]["name"]["address"] = "B27"
    region["fields"]["wbs"]["address"] = "C27"
    region["fields"]["wbs"]["value"] = "1.5.1000"
    _write(run_dir / "document_regions.json", payload)

    card_payload = json.loads((run_dir / "card_maps.json").read_text(encoding="utf-8"))
    card = card_payload["sheets"]["230KV SS"]["cards"][0]
    card["start_row"] = 27
    card["end_row"] = 28
    card["anchor_row"] = 27
    # Semantic extraction still works because card-relative offsets/columns drive it.
    _write(run_dir / "card_maps.json", card_payload)

    result = extract_board_to_log(load_cleaner_run(run_dir))
    assert {x.document_name for x in result.records} == {"PROJECT CHART"}
    assert {x.document_wbs for x in result.records} == {"1.5.1000"}


def test_board_to_log_preserves_multiple_transactions_per_revision(tmp_path):
    run_dir = _make_run(tmp_path)
    cards = json.loads((run_dir / "card_maps.json").read_text(encoding="utf-8"))
    card = cards["sheets"]["230KV SS"]["cards"][0]
    card["end_row"] = 6
    card["data_range"] = "D3:F6"
    card["slots"] = [
        {"address": "D3", "row_offset_start": 0, "row_offset_end": 0, "col_start": 4, "col_end": 4, "merged": False, "value": "1405/01/01"},
        {"address": "D4", "row_offset_start": 1, "row_offset_end": 1, "col_start": 4, "col_end": 4, "merged": False, "value": "1405/ES/S/0001"},
        {"address": "D5", "row_offset_start": 2, "row_offset_end": 2, "col_start": 4, "col_end": 4, "merged": False, "value": "1405/02/01"},
        {"address": "D6", "row_offset_start": 3, "row_offset_end": 3, "col_start": 4, "col_end": 4, "merged": False, "value": "1405/ES/S/0003"},
        {"address": "E3", "row_offset_start": 0, "row_offset_end": 0, "col_start": 5, "col_end": 5, "merged": False, "value": "1405/01/05"},
        {"address": "E4", "row_offset_start": 1, "row_offset_end": 1, "col_start": 5, "col_end": 5, "merged": False, "value": "1405/GF/R/0002"},
        {"address": "E5", "row_offset_start": 2, "row_offset_end": 2, "col_start": 5, "col_end": 5, "merged": False, "value": "1405/02/06"},
        {"address": "E6", "row_offset_start": 3, "row_offset_end": 3, "col_start": 5, "col_end": 5, "merged": False, "value": "1405/GF/R/0004"},
        {"address": "F3", "row_offset_start": 0, "row_offset_end": 0, "col_start": 6, "col_end": 6, "merged": False, "value": "A.N"},
        {"address": "F5", "row_offset_start": 2, "row_offset_end": 2, "col_start": 6, "col_end": 6, "merged": False, "value": "CM"},
    ]
    _write(run_dir / "card_maps.json", cards)

    regions = json.loads((run_dir / "document_regions.json").read_text(encoding="utf-8"))
    regions["sheets"]["230KV SS"]["regions"][0]["end_row"] = 6
    _write(run_dir / "document_regions.json", regions)

    result = extract_board_to_log(load_cleaner_run(run_dir))
    assert len(result.records) == 4
    sends = [x for x in result.records if x.side == "send"]
    receives = [x for x in result.records if x.side == "receive"]
    assert [x.letter_reference for x in sends] == ["1405/ES/S/0001", "1405/ES/S/0003"]
    assert [x.letter_reference for x in receives] == ["1405/GF/R/0002", "1405/GF/R/0004"]
    assert [x.doc_status for x in receives] == ["A.N", "CM"]


def test_board_to_log_treats_explanation_as_preserved_narrative_not_issue(tmp_path):
    run_dir = _make_run(tmp_path)
    cards = json.loads((run_dir / "card_maps.json").read_text(encoding="utf-8"))
    cards["sheets"]["230KV SS"]["cards"][0]["slots"].append({
        "address": "D3:D4",
        "row_offset_start": 0,
        "row_offset_end": 1,
        "col_start": 4,
        "col_end": 4,
        "merged": True,
        "value": "Narrative explanation retained for audit",
    })
    _write(run_dir / "card_maps.json", cards)

    result = extract_board_to_log(load_cleaner_run(run_dir))
    assert result.diagnostics["preserved_narrative_count"] == 1
    assert not any(x.kind == "UNMAPPED_TRANSACTION_CONTENT" for x in result.issues)


def test_board_to_log_reports_missing_reference_as_real_issue(tmp_path):
    run_dir = _make_run(tmp_path)
    cards = json.loads((run_dir / "card_maps.json").read_text(encoding="utf-8"))
    card = cards["sheets"]["230KV SS"]["cards"][0]
    card["slots"] = [slot for slot in card["slots"] if slot["address"] != "D4"]
    _write(run_dir / "card_maps.json", cards)

    result = extract_board_to_log(load_cleaner_run(run_dir))
    missing = [x for x in result.issues if x.kind == "MISSING_REFERENCE"]
    assert len(missing) == 1
    assert missing[0].address == "D3"


def test_board_to_log_summary_contains_issue_taxonomy(tmp_path):
    run_dir = _make_run(tmp_path)
    cards = json.loads((run_dir / "card_maps.json").read_text(encoding="utf-8"))
    card = cards["sheets"]["230KV SS"]["cards"][0]
    card["slots"] = [slot for slot in card["slots"] if slot["address"] != "D4"]
    _write(run_dir / "card_maps.json", cards)

    result = extract_board_to_log(load_cleaner_run(run_dir))
    summary = result.to_dict()["summary"]
    assert summary["issues_by_kind"]["MISSING_REFERENCE"] == 1
    assert summary["records_by_sheet"]["230KV SS"] == 2


def test_board_to_log_pairs_compact_numeric_hyphen_reference_from_explanation_lane(tmp_path):
    run_dir = _make_run(tmp_path)
    cards = json.loads((run_dir / "card_maps.json").read_text(encoding="utf-8"))
    card = cards["sheets"]["230KV SS"]["cards"][0]
    for slot in card["slots"]:
        if slot["address"] == "E4":
            slot["value"] = "3104-821"
    _write(run_dir / "card_maps.json", cards)

    result = extract_board_to_log(load_cleaner_run(run_dir))
    receive = next(x for x in result.records if x.side == "receive")
    assert receive.letter_reference == "3104-821"
    assert receive.reference_source == "E4"
    assert not any(
        x.kind == "MISSING_REFERENCE" and x.address == "E3"
        for x in result.issues
    )
    assert result.diagnostics["preserved_narrative_count"] == 0


def test_board_to_log_does_not_promote_narrative_below_date_to_reference(tmp_path):
    run_dir = _make_run(tmp_path)
    cards = json.loads((run_dir / "card_maps.json").read_text(encoding="utf-8"))
    card = cards["sheets"]["230KV SS"]["cards"][0]
    for slot in card["slots"]:
        if slot["address"] == "E4":
            slot["value"] = "مطابق مذاکرات جلسه مورخ 1405/01/02"
    _write(run_dir / "card_maps.json", cards)

    result = extract_board_to_log(load_cleaner_run(run_dir))
    receive = next(x for x in result.records if x.side == "receive")
    assert receive.letter_reference is None
    assert any(
        x.kind == "MISSING_REFERENCE" and x.address == "E3"
        for x in result.issues
    )
    assert result.diagnostics["preserved_narrative_count"] == 1


def test_board_to_log_issue_context_uses_cleaner_artifacts(tmp_path):
    run_dir = _make_run(tmp_path)
    cards = json.loads((run_dir / "card_maps.json").read_text(encoding="utf-8"))
    card = cards["sheets"]["230KV SS"]["cards"][0]
    # Remove the receive date so its status becomes an orphan while the rest of
    # the block remains available as context.
    card["slots"] = [slot for slot in card["slots"] if slot["address"] != "E3"]
    _write(run_dir / "card_maps.json", cards)

    run = load_cleaner_run(run_dir)
    result = extract_board_to_log(run)
    orphan = [x for x in result.issues if x.kind == "ORPHAN_STATUS"]
    assert len(orphan) == 1
    contexts = build_issue_contexts(run, result)
    context = next(x for x in contexts if x["issue"]["kind"] == "ORPHAN_STATUS")
    assert context["document_identity"]["name"] == "PROJECT CHART"
    assert context["revision"] == "A"
    assert any(slot["address"] == "F3:F4" and slot["role"] == "status" for slot in context["slots"])
    assert any(record["send_or_receive"] == "send" for record in context["records"])


def test_board_to_log_promotes_receive_narrative_with_embedded_date_and_status(tmp_path):
    run_dir = _make_run(tmp_path)
    cards = json.loads((run_dir / "card_maps.json").read_text(encoding="utf-8"))
    card = cards["sheets"]["230KV SS"]["cards"][0]
    card["slots"] = [slot for slot in card["slots"] if slot["address"] not in {"E3", "E4"}]
    card["slots"].append({
        "address": "E3:E4", "row_offset_start": 0, "row_offset_end": 1,
        "col_start": 5, "col_end": 5, "merged": True,
        "value": "مطابق مذاکرات صورت گرفته در جلسه مورخ 1405/01/02",
    })
    _write(run_dir / "card_maps.json", cards)

    result = extract_board_to_log(load_cleaner_run(run_dir))
    receives = [x for x in result.records if x.side == "receive"]
    assert len(receives) == 1
    receive = receives[0]
    assert receive.letter_date == "1405/01/02"
    assert receive.letter_reference == "مطابق مذاکرات صورت گرفته در جلسه مورخ 1405/01/02"
    assert receive.doc_status == "A.N"
    assert receive.reference_source == "E3:E4"
    assert not any(x.kind == "ORPHAN_STATUS" for x in result.issues)


def test_board_to_log_promotes_non_date_receive_narrative_with_status_losslessly(tmp_path):
    run_dir = _make_run(tmp_path)
    cards = json.loads((run_dir / "card_maps.json").read_text(encoding="utf-8"))
    card = cards["sheets"]["230KV SS"]["cards"][0]
    card["slots"] = [slot for slot in card["slots"] if slot["address"] not in {"E3", "E4"}]
    card["slots"].append({
        "address": "E3:E4", "row_offset_start": 0, "row_offset_end": 1,
        "col_start": 5, "col_end": 5, "merged": True,
        "value": "پیرو مذاکرات صورت گرفته",
    })
    _write(run_dir / "card_maps.json", cards)

    result = extract_board_to_log(load_cleaner_run(run_dir))
    receive = next(x for x in result.records if x.side == "receive")
    assert receive.letter_date == "پیرو مذاکرات صورت گرفته"
    assert receive.letter_reference == "پیرو مذاکرات صورت گرفته"
    assert receive.doc_status == "A.N"
    assert receive.transaction_mode == "narrative_receive"
    assert not any(x.kind == "ORPHAN_STATUS" for x in result.issues)


def test_board_to_log_does_not_promote_malformed_date_like_narrative(tmp_path):
    run_dir = _make_run(tmp_path)
    cards = json.loads((run_dir / "card_maps.json").read_text(encoding="utf-8"))
    card = cards["sheets"]["230KV SS"]["cards"][0]
    card["slots"] = [slot for slot in card["slots"] if slot["address"] not in {"E3", "E4"}]
    card["slots"].append({
        "address": "E3", "row_offset_start": 0, "row_offset_end": 0,
        "col_start": 5, "col_end": 5, "merged": False,
        "value": "14050/01/02",
    })
    _write(run_dir / "card_maps.json", cards)
    state = json.loads((run_dir / "resolved_state.json").read_text(encoding="utf-8"))
    state["value_overrides"].pop("230KV SS!E3", None)
    _write(run_dir / "resolved_state.json", state)

    result = extract_board_to_log(load_cleaner_run(run_dir))
    assert not any(x.side == "receive" for x in result.records)
    assert any(x.kind == "ORPHAN_STATUS" for x in result.issues)


def test_board_to_log_reclassifies_compressed_status_backed_lane_as_receive(tmp_path):
    run_dir = _make_run(tmp_path)
    cards = json.loads((run_dir / "card_maps.json").read_text(encoding="utf-8"))
    card = cards["sheets"]["230KV SS"]["cards"][0]
    # Simulate the AZD irregular two-column transaction inside a 3-column block:
    # date/reference in the nominal send column, status in the nominal receive
    # column, and no content in the ordinary status column.
    card["slots"] = [
        {"address": "D3", "row_offset_start": 0, "row_offset_end": 0, "col_start": 4, "col_end": 4, "merged": False, "value": "1405/01/01"},
        {"address": "D4", "row_offset_start": 1, "row_offset_end": 1, "col_start": 4, "col_end": 4, "merged": False, "value": "3105-821"},
        {"address": "E3:E4", "row_offset_start": 0, "row_offset_end": 1, "col_start": 5, "col_end": 5, "merged": True, "value": "A.N"},
    ]
    _write(run_dir / "card_maps.json", cards)

    result = extract_board_to_log(load_cleaner_run(run_dir))
    assert len(result.records) == 1
    record = result.records[0]
    assert record.side == "receive"
    assert record.letter_date == "1405/01/01"
    assert record.letter_reference == "3105-821"
    assert record.doc_status == "A.N"
    assert record.raw["mode"] == "compressed_receive_lane"
    assert not result.issues



def test_board_to_log_promotes_receive_narrative_merged_across_status_lane(tmp_path):
    run_dir = _make_run(tmp_path)
    cards = json.loads((run_dir / "card_maps.json").read_text(encoding="utf-8"))
    card = cards["sheets"]["230KV SS"]["cards"][0]
    card["slots"] = [slot for slot in card["slots"] if slot["address"] not in {"E3", "E4", "F3:F4"}]
    card["slots"].append({
        "address": "E3:F4", "row_offset_start": 0, "row_offset_end": 1,
        "col_start": 5, "col_end": 6, "merged": True,
        "value": "پیرو مذاکرات صورت گرفته در جلسه مورخ 1405/01/02",
    })
    _write(run_dir / "card_maps.json", cards)

    result = extract_board_to_log(load_cleaner_run(run_dir))
    receive = next(x for x in result.records if x.side == "receive")
    assert receive.letter_date == "1405/01/02"
    assert receive.letter_reference == "پیرو مذاکرات صورت گرفته در جلسه مورخ 1405/01/02"
    assert receive.doc_status is None
    assert receive.transaction_mode == "narrative_receive_merged_status"
    assert receive.reference_source == "E3:F4"
    assert not any(x.kind == "MISSING_RECEIVE_STATUS" for x in result.issues)
    assert result.diagnostics["merged_receive_status_narrative_count"] == 1


def test_board_to_log_promotes_undated_receive_narrative_merged_across_status_lane(tmp_path):
    run_dir = _make_run(tmp_path)
    cards = json.loads((run_dir / "card_maps.json").read_text(encoding="utf-8"))
    card = cards["sheets"]["230KV SS"]["cards"][0]
    card["slots"] = [slot for slot in card["slots"] if slot["address"] not in {"E3", "E4", "F3:F4"}]
    card["slots"].append({
        "address": "E3:F4", "row_offset_start": 0, "row_offset_end": 1,
        "col_start": 5, "col_end": 6, "merged": True,
        "value": "بر اساس اصلاحیه مدرک کی پلان",
    })
    _write(run_dir / "card_maps.json", cards)

    result = extract_board_to_log(load_cleaner_run(run_dir))
    receive = next(x for x in result.records if x.side == "receive")
    assert receive.letter_date == "بر اساس اصلاحیه مدرک کی پلان"
    assert receive.letter_reference == "بر اساس اصلاحیه مدرک کی پلان"
    assert receive.doc_status is None
    assert receive.transaction_mode == "narrative_receive_merged_status"
    assert not result.issues

def test_canonical_record_digest_treats_excel_integral_float_as_integer():
    from functions.board_to_log.writers import canonical_record_digest

    left = [{"source_row": 3, "source_col": 4, "doc_name": "A"}]
    right = [{"source_row": 3.0, "source_col": 4.0, "doc_name": "A"}]
    assert canonical_record_digest(left) == canonical_record_digest(right)


def test_logbook_writer_does_not_require_callable_excel_address():
    """Regression: some pywin32 Excel cells expose Address as a string property."""
    from functions.board_to_log.contracts import BoardToLogResult
    from functions.board_to_log.writers import LOGBOOK_COLUMNS, write_logbook_to_workbook_com

    class FakeCell:
        # Deliberately a string, matching the user's COM surface that raised
        # TypeError when the writer tried Address(False, False).
        Address = "$A$1"

        def __init__(self, row, col):
            self.row = row
            self.col = col

    class FakeRange:
        def __init__(self):
            self.Value2 = None

    class FakeFont:
        Bold = False

    class FakeRow:
        def __init__(self):
            self.Font = FakeFont()
            self.filtered = False

        def AutoFilter(self):
            self.filtered = True

    class FakeColumn:
        def __init__(self):
            self.NumberFormat = None
            self.ColumnWidth = 10

    class FakeColumns:
        def __init__(self):
            self._columns = {}
            self.autofit = False

        def __call__(self, idx):
            return self._columns.setdefault(idx, FakeColumn())

        def AutoFit(self):
            self.autofit = True

    class FakeRows:
        def __init__(self):
            self._rows = {}

        def __call__(self, idx):
            return self._rows.setdefault(idx, FakeRow())

    class FakeWorksheet:
        def __init__(self):
            self.Name = "Sheet1"
            self.Columns = FakeColumns()
            self.Rows = FakeRows()
            self.header_range = None

        def Cells(self, row, col):
            return FakeCell(row, col)

        def Range(self, first, last):
            # The regression is specifically that the writer passes cells
            # directly and never calls first.Address(...)/last.Address(...).
            assert isinstance(first, FakeCell)
            assert isinstance(last, FakeCell)
            self.header_range = FakeRange()
            return self.header_range

    class FakeWorksheets:
        def __init__(self):
            self.items = []

        def __iter__(self):
            return iter(self.items)

        def Add(self):
            ws = FakeWorksheet()
            self.items.append(ws)
            return ws

    class FakeExcel:
        DisplayAlerts = True

    class FakeWorkbook:
        def __init__(self):
            self.Application = FakeExcel()
            self.Worksheets = FakeWorksheets()

    wb = FakeWorkbook()
    result = BoardToLogResult(project_id="AZD", source_run_id="run", source_workbook="a.xlsx")
    summary = write_logbook_to_workbook_com(wb, result)

    ws = wb.Worksheets.items[0]
    assert summary["records_written"] == 0
    assert summary["columns_written"] == len(LOGBOOK_COLUMNS)
    assert ws.header_range.Value2 == (tuple(LOGBOOK_COLUMNS),)


def test_board_to_log_preserves_status_only_receive_without_inventing_metadata(tmp_path):
    run_dir = _make_run(tmp_path)
    cards = json.loads((run_dir / "card_maps.json").read_text(encoding="utf-8"))
    card = cards["sheets"]["230KV SS"]["cards"][0]
    # FSH-like case: SEND date/reference exists, RECEIVE cells are empty, but
    # the response-status column contains a confirmed status value.
    card["slots"] = [slot for slot in card["slots"] if slot["address"] not in {"E3", "E4"}]
    _write(run_dir / "card_maps.json", cards)

    result = extract_board_to_log(load_cleaner_run(run_dir))
    assert not result.issues
    assert result.diagnostics["status_only_receive_count"] == 1

    receives = [x for x in result.records if x.side == "receive"]
    assert len(receives) == 1
    receive = receives[0]
    assert receive.doc_status == "A.N"
    assert receive.letter_date is None
    assert receive.letter_reference is None
    assert receive.date_source is None
    assert receive.reference_source is None
    assert receive.status_source == "F3:F4"
    assert receive.transaction_mode == "status_only_receive"
