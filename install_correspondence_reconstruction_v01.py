"""Guarded, idempotent Cleaner correspondence reconstruction installer.

Run in the project root. --check makes no changes. --apply validates *every*
anchor and the supplied module/test syntax before touching the project.
"""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import ast
import shutil
import sys

ROOT = Path.cwd()
PAYLOAD = Path(__file__).resolve().parent
ENGINE = ROOT / 'functions/engineering_control/three_lists.py'
CORE = ROOT / 'cleaner_core/correspondence_reconstruction.py'
TESTS = ROOT / 'unit_tests/test_correspondence_reconstruction.py'
TASKS = ROOT / 'docs/DEMO_TASK_LIST.md'

IMPORT = 'from cleaner_core.correspondence_reconstruction import reconstruct_correspondence\n'
ENGINE_IMPORT_ANCHOR = 'from functions.board_to_log.contracts import LogRecord\n'
FIELD = '    correspondence_audit: list[dict[str, Any]] = field(default_factory=list)\n'
FIELD_ANCHOR = '    diagnostics: list[dict[str, Any]] = field(default_factory=list)\n'
OUTPUT = '            "correspondence_audit": list(self.correspondence_audit),\n'
OUTPUT_ANCHOR = '            "diagnostics": list(self.diagnostics),\n'
CALL_ANCHOR = '''        doc_records = grouped.get(key, [])
        ordered, chronology_issues = _order_events_chronologically(
            doc_records, status_date=status_date
        )
'''
CALL_UPDATED = '''        doc_records = grouped.get(key, [])
        reconstruction = reconstruct_correspondence(
            doc_records, status_library=status_library
        )
        ordered, chronology_issues = _order_events_chronologically(
            reconstruction.events, status_date=status_date
        )
'''
AUDIT_ANCHOR = '        result.diagnostics.extend({**identity, **issue} for issue in chronology_issues)\n'
AUDIT_BLOCK = '''        result.diagnostics.extend({**identity, **issue} for issue in chronology_issues)
        if reconstruction.representations or reconstruction.overlaps or reconstruction.possible_links:
            result.correspondence_audit.append({**identity, **reconstruction.to_dict()})
        result.diagnostics.extend({**identity, **issue} for issue in reconstruction.diagnostics)
'''
TASK_APPEND = '''
## Cleaner correspondence reconstruction (development phase)

- [x] 4A.13b Guarded replay of previously approved date corrections
- [x] 4A.11 Implement exact-letter correspondence reconstruction + provenance
- [ ] 4A.11b Run live AZD comparison; inspect letter-reference conflicts
- [ ] 4A.12 Cross-project regression and evidence-linking review
- [ ] 4A.13c Generic correction approval and solution replay workflow
- [ ] 4A.13d Regenerate and validate Logbook, Coverage, Engineering Lists
'''


def _read(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()
    return raw.decode('utf-8-sig').replace('\r\n', '\n'), '\r\n' if b'\r\n' in raw else '\n'


def _encode(text: str, newline: str) -> bytes:
    return text.replace('\n', newline).encode('utf-8')


def _add_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    n = text.count(old)
    if n != 1:
        raise ValueError(f'{label}: required single exact anchor not found (count={n})')
    return text.replace(old, new, 1)


def prepare() -> dict[Path, bytes]:
    if not ENGINE.is_file():
        raise ValueError(f'Not a Cleaner repository root: {ENGINE} missing')
    if 'def _order_events_chronologically(' not in ENGINE.read_text(encoding='utf-8-sig'):
        raise ValueError('Chronology patch missing; refusing unsafe integration')
    for fn in ('correspondence_reconstruction.py', 'test_correspondence_reconstruction.py'):
        if not (PAYLOAD / fn).is_file():
            raise ValueError(f'Payload missing: {fn}')

    current, nl = _read(ENGINE)
    updated = _add_once(current, ENGINE_IMPORT_ANCHOR,
                        IMPORT + ENGINE_IMPORT_ANCHOR, 'module import')
    updated = _add_once(updated, FIELD_ANCHOR, FIELD_ANCHOR + FIELD,
                        'audit dataclass field')
    updated = _add_once(updated, OUTPUT_ANCHOR, OUTPUT + OUTPUT_ANCHOR,
                        'audit JSON output')
    updated = _add_once(updated, CALL_ANCHOR, CALL_UPDATED,
                        'reconstruction integration')
    updated = _add_once(updated, AUDIT_ANCHOR, AUDIT_BLOCK,
                        'audit/diagnostics integration')
    ast.parse(updated, filename=str(ENGINE))
    module_bytes = (PAYLOAD / 'correspondence_reconstruction.py').read_bytes()
    tests_bytes = (PAYLOAD / 'test_correspondence_reconstruction.py').read_bytes()
    ast.parse(module_bytes.decode('utf-8'), filename=str(CORE))
    ast.parse(tests_bytes.decode('utf-8'), filename=str(TESTS))

    # Do not overwrite unknown preexisting implementations.
    for target, data in ((CORE, module_bytes), (TESTS, tests_bytes)):
        if target.is_file() and target.read_bytes() != data:
            raise ValueError(f'{target}: exists with differing content; manual reconciliation required')

    output = {ENGINE: _encode(updated, nl), CORE: module_bytes, TESTS: tests_bytes}
    if TASKS.is_file():
        existing, eol = _read(TASKS)
        if '4A.11 Implement exact-letter correspondence reconstruction' not in existing:
            existing = existing.rstrip() + '\n' + TASK_APPEND + '\n'
        output[TASKS] = _encode(existing, eol)
    else:
        output[TASKS] = ('# Cleaner Development Tasks\n' + TASK_APPEND).encode('utf-8')
    return output


def main() -> int:
    ap = argparse.ArgumentParser()
    action = ap.add_mutually_exclusive_group(required=True)
    action.add_argument('--check', action='store_true')
    action.add_argument('--apply', action='store_true')
    args = ap.parse_args()
    try:
        plan = prepare()
    except Exception as exc:
        print('[STOP] No files changed:', exc)
        return 2
    changed = {k:v for k,v in plan.items() if not k.is_file() or k.read_bytes() != v}
    print('[READY] Validated reconstruction integration and test syntax.')
    for target in changed:
        print('  ', target.relative_to(ROOT))
    if args.check:
        return 0
    if not changed:
        print('[OK] Already installed; nothing to change')
        return 0
    backup = ROOT.parent / '.cleaner_correspondence_backups' / ROOT.name / datetime.now().strftime('%Y%m%dT%H%M%S')
    for target in changed:
        if target.is_file():
            destination = backup / target.relative_to(ROOT)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, destination)
    for target,data in changed.items():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    print('[APPLIED] Correspondence reconstruction integrated.')
    print('[BACKUP]', backup)
    print('[NEXT] python -m pytest -q unit_tests')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
