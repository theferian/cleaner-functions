from __future__ import annotations

import re

from review.decisions import apply_decision_to_queue, make_decision


_WBS = re.compile(r"[0-9]+(?:\.[0-9]+)*\Z")
_EMPTY_TOKENS = {"", "-", "–", "—"}
_POLICY = "GENERAL_DOCUMENT_AUTO_WBS_V1"


def _can_auto_accept(item: dict, existing_wbs: set[str], used: set[str]) -> tuple[dict, str] | None:
    """Only accept a profile-generated, parent-based placeholder for an empty WBS.

    An actual (possibly mistyped) nonempty identifier, fallback-root suggestion,
    unsafe target, or duplicate proposed identifier must still be reviewed.
    """
    source = item.get("source") or {}
    evidence = item.get("evidence") or {}
    suggestion = (item.get("machine_suggestion") or {}).get("suggested_fix") or {}
    params = suggestion.get("parameters") or {}
    location = item.get("location") or {}
    if item.get("review_state") != "PENDING":
        return None
    if (source.get("test_id") != "IDENTIFIERS" or source.get("status") != "FAIL"
            or evidence.get("field_key") != "wbs" or params.get("field_key") != "wbs"
            or suggestion.get("action") != "SET_VALUE"):
        return None
    if not location.get("sheet") or not location.get("target"):
        return None
    if (params.get("sheet") != location["sheet"] or params.get("target") != location["target"]):
        return None
    observed = item.get("observed")
    if ("" if observed is None else str(observed).strip()) not in _EMPTY_TOKENS:
        return None
    expected = params.get("expected_old_value")
    if ("expected_old_value" not in params
            or (None if expected is None else str(expected).strip()) !=
               (None if observed is None else str(observed).strip())):
        return None
    parent = str(evidence.get("nearest_valid_wbs_above") or "")
    value = str(params.get("value") or "")
    if (not _WBS.fullmatch(parent) or not _WBS.fullmatch(value)
            or not value.startswith(parent + ".")):
        return None
    suffix = value[len(parent)+1:]
    if not suffix.isdigit() or int(suffix) < 1000:
        return None
    if value in existing_wbs or value in used:
        return None
    return params, value


def accept_general_document_wbs(queue: dict, profile: dict, existing_wbs: set[str]) -> int:
    """Convert safe IDENTIFIERS WBS suggestions to auditable review decisions.

    Mutates the review queue, but never modifies the Excel workbook. This is a
    family-level opt-in using the existing nearest-valid-above WBS profile rule.
    """
    if (str(profile.get("family") or "").upper() != "GENERAL_DOCUMENT"
            or str((queue.get("run") or {}).get("script_id") or "").upper() != "IDENTIFIERS"):
        return 0

    fields = (profile.get("data_model") or {}).get("family_fields") or []
    wbs_fields = [f for f in fields if f.get("key") == "wbs"]
    if len(wbs_fields) != 1:
        return 0
    cleaning = wbs_fields[0].get("cleaning") or {}
    if str(cleaning.get("strategy") or "").upper() != "NEAREST_VALID_ABOVE_APPEND_SEQUENCE":
        return 0

    used: set[str] = set()
    accepted = 0
    for item in queue.get("items", []):
        candidate = _can_auto_accept(item, existing_wbs, used)
        if candidate is None:
            continue
        params, value = candidate
        reason = (item.get("machine_suggestion") or {}).get("suggested_fix", {}).get("reason") or ""
        decision = make_decision(
            "SET_VALUE",
            parameters=params,
            reason=f"[{_POLICY}] Deterministic placeholder; {reason}",
            reviewer="GENERAL_DOCUMENT_FAMILY_POLICY",
        )
        decision["origin"] = _POLICY
        apply_decision_to_queue(queue, item["review_id"], decision)
        used.add(value)
        accepted += 1
    summary = queue.setdefault("summary", {})
    summary["pending_review"] = sum(x.get("review_state") == "PENDING" for x in queue.get("items", []))
    summary["resolved"] = sum(x.get("review_state") == "RESOLVED" for x in queue.get("items", []))
    summary["deferred"] = sum(x.get("review_state") == "DEFERRED" for x in queue.get("items", []))
    if accepted:
        summary["auto_accepted_wbs"] = accepted
        summary["auto_accept_policy"] = _POLICY
    return accepted
