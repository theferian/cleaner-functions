from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from openpyxl.utils import get_column_letter

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from cleaner_core.knowledge import decision_from_known_policy
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
    "d": "DEFER",
    "x": "DISMISS",
    "u": "USE_MACHINE_SUGGESTION",
    "s": "SKIP",
}

_ROW_SPAN_RE = re.compile(r"^(?P<start>\d+):(?P<end>\d+)$")


def prompt(text: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default not in (None, "") else ""
    value = input(f"{text}{suffix}: ").strip()
    return value if value else (default or "")


def build_parameters(action: str, item: dict) -> dict:
    loc = item.get("location") or {}
    sheet = loc.get("sheet") or ""
    target = loc.get("target") or ""

    if action == "SET_VALUE":
        return {
            "sheet": prompt("Sheet", sheet),
            "target": prompt("Cell", target),
            "value": prompt("New value"),
        }

    if action == "CLEAR_CELL":
        return {
            "sheet": prompt("Sheet", sheet),
            "target": prompt("Cell", target),
        }

    if action == "REPLACE_VALUE":
        return {
            "sheet": prompt("Sheet", sheet),
            "target": prompt("Cell/range", target),
            "expected_old_value": prompt("Expected old value (optional)"),
            "new_value": prompt("New value"),
        }

    if action in {"UNMERGE_RANGE", "MERGE_RANGE"}:
        return {
            "sheet": prompt("Sheet", sheet),
            "target": prompt("Range", target),
        }

    if action == "ACCEPT_EXCEPTION":
        evidence = item.get("evidence") or {}
        return {
            "test_id": item.get("source", {}).get("test_id"),
            "sheet": sheet,
            "target": target,
            "rows": evidence.get("rows") or evidence.get("candidate_rows"),
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


class ExcelReviewNavigator:
    """Small COM navigation helper used only for human review/navigation."""

    def __init__(self, queue: dict, *, enabled: bool = True):
        self.enabled = enabled
        self.workbook = None
        self.error: str | None = None
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

    def show(self, item: dict, target: str) -> str:
        """Activate/select a review target and return the actual Excel address."""
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

        self.workbook.Activate()
        ws.Activate()
        rng = ws.Range(address)

        app = self.workbook.Application
        try:
            app.Visible = True
        except Exception:
            pass

        # Goto both selects the range and scrolls it into view. Select is kept
        # as a fallback for Excel installations where Goto behaves differently.
        try:
            app.Goto(rng, True)
        except Exception:
            rng.Select()

        try:
            window = app.ActiveWindow
            row = int(rng.Row)
            window.ScrollRow = max(1, row - 2)
            window.ScrollColumn = 1
        except Exception:
            pass

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
    print("  2  SET_VALUE")
    print("  3  CLEAR_CELL")
    print("  4  REPLACE_VALUE")
    print("  5  UNMERGE_RANGE")
    print("  6  MERGE_RANGE")
    print("  7  MANUAL_FIX")
    print("  8  PROFILE_CHANGE")
    print("  9  TEST_RULE_CHANGE")
    print("  d  DEFER")
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
        "--no-excel-navigation",
        action="store_true",
        help="Disable automatic jump/select behavior in the already-open Excel workbook.",
    )
    args = parser.parse_args()

    queue_path = Path(args.queue)
    if not queue_path.exists():
        raise SystemExit(f"Review queue not found: {queue_path}")

    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    navigator = ExcelReviewNavigator(queue, enabled=not args.no_excel_navigation)
    if navigator.available:
        print(f"[EXCEL] Connected to open workbook: {navigator.workbook.Name}")
        print("[EXCEL] Each pending review item will be selected automatically.")
    elif not args.no_excel_navigation:
        print(f"[EXCEL] Automatic navigation unavailable: {navigator.error}")
        print("[EXCEL] Review will continue in terminal-only mode.")

    if args.accept_known:
        accepted = accept_known_resolutions(queue, reviewer=args.reviewer)
        update_summary(queue)
        queue_path.write_text(
            json.dumps(queue, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        write_decisions_file(queue, args.decisions)
        print(f"Accepted reusable profile resolutions: {accepted}")

    pending = [
        x for x in queue.get("items", [])
        if x.get("review_state") == "PENDING"
    ]

    if not pending:
        print("No pending review items.")
        write_decisions_file(queue, args.decisions)
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
            params = build_parameters(action, item)
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
        write_decisions_file(queue, args.decisions)

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

    print("\nReview complete.")
    print(f"Queue     : {queue_path}")
    print(f"Decisions : {decisions_path}")
    print(f"Pending   : {queue['summary']['pending_review']}")
    print(f"Resolved  : {queue['summary']['resolved']}")
    print(f"Deferred  : {queue['summary']['deferred']}")


if __name__ == "__main__":
    main()
