# Cleaner — Guarded correspondence correction replay v0.1

**Purpose:** Reuse a previously user-confirmed correspondence-date fix in future Cleaner runs, provided the source workbook still contains the *same document, WBS, letter, old date, paired receive date and response status*. Otherwise block automatic replay for that solution and create a review finding. Never change original Excel.

The current AZD correction refers to **230KV SS / PROT & CONTROL SINGLE LINE DIAGRAM / WBS 1.5.1.1.2.1.2 / letter 1404/ES/S/3003**, changing source send date `1404/08/11` to `1404/07/19`. Existing evidence in `runs/azd_20261014T071802/confirmed_corrections` is reused. The source run and its evidence must be retained, or an explicit reviewed evidence/guard migration is needed.

## Install from Windows CMD

1. Extract **all ZIP contents** into the existing `cleaner-functions` repo root. The `payload` subfolder holds the two new source files.
2. Verify then apply:

```bat
python .\install_guarded_correspondence_replay_v01.py --check
python .\install_guarded_correspondence_replay_v01.py --apply
python -m pytest -q unit_tests
git diff --check -- functions/cleaner/azd_pipeline.py
```

Existing exception/solution files are **not modified by the installer**. The installation hook executes replay at the beginning of `FIELD_VALIDATION` in every project Cleaner run; unmatchable correction records create `CORRESPONDENCE_REPLAY` review findings. It writes `correspondence_replay_report.json` inside the run folder, recording `APPLIED`, `ALREADY_APPLIED`, `ALREADY_CORRECT`, and `NEEDS_REVIEW` outcomes. All corrections are logical `resolved_state` overlays only.

## Read-only check of current AZD run

```bat
python -m cleaner_core.correspondence_replay --run-dir "runs\azd_20261014T071802" --project AZD
```

Expect `ALREADY_APPLIED` when the existing approved solution and evidence can be located; `NEEDS_REVIEW` is a stop signal (not a request to force the fix). If any solution was recorded without its approval evidence, the system refuses replay rather than extrapolating dates.

## Test coverage

9 regression cases: matching after row move, idempotency, already-correct source, conflicting old date, mismatched receive, duplicate letter identity, missing prior approval evidence, dry-run and conflict with an existing override. Archived repo full `unit_tests`: **153 passed**. Your live branch has more tests; run them after installation.

## Acceptance

A fresh run with the same letter and source typo must report `APPLIED` with the new discovered date target, and `FIELD_VALIDATION` must use the corrected value. A conflict must register as a review finding; the stage must not silently mark itself as reviewed. Prior run data, exception knowledge, and original workbook must remain unchanged.
