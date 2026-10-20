# Phase 2 — General Document Chronology Test Suite V01

Run from the existing Windows `cleaner-functions` repository root. No third-party dependencies.

## Install

Extract `GENERAL_DOC_CHRONOLOGY_V01.zip` directly into the repository root.

## One command — inspect the latest Phase 1 result

```bat
py .\CHRONOLOGY_TEST_SUITE_V01.py --phase1-dir "portfolio_audits\card_morphology_20261018T044939" --status-date 1405/07/22
```

Run the 12 regression tests:

```bat
py -m unittest -q test_chronology_test_suite_v01.py
```

Optional: limit scan to the source-order inversion discussed for YSK:

```bat
py .\CHRONOLOGY_TEST_SUITE_V01.py --phase1-dir "portfolio_audits\card_morphology_20261018T044939" --projects YSK --status-date 1405/07/22
```

## Output under `portfolio_audits\chronology_YYYYMMDDTHHMMSS`

| File | Meaning |
|---|---|
| `chronology_team_investigations.csv` | Actual validation failures plus situations needing investigation (NOT all are proven source errors) |
| `chronology_observations.csv` | Source order inversions, duplicate-looking references and same-day ambiguities; none cause automatic corrections |
| `chronology_findings_all.csv` | Both registers together |
| `chronology_event_orders.csv` | Evidence for three distinct orderings, with validated Jalali date and revised date rank |
| `chronology_exception_gallery.html` | Browser-readable case viewer showing the revision timeline and original source cells |
| `chronology_summary.csv` | Per-project counts and categories |
| `PHASE2_CHRONOLOGY_REPORT.md` | Rules, limitations and portfolio summary |

## Interpretation

- `ACTION`: mechanically demonstrable inconsistency (e.g. invalid date; extracted record-count mismatch). It does not authorize automatic source modification.
- `INVESTIGATE`: uncertain/missing evidence (e.g. possible receive-before-send; no letter date). Ask the project team or check original correspondence.
- `OBSERVE`: no correction recommended merely because a physical cell sequence has decreasing dates or a valid same-day tie.
- **No single SEND/RECEIVE pair is declared causally linked solely from revision membership**. The original correspondence must confirm linkage.
- Status date means reporting cutoff, **not** that a source file should stop containing future transactions.
- Day validation uses a civil 33-year Jalali leap cycle limited to 1350–1420; earlier/later years require authoritative calendar extension.
- Source versioning intentionally out of scope.
- No existing V06 reviewer decisions, run artifacts, overlays, or Excel workbooks are changed.

## Next

Review the new totals; then connect `chronology_team_investigations.csv` with the existing Phase 1 `card_review_queue.csv` for the project-team correction package. Evidence retrieval & OCR will follow once the structural and chronological cases are classified.
