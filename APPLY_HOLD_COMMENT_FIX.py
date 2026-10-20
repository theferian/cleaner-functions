"""In-place, drift-tolerant HOLD -> Commented fix for cleaner-functions.

Run ONLY from the cleaner-functions repository root:
    py .\\APPLY_HOLD_COMMENT_FIX.py

Edits selected exact code anchors, compiles all edits before writing, and backs up
changed files. Does not edit a working Excel workbook or run decisions.
"""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import shutil
import sys
import textwrap

ROOT = Path.cwd().resolve()
EXTRACTOR = Path('functions/board_to_log/extractor.py')
CONTRACTS = Path('functions/board_to_log/contracts.py')
WRITERS = Path('functions/board_to_log/writers.py')
STATUS_LIBRARY = Path('configs/status_library.json')
TEST = Path('unit_tests/test_hold_comment_notes.py')

class UnsafeEdit(RuntimeError):
    pass


def must_replace(s, old, new, label, *, expected=1):
    found = s.count(old)
    if found != expected:
        raise UnsafeEdit(f'{label}: expected {expected} exact anchor(s), found {found}. No files changed.')
    return s.replace(old, new)


def patch_extractor(s):
    if 'from cleaner_core.status_library import load_status_library' not in s:
        s = must_replace(s,
            'from functions.cleaner.service import CleanerRun\n',
            'from functions.cleaner.service import CleanerRun\nfrom cleaner_core.status_library import load_status_library\n', 'status-library import')

    if 'def _commented_hold_status(' not in s:
        helper = '''def _commented_hold_status(status: dict[str, Any] | None) -> tuple[Any, str | None, Any]:
    """Canonical CM for HOLD, but preserve original source token in notes."""
    if status is None:
        return None, None, None
    effective = status.get("value")
    original = (status.get("slot") or {}).get("value", effective)
    if not any(normalize_status(value) == "HOLD" for value in (effective, original)):
        return effective, None, original
    canonical = "CM" if normalize_status(effective) == "HOLD" else effective
    if normalize_status(canonical) == "CM":
        note = "Source status HOLD; treated as CM (Commented)."
    else:
        note = f"Source status HOLD; reviewed as {canonical}."
    return canonical, note, original


'''
        s = must_replace(s, 'def _effective_value(', helper+'def _effective_value(', 'helper placement')

    guard = ('    if kind == "TEXT" and "status" in offset_roles and load_status_library().is_known(value):\n'
             '        return "status"\n')
    if guard not in s:
        s = must_replace(s,
            '    if kind == "TEXT" and offset_roles:\n        return "explanation"',
            guard+'    if kind == "TEXT" and offset_roles:\n        return "explanation"', 'TEXT-status mapping')

    # Limit record-writing edits to the nested add_record routine, not unrelated
    # occurrences of status.  Its contents can move as other patches are added.
    start_marker = '                def add_record('
    if s.count(start_marker) != 1:
        raise UnsafeEdit('Unable to locate unique nested add_record routine.')
    a=s.index(start_marker)
    tail_marker='                send_events = '
    b=s.find(tail_marker,a)
    if b < 0:
        raise UnsafeEdit('Unable to locate add_record boundary (send_events).')
    part=s[a:b]
    if 'status_value, status_note, source_status = _commented_hold_status(status)' not in part:
        part=must_replace(part,
            '                    result.records.append(LogRecord(',
            '                    status_value, status_note, source_status = _commented_hold_status(status)\n'
            '                    result.records.append(LogRecord(', 'record helper')
    old='doc_status=status["value"] if status else None,'
    if old in part:
        part=must_replace(part,old,'doc_status=status_value,','record status')
    elif 'doc_status=status_value,' not in part:
        raise UnsafeEdit('Record status assignment anchor missing; aborting.')
    old='"status": status["value"] if status else None,'
    if old in part:
        part=must_replace(part,old,'"status": status_value,\n'
            '                            "original_status": source_status if status_note else None,',
            'raw status')
    elif '"status": status_value,' not in part:
        raise UnsafeEdit('Raw status assignment anchor missing; aborting.')
    if 'notes=status_note,' not in part:
        part=must_replace(part,
            '                        raw_source_value=event["value"],',
            '                        raw_source_value=event["value"],\n'
            '                        notes=status_note,','record notes')
    s = s[:a] + part + s[b:]
    return s


def patch_contracts(s):
    if '    notes: str | None = None' not in s:
        s=must_replace(s,
            '    raw_source_value: Any = None\n',
            '    raw_source_value: Any = None\n    notes: str | None = None\n', 'record dataclass notes')
    return s


def patch_writers(s):
    start=s.find('LOGBOOK_COLUMNS = [')
    if start<0:
        raise UnsafeEdit('LOGBOOK_COLUMNS missing.')
    end=s.find('\n]',start)
    if end<0:
        raise UnsafeEdit('LOGBOOK_COLUMNS ending missing.')
    chunk=s[start:end]
    if '"notes"' not in chunk:
        chunk += '\n    "notes",'
    s=s[:start]+chunk+s[end:]
    old='"status_source", "raw_source_value",'
    if '"status_source", "raw_source_value", "notes",' in s:
        pass  # Already present: idempotent
    elif old in s:
        s=must_replace(s, old, '"status_source", "raw_source_value", "notes",', 'Excel text columns')
    else:
        raise UnsafeEdit('Excel text-column marker changed; aborting.')
    return s


def status_new_bytes(current):
    # Use the actual installed schema so no aliases/metadata are dropped.
    import json
    obj=json.loads(current)
    statuses=obj.get('statuses')
    if not isinstance(statuses,dict):
        raise UnsafeEdit('Invalid status library: statuses is not an object')
    cm=statuses.get('CM')
    if not isinstance(cm,dict):
        raise UnsafeEdit('CM must exist in status library before HOLD mapping.')
    hold=statuses.get('HOLD')
    if hold is not None:
        raise UnsafeEdit('HOLD is already a canonical status; inspect before aliasing.')
    for code,payload in statuses.items():
        if code!='CM' and any(str(x).strip().upper()=='HOLD' for x in (payload.get('aliases') or [])):
            raise UnsafeEdit(f'HOLD already an alias of {code}; inspect before change.')
    aliases=[str(x) for x in cm.get('aliases',[]) or []]
    if 'HOLD' not in {x.strip().upper() for x in aliases}:
        aliases.append('HOLD')
    cm['aliases']=aliases
    cm['meaning']='Commented'
    # Respect any already-defined responsibility/action_required convention.
    return json.dumps(obj,ensure_ascii=False,indent=2)+'\n'


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--check',action='store_true',help='Validate anchors and syntax without writing')
    args=parser.parse_args()
    if not (ROOT/'pipeline/project_pipeline.py').is_file():
        raise UnsafeEdit('Run from cleaner-functions ROOT; pipeline/project_pipeline.py missing.')
    planned={}
    for p,fn in [(EXTRACTOR,patch_extractor),(CONTRACTS,patch_contracts),(WRITERS,patch_writers)]:
        if not (ROOT/p).is_file():
            raise UnsafeEdit(f'Missing required file: {p}')
        original=(ROOT/p).read_text(encoding='utf-8')
        changed=fn(original)
        compile(changed,str(p),'exec')
        if changed!=original:planned[p]=changed
    import json
    p=STATUS_LIBRARY
    if not (ROOT/p).is_file():
        raise UnsafeEdit(f'Missing {p}')
    old=(ROOT/p).read_text(encoding='utf-8')
    new=status_new_bytes(old)
    if new!=old: planned[p]=new
    test_text='''from functions.board_to_log.extractor import _commented_hold_status
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
'''
    test_text += '\n\ndef test_eyv_full_board_to_log_records_source_hold_in_notes(tmp_path):\n    import csv\n    from functions.board_to_log.extractor import extract_board_to_log\n    from functions.board_to_log.writers import write_csv\n\n    class EYVRun:\n        profile_name = "EYV"\n        run_id = "eyv_20261017T020820"\n        workbook = {"name":"EYV_GENERAL_DOC_CLEANER_WORKING.xlsx"}\n        def state(self):\n            return {"value_overrides":{"IVANAKI!G221:G222":{"value":"CM"}}}\n        def document_regions(self):\n            return {"sheets":{"IVANAKI":{"regions":[{\n                "record_index":1,"sheet":"IVANAKI",\n                "fields":{"name":{"value":"Test engineering drawing"},"wbs":{"value":"1.5.1"}}\n            }]}}}\n        def card_maps(self):\n            return {"sheets":{"IVANAKI":{"data_start_col":5,"cards":[{\n                "record_index":1,"start_row":221,"end_row":222,\n                "slots":[\n                    {"address":"E221","row_offset_start":0,"row_offset_end":0,\n                     "col_start":5,"col_end":5,"value":"1404/01/01"},\n                    {"address":"E222","row_offset_start":1,"row_offset_end":1,\n                     "col_start":5,"col_end":5,"value":"1404/ES/S/1234"},\n                    {"address":"F221","row_offset_start":0,"row_offset_end":0,\n                     "col_start":6,"col_end":6,"value":"1404/01/20"},\n                    {"address":"F222","row_offset_start":1,"row_offset_end":1,\n                     "col_start":6,"col_end":6,"value":"1404/ES/R/1234"},\n                    {"address":"G221:G222","row_offset_start":0,"row_offset_end":1,\n                     "col_start":7,"col_end":7,"value":"HOLD"},\n                ],\n            }]}}}\n        def slot_schema(self):\n            return {"sheets":{"IVANAKI":{\n                "data_start_col":5,"block_width":3,\n                "roles_by_offset":{"0":"send_date","1":"receive_date","2":"status"},\n                "roles_by_slot":{"0:TOP":"send_date","0:BOTTOM":"reference",\n                                 "1:TOP":"receive_date","1:BOTTOM":"reference",\n                                 "2:FULL":"status"},\n                "status_values":["CM","A"],\n                "columns":[{"column":5,"headers":["Send (Rev Z)"]},\n                           {"column":6,"headers":["Receive (Rev Z)"]},\n                           {"column":7,"headers":["Status"]}],\n            }}}\n    result=extract_board_to_log(EYVRun())\n    receives=[r for r in result.records if r.send_or_receive=="receive"]\n    assert len(receives)==1\n    assert receives[0].doc_status=="CM"\n    assert "HOLD" in receives[0].notes\n    assert receives[0].raw["original_status"]=="HOLD"\n    csv_path=write_csv(result,tmp_path / "hold.csv")\n    with csv_path.open(encoding="utf-8-sig",newline="") as f:\n        rows=list(csv.DictReader(f))\n    assert rows[-1]["notes"]==receives[0].notes\n'
    p=TEST
    if not (ROOT/p).exists():
        compile(test_text,str(p),'exec')
        planned[p]=test_text
    if args.check:
        print(f'[CHECK] Safe; {len(planned)} file(s) would be updated.')
        for p in planned:print('  '+str(p))
        return 0
    if not planned:
        print('[ALREADY APPLIED] Nothing changed.')
        return 0
    stamp=datetime.now().strftime('%Y%m%d_%H%M%S')
    backup=ROOT/('_hold_comment_backup_'+stamp)
    backup.mkdir()
    written=[]
    try:
        for p,new in planned.items():
            target=ROOT/p
            if target.exists():
                destination=backup/p
                destination.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(target,destination)
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_text(new,encoding='utf-8')
            written.append(p)
        # Validate installed library in the repository's own implementation.
        from cleaner_core.status_library import load_status_library
        lib=load_status_library()
        if lib.canonicalize('HOLD')!='CM':
            raise UnsafeEdit('Post-install verification failed: HOLD should be CM')
        from functions.board_to_log.extractor import _commented_hold_status
        val,note,orig=_commented_hold_status({'value':'CM','slot':{'value':'HOLD'}})
        if (val,orig)!=('CM','HOLD') or not note:
            raise UnsafeEdit('Post-install verification failed: original HOLD not retained')
    except Exception:
        for p in reversed(written):
            saved=backup/p
            if saved.exists():shutil.copy2(saved,ROOT/p)
            elif (ROOT/p).exists():(ROOT/p).unlink()
        raise
    print(f'[DONE] HOLD -> CM + source HOLD notes. Modified {len(written)} files.')
    print(f'[BACKUP] {backup}')
    print('[NEXT] py -m pytest -q unit_tests tests --ignore=payload --import-mode=importlib')
    return 0


if __name__=='__main__':
    try:sys.exit(main())
    except (UnsafeEdit, ValueError) as exc:
        print(f'[STOPPED SAFELY] {exc}',file=sys.stderr)
        sys.exit(2)
