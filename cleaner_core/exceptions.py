from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path
import hashlib
import json
import re
from typing import Any, Iterable


REGISTRY_SCHEMA = "cleaner.exception_registry/0.1"


AUTO_TRACK_AUDIT_KINDS = {"DATE_CHRONOLOGY"}


def is_auto_tracked_finding(finding: Any) -> bool:
    """Return True for anomaly classes that should be tracked without review.

    Auto-tracking never accepts or repairs data. It only opens/refreshes an
    INVESTIGATE case so recurring audit findings do not create repetitive
    human review gates.
    """
    if hasattr(finding, "to_dict"):
        finding = finding.to_dict()
    evidence = finding.get("evidence") or {}
    return (
        _norm(finding.get("status")).upper() == "FAIL"
        and _audit_kind(evidence).upper() in AUTO_TRACK_AUDIT_KINDS
    )


def auto_track_findings(
    registry: dict[str, Any],
    findings: Iterable[Any],
    *,
    run_id: str,
) -> dict[str, Any]:
    """Open or refresh non-blocking investigation cases for safe audit classes."""
    created: list[str] = []
    updated: list[str] = []

    for raw in findings:
        finding = raw.to_dict() if hasattr(raw, "to_dict") else raw
        if not is_auto_tracked_finding(finding):
            continue

        match = exception_match_from_finding(finding)
        case = _case_for_match(registry, match)
        is_new = case is None
        if case is None:
            case = {
                "handle": _next_handle(registry),
                "match_key": _match_key(match),
                "match": match,
                "first_seen_at": _now(),
                "detection_count": 0,
                "source": {
                    "first_run_id": run_id,
                    "origin": "AUTO_TRACK_POLICY",
                },
                "history": [],
            }
            registry.setdefault("cases", []).append(case)

        previous_run = case.get("last_seen_run_id") or case.get("last_run_id")
        if previous_run != run_id:
            case["detection_count"] = int(case.get("detection_count") or 0) + 1

        evidence = deepcopy(finding.get("evidence") or {})
        audit_kind = _audit_kind(evidence).upper()
        accepted = _norm(case.get("case_state")).upper() == "ACCEPTED"
        case.update({
            "title": audit_kind.replace("_", " ").title() or "Cleaner anomaly",
            "note": _norm(finding.get("message")),
            "message": _norm(finding.get("message")),
            "severity": _norm(finding.get("severity")) or case.get("severity") or "INFO",
            "case_state": case.get("case_state") if accepted else "OPEN",
            "workflow_status": case.get("workflow_status") if accepted else "INVESTIGATE",
            "classification": case.get("classification") if accepted else "DATA_ANOMALY",
            "tags": list(dict.fromkeys([
                *case.get("tags", []),
                _norm(finding.get("test_id")).lower(),
                audit_kind.lower(),
                _norm(evidence.get("field_role")).lower(),
                "auto-tracked",
                "investigate",
            ])),
            "owner": case.get("owner") or "",
            "evidence": evidence,
            "last_run_id": run_id,
            "last_seen_run_id": run_id,
            "last_seen_at": _now(),
        })
        case["tags"] = [tag for tag in case["tags"] if tag]

        if is_new or previous_run != run_id:
            case.setdefault("history", []).append(
                _history_event(
                    "AUTO_TRACKED",
                    run_id=run_id,
                    audit_kind=audit_kind,
                    reason="Matched non-blocking anomaly auto-track policy.",
                )
            )

        (created if is_new else updated).append(case["handle"])

    registry["updated_at"] = _now()
    return {
        "created_handles": list(dict.fromkeys(created)),
        "updated_handles": list(dict.fromkeys(updated)),
        "auto_tracked_count": len(set(created + updated)),
    }


def open_chronology_issue_rows(registry: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the current open chronology investigation register as flat rows."""
    rows: list[dict[str, Any]] = []
    for case in registry.get("cases", []):
        match = case.get("match") or {}
        if _norm(match.get("audit_kind")).upper() != "DATE_CHRONOLOGY":
            continue
        if _norm(case.get("case_state")).upper() != "OPEN":
            continue
        evidence = case.get("evidence") or {}
        rows.append({
            "handle": case.get("handle"),
            "workflow_status": case.get("workflow_status"),
            "severity": case.get("severity"),
            "sheet": match.get("sheet"),
            "send_target": evidence.get("send_target"),
            "send_date": evidence.get("send_date"),
            "receive_target": match.get("target"),
            "receive_date": evidence.get("receive_date"),
            "document_region": evidence.get("document_region"),
            "transaction_index": evidence.get("transaction_index"),
            "owner": case.get("owner") or "",
            "first_seen_at": case.get("first_seen_at"),
            "last_seen_at": case.get("last_seen_at"),
            "detection_count": int(case.get("detection_count") or 0),
            "message": case.get("message") or case.get("note"),
        })
    return sorted(rows, key=lambda row: (str(row.get("sheet") or ""), str(row.get("receive_target") or "")))


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _norm(value: Any) -> str:
    return str(value or "").strip()


def _slug(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9]+", "-", value.strip()).strip("-")
    return value.upper()


def new_exception_registry(profile_name: str) -> dict[str, Any]:
    return {
        "schema": REGISTRY_SCHEMA,
        "profile_name": profile_name,
        "created_at": _now(),
        "updated_at": _now(),
        "next_sequence": 1,
        "cases": [],
    }


def load_exception_registry(
    path: str | Path,
    *,
    profile_name: str,
    create: bool = True,
) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        if not create:
            raise FileNotFoundError(path)
        return new_exception_registry(profile_name)

    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != REGISTRY_SCHEMA:
        raise ValueError(
            f"Unsupported exception registry schema: {payload.get('schema')!r}"
        )
    payload.setdefault("profile_name", profile_name)
    payload.setdefault("next_sequence", 1)
    payload.setdefault("cases", [])
    return payload


def save_exception_registry(registry: dict[str, Any], path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    registry["updated_at"] = _now()
    path.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    return path


def _audit_kind(evidence: dict[str, Any]) -> str:
    return _norm(evidence.get("audit_kind") or evidence.get("kind"))


def exception_match_from_item(item: dict[str, Any]) -> dict[str, Any]:
    source = item.get("source") or {}
    location = item.get("location") or {}
    evidence = item.get("evidence") or {}
    return {
        "test_id": _norm(source.get("test_id")),
        "sheet": _norm(location.get("sheet")),
        "target": _norm(location.get("target")),
        "audit_kind": _audit_kind(evidence),
        "field_role": _norm(evidence.get("field_role")),
    }


def exception_match_from_finding(finding: Any) -> dict[str, Any]:
    if hasattr(finding, "to_dict"):
        finding = finding.to_dict()
    evidence = finding.get("evidence") or {}
    return {
        "test_id": _norm(finding.get("test_id")),
        "sheet": _norm(finding.get("sheet")),
        "target": _norm(finding.get("target")),
        "audit_kind": _audit_kind(evidence),
        "field_role": _norm(evidence.get("field_role")),
    }


def _match_key(match: dict[str, Any]) -> str:
    raw = "|".join(
        _norm(match.get(key)).upper()
        for key in ("test_id", "sheet", "target", "audit_kind", "field_role")
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _same_match(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return _match_key(left) == _match_key(right)


def _next_handle(registry: dict[str, Any]) -> str:
    profile = _slug(_norm(registry.get("profile_name")) or "PROJECT")
    sequence = int(registry.get("next_sequence") or 1)
    registry["next_sequence"] = sequence + 1
    return f"{profile}-EXC-{sequence:04d}"


def _default_tags(item: dict[str, Any], *, accepted: bool) -> list[str]:
    source = item.get("source") or {}
    evidence = item.get("evidence") or {}
    tags = []
    if source.get("test_id"):
        tags.append(_norm(source["test_id"]).lower())
    if evidence.get("audit_kind"):
        tags.append(_norm(evidence["audit_kind"]).lower())
    if evidence.get("field_role"):
        tags.append(_norm(evidence["field_role"]).lower())
    tags.append("accepted-exception" if accepted else "investigate")
    return list(dict.fromkeys(tag for tag in tags if tag))


def _title_from_item(item: dict[str, Any]) -> str:
    evidence = item.get("evidence") or {}
    audit_kind = _norm(evidence.get("audit_kind"))
    if audit_kind:
        return audit_kind.replace("_", " ").title()
    message = _norm(item.get("message"))
    if message:
        return message[:120]
    return "Cleaner exception"


def _history_event(kind: str, **extra: Any) -> dict[str, Any]:
    event = {"at": _now(), "event": kind}
    event.update(extra)
    return event


def _is_profile_superseded_case(case: dict[str, Any]) -> bool:
    """Return True for historical cases retired in favour of profile knowledge.

    These cases remain in the registry for audit history, but they are terminal:
    later runs must not reopen them, count them as active, or attach them to new
    review items. The reusable profile rule is the canonical representation.
    """
    return (
        _norm(case.get("workflow_status")).upper() == "SUPERSEDED_BY_PROFILE"
        or _norm(case.get("classification")).upper() == "PROFILE_KNOWN_EXCEPTION"
    )


def _case_for_match(registry: dict[str, Any], match: dict[str, Any]) -> dict[str, Any] | None:
    for case in registry.get("cases", []):
        if _is_profile_superseded_case(case):
            continue
        if _same_match(case.get("match") or {}, match):
            return case
    return None


def case_for_review_item(registry: dict[str, Any] | None, item: dict[str, Any]) -> dict[str, Any] | None:
    if not registry:
        return None
    return _case_for_match(registry, exception_match_from_item(item))


def case_for_finding(registry: dict[str, Any] | None, finding: dict[str, Any]) -> dict[str, Any] | None:
    if not registry:
        return None
    return _case_for_match(registry, exception_match_from_finding(finding))


def _parse_tags(value: Any) -> list[str]:
    if isinstance(value, list):
        raw = value
    else:
        raw = re.split(r"[,;]", _norm(value)) if _norm(value) else []
    tags = [_norm(x).lower().replace(" ", "-") for x in raw if _norm(x)]
    return list(dict.fromkeys(tags))


def _decision_origin(item: dict[str, Any]) -> str:
    return _norm((item.get("decision") or {}).get("origin")).upper()


def _is_reusable_profile_decision(item: dict[str, Any]) -> bool:
    """True when review was auto-resolved from already-reusable profile knowledge.

    Such decisions are useful for resolved-state ingestion, but they must not
    create a second exception case: the profile policy is already the canonical
    record for that known condition.
    """
    return _decision_origin(item).startswith("REUSABLE_PROFILE")


def _target_rows(target: str) -> set[int]:
    """Extract row numbers covered by a simple A1 target/range."""
    target = _norm(target).replace("$", "").upper()
    match = re.fullmatch(r"[A-Z]{1,3}(\d+)(?::[A-Z]{1,3}(\d+))?", target)
    if not match:
        return set()
    start = int(match.group(1))
    end = int(match.group(2) or start)
    lo, hi = sorted((start, end))
    return set(range(lo, hi + 1))


def _profile_exception_covers_case(rule: dict[str, Any], case: dict[str, Any]) -> bool:
    if not rule.get("enabled", True):
        return False
    rm = rule.get("match") or {}
    cm = case.get("match") or {}
    if _norm(rm.get("test_id")).upper() != _norm(cm.get("test_id")).upper():
        return False

    rule_sheet = _norm(rm.get("sheet") or "*").upper()
    case_sheet = _norm(cm.get("sheet")).upper()
    if rule_sheet not in {"", "*", case_sheet}:
        return False

    rule_target = _norm(rm.get("target")).replace("$", "").upper()
    case_target = _norm(cm.get("target")).replace("$", "").upper()
    if rule_target:
        return bool(case_target and rule_target == case_target)

    rule_rows = {int(x) for x in (rm.get("rows") or [])}
    if rule_rows:
        rows = _target_rows(case_target)
        return bool(rows and rows.issubset(rule_rows))

    return False


def retire_profile_covered_cases(
    registry: dict[str, Any],
    profile: dict[str, Any],
) -> dict[str, Any]:
    """Retire redundant accepted cases already represented by profile knowledge.

    We preserve the case/history for auditability but remove it from the active
    exception workflow by marking it RESOLVED / SUPERSEDED_BY_PROFILE.
    """
    rules = [x for x in profile.get("known_exceptions", []) if x.get("enabled", True)]
    retired: list[str] = []
    for case in registry.get("cases", []):
        if _norm(case.get("case_state")).upper() != "ACCEPTED":
            continue
        matched_rule = next((r for r in rules if _profile_exception_covers_case(r, case)), None)
        if matched_rule is None:
            continue
        if _norm(case.get("workflow_status")).upper() == "SUPERSEDED_BY_PROFILE":
            continue
        case["case_state"] = "RESOLVED"
        case["workflow_status"] = "SUPERSEDED_BY_PROFILE"
        case["classification"] = "PROFILE_KNOWN_EXCEPTION"
        case["profile_rule_id"] = matched_rule.get("id")
        case["resolved_at"] = _now()
        case["tags"] = list(dict.fromkeys([*case.get("tags", []), "profile-known"]))
        case.setdefault("history", []).append(
            _history_event(
                "SUPERSEDED_BY_PROFILE",
                profile_rule_id=matched_rule.get("id"),
                reason="Condition is already represented by reusable profile knowledge.",
            )
        )
        retired.append(case.get("handle"))
    if retired:
        registry["updated_at"] = _now()
    return {
        "retired_count": len(retired),
        "retired_handles": retired,
    }


def upsert_case_from_review_decision(
    registry: dict[str, Any],
    item: dict[str, Any],
    *,
    run_id: str | None = None,
) -> dict[str, Any] | None:
    decision = item.get("decision") or {}
    action = _norm(decision.get("action")).upper()
    if _is_reusable_profile_decision(item):
        return None
    if action not in {"DEFER", "TRACK_EXCEPTION", "ACCEPT_EXCEPTION"}:
        return None

    params = decision.get("parameters") or {}
    accepted = action == "ACCEPT_EXCEPTION"
    match = exception_match_from_item(item)
    case = _case_for_match(registry, match)
    created = case is None

    if case is None:
        case = {
            "handle": _next_handle(registry),
            "match_key": _match_key(match),
            "match": match,
            "first_seen_at": _now(),
            "last_seen_at": _now(),
            "detection_count": 1,
            "source": {
                "first_review_id": item.get("review_id"),
                "first_run_id": run_id,
            },
            "history": [],
        }
        registry.setdefault("cases", []).append(case)

    title = _norm(params.get("title")) or case.get("title") or _title_from_item(item)
    reason = _norm(decision.get("reason"))
    note = reason or _norm(params.get("note")) or _norm(item.get("message"))
    supplied_tags = _parse_tags(params.get("tags"))
    tags = supplied_tags or _default_tags(item, accepted=accepted)
    owner = _norm(params.get("owner"))

    case.update({
        "title": title,
        "note": note,
        "severity": _norm((item.get("source") or {}).get("severity")) or case.get("severity") or "INFO",
        "case_state": "ACCEPTED" if accepted else "OPEN",
        "workflow_status": "KNOWN_ACCEPTED" if accepted else _norm(params.get("workflow_status")) or "INVESTIGATE",
        "classification": "ACCEPTED_EXCEPTION" if accepted else "DATA_ANOMALY",
        "tags": list(dict.fromkeys([*case.get("tags", []), *tags])),
        "owner": owner or case.get("owner") or "",
        "last_review_id": item.get("review_id"),
        "last_run_id": run_id or case.get("last_run_id"),
        "last_seen_at": case.get("last_seen_at") or _now(),
        "message": _norm(item.get("message")),
    })
    case.setdefault("history", []).append(
        _history_event(
            "CREATED" if created else "REVIEW_UPDATED",
            action=action,
            review_id=item.get("review_id"),
            run_id=run_id,
            workflow_status=case["workflow_status"],
            note=note,
        )
    )
    return case


def sync_registry_from_decisions_payload(
    registry: dict[str, Any],
    decisions_payload: dict[str, Any],
) -> dict[str, Any]:
    run_id = (decisions_payload.get("run") or {}).get("run_id")
    created_or_updated = []
    ignored_reusable = 0
    for item in decisions_payload.get("decisions", []):
        if _is_reusable_profile_decision(item):
            ignored_reusable += 1
            continue
        case = upsert_case_from_review_decision(registry, item, run_id=run_id)
        if case is not None:
            created_or_updated.append(case["handle"])
    registry["updated_at"] = _now()
    return {
        "case_count": len(registry.get("cases", [])),
        "updated_handles": list(dict.fromkeys(created_or_updated)),
        "ignored_reusable_profile_decisions": ignored_reusable,
    }


def sync_registry_from_decisions_file(
    registry: dict[str, Any],
    path: str | Path,
) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return sync_registry_from_decisions_payload(registry, payload)


def reconcile_stage_findings(
    registry: dict[str, Any],
    findings: Iterable[Any],
    *,
    stage_id: str,
    run_id: str,
) -> dict[str, Any]:
    """Refresh open exception cases from the latest run of one stage.

    Open tracked exceptions remain visible while the finding is still detected.
    If a later run of the same stage no longer produces the matching finding,
    the case is closed as NO_LONGER_DETECTED. Accepted exceptions are not
    auto-closed because their absence may be caused by profile suppression.
    """
    stage_id = _norm(stage_id).upper()
    current = []
    for finding in findings:
        if hasattr(finding, "to_dict"):
            finding = finding.to_dict()
        current.append((exception_match_from_finding(finding), finding))

    detected = 0
    resolved = 0
    for case in registry.get("cases", []):
        match = case.get("match") or {}
        if _norm(match.get("test_id")).upper() != stage_id:
            continue
        if _is_profile_superseded_case(case):
            continue
        if case.get("case_state") == "ACCEPTED":
            continue

        matched = next(
            (finding for finding_match, finding in current if _same_match(match, finding_match)),
            None,
        )
        if matched is not None:
            detected += 1
            previous_run = case.get("last_seen_run_id") or case.get("last_run_id")
            case["last_seen_at"] = _now()
            case["last_seen_run_id"] = run_id
            case["last_run_id"] = run_id
            case["message"] = _norm(matched.get("message"))
            if previous_run != run_id:
                case["detection_count"] = int(case.get("detection_count") or 0) + 1
            if case.get("case_state") == "RESOLVED":
                case["case_state"] = "OPEN"
                case["workflow_status"] = "INVESTIGATE"
                case.setdefault("history", []).append(
                    _history_event("REOPENED", run_id=run_id, reason="Finding detected again.")
                )
            continue

        if case.get("case_state") == "OPEN":
            case["case_state"] = "RESOLVED"
            case["workflow_status"] = "NO_LONGER_DETECTED"
            case["resolved_at"] = _now()
            case["resolved_run_id"] = run_id
            case.setdefault("history", []).append(
                _history_event(
                    "AUTO_RESOLVED",
                    run_id=run_id,
                    reason="Matching finding was not detected in the latest stage run.",
                )
            )
            resolved += 1

    registry["updated_at"] = _now()
    return {
        "detected_open_cases": detected,
        "auto_resolved_cases": resolved,
        "case_count": len(registry.get("cases", [])),
    }
