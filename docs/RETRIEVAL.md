# Retrieval Function

Retrieval is a sibling function to Cleaner and Board→Log.  It does not inspect Excel cells and it does not clean workbooks.

```text
source Project Control folders
        ↓
functions/retrieval
        ↓
standardized working copy + retrieval manifest
        ↓
Cleaner
```

## Responsibilities

1. Resolve a configured project and source family.
2. Find the source using either a direct path or a filename regex.
3. When more than one file matches, apply the configured duplicate policy.
4. Copy the selected source into the retrieval workspace using the standard filename.
5. SHA-256 verify source and retrieved copy.
6. Write a retrieval manifest for downstream traceability.

Retrieval never overwrites a different existing retrieved file unless `--overwrite` is explicitly supplied.

## Source modes

### `direct`

Use when the Project Control team keeps one current workbook at a stable path.

```json
{
  "mode": "direct",
  "path": "W:\\...\\General Document.xlsx"
}
```

This corresponds to the earlier `Document Paths` design.

### `latest_regex`

Use when a folder contains dated versions.

```json
{
  "mode": "latest_regex",
  "root": "W:\\...\\General Document Archive",
  "recursive": false,
  "file_name_regex": "^(?:\\d+(?:\\.\\d+)?)_(?P<proj_id>[A-Z0-9]+)_LATEST_GENERAL_DOC_(?P<jalali_date>\\d{8})\\.xlsx$",
  "project_group": "proj_id",
  "date_group": "jalali_date",
  "duplicate_policy": "latest_date"
}
```

Supported duplicate policies: `latest_date`, `latest_modified`, `error`.

## Standard retrieved filename

```text
<REPORT_ORDER>_<PROJECT_ID>_<NAME_TOKEN>_<JALALI_RETRIEVAL_DATE>.<ext>
```

Examples:

```text
7_AZD_LATEST_GENERAL_DOC_14050715.xlsx
4.1_BFG_LATEST_GENERAL_DOC_14050715.xlsx
4.2_NKH_LATEST_GENERAL_DOC_14050715.xlsx
```

## CLI

Retrieve the enabled source family for AZD:

```bash
python ./pipeline/weekly_report_pipeline.py retrieve --config ./configs/project_control_sources.json --project AZD
```

Retrieve only General Document:

```bash
python ./pipeline/weekly_report_pipeline.py retrieve --config ./configs/project_control_sources.json --project AZD --family GENERAL_DOCUMENT
```

Use an explicit retrieval date while testing:

```bash
python ./pipeline/weekly_report_pipeline.py retrieve --config ./configs/project_control_sources.json --project AZD --family GENERAL_DOCUMENT --retrieval-date 14050715
```

The command prints source, selected candidate count, retrieved path and SHA-256, then writes an `<PROJECT>_retrieval_manifest.json` file in the retrieval workspace.

## Current engineering scope

`GENERAL_DOCUMENT` is the source currently mapped into the engineering Cleaner → Board→Log pipeline.

The three Project Control engineering lists are **downstream derived outputs**, not Retrieval source families:

1. Documents Not Sent
2. Company Response Delay
3. Consultant Response Delay

See `docs/ENGINEERING_THREE_LISTS.md`. Procurement/progress sources may be added later as separate Project Control workstreams, but they are not these three engineering lists.
