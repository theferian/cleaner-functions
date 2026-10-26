"""Durable field drawings, direction-scoped queues, interoperable read-only exports.

No assumption that OCR text or a machine match is an independently verified fact.
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

FAMILIES = {'send': 'OFFICIAL_OUTGOING_LETTER_FIELDS_v01',
            'receive': 'CONSULTANT_INCOMING_LETTER_FIELDS_v01'}
SCOPES = {'Outgoing (our letters)': 'send',
          'Incoming (consultant)': 'receive',
          'Both directions': 'both'}
REQUIRED = ('letter_date', 'letter_reference')


def scoped(queue, scope):
    direction = SCOPES.get(scope, scope)
    if direction not in ('send', 'receive', 'both'):
        raise ValueError('Unknown source direction: ' + str(scope))
    return [q for q in queue if direction == 'both' or q['event'].get('direction') == direction]


def _file_info(path):
    stat = Path(path).stat()
    return {'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns}


def draft_file(directory, pdf_path, family, page=1):
    ident = hashlib.sha256((str(Path(pdf_path).resolve()).casefold() + '|' + family + '|' + str(page)).encode('utf-8')).hexdigest()[:24]
    return Path(directory) / ('field_draft_' + ident + '.json')


def normalise_rects(boxes, width, height):
    if width <= 0 or height <= 0:
        raise ValueError('Invalid page dimensions')
    result = {}
    for field, rect in boxes.items():
        if not field.replace('_', '').isalnum():
            raise ValueError('Invalid field')
        if len(rect) != 4:
            raise ValueError('Expected 4 coordinates')
        x0, y0, x1, y1 = [float(x) for x in rect]
        if not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height):
            raise ValueError('Invalid rectangle')
        result[field] = [round(x0 / width, 7), round(y0 / height, 7),
                         round(x1 / width, 7), round(y1 / height, 7)]
    return result


def signature(normalized):
    return hashlib.sha256(json.dumps(normalized, sort_keys=True, separators=(',', ':')).encode()).hexdigest()[:20]


def save_draft(directory, pdf_path, family, boxes, width, height, *, prior_approval=None, page=1):
    rectangles = normalise_rects(boxes, width, height)
    target = draft_file(directory, pdf_path, family, page)
    approval = prior_approval if prior_approval == signature(rectangles) else None
    data = {'schema': 'cleaner.adaptive_field_draft/0.4', 'source_pdf': str(Path(pdf_path).resolve()),
            'source_stat': _file_info(pdf_path), 'family': family, 'page': page,
            'normalized_boxes': rectangles, 'box_signature': signature(rectangles),
            'approved_box_signature': approval, 'extraction_approved': bool(approval),
            'saved_at': datetime.now(timezone.utc).isoformat(),
            'meaning': 'Field-location draft; not confirmation of extracted values'}
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix('.json.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temp, target)
    return target, data


def load_draft(directory, pdf_path, family, width, height, page=1):
    target = draft_file(directory, pdf_path, family, page)
    if not target.is_file():
        return None
    data = json.loads(target.read_text(encoding='utf-8'))
    if (data.get('schema') != 'cleaner.adaptive_field_draft/0.4' or
        data.get('family') != family or data.get('source_stat') != _file_info(pdf_path)):
        return None  # source changed; do not silently reuse old geometry
    boxes = {}
    for name, (x0, y0, x1, y1) in data['normalized_boxes'].items():
        boxes[name] = [x0 * width, y0 * height, x1 * width, y1 * height]
    return {'boxes': boxes, 'data': data}


def _field_details(row, field):
    evid = (row.get('evidence') or {}).get('evidence') or {}
    obs = next((x for x in evid.get('fields', []) if x.get('field') == field), {})
    reconstruction = row.get('reconstructions', {}).get(field, {})
    review = row.get('review') or {}
    return {
        'expected': row['date_expected'] if field == 'letter_date' else row['reference_expected'],
        'raw_native': obs.get('native_text', ''),
        'raw_ocr': obs.get('ocr_text', ''),
        'ocr_status': obs.get('ocr_status', 'NOT_RUN'),
        'candidates': reconstruction.get('independent_candidates', []),
        'expected_guided_hint': reconstruction.get('expected_guided_hint'),
        'machine_status': reconstruction.get('machine_outcome', 'NOT_CHECKED'),
        'field_status': row.get('field_status', {}).get(field, 'NOT_CHECKED'),
        'manual_reading': review.get('manual', {}).get(field, ''),
        'bbox_pdf': obs.get('bbox_pdf'),
        'page': obs.get('page'),
    }


def portable_record(row):
    item = row['item']; ev = item['event']; card = row['card']
    evidence = row.get('evidence') or {}
    return {'schema': 'cleaner.card_source_verification/0.4',
            'event_key': row['event_key'], 'card': {k: card.get(k) for k in ('sheet','index','name','wbs')},
            'direction': ev.get('direction'), 'family': FAMILIES.get(ev.get('direction'),'UNKNOWN'),
            'source': {'pdf_path': row['source_path'], 'locator_status': row.get('locator'),
                       'pdf_sha256': (evidence.get('evidence') or {}).get('pdf_sha256'),
                       'ocr_event_time': evidence.get('at'),
                       'ocr_processing_status': evidence.get('processing_status'),
                       'date_source_cell': ev.get('date_source'),
                       'reference_source_cell': ev.get('reference_source')},
            'fields': {f: _field_details(row, f) for f in REQUIRED},
            'status': row['status'], 'review_status': row.get('review_status'),
            'reviewer': (row.get('review') or {}).get('reviewer'),
            'review_timestamp': (row.get('review') or {}).get('at'),
            'evidence_hash': row.get('evidence_hash'),
            'machine_output_is_approved': False,
            'changes_to_cleaner': False}


def export_machine_results(rows, output_dir, *, run_dir=None, scope='both'):
    output_dir = Path(output_dir); output_dir.mkdir(parents=True, exist_ok=True)
    records = [portable_record(row) for row in rows]
    json_file = output_dir / 'verification_events_v04.jsonl'
    csv_file = output_dir / 'verification_events_v04.csv'
    summary_file = output_dir / 'verification_summary_v04.json'
    with json_file.open('w', encoding='utf-8', newline='\n') as handle:
        for rec in records: handle.write(json.dumps(rec, ensure_ascii=False) + '\n')
    fields = ['event_key', 'card_sheet', 'card_index', 'card_name', 'wbs', 'direction', 'family', 'pdf_path',
              'expected_date', 'native_date', 'ocr_date', 'date_candidates', 'date_field_status', 'date_ocr_status',
              'expected_reference', 'native_reference', 'ocr_reference', 'reference_candidates',
              'reference_field_status', 'reference_ocr_status', 'manual_date', 'manual_reference',
              'status', 'review_status', 'pdf_sha256', 'evidence_hash', 'date_source_cell', 'reference_source_cell']
    with csv_file.open('w', encoding='utf-8-sig', newline='') as handle:
        writer=csv.DictWriter(handle, fieldnames=fields);writer.writeheader()
        for x in records:
            d=x['fields']['letter_date'];r=x['fields']['letter_reference'];s=x['source'];c=x['card']
            writer.writerow({'event_key': x['event_key'], 'card_sheet': c['sheet'], 'card_index': c['index'],
                'card_name': c['name'], 'wbs': c['wbs'], 'direction': x['direction'], 'family': x['family'],
                'pdf_path': s['pdf_path'], 'expected_date': d['expected'], 'native_date': d['raw_native'],
                'ocr_date': d['raw_ocr'], 'date_candidates': '|'.join(v['value'] for v in d['candidates']),
                'date_field_status': d['field_status'], 'date_ocr_status': d['ocr_status'],
                'expected_reference': r['expected'], 'native_reference': r['raw_native'],
                'ocr_reference': r['raw_ocr'], 'reference_candidates': '|'.join(v['value'] for v in r['candidates']),
                'reference_field_status': r['field_status'], 'reference_ocr_status': r['ocr_status'],
                'manual_date': d['manual_reading'], 'manual_reference': r['manual_reading'],
                'status': x['status'], 'review_status': x['review_status'],
                'pdf_sha256': s['pdf_sha256'], 'evidence_hash': x['evidence_hash'],
                'date_source_cell': s['date_source_cell'], 'reference_source_cell': s['reference_source_cell']})
    from collections import Counter
    counts = dict(Counter(x['status'] for x in records))
    summary = {'schema': 'cleaner.card_verification_export/0.4',
               'exported_at': datetime.now(timezone.utc).isoformat(),
               'run_dir': str(run_dir) if run_dir else None,
               'source': 'board_to_log.json snapshot, not live Excel',
               'direction_scope': scope, 'total': len(records), 'status_counts': counts,
               'files': [json_file.name, csv_file.name],
               'auto_corrections': 0, 'read_only': True,
               'warning': 'Machine OCR candidates are not verified facts; only independent manual readings may verify.'}
    summary_file.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding='utf-8')
    return json_file, csv_file, summary_file
