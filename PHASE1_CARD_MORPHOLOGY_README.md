# Cleaner: General Document — Phase 1 Card Morphology (read-only)

Copy `CARD_MORPHOLOGY_GALLERY_V01.py` into the root of `cleaner-functions`, next to `RUN_GENERAL_DOCUMENT_V06.py`.

Run on Windows CMD/cMder:

```bat
py .\CARD_MORPHOLOGY_GALLERY_V01.py
```

Optional native Excel images for the first **20** gallery examples:

```bat
py .\CARD_MORPHOLOGY_GALLERY_V01.py --excel-images 20
```

**Important:** `--excel-images` requires Microsoft Excel COM (`pywin32`) and Pillow. It reads the workbook without saving but **replaces clipboard contents**. If Excel is busy or the dependencies are missing, the run continues with recorded-cell visualizations; check `excel_capture_warnings.txt`. The base scan requires only standard Python.

Outputs, in `portfolio_audits/card_morphology_<timestamp>`:

- `card_morphology_catalog.csv` — every observed document/revision combination, morphology, source range, counts and flags.
- `card_review_queue.csv` — suspected anomalies only, with suggested investigation; no bulk acceptance.
- `board_issue_inventory.csv` — every current extractor issue, even if not paired to an event.
- `event_orderings.csv` — source cell order, revision membership and provisional date order separately.
- `morphology_summary.csv` — distribution of card types by project.
- `card_exception_gallery.html` — browse examples in Edge/Chrome, with a cell-range visualization and optional native Excel images.
- `PHASE1_DISCOVERY.md` — plain-language Phase 1 findings.

The gallery uses the **existing reviewed run artifacts**. It does not rescan or modify the source workbooks, accept any exceptions, rerun Cleaner stages, create versions, or infer chronological causality. It does not yet perform OCR. Some shape variations, notably multiple SENDs and one RECEIVE, are valid business patterns and do not enter the action queue merely because the event counts are unequal.

To run tests:

```bat
py -m unittest -q test_card_morphology_gallery_v01.py
```

On missing run data, the project is explicitly identified as unavailable; it is not misreported as a file full of empty document cards.
