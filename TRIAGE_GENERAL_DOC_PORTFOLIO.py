#!/usr/bin/env python3
"""Read-only triage of an existing GENERAL_DOCUMENT portfolio audit.

Prints why each project paused and separates current project-team issues
from historical, reviewed and corrected evidence. Does not rerun Cleaner.
"""
from __future__ import annotations
import argparse
import csv
import json
from collections import Counter
from pathlib import Path

CODES = ('AZD', 'JND', 'FSH', 'YSK', 'EYV', 'BFG', 'NKH', 'NGN')


def read_json(path: Path) -> dict:
    try:
        obj = json.loads(path.read_text(encoding='utf-8-sig'))
        return obj if isinstance(obj, dict) else {}
    except (FileNotFoundError, ValueError):
        return {}


def read_csv(path: Path) -> tuple[list[dict], list[str]]:
    if not path.is_file():
        raise FileNotFoundError(f'Required audit export missing: {path}')
    with path.open('r', encoding='utf-8-sig', newline='') as fh:
        reader = csv.DictReader(fh)
        return list(reader), list(reader.fieldnames or [])


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open('w', encoding='utf-8-sig', newline='') as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


def disposition(row: dict) -> str:
    state = str(row.get('exception_state') or '').upper().strip()
    if state.startswith('OPEN') or state in ('REVIEW_PENDING', 'INVESTIGATE', 'NEEDS_REVIEW', 'REVIEW_REQUIRED'):
        return 'CURRENT_TEAM_ACTION'
    if state in ('HISTORICAL_CORRECTION', 'REVIEW_DECIDED', 'REVIEWED_IN_STATE') or 'ACCEPTED' in state or 'RESOLVED' in state:
        return 'HISTORY_OR_REVIEWED'
    return 'TRIAGE_UNCLASSIFIED'  # never silently drop unknown states


def run_audit(repo: Path, audit_dir: Path) -> dict:
    if not audit_dir.is_dir():
        raise FileNotFoundError(f'Audit folder not found: {audit_dir}')
    summaries, _ = read_csv(audit_dir / 'portfolio_summary.csv')
    exceptions, fields = read_csv(audit_dir / 'exception_register.csv')
    statuses = {r.get('project', ''): r for r in summaries}
    pause_rows = []
    for project in CODES:
        s = statuses.get(project, {})
        run_id = s.get('run_id', '')
        progress = read_json(repo / 'runs' / run_id / 'general_doc_auto_progress.json') if run_id else {}
        logpath = audit_dir / f'{project}_pipeline.txt'
        lines = logpath.read_text(encoding='utf-8', errors='replace').splitlines() if logpath.is_file() else []
        gate = next((l.strip() for l in reversed(lines) if '[REVIEW REQUIRED]' in l or '[ERROR]' in l), '')
        pstate = str(s.get('execution') or '')
        if pstate not in ('REVIEW_REQUIRED', 'RUN_ERROR', 'SOURCE_DRIFT', 'WORKBOOK_DRIFT', 'BLOCKED_TEST_FAILURE', 'MISSING_WORKING_COPY'):
            continue
        stage = str(progress.get('pause_stage') or '')
        reason = str(progress.get('note') or progress.get('error') or '')
        if not reason and gate:
            reason = gate
        pause_rows.append({
            'project': project,
            'run_id': run_id,
            'execution': pstate,
            'review_stage': stage,
            'review_count': progress.get('review_count', ''),
            'reason': reason,
            'log_review_gate': gate,
            'run_log': str(logpath) if logpath.is_file() else '',
            'resumption_command': (
                f'py .\\RUN_GENERAL_DOCUMENT_V05.py --project {project} '
                f'--run-id "{run_id}" --status-date 1405/07/22'
                if run_id and pstate == 'REVIEW_REQUIRED' else ''
            ),
        })
    buckets = {'CURRENT_TEAM_ACTION': [], 'HISTORY_OR_REVIEWED': [], 'TRIAGE_UNCLASSIFIED': []}
    for case in exceptions:
        buckets[disposition(case)].append(case)
    write_csv(audit_dir / 'project_review_gates.csv', pause_rows,
              ['project', 'run_id', 'execution', 'review_stage', 'review_count', 'reason',
               'log_review_gate', 'run_log', 'resumption_command'])
    for kind, filename in [
        ('CURRENT_TEAM_ACTION', 'project_team_action_list.csv'),
        ('HISTORY_OR_REVIEWED', 'historical_reviewed_evidence.csv'),
        ('TRIAGE_UNCLASSIFIED', 'unclassified_exception_states.csv'),
    ]:
        write_csv(audit_dir / filename, buckets[kind], fields)
    counter = Counter((r.get('project', ''), r.get('exception_state', '')) for r in buckets['CURRENT_TEAM_ACTION'])
    md = ['# GENERAL_DOCUMENT — Audit triage', '',
          'Based strictly on the portfolio audit output. This is not business approval.', '',
          f"Audit folder: `{audit_dir}`", '',
          '## Processing state', '',
          '| Project | Execution | Review stage | Reason |', '|---|---|---|---|']
    by_pause = {r['project']: r for r in pause_rows}
    for project in CODES:
        s = statuses.get(project, {})
        p = by_pause.get(project, {})
        reason = str(p.get('reason') or p.get('log_review_gate') or '')
        md.append('| ' + ' | '.join(x.replace('|', '/') for x in
                    (project, str(s.get('execution') or 'NOT_REPORTED'), str(p.get('review_stage') or ''), reason[:240])) + ' |')
    md += ['', '## Exception register dispositions', '',
           '| Disposition | Rows |', '|---|---:|']
    for label in ('CURRENT_TEAM_ACTION', 'HISTORY_OR_REVIEWED', 'TRIAGE_UNCLASSIFIED'):
        md.append(f'| {label} | {len(buckets[label])} |')
    md += ['', '## Current team actions by project and state', '',
           '| Project | State | Entries |', '|---|---|---:|']
    for (project, state), count in sorted(counter.items()):
        md.append(f'| {project} | {state} | {count} |')
    md += ['', 'Historical/reviewed cases remain in the register for discovery and audit.',
           'Unclassified states are NOT presumed resolved. Inspect that CSV before publishing the team list.',
           'Coverage success and acknowledged diagnostics do not imply final business sign-off.', '']
    (audit_dir / 'PORTFOLIO_TRIAGE.md').write_text('\n'.join(md), encoding='utf-8')
    return {'paused': pause_rows, 'counts': {k: len(v) for k, v in buckets.items()}, 'audit_dir': audit_dir}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--audit-dir', help='Existing portfolio_..._RUN folder. Defaults to most recent RUN.')
    args = ap.parse_args()
    repo = Path(__file__).resolve().parent
    if args.audit_dir:
        audit_dir = Path(args.audit_dir)
        if not audit_dir.is_absolute():
            audit_dir = repo / audit_dir
    else:
        audit_dirs = sorted((repo / 'portfolio_audits').glob('portfolio_*_RUN'))
        if not audit_dirs:
            ap.error('No previous RUN audit found; provide --audit-dir')
        audit_dir = audit_dirs[-1]
    try:
        result = run_audit(repo, audit_dir)
    except (FileNotFoundError, OSError, ValueError) as exc:
        print(f'[ERROR] {exc}')
        return 1
    print(f'[AUDIT] {result["audit_dir"]}')
    for row in result['paused']:
        reason = row['reason'] or row['log_review_gate'] or 'Check recorded run log'
        print(f'[PAUSED] {row["project"]} {row["review_stage"] or "UNKNOWN_STAGE"}: {reason}')
    print('[EXCEPTIONS] ' + ', '.join(f'{k}={v}' for k, v in result['counts'].items()))
    print('[FILES] project_review_gates.csv; project_team_action_list.csv; '
          'historical_reviewed_evidence.csv; unclassified_exception_states.csv; PORTFOLIO_TRIAGE.md')
    print('[SAFE] No Cleaner stages rerun; no source, working, or run artifact edited')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
