r"""Install guarded correspondence correction replay; run from Cleaner repo root.

Windows CMD:
    python .\install_guarded_correspondence_replay_v01.py --check
    python .\install_guarded_correspondence_replay_v01.py --apply
"""
from __future__ import annotations

import argparse
import ast
from datetime import datetime
from pathlib import Path
import shutil

ROOT = Path.cwd()
PKG = Path(__file__).resolve().parent
MODULE = Path('cleaner_core/correspondence_replay.py')
TESTS = Path('unit_tests/test_correspondence_replay.py')
PIPELINE = Path('functions/cleaner/azd_pipeline.py')
TASKS = Path('docs/DEMO_TASK_LIST.md')

IMPORT_ANCHOR = 'from review.queue import build_review_queue, write_review_queue\n'
IMPORT_ADDITION = (
    'from cleaner_core.correspondence_replay import replay_approved_correspondence_corrections\n'
    'from cleaner_core.contracts import Finding\n'
)
HOOK_ANCHOR = '    snap = load_snapshot(snapshot_path)\n    try:\n        findings = run_stage(\n'
HOOK_REPLACEMENT = '''    snap = load_snapshot(snapshot_path)
    try:
        if stage_id == "FIELD_VALIDATION":
            replay_report = replay_approved_correspondence_corrections(
                run_dir, project_solutions, state
            )
            replay_path = run_dir / "correspondence_replay_report.json"
            replay_path.write_text(
                json.dumps(replay_report, ensure_ascii=False, indent=2, default=str) + "\\n",
                encoding="utf-8",
            )
            stage_artifacts["correspondence_replay"] = str(replay_path)
            counts = replay_report["summary"]
            logger(
                "REPLAY",
                "Approved correspondence corrections: "
                + ", ".join(f"{key}={value}" for key, value in counts.items()),
            )
            if counts.get("NEEDS_REVIEW", 0):
                logger("REPLAY", "Unresolved correspondence repairs require review before publishing.")
        findings = run_stage(
'''
AFTER_RUN_ANCHOR = '''        findings = run_stage(
            stage_id=stage_id,
            snapshot=snap,
            profile=profile,
            state=state,
            logger=logger,
        )
        resolved_snapshot, resolved_profile = build_resolved_context(snap, profile, state)
'''
AFTER_RUN_REPLACEMENT = '''        findings = run_stage(
            stage_id=stage_id,
            snapshot=snap,
            profile=profile,
            state=state,
            logger=logger,
        )
        if stage_id == "FIELD_VALIDATION":
            for issue in replay_report["results"]:
                if issue.get("result") != "NEEDS_REVIEW":
                    continue
                findings.append(Finding(
                    test_id="CORRESPONDENCE_REPLAY",
                    status="FAIL",
                    severity="HIGH",
                    sheet=issue.get("sheet"),
                    target=issue.get("target"),
                    message=(
                        "Approved correspondence correction could not be safely replayed: "
                        + str(issue.get("reason"))
                    ),
                    expected="Verified document/letter/date/response identity",
                    observed=issue.get("observed"),
                    evidence=dict(issue),
                    suggested_fix=None,
                ))
        resolved_snapshot, resolved_profile = build_resolved_context(snap, profile, state)
'''
TASK_MARKER = '### Guarded correspondence replay (4A.13b)'
TASK_APPEND = '''
### Guarded correspondence replay (4A.13b)

- [ ] 4A.13b Install and live-verify approved correspondence correction replay on a new Cleaner run.
- [ ] 4A.13c Generalize invalid chronology review → human-approved correction → evidence-linked replay.
- [ ] 4A.13d Re-run complete AZD data validation, logbook, audit and three-list consistency checks.
- [ ] 4A.11 Reconstruct overlapping correspondence and repeated letters without miscounting.
'''


def load(path: Path):
    raw = path.read_bytes()
    nl = '\r\n' if b'\r\n' in raw else '\n'
    return raw.decode('utf-8-sig').replace('\r\n', '\n'), nl


def content(text: str, nl: str):
    return text.replace('\n', nl).encode('utf-8')


def prepare():
    changes = {}
    for path in (MODULE, TESTS):
        src = PKG / 'payload' / path
        if not src.exists():
            raise RuntimeError(f'Missing installer payload: {src}')
        if (ROOT / path).exists():
            if (ROOT / path).read_bytes() != src.read_bytes():
                raise RuntimeError(f'Refusing to overwrite a different existing file: {path}')
        else:
            changes[path] = src.read_bytes()

    dst = ROOT / PIPELINE
    if not dst.is_file():
        raise RuntimeError(f'Cleaner pipeline not found: {dst}')
    text, nl = load(dst)
    marker = 'if stage_id == "FIELD_VALIDATION":\n            replay_report = '
    if marker in text:
        if IMPORT_ADDITION not in text:
            raise RuntimeError('Partial integration found; inspect the live pipeline before retrying')
    else:
        pairs = [(IMPORT_ANCHOR, IMPORT_ADDITION + IMPORT_ANCHOR),
                 (HOOK_ANCHOR, HOOK_REPLACEMENT),
                 (AFTER_RUN_ANCHOR, AFTER_RUN_REPLACEMENT)]
        for key, replacement in pairs:
            if text.count(key) != 1:
                raise RuntimeError(f'Expected one pipeline anchor, found {text.count(key)}: {key[:64]!r}')
            text = text.replace(key, replacement, 1)
        ast.parse(text, filename=str(PIPELINE))
        changes[PIPELINE] = content(text, nl)

    tasks_path = ROOT / TASKS
    if tasks_path.exists():
        text, nl = load(tasks_path)
        if TASK_MARKER not in text:
            changes[TASKS] = content(text.rstrip() + '\n' + TASK_APPEND, nl)
    else:
        changes[TASKS] = content('# Cleaner worklist\n' + TASK_APPEND, '\n')

    return changes


def main():
    p = argparse.ArgumentParser(description=__doc__)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check', action='store_true')
    mode.add_argument('--apply', action='store_true')
    args = p.parse_args()

    try:
        changes = prepare()
    except Exception as exc:
        print('[STOP]', exc)
        return 2
    print('[READY] Anchors verified; existing code preserved.')
    for name in changes:
        print('  ', name)
    if args.check or not changes:
        return 0
    backup = ROOT.parent / '.cleaner_replay_backups' / ROOT.name / datetime.now().strftime('%Y%m%dT%H%M%S')
    for path in changes:
        target = ROOT / path
        if target.exists():
            dest = backup / path
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, dest)
    for path, raw in changes.items():
        target = ROOT / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    print('[APPLIED] guarded correspondence replay installed.')
    print('[BACKUP]', backup)
    print('[NEXT] python -m pytest -q unit_tests')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
