from __future__ import annotations

import argparse
import atexit
import json
import re
import sys
from pathlib import Path

from openpyxl.utils import get_column_letter

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from cleaner_core.knowledge import decision_from_known_policy
from cleaner_core.exceptions import (
    load_exception_registry,
    save_exception_registry,
    sync_registry_from_decisions_file,
    case_for_review_item,
)
from cleaner_core.solutions import (
    load_project_solutions,
    save_project_solutions,
    sync_project_solutions_from_decisions_file,
)
from cleaner_core.live_excel import ExcelConnectionError, attach_excel_workbook
from review.decisions import (
    ACTIONS,
    apply_decision_to_queue,
    make_decision,
    write_decisions_file,
)


MENU = {
    "1": "ACCEPT_EXCEPTION",
    "2": "SET_VALUE",
    "3": "CLEAR_CELL",
    "4": "REPLACE_VALUE",
    "5": "UNMERGE_RANGE",
    "6": "MERGE_RANGE",
    "7": "MANUAL_FIX",
    "8": "PROFILE_CHANGE",
    "9": "TEST_RULE_CHANGE",
    "k": "TRACK_EXCEPTION",
    "d": "DEFER",
    "x": "DISMISS",
    "u": "USE_MACHINE_SUGGESTION",
    "s": "SKIP",
}

_ROW_SPAN_RE = re.compile(r"^(?P<start>\d+):(?P<end>\d+)$")
_A1_RANGE_RE = re.compile(r"^\$?[A-Z]{1,3}\$?\d+(?::\$?[A-Z]{1,3}\$?\d+)?$", re.IGNORECASE)


def prompt(text: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default not in (None, "") else ""
    value = input(f"{text}{suffix}: ").strip()
    return value if value else (default or "")


def prompt_excel_target(text: str, default: str) -> str:
    """Prompt until a plausible A1 cell/range is supplied."""
    while True:
        value = prompt(text, default).strip()
        if _A1_RANGE_RE.fullmatch(value):
            return value
        print(
            f"Invalid Excel target {value!r}. Expected an A1 address/range "
            f"such as H13 or H11:H12."
        )


def build_parameters(
    action: str,
    item: dict,
    *,
    allow_target_edit: bool = False,
) -> dict:
    """Build decision parameters with safe, location-locked defaults.

    For the most common cell-value actions the finding's sheet/target is locked
    by default. This prevents a reviewer from accidentally typing the desired
    value into the target-address prompt. Use ``--allow-target-edit`` only when
    deliberately redirecting an action to another cell/range.
    """
    loc = item.get("location") or {}
    sheet = str(loc.get("sheet") or "")
    target = str(loc.get("target") or "")

    def fixed_or_prompted_target(label: str = "Cell") -> tuple[str, str]:
        if allow_target_edit:
            return prompt("Sheet", sheet), prompt_excel_target(label, target)
        print(f"TARGET  : {sheet}!{target} (fixed from finding)")
        return sheet, target

    if action == "SET_VALUE":
        out_sheet, out_target = fixed_or_prompted_target("Cell")
        evidence = item.get("evidence") or {}
        params = {
            "sheet": out_sheet,
            "target": out_target,
            "value": prompt("New value"),
        }
        # Preserve the reviewed precondition so project memory never applies an
        # old fixed value to a different future typo by accident.
        if item.get("observed") is not None:
            params["expected_old_value"] = item.get("observed")
        for key in (
            "field_key", "field_role", "audit_kind", "transaction_index",
            "nearest_valid_wbs_above",
        ):
            value = evidence.get(key)
            if value not in (None, ""):
                params[key] = value
        return params

    if action == "CLEAR_CELL":
        out_sheet, out_target = fixed_or_prompted_target("Cell")
        return {
            "sheet": out_sheet,
            "target": out_target,
        }

    if action == "REPLACE_VALUE":
        out_sheet, out_target = fixed_or_prompted_target("Cell/range")
        return {
            "sheet": out_sheet,
            "target": out_target,
            "expected_old_value": prompt("Expected old value (optional)"),
            "new_value": prompt("New value"),
        }

    if action in {"UNMERGE_RANGE", "MERGE_RANGE"}:
        return {
            "sheet": prompt("Sheet", sheet),
            "target": prompt_excel_target("Range", target),
        }

    if action == "ACCEPT_EXCEPTION":
        evidence = item.get("evidence") or {}
        return {
            "test_id": item.get("source", {}).get("test_id"),
            "sheet": sheet,
            "target": target,
            "rows": evidence.get("rows") or evidence.get("candidate_rows"),
        }

    if action == "TRACK_EXCEPTION":
        evidence = item.get("evidence") or {}
        default_title = str(evidence.get("audit_kind") or item.get("message") or "Cleaner exception")
        default_tags = ", ".join(
            x.lower() for x in [
                str((item.get("source") or {}).get("test_id") or ""),
                str(evidence.get("audit_kind") or ""),
                "investigate",
            ] if x
        )
        return {
            "title": prompt("Case title", default_title.replace("_", " ").title()),
            "workflow_status": prompt("Workflow status", "INVESTIGATE").upper(),
            "tags": prompt("Tags (comma-separated)", default_tags),
            "owner": prompt("Owner (optional)"),
        }

    if action in {"MANUAL_FIX", "PROFILE_CHANGE", "TEST_RULE_CHANGE"}:
        return {
            "instruction": prompt("Instruction"),
        }

    return {}


def _review_targets(item: dict) -> list[str]:
    """Return occurrence targets for visual review, preserving source order."""
    evidence = item.get("evidence") or {}
    candidates = evidence.get("all_targets") or evidence.get("representative_targets") or []
    if not isinstance(candidates, list):
        candidates = []

    primary = (item.get("location") or {}).get("target")
    ordered: list[str] = []
    for value in [primary, *candidates]:
        if value in (None, ""):
            continue
        target = str(value)
        if target not in ordered:
            ordered.append(target)
    return ordered


def _structure_pattern_max_col(item: dict) -> int | None:
    pattern = (item.get("evidence") or {}).get("structure_pattern") or {}
    merges = pattern.get("merges") or []
    max_col: int | None = None
    for merge in merges:
        if not isinstance(merge, (list, tuple)) or len(merge) != 4:
            continue
        try:
            c2 = int(merge[3])
        except (TypeError, ValueError):
            continue
        max_col = c2 if max_col is None else max(max_col, c2)
    return max_col


def _selection_address_for_item(
    item: dict,
    target: str,
    *,
    used_max_col: int | None = None,
) -> str:
    """
    Translate a review target into a useful Excel selection.

    Normal A1 targets are used unchanged. A row-span target such as ``3:4``
    (used by DOCUMENT_STRUCTURE) is expanded to the full card width. The
    structure fingerprint supplies the preferred last column; UsedRange is a
    fallback only when the fingerprint has no merge geometry.
    """
    target = str(target or "").strip()
    match = _ROW_SPAN_RE.fullmatch(target)
    if not match:
        return target

    start_row = int(match.group("start"))
    end_row = int(match.group("end"))
    max_col = _structure_pattern_max_col(item) or used_max_col or 1
    max_col = max(1, int(max_col))
    return f"A{start_row}:{get_column_letter(max_col)}{end_row}"


def _resolve_edit_item(queue: dict, token: str) -> tuple[int, dict]:
    """Resolve an item to reopen by 1-based index, exact id, or unique id fragment."""
    items = queue.get("items", [])
    raw = str(token or "").strip()
    if not raw:
        raise ValueError("--edit requires an item number, review id, or unique id fragment.")

    if raw.isdigit():
        index = int(raw)
        if 1 <= index <= len(items):
            return index - 1, items[index - 1]
        raise ValueError(f"Review item number {index} is out of range 1..{len(items)}.")

    exact = [(i, item) for i, item in enumerate(items) if item.get("review_id") == raw]
    if exact:
        return exact[0]

    matches = [
        (i, item) for i, item in enumerate(items)
        if raw.lower() in str(item.get("review_id") or "").lower()
    ]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise ValueError(f"No review item matches {raw!r}.")
    raise ValueError(f"Review id fragment {raw!r} matches {len(matches)} items; be more specific.")


def reopen_item_for_edit(queue: dict, token: str) -> tuple[int, dict, dict | None]:
    """Remove the existing decision and reopen one item for correction."""
    index, item = _resolve_edit_item(queue, token)
    previous = item.get("decision")
    item.pop("decision", None)
    item["review_state"] = "PENDING"
    return index, item, previous


class ExcelReviewNavigator:
    """Minimal COM navigation helper for review.

    The navigator deliberately does not alter Excel window geometry, window
    state, zoom, formatting, or status-bar content. It only activates the
    workbook/worksheet, brings the existing Excel window to the foreground,
    makes the target visible, and applies Excel's native selection/ActiveCell.
    """

    def __init__(self, queue: dict, *, enabled: bool = True, spotlight: bool | None = None):
        # ``spotlight`` is retained only for backward compatibility with older
        # callers/CLI versions. No zoom/status-bar/window spotlight is applied.
        self.enabled = enabled
        self.workbook = None
        self.error: str | None = None
        # The reviewer is launched from the terminal. Capture whatever window is
        # currently foreground before we ever activate Excel, then return focus
        # to it after each navigation so keyboard input continues in the console.
        self.return_hwnd = self._capture_foreground_window() if enabled else None
        if not enabled:
            return

        meta = queue.get("workbook") or {}
        workbook_ref = meta.get("name") or meta.get("path") or None
        try:
            self.workbook = attach_excel_workbook(workbook_ref)
        except ExcelConnectionError as exc:
            self.error = str(exc)
        except Exception as exc:  # navigation must never prevent review itself
            self.error = f"Excel navigation unavailable: {exc}"

    @property
    def available(self) -> bool:
        return self.workbook is not None

    def _worksheet(self, sheet: str):
        if self.workbook is None:
            raise RuntimeError(self.error or "Excel navigation is not connected.")
        return self.workbook.Worksheets(sheet)

    @staticmethod
    def _capture_foreground_window() -> int | None:
        """Capture the current foreground HWND without modifying any window."""
        try:
            import ctypes
            hwnd = int(ctypes.windll.user32.GetForegroundWindow())
            return hwnd or None
        except Exception:
            return None

    def _bring_excel_to_front(self, app) -> None:
        """Best-effort foreground activation without resizing/restoring Excel."""
        try:
            import ctypes
            hwnd = int(app.Hwnd)
            user32 = ctypes.windll.user32
            # Do not call ShowWindow/SW_RESTORE: the reviewer must preserve the
            # user's current Excel window size, position and state exactly.
            try:
                user32.BringWindowToTop(hwnd)
            except Exception:
                pass
            user32.SetForegroundWindow(hwnd)
        except Exception:
            pass

    def _return_focus_to_console(self) -> None:
        """Return foreground focus to the window active when review started.

        Capturing the foreground HWND is more reliable than GetConsoleWindow for
        Git Bash/mintty and other pseudo-terminal hosts where Python itself does
        not own a traditional Windows console window.
        """
        hwnd = self.return_hwnd
        if not hwnd:
            return
        try:
            import ctypes
            user32 = ctypes.windll.user32
            if not user32.IsWindow(int(hwnd)):
                return
            try:
                user32.BringWindowToTop(int(hwnd))
            except Exception:
                pass
            user32.SetForegroundWindow(int(hwnd))
        except Exception:
            pass

    def clear_spotlight(self) -> None:
        """Backward-compatible no-op; the reviewer no longer uses a spotlight."""
        return

    def close(self) -> None:
        """No view restoration is required because window/view settings are untouched."""
        return

    def show(self, item: dict, target: str) -> str:
        """Activate/select a target while leaving Excel window/view settings alone."""
        if self.workbook is None:
            raise RuntimeError(self.error or "Excel navigation is not connected.")

        sheet = str((item.get("location") or {}).get("sheet") or "")
        if not sheet:
            raise RuntimeError("Review item has no worksheet location.")

        ws = self._worksheet(sheet)
        used_max_col = None
        try:
            used = ws.UsedRange
            used_max_col = int(used.Column) + int(used.Columns.Count) - 1
        except Exception:
            pass

        address = _selection_address_for_item(
            item,
            target,
            used_max_col=used_max_col,
        )
        if not address:
            raise RuntimeError("Review item has no selectable Excel target.")

        app = self.workbook.Application
        try:
            app.Visible = True
        except Exception:
            pass

        self.workbook.Activate()
        ws.Activate()
        self._bring_excel_to_front(app)

        rng = ws.Range(address)
        try:
            focus_rng = rng.MergeArea if bool(rng.MergeCells) else rng
        except Exception:
            focus_rng = rng

        # GoTo with Scroll=True is intentional: it makes an off-screen target
        # visible, but it does not change the Excel window size/position/state
        # or zoom. The target is then selected with a true ActiveCell.
        try:
            app.Goto(focus_rng.Cells(1, 1), True)
        except Exception:
            try:
                focus_rng.Cells(1, 1).Select()
            except Exception:
                pass

        try:
            focus_rng.Select()
        except Exception:
            pass
        try:
            focus_rng.Cells(1, 1).Activate()
        except Exception:
            pass

        # Excel needs foreground activation for the visual jump/selection, but
        # the reviewer is keyboard-driven from the terminal. Hand focus straight
        # back to the original foreground window before prompting for a decision.
        self._bring_excel_to_front(app)
        self._return_focus_to_console()
        return f"{sheet}!{address}"


def _show_review_target(
    navigator: ExcelReviewNavigator,
    item: dict,
    targets: list[str],
    target_index: int,
) -> str | None:
    if not targets:
        return None
    if not navigator.available:
        return None
    try:
        return navigator.show(item, targets[target_index])
    except Exception as exc:
        print(f"[EXCEL] Navigation failed: {exc}")
        return None


def print_item(
    index: int,
    total: int,
    item: dict,
    *,
    examples: list[str] | None = None,
    example_index: int = 0,
    excel_selection: str | None = None,
):
    print("\n" + "=" * 88)
    print(f"REVIEW {index}/{total}")
    print(f"ID      : {item['review_id']}")
    print(f"STATUS  : {item['source'].get('status')}")
    print(f"SEVERITY: {item['source'].get('severity')}")
    print(f"LOCATION: {item['location'].get('sheet')}!{item['location'].get('target')}")
    if examples:
        print(f"EXAMPLE : {example_index + 1}/{len(examples)} -> {examples[example_index]}")
    if excel_selection:
        print(f"EXCEL   : selected {excel_selection}")
    print(f"MESSAGE : {item.get('message')}")
    tracked = item.get("tracked_exception") or {}
    if tracked:
        print(f"CASE    : {tracked.get('handle')} [{tracked.get('case_state')}/{tracked.get('workflow_status')}]")
        if tracked.get("tags"):
            print(f"TAGS    : {', '.join(tracked.get('tags') or [])}")
        if tracked.get("note"):
            print(f"CASE NOTE: {tracked.get('note')}")
    print(f"POLICY  : {item.get('current_policy', {}).get('state')}")
    note = item.get('current_policy', {}).get('note')
    if note:
        print(f"          {note}")

    print("\nActions")
    if examples and len(examples) > 1:
        print("  n  NEXT EXAMPLE in Excel")
        print("  p  PREVIOUS EXAMPLE in Excel")
    print("  r  RESELECT current item in Excel")
    print("  1  ACCEPT_EXCEPTION")
    print("  2  SET_VALUE (current finding target)")
    print("  3  CLEAR_CELL (current finding target)")
    print("  4  REPLACE_VALUE (current finding target)")
    print("  5  UNMERGE_RANGE")
    print("  6  MERGE_RANGE")
    print("  7  MANUAL_FIX")
    print("  8  PROFILE_CHANGE")
    print("  9  TEST_RULE_CHANGE")
    print("  k  TRACK_EXCEPTION (open/investigate; does not accept the anomaly)")
    print("  d  DEFER (also tracked as INVESTIGATE)")
    print("  x  DISMISS")
    suggestion = item.get("machine_suggestion", {}).get("suggested_fix")
    if suggestion:
        p = suggestion.get("parameters", {})
        print(
            f"  u  USE_MACHINE_SUGGESTION -> "
            f"{suggestion.get('action')} {p.get('target')}={p.get('value')!r}"
        )
    print("  s  SKIP (leave pending)")


def accept_known_resolutions(queue: dict, reviewer: str = "") -> int:
    accepted = 0
    for item in queue.get("items", []):
        if item.get("review_state") != "PENDING":
            continue
        template = decision_from_known_policy(item)
        if not template:
            continue
        decision = make_decision(
            template["action"],
            parameters=template.get("parameters") or {},
            reason=template.get("reason") or "Accepted reusable profile policy.",
            reviewer=reviewer,
        )
        decision["origin"] = template.get("origin", "REUSABLE_PROFILE")
        if template.get("project_solution_handle"):
            decision["project_solution_handle"] = template.get("project_solution_handle")
        apply_decision_to_queue(queue, item["review_id"], decision)
        accepted += 1
    return accepted


def update_summary(queue: dict):
    items = queue.get("items", [])
    queue["summary"]["pending_review"] = sum(
        1 for x in items if x.get("review_state") == "PENDING"
    )
    queue["summary"]["resolved"] = sum(
        1 for x in items if x.get("review_state") == "RESOLVED"
    )
    queue["summary"]["deferred"] = sum(
        1 for x in items if x.get("review_state") == "DEFERRED"
    )


def main():
    parser = argparse.ArgumentParser(
        description="Review Cleaner findings and record decisions without executing changes."
    )
    parser.add_argument(
        "queue",
        nargs="?",
        default=str(PROJECT_ROOT / "azd_review_queue.json"),
    )
    parser.add_argument(
        "--decisions",
        default=str(PROJECT_ROOT / "azd_review_decisions.json"),
    )
    parser.add_argument(
        "--reviewer",
        default="",
    )
    parser.add_argument(
        "--accept-known",
        action="store_true",
        help=(
            "Auto-record decisions for findings already covered by reusable "
            "profile knowledge, then review only unknown findings."
        ),
    )
    parser.add_argument(
        "--project-solutions",
        default="",
        help="Optional persistent project-solution registry path.",
    )
    parser.add_argument(
        "--no-excel-navigation",
        action="store_true",
        help="Disable automatic jump/select behavior in the already-open Excel workbook.",
    )
    parser.add_argument(
        "--no-spotlight",
        action="store_true",
        help=argparse.SUPPRESS,  # deprecated compatibility flag; spotlight no longer exists
    )
    parser.add_argument(
        "--allow-target-edit",
        action="store_true",
        help=(
            "Allow SET_VALUE/CLEAR_CELL/REPLACE_VALUE to edit sheet/target. "
            "By default those actions are locked to the finding location for safety."
        ),
    )
    parser.add_argument(
        "--edit",
        default="",
        metavar="ITEM",
        help=(
            "Reopen one resolved/deferred review item by 1-based queue number, "
            "exact review id, or unique review-id fragment."
        ),
    )
    args = parser.parse_args()

    queue_path = Path(args.queue)
    if not queue_path.exists():
        raise SystemExit(f"Review queue not found: {queue_path}")

    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    profile_name = str((queue.get("profile") or {}).get("profile_name") or "PROJECT")
    exception_registry_path = PROJECT_ROOT / "exceptions" / f"{profile_name}.exceptions.json"
    exception_registry = load_exception_registry(
        exception_registry_path,
        profile_name=profile_name,
        create=True,
    )
    project_solutions_path = (
        Path(args.project_solutions)
        if args.project_solutions
        else PROJECT_ROOT / "project_solutions" / f"{profile_name}.solutions.json"
    )
    project_solutions = load_project_solutions(
        project_solutions_path,
        project_id=profile_name,
        create=True,
    )
    navigator = ExcelReviewNavigator(
        queue,
        enabled=not args.no_excel_navigation,
    )
    atexit.register(navigator.close)
    if navigator.available:
        print(f"[EXCEL] Connected to open workbook: {navigator.workbook.Name}")
        print("[EXCEL] Each pending review item will activate/select its Excel target, then return keyboard focus to the console; window size, position, state and zoom are left unchanged.")
    elif not args.no_excel_navigation:
        print(f"[EXCEL] Automatic navigation unavailable: {navigator.error}")
        print("[EXCEL] Review will continue in terminal-only mode.")

    edited_item = None
    previous_edit_decision = None
    if args.edit:
        try:
            edit_index, edited_item, previous_edit_decision = reopen_item_for_edit(queue, args.edit)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        # Do not persist the reopening yet. If review is interrupted, the previous
        # decision remains safely on disk until a replacement decision is recorded.
        update_summary(queue)
        print(f"[EDIT] Reopened review {edit_index + 1}: {edited_item['review_id']}")
        if previous_edit_decision:
            print(
                f"[EDIT] Previous decision: {previous_edit_decision.get('action')} "
                f"{previous_edit_decision.get('parameters') or {}}"
            )

    if args.accept_known and edited_item is None:
        accepted = accept_known_resolutions(queue, reviewer=args.reviewer)
        update_summary(queue)
        queue_path.write_text(
            json.dumps(queue, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        decisions_written = write_decisions_file(queue, args.decisions)
        solution_report = sync_project_solutions_from_decisions_file(project_solutions, decisions_written)
        save_project_solutions(project_solutions, project_solutions_path)
        created = solution_report.get("created_handles", [])
        updated = solution_report.get("updated_handles", [])
        print(f"Accepted reusable profile/project resolutions: {accepted}")
        if created or updated:
            print(
                "Project solutions persisted: "
                + ", ".join(created + updated)
            )

    if edited_item is not None:
        pending = [edited_item]
    else:
        pending = [
            x for x in queue.get("items", [])
            if x.get("review_state") == "PENDING"
        ]

    if not pending:
        print("No pending review items.")
        decisions_written = write_decisions_file(queue, args.decisions)
        sync_project_solutions_from_decisions_file(project_solutions, decisions_written)
        save_project_solutions(project_solutions, project_solutions_path)
        print(f"Solutions  : {project_solutions_path}")
        navigator.close()
        return

    for index, item in enumerate(pending, start=1):
        examples = _review_targets(item)
        example_index = 0
        excel_selection = _show_review_target(
            navigator,
            item,
            examples,
            example_index,
        )
        print_item(
            index,
            len(pending),
            item,
            examples=examples,
            example_index=example_index,
            excel_selection=excel_selection,
        )

        while True:
            choice = input("\nDecision: ").strip().lower()

            if choice in {"n", "p", "r"}:
                if not examples:
                    print("This review item has no Excel target.")
                    continue
                if choice == "n":
                    example_index = (example_index + 1) % len(examples)
                elif choice == "p":
                    example_index = (example_index - 1) % len(examples)

                excel_selection = _show_review_target(
                    navigator,
                    item,
                    examples,
                    example_index,
                )
                if excel_selection:
                    print(
                        f"[EXCEL] Example {example_index + 1}/{len(examples)}: "
                        f"{excel_selection}"
                    )
                elif not navigator.available:
                    print("[EXCEL] Automatic navigation is not available.")
                continue

            action = MENU.get(choice)
            if action:
                break
            print("Unknown choice.")

        if action == "SKIP":
            if edited_item is item and previous_edit_decision:
                item["decision"] = previous_edit_decision
                item["review_state"] = (
                    "DEFERRED"
                    if previous_edit_decision.get("action") == "DEFER"
                    else "RESOLVED"
                )
                print("Edit cancelled; previous decision preserved.")
            else:
                print("Left pending.")
            continue

        if action == "USE_MACHINE_SUGGESTION":
            suggestion = item.get("machine_suggestion", {}).get("suggested_fix")
            if not suggestion:
                print("This item has no machine fix suggestion; left pending.")
                continue
            action = suggestion["action"]
            params = suggestion.get("parameters") or {}
            reason = prompt(
                "Reason / note",
                suggestion.get("reason") or "Accepted machine cleaning suggestion"
            )
        else:
            params = build_parameters(
                action,
                item,
                allow_target_edit=args.allow_target_edit,
            )
            reason = prompt("Reason / note (optional)")

        decision = make_decision(
            action,
            parameters=params,
            reason=reason,
            reviewer=args.reviewer,
        )
        apply_decision_to_queue(queue, item["review_id"], decision)

        update_summary(queue)
        queue_path.write_text(
            json.dumps(queue, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        decisions_written = write_decisions_file(queue, args.decisions)
        sync_project_solutions_from_decisions_file(project_solutions, decisions_written)
        save_project_solutions(project_solutions, project_solutions_path)
        if action in {"DEFER", "TRACK_EXCEPTION", "ACCEPT_EXCEPTION"}:
            sync_registry_from_decisions_file(exception_registry, decisions_written)
            save_exception_registry(exception_registry, exception_registry_path)
            tracked = case_for_review_item(exception_registry, item)
            if tracked is not None:
                item["tracked_exception"] = tracked
                print(
                    f"Exception case: {tracked.get('handle')} "
                    f"[{tracked.get('case_state')}/{tracked.get('workflow_status')}]"
                )

        print(
            f"Recorded: {action} "
            f"(execution={decision['execution_kind']}, state={decision['execution_state']})"
        )

    update_summary(queue)
    queue_path.write_text(
        json.dumps(queue, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    decisions_path = write_decisions_file(queue, args.decisions)
    sync_project_solutions_from_decisions_file(project_solutions, decisions_path)
    save_project_solutions(project_solutions, project_solutions_path)

    print("\nReview complete.")
    print(f"Queue     : {queue_path}")
    print(f"Decisions : {decisions_path}")
    print(f"Pending   : {queue['summary']['pending_review']}")
    print(f"Resolved  : {queue['summary']['resolved']}")
    print(f"Deferred  : {queue['summary']['deferred']}")
    print(f"Exceptions: {exception_registry_path}")
    print(f"Solutions : {project_solutions_path}")
    navigator.close()


if __name__ == "__main__":
    main()
