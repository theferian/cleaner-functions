"""Guarded fix: include every transactional document in correspondence audit.

Run from cleaner-functions root:
    python install_correspondence_audit_coverage_v01.py --check
    python install_correspondence_audit_coverage_v01.py --apply
"""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import shutil
import sys

SOURCE_REL = Path('functions/engineering_control/three_lists.py')
TEST_REL = Path('unit_tests/test_correspondence_reconstruction.py')
TASK_REL = Path('docs/DEMO_TASK_LIST.md')
OLD_CONDITION = 'if reconstruction.representations or reconstruction.overlaps or reconstruction.possible_links:'
NEW_CONDITION = 'if doc_records:'

TEST_NAME = 'def test_audit_covers_all_transactional_documents_even_without_links():'
TEST = '''\n\ndef test_audit_covers_all_transactional_documents_even_without_links():
    from functions.engineering_control.three_lists import build_three_engineering_lists

    records = [
        rec(side="send", date="1405/01/01", ref="OUT-1", idx=1),
        rec(side="receive", date="1405/01/03", ref="IN-2", status="CM", idx=2),
    ]
    inventory = [
        {"source_sheet": "230KV SS", "document_index": n,
         "doc_name": f"DOC-{n}", "doc_wbs": f"1.{n}"}
        for n in (1, 2, 3)
    ]
    result = build_three_engineering_lists(
        records, status_date="1405/01/10", document_inventory=inventory,
    )
    audit = result.to_dict()["correspondence_audit"]
    by_index = {x["document_index"]: x for x in audit}
    assert set(by_index) == {1, 2}
    assert by_index[1]["raw_events"] == 1
    assert by_index[2]["raw_events"] == 1
    assert by_index[1]["canonical_events"] == 1
    assert by_index[2]["canonical_events"] == 1
    assert by_index[1]["possible_source_slot_links"] == []
    assert by_index[2]["possible_source_slot_links"] == []
    assert by_index[1]["overlapping_submission_groups"] == []
    assert by_index[2]["overlapping_submission_groups"] == []
'''


def read(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()
    line_ending = '\r\n' if b'\r\n' in raw else '\n'
    return raw.decode('utf-8-sig').replace('\r\n', '\n'), line_ending


def data(text: str, ending: str) -> bytes:
    return text.replace('\n', ending).encode('utf-8')


def prepare(root: Path) -> dict[Path, bytes]:
    src, test = root / SOURCE_REL, root / TEST_REL
    if not src.is_file() or not test.is_file():
        raise RuntimeError('Cannot locate current three_lists.py and test_correspondence_reconstruction.py')
    changes = {}
    source, nl = read(src)
    if source.count(OLD_CONDITION) == 1:
        source = source.replace(OLD_CONDITION, NEW_CONDITION, 1)
    elif OLD_CONDITION not in source and source.count('        ' + NEW_CONDITION) == 1:
        pass
    else:
        raise RuntimeError('Expected unique audit inclusion condition missing/ambiguous; no files changed')
    if source.count('result.correspondence_audit.append({**identity, **reconstruction.to_dict()})') != 1:
        raise RuntimeError('Expected reconstruction audit append anchor missing/ambiguous')
    changes[src] = data(source, nl)

    tests, nl = read(test)
    if TEST_NAME not in tests:
        if tests.count('def rec(') != 1:
            raise RuntimeError('Test helper has changed; no files changed')
        tests = tests.rstrip('\n') + TEST + '\n'
    changes[test] = data(tests, nl)

    task = root / TASK_REL
    marker = '- [x] 4A.11c Include every transactional document in correspondence audit'
    if task.exists():
        tasks, nl = read(task)
        if marker not in tasks:
            tasks = tasks.rstrip('\n') + '\n' + marker + '\n'
        changes[task] = data(tasks, nl)
    else:
        changes[task] = ('# Cleaner development tasks\n\n' + marker + '\n').encode('utf-8')
    return changes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check', action='store_true')
    mode.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    root = Path.cwd().resolve()
    try:
        changes = prepare(root)
    except Exception as exc:
        print('[STOP]', exc)
        return 2
    modified = [p for p, content in changes.items()
                if not p.exists() or p.read_bytes() != content]
    print('[READY] Validated correspondence audit coverage update.')
    for p in changes:
        print('  ', p.relative_to(root))
    if args.check:
        print('[CHECK] Changes required:', len(modified))
        return 0
    if not modified:
        print('[UNCHANGED] Already applied')
        return 0
    stamp = datetime.now().strftime('%Y%m%dT%H%M%S')
    backups = root.parent / '.cleaner_audit_backups' / root.name / stamp
    for p in modified:
        if p.exists():
            dst = backups / p.relative_to(root)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dst)
    for p in modified:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(changes[p])
    print('[APPLIED] Complete transactional-document audit entries enabled.')
    print('[BACKUP]', backups)
    print('[NEXT] python -m pytest -q unit_tests')
    return 0


if __name__ == '__main__':
    sys.exit(main())
