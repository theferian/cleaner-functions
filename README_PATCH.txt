AZD compatibility launcher import-path fix

Changes:
- pipeline/azd_pipeline.py adds repository root to sys.path before importing functions.cleaner.
- unit_tests/test_weekly_report_pipeline_cli.py adds direct launcher regression under cp1256.

Verified: 97 tests passed.
