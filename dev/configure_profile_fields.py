from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


DEFAULT_FIELDS = [
    {
        "key": "document_type",
        "label": "Document Type",
        "data_type": "TEXT",
        "required": False,
        "default_column": 1,
    },
    {
        "key": "name",
        "label": "Name",
        "data_type": "TEXT",
        "required": True,
        "default_column": 2,
    },
    {
        "key": "wbs",
        "label": "WBS",
        "data_type": "WBS",
        "required": True,
        "default_column": 3,
    },
]


def ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default != "" else ""
    value = input(f"{prompt}{suffix}: ").strip()
    return value if value else default


def yes_no(prompt: str, default: bool = True) -> bool:
    d = "Y" if default else "N"
    value = ask(f"{prompt} (Y/N)", d).lower()
    return value in {"y", "yes", "1", "true"}


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Edit the family data-field requirements and per-instance(sheet) "
            "column mappings in a Cleaner profile."
        )
    )
    parser.add_argument(
        "--profile",
        default=str(PROJECT_ROOT / "profiles" / "AZD.profile.json"),
    )
    args = parser.parse_args()

    path = Path(args.profile)
    profile = json.loads(path.read_text(encoding="utf-8"))
    data_model = profile.setdefault("data_model", {})
    fields = data_model.setdefault("family_fields", [])
    instances = data_model.setdefault("instances", {})

    print("\n=== FAMILY DATA FIELDS ===")
    print("These define which fields exist for this document family.")
    print("Current fields:")
    for idx, f in enumerate(fields, start=1):
        print(
            f"{idx:>2}. {f.get('key')} | {f.get('label')} | "
            f"type={f.get('data_type')} | required={f.get('required')}"
        )

    while yes_no("\nAdd another family field?", False):
        key = ask("Field key").strip()
        if not key:
            print("Field key cannot be empty.")
            continue

        label = ask("Label", key.replace("_", " ").title())
        data_type = ask("Data type", "TEXT").upper()
        required = yes_no("Required?", False)
        default_col = int(ask("Default column number", "1"))

        fields.append({
            "key": key,
            "label": label,
            "data_type": data_type,
            "required": required,
            "default_locator": {
                "kind": "COLUMN",
                "column": default_col,
            },
            "validation": {"kind": "NONE"},
            "cleaning": {},
        })

    target_sheets = (
        profile.get("structure", {}).get("m_line", {}).get("target_sheets")
        or list(instances.keys())
    )

    print("\n=== INSTANCE FIELD MAPPINGS ===")
    print(
        "Now map the family fields to the columns used by each concrete sheet instance."
    )

    for sheet in target_sheets:
        instance = instances.setdefault(
            sheet,
            {"instance_type": "SHEET", "field_map": {}},
        )
        fmap = instance.setdefault("field_map", {})

        print(f"\n--- {sheet} ---")
        for f in fields:
            key = f["key"]
            current = (
                fmap.get(key, {}).get("column")
                or f.get("default_locator", {}).get("column")
                or 1
            )
            col = int(ask(f"{f.get('label', key)} column", str(current)))
            fmap[key] = {"kind": "COLUMN", "column": col}

    path.write_text(
        json.dumps(profile, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"\nSaved profile: {path}")
    print(
        "The family field definitions and instance mappings are now available "
        "to tests, cleaners, the review JSON, and later Frappe."
    )


if __name__ == "__main__":
    main()
