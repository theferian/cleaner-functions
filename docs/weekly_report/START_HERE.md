# Weekly Report Cleaner — branch start

Branch: `feature/weekly-report-cleaner-template`

## Goal

Read each weekly-report workbook without changing the original, discover its sheet/field structure,
extract typed and source-linked records, join to authoritative WBS/schedule data only when mappings
are approved, and populate a user-selected reporting template. Separate observed values from derived
values, proposed corrections and human approvals.

## Starting assumptions to verify, not hard-code

- There may be several report families and project-specific layouts.
- The master Jalali reporting date may be stored on worksheet 2; *discover* rather than assume its address.
- Project names, WBS numbers, engineering/procurement/construction progress, and planned/actual values may
  be represented as formulas, merged regions and multiple sheets.
- Excel formulas, hyperlinks, formatting and original source history must not be lost.

## Initial inventory command (Windows CMD)

```bat
py .\tools\weekly_report\inspect_workbook.py --file "C:\path\to\LATEST_WR.xlsx"
```

The inspector only reads the source file and writes a JSON inventory under
`working/weekly_report_discovery`. Inspect the JSON to determine *actual* schema.

## Build sequence

1. Inventory representative weekly reports from AZD, JND, FSH, YSK, EYV, BFG, NKH, NGN.
2. Define family-level and project-specific field maps with exact sheet/range evidence.
3. Extract canonical rows (project, WBS, measured item, period, planned, actual, notes, provenance).
4. Validate formulas, arithmetic, dates, WBS identity, completeness, and reporting cut-off.
5. Write to a copy of a designated template, not the original; verify populated cell counts.
6. Offer interactive review/overlay for uncertain mappings, then re-extract and regenerate.

## Planned contracts

- `source_inventory.json`: file hash, sheets, merges, formulas, date candidates, links.
- `weekly_report_extract.jsonl`: one typed fact with `source_file`, `sheet`, `cell`, `raw_value`, `interpreted_value`, `confidence`.
- `weekly_report_mapping.json`: reviewed map of source fields to template fields.
- `template_fill_manifest.json`: each output cell with input fact IDs and formula behavior.
- `quality_report.json`: checks, active exceptions, review history.

No source editing, no fabricated WBS IDs, no implicit sign-off, no assumption of a fixed template.
