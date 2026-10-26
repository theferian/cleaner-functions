"""Read-only General Doc source verification ledger (v0.3).

Consumes v0.2 OCR journal, keeps independently reviewed decisions in its own
append-only file. Never edits General Doc/Excel/Cleaner correction state.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

from card_teaching_core import canonical_date, canonical_reference, normalize_digits

FIELD_NAMES = ('letter_date', 'letter_reference')
DIGIT_TRANSLATION = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')
ZERO_WIDTH = '\u200c\u200d\u200e\u200f\u202a\u202b\u202c\u2066\u2067\u2068\u2069'


def _fold(value: str) -> str:
    v = unicodedata.normalize('NFKC', str(value or '')).translate(DIGIT_TRANSLATION)
    v = v.translate({ord(c): None for c in ZERO_WIDTH})
    return v.replace('／', '/').replace('⁄', '/').replace('∕', '/').replace('٫', '/').replace('\\', '/')


def _valid_date(value: str) -> str | None:
    v = _fold(value)
    # Month/day may use one digit. Do NOT infer year or omitted digits.
    m = re.search(r'(?<!\d)(1[34]\d{2})\s*[/._:\-]\s*(\d{1,2})\s*[/._:\-]\s*(\d{1,2})(?!\d)', v)
    if m:
        return canonical_date('/'.join(m.groups()))
    # OCR sometimes loses both separators but retains all eight digits.
    m = re.search(r'(?<!\d)(1[34]\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(?!\d)', v)
    if m:
        return canonical_date('/'.join(m.groups()))
    return None


def _reference(value: str) -> str | None:
    v = _fold(value).upper()
    # Full official-letter form: YYYY/ES/S/2605. Other letter-code pairs permitted.
    m = re.search(r'(?<!\d)(1[34]\d{2})\s*[/._\-]\s*([A-Z]{1,5})\s*[/._\-]\s*([A-Z]{1,5})\s*[/._\-]\s*(\d{1,7})(?!\d)', v)
    if m:
        return canonical_reference('/'.join(m.groups()))
    return None


def _short_reference(value: str) -> tuple[str, str] | None:
    v = _fold(value)
    m = re.search(r'(?<!\d)(1[34]\d{2})\s*[-/]\s*(\d{2,7})(?!\d)', v)
    return (m.group(1), str(int(m.group(2)))) if m else None


def _distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ch in enumerate(a, 1):
        curr = [i] + [0] * len(b)
        for j, want in enumerate(b, 1):
            curr[j] = min(curr[j-1] + 1, prev[j] + 1, prev[j-1] + (ch != want))
        prev = curr
    return prev[-1]


def reconstruct_field(field: str, native: str, ocr: str, expected: str) -> dict[str, Any]:
    """Field reconstruction candidates; anything guided by expected is labeled.

    A fuzzy/shortened match must NEVER be promoted to independently verified.
    """
    parser = _valid_date if field == 'letter_date' else _reference
    expected_norm = parser(expected)
    options = []
    for origin, raw in (('NATIVE', native), ('OCR', ocr)):
        v = parser(raw)
        if v and not any(x['value'] == v and x['origin'] == origin for x in options):
            options.append({'value': v, 'origin': origin, 'basis': 'INDEPENDENT_PARSE'})
    unique = {x['value'] for x in options}
    short_compatible = False
    if field == 'letter_reference' and expected_norm:
        exp = re.search(r'(1[34]\d{2})[A-Z]+[A-Z]+(\d+)$', expected_norm)
        if exp:
            for text in (native, ocr):
                short = _short_reference(text)
                if short and short == (exp.group(1), str(int(exp.group(2)))):
                    short_compatible = True
    # This is ONLY a search hint: don't manufacture an evidence-based value
    # using the General Doc's expectation.
    hint = None
    if expected_norm and not unique:
        for origin, raw in (('NATIVE', native), ('OCR', ocr)):
            token = re.sub('[^A-Z0-9]', '', _fold(raw).upper())
            if len(token) >= 4:
                dist = _distance(token, expected_norm)
                if hint is None or dist < hint['edit_distance']:
                    hint = {'expected_hypothesis': expected_norm, 'origin': origin,
                            'edit_distance': dist, 'basis': 'EXPECTED_GUIDED_NOT_EVIDENCE'}
    if len(unique) > 1:
        outcome = 'READER_CONFLICT'
    elif len(unique) == 1:
        outcome = 'EXACT_CANDIDATE_MATCH' if expected_norm in unique else 'CANDIDATE_MISMATCH'
    elif short_compatible:
        outcome = 'SHORT_REFERENCE_COMPATIBLE_UNCONFIRMED'
    else:
        outcome = 'UNREADABLE_NEEDS_REVIEW'
    return {'field': field, 'expected_normalized': expected_norm,
            'independent_candidates': options, 'machine_outcome': outcome,
            'short_reference_compatible': short_compatible,
            'expected_guided_hint': hint,
            'verified': False}


def compare_manual(field: str, printed_value: str, general_doc_value: str) -> str:
    """Human transcription comparison: no automatic match on abbreviated references."""
    if not str(printed_value).strip():
        return 'NOT_REVIEWED'
    parser = _valid_date if field == 'letter_date' else _reference
    found, expected = parser(printed_value), parser(general_doc_value)
    if not expected:
        return 'GENERAL_DOC_FORMAT_REVIEW'
    if not found:
        if field == 'letter_reference':
            short = _short_reference(printed_value)
            exp = re.search(r'(1[34]\d{2})[A-Z]+[A-Z]+(\d+)$', expected)
            if short and exp and short == (exp.group(1), str(int(exp.group(2)))):
                return 'PARTIAL_REFERENCE_REVIEW'
        return 'TRANSCRIPTION_FORMAT_REVIEW'
    return 'HUMAN_MATCH' if found == expected else 'HUMAN_MISMATCH'


def _read_jsonl(p: Path):
    if not p.is_file():
        return
    with p.open('r', encoding='utf-8-sig') as f:
        for line in f:
            try:
                value = json.loads(line)
                if isinstance(value, dict):
                    yield value
            except (ValueError, UnicodeError):
                continue


def evidence_hash(event: dict) -> str | None:
    """Anchors an approval to actual source hash, expected General Doc values,
    OCR values, and boxes; changing any makes the old approval stale.
    """
    data = event.get('evidence') or {}
    pdf_hash = data.get('pdf_sha256')
    if not pdf_hash or not data.get('complete'):
        return None
    snapshot = {
        'source_pdf_sha256': pdf_hash,
        'event_key': event.get('event_key'),
        'source_pdf': event.get('source_pdf'),
        'expected': {f: event.get('source_event', {}).get(k, '') for f,k in
                     [('letter_date','date'), ('letter_reference','reference')]},
        'fields': [{k: f.get(k) for k in
                    ('field','bbox_pdf','page','native_text','ocr_text','ocr_status','result')}
                   for f in data.get('fields', [])],
    }
    return hashlib.sha256(json.dumps(snapshot, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode('utf-8')).hexdigest()


def latest_results(journal: Path) -> dict[str, dict]:
    records = {}
    for item in _read_jsonl(journal):
        if item.get('event_key'):
            records[item['event_key']] = item
    return records


def latest_reviews(journal: Path) -> dict[str, dict]:
    records = {}
    for item in _read_jsonl(journal):
        if item.get('event_key') and item.get('schema') == 'cleaner.card_verification_review/0.3':
            key = item['event_key']
            previous = records.get(key)
            # Independent field reviews can be completed on different days.
            # Carry forward only reviews of EXACTLY the same OCR/source snapshot.
            if previous and previous.get('evidence_hash') == item.get('evidence_hash'):
                merged = dict(item)
                merged['manual'] = {**previous.get('manual', {}), **item.get('manual', {})}
                merged['field_decisions'] = {**previous.get('field_decisions', {}),
                                             **item.get('field_decisions', {})}
                item = merged
            records[key] = item
    return records


def _status(field_states: list[str], evidence: dict | None, locator: str):
    if field_states and all(v == 'HUMAN_MATCH' for v in field_states):
        return 'VERIFIED_CORRECT'
    if 'HUMAN_MISMATCH' in field_states:
        return 'VERIFIED_ERROR'
    if any(v in ('HUMAN_MATCH','PARTIAL_REFERENCE_REVIEW') for v in field_states):
        return 'PARTIALLY_REVIEWED'
    if locator == 'NOT_FOUND':
        return 'SOURCE_MISSING'
    if locator == 'MULTIPLE_CANDIDATES':
        return 'SOURCE_AMBIGUOUS'
    if not evidence:
        return 'NOT_CHECKED'
    if evidence.get('processing_status') != 'COMPLETED':
        return 'NEEDS_REVIEW'
    if any(v == 'READER_CONFLICT' for v in field_states):
        return 'READER_CONFLICT'
    if any(v in ('CANDIDATE_MISMATCH','SHORT_REFERENCE_COMPATIBLE_UNCONFIRMED') for v in field_states):
        return 'POSSIBLE_MISMATCH'
    if any(v == 'UNREADABLE_NEEDS_REVIEW' for v in field_states):
        return 'UNREADABLE'
    if field_states and all(v == 'EXACT_CANDIDATE_MATCH' for v in field_states):
        return 'MACHINE_MATCH_UNVERIFIED'
    return 'NEEDS_REVIEW'


def build_ledger(queue: list[dict], ocr_journal: Path, review_journal: Path) -> list[dict]:
    reads = latest_results(ocr_journal)
    approvals = latest_reviews(review_journal)
    result = []
    for item in queue:
        key = item['event_key']; ev = item['event']; saved = reads.get(key)
        proof = evidence_hash(saved) if saved else None
        review = approvals.get(key)
        review_status = ('CURRENT' if review and proof and
                         review.get('evidence_hash') == proof else
                         'STALE' if review else 'NONE')
        observed = {f['field']: f for f in (saved or {}).get('evidence',{}).get('fields',[])
                    if f.get('field') in FIELD_NAMES}
        states = {}; recon = {}
        for f in FIELD_NAMES:
            value = ev.get('date' if f=='letter_date' else 'reference','')
            obs = observed.get(f,{})
            s = reconstruct_field(f, obs.get('native_text',''), obs.get('ocr_text',''), value)
            recon[f] = s
            state = s['machine_outcome'] if obs else 'NOT_CHECKED'
            if review_status == 'CURRENT' and f in (review or {}).get('manual',{}):
                state = compare_manual(f, review['manual'][f], value)
            states[f] = state
        status = _status(list(states.values()), saved, item['locator'])
        if review_status == 'STALE':
            status = 'STALE_REVIEW' if proof else 'EVIDENCE_CHANGED'
        result.append({'event_key':key,'item':item,'date_expected':ev.get('date',''),
                       'reference_expected':ev.get('reference',''), 'source_path':str(item.get('path') or ''),
                       'card':item['card'], 'locator':item['locator'], 'evidence':saved,
                       'evidence_hash':proof,'review':review,'review_status':review_status,
                       'reconstructions':recon,'field_status':states,'status':status})
    return result


def make_review(row: dict, *, manual_date: str='', manual_reference: str='',
                reviewer: str='', note: str='', at: str='') -> dict:
    if not row.get('evidence_hash') or not row.get('evidence'):
        raise ValueError('Run OCR and save source evidence before recording a verified review')
    manual = {}
    if manual_date.strip(): manual['letter_date'] = manual_date.strip()
    if manual_reference.strip(): manual['letter_reference'] = manual_reference.strip()
    if not manual:
        raise ValueError('Enter at least one value independently read from the PDF')
    outcomes = {f: compare_manual(f, v, row['date_expected'] if f=='letter_date'
                                  else row['reference_expected']) for f,v in manual.items()}
    if any(v in ('TRANSCRIPTION_FORMAT_REVIEW','GENERAL_DOC_FORMAT_REVIEW') for v in outcomes.values()):
        raise ValueError('Could not parse a transcribed value; correct it or leave that field empty')
    return {'schema':'cleaner.card_verification_review/0.3',
            'at': at,'event_key':row['event_key'],'source_pdf':row['source_path'],
            'source_sha256':row['evidence']['evidence'].get('pdf_sha256'),
            'evidence_hash':row['evidence_hash'], 'general_doc_snapshot':{
                'date':row['date_expected'],'reference':row['reference_expected']},
            'manual':manual,'field_decisions':outcomes,'reviewer':reviewer.strip() or 'local_operator',
            'note':note.strip(),'writes_to_general_doc':False}


def overview(rows: list[dict]) -> dict[str,int]:
    counts = Counter(x['status'] for x in rows)
    counts['TOTAL'] = len(rows)
    counts['OCR_PROCESSED'] = sum(bool(x['evidence'] and x['evidence'].get('processing_status') == 'COMPLETED') for x in rows)
    counts['HUMAN_VERIFIED'] = counts['VERIFIED_CORRECT'] + counts['VERIFIED_ERROR']
    counts['REQUIRES_ATTENTION'] = sum(x['status'] not in ('VERIFIED_CORRECT','MACHINE_MATCH_UNVERIFIED') for x in rows)
    cards = {}
    for row in rows:
        card = row['card']
        cards.setdefault((str(card.get('sheet','')),str(card.get('index',''))),[]).append(row['status'])
    counts['CARDS_TOTAL'] = len(cards)
    counts['CARDS_FULLY_VERIFIED'] = sum(all(s == 'VERIFIED_CORRECT' for s in states)
                                         for states in cards.values())
    counts['CARDS_WITH_VERIFIED_ERROR'] = sum('VERIFIED_ERROR' in states for states in cards.values())
    counts['CARDS_PENDING'] = counts['CARDS_TOTAL'] - counts['CARDS_FULLY_VERIFIED'] - counts['CARDS_WITH_VERIFIED_ERROR']
    return dict(counts)


def export_csv(rows: list[dict], target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    cols = ('card_sheet','card_index','card_name','wbs','direction','source_pdf','expected_date',
            'ocr_date','date_status','expected_reference','ocr_reference','reference_status',
            'date_source_cell','reference_source_cell','overall_status','review_status','event_key','evidence_hash')
    with target.open('w', encoding='utf-8-sig', newline='') as fh:
        writer = csv.DictWriter(fh, fieldnames=cols);writer.writeheader()
        for row in rows:
            card=row['card'];item=row['item'];fs=row['field_status'];r=row['reconstructions']
            def val(f):
                v = r[f]['independent_candidates']
                return ' | '.join(dict.fromkeys(x['value'] for x in v))
            writer.writerow(dict(card_sheet=card.get('sheet',''),card_index=card.get('index',''),
                card_name=card.get('name',''),wbs=card.get('wbs',''),
                direction=item['event'].get('direction',''),source_pdf=row['source_path'],
                expected_date=row['date_expected'],ocr_date=val('letter_date'),
                date_status=fs['letter_date'], expected_reference=row['reference_expected'],
                ocr_reference=val('letter_reference'),reference_status=fs['letter_reference'],
                date_source_cell=item['event'].get('date_source',''),
                reference_source_cell=item['event'].get('reference_source',''),
                overall_status=row['status'], review_status=row['review_status'],
                event_key=row['event_key'],evidence_hash=row['evidence_hash'] or ''))
