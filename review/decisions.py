from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path
import json
from typing import Any


ACTIONS = {
    "ACCEPT_EXCEPTION": {
        "description": "Accept this condition as a legitimate exception and later add/update profile exception policy.",
        "requires": [],
        "execution_kind": "PROFILE_UPDATE",
    },
    "SET_VALUE": {
        "description": "Set a specific cell to a value later.",
        "requires": ["sheet", "target", "value"],
        "execution_kind": "WORKBOOK_CHANGE",
    },
    "CLEAR_CELL": {
        "description": "Clear a specific cell later.",
        "requires": ["sheet", "target"],
        "execution_kind": "WORKBOOK_CHANGE",
    },
    "REPLACE_VALUE": {
        "description": "Replace an expected old value with a new value later.",
        "requires": ["sheet", "target", "new_value"],
        "execution_kind": "WORKBOOK_CHANGE",
    },
    "UNMERGE_RANGE": {
        "description": "Unmerge a range later.",
        "requires": ["sheet", "target"],
        "execution_kind": "WORKBOOK_CHANGE",
    },
    "MERGE_RANGE": {
        "description": "Merge a range later.",
        "requires": ["sheet", "target"],
        "execution_kind": "WORKBOOK_CHANGE",
    },
    "MANUAL_FIX": {
        "description": "Record a human repair instruction not yet represented by a deterministic action.",
        "requires": ["instruction"],
        "execution_kind": "MANUAL",
    },
    "PROFILE_CHANGE": {
        "description": "Change the profile/rule definition rather than the workbook.",
        "requires": ["instruction"],
        "execution_kind": "PROFILE_UPDATE",
    },
    "TEST_RULE_CHANGE": {
        "description": "Change the discovery/test logic rather than the workbook.",
        "requires": ["instruction"],
        "execution_kind": "TEST_UPDATE",
    },
    "DEFER": {
        "description": "Leave unresolved for later review.",
        "requires": [],
        "execution_kind": "NONE",
    },
    "DISMISS": {
        "description": "Close the item without creating an exception or repair.",
        "requires": [],
        "execution_kind": "NONE",
    },
}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def validate_decision(decision: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(decision, dict):
        raise ValueError("Decision must be a JSON object.")

    action = str(decision.get("action") or "").upper().strip()
    if action not in ACTIONS:
        raise ValueError(
            f"Unknown review action {action!r}. Allowed: {', '.join(ACTIONS)}"
        )

    params = decision.get("parameters") or {}
    if not isinstance(params, dict):
        raise ValueError("decision.parameters must be an object.")

    missing = [
        key for key in ACTIONS[action]["requires"]
        if params.get(key) in (None, "")
    ]
    if missing:
        raise ValueError(
            f"{action} requires parameter(s): {', '.join(missing)}"
        )

    normalized = deepcopy(decision)
    normalized["action"] = action
    normalized["parameters"] = params
    normalized.setdefault("reason", "")
    normalized.setdefault("reviewer", "")
    normalized.setdefault("decided_at", _now())
    normalized["execution_kind"] = ACTIONS[action]["execution_kind"]
    normalized["execution_state"] = "PENDING" if normalized["execution_kind"] != "NONE" else "NOT_REQUIRED"
    return normalized


def make_decision(
    action: str,
    *,
    parameters: dict[str, Any] | None = None,
    reason: str = "",
    reviewer: str = "",
) -> dict[str, Any]:
    return validate_decision({
        "action": action,
        "parameters": parameters or {},
        "reason": reason,
        "reviewer": reviewer,
    })


def apply_decision_to_queue(queue: dict, review_id: str, decision: dict) -> dict:
    decision = validate_decision(decision)

    for item in queue.get("items", []):
        if item.get("review_id") == review_id:
            item["decision"] = decision
            item["review_state"] = (
                "DEFERRED" if decision["action"] == "DEFER"
                else "RESOLVED"
            )
            return item

    raise KeyError(f"Review item not found: {review_id}")


def write_decisions_file(queue: dict, path: str | Path) -> Path:
    path = Path(path)

    decisions = []
    for item in queue.get("items", []):
        if item.get("decision"):
            decisions.append({
                "review_id": item["review_id"],
                "source": item["source"],
                "location": item["location"],
                "evidence": item.get("evidence") or {},
                "decision": item["decision"],
            })

    payload = {
        "schema": "cleaner.review_decisions/0.1",
        "package": queue.get("package"),
        "run": queue.get("run"),
        "profile": queue.get("profile"),
        "workbook": queue.get("workbook"),
        "summary": {
            "decision_count": len(decisions),
            "pending_execution": sum(
                1 for x in decisions
                if x["decision"].get("execution_state") == "PENDING"
            ),
        },
        "decisions": decisions,
    }

    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    return path
