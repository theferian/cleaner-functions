# Data Field Model 0.1

The profile now has two levels.

## 1. Family fields

These answer:

> What data fields does this document family need?

Example:

```json
{
  "key": "name",
  "label": "Name",
  "data_type": "TEXT",
  "required": true,
  "default_locator": {
    "kind": "COLUMN",
    "column": 2
  }
}
```

## 2. Instance mappings

These answer:

> Where is that family field located in this concrete workbook/sheet instance?

Example:

```json
{
  "230KV SS": {
    "instance_type": "SHEET",
    "field_map": {
      "name": {"kind": "COLUMN", "column": 2},
      "wbs": {"kind": "COLUMN", "column": 3}
    }
  }
}
```

This separation is useful for Frappe:

```text
Document Family
    1 ── n Family Field

Document/Profile Instance
    1 ── n Field Mapping
```

The current CLI configuration tool is:

```powershell
python .\dev\configure_profile_fields.py
```

Later, Frappe can render exactly the same schema as editable child tables/forms.
