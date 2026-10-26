# Adaptive Reader — General Doc Source Workbench v0.4

**Additive update** for your existing `cleaner-functions` branch, on top of installed Adaptive Reader v0.6 and Card Teaching v0.1, OCR/Auto-Run v0.2, Verification Ledger v0.3. This ZIP adds **new files only**; it does not replace existing Cleaner or Adaptive Reader modules. Original Excel/PDF files remain read-only.

## Install (Windows CMD, from Cleaner repository root)

Extract ZIP preserving the `tools/adaptive_document_reader` and `tests` directories. Then:

```bat
python -m unittest discover -s tests -p test_card_workbench_v04.py
OPEN_AZD_SOURCE_WORKBENCH_v04.cmd
```

The launcher points at the saved AZD logbook (`runs\azd_20261014T071802\board_to_log.json`) and shared `W:\00-1403\1403-02-05-230kV Azad\Letter\technical` folder, including `send` and `recive`. Edit the `.cmd` **only if** your run directory or `tesseract.exe` differs. Reader requirements remain `pymupdf`, `opencv-python`, `numpy`, `pillow`, Tkinter, and Tesseract `fas+eng`.

## One guided screen — the intended interaction

1. **Document direction:** Outgoing (our letters), Incoming (consultant), or Both directions. The queue, ledger, auto-run and export reflect this selection. Direction comes from `send_or_receive` in the saved Logbook, not automatic recipient inference.
2. Select an event in the ledger and click **1 OPEN SELECTED PDF**. The reader fetches the indexed PDF via its reference filename, not by assuming every card has a valid source.
3. Click **2 DRAW DATE** or **DRAW REFERENCE**. If a suggested box exists, the tool selects it for resizing rather than making a second box. Draw just once for new layouts. Edits are saved per source PDF (even if you haven't approved them) and restored on reopen, including across app restarts. The draft is invalidated if the PDF size/mtime changes.
4. Click **3 APPROVE BOXES** to explicitly teach the family (outgoing and consultant memory stores are separate). Approving the exact same boxes again is a no-op, so it does not create duplicate training examples. Box approval does NOT mean the source values have been independently verified.
5. Click **4 READ OCR + COMPARE**. OCR is asynchronous and **only** crops the two field regions. Both raw PDF native text and raw Tesseract OCR results appear in the page, with comparison candidates and unreadable statuses. The OCR setup diagnostic at the top shows when Tesseract and `fas+eng` are unavailable; Auto-Run is blocked until the OCR engine is ready. OCR errors are **not** marked as completed.
6. To human-verify an entry, inspect the printed source values, type them in **5 PDF date / PDF reference**, then click **CONFIRM SOURCE VALUES**. One or both fields may be reviewed. A confirmation dialog states whether the transcribed value matches the General Doc. Human review is bound to the PDF SHA-256 and OCR evidence hash, and becomes stale if the evidence changes.
7. Once happy with field positions, press **START AUTO-RUN**. It loops over the selected direction using approved/source-specific boxes or transferred ORB-aligned family examples. Low-confidence alignment pauses for teaching, not guessed extraction; OCR mismatches remain in review queue while the loop continues. **STOP** is cooperative and saves prior results. Resuming skips completed OCR events.
8. **EXPORT JSON + CSV** writes interoperable results for current scope. The previous v0.3 review journal and v0.2 extraction journal remain untouched.

The old native Detection Lab and diagnostic controls are available behind **Advanced**. The large list of previous v0.1/v0.2/v0.3 toolbar buttons is hidden; the source ledger and Human Edit canvas stay visible.

## Persistent artifacts

Inside `runs\azd_20261014T071802\source_verification\`:

- `field_drafts_v04/field_draft_<id>.json`: source-specific normalized boxes, approval signature, file stat. Separate for family and page. Saves unapproved edits too.
- `card_field_autorun_v02.jsonl`: append-only raw per-event OCR evidence and PDF fingerprints (pre-existing journal, reused).
- `card_verification_reviews_v03.jsonl`: append-only, human-confirmed values (pre-existing journal, reused).
- `exports_v04/send/`, `exports_v04/receive/`, or `exports_v04/both/`:
  - `verification_events_v04.jsonl`: one structured record per correspondence event with family, General Doc card/WBS, PDF source, OCR/native text, candidates, statuses, source-cell links and review metadata.
  - `verification_events_v04.csv`: Excel-compatible UTF-8-BOM flat reporting table.
  - `verification_summary_v04.json`: export scope, status counts, provenance and read-only contract.

All source values currently come from **that run's saved `board_to_log.json` snapshot**; the app does **not** rescan the live General Doc workbook. A correspondence event without a reference is not in this queue. Exports do not write to Cleaner solutions, Excel, PDF or Mass Reader. Mass Reader integration is a later change once the contract and workflow are accepted.

## Meaning of results

`NOT_CHECKED` → no OCR; `NEEDS_REVIEW` / `UNREADABLE` → insufficient evidence; `MACHINE_MATCH_UNVERIFIED` → candidate match **not approval**; `POSSIBLE_MISMATCH` → compare manually; `VERIFIED_CORRECT` / `VERIFIED_ERROR` → human-confirmed source reading agrees/disagrees. `STALE_REVIEW` → evidence changed and approval must be repeated.

The app does **not** reconstruct characters by copying the expected General Doc value. Any guided OCR hypothesis remains separately labeled and must never count as independent proof.

## Verification on synthetic fixtures

- Existing v0.1: 10/10 tests passed; v0.2: 8/8; v0.3: 21/21.
- v0.4: 8/8 tests passed (scoping, drafts, source change, approval idempotency, exports, missing OCR retry).
- Headless Tkinter tests: open PDF, teach/approve, reopen saved boxes, switch direction, cropped OCR returns machine-matched date/reference on a synthetic letter with printed Latin-text fields; review ledger and Auto-Run updated; JSONL/CSV exported.
- **Not yet tested on your live Windows/W: drive or handwritten/Persian headers.** Verify Tesseract installation and crops on a real letter before enabling unattended checking of an entire queue.
