from __future__ import annotations

import csv
import json
from pathlib import Path

from .three_lists import EngineeringThreeLists


COLUMNS = [
    "source_sheet", "document_index", "doc_name", "doc_wbs", "revision",
    "responsibility", "current_holder", "responsible_unit", "unit_basis",
    "responsibility_since", "responsibility_age_days",
    "state", "last_action_date", "last_action_text", "status", "status_meaning",
    "elapsed_days", "allowance_days", "delay_days", "calculation_status",
]


def write_three_lists_json(result: EngineeringThreeLists, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    return path


def write_three_lists_csv(result: EngineeringThreeLists, directory: str | Path) -> dict[str, Path]:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    outputs = {}
    for name, rows in (
        ("01_Not_Sent", result.not_sent),
        ("02_Company_Delay", result.company_delay),
        ("03_Consultant_Delay", result.consultant_delay),
        ("04_Delay_Register", result.delay_register()),
    ):
        path = directory / f"{name}.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=COLUMNS, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow(row.to_dict())
        outputs[name] = path
    return outputs
