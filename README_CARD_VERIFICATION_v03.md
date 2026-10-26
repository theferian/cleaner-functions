# Adaptive Reader — General Doc Verification Ledger v0.3

**Purpose:** Confirm or dispute the General Doc's letter date and reference using the actual PDF, retaining what was processed, what the machine suggested, what a person verified, and what still needs review.

## Install (additive; Windows CMD)

Extract this ZIP into the root of your existing `cleaner-functions` repository. All files are new: **do not replace your existing** v0.1/v0.2 reader/teaching/OCR files or Cleaner modules. Works on `feature/weekly-report-cleaner-template` provided the previous versions were installed.

```bat
python -m unittest discover -s tests -p test_card_verification_ledger_v03.py
OPEN_AZD_CARD_VERIFICATION_v03.cmd
```

Test script uses only the Python standard library; unlike the older v0.2 tests, it does not need `reportlab` or Tesseract. Launching the actual UI needs the same dependencies as v0.2 (PyMuPDF, Tkinter, OpenCV, Pillow, numpy, Tesseract with `fas+eng`). The CMD file uses the established AZD `runs\azd_20261014T071802` and W: drive. Edit it if your run ID or Tesseract installation path differs.

## UI: General Doc verification ledger

The new table shows the **General Doc entry** and the **PDF-derived reading** side-by-side for both `letter_date` and `letter_reference`, plus machine and human-review status.

- **Open selected PDF**: bring selected correspondence into the existing Human Edit workspace.
- **Inspect OCR evidence**: raw Tesseract reading, raw PDF text, normalized values, tentative expected-guided hint and page coordinates.
- **Record what I read in PDF**: manually transcribe date/reference *from the PDF*. Either field may be left empty. The app derives the comparison with General Doc; partial reviews remain partial. It does not copy OCR's guess into your transcription boxes.
- **Refresh ledger**: reload latest v0.2 append-only OCR journal and v0.3 human-review journal.
- **Export CSV**: report on all source events, both field results, linked card, provenance and verification status.
- **Start Auto-Run / Stop / Recheck all**: exactly as in v0.2, now continuously reflected in this ledger. OCR runs without human approval; mismatches are NOT automatically written into Cleaner.
- **Filters**: Not checked, Needs review, Possible errors, Human verified, Machine candidates and Missing source.

## The meaning of statuses

- `NOT_CHECKED`: no OCR evidence yet.
- `SOURCE_MISSING` / `SOURCE_AMBIGUOUS`: filename locator did not identify a unique source. Not a General Doc error.
- `MACHINE_MATCH_UNVERIFIED`: OCR/native reading yielded compatible values for *both* fields. This is **not an independent verification**.
- `POSSIBLE_MISMATCH`: read text differs or only an abbreviated reference was found. Human review needed.
- `UNREADABLE` / `READER_CONFLICT` / `NEEDS_REVIEW`: weak OCR, disagreement between text readings or failed extraction. No assertion that the entry is wrong.
- `PARTIALLY_REVIEWED`: one field has been human checked, or a reference is only partially printed.
- `VERIFIED_CORRECT`: operator read both field values from the PDF, and both normalized values match the General Doc snapshot.
- `VERIFIED_ERROR`: at least one independently transcribed field disagrees with that snapshot.
- `STALE_REVIEW`: evidence fingerprint changed after review; approval must be reconsidered.

**Important:** The General Doc values here come from the `board_to_log.json` snapshot in the specified run, **not a live reread of the latest General Doc Excel workbook**. Rebuild the Cleaner extraction/logbook after source workbook updates, then reopen the dashboard. The app blocks a review if that snapshot changes during the session. It also verifies that the PDF's current SHA-256 equals the OCR evidence before recording a human review.

**Not all General Doc cards necessarily have traceable letter events**: this queue covers correspondences with recorded references; card coverage counts are based on that queue and do not imply that unrelated blank/no-letter cards have been checked.

## Saved records (nothing overwrites existing results)

Base folder: `runs\azd_20261014T071802\source_verification\`

- `card_field_autorun_v02.jsonl`: existing append-only, per-event OCR and source hashes.
- `card_verification_reviews_v03.jsonl`: **new** append-only operator-transcribed date/reference, decision, evidence hash, source hash, General Doc comparison snapshot and timestamp.
- `card_verification_ledger_v03.csv`: regenerated on **Export CSV**, suitable for Excel, filtering and management review.

Reviewer entries do not edit the source PDF, General Doc Excel file, Cleaner `resolved_state.json`, project solutions or any automatic corrections. To correct a verified General Doc error, use the existing governed Cleaner resolution workflow separately.

## On OCR reconstruction

- Persian and Arabic digits normalize to ASCII, dates accept one-/two-digit months and days, and exact eight-digit dates can be reconstructed without inventing digits.
- Full references normalize punctuation, letters and digits.
- A shortened reference (such as `1404-2605` when General Doc has `1404/ES/S/2605`) is **partial evidence**, not automatic proof of the full reference.
- The system may show an `EXPECTED_GUIDED_NOT_EVIDENCE` hint based on similarity to the General Doc value. Such a hint does **not** count as matching evidence or a confirmed reading.
- Each human transcription is kept alongside original OCR evidence for later error-pattern training; v0.3 does **not** claim to have trained a new OCR model.

## Verification performed before packaging

`21/21` ledger/core tests passed. Existing v0.2 `8/8` tests passed in the development container (with ReportLab installed). A headless Tkinter smoke test opened a synthetic one-card PDF, then demonstrated `NOT_CHECKED` → `MACHINE_MATCH_UNVERIFIED` after regional OCR. **The real W: drive and user's Windows OCR were not accessible for live tests.**
