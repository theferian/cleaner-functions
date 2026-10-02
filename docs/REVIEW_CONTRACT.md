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
