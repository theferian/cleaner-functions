# Weekly Report Cleaner Service Contract v0.1

## Inputs

- workbook path
- project/document profile path

## Operations

### `inspect_file(workbook, profile)`
Returns file hash, sheets, matched archetypes, dimensions, formula/merge counts and formula-reference errors.

### `validate_file(workbook, profile)`
Returns `passed` or `needs_review`, issue/evidence arrays, date evidence and WBS counts.

### `extract_file(workbook, profile)`
Returns canonical structured data:

- report dates
- recognized semantic regions
- master WBS/progress rows with row classification
- canonical engineering-status counts
- current Not Sent / Company Delay / Consultant Delay report rows
- procurement report rows

## Contract principle

The caller supplies a file and profile. The caller should not hard-code AZD workbook cell addresses. Those remain profile knowledge owned by Cleaner.

## Current limitation

This version is read-only and uses structural/semantic extraction from `.xlsx` OOXML. It does not recalculate formulas and does not mutate workbooks.
