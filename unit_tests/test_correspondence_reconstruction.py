from functions.board_to_log.contracts import LogRecord
from cleaner_core.correspondence_reconstruction import reconstruct_correspondence


def rec(*, side, date, ref, status=None, block=0, idx=1, event=1,
        row=7, col=4, name="DOC", sheet="230KV SS"):
    return LogRecord(
        project_id="AZD", source_run_id="test", source_workbook="AZD.xlsx",
        source_sheet=sheet, document_index=idx, doc_name=name,
        send_or_receive=side, doc_rev="Z", event_index=event,
        letter_date=date, letter_reference=ref, doc_status=status,
        block_index=block, source_row=row, source_col=col,
        date_source=f"D{row}", reference_source=f"D{row+1}",
    )


def test_ct_pt_exact_same_received_letter_multiple_physical_cells():
    events = [
        rec(side="send", date="1404/05/07", ref="1404/ES/S/2190", block=0),
        rec(side="receive", date="1404/05/25", ref="3104-821", status="A.N", block=0, col=5),
        rec(side="send", date="1404/09/25", ref="1404/ES/S/3930", block=6, col=22),
        rec(side="receive", date="1404/05/25", ref="3104-821", status="A.N", block=6, col=23),
        rec(side="receive", date="1404/10/01", ref="7104-374", status="CM", block=7, col=25),
    ]
    r = reconstruct_correspondence(events)
    assert r.raw_count == 5
    assert len(r.events) == 4
    assert r.representations[0]["letter_reference"] == "3104-821"
    assert len(r.representations[0]["source_locations"]) == 2
    assert not r.diagnostics


def test_same_day_separate_replies_are_not_collapsed():
    events = [
        rec(side="send", date="1404/09/18", ref="OUT-1", block=0),
        rec(side="send", date="1404/11/26", ref="OUT-2", block=1),
        rec(side="receive", date="1405/02/06", ref="IN-1", status="A.N", block=0),
        rec(side="receive", date="1405/02/06", ref="IN-2", status="A.N", block=1),
    ]
    r = reconstruct_correspondence(events)
    assert len(r.events) == 4
    assert not r.representations
    assert r.overlaps
    assert r.overlaps[0]["link_status"] == "NOT_INFERRED"


def test_differing_dates_for_same_reference_not_silently_merged():
    events = [
        rec(side="receive", date="1404/05/25", ref="3104-821", status="CM"),
        rec(side="receive", date="1404/05/26", ref="3104-821", status="CM", block=1),
    ]
    r = reconstruct_correspondence(events)
    assert len(r.events) == 2
    assert r.diagnostics[0]["kind"] == "CORRESPONDENCE_REFERENCE_CONFLICT"


def test_differing_status_for_same_reference_not_silently_merged():
    events = [
        rec(side="receive", date="1404/05/25", ref="3104-821", status="CM"),
        rec(side="receive", date="1404/05/25", ref="3104-821", status="A", block=1),
    ]
    r = reconstruct_correspondence(events)
    assert len(r.events) == 2
    assert r.diagnostics[0]["kind"] == "CORRESPONDENCE_REFERENCE_CONFLICT"


def test_no_reference_never_deduplicates():
    events = [
        rec(side="receive", date="1404/05/25", ref=None, status="CM"),
        rec(side="receive", date="1404/05/25", ref=None, status="CM", block=1),
    ]
    r = reconstruct_correspondence(events)
    assert len(r.events) == 2


def test_undated_narrative_preserved():
    r = reconstruct_correspondence([
        rec(side="receive", date="پیرو مذاکرات", ref="پیرو مذاکرات", status="CM"),
    ])
    assert len(r.events) == 1
    assert not r.representations


def test_identical_reference_in_different_documents_is_separate():
    events = [
        rec(side="receive", date="1404/05/25", ref="IN-1", status="A", idx=1),
        rec(side="receive", date="1404/05/25", ref="IN-1", status="A", idx=2),
    ]
    r = reconstruct_correspondence(events)
    assert len(r.events) == 2


def test_source_slot_link_is_tentative_not_confirmed():
    events = [
        rec(side="send", date="1404/08/01", ref="OUT-1", block=0, event=1),
        rec(side="receive", date="1404/08/10", ref="IN-1", status="A", block=0, event=1),
    ]
    r = reconstruct_correspondence(events)
    assert len(r.possible_links) == 1
    assert r.possible_links[0]["confirmed"] is False


def test_foundation_drawing_latest_date_survives_reconstruction():
    events = [
        rec(side="send", date="1404/10/24", ref="1404/ES/S/4369", block=0, event=3, sheet="LINE"),
        rec(side="receive", date="1404/11/04", ref="8104-244", status="CM", block=0, event=2, sheet="LINE"),
    ]
    r = reconstruct_correspondence(events)
    assert len(r.events) == 2
    assert max(x.letter_date for x in r.events) == "1404/11/04"


def test_same_day_opposite_directions_are_flagged_for_review():
    events = [
        rec(side="send", date="1404/09/18", ref="OUT-1", block=0),
        rec(side="receive", date="1404/09/18", ref="IN-1", status="CM", block=1),
    ]
    r = reconstruct_correspondence(events)
    assert len(r.events) == 2
    assert any(x["kind"] == "SAME_DAY_DIRECTION_ORDER_UNVERIFIED" for x in r.diagnostics)


def test_three_lists_receives_reconstruction_audit_and_remains_chronological():
    from functions.engineering_control.three_lists import build_three_engineering_lists

    records = [
        rec(side="send", date="1404/05/07", ref="OUT-1", block=0, sheet="LINE"),
        rec(side="receive", date="1404/05/25", ref="IN-1", status="CM", block=0, sheet="LINE"),
        rec(side="receive", date="1404/05/25", ref="IN-1", status="CM", block=4, sheet="LINE"),
        rec(side="send", date="1404/09/25", ref="OUT-2", block=2, sheet="LINE"),
        rec(side="receive", date="1404/10/01", ref="IN-2", status="CM", block=2, sheet="LINE"),
    ]
    result = build_three_engineering_lists(records, status_date="1405/01/01")
    assert not result.not_sent
    assert not result.consultant_delay
    assert len(result.company_delay) == 1
    assert result.company_delay[0].last_action_date == "1404/10/01"
    audit = result.to_dict()["correspondence_audit"]
    assert audit and audit[0]["raw_events"] == 5
    assert audit[0]["canonical_events"] == 4
    assert audit[0]["duplicate_representation_count"] == 1

def test_audit_covers_all_transactional_documents_even_without_links():
    from functions.engineering_control.three_lists import build_three_engineering_lists

    records = [
        rec(side="send", date="1405/01/01", ref="OUT-1", idx=1),
        rec(side="receive", date="1405/01/03", ref="IN-2", status="CM", idx=2),
    ]
    inventory = [
        {"source_sheet": "230KV SS", "document_index": n,
         "doc_name": f"DOC-{n}", "doc_wbs": f"1.{n}"}
        for n in (1, 2, 3)
    ]
    result = build_three_engineering_lists(
        records, status_date="1405/01/10", document_inventory=inventory,
    )
    audit = result.to_dict()["correspondence_audit"]
    by_index = {x["document_index"]: x for x in audit}
    assert set(by_index) == {1, 2}
    assert by_index[1]["raw_events"] == 1
    assert by_index[2]["raw_events"] == 1
    assert by_index[1]["canonical_events"] == 1
    assert by_index[2]["canonical_events"] == 1
    assert by_index[1]["possible_source_slot_links"] == []
    assert by_index[2]["possible_source_slot_links"] == []
    assert by_index[1]["overlapping_submission_groups"] == []
    assert by_index[2]["overlapping_submission_groups"] == []

