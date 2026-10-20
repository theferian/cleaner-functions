# Adaptive Document Reader — AZD technical letter (v0.1 bridge)

This bundle **reuses the original `DetectionEngine` from `adaptive_document_annotator_v0_6.py` without modifying it**. The additional headless bridge adds PyMuPDF-native text coordinates and *proposed* correspondence-field labels. The bundled `document_layout_discovery_v1_4.py` is the user's existing interactive relabel/QA workbench.

## Contents

```
tools/adaptive_document_reader/
    adaptive_document_annotator_v0_6.py      # existing user-developed engine and template-learning GUI
    document_layout_discovery_v1_4.py        # existing user-developed document layout editor
    run_adaptive_letter_layout.py           # NEW headless bridge to the existing detector
ADAPTIVE_LETTER_LAYOUT_v01_README.md
```

No company files are included. The real PDF is on the user's mapped drive and was **not accessible to this test environment**.

## Install / run (Windows CMD, from cleaner-functions root)

Unzip with the repository root as destination, preserving the `tools/adaptive_document_reader/` directory. Python dependencies for v0.6:

```
python -m pip install pymupdf pillow numpy opencv-python
```

Then:

```
python .\tools\adaptive_document_reader\run_adaptive_letter_layout.py --pdf "W:\00-1403\1403-02-05-230kV Azad\Letter\technical\send\1404-3003.pdf" --reference "1404/ES/S/3003" --expected-date "1404/07/19" --out "working\source_registry\AZD_1404-3003_layout"
```

The bridge saves:

- `layout_proposals.json`: all page regions, normalized bounding boxes, provisional layout labels, native-text excerpts, date/reference candidates, PDF hash.
- `page_01_labeled.png` and `page_02_labeled.png`: the source page with box overlays, proposed labels and field highlights.

Nothing is written to the source PDF or the Cleaner's resolved state / solutions. It does **not** verify fields merely because the date and serial were located. No OCR is performed; scanned regions require human review or an OCR step.

## Human label correction and adaptive learning

The user's **Adaptive Document Annotator v0.6** supports: Detection Lab → Send to Human Edit → edit region boxes/types/roles → Save & Learn for the correspondence family. Run:

```
python .\tools\adaptive_document_reader\adaptive_document_annotator_v0_6.py
```

Open the same PDF, choose family `ENGINEERING_CORRESPONDENCE_OUTGOING`, run Detection Lab, send proposals to Human Edit, correct labels (`header`, `title`, `text_block`, `table`, `signature`, `stamp`), and save the reviewed example. This builds reusable layout memory; training in the existing GUI is separate from the headless v0.1 bridge.

If the user wants detailed semantic field labeling in a second interface, run:

```
python .\tools\adaptive_document_reader\document_layout_discovery_v1_4.py
```

Click **Open PDF → Native blocks** (optionally AI Layout if already configured) → label region semantics → Export JSON / QA PNG. This workbench can label `header`, `title`, `text`, `table`, `stamp`, `signature`, etc. It does **not** read an exported JSON file from the bridge automatically; the PDF is opened afresh.

## Interpretation

The source probe previously found `1404/07/02` and serial `3003`, but **not** the expected full reference `1404/ES/S/3003` or the approved date `1404/07/19`. The bridge's task is to locate, visualize and label the evidence; it must not promote `1404/07/02` into the letter issue date without reviewing the PDF's header/field position.

`MATCHING_TEXT_CANDIDATES_FIELD_REVIEW_REQUIRED` is not `VERIFIED`.

## Test evidence

- The bundled v0.6 detector ran successfully on a synthetic positive sample, correctly identifying the expected full reference and date as *candidates*.
- A separate synthetic two-page PDF with only serial `3003` and a different date `1404/07/02` remained `EVIDENCE_INCOMPLETE_FIELD_REVIEW_REQUIRED` with `full_reference_found=false` and `expected_date_found=false`.
- The real company PDF has **not** been analyzed in this environment. The user should run the command locally and share the generated annotated page images / summary for targeted review.
