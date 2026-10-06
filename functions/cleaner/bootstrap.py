from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, asdict
from datetime import datetime
import json
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class SheetProbe:
    sheet: str
    max_row: int
    max_col: int
    identifier_rows: int
    transaction_cells: int
    header_hits: tuple[str, ...]
    selected: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["header_hits"] = list(self.header_hits)
        return payload


HEADER_TERMS = (
    "send",
    "receive",
    "status",
    "rev",
    "ارسال",
    "دریافت",
    "وضعیت",
)


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def inspect_general_document_workbook(path: str | Path) -> list[SheetProbe]:
    """Conservatively identify General-Document data sheets.

    A sheet is selected when it has repeated identifier content in B/C and
    non-empty transaction-board content at D or later.  Header terms are
    evidence only; they are deliberately not mandatory because historical
    project templates are inconsistent.
    """
    from openpyxl import load_workbook

    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)

    keep_vba = path.suffix.lower() in {".xlsm", ".xltm"}
    wb = load_workbook(path, read_only=False, data_only=False, keep_vba=keep_vba)
    try:
        probes: list[SheetProbe] = []
        for ws in wb.worksheets:
            max_row = int(ws.max_row or 0)
            max_col = int(ws.max_column or 0)
            identifier_rows = 0
            transaction_cells = 0
            for row in range(3, max_row + 1):
                b = _text(ws.cell(row=row, column=2).value) if max_col >= 2 else ""
                c = _text(ws.cell(row=row, column=3).value) if max_col >= 3 else ""
                if b or c:
                    identifier_rows += 1
            if max_col >= 4:
                for row in range(1, min(max_row, 80) + 1):
                    for col in range(4, max_col + 1):
                        if _text(ws.cell(row=row, column=col).value):
                            transaction_cells += 1

            header_blob = " ".join(
                _text(ws.cell(row=r, column=c).value).casefold()
                for r in range(1, min(max_row, 3) + 1)
                for c in range(1, min(max_col, 40) + 1)
            )
            hits = tuple(term for term in HEADER_TERMS if term.casefold() in header_blob)
            selected = (
                ws.sheet_state == "visible"
                and max_col >= 4
                and identifier_rows >= 2
                and transaction_cells >= 2
            )
            if selected:
                reason = "identifier columns B/C + transaction board D+ detected"
            elif ws.sheet_state != "visible":
                reason = f"sheet_state={ws.sheet_state}"
            elif max_col < 4:
                reason = "fewer than four used columns"
            elif identifier_rows < 2:
                reason = "insufficient identifier rows in B/C"
            else:
                reason = "insufficient transaction-board content in D+"
            probes.append(
                SheetProbe(
                    sheet=str(ws.title),
                    max_row=max_row,
                    max_col=max_col,
                    identifier_rows=identifier_rows,
                    transaction_cells=transaction_cells,
                    header_hits=hits,
                    selected=selected,
                    reason=reason,
                )
            )
        return probes
    finally:
        wb.close()


def _sheet_instance() -> dict[str, Any]:
    return {
        "instance_type": "SHEET",
        "field_map": {
            "document_type": {"kind": "COLUMN", "column": 1},
            "name": {"kind": "COLUMN", "column": 2},
            "wbs": {"kind": "COLUMN", "column": 3},
        },
    }


def build_general_document_profile(
    *,
    project_id: str,
    workbook_path: str | Path,
    base_profile_path: str | Path,
    output_path: str | Path,
    sheets: Iterable[str] | None = None,
    overwrite: bool = False,
) -> tuple[Path, dict[str, Any]]:
    project_id = str(project_id).strip().upper()
    workbook_path = Path(workbook_path)
    base_profile_path = Path(base_profile_path)
    output_path = Path(output_path)

    if output_path.exists() and not overwrite:
        raise FileExistsError(
            f"Project profile already exists: {output_path}. Use overwrite=True only if you intend to rebuild it."
        )

    base = json.loads(base_profile_path.read_text(encoding="utf-8"))
    probes = inspect_general_document_workbook(workbook_path)
    if sheets is None:
        selected = [p.sheet for p in probes if p.selected]
    else:
        requested = [str(x).strip() for x in sheets if str(x).strip()]
        existing = {p.sheet for p in probes}
        missing = [x for x in requested if x not in existing]
        if missing:
            raise ValueError(f"Requested sheet(s) not found in workbook: {missing}")
        selected = requested

    if not selected:
        raise RuntimeError(
            "No General-Document data sheets were selected. Inspect the workbook probe and rerun with explicit --sheet values."
        )

    profile = deepcopy(base)
    profile["profile_name"] = project_id
    profile["workbook"] = {"expected_sheets": list(selected)}
    profile.setdefault("structure", {}).setdefault("m_line", {})["target_sheets"] = list(selected)
    profile.setdefault("data_model", {})["instances"] = {
        sheet: _sheet_instance() for sheet in selected
    }
    profile["known_exceptions"] = []
    profile["known_fixes"] = []
    profile["bootstrap"] = {
        "template": "GENERAL_DOCUMENT",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "project_id": project_id,
        "source_workbook": str(workbook_path),
        "selected_sheets": list(selected),
        "probe": [p.to_dict() for p in probes],
        "note": (
            "Bootstrapped from family rules only. No AZD project fixes or exceptions were inherited; "
            "project-specific knowledge must be learned through review."
        ),
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(profile, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return output_path, profile
