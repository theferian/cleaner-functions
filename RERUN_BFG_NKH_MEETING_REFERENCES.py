#!/usr/bin/env python3
r"""Replay BFG and NKH after installing GENERAL_DOCUMENT meeting-reference rule.

Keeps old issues in discovery_history/ before regenerating any results.
Verifies that every old MISSING_REFERENCE has a corresponding discovered literal
receive-reference observation afterward. Does not modify the original Excel files.

Use in cleaner-functions root:
  py .\RERUN_BFG_NKH_MEETING_REFERENCES.py --status-date 1405/07/22
"""
from __future__ import annotations
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
PROJECTS = (("BFG", "bfg_20261017T130419"), ("NKH", "nkh_20261017T053117"))
KEEP = (
    "board_to_log.json", "board_to_log_issues.csv", "board_to_log_issue_context.json",
    "board_to_log_review.json", "coverage_audit.json", "engineering_review.json",
)


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def expected_observations(before, after):
    """Prove each formerly missing-reference date has a source-backed reference."""
    issues = [x for x in before.get("issues", []) if x.get("kind") == "MISSING_REFERENCE"]
    observations = (after.get("diagnostics") or {}).get("reference_observations") or []
    found = {
        (str(x.get("source_sheet")), str(x.get("date_source")), str(x.get("document_index"))): x
        for x in observations if x.get("kind") == "MEETING_BASED_RECEIVE_REFERENCE"
    }
    recovered, unmatched = [], []
    for issue in issues:
        key = (str(issue.get("sheet")), str(issue.get("address")), str(issue.get("document_index")))
        observation = found.get(key)
        if observation is None:
            unmatched.append(issue)
        else:
            recovered.append({"prior_issue": issue, "recovered_observation": observation})
    return recovered, unmatched


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--status-date', required=True)
    args = p.parse_args()
    if not (ROOT / 'RUN_GENERAL_DOCUMENT_V03.py').is_file():
        p.error('RUN_GENERAL_DOCUMENT_V03.py not found in cleaner-functions root')
    extractor = ROOT / 'functions' / 'board_to_log' / 'extractor.py'
    if not extractor.is_file() or 'GENERAL_DOCUMENT_MEETING_REFERENCE_V01' not in extractor.read_text(encoding='utf-8'):
        p.error('Meeting reference installer not applied; use --check and --apply first')

    print('[REPLAY] BFG and NKH; old MISSING_REFERENCE findings will be preserved')
    for project, run_id in PROJECTS:
        run_dir = ROOT / 'runs' / run_id
        before_path = run_dir / 'board_to_log.json'
        if not before_path.is_file():
            p.error(f'Missing existing run evidence: {before_path}')
        before = load(before_path)
        if str(before.get('project_id')).upper() != project:
            p.error(f'Project mismatch in {before_path}')
        stamp = datetime.now().strftime('%Y%m%dT%H%M%S%f')
        history = run_dir / 'discovery_history' / f'meeting_reference_replay_{stamp}'
        history.mkdir(parents=True, exist_ok=False)
        for name in KEEP:
            src = run_dir / name
            if src.exists():
                shutil.copy2(src, history / name)
        print(f'[ARCHIVE] {project}: {history}')
        prior_count = sum(x.get('kind') == 'MISSING_REFERENCE' for x in before.get('issues', []))
        print(f'[BEFORE] {project}: records={len(before.get("records", []))}, MISSING_REFERENCE={prior_count}')

        cmd = [sys.executable, str(ROOT / 'RUN_GENERAL_DOCUMENT_V03.py'),
               '--project', project, '--run-id', run_id,
               '--status-date', args.status_date]
        rc = subprocess.call(cmd, cwd=str(ROOT))
        if rc:
            print(f'[STOP] {project}: runner returned {rc}; archived originals remain at {history}')
            return rc

        after = load(before_path)
        observations = (after.get('diagnostics') or {}).get('reference_observations') or []
        recovered, unmatched = expected_observations(before, after)
        unmatched_other = [x for x in (after.get('issues') or []) if x.get('kind') == 'MISSING_REFERENCE']
        manifest = load(run_dir / 'run_manifest.json')
        discovery = {
            'schema': 'general_document.meeting_reference_discovery/0.1',
            'rule': 'GENERAL_DOCUMENT_MEETING_REFERENCE_V01',
            'project': project, 'run_id': run_id,
            'status_date': args.status_date,
            'source_workbook_sha256_at_run_start': (manifest.get('workbook') or {}).get('sha256_at_run_start'),
            'prior_board_to_log_sha256': hashlib.sha256((history / 'board_to_log.json').read_bytes()).hexdigest(),
            'prior_missing_reference_count': prior_count,
            'recovered_count': len(recovered),
            'still_unmatched_count': len(unmatched),
            'remaining_missing_reference_count': len(unmatched_other),
            'record_count_before': len(before.get('records') or []),
            'record_count_after': len(after.get('records') or []),
            'recovered_evidence': recovered,
            'unmatched_previous_issues': unmatched,
            'remaining_reference_issues': unmatched_other,
            'all_meeting_reference_observations': observations,
            'prior_issue_archive': str(history),
            'state': 'VERIFIED' if not unmatched and len(before.get('records') or []) == len(after.get('records') or []) else 'INVESTIGATION_REQUIRED',
        }
        output = run_dir / 'meeting_reference_discovery.json'
        if output.exists():
            shutil.copy2(output, history / 'prior_meeting_reference_discovery.json')
        write(output, discovery)
        print(f'[DISCOVERY] {project}: recovered {len(recovered)}/{prior_count} prior MISSING_REFERENCE; current missing={len(unmatched_other)}')
        print(f'[EVIDENCE] {output}')
        if discovery['state'] != 'VERIFIED':
            print('[STOP] Discovery reconciliation not complete; inspect unmatched issues and record counts.')
            return 2
    print('[COMPLETE] BFG and NKH replayed; original meeting observations and prior issues remain discoverable.')
    return 0

if __name__ == '__main__':
    sys.exit(main())
