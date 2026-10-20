# Cleaner Task 4A.11c — Complete correspondence audit coverage

## Verified reason for 179 vs 187

The original AZD General Document Logbook contains 792 transaction records in 187 `(source_sheet, document_index)` groups. The current `build_three_engineering_lists` implementation appends an entry to `correspondence_audit` **only when** a reconstruction detects repeated representations, overlaps, or source-slot candidates. Exactly eight other documents have no matching signal and are left out of the *audit list*, not out of the Logbook.

The eight records excluded by the old predicate are:
- 230KV SS #1, LIST OF DOCUMENT
- 230KV SS #153, SITE PLAN
- 63KV SS #7, MODIFICATION OF ALARM & SIGNAL LIST DIAGRAM
- 63KV SS #13, MODIFICATION OF CONTROL SCHEMATIC DIAGRAM
- 63KV SS #14, PROTECTION SCHEMATIC DIAGRAM
- 63KV SS #55, GEOTECHNICAL
- LINE #17, INSPECTION AND TEST PLAN/QUALITY CONTROL PLAN FOR STRANDED CONDUCTORS
- LINE #19, INSPECTION AND TEST PLAN/QUALITY CONTROL PLAN FOR STRING INSULATOR (15KM)

## Change

Use `if doc_records:` rather than `if reconstruction.representations or reconstruction.overlaps or reconstruction.possible_links:` to append `correspondence_audit`. This adds information only; **it does not modify event history, relationship inference, delays, status semantics, or list membership**. The document inventory entries with *zero transactions* continue to be handled by the `Not Sent` classification, without being misrepresented as transactional audit documents.

A new unit regression checks single SEND and single RECEIVE documents are included, and inventory-only documents remain excluded.

## Apply to live Windows CMD repository

Extract `install_correspondence_audit_coverage_v01.py` to the `cleaner-functions` root:

```bat
python .\install_correspondence_audit_coverage_v01.py --check
python .\install_correspondence_audit_coverage_v01.py --apply
python -m pytest -q unit_tests
git diff --check -- functions/engineering_control/three_lists.py unit_tests/test_correspondence_reconstruction.py
```

Backups of any changed existing files are saved in the sibling folder `.cleaner_audit_backups` outside the repository. The patcher checks all anchors in memory before writing and can be run again safely.

Then close Excel copies of active CSVs and regenerate:

```bat
python .\pipeline\weekly_report_pipeline.py engineering-lists --run-dir "runs\azd_20261014T071802" --project AZD --status-date 1405/07/22
```

Verify:

```bat
python -c "import json,collections; p=r'runs\azd_20261014T071802\engineering_lists\engineering_three_lists.json';d=json.load(open(p,encoding='utf-8'));a=d.get('correspondence_audit',[]);print('Audit documents:',len(a));print('Raw events:',sum(x['raw_events'] for x in a));print('Duplicate representations:',sum(x['duplicate_representation_count'] for x in a));print('Lists:',{k:len(v) for k,v in d['lists'].items()})"
```

Expected for unchanged AZD source artifacts: 187 audit entries, 792 raw events, 1 duplicate representation. Three-list counts should remain 43 Not Sent, 45 Company Delay, and 9 Consultant Delay. All counts are expected values, not claims of live verification.

## Archived validation

The patch was installed twice (second check: zero changes) in an archived Cleaner snapshot. The unit test suite passed: 162 passed. Your live baseline is 196 tests; the live validation has not yet been run.

## Separate follow-on task 4A.12

The 386 source-slot SEND/RECEIVE links are **candidates**. Confirmed/inferred/unresolved relationship policies must remain a separate evidence-backed implementation with regression tests; do not let candidate slot links assert correspondence pairing automatically.
