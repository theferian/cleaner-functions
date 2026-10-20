# AZD confirmed correspondence-date correction

Human-confirmed source typo: `230KV SS!M21` has `1404/08/11`, but the true SEND date is `1404/07/19` for PROT & CONTROL SINGLE LINE DIAGRAM (`1.5.1.1.2.1.2`) letter `1404/ES/S/3003`. The paired RECEIVE remains `1404/08/10`, status `A`.

Copy `apply_azd_confirmed_date_correction.py` to the root of the live `cleaner-functions` repository. Do not overwrite the source General Document.

Windows CMD:

```bat
python .\apply_azd_confirmed_date_correction.py --run-dir "runs\azd_20261014T071802" --dry-run
python .\apply_azd_confirmed_date_correction.py --run-dir "runs\azd_20261014T071802"
python .\pipeline\weekly_report_pipeline.py board-to-log --run-dir "runs\azd_20261014T071802" --project AZD
python .\pipeline\weekly_report_pipeline.py audit-coverage --run-dir "runs\azd_20261014T071802" --project AZD --overwrite
python .\pipeline\weekly_report_pipeline.py engineering-lists --run-dir "runs\azd_20261014T071802" --project AZD --status-date 1405/07/22
python -m pytest -q unit_tests
git status --short
```

The script checks document identity, WBS, correspondence reference, original SEND value, paired RECEIVE date and status. It stores a reviewed value override in `resolved_state.json`, an approved correction in `project_solutions/AZD.solutions.json`, and a `confirmed_corrections` evidence file. It makes backups of the modified registry/state. It is repeatable without adding another solution.

**Important:** the existing Cleaner already supports reviewed value overlays and durable project solutions. This script registers this verified typo and updates this run. It does **not yet automatically re-apply the fix to newly retrieved weekly workbooks**; implementing the broader *confirmed-correction replay* stage is the next Cleaner task. That replay must find matching document identity + letter reference + old value on each new workbook and fail closed on mismatches. Do not automatically infer date corrections from chronology inversions.

**Cleaner backlog additions:**

- [x] 4A.13a: Register AZD approved M21 send-date correction and update current run's effective values.
- [ ] 4A.13b: Integrate persistent confirmed-correction replay into every new Cleaner run (with old-value, letter and document guards).
- [ ] 4A.13c: Add generic `RECEIVE_BEFORE_MATCHED_SEND` review workflow: detect; obtain approved SEND or RECEIVE replacement; persist; revalidate and re-export.
- [ ] 4A.13d: Compare regenerated Logbook and engineering-list classifications; confirm contradiction clears.
