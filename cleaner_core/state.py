from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path
import json
from typing import Any


STATE_SCHEMA = "cleaner.resolved_state/0.1"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _cell_key(sheet: str, target: str) -> str:
    return f"{sheet}!{target}".upper()


def new_resolved_state(
    *,
    run_id: str,
    profile_name: str | None = None,
    workbook: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema": STATE_SCHEMA,
        "run_id": run_id,
        "created_at": _now(),
        "updated_at": _now(),
        "profile_name": profile_name,
        "workbook": workbook or {},
        "stages": {},
        "value_overrides": {},
        "merge_operations": [],
        "accepted_exceptions": [],
        "profile_changes": [],
        "test_rule_changes": [],
        "manual_fixes": [],
        "decision_audit": [],
    }


def load_resolved_state(
    path: str | Path,
    *,
    create: bool = False,
    run_id: str | None = None,
    profile_name: str | None = None,
    workbook: dict[str, Any] | None = None,
) -> dict[str, Any]:
    path = Path(path)
    if path.exists():
        state = json.loads(path.read_text(encoding="utf-8"))
        if state.get("schema") != STATE_SCHEMA:
            raise ValueError(
                f"Unsupported resolved-state schema: {state.get('schema')!r}"
            )
        return state

    if not create:
        raise FileNotFoundError(path)
    if not run_id:
        raise ValueError("run_id is required when creating resolved state.")

    return new_resolved_state(
        run_id=run_id,
        profile_name=profile_name,
        workbook=workbook,
    )


def save_resolved_state(state: dict[str, Any], path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = _now()
    path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    return path


def mark_stage_run(
    state: dict[str, Any],
    stage_id: str,
    *,
    finding_count: int,
    report_path: str | None = None,
    review_queue_path: str | None = None,
) -> None:
    stage_id = str(stage_id).upper()
    stage = state.setdefault("stages", {}).setdefault(stage_id, {})
    stage.update({
        "status": "REVIEWED" if int(finding_count) == 0 else "AWAITING_REVIEW",
        "last_run_at": _now(),
        "finding_count": int(finding_count),
        "report_path": report_path,
        "review_queue_path": review_queue_path,
        "decision_count": int(stage.get("decision_count", 0)),
    })
    if int(finding_count) == 0:
        stage["reviewed_at"] = _now()
        stage["auto_reviewed"] = True


def _upsert_by_review_id(items: list[dict], item: dict) -> None:
    review_id = item.get("source_review_id")
    for index, existing in enumerate(items):
        if existing.get("source_review_id") == review_id:
            items[index] = item
            return
    items.append(item)


def _record_value_override(
    state: dict[str, Any],
    *,
    review_id: str,
    action: str,
    params: dict,
    decision: dict,
) -> None:
    sheet = str(params.get("sheet") or "")
    target = str(params.get("target") or "")
    if not sheet or not target:
        return

    if action == "CLEAR_CELL":
        value = None
    elif action == "REPLACE_VALUE":
        value = params.get("new_value")
    else:
        value = params.get("value")

    state.setdefault("value_overrides", {})[_cell_key(sheet, target)] = {
        "sheet": sheet,
        "target": target,
        "value": value,
        "action": action,
        "expected_old_value": params.get("expected_old_value"),
        "source_review_id": review_id,
        "reason": decision.get("reason", ""),
        "decided_at": decision.get("decided_at"),
    }


def ingest_review_decisions(
    state: dict[str, Any],
    decisions_payload: dict[str, Any],
) -> dict[str, Any]:
    """
    Convert reviewed decisions into logical state used by later stages.

    This does not mutate Excel. WORKBOOK_CHANGE decisions become overlays;
    accepted exceptions become profile overlays; other decisions remain audit
    records until a future structured executor exists.
    """
    source_stage = str(
        decisions_payload.get("run", {}).get("script_id") or "UNKNOWN"
    ).upper()

    audit = state.setdefault("decision_audit", [])
    existing_audit = {
        (x.get("review_id"), x.get("decision", {}).get("decided_at"))
        for x in audit
    }

    ingested = 0
    for item in decisions_payload.get("decisions", []):
        review_id = str(item.get("review_id") or "")
        decision = deepcopy(item.get("decision") or {})
        action = str(decision.get("action") or "").upper()
        params = decision.get("parameters") or {}

        if not review_id or not action:
            continue

        audit_key = (review_id, decision.get("decided_at"))
        if audit_key not in existing_audit:
            audit.append({
                "review_id": review_id,
                "source": deepcopy(item.get("source") or {}),
                "location": deepcopy(item.get("location") or {}),
                "decision": decision,
                "ingested_at": _now(),
            })
            existing_audit.add(audit_key)

        if action in {"SET_VALUE", "CLEAR_CELL", "REPLACE_VALUE"}:
            _record_value_override(
                state,
                review_id=review_id,
                action=action,
                params=params,
                decision=decision,
            )

        elif action in {"MERGE_RANGE", "UNMERGE_RANGE"}:
            op = {
                "action": action,
                "sheet": params.get("sheet"),
                "target": params.get("target"),
                "source_review_id": review_id,
                "reason": decision.get("reason", ""),
                "decided_at": decision.get("decided_at"),
            }
            _upsert_by_review_id(state.setdefault("merge_operations", []), op)

        elif action == "ACCEPT_EXCEPTION":
            exc = {
                "source_review_id": review_id,
                "test_id": params.get("test_id")
                    or item.get("source", {}).get("test_id"),
                "sheet": params.get("sheet")
                    or item.get("location", {}).get("sheet"),
                "target": params.get("target")
                    or item.get("location", {}).get("target"),
                "rows": params.get("rows"),
                "reason": decision.get("reason", ""),
                "decided_at": decision.get("decided_at"),
            }
            _upsert_by_review_id(
                state.setdefault("accepted_exceptions", []), exc
            )

        elif action == "PROFILE_CHANGE":
            _upsert_by_review_id(
                state.setdefault("profile_changes", []),
                {
                    "source_review_id": review_id,
                    "instruction": params.get("instruction", ""),
                    "reason": decision.get("reason", ""),
                    "decided_at": decision.get("decided_at"),
                },
            )

        elif action == "TEST_RULE_CHANGE":
            _upsert_by_review_id(
                state.setdefault("test_rule_changes", []),
                {
                    "source_review_id": review_id,
                    "instruction": params.get("instruction", ""),
                    "reason": decision.get("reason", ""),
                    "decided_at": decision.get("decided_at"),
                },
            )

        elif action == "MANUAL_FIX":
            _upsert_by_review_id(
                state.setdefault("manual_fixes", []),
                {
                    "source_review_id": review_id,
                    "instruction": params.get("instruction", ""),
                    "reason": decision.get("reason", ""),
                    "decided_at": decision.get("decided_at"),
                },
            )

        ingested += 1

    stage = state.setdefault("stages", {}).setdefault(source_stage, {})
    stage["status"] = "REVIEWED"
    stage["reviewed_at"] = _now()
    stage["decision_count"] = ingested
    stage["decisions_schema"] = decisions_payload.get("schema")
    state["updated_at"] = _now()
    return state


def ingest_review_decisions_file(
    state: dict[str, Any],
    path: str | Path,
) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return ingest_review_decisions(state, payload)
