from copy import deepcopy
import json
from pathlib import Path

from cleaner_core.correspondence_replay import replay_approved_correspondence_corrections
from cleaner_core.state import new_resolved_state


def make_fixture(tmp_path, *, row=21, raw_date='1404/08/11', recv='1404/08/10', status='A', duplicate_letter=False):
    runs = tmp_path / 'runs'
    old = runs / 'azd_old'
    new = runs / 'azd_new'
    (old / 'confirmed_corrections').mkdir(parents=True)
    new.mkdir(parents=True)
    evidence = {
        'project_solution_handle': 'AZD-SOL-9999', 'source_sheet': '230KV SS',
        'document_name': 'PROT & CONTROL SINGLE LINE DIAGRAM',
        'document_wbs': '1.5.1.1.2.1.2', 'send_letter_reference': '1404/ES/S/3003',
        'old_date': '1404/08/11', 'corrected_date': '1404/07/19',
        'paired_receive_date': '1404/08/10', 'paired_receive_status': 'A'}
    (old / 'confirmed_corrections' / 'approved.json').write_text(json.dumps(evidence), encoding='utf-8')
    regions = {'sheets': {'230KV SS': {'regions': [{
        'record_index': 7, 'fields': {
            'name': {'value': evidence['document_name']}, 'wbs': {'value': evidence['document_wbs']}
        }}]}}}
    slots = [
        {'address': f'M{row}', 'value': raw_date},
        {'address': f'M{row+1}', 'value': '1404/ES/S/3003'},
        {'address': f'N{row}', 'value': recv},
        {'address': f'O{row}:O{row+1}', 'value': status},
    ]
    if duplicate_letter:
        slots.append({'address': f'P{row+1}', 'value': '1404/ES/S/3003'})
    cards = {'sheets': {'230KV SS': {'cards': [{'record_index': 7, 'slots': slots}]}}}
    for filename, payload in [('document_regions.json', regions), ('card_maps.json', cards)]:
        (new / filename).write_text(json.dumps(payload), encoding='utf-8')
    solution = {
        'handle': 'AZD-SOL-9999', 'enabled': True,
        'source': {'run_id': 'azd_old'},
        'match': {'test_id': 'CONFIRMED_CORRESPONDENCE_DATE',
                  'sheet': '230KV SS', 'letter_reference': '1404/ES/S/3003',
                  'expected_old_date': '1404/08/11',
                  'document_identity': {'name': evidence['document_name'], 'wbs': evidence['document_wbs']}},
        'resolution': {'action': 'SET_VALUE', 'parameters': {'value': '1404/07/19'}}}
    registry = {'solutions': [solution]}
    state = new_resolved_state(run_id='azd_new', profile_name='AZD')
    return new, registry, state


def run(new, registry, state, **kwargs):
    return replay_approved_correspondence_corrections(new, registry, state, **kwargs)


def test_replay_applies_same_letter_at_moved_row(tmp_path):
    new, registry, state = make_fixture(tmp_path, row=35)
    report = run(new, registry, state)
    assert report['summary']['APPLIED'] == 1
    assert state['value_overrides']['230KV SS!M35']['value'] == '1404/07/19'
    assert '230KV SS!M21' not in state['value_overrides']


def test_replay_is_idempotent(tmp_path):
    new, registry, state = make_fixture(tmp_path)
    run(new, registry, state)
    report = run(new, registry, state)
    assert report['summary']['ALREADY_APPLIED'] == 1
    assert len(state['value_overrides']) == 1


def test_already_correct_source_is_not_overwritten(tmp_path):
    new, registry, state = make_fixture(tmp_path, raw_date='1404/07/19')
    report = run(new, registry, state)
    assert report['summary']['ALREADY_CORRECT'] == 1
    assert not state['value_overrides']


def test_conflicting_source_date_goes_to_review(tmp_path):
    new, registry, state = make_fixture(tmp_path, raw_date='1404/06/22')
    report = run(new, registry, state)
    assert report['summary']['NEEDS_REVIEW'] == 1
    assert report['results'][0]['reason'] == 'OLD_VALUE_GUARD_FAILED'
    assert not state['value_overrides']


def test_guard_rejects_changed_correspondence_response(tmp_path):
    new, registry, state = make_fixture(tmp_path, recv='1404/08/12')
    report = run(new, registry, state)
    assert report['results'][0]['reason'] == 'PAIRED_RECEIVE_GUARD_FAILED'
    assert not state['value_overrides']


def test_ambiguous_reference_is_reviewed(tmp_path):
    new, registry, state = make_fixture(tmp_path, duplicate_letter=True)
    report = run(new, registry, state)
    assert report['results'][0]['reason'] == 'LETTER_REFERENCE_NOT_UNIQUE'
    assert not state['value_overrides']


def test_missing_approval_evidence_never_applies(tmp_path):
    new, registry, state = make_fixture(tmp_path)
    for p in (new.parent / 'azd_old' / 'confirmed_corrections').glob('*.json'):
        p.unlink()
    report = run(new, registry, state)
    assert report['results'][0]['reason'] == 'APPROVAL_EVIDENCE_UNAVAILABLE'
    assert not state['value_overrides']


def test_dry_run_preserves_state(tmp_path):
    new, registry, state = make_fixture(tmp_path)
    report = run(new, registry, state, dry_run=True)
    assert report['summary']['APPLIED'] == 1
    assert not state['value_overrides']


def test_conflicting_existing_override_never_replaced(tmp_path):
    new, registry, state = make_fixture(tmp_path)
    state['value_overrides']['230KV SS!M21'] = {'value': '1404/01/01'}
    report = run(new, registry, state)
    assert report['results'][0]['reason'] == 'EXISTING_OVERRIDE_CONFLICT'
    assert state['value_overrides']['230KV SS!M21']['value'] == '1404/01/01'
