# Visual Coverage Audit

The coverage audit is a final QA artifact. It creates a **copy** of the source workbook, applies reviewed Cleaner fixes to that copy, writes the validated canonical Logbook, and colours every non-empty mapped source slot according to whether its information reached the Logbook.

The original workbook is never coloured or saved.

## Legend

- `CAPTURED_TRANSACTION` — green: transaction content emitted into the Logbook.
- `CAPTURED_NARRATIVE` — blue: narrative receive content emitted losslessly.
- `CAPTURED_IDENTITY` — grey: document identity used by the Logbook.
- `UNRESOLVED_ISSUE` — orange/red: unresolved Board→Log source issue.
- `SCANNED_NOT_RETRIEVED` — yellow: Cleaner mapped a non-empty slot but Board→Log did not emit it into a canonical field.

The audit workbook contains a `Coverage_Audit` legend sheet and the run folder receives `coverage_audit.json` with counts by sheet and classification.

Yellow cells are the main completeness-review queue. They may be legitimate explanatory text, or they may expose a missing extraction rule. The visual audit deliberately does not decide that automatically.

## CLI

```bash
python ./pipeline/weekly_report_pipeline.py audit-coverage \
  --run-dir ./runs/<RUN_ID> \
  --project AZD \
  --overwrite
```

The default output name is `<SOURCE>_COVERAGE_AUDIT.xlsx` (or `.xlsm` when the source is macro-enabled).
