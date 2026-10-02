from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

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
    "s": "SKIP",
}


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


def print_item(index: int, total: int, item: dict):
    print("\n" + "=" * 88)
    print(f"REVIEW {index}/{total}")
    print(f"ID      : {item['review_id']}")
    print(f"STATUS  : {item['source'].get('status')}")
    print(f"SEVERITY: {item['source'].get('severity')}")
    print(f"LOCATION: {item['location'].get('sheet')}!{item['location'].get('target')}")
    print(f"MESSAGE : {item.get('message')}")
    print(f"POLICY  : {item.get('current_policy', {}).get('state')}")
    note = item.get('current_policy', {}).get('note')
    if note:
        print(f"          {note}")

    print("\nActions")
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
    print("  s  SKIP (leave pending)")


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
    args = parser.parse_args()

    queue_path = Path(args.queue)
    if not queue_path.exists():
        raise SystemExit(f"Review queue not found: {queue_path}")

    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    pending = [
        x for x in queue.get("items", [])
        if x.get("review_state") == "PENDING"
    ]

    if not pending:
        print("No pending review items.")
        write_decisions_file(queue, args.decisions)
        return

    for index, item in enumerate(pending, start=1):
        print_item(index, len(pending), item)

        while True:
            choice = input("\nDecision: ").strip().lower()
            action = MENU.get(choice)
            if action:
                break
            print("Unknown choice.")

        if action == "SKIP":
            print("Left pending.")
            continue

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
