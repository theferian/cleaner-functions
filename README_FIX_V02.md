# Cleaner multi-project demonstration — v0.2 fix

**Replace only `DEMO_ALL_GENERAL_DOCS.py`** in your existing `cleaner-functions` repository with the file included here. Retain your existing `DEMO_ALL_GENERAL_DOCS_CONFIG.json`, `RUN_GENERAL_DOCUMENT_V06.py`, profile files, and Cleaner code. This patch changes only the demo controller; it never modifies a source General Document or skips a Cleaner review gate.

## What the uploaded DEMO_14050730 evidence showed

- All 7 registered `prepare-general-doc` calls **succeeded**, with a `Retrieved: input\\...` workbook path in `retrieval.log`.
- The old controller compared the copied workbook's source-preserved modification time to the freshly created log's time. It then wrongly rejected 7 valid retrieved files as `RETRIEVAL_NO_FRESH_CANDIDATE`.
- NGN passed its initial stages but stopped at `FIELD_VALIDATION` / `AWAITING_REVIEW` on run `ngn_20261022T190857`.
- No engineering lists could be consolidated because the 7 projects had no Cleaner run and NGN had not passed its validation gate.

## Run on the **same existing batch** (Windows CMD)

```cmd
cd /d "C:\Users\f.tehrani\Desktop\Weekly Report Golden\cleaner-functions"
py .\DEMO_ALL_GENERAL_DOCS.py --status-date 1405/07/30 --batch DEMO_14050730
```

This will use the existing frozen NGN snapshot/run, retrieve and stage the seven previously blocked projects, launch V06 for all runnable projects, and regenerate the shared portfolio review. `SOURCE_INVENTORY.csv`, `PROJECT_STATUS.csv`, 3 consolidated list CSVs, and `index.html` are written under `demo_review\DEMO_14050730`.

**A workbook being old is not a reason to exclude it.** Source modified time, original filename, original source path, retrieval time, selected input filename, and SHA256 are separately recorded. The selected workbook is sourced from the successful preparer's output, not an inference from file timestamps. The report date still sets the report's as-of cut-off.

## Review a paused project

```cmd
py .\DEMO_ALL_GENERAL_DOCS.py --status-date 1405/07/30 --batch DEMO_14050730 --review NGN
```

The same command with `--review JND` works **even if JND previously had no Cleaner run** (and the retrieval receipt is still accessible). If a project already has a run, review continues using its existing run ID and original batch snapshot. The controller never auto-approves exceptions. It copies available review-queue JSON files into each project's `evidence` directory and links them from the dashboard.

To regenerate only the review UI without executing Cleaner:

```cmd
py .\DEMO_ALL_GENERAL_DOCS.py --status-date 1405/07/30 --batch DEMO_14050730 --collect-only
```

## What counts as an output

- `CALCULATED`: all 3 lists exist, including legitimately empty lists (`0` means computed and empty).
- `PROVISIONAL_REVIEW_PENDING`: all 3 lists exist, but a review is still open or exceptions were accepted provisionally.
- `PARTIAL_OUTPUTS`: fewer than 3 lists were generated.
- `NOT_CALCULATED`: the pipeline stopped before it could produce engineering lists. Empty source/review output must **not** be represented as zero records.

If engineering results are provided in JSON instead of CSV, the controller can also consolidate the `not_sent`, `company_delay`, and `consultant_delay` JSON arrays (including those under `lists`, `results`, or `output`). It never fabricates document rows or classifications.

**Important:** this corrects the false freshness gate and aggregation, but it cannot turn blocked structural/field-validation runs into validated engineering reports without resolving those Cleaner review queues. The user's project drive and local repository cannot be executed inside ChatGPT; the integration test only uses synthetic sources and a simulated runner.
