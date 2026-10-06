# Cleaner Functions v0.3 — AZD M-Line

This package implements the revised architecture:

```text
Live Excel workbook
        ↓
Excel SaveCopyAs
        ↓
temporary current-state snapshot
        ↓
openpyxl analysis
        ↓
Profile Discovery / Profile-Driven Tests
```

The analysis layer no longer enumerates Excel cells through COM.

## Package contract

`cleaner.package.json` is at the ZIP root:

```json
{
  "package_id": "cleaner_functions",
  "version": "0.3.0",
  "core_module": "cleaner_core",
  "profile_schema": "0.3",
  "requirements": "requirements.txt",
  "entrypoints": {
    "profile_discovery": "discoveries",
    "tests": "tests",
    "cleaners": "cleaners"
  }
}
```

A future Frappe bridge can inspect this manifest rather than guessing the ZIP layout.

## Important separation

### Discovery

`discoveries/discover_m_line.py`

Used while developing a profile. It scans only the configured header window and reports merged title candidates and the boundary each candidate would imply.

It does **not** determine PASS/FAIL.

### Health check

`tests/m_line_check.py`

Uses the boundary already stored in the profile:

```json
"boundary_after_col": 3
```

which means:

```text
C | D
```

The test does not depend on A1 or title discovery.

## AZD profile

`profiles/AZD.profile.json` currently contains:

```text
Expected sheets:
- 230KV SS
- 63KV SS
- LINE

Stored M-line:
C | D

Known exception rows:
15,16
129,130
197,198
341,342
```

Known exception geometry is also used to identify structurally similar candidate exception groups elsewhere. Candidate exceptions are reported, not automatically trusted.

## Run against the Excel workbook currently open

From PowerShell:

```powershell
cd cleaner_functions_v0_3_azd

python -m pip install -r requirements.txt

python .\dev\run_azd_mline.py
```

Optional:

```powershell
python .\dev\run_azd_mline.py --mode check
python .\dev\run_azd_mline.py --mode discover
python .\dev\run_azd_mline.py --workbook "7_AZD_LATEST_GENERAL_DOC_14050707.xlsx"
```

The runner logs live stages such as:

```text
[CONNECT] Attaching to running Excel.
[CONNECT] Workbook: 7_AZD_LATEST_GENERAL_DOC_14050707.xlsx
[SNAPSHOT] Creating temporary SaveCopyAs snapshot...
[TIMING] Excel SaveCopyAs snapshot created in 0.42s
[STAGE] Running profile-development discovery.
...
[STAGE] Running profile-driven M-line health check.
[INFO] 230KV SS: 120 total merged ranges; 4 cross C|D.
...
```

Output is written to:

```text
azd_mline_report.json
```

## Why it should be much faster

The old implementation did this:

```text
Python
  ↕ COM
every used Excel cell
```

The revised implementation makes one Excel `SaveCopyAs` call, then openpyxl reads the file locally:

```text
Excel COM
   ↓ one copy operation
openpyxl
   ↓
merged-range geometry
```

## Next development

Once the actual AZD report is reviewed:

1. confirm whether `C|D` is correct for all three sheets;
2. review known exceptions;
3. approve/reject newly discovered candidate exceptions;
4. then build the next profile-driven structural rule.


# v0.4 Review Layer

After the M-line check, the runner now creates two distinct outputs:

```text
azd_mline_report.json
    raw technical detector output

azd_review_queue.json
    normalized human/Frappe review input
```

Run normally:

```powershell
python .\dev\run_azd_mline.py
```

The final console section is:

```text
=== FINAL REVIEW LIST ===
1. KNOWN_EXCEPTION ...
2. FAIL ...
3. POSSIBLE_EXCEPTION ...
```

To immediately review each finding in the terminal:

```powershell
python .\dev\run_azd_mline.py --review
```

or later:

```powershell
python .\dev\review_findings.py
```

Review decisions are written to:

```text
azd_review_decisions.json
```

The review layer **does not change Excel yet**.

It records what should happen later, for example:

```text
ACCEPT_EXCEPTION
SET_VALUE
CLEAR_CELL
REPLACE_VALUE
UNMERGE_RANGE
MERGE_RANGE
MANUAL_FIX
PROFILE_CHANGE
TEST_RULE_CHANGE
DEFER
DISMISS
```

This is intentional: detection, human judgment, and execution remain separate.
That separation is also suitable for later Frappe workflow/approval handling.

See:

```text
docs/REVIEW_CONTRACT.md
```


# v0.4.1 — Identifier Cleaner / Test

The v0.4 core and review contract are preserved.

Added:

```text
tests/identifier_check.py
cleaners/identifier_cleaner.py
dev/run_azd_identifiers.py
dev/run_azd_health.py
dev/configure_profile_fields.py
docs/IDENTIFIER_RULE.md
docs/DATA_FIELD_MODEL.md
```

## Run only Name/WBS identifiers

```powershell
python .\dev\run_azd_identifiers.py
```

Interactive review:

```powershell
python .\dev\run_azd_identifiers.py --review
```

When a machine cleaning suggestion exists, the reviewer can choose:

```text
u  USE_MACHINE_SUGGESTION
```

The decision is still only recorded; it is not applied to Excel yet.

## Run current AZD health suite

M-line + identifiers:

```powershell
python .\dev\run_azd_health.py
```

With review:

```powershell
python .\dev\run_azd_health.py --review
```

This creates one Frappe-friendly queue containing findings from both tests.

## Edit family data fields / instance mappings

```powershell
python .\dev\configure_profile_fields.py
```

Default family fields are:

```text
Document Type
Name
WBS
```

You may add more fields without changing the test framework.


# Resolved-state pipeline

Ordered stages can now carry reviewed resolutions forward without changing the
live Excel workbook.

Start a **fresh workbook run** explicitly at M-line:

```powershell
python .\pipeline\azd_pipeline.py --new-run --stage M_LINE
```

The command creates a new `runs/<run-id>/` directory, `resolved_state.json`, and
`run_manifest.json`, then prints the generated run ID. Continue later stages
with that exact ID:

```powershell
python .\pipeline\azd_pipeline.py --run-id "<run-id>" --stage DOCUMENT_BOUNDARIES --decisions ".\runs\<run-id>\m_line_review_decisions.json"
```

Run mode is intentionally explicit: use `--new-run` only for a freshly retrieved
workbook and `--run-id` only to continue an existing run. A continued run is
bound to the workbook/profile it started with. See `docs/RESOLVED_STATE.md`.


# Reusable knowledge across weekly AZD workbooks

Cleaner now keeps reuse at separate scopes:

- `runs/<run-id>/resolved_state.json` — one run only;
- `exceptions/AZD.exceptions.json` — unresolved/tracked anomalies;
- `project_solutions/AZD.solutions.json` — approved AZD-specific recurring repairs;
- `profiles/AZD.profile.json` — project structure/read rules and broader reusable knowledge.

Deterministic workbook repairs reviewed for AZD are synchronized into the project
solution registry automatically. Project solutions are matched primarily by logical
document identity (especially document Name) plus field/transaction semantics, with
the old cell address only as a fallback. This allows an approved repair to follow the
same document when rows move in a later weekly revision without applying the repair
to other projects.

Existing decision files can be backfilled explicitly:

```powershell
python .\dev\project_solutions.py sync .\runs\<run-id>\field_validation_review_decisions.json .\runs\<run-id>\identifiers_review_decisions.json --project AZD
```

List active project solutions:

```powershell
python .\dev\project_solutions.py list --project AZD
```

Profile promotion remains available for rules/exceptions that should become part of
how the project/document family is interpreted. Preview promotion:

```powershell
python .\dev\promote_decisions.py .\runs\<run-id>\m_line_review_decisions.json .\runs\<run-id>\identifiers_review_decisions.json
```

Apply promotion:

```powershell
python .\dev\promote_decisions.py .\runs\<run-id>\m_line_review_decisions.json .\runs\<run-id>\identifiers_review_decisions.json --apply
```

On a later weekly workbook, use `--accept-known` during review. Project solutions
are preferred over old exact-target profile fixes, so a project-approved value can
follow the same logical document after row movement. New/unknown findings remain
interactive.

See `docs/PROJECT_SOLUTIONS.md` and `docs/REUSABLE_KNOWLEDGE.md`.

# Document boundaries

The ordered AZD pipeline now separates record detection from identifier
validation:

```text
M_LINE
  -> DOCUMENT_BOUNDARIES
  -> IDENTIFIERS
```

`DOCUMENT_BOUNDARIES` derives `DocumentRegion` objects from the current
workbook's mapped Name/WBS anchors and merge geometry. Large category/separator
merges anchored outside the identifier columns are excluded. Ambiguous geometry
is sent to review instead of silently guessed.

Run the new stage after reviewing M-line:

```powershell
python .\pipeline\azd_pipeline.py --run-id "<run-id>" --stage DOCUMENT_BOUNDARIES --decisions ".\runs\<run-id>\m_line_review_decisions.json"
```

The stage writes `runs/<run-id>/document_regions.json` as an audit/debug catalog.
`IDENTIFIERS` now consumes the same logical regions instead of using its former
provisional physical-row heuristic.

See `docs/DOCUMENT_BOUNDARIES.md`.


## Document structure

The ordered AZD pipeline now includes a structural card-layout stage:

```text
M_LINE
  -> DOCUMENT_BOUNDARIES
  -> DOCUMENT_STRUCTURE
  -> IDENTIFIERS
```

`DOCUMENT_STRUCTURE` fingerprints each `DocumentRegion` from normalized merge
geometry. Absolute row numbers and cell values are excluded, so the same valid
card remains recognizable when it moves in a later weekly workbook. Unknown
patterns are reviewed once per unique geometry and can be promoted into
`profiles/AZD.profile.json` with `dev/promote_decisions.py --apply`. The run
also writes `document_structure_catalog.json`. See
`docs/DOCUMENT_STRUCTURE.md`.

## Card map: explicit data boundaries

The required pipeline no longer asks reviewers to approve anonymous merge fingerprints.
The operational path is now:

```text
M_LINE
  -> DOCUMENT_BOUNDARIES
  -> CARD_MAP
  -> IDENTIFIERS
```

`CARD_MAP` records, for every document card, a human-readable identifier range
and data range plus the visible merged/unmerged data slots. For AZD the data area
starts after the C|D boundary. The right edge is derived from the workbook's
actual merge extent.

The profile also records the semantic fields we intend to map next:
`reference`, `send_date`, `receive_date`, and `status`. They are not validated
until their locations are explicitly mapped.

A stage with zero findings is now marked `REVIEWED` automatically, so the next
stage does not require an empty decisions file.

See `docs/CARD_MAP.md`.

## Transaction field inference and validation

After `CARD_MAP`, the ordered AZD pipeline now runs `SLOT_SCHEMA` and `FIELD_VALIDATION` before `IDENTIFIERS`. `SLOT_SCHEMA` infers repeating transaction-block width and semantic roles from worksheet headers plus majority value patterns. `FIELD_VALIDATION` keeps valid values silent and sends only non-canonical/invalid Jalali dates, reference-regex outliers, and status-vocabulary outliers to human review. See `docs/FIELD_INFERENCE_AND_VALIDATION.md`.
