# Exception Registry

The Cleaner distinguishes three concepts:

1. **Workbook fix** — a deterministic change such as `SET_VALUE`.
2. **Accepted exception** — a legitimate recurring condition that may be promoted into reusable profile knowledge.
3. **Tracked exception** — a real unresolved anomaly that must stay visible until investigated/resolved.

Tracked/accepted exception cases are stored per project in `exceptions/<PROFILE>.exceptions.json`.

Each case has a human handle such as `AZD-EXC-0001`, lifecycle state, workflow status, tags, note, source finding, match signature, first/last seen timestamps and history.

## Review actions

- `1 ACCEPT_EXCEPTION` creates/updates an exception case with `ACCEPTED / KNOWN_ACCEPTED`, and may still be promoted to profile knowledge.
- `k TRACK_EXCEPTION` creates/updates an `OPEN / INVESTIGATE` case without accepting the anomaly as valid data.
- `d DEFER` also creates/updates an `OPEN / INVESTIGATE` case automatically.

## Recurrence

When the same validation stage runs again:

- if the finding still exists, the case remains open and is shown by handle in the review queue;
- if the finding is no longer detected, an open case is automatically marked `RESOLVED / NO_LONGER_DETECTED`;
- accepted exceptions are not auto-resolved merely because profile logic suppresses them.

This JSON model is intentionally suitable for a later Frappe `Cleaner Exception Case` DocType.

## Reusable profile knowledge vs exception cases

A review decision whose `origin` starts with `REUSABLE_PROFILE` is already
represented by reusable profile knowledge. It is ingested into resolved state
but does **not** create another exception-registry case.

For registries created before this rule, accepted cases that are exactly covered
by an enabled `known_exceptions` profile rule are retained for audit history but
retired as:

- `case_state = RESOLVED`
- `workflow_status = SUPERSEDED_BY_PROFILE`
- `classification = PROFILE_KNOWN_EXCEPTION`

This keeps the active exception workflow focused on unresolved business/data
anomalies while preserving historical handles.
