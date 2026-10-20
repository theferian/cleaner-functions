#!/usr/bin/env python3
r"""GENERAL_DOCUMENT: preserve meeting labels as RECEIVE references and as discoveries.

Place in cleaner-functions repository root, run with --check then --apply.
Never edits Excel, runs, resolved states, or prior reviews.
"""
from __future__ import annotations

import argparse
import ast
from datetime import datetime
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parent
EXTRACTOR = Path('functions/board_to_log/extractor.py')
CONTRACTS = Path('functions/board_to_log/contracts.py')
WRITERS = Path('functions/board_to_log/writers.py')
COVERAGE = Path('functions/board_to_log/coverage.py')
TEST = Path('unit_tests/test_meeting_reference_discovery.py')
VERSION = 'GENERAL_DOCUMENT_MEETING_REFERENCE_V01'

class UnsafeEdit(Exception):
    pass

def once(s, old, new, label):
    n = s.count(old)
    if n != 1:
        raise UnsafeEdit(f'{label}: expected exactly 1 source anchor, found {n}; refusing to modify files')
    return s.replace(old, new, 1)

def change_extractor(s):
    if 'def _meeting_reference_literal(' in s:
        if VERSION not in s:
            raise UnsafeEdit('Another meeting reference implementation exists; inspect before applying')
        return s
    marker = 'def _reference_candidates(items: list[dict[str, Any]], status_values: set[str]) -> list[dict[str, Any]]:'
    helper = '''# GENERAL_DOCUMENT_MEETING_REFERENCE_V01
# A short literal in a receive reference slot is evidence, not an official
# numbered letter. The full narrative classifier still handles longer prose.
def _meeting_reference_literal(value: Any) -> str | None:
    if value is None:
        return None
    import re as _re
    text = _re.sub(r"[\\s\\u200c\\u200d]+", "", str(value).strip())
    text = text.replace("ي", "ی").replace("ك", "ک")
    if text in {"صورتجلسه", "جلسه"}:
        return str(value).strip()
    return None


'''
    s = once(s, marker, helper+marker, 'meeting helper insertion')
    s = once(s,
'''    for item in items:
        if item.get("role") in {"send_date", "receive_date", "date", "status"}:
            continue
        if item.get("role") == "reference" or _looks_like_reference_candidate(''',
'''    for item in items:
        if item.get("role") in {"send_date", "receive_date", "date", "status"}:
            continue
        # A literal meeting marker below a RECEIVE date is the source's
        # actual reference text. It is not a numbered correspondence letter.
        if (item.get("side_hint") == "receive"
                and item.get("role") == "explanation"
                and _meeting_reference_literal(item.get("value")) is not None):
            candidates.append(item)
            continue
        if item.get("role") == "reference" or _looks_like_reference_candidate(''', 'candidate reference classification')
    s = once(s,
'''        if start < date_end:
            continue
        if next_date_start is not None and start >= next_date_start:''',
'''        if start < date_end:
            continue
        # Do not attach a meeting marker from a remote row to an unrelated date.
        if _meeting_reference_literal(ref.get("value")) is not None and start - date_end > 2:
            continue
        if next_date_start is not None and start >= next_date_start:''', 'meeting row-adjacency safety')
    head = '''                def add_record(
'''
    if s.count(head) != 1:
        raise UnsafeEdit('add_record: no unique nested record writer')
    start = s.index(head)
    end = s.index('                # --------------------------------------------------------------\n                # SEND events', start)
    part = s[start:end]
    part = once(part, '''                    result.records.append(LogRecord(''', '''                    meeting_literal = (
                        _meeting_reference_literal(letter_reference)
                        if side == "receive" and ref is not None else None
                    )
                    reference_kind = (
                        "MEETING_MINUTES" if meeting_literal and
                        meeting_literal.replace(" ", "").replace("‌", "") == "صورتجلسه"
                        else "MEETING" if meeting_literal else
                        "LETTER" if letter_reference is not None else None
                    )
                    # Preserve the observation for later discovery and verification.
                    if meeting_literal:
                        result.diagnostics["meeting_reference_count"] = (
                            int(result.diagnostics.get("meeting_reference_count", 0)) + 1
                        )
                        result.diagnostics.setdefault("reference_observations", []).append({
                            "kind": "MEETING_BASED_RECEIVE_REFERENCE",
                            "discovery_state": "OBSERVED_UNVERIFIED",
                            "source_sheet": sheet,
                            "document_index": doc_index,
                            "doc_name": identity.get("name") or identity.get("document_name"),
                            "revision": revision,
                            "date_source": event["address"],
                            "reference_source": ref["address"],
                            "reference_literal": meeting_literal,
                            "reference_kind": reference_kind,
                            "numbered_letter_provided": False,
                        })
                    result.records.append(LogRecord(''', 'meeting discovery insertion')
    part = once(part, '''                        letter_reference=letter_reference,
''', '''                        letter_reference=letter_reference,
                        reference_kind=reference_kind,
''', 'record field reference_kind')
    # HOLD patch creates status_note; source snapshot may not have it, both supported.
    if 'notes=status_note,' in part:
        part = once(part, '''                        notes=status_note,
''', '''                        notes=(
                            ((status_note + " ") if status_note else "") +
                            (f"Meeting-based receive reference: {meeting_literal}; numbered letter not supplied."
                             if meeting_literal else "")
                        ) or None,
''', 'notes preserve HOLD and meeting')
    else:
        part = once(part, '''                        raw_source_value=event["value"],
''', '''                        raw_source_value=event["value"],
                        notes=(
                            f"Meeting-based receive reference: {meeting_literal}; numbered letter not supplied."
                            if meeting_literal else None
                        ),
''', 'record note')
    part = once(part, '''                            "reference": letter_reference,
''', '''                            "reference": letter_reference,
                            "reference_kind": reference_kind,
                            "source_reference_literal": (ref["slot"].get("value") if ref else None),
                            "reference_discovery_state": ("OBSERVED_UNVERIFIED" if meeting_literal else None),
''', 'raw discovery fields')
    return s[:start] + part + s[end:]

def change_contracts(s):
    if '    reference_kind: str | None = None' in s:
        return s
    return once(s, '    letter_reference: Any = None\n',
                '    letter_reference: Any = None\n    reference_kind: str | None = None\n', 'LogRecord.reference_kind') if '    notes: str | None = None' in s else once(once(s, '    letter_reference: Any = None\n', '    letter_reference: Any = None\n    reference_kind: str | None = None\n', 'LogRecord.reference_kind'), '    raw_source_value: Any = None\n', '    raw_source_value: Any = None\n    notes: str | None = None\n', 'LogRecord.notes')

def change_writers(s):
    if '    "reference_kind",' not in s:
        s = once(s, '    "letter_reference",\n', '    "letter_reference",\n    "reference_kind",\n', 'Logbook column')
    if '"letter_reference", "reference_kind",' not in s:
        s = once(s, '"letter_reference", "doc_status",',
                 '"letter_reference", "reference_kind", "doc_status",', 'Excel text columns')
    return s

def change_coverage(s):
    # This keeps the existing CAPTURED_TRANSACTION classification, but makes
    # meeting-based reference discovery explicit in its source_kind and note.
    if 'meeting_reference_sources: set[tuple[str, str]]' in s:
        return s
    s = once(s,
'''    narrative_sources: set[tuple[str, str]] = set()
    for record in result.records:''',
'''    narrative_sources: set[tuple[str, str]] = set()
    meeting_reference_sources: set[tuple[str, str]] = set()
    for record in result.records:
        if (record.reference_kind in {"MEETING_MINUTES", "MEETING"}
                and record.reference_source):
            meeting_reference_sources.add((record.source_sheet, record.reference_source))''',
'coverage meeting sources')
    s = once(s,
'''                elif key in transaction_sources:
                    classification = "CAPTURED_TRANSACTION"
                    source_kind = ",".join(sorted(set(transaction_sources[key])))
                    note = None''',
'''                elif key in transaction_sources:
                    classification = "CAPTURED_TRANSACTION"
                    source_kind = ",".join(sorted(set(transaction_sources[key])))
                    if key in meeting_reference_sources:
                        source_kind += ",MEETING_BASED_RECEIVE_REFERENCE"
                        note = "Original meeting reference captured; discovery/verification pending"
                    else:
                        note = None''',
'coverage discovered reference note')
    return s

TEST_CODE = r'''from __future__ import annotations
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
'''

def run():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check', action='store_true')
    mode.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if not (ROOT / 'pipeline/project_pipeline.py').is_file():
        raise UnsafeEdit('Place installer in cleaner-functions repository root')
    planned = {}
    for rel, func in ((EXTRACTOR,change_extractor), (CONTRACTS,change_contracts),
                      (WRITERS,change_writers), (COVERAGE,change_coverage)):
        path = ROOT / rel
        if not path.is_file():
            raise UnsafeEdit(f'Required code not found: {rel}')
        old = path.read_text(encoding='utf-8')
        new = func(old)
        ast.parse(new, filename=str(rel))
        if old != new:
            planned[rel] = new
    if not (ROOT/TEST).exists():
        ast.parse(TEST_CODE, filename=str(TEST))
        planned[TEST] = TEST_CODE
    print(f'[CHECK] {len(planned)} file(s) eligible; prior runs and source workbooks unchanged')
    for p in planned:
        print('   ' + str(p))
    if args.check:
        return 0
    if not planned:
        print('[ALREADY APPLIED] No changes')
        return 0
    backup = ROOT / ('_meeting_reference_backup_' + datetime.now().strftime('%Y%m%d_%H%M%S'))
    backup.mkdir()
    changed = []
    try:
        for rel, new in planned.items():
            dest = ROOT / rel
            if dest.exists():
                bp = backup/rel
                bp.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dest, bp)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(new, encoding='utf-8')
            changed.append(rel)
    except Exception:
        for rel in changed:
            backup_file = backup/rel
            if backup_file.exists():
                shutil.copy2(backup_file, ROOT/rel)
            else:
                (ROOT/rel).unlink(missing_ok=True)
        raise
    print('[APPLIED] Meeting labels are captured as RECEIVE references and discovery observations')
    print('[BACKUP] ' + str(backup))
    print('[TEST] py -m pytest -q --ignore=payload --import-mode=importlib')
    return 0

if __name__ == '__main__':
    try:
        sys.exit(run())
    except (UnsafeEdit, SyntaxError) as exc:
        print(f'[STOP] {exc}; no code changed')
        sys.exit(2)
