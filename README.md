# Cleaner correspondence reconstruction — Task 4A.11

Non-destructive canonical correspondence event identity. The original Board→Log
transaction records remain untouched. The new layer removes repeated physical
representations of a letter from **current-state analysis**, while retaining
all source-cell locations in `correspondence_audit`.

Deterministic identity requires project document (sheet + document index),
direction, normalized letter reference, valid canonical date, and canonical
response status. Reference matches with conflicting dates/statuses are not
merged; they are flagged `CORRESPONDENCE_REFERENCE_CONFLICT`.

Same-day opposite-direction events are flagged `SAME_DAY_DIRECTION_ORDER_UNVERIFIED` because day precision does not prove intra-day event order.

Correspondence overlap is **allowed**, not a data-quality failure. Pairings
suggested by source slot are **candidates only**; no reply-to-send relationship
is automatically confirmed.

## Install (Windows CMD, from cleaner-functions)

```
python .\install_correspondence_reconstruction_v01.py --check
python .\install_correspondence_reconstruction_v01.py --apply
python -m pytest -q unit_tests
```

Then regenerate a controlled AZD run and compare engineering counts and
`correspondence_audit`. New diagnostic `CORRESPONDENCE_REFERENCE_CONFLICT`
requires review; duplicated representation and overlapping submissions do
not by themselves block publication.

**Important:** The archived repository baseline differs from the current local
Cleaner branch (185 tests). Installer first verifies anchors and leaves files
untouched if they do not match.

## Grounded AZD evidence (uploaded coverage audit)

- Logbook rows: 792; 187 documents have recorded transactions.
- 1 exact repeated-letter representation: `63KV SS`, CT & PT CALCULATION, `3104-821`, received `1404/05/25` (two source locations).
- 7 documents have observed overlapping submissions (no reply links inferred).
- 8 documents contain same-day opposite-direction event sets requiring review of intra-day order.
- No conflicting dates/statuses for identical references were found in this uploaded run.

These are evidence counts from the attached historic coverage audit, not a claim about any regenerated live Cleaner run.
