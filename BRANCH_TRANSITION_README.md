# Finish General Document Cleaner → start Weekly Report Cleaner

Copy/extract the whole kit to the existing `cleaner-functions` repository root.

```bat
py .\FINISH_BOARD_TO_LOG_START_WR.py --check
py .\FINISH_BOARD_TO_LOG_START_WR.py --apply
```

- `--check` does not modify files or Git; lists safe archives, code to stage, protected changes.
- `--apply` first runs `py -m pytest -q --ignore=payload --import-mode=importlib`.
- It archives only **untracked** root ZIP/PYZ/patch installers, explicit old report JSON and backup folders into a sibling directory `_cleaner_branch_archives` (outside Git). Nothing is deleted.
- It does **not** archive `runs/`, `working/`, `portfolio_audits/`, `profiles/`, `exceptions/`, `project_solutions/`, `input/` or any source workbooks.
- It refuses already staged changes, changed tracked runtime files, oversized new source files, pre-existing new branch and existing new-branch starter files.
- It commits source changes on `feature/board-to-log`, creates `feature/weekly-report-cleaner-template`, copies a read-only XLSX Weekly Report inspector into the new branch, tests and commits that starter.
- It preserves other unknown untracked material; inspect the printed warning. It never pushes to a remote.

On the new branch, inspect an existing weekly-report workbook:

```bat
py .\tools\weekly_report\inspect_workbook.py --file "C:\path\to\LATEST_WR.xlsx"
```

Share its console summary and generated JSON inventory to decide real extraction rules and the target template schema.

## Recovery

Archive manifest is in `_cleaner_branch_archives/board_to_log_*/manifest.json` at the parent folder of `cleaner-functions`. Git commits remain locally recoverable with `git log --oneline -3` and `git switch feature/board-to-log`.
