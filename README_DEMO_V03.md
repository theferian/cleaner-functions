# Multi-project engineering demonstration V03

Extract into the cleaner-functions repository root. Replace DEMO_ALL_GENERAL_DOCS.py;
add RUN_GENERAL_DOCUMENT_BATCH_V03.py. Keep your existing configuration,
RUN_GENERAL_DOCUMENT_V06.py, Cleaner modules, knowledge, and runs.

Run from Windows CMD:

```bat
py tests\test_demo_batch_v03.py
py DEMO_ALL_GENERAL_DOCS.py --status-date 1405/07/30 --batch DEMO_14050730
start "" "demo_review\DEMO_14050730\index.html"
```

This resumes existing source snapshots and run IDs. Use a new batch ID to retrieve
sources afresh. New snapshots have retrieval timestamps in their filenames;
existing run-bound filenames stay intact so earlier runs remain resumable.
Old document content remains included. Retrieval time does not certify document age.

## One review location

- index.html: sources, project statuses, lists, evidence links, review register.
- projects/PROJECT/source/: unchanged source snapshot.
- projects/PROJECT/outputs/: the three canonical engineering CSVs and report JSON.
- projects/PROJECT/evidence/: complete run directory, including nested audits,
  coverage workbooks, queues, decisions, console history, and FILES.csv index.
- ALL_01_Not_Sent.csv, ALL_02_Company_Delay.csv,
  ALL_03_Consultant_Delay.csv: consolidated rows with project and source provenance.
- REVIEW_REQUIRED.csv/json: open pipeline gates and source actions, plus queue
  evidence. QUEUE_EVIDENCE includes historical findings and is not an unresolved
  finding count; inspect its matching decisions in the evidence directory.
- PROJECT_STATUS.csv, SOURCE_INVENTORY.csv, ALL_Diagnostics.csv,
  portfolio_manifest.json: processing state and provenance.

## Calculation and review

V03 calls existing V06 stages and existing engineering-list calculations; it does
not replace their business rules or manufacture acceptance decisions. V06's
existing complete decisions are reused. There is no new automatic rule learner.

After structural stages succeed, Board/Log, Coverage and Engineering review gates
are recorded and deferred so dependent calculations can finish. Reports with
unresolved issues are explicitly PROVISIONAL_REVIEW_PENDING. Coverage gaps can
make these reports incomplete: they are useful review outputs, not a certified
complete account of every source document.

An unresolved structural gate blocks extraction because locations/identities are
not reliable. Its reason and available queue evidence appear in the review
register. Missing calculations are blank, never represented as zero. A source
retrieval failure or calculation error stays explicit and other projects continue.

To correct a blocked project using the established interactive reviewer:

```bat
py DEMO_ALL_GENERAL_DOCS.py --status-date 1405/07/30 --batch DEMO_14050730 --review NGN
```

Then rerun the batch command to calculate and consolidate all available outputs.
Interactive review still uses V06's existing stage-by-stage workflow. No source
workbooks are automatically edited by this batch adapter.

## Validation and limits

Six stdlib unittest checks pass: deferred reviews, structural dependencies, hard
errors, nested evidence and combined lists, missing-versus-zero, snapshot integrity.
These exercise orchestration with simulated Cleaner interfaces, not real report
correctness. The supplied demo ZIP contains only NGN's retrieved workbook and
partial run evidence, not the current full Cleaner repository or the missing
FIELD_VALIDATION queue. Live Windows/network calculations remain unverified.

Requires the existing V06 runner interface from 17 October 2026, existing pipeline
commands, and DEMO_ALL_GENERAL_DOCS_CONFIG.json from the earlier installation.
BFG and NKH must remain separately configured; this patch preserves your registry.
