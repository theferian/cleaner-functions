# Weekly Report Pipeline Architecture

## Layering

```text
pipeline/
  orchestration only
       ↓
functions/
  cleaner/               interpretation + approved-change executor
  board_to_log/          canonical transaction/log function
  retrieval/             (next)
```

The pipeline owns ordering. Functions own one business capability each.

## Cleaner function

Cleaner owns interpretation of the source workbook:

- M-line / identifier-board boundary
- logical document regions
- card/data boundaries
- repeating slot schema
- semantic field roles
- field validation
- identifier/WBS validation
- review decisions
- project solutions
- exception registry
- resolved-state overlay
- controlled execution of approved workbook changes onto a copy

Its stable downstream contract is the reviewed run directory, especially:

```text
document_regions.json
card_maps.json
slot_schema.json
resolved_state.json
run_manifest.json
```

## Board→Log function

Board→Log consumes that contract. It must not independently rediscover document
regions, revision widths, or status semantics.

Its stable outputs are:

```text
board_to_log.json
board_to_log.csv
board_to_log_issues.csv
```

with one canonical record for every interpreted Send/Receive event plus an explicit
issue list for content Cleaner preserved but Board→Log cannot yet map safely.

## Publish boundary

The pipeline command `publish-logbook` creates a controlled workbook copy, applies
Cleaner-approved workbook changes to that copy, writes the canonical Logbook, and
performs read-back validation before saving. The source workbook is never overwritten.
A `publish_manifest.json` records the execution and validation result.

## Why this boundary matters

If Cleaner learns that an AZD layout is irregular but valid, Board→Log benefits
immediately. We avoid maintaining two different parsers for the same workbook.

## Compatibility

`pipeline/azd_pipeline.py` remains as a compatibility launcher. The actual Cleaner
runner now lives under `functions/cleaner/azd_pipeline.py`.
