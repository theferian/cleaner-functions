#!/usr/bin/env python3
r"""Quarantine the unsafe BFG review that replaces a RECEIVE DATE with 'NA'.

Run from cleaner-functions root:
    py .\RECOVER_BFG_K69.py --check
    py .\RECOVER_BFG_K69.py --apply

It changes only run-local review/overlay metadata and disables its project-specific
learned solution. No workbook or network original is edited. Backups are created.
"""
from __future__ import annotations
import argparse
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parent
RUN_ID = 'bfg_20261017T130419'
REVIEW_ID_FRAGMENT = 'FIELD_VALIDATION_BAAFGH_K69_'


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def ensure(test, message):
    if not test:
        raise RuntimeError(message)


def write(path, obj):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str) + '\n', encoding='utf-8')
    temp.replace(path)


def find_review(items):
    found = [item for item in items if isinstance(item, dict) and REVIEW_ID_FRAGMENT in str(item.get('review_id') or '')]
    ensure(len(found) == 1, f'Expected exactly one BAAFGH K69 item, found {len(found)}')
    return found[0]


def prepare(root, run_id):
    run_dir = root / 'runs' / run_id
    ensure(run_dir.is_dir(), f'Run missing: {run_dir}')
    manifest = load(run_dir / 'run_manifest.json')
    ensure(manifest.get('profile_name') == 'BFG', 'Wrong project: refuse to modify run')
    decisions_path = run_dir / 'field_validation_review_decisions.json'
    queue_path = run_dir / 'field_validation_review_queue.json'
    state_path = run_dir / 'resolved_state.json'
    solution_path = root / 'project_solutions' / 'BFG.solutions.json'
    exception_path = root / 'exceptions' / 'BFG.exceptions.json'
    paths = [decisions_path, queue_path, state_path, solution_path]
    for path in paths:
        ensure(path.is_file(), f'Required file missing: {path}')
    decisions, queue, state, solutions = map(load, paths)
    item = find_review(decisions.get('decisions') or [])
    qitem = find_review(queue.get('items') or [])
    rid = item['review_id']
    ensure(qitem['review_id'] == rid, 'Decision and queue item IDs differ')
    location = item.get('location') or {}
    ensure(location.get('sheet') == 'BAAFGH' and location.get('target') == 'K69', 'Unexpected K69 review target')
    ensure('no populated corresponding status' in str(item.get('message') or ''), 'This is not the expected missing-status finding')
    d = item.get('decision') or {}
    params = d.get('parameters') or {}
    ensure(d.get('action') == 'REPLACE_VALUE', 'Expected old REPLACE_VALUE; already changed or different scenario')
    ensure(params.get('sheet') == 'BAAFGH' and params.get('target') == 'K69' and str(params.get('new_value')).upper() == 'NA', 'Unexpected replacement values; refuse')
    override = (state.get('value_overrides') or {}).get('BAAFGH!K69')
    ensure(isinstance(override, dict) and override.get('source_review_id') == rid and str(override.get('value')).upper() == 'NA', 'Unrecognized K69 state override; refuse')
    matches = [s for s in solutions.get('solutions') or [] if (s.get('source') or {}).get('review_id') == rid and (s.get('source') or {}).get('run_id') == run_id]
    ensure(len(matches) <= 1, f'Expected at most one project solution for the review; found {len(matches)}')
    print('[CHECK] Unsafe receive-date replacement at BAAFGH!K69 -> NA found')
    print(f'[CHECK] Review: {rid}; matching learned solutions: {len(matches)}')
    return dict(run_dir=run_dir, paths=paths, decision=decisions, queue=queue, state=state,
                solutions=solutions, matches=matches, rid=rid, item=item, qitem=qitem,
                old=deepcopy(d), exception_path=exception_path)


def main():
    ap = argparse.ArgumentParser()
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check', action='store_true')
    mode.add_argument('--apply', action='store_true')
    ap.add_argument('--run-id', default=RUN_ID)
    args = ap.parse_args()
    try:
        ctx = prepare(ROOT, args.run_id)
        if args.check:
            print('[CHECK] Ready to quarantine this decision without changing any workbook.')
            return 0
        # Record an unresolved investigation rather than inventing a status.
        new = {
            'action': 'TRACK_EXCEPTION',
            'parameters': {'title': 'BAAFGH K69 receive date lacks paired response status',
                           'workflow_status': 'INVESTIGATE',
                           'tags': 'field_validation,missing_receive_status,wrong_target_repair'},
            'reason': 'Supersedes unsafe K69 date -> NA replacement; actual response status needs source evidence.',
            'reviewer': 'operator-correction',
            'decided_at': datetime.now().isoformat(timespec='seconds'),
            'execution_kind': 'EXCEPTION_REGISTRY',
            'execution_state': 'PENDING',
        }
        ctx['item']['decision'] = deepcopy(new)
        ctx['qitem']['decision'] = deepcopy(new)
        ctx['qitem']['review_state'] = 'RESOLVED'
        del ctx['state']['value_overrides']['BAAFGH!K69']
        ctx['state'].setdefault('decision_audit', []).append({
            'review_id': ctx['rid'], 'source': deepcopy(ctx['item'].get('source') or {}),
            'location': deepcopy(ctx['item'].get('location') or {}),
            'decision': deepcopy(new), 'ingested_at': new['decided_at'],
            'note': 'Previous action retained in recovery backup; no Excel workbook edit.'
        })
        ctx['state'].setdefault('review_corrections', []).append({
            'review_id': ctx['rid'], 'corrected_at': new['decided_at'],
            'old_action': ctx['old'], 'new_action': deepcopy(new),
            'source_workbook_unchanged': True})
        for sol in ctx['matches']:
            sol['enabled'] = False
            sol['disabled_reason'] = 'Unsafe date-cell replacement superseded by tracked investigation.'
            sol['disabled_at'] = new['decided_at']
        # Link a tracked exception through the existing project's registry handler.
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from cleaner_core.exceptions import (load_exception_registry,
                                              save_exception_registry,
                                              sync_registry_from_decisions_payload)
        reg = load_exception_registry(ctx['exception_path'], profile_name='BFG', create=True)
        sync_registry_from_decisions_payload(reg, ctx['decision'])
        backup = ROOT / f'_bfg_k69_recovery_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
        ensure(not backup.exists(), 'Backup directory already exists')
        backup.mkdir(parents=True)
        for p in ctx['paths'] + ([ctx['exception_path']] if ctx['exception_path'].exists() else []):
            shutil.copy2(p, backup / p.name)
        write(ctx['paths'][0], ctx['decision'])
        write(ctx['paths'][1], ctx['queue'])
        write(ctx['paths'][2], ctx['state'])
        write(ctx['paths'][3], ctx['solutions'])
        save_exception_registry(reg, ctx['exception_path'])
        print('[DONE] K69 -> NA workbook change quarantined; original date left untouched.')
        print('[DONE] Missing receive status tracked as INVESTIGATE; learned unsafe solution disabled.')
        print(f'[BACKUP] {backup}')
        print('[NEXT] py .\\RUN_GENERAL_DOCUMENT_V03.py --project BFG --run-id "' + args.run_id + '" --status-date 1405/07/22')
        return 0
    except Exception as exc:
        print(f'[STOP] {exc}. No source workbook was edited.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
