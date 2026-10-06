import json

from functions.board_to_log import build_coverage_audit, extract_board_to_log
from functions.cleaner.service import load_cleaner_run
from unit_tests.test_board_to_log import _make_run, _write


def test_coverage_audit_marks_canonical_sources_and_identity(tmp_path):
    run_dir = _make_run(tmp_path)
    run = load_cleaner_run(run_dir)
    result = extract_board_to_log(run)
    audit = build_coverage_audit(run, result)
    classes = {(x["sheet"], x["address"]): x["classification"] for x in audit["items"]}

    assert classes[("230KV SS", "A3")] == "CAPTURED_IDENTITY"
    assert classes[("230KV SS", "B3")] == "CAPTURED_IDENTITY"
    assert classes[("230KV SS", "C3")] == "CAPTURED_IDENTITY"
    assert classes[("230KV SS", "D3")] == "CAPTURED_TRANSACTION"
    assert classes[("230KV SS", "D4")] == "CAPTURED_TRANSACTION"
    assert classes[("230KV SS", "E3")] == "CAPTURED_TRANSACTION"
    assert classes[("230KV SS", "E4")] == "CAPTURED_TRANSACTION"
    assert classes[("230KV SS", "F3:F4")] == "CAPTURED_TRANSACTION"
    assert audit["summary"]["counts"]["SCANNED_NOT_RETRIEVED"] == 0


def test_coverage_audit_marks_narrative_receive_separately(tmp_path):
    run_dir = _make_run(tmp_path)
    cards = json.loads((run_dir / "card_maps.json").read_text(encoding="utf-8"))
    card = cards["sheets"]["230KV SS"]["cards"][0]
    card["slots"] = [x for x in card["slots"] if x["address"] not in {"E3", "E4"}]
    card["slots"].append({
        "address": "E3:E4", "row_offset_start": 0, "row_offset_end": 1,
        "col_start": 5, "col_end": 5, "merged": True,
        "value": "پیرو مذاکرات صورت گرفته",
    })
    _write(run_dir / "card_maps.json", cards)

    run = load_cleaner_run(run_dir)
    result = extract_board_to_log(run)
    audit = build_coverage_audit(run, result)
    item = next(x for x in audit["items"] if x["address"] == "E3:E4")
    assert item["classification"] == "CAPTURED_NARRATIVE"


def test_coverage_audit_exposes_scanned_content_not_retrieved(tmp_path):
    run_dir = _make_run(tmp_path)
    cards = json.loads((run_dir / "card_maps.json").read_text(encoding="utf-8"))
    cards["sheets"]["230KV SS"]["cards"][0]["slots"].append({
        "address": "D3:D4", "row_offset_start": 0, "row_offset_end": 1,
        "col_start": 4, "col_end": 4, "merged": True,
        "value": "Narrative explanation retained for audit",
    })
    _write(run_dir / "card_maps.json", cards)

    run = load_cleaner_run(run_dir)
    result = extract_board_to_log(run)
    audit = build_coverage_audit(run, result)
    item = next(x for x in audit["items"] if x["address"] == "D3:D4")
    assert item["classification"] == "SCANNED_NOT_RETRIEVED"


class _Fmt:
    def __init__(self):
        self.Color = None
        self.Bold = False


class _Range:
    def __init__(self):
        self.Interior = _Fmt()
        self.Font = _Fmt()
        self.Value2 = None


class _Cell(_Range):
    pass


class _Accessor:
    def __init__(self, factory):
        self.factory = factory
        self.items = {}

    def __call__(self, *key):
        if len(key) == 1:
            key = key[0]
        self.items.setdefault(key, self.factory())
        return self.items[key]


class _Worksheet:
    def __init__(self, name):
        self.Name = name
        self._ranges = {}
        self.Cells = _Accessor(_Cell)
        self.Rows = _Accessor(_Range)
        self.Columns = _Accessor(_Range)

    def Range(self, *args):
        key = tuple(id(x) if not isinstance(x, str) else x for x in args)
        self._ranges.setdefault(key, _Range())
        return self._ranges[key]

    def Delete(self):
        self._deleted = True


class _Worksheets:
    def __init__(self, names):
        self.items = [_Worksheet(x) for x in names]

    def __iter__(self):
        return iter(list(self.items))

    def __call__(self, name):
        return next(x for x in self.items if x.Name == name)

    def Add(self):
        ws = _Worksheet(f"Sheet{len(self.items)+1}")
        self.items.append(ws)
        return ws


class _Excel:
    def __init__(self):
        self.DisplayAlerts = True


class _Workbook:
    def __init__(self):
        self.Application = _Excel()
        self.Worksheets = _Worksheets(["230KV SS"])


def test_coverage_com_writer_colours_source_and_builds_legend():
    from functions.board_to_log.coverage import apply_coverage_highlights_com

    wb = _Workbook()
    audit = {
        "items": [
            {"sheet": "230KV SS", "address": "D3", "classification": "CAPTURED_TRANSACTION"},
            {"sheet": "230KV SS", "address": "E3:E4", "classification": "CAPTURED_NARRATIVE"},
        ]
    }
    summary = apply_coverage_highlights_com(wb, audit)
    assert summary["highlighted_count"] == 2
    assert summary["counts"]["CAPTURED_TRANSACTION"] == 1
    assert any(ws.Name == "Coverage_Audit" for ws in wb.Worksheets)


def test_coverage_audit_marks_merged_receive_status_narrative_as_captured(tmp_path):
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
    run = load_cleaner_run(run_dir)
    result = extract_board_to_log(run)
    audit = build_coverage_audit(run, result)
    item = next(x for x in audit["items"] if x["address"] == "E3:F4")
    assert item["classification"] == "CAPTURED_NARRATIVE"
    assert audit["summary"]["counts"]["SCANNED_NOT_RETRIEVED"] == 0
