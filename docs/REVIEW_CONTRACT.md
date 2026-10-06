# Cleaner Review Contract 0.1

The review layer sits between detection and execution:

```text
Profile-driven Test
        ↓
Finding
        ↓
Review Queue
        ↓
Human Decision
        ↓
Decision File
        ↓
Later: Executor / Frappe workflow
```

A known exception is **not automatically treated as permanently correct**.
It appears in the review queue with:

```text
current_policy.state = CURRENTLY_ACCEPTED_BY_PROFILE
```

The reviewer can still choose to replace that policy with a workbook repair,
profile change, or test-rule change.

## Review item

Each review item has:

```json
{
  "review_id": "stable-id",
  "review_state": "PENDING",
  "source": {
    "kind": "TEST_FINDING",
    "test_id": "M_LINE",
    "status": "FAIL",
    "severity": "HIGH"
  },
  "location": {
    "sheet": "63KV SS",
    "target": "B9:X10"
  },
  "message": "...",
  "evidence": {},
  "current_policy": {},
  "allowed_actions": [],
  "decision": null
}
```

## Decision vocabulary

### Policy decisions

- `ACCEPT_EXCEPTION`
- `PROFILE_CHANGE`
- `TEST_RULE_CHANGE`

### Workbook repair decisions

- `SET_VALUE`
- `CLEAR_CELL`
- `REPLACE_VALUE`
- `UNMERGE_RANGE`
- `MERGE_RANGE`
- `MANUAL_FIX`

### Workflow decisions

- `DEFER`
- `DISMISS`

The review phase records **intent only**. It does not execute workbook changes.

For a workbook repair, a decision looks like:

```json
{
  "action": "SET_VALUE",
  "execution_kind": "WORKBOOK_CHANGE",
  "execution_state": "PENDING",
  "parameters": {
    "sheet": "63KV SS",
    "target": "C47",
    "value": "Corrected value"
  },
  "reason": "..."
}
```

A later executor can consume `azd_review_decisions.json`.

## Frappe mapping

The JSON deliberately uses flat, stable concepts that can map to DocTypes:

```text
Cleaner Run
  1 ── n Cleaner Review Item
          1 ── 0..1 Cleaner Decision
```

Suggested future fields:

### Cleaner Run
- run_id
- package_id
- package_version
- profile_name
- workbook_name
- workbook_path
- created_at

### Cleaner Review Item
- review_id
- test_id
- detected_status
- severity
- sheet
- target
- message
- evidence_json
- review_state

### Cleaner Decision
- action
- execution_kind
- execution_state
- parameters_json
- reason
- reviewer
- decided_at

## Reviewer safety and Excel navigation

The terminal reviewer keeps workbook repair **non-executing**. Excel navigation may
activate/select cells, change the active window zoom/scroll position, and show a
temporary application status-bar message, but it must not change worksheet values,
formats, shapes, merges, row heights, or column widths.

By default `SET_VALUE`, `CLEAR_CELL`, and `REPLACE_VALUE` are locked to the
finding's own `location.sheet` and `location.target`. This prevents accidental
replacement of the target address while entering a value. Deliberate redirection
requires the explicit `--allow-target-edit` flag.

A completed decision can be corrected without editing JSON manually:

```powershell
python .\dev\review_findings.py <queue.json> --decisions <decisions.json> --edit 4
```

`--edit` accepts a 1-based queue number, an exact review id, or a unique review-id
fragment. The prior decision remains on disk until the replacement is actually
recorded; skipping the edit preserves the previous decision.

During review the navigator:

1. activates the workbook and worksheet;
2. brings Excel to the foreground when Windows allows it;
3. establishes the target's top-left cell as the real `ActiveCell`;
4. selects the full target/merged area using Excel's native selection border;
5. zooms and scrolls the target into a prominent position; and
6. restores the pre-review sheet, active cell, zoom, scroll position, and status bar
   when the reviewer exits normally.
