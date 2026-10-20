"""Repair one synthetic regression fixture after correspondence reconstruction.

Usage from cleaner-functions root:
  python fix_correspondence_test_fixture_v01.py --check
  python fix_correspondence_test_fixture_v01.py --apply

No production code, project profiles, exceptions, or solutions are modified.
"""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import shutil
import sys

TEST_PATH = Path('unit_tests/test_engineering_three_lists.py')
FUNCTION = 'def test_latest_closed_revision_overrides_older_open_revision():'
ANCHOR = '    result = build_three_engineering_lists(\n'
MARKER = '# DISTINCT_LETTER_REFERENCES_PER_REVISION'
REPLACEMENT = '''    # DISTINCT_LETTER_REFERENCES_PER_REVISION
    # The rec() helper defaults to REF/RESP for every revision. That creates
    # legitimate same-reference conflicts across different dates/statuses.
    # This test checks closure across distinct revision correspondence.
    from dataclasses import replace
    records = [
        replace(record, letter_reference=f"{record.letter_reference}-{record.doc_rev}")
        for record in records
    ]

''' + ANCHOR


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check', action='store_true')
    mode.add_argument('--apply', action='store_true')
    args = parser.parse_args()

    root = Path.cwd()
    path = root / TEST_PATH
    if not path.is_file():
        print(f'[STOP] Missing test file: {path}')
        return 2
    raw = path.read_bytes()
    newline = '\r\n' if b'\r\n' in raw else '\n'
    text = raw.decode('utf-8-sig').replace('\r\n', '\n')
    if text.count(FUNCTION) != 1:
        print(f'[STOP] Expected one {FUNCTION} but found {text.count(FUNCTION)}')
        return 2
    head, body = text.split(FUNCTION, 1)
    next_test = body.find('\ndef test_')
    if next_test >= 0:
        target, tail = body[:next_test], body[next_test:]
    else:
        target, tail = body, ''
    if MARKER in target:
        print('[OK] Test fixture already uses distinct letter references; no change needed.')
        return 0
    if target.count(ANCHOR) != 1:
        print(f'[STOP] Test call anchor mismatch: {target.count(ANCHOR)}; no change made.')
        return 2
    if '    records = [\n' not in target or 'assert not result.diagnostics' not in target:
        print('[STOP] Test structure differs; no change made.')
        return 2
    updated = head + FUNCTION + target.replace(ANCHOR, REPLACEMENT, 1) + tail
    compile(updated, str(path), 'exec')
    if args.check:
        print('[READY] One fixture-only edit: unit_tests/test_engineering_three_lists.py')
        print('[UNCHANGED] Production code and correspondence conflict detection')
        return 0
    backup_root = root.parent / '.cleaner_fixture_backups' / root.name / datetime.now().strftime('%Y%m%dT%H%M%S')
    backup = backup_root / TEST_PATH
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, backup)
    path.write_bytes(updated.replace('\n', newline).encode('utf-8'))
    print('[APPLIED] Distinct SEND/RECEIVE references per revision in one test.')
    print('[BACKUP]', backup)
    print('[NEXT] python -m pytest -q unit_tests')
    return 0


if __name__ == '__main__':
    sys.exit(main())
