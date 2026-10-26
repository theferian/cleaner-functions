# Multi-Project General Doc Cleaner demo

Place these 3 files **in the root** of your existing `cleaner-functions` repository, alongside `RUN_GENERAL_DOCUMENT_V06.py` and the existing `pipeline/` folder. Uses Python standard library; does not require Docker.

## One-line Windows CMD launch

```cmd
cd /d "C:\Users\f.tehrani\Desktop\Weekly Report Golden\cleaner-functions"
py .\DEMO_ALL_GENERAL_DOCS.py --status-date 1405/07/30 --batch DEMO_14050730
```

Or run `RUN_DEMO_GENERAL_DOCS.cmd` for the same date and batch ID. The date is **30 Mehr 1405 = 22 October 2026**. Change the date and batch ID for later demonstrations. The batch controller does **not** run unit tests or alter your existing repository tests.

## What happens

1. For registered projects AZD, JND, FSH, YSK, EYV, BFG, NKH, invoke the existing `pipeline/weekly_report_pipeline.py prepare-general-doc --project CODE --overwrite` against `configs/project_control_sources.json`. Only this retrieved input copy is overwritten, not original network workbooks. The latest dated candidate from the established `input/*_LATEST_GENERAL_DOC_*.xlsx` naming pattern is then selected. A provenance receipt records the path, modification date, and SHA256; verify that your registry points to the current official General Doc.
2. For NGN, use the **explicit known source path**, since earlier runs identified a distinct no-WBS `MOBILE SS` layout. Edit `DEMO_ALL_GENERAL_DOCS_CONFIG.json` if the official NGN source has moved. A review gate is expected until its source identifier profile is approved.
3. Hash and copy the original to `demo_review/<batch>/projects/<CODE>/source/`. Once the batch is staged, running the same batch ID reuses this immutable copy even if source network files change.
4. Invoke `RUN_GENERAL_DOCUMENT_V06.py --new-run --workbook SNAPSHOT --project CODE --status-date DATE --non-interactive`. V06 performs 6 Cleaner stages, Board→Log, Coverage, and Engineering lists; stops at real review gates instead of inventing decisions. Next projects continue.
5. Collect outputs under the same folder; generate portfolio CSVs, statuses, an offline searchable HTML review page, and source and run manifests.

## Main output files

```
demo_review/DEMO_14050730/
  index.html                         <- central offline review
  PROJECT_STATUS.csv                 <- project source, run, state, counts, diagnostics
  ALL_01_Not_Sent.csv
  ALL_02_Company_Delay.csv
  ALL_03_Consultant_Delay.csv
  ALL_Diagnostics.csv
  portfolio_manifest.json
  projects/AZD/
    source/General - Azad.xlsx       <- immutable snapshot; actual name retained
    retrieval.log
    cleaner.log
    state.json
    outputs/                       <- 3 CSVs + JSON (+ Delay Register when present)
    evidence/                      <- Coverage, Board->Log, run manifest
  projects/JND/...                 <- same structure for all 8 projects
```

The initial run can pause with `REVIEW_REQUIRED` on structural anomalies or Engineering diagnostics. No results exist for a project until it reaches the output stage, and a missing output is **not counted as zero**.

## Resolve reviews one project at a time

```cmd
py .\DEMO_ALL_GENERAL_DOCS.py --status-date 1405/07/30 --batch DEMO_14050730 --review JND
```

This runs V06 interactively using the **same run ID and immutable working snapshot**. After approval it automatically regenerates the consolidated dashboard. Repeat for another paused project; do **not** start a new run for an unresolved project.

To refresh all status views without touching sources or running Cleaner:

```cmd
py .\DEMO_ALL_GENERAL_DOCS.py --status-date 1405/07/30 --batch DEMO_14050730 --collect-only
```

To retrieve and stage only, without running the cleaner:

```cmd
py .\DEMO_ALL_GENERAL_DOCS.py --status-date 1405/07/30 --batch SOURCES_14050730 --retrieve-only
```

To demo fewer projects first:

```cmd
py .\DEMO_ALL_GENERAL_DOCS.py --status-date 1405/07/30 --batch FIRST3_14050730 --projects AZD,JND,FSH
```

## Guardrails and limitations

- Network originals are never written by this controller. It makes snapshots and passes them to the existing Cleaner runner.
- Source retrieval depends on **your local source registry**, network drive availability, and the installed repo. This package cannot verify those from ChatGPT. If your registry has changed its CLI or its retrieved-file naming, `SOURCE_REVIEW` makes that visible; do not silently fall back to an unverified workbook.
- The GUI does not claim `COMPLETE` for a project paused on review. `COMPLETE_WITH_REVIEWED_EXCEPTIONS` still requires business sign-off.
- The date attached to a retrieved input file is not proof of the latest source revision. The source provenance needs a human confirmation of the correct official General Doc before formal release.
- No automatic remediation or fabricated WBS, dates, letters, or statuses. V06 controls the review process.
- The offline dashboard is read-only and does not change Cleaner decisions. Open `index.html` from its folder in Chrome/Edge.
