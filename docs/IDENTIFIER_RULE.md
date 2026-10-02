# AZD Identifier Rule — Name and WBS

## Family fields

The profile now separates:

```text
Family field definition
        ↓
Concrete instance/sheet mapping
```

Default AZD family fields:

```text
document_type → column A
name          → column B
wbs           → column C
```

These are not hard-coded in the test. They are stored under:

```text
data_model.family_fields
data_model.instances
```

Use:

```powershell
python .\dev\configure_profile_fields.py
```

to add fields and change per-sheet mappings.

This configuration contract is intended to map naturally into Frappe later.

## Name rule

`name` is required.

If an identifier record has no Name, the machine proposes:

```text
ERR_EMPT_NAME_{ROW_NUMBER}
```

Example:

```text
row 47 → ERR_EMPT_NAME_47
```

The proposed change is stored as a machine `SET_VALUE` suggestion and must
still be reviewed.

## WBS rule

Current provisional validation:

```regex
^\d+(?:\.\d+)*$
```

Examples considered valid:

```text
1
1.2
1.2.5
01.003.12
```

Empty cells, `-`, and other non-matching values are invalid.

### Suggested cleaning

Scan top-to-bottom.

If the closest valid WBS above is:

```text
1.4.2
```

then invalid WBS values below it are proposed as:

```text
1.4.2.1000
1.4.2.1001
1.4.2.1002
```

When a new valid WBS appears, numbering restarts from `.1000` under that WBS.

If there is no valid WBS above, fallback proposals are:

```text
1000
1001
1002
```

This strategy is profile-configured and can be replaced later when WBS
validation becomes its own independent rule.

## Current record-detection limitation

Explicit document data boundaries are not modeled yet.

For now, the check treats a row as a logical identifier record when at least
one mapped identifier field carries its own value/merge anchor.

Rows that are only covered by large separator/background merges anchored in
another column are ignored.

The next boundary function should replace this provisional record-detection
method with explicit document regions.
