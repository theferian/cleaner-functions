from __future__ import annotations
import csv
import json
from functions.cleaner.service import load_cleaner_run
from functions.board_to_log.extractor import extract_board_to_log
from functions.board_to_log.coverage import build_coverage_audit
from functions.board_to_log.writers import LOGBOOK_COLUMNS, write_csv
from unit_tests.test_board_to_log import _make_run, _write


def _prepare(tmp_path, meeting, *, status="A.N"):
    run_dir = _make_run(tmp_path)
    path = run_dir / "card_maps.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    card = payload["sheets"]["230KV SS"]["cards"][0]
    for slot in card["slots"]:
        if slot["address"] == "E4":
            slot["value"] = meeting
        elif slot["address"] == "F3:F4":
            slot["value"] = status
    _write(path, payload)
    return load_cleaner_run(run_dir)


def test_bfg_meeting_minutes_in_letter_reference_and_discovery(tmp_path):
    run = _prepare(tmp_path, "صورتجلسه", status="A.N")
    result = extract_board_to_log(run, project_id="BFG")
    receive = next(x for x in result.records if x.send_or_receive == "receive")
    assert receive.letter_reference == "صورتجلسه"
    assert receive.reference_source == "E4"
    assert receive.reference_kind == "MEETING_MINUTES"
    assert receive.raw["source_reference_literal"] == "صورتجلسه"
    assert receive.raw["reference_discovery_state"] == "OBSERVED_UNVERIFIED"
    assert result.diagnostics["meeting_reference_count"] == 1
    assert result.diagnostics["reference_observations"][0]["reference_source"] == "E4"
    assert not any(x.kind == "MISSING_REFERENCE" and x.address == "E3" for x in result.issues)
    coverage = build_coverage_audit(run, result)
    meeting_slot = next(x for x in coverage["items"] if x["address"] == "E4")
    assert meeting_slot["classification"] == "CAPTURED_TRANSACTION"
    assert "MEETING_BASED_RECEIVE_REFERENCE" in meeting_slot["source_kind"]
    assert "discovery" in meeting_slot["note"]
    assert "reference_kind" in LOGBOOK_COLUMNS
    csv_path = write_csv(result, tmp_path / "meeting.csv")
    with csv_path.open(encoding="utf-8-sig",newline="") as f:
        csv_row = next(x for x in csv.DictReader(f) if x["send_or_receive"] == "receive")
    assert csv_row["letter_reference"] == "صورتجلسه"
    assert csv_row["reference_kind"] == "MEETING_MINUTES"


def test_nkh_meeting_word_is_reference_not_unmapped_narrative(tmp_path):
    result = extract_board_to_log(_prepare(tmp_path, "جلسه"), project_id="NKH")
    receive = next(x for x in result.records if x.send_or_receive == "receive")
    assert receive.letter_reference == "جلسه"
    assert receive.reference_kind == "MEETING"
    assert receive.reference_source == "E4"
    assert result.diagnostics["preserved_narrative_count"] == 0


def test_merged_spelling_variant_is_preserved_verbatim(tmp_path):
    result = extract_board_to_log(_prepare(tmp_path, "صورت‌جلسه"), project_id="NKH")
    receive = next(x for x in result.records if x.send_or_receive == "receive")
    assert receive.letter_reference == "صورت‌جلسه"
    assert receive.reference_kind == "MEETING_MINUTES"


def test_long_narrative_not_promoted_into_reference(tmp_path):
    result = extract_board_to_log(_prepare(tmp_path, "مطابق مذاکرات جلسه مورخ 1405/01/02"))
    receive = next(x for x in result.records if x.send_or_receive == "receive")
    assert receive.letter_reference is None
    assert any(x.kind == "MISSING_REFERENCE" for x in result.issues)
    assert result.diagnostics.get("meeting_reference_count", 0) == 0


def test_send_side_meeting_label_does_not_become_reference(tmp_path):
    run = _prepare(tmp_path, "1405/GF/R/0002")
    path = run.run_dir / "card_maps.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    for slot in payload["sheets"]["230KV SS"]["cards"][0]["slots"]:
        if slot["address"] == "D4":
            slot["value"] = "صورتجلسه"
    _write(path, payload)
    result = extract_board_to_log(load_cleaner_run(run.run_dir))
    send = next(x for x in result.records if x.send_or_receive == "send")
    assert send.letter_reference is None
    assert any(x.kind == "MISSING_REFERENCE" and x.address == "D3" for x in result.issues)
