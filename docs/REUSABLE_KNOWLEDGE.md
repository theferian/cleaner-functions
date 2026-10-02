# Reusable AZD knowledge

`resolved_state.json` belongs to one cleaner run. It carries reviewed decisions
between ordered stages without changing Excel.

Reusable knowledge belongs to the document-family profile and survives into
future weekly workbooks.

```text
weekly finding
  -> human review
  -> resolved_state.json                 (this run)
  -> explicit promotion
  -> profiles/AZD.profile.json           (future runs)
```

## Promotion

Preview reviewed decisions first:

```powershell
python .\dev\promote_decisions.py `
  .\runs\<run-id>\m_line_review_decisions.json `
  .\runs\<run-id>\identifiers_review_decisions.json
```

Persist accepted reusable knowledge:

```powershell
python .\dev\promote_decisions.py `
  .\runs\<run-id>\m_line_review_decisions.json `
  .\runs\<run-id>\identifiers_review_decisions.json `
  --apply
```

Promotion is deliberately explicit; a single unusual workbook cannot silently
redefine the AZD profile.

## What is promoted

- `ACCEPT_EXCEPTION` becomes `known_exceptions`.
- `SET_VALUE`, `CLEAR_CELL`, `REPLACE_VALUE`, `MERGE_RANGE`, and
  `UNMERGE_RANGE` become `known_fixes` when they have a stable test/sheet/target
  match.
- `DEFER`, `DISMISS`, free-text manual fixes, and free-text rule changes are not
  automatically promoted.

For `IDENTIFIERS` `SET_VALUE`, the old generated value is **not** reused. The
profile stores a policy to use the current run's machine suggestion. This keeps
WBS generation tied to the current workbook's nearest valid WBS context.

## Faster review next week

A finding that matches a promoted fix is marked `KNOWN_REUSABLE_RESOLUTION`.
Known M-line exceptions remain recognized by the M-line test.

Use:

```powershell
python .\dev\review_findings.py <queue.json> --decisions <decisions.json> --accept-known
```

This automatically records decisions only for findings already covered by a
reusable profile policy, then interactively shows only unknown/new findings.
Nothing is physically written to Excel by this command.

## Current matching limit

Known fixes currently match by `test_id + sheet + target + status`. This is safe
for a stable weekly template but row movement creates a new finding requiring
review. A later document-boundary/record-identity layer can replace row-based
matching with logical document identity.
