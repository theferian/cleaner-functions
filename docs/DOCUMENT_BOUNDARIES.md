# Document Boundaries

`DOCUMENT_BOUNDARIES` turns the worksheet's mapped identifier geometry into
logical `DocumentRegion` objects before later tests inspect document fields.

## Why this exists

The first identifier implementation had to guess whether each physical row was
a document. That worked as a bootstrap, but it mixed two separate questions:

1. Is this row part of a real document record?
2. If it is, are Name and WBS valid?

The boundary layer answers the first question once and exposes the answer to
later cleaner stages.

## AZD default rule

For each configured sheet:

- `document_type`, `name`, and `wbs` are signal fields.
- `name` and `wbs` are boundary fields.
- A row is a candidate document anchor when at least one signal field owns a
  non-empty value at that row.
- Vertical merges owned by Name/WBS define the document's row span.
- Continuation rows of those merges are not new documents.
- If Name and WBS are both only covered by a larger merge anchored elsewhere
  (for example `A15:AA16`), the range is classified as separator/background,
  not a document.
- Mixed/external identifier merges and overlapping document spans are emitted
  as review findings rather than silently guessed.

No row numbers are learned as document boundaries. The regions are derived
again from each workbook, so a weekly report may insert or remove rows without
invalidating the rule.

## Pipeline order

The AZD pipeline is now:

```text
M_LINE
  -> review
DOCUMENT_BOUNDARIES
  -> review only ambiguities
IDENTIFIERS
  -> review
```

`IDENTIFIERS` uses the same `DocumentRegion` detector, so its Name/WBS checks
operate only on logical document anchors instead of scanning worksheet rows
with its old provisional heuristic.

## Audit artifact

When the boundary stage runs, the pipeline also writes
`document_regions.json` into that run directory. It contains the derived
regions, excluded separator ranges, and ambiguities for inspection/debugging.
It is derived runtime data and is not intended to be committed to Git.
