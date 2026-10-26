# Adaptive Document Reader — Batch Template Discovery v0.1

This is a companion module for **your existing** `adaptive_document_annotator_v0_6.py`.
It adds read-only folder-wide visual grouping, draft static-region proposals, and
region-scoped field extraction. It does **not** modify the Adaptive Reader GUI,
source PDFs, General Doc, resolved state, or approved Cleaner project solutions.

## Goal

Separate information into three classes:

- `IGNORE_STATIC:logo` / `IGNORE_STATIC:footer` — recurring artwork or boilerplate.
- `EXTRACT:letter_date`, `EXTRACT:letter_reference` — variable evidence fields.
- `CONTEXT` — remaining page regions, neither omitted as evidence nor automatically OCR'd.

The same region can be useful for **template classification** but intentionally
skipped during field extraction. `EXTRACT` wins if a user mistakenly overlaps it
with a proposed static region; review and separate the boxes.

## 1. Discover candidate templates from shared-folder PDFs

Start with outgoing letters, which may share a simpler, more consistent layout:

```cmd
python .\tools\adaptive_document_reader\adaptive_template_learning.py discover --root "W:\00-1403\1403-02-05-230kV Azad\Letter\technical\send" --out "working\source_registry\AZD_template_scan_send" --max-files 150 --threshold 0.86
```

Use `--recursive` if the chosen source directory contains nested PDF folders.
Run independently on `technical\recive` to find incoming-letter families.

Outputs: `discovery.json`, `G001_example.png`, `G001_persistent_ink.png`,
`G001_static_suggestions.png`, and equivalents for additional groups.

**Important limitations**: visual clustering is heuristic, first-page only, and
uses normalized page placement rather than registration. The proposed static areas
are NOT enabled automatically. The current version does not detect signatures or
complex embedded images reliably and is not production-ready for unsupervised
OCR masking. Group assignments and suggested masks require manual review.

## 2. Teach the existing Annotator what to ignore and extract

Open one representative PDF for a candidate group in your existing v0.6 Human Edit.
Create/edit regions and write these strings into the **Role** field:

- `IGNORE_STATIC:logo`
- `IGNORE_STATIC:footer`
- `IGNORE_STATIC:vertical_branding`
- `EXTRACT:letter_date`
- `EXTRACT:letter_reference`
- optionally `EXTRACT:recipient`, `EXTRACT:subject`

Adjust bounding boxes to include the variable value, preferably excluding fixed
labels around it. Then click **Save correction + learn**. The reader stores a
reviewed example under:

`tools\adaptive_document_reader\adaptive_document_learning\families\ENGINEERING_CORRESPONDENCE\examples\example_XXXXXX\regions.json`

The existing reader already transfers corrected region boxes using ORB/homography;
this prototype consumes the semantic Role labels to generate extraction policy.

## 3. Convert the reviewed example into a draft extraction policy

```cmd
python .\tools\adaptive_document_reader\adaptive_template_learning.py from-example --regions "tools\adaptive_document_reader\adaptive_document_learning\families\ENGINEERING_CORRESPONDENCE\examples\example_000001\regions.json" --out "working\source_registry\AZD_letter_policy_DRAFT.json"
```

Replace `example_000001` with the actual saved example. The policy includes normalized
page-coordinate rectangles, so extraction does not depend on current UI zoom.
The file is explicitly marked `DRAFT_REVIEW_REQUIRED`.

## 4. Targeted date extraction and dual reader check

```cmd
python .\tools\adaptive_document_reader\adaptive_template_learning.py extract --pdf "W:\00-1403\1403-02-05-230kV Azad\Letter\technical\send\1404-3003.pdf" --policy "working\source_registry\AZD_letter_policy_DRAFT.json" --expected-date "1404/07/19" --out "working\source_registry\AZD_1404-3003_evidence.json" --lang fas+eng
```

For `EXTRACT:letter_date`, the tool independently requests native PDF text and
300 DPI cropped Tesseract OCR; it first uses PSM 7 (single line) and retries
PSM 6 if no date is found. The resulting JSON includes both transcriptions,
normalized Jalali-style date candidates, disagreements, source hash, exact
region and `UNVERIFIED_DO_NOT_MUTATE_CLEANER` state.

PyMuPDF supports clipped native text extraction; OCR is cropped to the target ROI.
PyMuPDF's whole-page OCR API does NOT itself accept a crop rectangle, which is why
this utility renders and OCRs the selected ROI separately.

**No extracted date is automatically treated as proof** of a matched source letter.
The letter's reference, document identity, physical field role and source provenance
still require evidence-backed verification.

## Integration to build next

1. Batch-group approval: require a reviewed minimum set of representative PDF pages.
2. Reuse v0.6 homography for reliable source-to-template alignment and transfer of ROIs.
3. Add two explicit UI actions: **Mark static (ignore extraction)** and **Mark field (extract)**.
4. Promote reviewed draft policy to `profiles/families/ENGINEERING_CORRESPONDENCE/...`
   only with reviewer, schema version and source example hashes.
5. Register source evidence to Cleaner Logbook, with discrepancy review before applying any corrections.

## Validation

Run in Windows CMD:

```cmd
python -m pytest -q tests\test_adaptive_template_learning.py
```

The bundled test creates six synthetic PDF letters with two distinct letterheads,
checks that they group separately, and checks region-scoped date extraction.
This has **not** been run against the network-drive PDFs in your environment.
