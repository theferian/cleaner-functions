# Board→Log

## Purpose

Convert the reviewed semantic output of Cleaner into a canonical transaction log.

## Input contract

A Cleaner run must provide:

```text
document_regions.json
card_maps.json
slot_schema.json
resolved_state.json
run_manifest.json
```

`functions.cleaner.finalize_run()` ingests a fully-reviewed final stage decision
file when necessary. This is important for IDENTIFIERS because there is no later
Cleaner stage that would otherwise ingest its decisions.

## Extraction model

For every Cleaner card:

1. use DocumentRegion for document identity;
2. apply resolved-state value overrides;
3. use the Cleaner slot schema to interpret physical card slots;
4. derive repeating transaction blocks;
5. map Send/Receive date events;
6. pair references within the same correspondence column/event;
7. pair statuses to Receive events;
8. preserve source addresses for traceability;
9. report unmapped semantic content as an issue instead of silently dropping it.

Multiple transaction events in the same document/revision are retained as separate
records.

## Canonical fields

Core output fields include:

```text
project_id
source_run_id
source_workbook
source_sheet
document_index
doc_type
doc_type_a
doc_type_b
doc_name
doc_code
doc_wbs
send_or_receive
doc_rev
event_index
letter_date
letter_reference
doc_status
date_source
reference_source
status_source
block_index
```

## Safe rollout

First validate JSON/CSV output:

```powershell
python .\pipeline\weekly_report_pipeline.py board-to-log `
  --run-dir ".\runs\azd_20261006T063256" `
  --project AZD `
  --csv-out ".\runs\azd_20261006T063256\board_to_log.csv"
```

Only after acceptance should the optional Excel COM writer create/replace a
`Logbook` sheet, and then only on the controlled cleaned workbook copy.

## Backward compatibility

The canonical record intentionally retains the legacy Board2Log names used by
existing downstream reports (`doc_name`, `doc_wbs`, `send_or_receive`, `doc_rev`,
`letter_date`, `letter_reference`, `doc_status`). New traceability fields are added
around them rather than renaming the established contract.

## Extraction quality audit

Board-to-Log distinguishes preserved narrative from transaction extraction problems.
Narrative/explanation slots are counted in `preserved_narrative_count` and are not
review issues merely because they are not Logbook transactions.

Current extraction issue kinds include:

- `AMBIGUOUS_DATE_ROLE`: a date was recognized but could not be assigned to Send or Receive.
- `MISSING_REFERENCE`: a Send/Receive date has no paired letter reference.
- `MISSING_RECEIVE_STATUS`: a Receive event has no paired status.
- `ORPHAN_REFERENCE`: a reference could not be paired to a transaction date.
- `ORPHAN_STATUS`: a status could not be paired to a Receive event.
- structural artifact issues such as `MISSING_CLEANER_ARTIFACT` and `MISSING_DOCUMENT_REGION`.

The orchestration command writes `board_to_log_issues.csv` beside the canonical JSON
unless `--issues-csv` supplies another path. The console prints counts by issue kind.

## Reference pairing

Board-to-Log consumes Cleaner semantic roles first. Some project correspondence
references are compact numeric/punctuation identifiers (for example `3104-821`)
that Cleaner may intentionally leave as text because they do not match the
learned alphanumeric reference pattern. In that case Board-to-Log may promote
the next compact, non-date, non-status value below a Send/Receive date in the
same transaction column to `letter_reference`.

Long narrative/explanation text is never promoted by this fallback. This keeps
reference pairing compatible with legacy boards without turning prose into
transactions.

## Controlled workbook publication

`publish-logbook` is the production boundary. It finalizes the Cleaner run,
creates a new workbook copy with Excel `SaveCopyAs`, applies only structured
approved workbook changes from `resolved_state.json`, writes the canonical
`Logbook`, reads the sheet back, and verifies a canonical digest before saving.
The source workbook is never saved or overwritten.

```bash
python ./pipeline/weekly_report_pipeline.py publish-logbook --run-dir ./runs/<run_id> --project AZD --allow-issues
```

Publication blocks when Board->Log issues remain unless `--allow-issues` is
explicitly supplied. The run receives `publish_manifest.json` with executed
cleaner changes, known issues, record counts and validation digest.
