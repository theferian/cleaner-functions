# Reusable Status Library

`configs/status_library.json` is the persistent semantic catalog for engineering-document status codes.

The Cleaner keeps two concepts separate:

1. **Inferred workbook vocabulary** — codes common enough in the current workbook to be learned statistically.
2. **Reusable status library** — known valid codes and their business meaning, even when they are rare in a workbook.

A status passes validation when it is either inferred from the workbook or explicitly known in the reusable library.

## Definition fields

- `code`: canonical status code.
- `aliases`: explicit formatting/legacy aliases. Punctuation is never guessed automatically.
- `meaning`: English business meaning.
- `meaning_fa`: Persian business meaning.
- `responsibility_after_receive`: `COMPANY`, `CONSULTANT`, `NONE`, or null when not yet defined.
- `action_required`: whether this received status creates an open action.
- `notes`: free-text project-control explanation.
- `source`: provenance of the definition.

The initial confirmed definition is `RJ = Rejected / رد شده`; after a received `RJ`, responsibility is on the company to revise/respond.

## CLI

List the catalog:

```bash
python ./dev/status_library.py list
```

Inspect one status:

```bash
python ./dev/status_library.py show RJ
```

Add or update a status once its meaning is confirmed:

```bash
python ./dev/status_library.py add CODE --meaning "..." --meaning-fa "..." --responsibility COMPANY --action-required yes
```

Add an explicit alias only when the equivalence is confirmed:

```bash
python ./dev/status_library.py add CM --alias C.M
```

The library deliberately does not infer that visually similar codes such as `CM` and `C.M`, or `FC` and `F.C`, are semantically identical. That relationship must be confirmed and recorded explicitly.
