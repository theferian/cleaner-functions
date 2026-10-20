# AZD Weekly Report Cleaner v0.1

Read-only Cleaner service for the `WEEKLY_REPORT_TEMPLATE` document family.

## What it does

1. **Inspect** workbook identity and structure.
2. **Validate** required sheets, dates, anchors, WBS/progress and formula-reference integrity.
3. **Extract** canonical WBS/progress, engineering status vocabulary, current engineering report-list contents and procurement rows.
4. **Corpus-test** the same AZD profile against historical Weekly Reports.

This package does **not write into the Weekly Report**. It only discovers, validates and extracts. Downstream report-update services may consume the evidence/results.

## Service boundary for MSP Handler / other callers

```python
from wr_cleaner import inspect_file, validate_file, extract_file

validation = validate_file(workbook_path, profile_path)
extraction = extract_file(workbook_path, profile_path)
```

The caller does not need to know AZD cell addresses. Those belong in the project/document profile.

## Base test

From this folder:

```bat
python -m pytest -q tests
python -m wr_cleaner.cli run --workbook "C:\path\7- سد آزاد.xlsx" --profile ".\profiles\projects\AZD.WEEKLY_REPORT_TEMPLATE.profile.json" --output ".\outputs\AZD_base_run.json"
```

## Historical corpus test

Your earlier retrieval evidence lists many historical copies of `7- سد آزاد.xlsx` under weekly folders such as `1405.03.06`, `1405.03.13`, ... through `1405.07.08`.

Run on the company network from a folder containing those files:

```bat
python -m wr_cleaner.cli corpus-test --root "W:\پیگیری پروژه ها\گزارش هفتگی پروژه ها\1405" --pattern "**\7- سد آزاد.xlsx" --profile ".\profiles\projects\AZD.WEEKLY_REPORT_TEMPLATE.profile.json" --output ".\outputs\AZD_WR_corpus_result.json"
```

## Interpretation

- `passed`: no structural error; warnings may still exist.
- `needs_review`: at least one structural/data error requires review.
- warnings capture known/possible anomalies without silently modifying the workbook.
