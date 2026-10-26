# Mass Reader V01 — Workspace, Scope and Progress prototype

**Branch:** `feature/weekly-report-cleaner-template` (not automatically switched or committed).

This is an actual local web application with a persistent SQLite backend. It requires **only Python 3.13+ standard library** and a modern browser (Edge/Chrome). It does **not** open or modify source documents. It does not require Docker, Node, OCR, or network subscriptions.

## Install (Windows CMD)

Extract the ZIP into the root of `cleaner-functions`, preserving the `mass_reader_v01` folder.

```bat
py -m pytest -q tests\test_mass_reader_v01.py
py .\MASS_READER_V01.py
```

The tool opens `http://127.0.0.1:8765/`. If Edge doesn't open automatically, type this address directly in Edge. Press **Ctrl+C** to stop the server. You can reopen later; SQLite retains the state.

To create a **sample configuration** for the two established Weekly Report search paths (creates scopes but does **not** scan anything):

```bat
py .\MASS_READER_V01.py --seed-weekly-reports
```

These two predefined search locations are:

- `W:\پیگیری پروژه ها\گزارش هفتگی پروژه ها`
- `Y:\Planning Department`

## Normal operation

1. Create a **Workspace**. This can be an EPC project, another company, accounting drive, or a custom investigation area.
2. Add one or more **source scopes**: absolute local/UNC/mapped-drive path (folder **or file**), enable/disable, recursion, maximum depth, filename/path inclusion and exclusion patterns, and specific allow overrides.
3. Open **Progress & runs**. Choose **100** for a small batch or **0** for unrestricted discovery. Click **Start new scan**.
4. After `PAUSED` at a batch boundary, click **Resume**. You can stop and relaunch the app; the run and its queued folders and file cursor remain in SQLite.
5. Inspect **File inventory**. All observed extensions, even unsupported and excluded entries, are recorded; excluded directories are listed as skipped **without entering them**.
6. Open the latest or prior run to review folder-by-folder progress, errors and event history. Download **area progress CSV** and **folder status CSV** from the run panel.
7. Click **Start new scan** only after a run is complete or cancelled. Subsequent runs classify file metadata as NEW, CHANGED or UNCHANGED.

## Scope rules and examples

These rules apply **relative to each scope root**, not to the whole drive:

| Setting | Example | Effect |
|---|---|---|
| Root | `Y:\Accounting` | Scan the selected location only |
| Recursive | unchecked | Inventory the immediate folder's files; don't enter child folders |
| Max depth | `2` | Descend at most 2 folder levels |
| Include | `*.xlsx` and `*.pdf` | Mark other observed files OUTSIDE_INCLUDE, still inventory them |
| Exclude | `Archive/**` | Skip entering the Archive directory |
| Exclude | `~$*` | Mark Excel lock files EXCLUDED |
| Override | `Archive/Approved.xlsx` | Traverse the excluded ancestor **only to reach** this specific file; all other observed siblings remain EXCLUDED |
| Exact file root | `C:\Work\report.xlsx` | Inventory a single file |

- An excluded directory is recorded as **SKIPPED**; its unseen descendants are **not** counted or examined.
- Explicit overrides take precedence over exclude and include rules. Use forward slashes in relative patterns, even on Windows.
- If a specific child of an excluded parent must be examined, add that file under **Explicit include overrides**.
- The scan does not traverse symbolic-link directories (prevents loops/escape from selected scopes).
- **User-defined overlapping paths are currently independent scope observations**: the same physical file might be counted in two scopes. Cross-scope physical deduplication is a later feature.

## Data persistence and privacy

- Database: `working\mass_reader\state.sqlite3` (kept within this repository but not tracked by Git unless you manually add it).
- Every run retains: run ID, scope snapshot, folder queue and cursor, discovered file metadata, file decisions, whether metadata changed, events, and errors.
- Files are only enumerated and `stat`-ed. No content reading, retrieval cloning, changes to Excel, OCR, network transmission, or automatic action against discovered files.
- User-defined source paths are accessible only by the account running the local Python process. The HTTP server binds to **127.0.0.1 only**.
- The dashboard is bilingual (Persian/English). Persian labels don't translate source filenames or technical identifiers.
- Stop by closing the CMD server with Ctrl+C; don't delete the `state.sqlite3` file if you want to retain history.
- Large scans can take time on network drives. Progress percentages are **observed folder queue completion** and can shift as new subfolders are found; they are not the percentage of unknown total files before discovery.

## What's implemented vs next

**V01 implemented:** workspace registry, configurable path scope and filters, read-only all-extension inventory, persistent SQLite queue, pause/resume in bounded file batches, restart recovery, per-run/per-area/per-folder progress, change detection based on size and modification time, event/error log, bilingual browser UI, CSV exports, tests.

**Not yet implemented:** parse every file's contents, group files into learned document families, infer report dates/project identity, validate document-family policies, compare file hashes/contents, use historical Weekly Report selection knowledge, map files to extraction targets, populate templates, schedule unattended re-scans. All these can connect as later *evaluation stages* on top of this persistent inventory; V01 does not pretend to evaluate file content or enforce document-family policies.

## Helpful API endpoints

- `GET /api/workspaces` — workspace overview
- `GET /api/workspaces/<id>` — scopes and runs
- `GET /api/workspaces/<id>/files?limit=100&offset=0&q=...` — inventory
- `GET /api/runs/<run-id>` — current progress, counts, source areas, error/event history
- `GET /api/runs/<run-id>/folders` — folder queue snapshot
- `GET /api/runs/<run-id>/progress.csv` — area-level export
- `GET /api/runs/<run-id>/folders.csv` — full folder-level export

POST operations are used by the dashboard only. Avoid editing the SQLite database manually while scanning.

## Git staging

Do not add the database to Git. Stage the source files and test:

```bat
git add MASS_READER_V01.py mass_reader_v01 README_MASS_READER_V01.md tests\test_mass_reader_v01.py
git diff --cached --check
py -m pytest -q tests\test_mass_reader_v01.py
```

This kit doesn't perform any Git operations itself.
