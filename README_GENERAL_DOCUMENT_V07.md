# General Document Cleaner V07

Extract these files into the existing cleaner-functions repository root. The
package adds RUN_GENERAL_DOCUMENT_V07.py, cleaner_v07/, and one test module.
It uses your installed RUN_GENERAL_DOCUMENT_V06.py and current Cleaner modules.
No replacement of profiles, project solutions, earlier runs or core modules is
required. Use the V07 command to activate the changes; the V06 command and earlier
demo controller retain their previous behavior.

## Test and run — Windows CMD

```bat
py unit_tests\test_general_document_v07.py
```

Resume the reported AZD run, including its recorded corrections:

```bat
py RUN_GENERAL_DOCUMENT_V07.py --project AZD --run-id azd_20261022T195101 --status-date 1405/07/29
```

For a NEW run from an already retrieved file:

```bat
py RUN_GENERAL_DOCUMENT_V07.py --project AZD --new-run --workbook "input\7_AZD_LATEST_GENERAL_DOC_14050730.xlsx" --status-date 1405/07/29
```

For another project, supply its project ID and actual retrieved workbook path.
Retrieval remains the existing prepare-general-doc command. The filename date is
not used as the report date. --status-date is REQUIRED, validated as a Jalali date,
and passed to existing engineering calculations. There is no default date.
Resume uses the saved workbook path; a changed reporting date requires a new run.

## Working copies and correction execution

A new run copies the retrieved file into a dated working/GENERAL_DOCUMENT/PROJECT
folder, retaining a source snapshot and source_lineage.json. The run is bound to
that staged base. Resuming a V06 run keeps its original binding and decisions.

Before Board->Log, V07 finalizes existing decisions and physically executes the
approved change plan on runs/RUN_ID/working/GENERAL_DOC_CLEANED_WORKING.xlsx.
It saves, closes, reopens and verifies the affected values/merge conditions.
working_copy_execution.json records source and cleaned hashes, the change-plan
hash, execution details and verification results. A matching verified copy is
reused. Changed decisions cause regeneration from the run-bound source.

The source and run snapshot remain traceable. Existing extraction uses the
Cleaner's resolved logical overlay; physical execution verifies its workbook
changes. The audit workbook is copied from the verified corrected working copy,
then receives the logbook and highlights. It is not regenerated from the
uncorrected retrieval without applying the fixes.

## Remembered corrections

Existing reusable profile/project resolutions are accepted before opening the
interactive reviewer, including in non-interactive mode. Unknown findings still
need review. Applicable decisions continue to be stored in project_solutions.

V07 adds the requested reusable explanation-date normalization rule. It applies
only to FIELD_VALIDATION explanation-date findings where the existing normalizer
produces valid dates and exactly matches the suggested target/value. The observed
old value is a required execution guard. Invalid dates and unrelated text fixes
are not auto-approved. This rule is authorized by the requested V07 workflow;
it does not turn every machine suggestion into an approved correction.

Review decisions can still display execution=PENDING: physical completion is
established by the separate working_copy_execution.json receipt. If structural
review blocks the run, no physical completion is claimed.

## Vertical revision history

The order is revision block, physical event start row, and send before receive
at the same row. Independent SEND/RECEIVE event counters no longer determine
which event is latest. Later revisions may restart near the top of the card.
Merged date cells use their anchor/start row; a lower reference or status cell
alone does not constitute another event.

chronology_v07.json records the selected geometry, dates and references per
document. Conflicting dates, missing positions and duplicate same-side positions
remain review diagnostics. Ambiguous documents are withheld from delay assignment
and not misclassified as Not Sent. A narrative response still changes workflow
state according to its known status, with NEEDS_DATE if its delay cannot be calculated.
This version does not infer undocumented cross-revision response references.

## Excel lifecycle

Pipeline operations use owned DispatchEx Excel instances. Excel visibility is
best-effort; failure to set Visible cannot abort the audit. Known transient COM
busy/rejected-call errors receive bounded retries. Owned workbooks and applications
close in finally blocks on success, errors and cancellation. Unrelated user Excel
sessions are not attached to or closed. Already-open workbooks left by a previous
V06 run therefore remain under your control.

Source/review workbooks are opened read-only. Use the review correction commands;
this workflow does not save ad-hoc edits made directly in the displayed source.

## Validation and scope

18 automated checks pass against the available Cleaner source: date requirement,
vertical chronology, missing/conflicting evidence, required review, safe date-rule
reuse, execution/save/reopen verification, corrected audit source, cache integrity,
source preservation and owned Excel cleanup/retries.

An archived JND run also passed extraction through the updated calculation adapter:
639 records, zero extraction issues. Its historical date/position conflicts and
unknown statuses remained explicit diagnostics; this is not a current-project
approval or a claim that the live lists are correct.

Excel automation is exercised with object doubles locally; actual Excel/pywin32,
network retrieval, and your latest repository require the Windows test. No new
pip installation is needed beyond the dependencies already used by your Cleaner.
