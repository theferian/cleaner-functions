# Adaptive Reader — Visual Calibration v0.3

**Goal:** reproduce the *semantic segmentation* shown in the user's Adaptive Reader screenshot, using the existing Adaptive Document Annotator v0.6 and its direct-open launcher v0.2. It is NOT a new viewer or a new OCR engine.

The screenshot depicts the following page-1 regions: header data (letter number/date/attachment), logo, recipient organization/title, recipient name, subject, subject continuation, greeting, main message, closing/blessing, signature, postscript, contact footer, and optional vertical branding. **Their approximate rectangles are stored as normalized screenshot-derived geometry** in `azd_outgoing_letter_calibration_v01.json`.

These labels are reference *proposals*, not automatically detected facts, and are **not** automatically generalized to other layouts. Only page 1 has a target profile; page 2 uses the native detector until separately reviewed.

## Install

The current v0.2 direct-open reader must already exist under `tools/adaptive_document_reader/` (as in the user's working screenshot). Extract this v0.3 bundle into the root of `cleaner-functions`, preserving paths. Only new files are supplied; existing v0.6 native source and direct-open v0.2 launcher are **not overwritten**.

## Windows CMD

Default AZD letter, opens actual PDF directly in Human Edit:

```bat
OPEN_AZD_CALIBRATION_v03.cmd
```

Or another letter:

```bat
python .\tools\adaptive_document_reader\calibrate_letter_in_reader_v03.py --pdf "W:\00-1403\1403-02-05-230kV Azad\Letter\technical\send\1404-3003.pdf" --reference "1404/ES/S/3003" --expected-date "1404/07/19"
```

To **visually mimic black masks + red labels in the user's screenshot**:

```bat
OPEN_AZD_CALIBRATION_v03.cmd --mask-preview
```

You can toggle masks/outlined regions in the GUI; the *outline* mode is more useful for inspecting underlying document contents.

## Calibration workflow

1. Open the actual PDF; v0.6 Detection Lab and Human Edit remain available.
2. The new **Calibration targets — REVIEW BEFORE LEARNING** layer is added on page 1.
3. Toggle the **Mask / outline preview** button to compare layout against the supplied screenshot.
4. Compare the 13 targets with the source letter; move, resize, relabel, remove any incorrect regions. Use **Show / hide target** to compare with native detection.
5. Press **Evaluate detector** to write `working/source_registry/AZD_1404-3003_calibration/page_01_calibration_audit.json`. It reports geometry intersection-over-union (IoU ≥ 0.30 considered a geometric hit), target coverage and the positions of current editable regions. **Geometry overlap is not semantic correctness or field verification.**
6. When satisfied, press **Accept corrected layout**, acknowledge that you have checked it, then **Save correction + learn**. The save action trains only the reviewed calibration regions, not the unreviewed native detector suggestions.
7. Test the resulting family memory on another letter of the *same layout*, and inspect its predictions. Do not treat matching page coordinates as proof of matching field values.

### Required region acceptance

- Header metadata group, logo, recipient organization, recipient name, subject, greeting, message body, closing, signature, postscript and footer are identifiable and editable.
- Headers/subregions remain readable in outline mode.
- PDF source remains unchanged; approved Cleaner date correction stays unchanged.
- No letter date or reference becomes VERIFIED automatically: fields must be extracted from evidence and reviewed separately.
- Page navigation preserves region geometry and manual edits.
- Page 2 is *not* assigned page-1 labels.

### Critical source caveat

The previous `1404-3003.pdf` probe detected serial `3003` and date `1404/07/02` in searchable text, but not full reference `1404/ES/S/3003` or approved date `1404/07/19`. The screenshot's native-text status reported no recognized dates. This discrepancy is still **unresolved**; structural calibration does not establish the letter's true header date or whether it matches `AZD-SOL-0099`.

## Tests

```bat
python -m unittest -q tests.test_adaptive_letter_calibration_v03
```

If `tests` is not an importable package in your repo, run:

```bat
python .\tests\test_adaptive_letter_calibration_v03.py
```

The visual GUI can only be smoke-tested on a machine with a display. The app is read-only toward the source PDF, its behavior is limited to suggestions and user-driven learning, and the confirmation step prevents unreviewed targets from entering the learned examples.
