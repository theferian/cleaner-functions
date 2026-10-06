# Engineering Control — Three Exception Lists

These are the three engineering exception outputs used by Project Control. They are **derived lists**, not three source-document families.

```text
Cleaner Document Inventory + Canonical Board→Log transactions
                              │
                              ▼
                       Current document state
                              │
              ┌───────────────┼────────────────┐
              ▼               ▼                ▼
        01_Not_Sent    02_Company_Delay  03_Consultant_Delay
```

## 01 — Documents Not Sent

A document belongs here when the Cleaner document inventory contains the document but its canonical transaction history contains **no SEND event**.

The Cleaner inventory is essential: a document with zero transactions produces zero Logbook rows, so this list cannot be calculated from the Logbook alone.

Current fields include document title, WBS, sheet, last known action (if any), and calculation state.

## 02 — Company Response Delay

Responsibility returns to the company when the latest canonical event is a consultant/client **RECEIVE** whose response status requires another company submission. The initial default response-required statuses are:

- `CM`
- `RJ`

This vocabulary is configurable.

For a dated response:

```text
Elapsed Company Response Days = Status Date - Receive Date
Company Delay Days = max(0, Elapsed Days - Company Allowance)
```

A later SEND moves responsibility away from the company and back to the consultant.

### Narrative receive without a date

A row such as:

```text
LINE / ROUTE PLAN AND PROFILE / Rev A
Receive text = پیرو مذاکرات صورت گرفته
Status = CM
```

is a real receive-state event and is kept in this list when it is the latest actionable state. Because the narrative has no canonical Jalali date, the list records:

```text
calculation_status = NEEDS_DATE
delay_days = null
```

The system never invents a date from narrative text.

## 03 — Consultant Response Delay

Responsibility is with the consultant when the latest canonical event is a company **SEND** and no later RECEIVE exists.

For a dated send:

```text
Elapsed Consultant Response Days = Status Date - Send Date
Consultant Delay Days = max(0, Elapsed Days - Consultant Allowance)
```

Once a RECEIVE arrives, the document leaves this list. If that RECEIVE is `CM`/`RJ`, it may move into the Company Delay list instead.

## Current-state model

The three lists are current exception lists, not historical cycle KPIs. Historical response durations can still be calculated later from every SEND→RECEIVE and RECEIVE→next SEND pair, but they do not define membership in these three operational lists.

## Output files

The CLI writes:

```text
engineering_lists/
├── 01_Not_Sent.csv
├── 02_Company_Delay.csv
├── 03_Consultant_Delay.csv
└── engineering_three_lists.json
```

## CLI

```bash
python ./pipeline/weekly_report_pipeline.py engineering-lists \
  --run-dir ./runs/<RUN_ID> \
  --project AZD \
  --status-date 1405/07/15 \
  --company-allowance-days 0 \
  --consultant-allowance-days 0
```

Until contractual/management response allowances are configured, an allowance of `0` means `delay_days` equals elapsed days. Configure the allowances before using the values as contractual delay attribution.
