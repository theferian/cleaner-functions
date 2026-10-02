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

If a merged range intersects a derived document region but extends outside its
row boundary, the stage emits a `FAIL`. That indicates disagreement between the
boundary model and the physical card geometry and should be reviewed before
content-level cleaning.

## Pipeline position

```text
M_LINE
  -> DOCUMENT_BOUNDARIES
  -> DOCUMENT_STRUCTURE
  -> IDENTIFIERS
```

`document_structure_catalog.json` is written into the run folder for inspection
and future UI/Frappe integration.
