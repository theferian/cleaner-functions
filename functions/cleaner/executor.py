from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path, PureWindowsPath
from typing import Any


@dataclass(frozen=True)
class WorkbookChange:
    kind: str
    sheet: str
    target: str
    value: Any = None
    expected_old_value: Any = None
    source_review_id: str | None = None
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_change_plan(state: dict[str, Any]) -> list[WorkbookChange]:
    """Build deterministic physical workbook changes from resolved state.

    Only structured workbook changes are executable here. Profile/test changes,
    tracked exceptions and manual notes remain metadata and are never silently
    applied to Excel.
    """
    changes: list[WorkbookChange] = []

    # Unmerge first so later value writes can target formerly merged cells.
    for op in state.get("merge_operations", []):
        if str(op.get("action") or "").upper() != "UNMERGE_RANGE":
            continue
        if op.get("sheet") and op.get("target"):
            changes.append(WorkbookChange(
                kind="UNMERGE_RANGE",
                sheet=str(op["sheet"]),
                target=str(op["target"]),
                source_review_id=op.get("source_review_id"),
                reason=str(op.get("reason") or ""),
            ))

    # Value overrides are already the final logical value for each target.
    for key in sorted((state.get("value_overrides") or {}).keys()):
        item = state["value_overrides"][key]
        sheet = str(item.get("sheet") or "")
        target = str(item.get("target") or "")
        if not sheet or not target:
            continue
        action = str(item.get("action") or "SET_VALUE").upper()
        kind = action if action in {"SET_VALUE", "CLEAR_CELL", "REPLACE_VALUE"} else "SET_VALUE"
        changes.append(WorkbookChange(
            kind=kind,
            sheet=sheet,
            target=target,
            value=item.get("value"),
            expected_old_value=item.get("expected_old_value"),
            source_review_id=item.get("source_review_id"),
            reason=str(item.get("reason") or ""),
        ))

    # Merge last to avoid Excel discarding values from non-anchor cells before
    # approved value changes have been written.
    for op in state.get("merge_operations", []):
        if str(op.get("action") or "").upper() != "MERGE_RANGE":
            continue
        if op.get("sheet") and op.get("target"):
            changes.append(WorkbookChange(
                kind="MERGE_RANGE",
                sheet=str(op["sheet"]),
                target=str(op["target"]),
                source_review_id=op.get("source_review_id"),
                reason=str(op.get("reason") or ""),
            ))

    return changes


def default_published_path(run, *, label: str = "CLEANED_LOGBOOK") -> Path:
    raw = str(run.workbook.get("path") or run.workbook.get("name") or "workbook.xlsx")
    # Runs created on Windows can be inspected/tested on another OS. Parse the
    # filename with Windows semantics when the stored path is Windows-shaped.
    source = PureWindowsPath(raw) if ("\\" in raw or (len(raw) > 1 and raw[1] == ":")) else Path(raw)
    suffix = source.suffix or ".xlsx"
    return run.run_dir / f"{source.stem}_{label}{suffix}"


def _normalized(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _cell_address(cell) -> str:
    try:
        return str(cell.Address)
    except Exception:
        return "<?>"


def _physical_anchors(rng) -> list[Any]:
    """Return unique physical value anchors inside a logical COM range.

    Cleaner findings can legitimately use logical slot addresses such as
    ``E19:E22``.  That address may have been one merged slot in the snapshot,
    or the live workbook may expose the same logical slot as one populated
    anchor followed by blank cells.  Publication must therefore resolve the
    logical range back to a physical value anchor instead of blindly writing
    to every cell in the range.
    """
    try:
        count = int(rng.Cells.Count)
    except Exception:
        count = 1

    anchors: dict[str, Any] = {}
    for index in range(1, count + 1):
        try:
            cell = rng.Cells.Item(index)
        except Exception:
            cell = rng.Cells(index)

        anchor = cell
        try:
            if bool(cell.MergeCells):
                anchor = cell.MergeArea.Cells(1, 1)
        except Exception:
            pass

        anchors.setdefault(_cell_address(anchor).upper(), anchor)
    return list(anchors.values())


def _resolve_value_anchor(rng, change: WorkbookChange):
    """Resolve one logical Cleaner target to one safe physical Excel anchor.

    Multi-cell logical targets are accepted only when the executor can prove
    which physical anchor is intended from either the reviewed old value or
    an already-applied wanted value.  Ambiguity remains a hard failure.
    """
    anchors = _physical_anchors(rng)
    if len(anchors) == 1:
        return anchors[0]

    expected = change.expected_old_value
    wanted = None if change.kind == "CLEAR_CELL" else change.value

    def matching(value):
        if value is None:
            return []
        return [
            cell for cell in anchors
            if _normalized(getattr(cell, "Value2", None)) == _normalized(value)
        ]

    expected_matches = matching(expected)
    if len(expected_matches) == 1:
        return expected_matches[0]
    if len(expected_matches) > 1:
        raise RuntimeError(
            f"Refusing ambiguous multi-cell value target {rng.Address}: "
            f"reviewed old value {expected!r} appears in multiple physical anchors."
        )

    # Idempotent re-publication: the reviewed change may already have been
    # applied to exactly one anchor in a copy from an earlier successful pass.
    wanted_matches = matching(wanted)
    if len(wanted_matches) == 1:
        return wanted_matches[0]
    if len(wanted_matches) > 1:
        raise RuntimeError(
            f"Refusing ambiguous multi-cell value target {rng.Address}: "
            f"wanted value {wanted!r} appears in multiple physical anchors."
        )

    # For legacy decisions without an expected-old guard, one and only one
    # populated physical anchor is still a safe deterministic target.
    if expected is None:
        populated = [
            cell for cell in anchors
            if _normalized(getattr(cell, "Value2", None)) != ""
        ]
        if len(populated) == 1:
            return populated[0]

    candidates = ", ".join(
        f"{_cell_address(cell)}={getattr(cell, 'Value2', None)!r}"
        for cell in anchors
    )
    raise RuntimeError(
        f"Refusing ambiguous multi-cell value target {rng.Address}; "
        "could not resolve one physical anchor from the reviewed values. "
        f"Candidates: {candidates}"
    )


def apply_change_plan_com(workbook, changes: list[WorkbookChange]) -> dict[str, Any]:
    """Apply approved changes to an already-open *copy* through Excel COM."""
    applied: list[dict[str, Any]] = []
    already_applied: list[dict[str, Any]] = []

    for change in changes:
        ws = workbook.Worksheets(change.sheet)
        rng = ws.Range(change.target)

        if change.kind == "UNMERGE_RANGE":
            rng.UnMerge()
            applied.append(change.to_dict())
            continue
        if change.kind == "MERGE_RANGE":
            rng.Merge()
            applied.append(change.to_dict())
            continue

        anchor = _resolve_value_anchor(rng, change)
        current = anchor.Value2
        wanted = None if change.kind == "CLEAR_CELL" else change.value

        if _normalized(current) == _normalized(wanted):
            already_applied.append({
                **change.to_dict(),
                "observed": current,
                "resolved_anchor": _cell_address(anchor),
            })
            continue

        expected = change.expected_old_value
        if expected is not None and _normalized(current) != _normalized(expected):
            raise RuntimeError(
                f"Workbook change guard failed at {change.sheet}!{change.target}: "
                f"expected old value {expected!r}, observed {current!r}, wanted {wanted!r}."
            )

        anchor.Value2 = wanted
        applied.append({
            **change.to_dict(),
            "observed_before": current,
            "resolved_anchor": _cell_address(anchor),
        })

    return {
        "planned": len(changes),
        "applied": applied,
        "already_applied": already_applied,
        "applied_count": len(applied),
        "already_applied_count": len(already_applied),
    }


def _same_path(left: str | Path, right: str | Path) -> bool:
    try:
        return str(Path(left).resolve()).casefold() == str(Path(right).resolve()).casefold()
    except Exception:
        return str(left).casefold() == str(right).casefold()


def _find_open_workbook(excel, path: Path):
    for candidate in excel.Workbooks:
        try:
            if _same_path(candidate.FullName, path):
                return candidate
        except Exception:
            continue
    return None


def _close_workbook_safely(workbook) -> None:
    if workbook is None:
        return
    try:
        workbook.Close(SaveChanges=False)
    except Exception:
        pass


def create_cleaned_copy_com(
    run,
    *,
    output_path: str | Path | None = None,
    overwrite: bool = False,
) -> tuple[Any, Any, Path, dict[str, Any]]:
    """Create/open a controlled Excel copy and apply resolved workbook changes.

    The source workbook is never saved by this function. SaveCopyAs is used so
    an already-open workbook can be copied without changing its active file.

    Failure is transactional at the file level: any copy opened/created by this
    call is closed and the failed output is removed before the exception is
    re-raised.  This prevents a failed COM pass from leaving a locked workbook.
    """
    try:
        import win32com.client as win32
    except Exception as exc:  # pragma: no cover - Windows-only surface
        raise RuntimeError("Controlled workbook publishing requires pywin32 on Windows.") from exc

    source_path = Path(str(run.workbook.get("path") or "")).resolve()
    if not str(run.workbook.get("path") or "").strip():
        raise RuntimeError("Cleaner run manifest does not contain the source workbook path.")
    if not source_path.exists():
        raise FileNotFoundError(f"Source workbook not found: {source_path}")

    destination = Path(output_path).resolve() if output_path else default_published_path(run).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)

    try:
        excel = win32.GetActiveObject("Excel.Application")
    except Exception:
        excel = win32.Dispatch("Excel.Application")
    excel.Visible = True

    copy_wb = None
    source_wb = None
    opened_source = False
    created_destination = False
    closed_existing_output = False

    try:
        # Handle a stale/previous output only after attaching to Excel so an
        # explicit --overwrite can first close that workbook if Excel still has
        # it open from a failed prior publish attempt.
        if destination.exists():
            if not overwrite:
                raise FileExistsError(
                    f"Published workbook already exists: {destination}. Use --overwrite to replace it."
                )
            open_output = _find_open_workbook(excel, destination)
            if open_output is not None:
                open_output.Close(SaveChanges=False)
                closed_existing_output = True
            destination.unlink()

        source_wb = _find_open_workbook(excel, source_path)
        if source_wb is None:
            source_wb = excel.Workbooks.Open(str(source_path))
            opened_source = True

        # SaveCopyAs does not change the source workbook's name/path or save state.
        source_wb.SaveCopyAs(str(destination))
        created_destination = True
        if opened_source:
            source_wb.Close(SaveChanges=False)
            source_wb = None

        copy_wb = excel.Workbooks.Open(str(destination))
        execution = apply_change_plan_com(copy_wb, build_change_plan(run.state()))
        execution["closed_existing_output"] = closed_existing_output
        execution["output_replaced"] = bool(overwrite)
        return excel, copy_wb, destination, execution

    except Exception:
        # Critical COM hygiene: do not leak the generated workbook into the
        # user's Excel session after a failed cleaner execution.
        _close_workbook_safely(copy_wb)
        if opened_source:
            _close_workbook_safely(source_wb)

        if created_destination and destination.exists():
            try:
                destination.unlink()
            except Exception:
                # If Excel/another process still owns it, preserve the original
                # exception; the next --overwrite pass will close the stale copy.
                pass
        raise

