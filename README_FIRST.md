# General Document — real Excel screenshot gallery

This tool generates a **native Excel screenshot gallery**, not AI illustrations, from the already reviewed General Document runs for AZD, JND, FSH, YSK, EYV, BFG, NKH and NGN.

## Installation

Extract the ZIP **directly** into the repository root:

`C:\Users\f.tehrani\Desktop\Weekly Report Golden\cleaner-functions`

Keep these four files together:

- `GENERAL_DOC_REAL_SCREENSHOT_GALLERY.py`
- `GENERAL_DOC_REVIEW_GROUPS.csv`
- `GENERAL_DOC_FINDINGS_103.csv`
- `GENERAL_DOC_CARD_CATALOG.csv`

No original Excel file is modified.

## Run — all eight projects

From CMD/cmder:

```bat
py .\GENERAL_DOC_REAL_SCREENSHOT_GALLERY.py --projects AZD,JND,FSH,YSK,EYV,BFG,NKH,NGN --pdf
```

Creates a new `portfolio_audits\general_doc_real_excel_gallery_YYYYMMDDTHHMMSS` folder containing:

| File | Meaning |
|---|---|
| `GENERAL_DOCUMENT_REAL_EXCEL_GALLERY.html` | **Interactive gallery** with 58 case pages and 103 traceable finding descriptions; click any native image to zoom |
| `GENERAL_DOCUMENT_REAL_EXCEL_GALLERY.pdf` | Same gallery, printable PDF (requires locally installed Edge or Chrome) |
| `images\original\GD-*.png` | Actual Excel screenshots from matching W: source when the source is unchanged, or the reviewed unedited working input if the source has changed |
| `images\cleaned\GD-*.png` | Actual Excel screenshots from a **disposable copy** of the working file after rendering approved `resolved_state.json` cell-value corrections |
| `all_103_findings_with_images.csv` | Individual issue, rule, source location, explanation, proposed correction, links to screenshots |
| `all_58_grouped_cases.csv` | Each document-level assignment and its screenshot paths |
| `approved_overlay_outcomes.csv` | Which approved edits were rendered, which were already equal, which were rejected by old-value preconditions |
| `capture_warnings.csv` | Missing files, protected ranges, COM failures, or inaccessible evidence |
| `gallery_summary.json` | Final output counts and comparison states |

The script uses **your own local Microsoft Excel**, Excel's `CopyPicture`, and `pywin32`. `Pillow` improves clipboard reliability but the tool has an Excel chart export fallback. It uses **no OCR / Tesseract**.

### Run one project first

```bat
py .\GENERAL_DOC_REAL_SCREENSHOT_GALLERY.py --projects YSK --pdf
```

### Scan input cases without opening Excel

```bat
py .\GENERAL_DOC_REAL_SCREENSHOT_GALLERY.py --mode inventory --no-pdf
```

### Test included source-code integrity

```bat
py -m unittest -q test_general_doc_gallery.py
```

### Override an unavailable original or working path — single project only

```bat
py .\GENERAL_DOC_REAL_SCREENSHOT_GALLERY.py --projects NGN --source-path "W:\...\General - Negin.xlsx" --clean-path "working\GENERAL_DOCUMENT\NGN\NGN_GENERAL_DOC_CLEANER_WORKING.xlsx"
```

### PDF export

The tool invokes installed Microsoft Edge or Chrome in headless print mode. If PDF export fails, open the generated `GENERAL_DOCUMENT_REAL_EXCEL_GALLERY.html` in Edge, press `Ctrl+P`, and choose **Save as PDF**. Images and report work offline.

## How to interpret the gallery

- **Observed / source workbook**: an actual Excel range from the original source **only when it matches the reviewed input**, otherwise from the *unedited Cleaner run input*. The comparison note makes the provenance explicit. The current `W:` workbook is never assumed to be an old version if its contents changed.
- **Cleaner view**: the *same input version* opened in a disposable copied workbook, with approved `SET_VALUE`, `REPLACE_VALUE`, and `CLEAR_CELL` overlays applied **only to relevant cells**. The script validates `expected_old_value` before applying an overlay.
- **APPROVED OVERLAY RENDERED**: at least one relevant approved cell correction is visibly applied to the temporary copy. It does **not** mean every finding about that card was fixed or formally accepted.
- **UNRESOLVED**: the output is identical or has no approved cell correction; the solution is the **written rule and required team action**, not a manufactured green "fixed" image.
- **CAPTURE INCOMPLETE**: consult `capture_warnings.csv`, supply an actual workbook, or rerun that project.

Status exceptions, card geometry, missing source letters, and chronology questions cannot be automatically resolved by inventing dates or references. They remain human-review cases. Approved structural merge operations are **not applied** by this renderer (only guarded cell values).

**Safety:** no workbook `Save` is issued; all Excel instances are launched independently; the script closes books with `SaveChanges=False` and deletes its disposable working copies. Gallery screenshots may contain commercially sensitive correspondence; distribute the output only to authorized project teams.
