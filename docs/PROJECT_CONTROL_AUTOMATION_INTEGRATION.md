# PROJECT_CONTROL_AUTOMATION — Cleaner integration contract

Contract compatibility: **0.2.1**

## Boundary

Cleaner remains authoritative for General Document structure discovery, project profiles,
reviewed corrections, exception history, Board→Log, Coverage Audit and engineering reporting.
The integration layer consumes Cleaner artifacts; it does not reimplement workbook discovery.

### Minimum request into Cleaner

- `project_id`
- approved working-copy path (or an externally approved SHA-256)
- approved `source_artifact_id`
- orchestration `run_id`
- Cleaner project profile

### Minimum response from Cleaner

- Cleaner `run_id`
- versioned `document_structure_quality_schema.json`
- source artifact binding and SHA-256
- separate quality states: structure discovered/reviewed, data validated, coverage verified,
  write targets approved
- references/digests for run artifacts

**Coverage is not write approval.** `write_targets_approved` is false in the current implementation
because the Cleaner does not yet model an explicit workbook write-target approval contract.

## Existing Excel entry point

Explicit workbook processing is already supported:

```cmd
python .\pipeline\project_pipeline.py --project AZD --workbook "C:\path\approved.xlsx" --stage M_LINE --new-run
```

Continue with the returned Cleaner run ID and the same `--workbook` argument. Reviewed decision
files are ingested with repeated `--decisions <path>` arguments.

Python entry point:

```python
from pipeline.project_pipeline import main
main(["--project", "AZD", "--workbook", workbook, "--stage", "M_LINE", "--new-run"])
```

## Structure/quality schema export

```cmd
python .\pipeline\weekly_report_pipeline.py export-structure-schema ^
  --run-dir runs\<cleaner_run_id> ^
  --project AZD ^
  --orchestration-run-id 20261013T225747Z_4011c1bf ^
  --source-artifact-id R06e86d9ebfa5 ^
  --workbook "C:\path\approved_AZD.xlsx" ^
  --source-sha256 <approved_sha256>
```

The exporter reads and hashes the approved copy but never modifies it. If the externally supplied
SHA-256 differs from the bytes on disk, export fails.

Python entry point:

```python
from functions.cleaner import export_structure_quality_schema
output, schema = export_structure_quality_schema(
    "runs/<cleaner_run_id>",
    project_id="AZD",
    orchestration_run_id="20261013T225747Z_4011c1bf",
    source_artifact_id="R06e86d9ebfa5",
    workbook_path=r"C:\path\approved_AZD.xlsx",
    source_sha256="...",
)
```

## Existing artifact contracts

- `cleaner.run_manifest/0.1` — run/profile/workbook/pipeline identity.
- `cleaner.resolved_state/0.1` — stage review state plus value/merge/profile/test decisions and audit.
- stage reports — `kind=azd_pipeline_stage`, `script_id`, logs, findings, candidates, snapshot/run metadata.
- `cleaner.document_regions/0.1` — run-bound document boundaries and identifier fields.
- `cleaner.card_map/0.1` — identifier/data areas and per-card slot addresses.
- `cleaner.slot_schema/0.1` — repeating transaction width, column semantics and inferred roles.
- `board_to_log.logbook/0.1` — canonical send/receive transaction records.
- `board_to_log.coverage_audit/0.1` — mapped-cell retrieval classifications.
- `engineering.three_lists/0.2` — Not Sent, Company Delay, Consultant Delay and Delay Register.
- `weekly_report.publish/0.1` — controlled cleaned-copy execution and Logbook read-back validation.

## Reuse across runs

Persistent project knowledge lives in `profiles/<PROJECT>.profile.json`,
`exceptions/<PROJECT>.exceptions.json`, and `project_solutions/<PROJECT>.solutions.json`.
A fresh run gets a new `resolved_state.json`; known project/profile fixes and accepted exception
patterns are matched against new findings. Run decisions are not blindly inherited. Persistent
anomaly cases remain visible until evidence changes or the case is resolved.

## Current unsupported scope

- formula/dependency graph discovery for Excel;
- explicit write-target approval manifests/ranges;
- MSP parsing/extraction (Chat 04 owns schedule parsing);
- P6 XER/XML parsing/extraction (Chat 04 owns schedule parsing);
- generalized CSV structural discovery.

The new schema records these gaps explicitly instead of treating them as clean/approved.

## Manifest examples (historical AZD contract shapes)

These are shape examples; they are not evidence for the canonical 20261013 run.

```json
{"schema":"board_to_log.logbook/0.1","project_id":"AZD","source_run_id":"<cleaner_run>","summary":{"record_count":780,"issue_count":1},"records":["..."]}
```

```json
{"schema":"board_to_log.coverage_audit/0.1","run_id":"<cleaner_run>","project_id":"AZD","summary":{"counts":{"CAPTURED_TRANSACTION":1925,"SCANNED_NOT_RETRIEVED":0,"UNRESOLVED_ISSUE":1}},"items":["..."]}
```

```json
{"schema":"engineering.three_lists/0.2","status_date":"1405/07/16","summary":{"not_sent":"<n>","company_delay":"<n>","consultant_delay":"<n>","delay_register":"<n>","diagnostic_count":"<n>"},"lists":{"01_Not_Sent":[],"02_Company_Delay":[],"03_Consultant_Delay":[],"04_Delay_Register":[]},"diagnostics":[]}
```

```json
{"schema":"weekly_report.publish/0.1","run_id":"<cleaner_run>","project_id":"AZD","source_workbook":{},"output_workbook":"<controlled copy>","cleaner_execution":{},"board_to_log":{},"known_issues":[],"logbook_write":{},"validation":{"record_count":"<n>","digest":"<sha256>"}}
```

## P6 / MSP coordination boundary

The shared quality mechanism can later accept parser-owned findings such as encoding errors,
identifier duplication, chronology violations, broken WBS parentage and invalid progress fields.
The Cleaner service should own reusable anomaly-case lifecycle, deterministic correction policy and
review evidence. **Chat 04 remains owner of MSP/P6 parsing and schedule extraction.** No schedule
parser is added by this change.

## AZD profile inventory (provided Cleaner baseline)

`profiles/AZD.profile.json` is `schema_version: 0.4`, family `GENERAL_DOCUMENT`, profile `AZD`.
The expected data sheets are `230KV SS`, `63KV SS`, and `LINE`. `M_LINE` is enabled on those
sheets with boundary `C|D` (`boundary_after_col: 3`) and candidate exceptions are discovered by
`EXACT_CROSSING_GEOMETRY_SIGNATURE`.

The reusable identifier model is:

- `document_type`: column 1, text, optional;
- `name`: column 2, required non-empty text; deterministic empty-name repair uses
  `ERR_EMPT_NAME_{NUMBER}`;
- `wbs`: column 3, required WBS matching `^\\d+(?:\\.\\d+)*$`; invalid/empty values use
  nearest-valid-above plus a sequence starting at 1000.

Document boundaries start at row 3 and are merge-aware. The Board/card data area starts at column 4.
The semantic transaction vocabulary is `reference`, `send_date`, `receive_date`, `status` and the
current profile enables global Jalali-token audit, receive-date/status relation validation and
receive-on-or-after-send chronology review.

In the provided repository snapshot the AZD profile contains 5 known structural exceptions and 44
promoted deterministic fixes. Those counts are inventory evidence from the supplied baseline only;
the operator's newer Windows repository may contain additional learned cases and remains authoritative.
