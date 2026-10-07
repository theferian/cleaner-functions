# Resolved State 0.1

Cleaner stages are ordered. A later stage reads the reviewed resolutions from
prior stages without requiring those fixes to be physically written into Excel.

```text
M_LINE
  -> review decisions
  -> resolved_state.json
  -> IDENTIFIERS
  -> review decisions
  -> resolved_state.json
  -> future boundary/card/data stages
```

## What becomes logical state

- `SET_VALUE`, `REPLACE_VALUE`, `CLEAR_CELL` -> value overlay
- `MERGE_RANGE`, `UNMERGE_RANGE` -> merge-geometry overlay
- `ACCEPT_EXCEPTION` -> profile exception overlay
- profile/test/manual decisions -> preserved in state for later structured handling

The original workbook remains untouched.

## Run workflow

First stage:

```powershell
python .\pipeline\azd_pipeline.py --stage M_LINE
```

The command prints a `run_id` and paths under:

```text
runs/<run_id>/
```

Review the generated queue:

```powershell
python .\dev\review_findings.py \
  ".\runs\<run_id>\m_line_review_queue.json" \
  --decisions ".\runs\<run_id>\m_line_review_decisions.json"
```

Then run the next stage, ingesting those decisions:

```powershell
python .\pipeline\azd_pipeline.py \
  --run-id "<run_id>" \
  --stage IDENTIFIERS \
  --decisions ".\runs\<run_id>\m_line_review_decisions.json"
```

`IDENTIFIERS` now sees the logical effects of the reviewed M-line decisions.

## Git

`runs/` is runtime state and is ignored by Git.
