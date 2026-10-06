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


def _workbooks_collection(excel):
    """Return Excel.Workbooks, tolerating weak/dynamic COM wrappers.

    Some pywin32/Excel combinations expose the running application through a
    dynamic wrapper where ``excel.Workbooks`` raises ``AttributeError`` even
    though the underlying Excel instance is alive.  ``excel.Application`` can
    still expose the collection in that state.
    """
    try:
        return excel.Workbooks
    except Exception:
        pass

    try:
        return excel.Application.Workbooks
    except Exception as exc:
        raise ExcelConnectionError(
            "Connected to Excel, but its Workbooks collection is not accessible."
        ) from exc


def _fresh_excel_application(win32_client):
    """Start a private Excel instance for a retrieved working copy."""
    dispatch_ex = getattr(win32_client, "DispatchEx", None)
    try:
        excel = (
            dispatch_ex("Excel.Application")
            if dispatch_ex is not None
            else win32_client.Dispatch("Excel.Application")
        )
        _workbooks_collection(excel)
        return excel
    except Exception as exc:
        raise ExcelConnectionError("Could not start a usable Excel instance.") from exc


def ensure_excel_workbook_open(workbook_path: str | Path, *, visible: bool = True):
    """Return/open a retrieved working copy in a usable Excel instance.

    We first reuse a healthy running Excel instance.  If the active COM object
    is present but does not expose ``Workbooks`` (a state observed with some
    pywin32/Excel combinations), we deliberately start a fresh Excel instance
    rather than failing or opening the network source.
    """
    try:
        import pythoncom
        import win32com.client
    except Exception as exc:
        raise ExcelConnectionError(
            "Opening a workbook in Excel requires Windows, desktop Excel and pywin32."
        ) from exc

    pythoncom.CoInitialize()
    wanted = Path(workbook_path).resolve()
    if not wanted.exists():
        raise FileNotFoundError(wanted)

    excel = None
    workbooks = None
    try:
        candidate = win32com.client.GetActiveObject("Excel.Application")
        workbooks = _workbooks_collection(candidate)
        excel = candidate
    except Exception:
        excel = _fresh_excel_application(win32com.client)
        workbooks = _workbooks_collection(excel)

    try:
        excel.Visible = bool(visible)
    except Exception:
        pass

    wanted_cf = str(wanted).casefold()
    try:
        for wb in workbooks:
            try:
                if str(wb.FullName).casefold() == wanted_cf:
                    return wb
            except Exception:
                continue
    except Exception:
        # A collection that cannot be enumerated is not safe to reuse.
        excel = _fresh_excel_application(win32com.client)
        workbooks = _workbooks_collection(excel)
        try:
            excel.Visible = bool(visible)
        except Exception:
            pass

    try:
        return workbooks.Open(str(wanted))
    except Exception as exc:
        raise ExcelConnectionError(f"Excel could not open retrieved workbook: {wanted}") from exc
