"""Targeted, reversible chronology fix for Cleaner engineering lists.

Run from cleaner-functions repository root. Validates all anchors before writing.
Does not touch project exceptions/solutions or original workbooks.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil
import sys

ROOT = Path.cwd()
ENGINE = ROOT / 'functions' / 'engineering_control' / 'three_lists.py'
TESTS = ROOT / 'unit_tests' / 'test_engineering_three_lists.py'
TASKS = ROOT / 'docs' / 'DEMO_TASK_LIST.md'

HELPER = '''def _order_events_chronologically(
    doc_records: list[LogRecord], *, status_date: str
) -> tuple[list[LogRecord], list[dict[str, Any]]]:
    """Order *dated* transactions by Jalali day, not revision/slot position.

    Source sequence is only a tie-breaker for equal dates. An undated event
    cannot safely be assigned a calendar position: preserve it as potentially
    latest when its source sequence follows the latest dated event, and emit
    a diagnostic whenever an undated event makes chronology uncertain.

    Future-dated records are retained as evidence but excluded from the state
    as of status_date; the caller must not mistake that for no history.
    """
    dated: list[LogRecord] = []
    undated: list[LogRecord] = []
    future: list[LogRecord] = []
    diagnostics: list[dict[str, Any]] = []
    as_of = _jalali_parts(status_date)
    for event in doc_records:
        date = _jalali_parts(event.letter_date)
        if date is None:
            undated.append(event)
        elif as_of is not None and date > as_of:
            future.append(event)
        else:
            dated.append(event)

    # Lexicographic YYYY/MM/DD components are chronological Jalali dates.
    dated.sort(key=lambda x: (_jalali_parts(x.letter_date), _sequence_key(x)))
    undated.sort(key=_sequence_key)

    if future:
        diagnostics.append({
            "kind": "FUTURE_DATED_EVENT_EXCLUDED",
            "count": len(future),
            "events": [
                {"date": str(x.letter_date), "side": x.send_or_receive,
                 "revision": x.doc_rev, "block_index": x.block_index,
                 "event_index": x.event_index}
                for x in future
            ],
        })

    # Logbook source/revision order may disagree with dated event order.
    by_source = sorted(dated, key=_sequence_key)
    inverted_pairs = [
        (left, right)
        for left, right in zip(by_source, by_source[1:])
        if _jalali_parts(left.letter_date) > _jalali_parts(right.letter_date)
    ]
    if inverted_pairs:
        diagnostics.append({
            "kind": "SOURCE_SEQUENCE_DATE_INVERSION",
            "count": len(inverted_pairs),
            "examples": [
                {"earlier_source_date": str(left.letter_date),
                 "later_source_date": str(right.letter_date),
                 "earlier_source_side": left.send_or_receive,
                 "later_source_side": right.send_or_receive}
                for left, right in inverted_pairs[:5]
            ],
        })

    # A RECEIVE before its paired SEND is an evidence problem, not an
    # ordinary response-time interval. Preserve both events and flag it.
    transaction_pairs: dict[tuple[int, int], dict[str, list[LogRecord]]] = {}
    for event in dated:
        pair_key = (int(event.block_index if event.block_index is not None else -1),
                    int(event.event_index or 0))
        transaction_pairs.setdefault(pair_key, {}).setdefault(event.send_or_receive, []).append(event)
    contradictions = []
    for pair_key, parts in transaction_pairs.items():
        for send in parts.get("send", []):
            for receive in parts.get("receive", []):
                if _jalali_parts(receive.letter_date) < _jalali_parts(send.letter_date):
                    contradictions.append({
                        "block_index": pair_key[0], "event_index": pair_key[1],
                        "send_date": str(send.letter_date),
                        "receive_date": str(receive.letter_date),
                    })
    if contradictions:
        diagnostics.append({
            "kind": "RECEIVE_BEFORE_MATCHED_SEND",
            "count": len(contradictions),
            "examples": contradictions[:5],
        })

    if not dated:
        # With no usable dates, preserve original semantic source order and
        # let the existing NEEDS_DATE behavior handle the current state.
        if undated:
            diagnostics.append({"kind": "ALL_EVENTS_UNDATED", "count": len(undated)})
        return undated, diagnostics

    latest_dated = dated[-1]
    earlier_undated = [x for x in undated if _sequence_key(x) <= _sequence_key(latest_dated)]
    later_undated = [x for x in undated if _sequence_key(x) > _sequence_key(latest_dated)]
    if undated:
        diagnostics.append({
            "kind": "UNRESOLVED_UNDATED_EVENT_ORDER",
            "count": len(undated),
            "potentially_latest": len(later_undated),
            "latest_dated_event": str(latest_dated.letter_date),
        })

    return earlier_undated + dated + later_undated, diagnostics


'''

TEST_APPEND = '''

def test_azd_line_foundation_drawing_uses_latest_actual_date():
    """AZD LINE / FOUNDATION DRAWING: receive 11/04 beats send 10/24."""
    records = [
        rec(side="send", rev="Z", date="1404/09/12", block=0, event=1, sheet="LINE", name="FOUNDATION DRAWING"),
        rec(side="receive", rev="Z", date="1404/09/20", status="A.N", block=0, event=1, sheet="LINE", name="FOUNDATION DRAWING"),
        rec(side="send", rev="Z", date="1404/09/18", block=0, event=2, sheet="LINE", name="FOUNDATION DRAWING"),
        rec(side="receive", rev="Z", date="1404/11/04", status="CM", block=0, event=2, sheet="LINE", name="FOUNDATION DRAWING"),
        rec(side="send", rev="Z", date="1404/10/24", block=0, event=3, sheet="LINE", name="FOUNDATION DRAWING"),
    ]
    inv = [{"source_sheet": "LINE", "document_index": 1,
            "doc_name": "FOUNDATION DRAWING", "doc_wbs": "1.6.1.1.3"}]
    result = build_three_engineering_lists(records, status_date="1405/07/22", document_inventory=inv)
    assert not result.not_sent
    assert not result.consultant_delay
    assert len(result.company_delay) == 1
    item = result.company_delay[0]
    assert item.status == "CM"
    assert item.last_action_date == "1404/11/04"
    assert any(x["kind"] == "SOURCE_SEQUENCE_DATE_INVERSION" for x in result.diagnostics)


def test_temporal_order_outweighs_revision_index():
    records = [
        rec(side="receive", date="1405/01/20", status="CM", block=0, event=1),
        rec(side="send", date="1405/01/10", block=2, event=1),
    ]
    result = build_three_engineering_lists(records, status_date="1405/01/30", document_inventory=[inventory(1)])
    assert len(result.company_delay) == 1
    assert not result.consultant_delay
    assert result.company_delay[0].last_action_date == "1405/01/20"


def test_undated_later_narrative_remains_visible_without_invented_date():
    records = [
        rec(side="send", date="1405/01/01", block=0),
        rec(side="receive", date="پیرو مذاکرات", status="CM", block=1),
    ]
    result = build_three_engineering_lists(records, status_date="1405/01/30", document_inventory=[inventory(1)])
    assert len(result.company_delay) == 1
    assert result.company_delay[0].calculation_status == "NEEDS_DATE"
    assert result.company_delay[0].last_action_date is None
    assert any(x["kind"] == "UNRESOLVED_UNDATED_EVENT_ORDER" for x in result.diagnostics)


def test_future_dated_event_cannot_override_as_of_responsibility():
    records = [
        rec(side="send", date="1405/01/01", block=0),
        rec(side="receive", date="1405/01/20", status="A", block=1),
    ]
    result = build_three_engineering_lists(records, status_date="1405/01/10", document_inventory=[inventory(1)])
    assert len(result.consultant_delay) == 1
    assert result.consultant_delay[0].last_action_date == "1405/01/01"
    assert any(x["kind"] == "FUTURE_DATED_EVENT_EXCLUDED" for x in result.diagnostics)


def test_only_future_events_are_not_mislabeled_not_sent():
    records = [rec(side="send", date="1405/02/01", block=0)]
    result = build_three_engineering_lists(records, status_date="1405/01/10", document_inventory=[inventory(1)])
    assert not result.not_sent
    assert not result.company_delay
    assert not result.consultant_delay
    assert any(x["kind"] == "FUTURE_DATED_EVENT_EXCLUDED" for x in result.diagnostics)


def test_receive_before_matched_send_is_diagnostic():
    records = [
        rec(side="send", date="1404/08/11", block=0, event=1),
        rec(side="receive", date="1404/08/10", status="CM", block=0, event=1),
    ]
    result = build_three_engineering_lists(records, status_date="1405/01/01", document_inventory=[inventory(1)])
    issues = [x for x in result.diagnostics if x["kind"] == "RECEIVE_BEFORE_MATCHED_SEND"]
    assert len(issues) == 1
    assert issues[0]["examples"][0]["send_date"] == "1404/08/11"
    assert issues[0]["examples"][0]["receive_date"] == "1404/08/10"
'''


def read(path: Path) -> tuple[str, str]:
    b = path.read_bytes()
    return b.decode('utf-8-sig').replace('\r\n', '\n'), ('\r\n' if b'\r\n' in b else '\n')


def encode(text: str, nl: str) -> bytes:
    return text.replace('\n', nl).encode('utf-8')


def main() -> int:
    for p in (ENGINE, TESTS):
        if not p.is_file():
            print(f'[STOP] Not a Cleaner root: missing {p}')
            return 2

    e, enl = read(ENGINE)
    t, tnl = read(TESTS)

    if 'def _order_events_chronologically(' not in e:
        insertion = 'def _identity(record: LogRecord) -> dict[str, Any]:\n'
        if e.count(insertion) != 1 or e.count('        ordered = sorted(doc_records, key=_sequence_key)\n') != 1:
            print('[STOP] Live source differs from expected anchors. NO FILES CHANGED.')
            print('Send the _sequence_key and ordered= sections for a targeted reconciliation.')
            return 2
        e = e.replace(insertion, HELPER + insertion, 1)
        e = e.replace(
            '        ordered = sorted(doc_records, key=_sequence_key)\n',
            '        ordered, chronology_issues = _order_events_chronologically(\n'
            '            doc_records, status_date=status_date\n'
            '        )\n', 1,
        )
        # Identity must be computed before the diagnostics are added.
        before = ('        if not sends:\n' if '        if not sends:\n' in e else
                  '        if not ordered:\n' if '        if not ordered:\n' in e else None)
        if before is None or e.count(before) != 1:
            print('[STOP] Cannot locate NOT_SENT branch unambiguously. NO FILES CHANGED.')
            return 2
        e = e.replace(before,
                      '        result.diagnostics.extend({**identity, **issue} for issue in chronology_issues)\n'
                      '        if not ordered and doc_records:\n'
                      '            # Interactions exist, but all are after the Status Date.\n'
                      '            continue\n\n' + before, 1)
        # Future-only should not appear NOT_SENT even when legacy check is `if not sends`.
        # The previous guard handles this; strict NOT_SENT remains separately governed.
    else:
        if '_order_events_chronologically(\n            doc_records' not in e:
            print('[STOP] Chronology helper already exists but usage differs. NO FILES CHANGED.')
            return 2

    if 'def test_azd_line_foundation_drawing_uses_latest_actual_date(' not in t:
        t = t.rstrip() + TEST_APPEND + '\n'

    taskline = '- [ ] 4A.10 — Chronological ordering by Jalali event date (AZD FOUNDATION DRAWING regression)'
    if TASKS.is_file():
        tasks, nl = read(TASKS)
        if taskline not in tasks:
            tasks = tasks.rstrip() + '\n' + taskline + '\n'
        task_data = encode(tasks, nl)
    else:
        task_data = ('# Weekly Report Demonstration Tasks\n\n' + taskline + '\n').encode('utf-8')

    changes = {ENGINE: encode(e,enl), TESTS: encode(t,tnl), TASKS: task_data}
    changes = {p:data for p,data in changes.items() if not p.is_file() or p.read_bytes() != data}
    if not changes:
        print('[OK] Already installed. No edits made.')
        return 0

    stamp = datetime.now().strftime('%Y%m%dT%H%M%S')
    backup = ROOT.parent / '.chronology_patch_backups' / ROOT.name / stamp
    for p in changes:
        if p.exists():
            dst = backup / p.relative_to(ROOT)
            dst.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(p,dst)
    for p,data in changes.items():
        p.parent.mkdir(parents=True,exist_ok=True)
        p.write_bytes(data)
    print('[DONE] Chronological event-ordering patch installed.')
    print(f'[BACKUP] {backup}')
    for p in changes:
        print('  '+str(p.relative_to(ROOT)))
    print('[NEXT] python -m pytest -q unit_tests')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
