from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .contracts import BoardToLogResult




ISSUE_COLUMNS = [
    "kind",
    "sheet",
    "document_index",
    "address",
    "message",
    "evidence",
]


LOGBOOK_COLUMNS = [
    "project_id",
    "source_run_id",
    "source_workbook",
    "source_sheet",
    "document_index",
    "doc_type",
    "doc_type_a",
    "doc_type_b",
    "doc_name",
    "doc_code",
    "doc_wbs",
    "send_or_receive",
    "doc_rev",
    "event_index",
    "letter_date",
    "letter_reference",
    "doc_status",
    "transaction_mode",
    "source_row",
    "source_col",
    "date_source",
    "reference_source",
    "status_source",
    "block_index",
    "raw_source_value",
]


def write_json(result: BoardToLogResult, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    return path


def write_csv(result: BoardToLogResult, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=LOGBOOK_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for record in result.records:
            writer.writerow(record.to_dict())
    return path


def write_issues_csv(result: BoardToLogResult, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=ISSUE_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for issue in result.issues:
            payload = issue.to_dict()
            payload["evidence"] = json.dumps(payload.get("evidence") or {}, ensure_ascii=False, default=str)
            writer.writerow(payload)
    return path


def write_excel_com(
    result: BoardToLogResult,
    *,
    workbook_path: str | Path,
    sheet_name: str = "Logbook",
    save: bool = True,
) -> dict[str, Any]:
    """Write the canonical Logbook through Excel COM on Windows.

    Kept optional/lazy so extraction and tests remain platform-independent.
    """
    try:
        import win32com.client as win32
    except Exception as exc:  # pragma: no cover - Windows-only surface
        raise RuntimeError("Excel COM writer requires pywin32 on Windows.") from exc

    wanted = str(Path(workbook_path).resolve()).lower()
    try:
        excel = win32.GetActiveObject("Excel.Application")
    except Exception:
        excel = win32.Dispatch("Excel.Application")
    excel.Visible = True

    wb = None
    for candidate in excel.Workbooks:
        try:
            if str(Path(candidate.FullName).resolve()).lower() == wanted:
                wb = candidate
                break
        except Exception:
            continue
    opened = False
    if wb is None:
        wb = excel.Workbooks.Open(str(Path(workbook_path).resolve()))
        opened = True

    old_alerts = excel.DisplayAlerts
    try:
        excel.DisplayAlerts = False
        for ws in wb.Worksheets:
            if ws.Name == sheet_name:
                ws.Delete()
                break
        ws = wb.Worksheets.Add()
        ws.Name = sheet_name
        for col, header in enumerate(LOGBOOK_COLUMNS, start=1):
            ws.Cells(1, col).Value = header
        for row, record in enumerate(result.records, start=2):
            payload = record.to_dict()
            for col, header in enumerate(LOGBOOK_COLUMNS, start=1):
                value = payload.get(header)
                if value is not None:
                    ws.Cells(row, col).Value = value
        ws.Rows(1).Font.Bold = True
        ws.Rows(1).AutoFilter()
        ws.Columns.AutoFit()
        if save:
            wb.Save()
    finally:
        excel.DisplayAlerts = old_alerts

    return {
        "workbook": wb.Name,
        "sheet": sheet_name,
        "records": len(result.records),
        "opened_by_writer": opened,
        "saved": save,
    }


def _canonical_scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        number = float(value)
        return int(number) if number.is_integer() else number
    return str(value)


def canonical_record_digest(records) -> str:
    """Stable digest used to prove the written Logbook round-trips losslessly."""
    import hashlib
    rows = []
    for record in records:
        payload = record.to_dict() if hasattr(record, "to_dict") else dict(record)
        rows.append([_canonical_scalar(payload.get(col)) for col in LOGBOOK_COLUMNS])
    blob = json.dumps(rows, ensure_ascii=False, default=str, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _record_matrix(result: BoardToLogResult) -> list[list[Any]]:
    return [
        [record.to_dict().get(header) for header in LOGBOOK_COLUMNS]
        for record in result.records
    ]


def write_logbook_to_workbook_com(
    workbook,
    result: BoardToLogResult,
    *,
    sheet_name: str = "Logbook",
) -> dict[str, Any]:
    """Write canonical records into an already-open controlled workbook copy."""
    excel = workbook.Application
    old_alerts = excel.DisplayAlerts
    try:
        excel.DisplayAlerts = False
        for ws in workbook.Worksheets:
            if ws.Name == sheet_name:
                ws.Delete()
                break
        ws = workbook.Worksheets.Add()
        ws.Name = sheet_name

        col_count = len(LOGBOOK_COLUMNS)
        # Avoid Cell.Address(...) here. Depending on the pywin32 dispatch
        # wrapper/Excel version, Address may be exposed as a string property
        # instead of a callable method. A two-cell Range is unambiguous and
        # works consistently across both COM shapes.
        ws.Range(ws.Cells(1, 1), ws.Cells(1, col_count)).Value2 = (tuple(LOGBOOK_COLUMNS),)

        # Explicit text columns prevent Excel from coercing WBS/date/reference IDs.
        text_columns = {
            "project_id", "source_run_id", "source_workbook", "source_sheet",
            "doc_type", "doc_type_a", "doc_type_b", "doc_name", "doc_code",
            "doc_wbs", "send_or_receive", "doc_rev", "letter_date",
            "letter_reference", "doc_status", "transaction_mode", "date_source", "reference_source",
            "status_source", "raw_source_value",
        }
        for idx, header in enumerate(LOGBOOK_COLUMNS, start=1):
            if header in text_columns:
                ws.Columns(idx).NumberFormat = "@"

        matrix = _record_matrix(result)
        if matrix:
            end_row = len(matrix) + 1
            ws.Range(ws.Cells(2, 1), ws.Cells(end_row, col_count)).Value2 = tuple(tuple(row) for row in matrix)
        else:
            end_row = 1

        ws.Rows(1).Font.Bold = True
        ws.Rows(1).AutoFilter()
        ws.Columns.AutoFit()
        for idx in range(1, col_count + 1):
            if ws.Columns(idx).ColumnWidth > 40:
                ws.Columns(idx).ColumnWidth = 40

        return {
            "sheet": sheet_name,
            "records_written": len(matrix),
            "columns_written": col_count,
            "expected_digest": canonical_record_digest(result.records),
        }
    finally:
        excel.DisplayAlerts = old_alerts


def validate_logbook_workbook_com(
    workbook,
    result: BoardToLogResult,
    *,
    sheet_name: str = "Logbook",
) -> dict[str, Any]:
    """Read the controlled copy back through Excel and compare canonical rows."""
    ws = workbook.Worksheets(sheet_name)
    col_count = len(LOGBOOK_COLUMNS)
    record_count = len(result.records)

    headers_raw = ws.Range(ws.Cells(1, 1), ws.Cells(1, col_count)).Value2
    headers = list(headers_raw[0]) if headers_raw else []
    if headers != LOGBOOK_COLUMNS:
        raise RuntimeError(f"Logbook header validation failed: {headers!r}")

    rows: list[dict[str, Any]] = []
    if record_count:
        raw = ws.Range(ws.Cells(2, 1), ws.Cells(record_count + 1, col_count)).Value2
        for values in raw:
            rows.append(dict(zip(LOGBOOK_COLUMNS, values)))

    expected_digest = canonical_record_digest(result.records)
    actual_digest = canonical_record_digest(rows)
    if expected_digest != actual_digest:
        raise RuntimeError(
            "Logbook read-back validation failed: canonical digest differs from extracted records."
        )

    return {
        "validated": True,
        "record_count": record_count,
        "column_count": col_count,
        "digest": actual_digest,
    }
