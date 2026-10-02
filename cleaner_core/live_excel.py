from __future__ import annotations

from pathlib import Path
import tempfile
import uuid


class ExcelConnectionError(RuntimeError):
    pass


class SnapshotError(RuntimeError):
    pass


def attach_excel_workbook(workbook_name: str | None = None):
    """
    Attach to an already-running Excel application.

    If workbook_name is omitted, use the active workbook.
    This layer only obtains the handle; analysis is performed on a SaveCopyAs
    snapshot, not by iterating cells through COM.
    """
    try:
        import pythoncom
        import win32com.client
    except Exception as exc:
        raise ExcelConnectionError(
            "Live Excel requires Windows, desktop Excel and pywin32."
        ) from exc

    pythoncom.CoInitialize()

    try:
        excel = win32com.client.GetActiveObject("Excel.Application")
    except Exception as exc:
        raise ExcelConnectionError(
            "No accessible running Excel instance was found."
        ) from exc

    if workbook_name:
        wanted = workbook_name.casefold()
        for wb in excel.Workbooks:
            if str(wb.Name).casefold() == wanted or str(wb.FullName).casefold() == wanted:
                return wb
        raise ExcelConnectionError(f"Open workbook not found: {workbook_name}")

    wb = excel.ActiveWorkbook
    if wb is None:
        raise ExcelConnectionError("Excel is running but has no active workbook.")
    return wb


def snapshot_live_workbook(workbook, destination: str | Path | None = None) -> Path:
    """
    Save a temporary copy of the *current live Excel state* using SaveCopyAs.

    The open workbook remains open and its saved/unsaved state is not changed.
    openpyxl analyzes the copy, avoiding slow Python<->Excel per-cell COM calls.
    """
    name = str(workbook.Name)
    suffix = Path(name).suffix.lower()

    if suffix not in {".xlsx", ".xlsm", ".xltx", ".xltm"}:
        raise SnapshotError(
            f"Fast snapshot analysis currently supports .xlsx/.xlsm/.xltx/.xltm, not {suffix or '<no extension>'}."
        )

    if destination is None:
        temp_dir = Path(tempfile.gettempdir()) / "cleaner_snapshots"
        temp_dir.mkdir(parents=True, exist_ok=True)
        destination = temp_dir / f"{Path(name).stem}_{uuid.uuid4().hex[:10]}{suffix}"
    else:
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)

    try:
        workbook.SaveCopyAs(str(destination))
    except Exception as exc:
        raise SnapshotError(f"Excel SaveCopyAs failed: {exc}") from exc

    if not Path(destination).exists():
        raise SnapshotError("Excel reported success but the snapshot file was not created.")

    return Path(destination)
