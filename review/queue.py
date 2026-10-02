from __future__ import annotations

from datetime import datetime
from pathlib import Path
import hashlib
import json
from typing import Any

from .decisions import ACTIONS
from cleaner_core.knowledge import match_known_fix


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _stable_review_id(
    *,
    profile_name: str,
    test_id: str,
    sheet: str | None,
    target: str | None,
    status: str,
) -> str:
    raw = "|".join([
        profile_name or "",
        test_id or "",
        sheet or "",
        target or "",
        status or "",
    ])
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    prefix = "_".join(
        x for x in [test_id, (sheet or "").replace(" ", "_"), target or ""]
        if x
    )
    prefix = prefix.replace(":", "_").replace("!", "_")
    return f"{prefix}_{digest}" if prefix else digest


def _allowed_actions(finding: dict) -> list[str]:
    """
    Keep action vocabulary broad because the review phase records intent,
    not execution. Frappe can later render these as buttons/forms.
    """
    return list(ACTIONS.keys())


def _default_parameters(finding: dict, action: str) -> dict[str, Any]:
    sheet = finding.get("sheet")
    target = finding.get("target")

    if action in {"SET_VALUE", "CLEAR_CELL", "REPLACE_VALUE", "UNMERGE_RANGE", "MERGE_RANGE"}:
        base = {
            "sheet": sheet,
            "target": target,
        }
        if action == "SET_VALUE":
            base["value"] = None
        elif action == "REPLACE_VALUE":
            base["expected_old_value"] = None
            base["new_value"] = None
        return base

    if action == "ACCEPT_EXCEPTION":
        return {
            "test_id": finding.get("test_id"),
            "sheet": sheet,
            "target": target,
            "rows": finding.get("evidence", {}).get("rows")
                or finding.get("evidence", {}).get("candidate_rows"),
        }

    if action in {"PROFILE_CHANGE", "TEST_RULE_CHANGE", "MANUAL_FIX"}:
        return {"instruction": ""}

    return {}


def finding_to_review_item(finding: dict, profile: dict) -> dict:
    profile_name = str(profile.get("profile_name") or profile.get("name") or "")
    review_id = _stable_review_id(
        profile_name=profile_name,
        test_id=str(finding.get("test_id") or ""),
        sheet=finding.get("sheet"),
        target=finding.get("target"),
        status=str(finding.get("status") or ""),
    )

    status = str(finding.get("status") or "").upper()

    # Known exception means "current profile accepts it", not "review permanently closed".
    current_policy = None
    if status == "KNOWN_EXCEPTION":
        current_policy = {
            "state": "CURRENTLY_ACCEPTED_BY_PROFILE",
            "note": (
                "The current profile recognizes this exception. "
                "Reviewer may keep it, replace it with a repair, or change the rule."
            ),
        }
    elif status == "POSSIBLE_EXCEPTION":
        current_policy = {
            "state": "CANDIDATE_ONLY",
            "note": "Similarity was detected but no exception has been approved.",
        }
    elif status == "FAIL":
        current_policy = {
            "state": "UNRESOLVED_ERROR",
            "note": "The current profile/test classifies this as an error.",
        }
    else:
        current_policy = {
            "state": status or "OBSERVED",
            "note": "Review if required.",
        }

    reusable_resolution = None
    known_fix = match_known_fix(profile, finding)
    if known_fix is not None:
        current_policy = {
            "state": "KNOWN_REUSABLE_RESOLUTION",
            "note": (
                "This exact test/sheet/target/status signature has a reusable "
                "resolution in the profile. It may be accepted automatically "
                "during review with --accept-known."
            ),
            "known_fix_id": known_fix.get("id"),
        }
        reusable_resolution = {
            "kind": "KNOWN_FIX",
            "known_fix_id": known_fix.get("id"),
            "reason": known_fix.get("reason"),
            "resolution": known_fix.get("resolution") or {},
        }
    elif status == "KNOWN_EXCEPTION":
        reusable_resolution = {
            "kind": "KNOWN_EXCEPTION",
        }

    allowed = _allowed_actions(finding)

    return {
        "review_id": review_id,
        "review_state": "PENDING",
        "source": {
            "kind": "TEST_FINDING",
            "test_id": finding.get("test_id"),
            "status": finding.get("status"),
            "severity": finding.get("severity"),
        },
        "location": {
            "sheet": finding.get("sheet"),
            "target": finding.get("target"),
        },
        "message": finding.get("message"),
        "expected": finding.get("expected"),
        "observed": finding.get("observed"),
        "evidence": finding.get("evidence") or {},
        "machine_suggestion": {
            "suggested_exception": finding.get("suggested_exception"),
            "suggested_fix": finding.get("suggested_fix"),
        },
        "current_policy": current_policy,
        "reusable_resolution": reusable_resolution,
        "allowed_actions": [
            {
                "action": action,
                "description": ACTIONS[action]["description"],
                "execution_kind": ACTIONS[action]["execution_kind"],
                "parameter_template": _default_parameters(finding, action),
            }
            for action in allowed
        ],
        "decision": None,
    }


def build_review_queue(
    *,
    report: dict,
    profile: dict,
    package_manifest: dict,
    workbook: dict,
    report_path: str | None = None,
) -> dict:
    items = [
        finding_to_review_item(finding, profile)
        for finding in report.get("findings", [])
    ]

    counts = {}
    for item in items:
        status = item["source"].get("status") or "UNKNOWN"
        counts[status] = counts.get(status, 0) + 1

    run_id = report.get("run_id") or (
        f"run_{datetime.now().strftime('%Y%m%dT%H%M%S')}"
    )

    return {
        "schema": "cleaner.review_queue/0.1",
        "package": {
            "package_id": package_manifest.get("package_id"),
            "package_version": package_manifest.get("version"),
            "review_schema": package_manifest.get("review_schema"),
            "decision_schema": package_manifest.get("decision_schema"),
        },
        "run": {
            "run_id": run_id,
            "created_at": _now(),
            "script_id": report.get("script_id"),
            "kind": report.get("kind"),
            "raw_report_path": report_path,
        },
        "profile": {
            "schema_version": profile.get("schema_version"),
            "family": profile.get("family"),
            "profile_name": profile.get("profile_name"),
        },
        "workbook": workbook,
        "summary": {
            "total_items": len(items),
            "by_status": counts,
            "pending_review": len(items),
            "resolved": 0,
            "deferred": 0,
        },
        "items": items,
    }


def write_review_queue(queue: dict, path: str | Path) -> Path:
    path = Path(path)
    path.write_text(
        json.dumps(queue, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    return path
