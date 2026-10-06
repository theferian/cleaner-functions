# Multi-project General Document rollout

The General-Document pipeline is now project-profile driven.

## Registered direct sources

- AZD -> `General - Azad.xlsx`
- JND -> `General - Jondi Shapour.xlsx`
- FSH -> `GOSTARESH E FOLAD E SHAHRIAR - UPDATED DOC.xlsx`
- BFG -> `Baafgh..xlsx`
- NKH -> `Nakhlestan...xlsx`
- EYV -> `General-IVANAKI.xlsx`
- YSK -> `Yasookand-General.xlsx`
- NGN -> disabled until a source path is registered.

The network source is never cleaned in place. Retrieval copies it into `./input` using the standardized naming convention.

## First-time project preparation

```bash
python ./pipeline/weekly_report_pipeline.py prepare-general-doc --project JND
python ./pipeline/weekly_report_pipeline.py prepare-general-doc --project FSH
```

Each command:

1. retrieves the configured network source;
2. verifies the copy with SHA-256;
3. writes `input/<PROJECT>_retrieval_manifest.json`;
4. inspects the workbook sheet structure;
5. creates `profiles/<PROJECT>.profile.json` from GENERAL_DOCUMENT family rules only;
6. does **not** inherit AZD fixes or exceptions.

Review the printed DATA/skip sheet classification. If automatic sheet selection is wrong, rerun with explicit repeated `--sheet` values and `--overwrite-profile`.

## Cleaner discovery for a new project

Start with M_LINE:

```bash
python ./pipeline/project_pipeline.py --project JND --stage M_LINE --new-run
python ./pipeline/project_pipeline.py --project FSH --stage M_LINE --new-run
```

The generic launcher resolves the retrieved workbook from the project retrieval manifest, opens the retrieved working copy in Excel, and loads the matching project profile.

Continue the same ordered stages after reviewing any pending findings:

`M_LINE -> DOCUMENT_BOUNDARIES -> CARD_MAP -> SLOT_SCHEMA -> FIELD_VALIDATION -> IDENTIFIERS`

Use the review command printed by each stage. Pass the resulting decisions file to the next stage with `--decisions`.

## Post-cleaning outputs

After IDENTIFIERS is reviewed, run the same downstream validation used for AZD:

```bash
python ./pipeline/weekly_report_pipeline.py board-to-log --run-dir ./runs/<run-id> --project JND --csv-out ./runs/<run-id>/board_to_log.csv --show-issue-context
python ./pipeline/weekly_report_pipeline.py audit-coverage --run-dir ./runs/<run-id> --project JND --overwrite
python ./pipeline/weekly_report_pipeline.py engineering-lists --run-dir ./runs/<run-id> --project JND --status-date <Jalali YYYY/MM/DD>
```

Repeat with FSH.

Acceptance target is not a fixed transaction count. For every project the key QA invariant is:

`SCANNED_NOT_RETRIEVED = 0`

Any remaining Board->Log issues must be explicit source-data anomalies or reviewed project exceptions.
