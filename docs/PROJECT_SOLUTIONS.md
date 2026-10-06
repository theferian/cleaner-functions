# Project Solutions

Project solutions are persistent, project-scoped approved repairs. They are intentionally separate from:

- family/profile rules: how a document family/project is interpreted;
- exception cases: unresolved anomalies that remain under investigation;
- run state: decisions and overlays for one cleaner run.

Default registry: `project_solutions/<PROJECT>.solutions.json`.

A solution stores:

- a stable project handle such as `AZD-SOL-0001`;
- source test and status;
- document identity (primarily document Name, plus document type / valid WBS when available);
- semantic field context (`field_key`, `field_role`, `audit_kind`, transaction index);
- the observed bad value where useful;
- the approved workbook repair;
- a physical cell/range only as a fallback;
- confirmation/history metadata.

Matching order on later revisions:

1. same project registry;
2. same test/sheet;
3. same document identity;
4. same semantic field context;
5. same observed problem, when stored;
6. exact old target only as a fallback.

This lets a solution follow a document after row movement between weekly revisions without applying it globally to other projects.

Reviewed deterministic workbook changes are synchronized into the project registry automatically by the reviewer and pipeline decision ingestion. Existing decision files can be backfilled with:

```powershell
python .\dev\project_solutions.py sync <decision-file> --project AZD
```

List active solutions with:

```powershell
python .\dev\project_solutions.py list --project AZD
```

## Revision-stable identity and registry repair

Project solutions are project-scoped memory, not run-local decisions. New solutions
store two row-shift-resistant anchors when available:

- logical document identity (primarily Document Name, plus stable type/WBS context),
- `document_relative_target`, e.g. `H+0:H+1`, describing the field position inside
  the logical document card rather than its absolute worksheet row.

This allows an AZD repair approved at `H11:H12` to follow the same document if it
moves to another row in a later weekly revision, while keeping two different repairs
inside the same document distinct.

Legacy/contextless solutions retain their absolute target as a fallback. For those
solutions, the target participates in the signature so separate cells cannot collapse
into one solution.

### Repairing a legacy registry

After upgrading an existing repository, run the migration against a run that already
contains `document_regions.json`:

```powershell
python .\dev\project_solutions.py repair --project AZD --run-dir ".\runs\azd_20261006T063256"
```

The repair command:

1. enriches target-only solutions with document identity and relative target;
2. splits historical collision records where the match target and stored resolution
   target disagree;
3. consolidates equivalent target-only/rich-identity duplicates;
4. preserves superseded entries as disabled audit records rather than deleting them.

`list` shows active solutions only. Superseded solutions remain in the JSON registry
with `enabled=false` and `superseded_by`.

### Manual one-time migration

For an old repair whose original evidence is no longer available, add it explicitly:

```powershell
python .\dev\project_solutions.py add --project AZD \
  --run-dir ".\runs\azd_20261006T063256" \
  --test-id FIELD_VALIDATION --sheet "63KV SS" --target H13 \
  --observed "140/08/10" --value "1404/08/10" \
  --audit-kind GLOBAL_DATE_TOKEN_SCAN
```

Future manual `SET_VALUE` reviews preserve the observed value and semantic evidence
automatically, so this recovery command should only be needed for legacy decisions.
