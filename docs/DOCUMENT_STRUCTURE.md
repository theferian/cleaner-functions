# DOCUMENT_STRUCTURE

`DOCUMENT_STRUCTURE` validates the physical card/layout inside each derived
`DocumentRegion`. It deliberately does **not** validate dates, status values, or
transaction content yet.

## Fingerprint

Each region is converted into a normalized merge-geometry signature:

- document row count;
- transaction area start column (normally `D`, immediately after the M-line);
- all merged ranges fully contained in the region;
- merge row coordinates stored relative to the region start.

Absolute row numbers and cell values are excluded. Therefore, if a valid card
moves from rows `43:44` to `55:56` in a later weekly workbook, it still receives
the same `pattern_id` when its layout is unchanged.

## First run / learning

Patterns not yet present in `data_model.document_structure.known_patterns` are
reported once per unique geometry as `POSSIBLE_EXCEPTION`. Ten documents with
the same new geometry create one review item, not ten.

If the reviewer confirms the geometry is valid:

1. choose `ACCEPT_EXCEPTION`;
2. finish the stage review;
3. run `dev/promote_decisions.py ... --apply` on the resulting decision file.

The promotion logic stores the reviewed geometry as a sheet-specific known
structure pattern. Future weekly workbooks recognize it by geometry rather than
by row number.

## Hard structural hazard

A merge is **not** a hazard merely because it spans several document rows. AZD
contains legitimate higher-level/context merges (for example Document Type or
transaction-side grouping) that can cross multiple `DocumentRegion`s.

Under the default `OWNED_BOUNDARY_FIELDS_ONLY` policy, a crossing merge becomes
a `FAIL` only when both conditions are true:

1. the merge anchor starts inside the current `DocumentRegion` (the region owns it);
2. the merge covers one of the configured boundary-field columns (for AZD, Name/WBS).

This keeps genuine boundary disagreements visible while ignoring contextual
merges that do not define document ownership.

## Pipeline position

```text
M_LINE
  -> DOCUMENT_BOUNDARIES
  -> DOCUMENT_STRUCTURE
  -> IDENTIFIERS
```

`document_structure_catalog.json` is written into the run folder for inspection
and future UI/Frappe integration.

> **Pipeline status:** merge fingerprints are now diagnostic only. The required
> AZD workflow uses `CARD_MAP` instead, because reviewers need explicit card/data
> boundaries rather than anonymous geometry IDs.
