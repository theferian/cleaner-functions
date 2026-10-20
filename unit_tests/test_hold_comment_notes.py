from functions.board_to_log.extractor import _commented_hold_status
from functions.board_to_log.writers import LOGBOOK_COLUMNS
from functions.board_to_log.contracts import LogRecord
from cleaner_core.status_library import load_status_library


def test_hold_review_preserves_source_status():
    canonical, note, original = _commented_hold_status(
        {"value":"CM", "slot":{"value":"HOLD","address":"G221:G222"}}
    )
    assert canonical == "CM" and original == "HOLD"
    assert "HOLD" in note and "Commented" in note
    assert "notes" in LOGBOOK_COLUMNS
    r=LogRecord("EYV","r","x.xlsx","IVANAKI",1,doc_status=canonical,notes=note)
    assert r.to_dict()["notes"] == note


def test_unreviewed_hold_converts_to_cm():
    assert _commented_hold_status({"value":"HOLD","slot":{"value":"HOLD"}})[0] == "CM"
    assert _commented_hold_status({"value":"A","slot":{"value":"A"}})[1] is None


def test_status_alias_preserves_other_codes():
    lib=load_status_library()
    assert lib.canonicalize("HOLD") == "CM"
    assert lib.canonicalize("C.M") == "CM"
    assert lib.definition("N.A").meaning == "Not Approved"


def test_eyv_full_board_to_log_records_source_hold_in_notes(tmp_path):
    import csv
    from functions.board_to_log.extractor import extract_board_to_log
    from functions.board_to_log.writers import write_csv

    class EYVRun:
        profile_name = "EYV"
        run_id = "eyv_20261017T020820"
        workbook = {"name":"EYV_GENERAL_DOC_CLEANER_WORKING.xlsx"}
        def state(self):
            return {"value_overrides":{"IVANAKI!G221:G222":{"value":"CM"}}}
        def document_regions(self):
            return {"sheets":{"IVANAKI":{"regions":[{
                "record_index":1,"sheet":"IVANAKI",
                "fields":{"name":{"value":"Test engineering drawing"},"wbs":{"value":"1.5.1"}}
            }]}}}
        def card_maps(self):
            return {"sheets":{"IVANAKI":{"data_start_col":5,"cards":[{
                "record_index":1,"start_row":221,"end_row":222,
                "slots":[
                    {"address":"E221","row_offset_start":0,"row_offset_end":0,
                     "col_start":5,"col_end":5,"value":"1404/01/01"},
                    {"address":"E222","row_offset_start":1,"row_offset_end":1,
                     "col_start":5,"col_end":5,"value":"1404/ES/S/1234"},
                    {"address":"F221","row_offset_start":0,"row_offset_end":0,
                     "col_start":6,"col_end":6,"value":"1404/01/20"},
                    {"address":"F222","row_offset_start":1,"row_offset_end":1,
                     "col_start":6,"col_end":6,"value":"1404/ES/R/1234"},
                    {"address":"G221:G222","row_offset_start":0,"row_offset_end":1,
                     "col_start":7,"col_end":7,"value":"HOLD"},
                ],
            }]}}}
        def slot_schema(self):
            return {"sheets":{"IVANAKI":{
                "data_start_col":5,"block_width":3,
                "roles_by_offset":{"0":"send_date","1":"receive_date","2":"status"},
                "roles_by_slot":{"0:TOP":"send_date","0:BOTTOM":"reference",
                                 "1:TOP":"receive_date","1:BOTTOM":"reference",
                                 "2:FULL":"status"},
                "status_values":["CM","A"],
                "columns":[{"column":5,"headers":["Send (Rev Z)"]},
                           {"column":6,"headers":["Receive (Rev Z)"]},
                           {"column":7,"headers":["Status"]}],
            }}}
    result=extract_board_to_log(EYVRun())
    receives=[r for r in result.records if r.send_or_receive=="receive"]
    assert len(receives)==1
    assert receives[0].doc_status=="CM"
    assert "HOLD" in receives[0].notes
    assert receives[0].raw["original_status"]=="HOLD"
    csv_path=write_csv(result,tmp_path / "hold.csv")
    with csv_path.open(encoding="utf-8-sig",newline="") as f:
        rows=list(csv.DictReader(f))
    assert rows[-1]["notes"]==receives[0].notes
