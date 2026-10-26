# Direct-open Adaptive Document Reader (v0.2)

This build **opens the actual source PDF directly in the existing v0.6 Adaptive Document Annotator GUI**. It preserves the original Detection Lab, Human Edit, editable layers, page navigation and Save & Learn functionality.

## Installation

Extract the bundle into your `cleaner-functions` repository root, preserving the `tools/adaptive_document_reader` folder. The two existing reader files are included unmodified. This distribution does **not** include your learned examples or overwrite any `adaptive_document_learning` folder.

Install dependencies if missing: `python -m pip install pymupdf pillow numpy opencv-python`.

## Open the AZD letter directly

```cmd
python .\tools\adaptive_document_reader\open_letter_in_reader.py
```

The launcher defaults to:

`W:\00-1403\1403-02-05-230kV Azad\Letter\technical\send\1404-3003.pdf`

For a different PDF:

```cmd
python .\tools\adaptive_document_reader\open_letter_in_reader.py --pdf "W:\some\other\letter.pdf" --reference "1404/ES/S/3003" --expected-date "1404/07/19"
```

## What is visible in the app

1. Page 1 opens **in the Human Edit tab** without asking you to browse to the PDF.
2. The native v0.6 detector runs automatically and populates editable page regions.
3. Additional native-text field proposals appear in a separate layer group: **Field candidates — UNVERIFIED**. They include dates, letter reference/serial, and literal field captions (`تاریخ`, `شماره`, `موضوع`, `پیوست`, `گیرنده`) when found.
4. The top source-evidence bar states whether the full expected reference and approved date were detected in selectable text. Neither a filename nor matching serial verifies those fields.
5. Clicking **Page ▶** runs the same detection once for each new page. Returning to a previously viewed page preserves your edits.
6. You can move, resize, relabel and save regions using the existing **Save & Learn** button. Saving is always your explicit action.

The launcher is **read-only with respect to the company PDF** and does not alter Cleaner `resolved_state.json`, `AZD.solutions.json`, or the General Doc. It adds no OCR. For image-only or poorly encoded Persian PDF text, annotate visible fields manually until an OCR backend is connected.

## Verification

Smoke-tested under a virtual display using a synthetic two-page PDF, including the previously observed date `1404/07/02` and expected date `1404/07/19`. Those remain different values and are not silently reconciled. **The real `W:` drive is not accessible in the packaging environment.**
