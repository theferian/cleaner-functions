# Fresh workbook run

A newly retrieved workbook must start with an explicit fresh run:

```powershell
python .\pipeline\azd_pipeline.py --new-run --stage M_LINE
```

The fresh run:

- starts only at `M_LINE`;
- generates a new project-prefixed run ID;
- creates a new `runs/<run-id>/resolved_state.json`;
- creates `runs/<run-id>/run_manifest.json` with workbook/profile identity;
- does not inherit run-local decisions from an older workbook;
- continues to use project-level reusable knowledge and the exception registry.

Continue the same workbook with:

```powershell
python .\pipeline\azd_pipeline.py --run-id "<run-id>" --stage <NEXT_STAGE> [--decisions ...]
```

Safety rules:

1. `--new-run` and `--run-id` are mutually exclusive.
2. `--new-run` is allowed only at `M_LINE`.
3. `--run-id` must reference an existing resolved-state file.
4. A continued run refuses a different workbook path/name or profile.
5. Retrieval/cleaning execution will later produce a new controlled workbook copy; it should begin a new acceptance run rather than reuse the raw-source run.
