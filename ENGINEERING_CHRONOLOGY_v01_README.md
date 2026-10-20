# Engineering Event Chronology Patch v0.1

## Goal

Select current engineering document responsibility from the **actual chronological Jalali event date**, not revision index, event index or Excel source position. Keep provenance and diagnose contradictions.

The verified AZD case `LINE / FOUNDATION DRAWING / 1.6.1.1.3` is:

- SEND `1404/10/24`
- RECEIVE `1404/11/04`, `CM`
- **Current holder = COMPANY**, last action `1404/11/04`

## What changes

- Valid dated events are ordered by `(year, month, day)` from the canonical Jalali date.
- Revision and source index are secondary tie-breakers *only on the same date*.
- Source-order/date inversions are reported as `SOURCE_SEQUENCE_DATE_INVERSION`.
- Paired receive dates preceding send dates are diagnosed as `RECEIVE_BEFORE_MATCHED_SEND` and remain reviewable.
- Events later than the reporting date are excluded from the as-of state and diagnosed as `FUTURE_DATED_EVENT_EXCLUDED`.
- Undated narrative interactions remain visible; cases with ambiguous chronology are flagged `UNRESOLVED_UNDATED_EVENT_ORDER` and may retain `NEEDS_DATE`.
- Future-only histories cannot be mislabeled as `NOT_SENT`.

## Apply to the newer live repository

The older `engineering_chronology_v01.patch` is supplied **only for code review**. Since your live repository has drifted since the archived source, use the anchor-based installer rather than `git apply`.

From the Cleaner root in Windows CMD/cmder:

```bat
cd /d "C:\Users\f.tehrani\Desktop\Weekly Report Golden\cleaner-functions"
git status -sb
python .\apply_engineering_chronology_v01.py
python -m pytest -q unit_tests
git diff --check
git status --short
```

The installer makes a timestamped backup in `.chronology_patch_backups/` beside the repository (outside Git), changes only `three_lists.py`, `test_engineering_three_lists.py`, and creates/updates `docs/DEMO_TASK_LIST.md`. It does **not** alter source Excel files, Cleaner run files, existing project-specific exceptions/solutions, or commits. If expected anchors differ, it stops before changing anything.

## Acceptance: rerun AZD engineering lists

```bat
python .\pipeline\weekly_report_pipeline.py engineering-lists --run-dir "runs\azd_20261014T071802" --project AZD --status-date 1405/07/22
findstr /i /c:"FOUNDATION DRAWING" "runs\azd_20261014T071802\engineering_lists\02_Company_Delay.csv"
findstr /i /c:"FOUNDATION DRAWING" "runs\azd_20261014T071802\engineering_lists\03_Consultant_Delay.csv"
```

Because other foundation drawings exist, verify the exact composite key `LINE + document_index=3 + WBS=1.6.1.1.3`, not a name-only match.

Expected: **in Company Delay with latest event `CM` at `1404/11/04`; absent from Consultant Delay**.

When this is verified, review `git diff`, then commit **only the code/test/docs files**, preserving pre-existing modifications to project exception/solution JSON files.

## Validation evidence on archived Cleaner source

- Unit suite: **150 passed** (144 baseline + 6 regression tests)
- Idempotency: second install reports `Already installed`.
- FOUNDATION DRAWING fixture: Company=1; Consultant=0; last action `1404/11/04`, status CM.

No claim is made that the newer live repository or current AZD lists have already passed these tests; those tests are the next step.
