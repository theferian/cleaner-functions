# Mass Reader V02 — Responsive stop + stable progress UI

**Branch**: `feature/weekly-report-cleaner-template`.

Fixes:

- Explicit `PAUSING` and `CANCELLING` states until the worker acknowledges its stop request.
- Stop checks between files and during large folder enumerations. Remote filesystem calls can delay acknowledgement until the OS returns.
- Restore unfinished directory status to `PENDING` when paused, cancelled, or interrupted.
- Prevent a new run or editing a scope while a stop is still in progress.
- Preserve the existing run ID, cursor, file inventory, and historical events; no SQLite migration and no source workbook mutation.
- Live browser polling updates only changed numbers/tables; doesn't rebuild the entire progress panel, reset its scroll position, or forget the selected run.
- Fixed-height folder and event panels prevent vertical layout jumps during discovery.

### Installation from the repository root (Windows CMD)

1. Stop the old Mass Reader **server** with Ctrl+C in its CMD window. Do not delete the database.
2. Extract this ZIP into the `cleaner-functions` repository root. The patch payload lives under `mass_reader_v02_update` and will **not** overwrite V01 until you run the installer.
3. Preview:

```bat
py .\INSTALL_MASS_READER_V02.py --check
```

4. Apply:

```bat
py .\INSTALL_MASS_READER_V02.py --apply
```

If the installer warns of locally modified source files, review the warning before choosing `--apply --allow-modified` (it takes backups before replacement).

5. Test:

```bat
py -m pytest -q tests\test_mass_reader_v01.py tests\test_mass_reader_v02.py
```

6. Launch on the working port:

```bat
py .\MASS_READER_V01.py --port 8877
```

7. Open `http://127.0.0.1:8877/` and press **Ctrl+Shift+R** once in Edge to reload the updated JavaScript.

### Behaviour

- Budget = 100 means 100 files **per start/resume call**; the run becomes `PAUSED` with remaining folders pending. It is not supposed to finish all folders in that batch.
- Pause or Cancel during an unlimited scan shows a transitional state until the active worker acknowledges it.
- Pause can resume using the **same** run ID; Cancel is terminal, keeping evidence and history.
- On a slow or disconnected network drive, an operating-system directory call may be blocked; stop completes when that call returns. Force-killing the server leaves a resumable checkpoint.
- Only folder/file enumeration and metadata are performed; original workbooks are not opened or saved.

### Files modified by installer

`mass_reader_v01/core.py`, `mass_reader_v01/static/app.js`, `mass_reader_v01/static/app.css`, `mass_reader_v01/static/index.html`; adds `tests/test_mass_reader_v02.py`.

Backups of existing code go to `working\mass_reader\patch_backups\v02_*`. `working\mass_reader\state.sqlite3` is never modified by the installer (the app naturally continues to record scan progress when running).
