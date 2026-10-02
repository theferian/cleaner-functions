from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path
import hashlib
import json
from typing import Any


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _slug_id(prefix: str, payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12].upper()
    return f"{prefix}_{digest}"


def _same_exception(existing: dict, candidate: dict) -> bool:
    em = existing.get("match", {})
    cm = candidate.get("match", {})
    if str(em.get("test_id") or "").upper() != str(cm.get("test_id") or "").upper():
        return False

    es = em.get("sheet", "*")
    cs = cm.get("sheet", "*")
    if es not in ("*", "", None, cs) and cs not in ("*", "", None, es):
        return False

    erows = {int(x) for x in em.get("rows", [])}
    crows = {int(x) for x in cm.get("rows", [])}
    if erows and crows and crows.issubset(erows):
        return True

    etarget = str(em.get("target") or "").upper()
    ctarget = str(cm.get("target") or "").upper()
    return bool(etarget and ctarget and etarget == ctarget)


def _same_fix(existing: dict, candidate: dict) -> bool:
    em = existing.get("match", {})
    cm = candidate.get("match", {})
    return (
        str(em.get("test_id") or "").upper() == str(cm.get("test_id") or "").upper()
        and str(em.get("sheet") or "").upper() == str(cm.get("sheet") or "").upper()
        and str(em.get("target") or "").upper() == str(cm.get("target") or "").upper()
        and str(em.get("status") or "").upper() == str(cm.get("status") or "").upper()
    )


def _exception_from_item(item: dict, *, source_run_id: str | None) -> dict | None:
    source = item.get("source") or {}
    location = item.get("location") or {}
    decision = item.get("decision") or {}
    params = decision.get("parameters") or {}

    test_id = params.get("test_id") or source.get("test_id")
    sheet = params.get("sheet") or location.get("sheet")
    target = params.get("target") or location.get("target")
    rows = params.get("rows")

    if not test_id or not sheet:
        return None

    match = {
        "test_id": test_id,
        "sheet": sheet,
    }
    if rows:
        match["rows"] = [int(x) for x in rows]
    if target:
        match["target"] = target

    return {
        "id": _slug_id("PROMOTED_EXCEPTION", match),
        "enabled": True,
        "reason": decision.get("reason") or "Promoted from reviewed cleaner decision.",
        "match": match,
        "source": {
            "kind": "PROMOTED_REVIEW_DECISION",
            "run_id": source_run_id,
            "review_id": item.get("review_id"),
            "promoted_at": _now(),
        },
    }


def _fix_from_item(item: dict, *, source_run_id: str | None) -> dict | None:
    source = item.get("source") or {}
    location = item.get("location") or {}
    decision = item.get("decision") or {}
    action = str(decision.get("action") or "").upper()
    params = deepcopy(decision.get("parameters") or {})

    test_id = source.get("test_id")
    sheet = params.get("sheet") or location.get("sheet")
    target = params.get("target") or location.get("target")
    status = source.get("status")

    if not test_id or not sheet or not target:
        return None

    match = {
        "test_id": test_id,
        "sheet": sheet,
        "target": target,
        "status": status,
    }

    # Identifier SET_VALUE suggestions are context-dependent. Recompute the
    # value from the current workbook instead of reusing last week's value.
    if str(test_id).upper() == "IDENTIFIERS" and action == "SET_VALUE":
        resolution = {
            "mode": "CURRENT_MACHINE_SUGGESTION",
            "expected_action": "SET_VALUE",
        }
    else:
        resolution = {
            "mode": "DECISION_TEMPLATE",
            "action": action,
            "parameters": params,
        }

    return {
        "id": _slug_id("PROMOTED_FIX", match),
        "enabled": True,
        "reason": decision.get("reason") or "Promoted from reviewed cleaner decision.",
        "match": match,
        "resolution": resolution,
        "source": {
            "kind": "PROMOTED_REVIEW_DECISION",
            "run_id": source_run_id,
            "review_id": item.get("review_id"),
            "last_decision": deepcopy(decision),
            "promoted_at": _now(),
        },
    }


def promote_decisions_to_profile(
    profile: dict[str, Any],
    decisions_payload: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Convert reviewed decisions into reusable profile knowledge.

    Promotion is intentionally explicit and conservative:
    - ACCEPT_EXCEPTION -> known_exceptions
    - deterministic workbook changes -> known_fixes
    - IDENTIFIERS SET_VALUE -> reuse the *current* machine suggestion next run
    - DEFER/DISMISS/manual/free-text rule changes are not promoted automatically
    """
    updated = deepcopy(profile)
    known_exceptions = updated.setdefault("known_exceptions", [])
    known_fixes = updated.setdefault("known_fixes", [])

    run_id = decisions_payload.get("run", {}).get("run_id")
    promoted_exceptions = []
    promoted_fixes = []
    skipped = []

    for item in decisions_payload.get("decisions", []):
        decision = item.get("decision") or {}
        action = str(decision.get("action") or "").upper()

        if action == "ACCEPT_EXCEPTION":
            candidate = _exception_from_item(item, source_run_id=run_id)
            if candidate is None:
                skipped.append({"review_id": item.get("review_id"), "reason": "Incomplete exception match."})
                continue
            if any(_same_exception(x, candidate) for x in known_exceptions if x.get("enabled", True)):
                skipped.append({"review_id": item.get("review_id"), "reason": "Already covered by known exception."})
                continue
            known_exceptions.append(candidate)
            promoted_exceptions.append(candidate)
            continue

        if action in {"SET_VALUE", "CLEAR_CELL", "REPLACE_VALUE", "UNMERGE_RANGE", "MERGE_RANGE"}:
            candidate = _fix_from_item(item, source_run_id=run_id)
            if candidate is None:
                skipped.append({"review_id": item.get("review_id"), "reason": "Incomplete known-fix match."})
                continue
            existing_index = next(
                (i for i, x in enumerate(known_fixes) if _same_fix(x, candidate)),
                None,
            )
            if existing_index is None:
                known_fixes.append(candidate)
            else:
                # Latest reviewed decision becomes the reusable policy for this
                # exact test/sheet/target/status signature.
                candidate["id"] = known_fixes[existing_index].get("id", candidate["id"])
                known_fixes[existing_index] = candidate
            promoted_fixes.append(candidate)
            continue

        skipped.append({
            "review_id": item.get("review_id"),
            "reason": f"Action {action or 'UNKNOWN'} is not auto-promotable.",
        })

    report = {
        "source_run_id": run_id,
        "promoted_exception_count": len(promoted_exceptions),
        "promoted_fix_count": len(promoted_fixes),
        "skipped_count": len(skipped),
        "promoted_exceptions": promoted_exceptions,
        "promoted_fixes": promoted_fixes,
        "skipped": skipped,
    }
    return updated, report


def save_profile(profile: dict[str, Any], path: str | Path) -> Path:
    path = Path(path)
    path.write_text(
        json.dumps(profile, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    return path


def match_known_fix(profile: dict[str, Any], finding: dict[str, Any]) -> dict | None:
    test_id = str(finding.get("test_id") or "").upper()
    sheet = str(finding.get("sheet") or "").upper()
    target = str(finding.get("target") or "").upper()
    status = str(finding.get("status") or "").upper()

    for fix in profile.get("known_fixes", []):
        if not fix.get("enabled", True):
            continue
        match = fix.get("match", {})
        if str(match.get("test_id") or "").upper() != test_id:
            continue
        if str(match.get("sheet") or "").upper() != sheet:
            continue
        if str(match.get("target") or "").upper() != target:
            continue
        match_status = str(match.get("status") or "").upper()
        if match_status and match_status != status:
            continue
        return fix
    return None


def decision_from_known_policy(item: dict[str, Any]) -> dict[str, Any] | None:
    """Build a review decision from a queue item's reusable profile policy."""
    policy = item.get("reusable_resolution") or {}
    kind = str(policy.get("kind") or "").upper()

    if kind == "KNOWN_EXCEPTION":
        loc = item.get("location") or {}
        evidence = item.get("evidence") or {}
        return {
            "action": "ACCEPT_EXCEPTION",
            "parameters": {
                "test_id": item.get("source", {}).get("test_id"),
                "sheet": loc.get("sheet"),
                "target": loc.get("target"),
                "rows": evidence.get("rows") or evidence.get("candidate_rows"),
            },
            "reason": "Accepted from reusable profile exception policy.",
            "origin": "REUSABLE_PROFILE",
        }

    if kind != "KNOWN_FIX":
        return None

    resolution = policy.get("resolution") or {}
    mode = str(resolution.get("mode") or "").upper()

    if mode == "CURRENT_MACHINE_SUGGESTION":
        suggestion = item.get("machine_suggestion", {}).get("suggested_fix")
        if not suggestion:
            return None
        expected = str(resolution.get("expected_action") or "").upper()
        actual = str(suggestion.get("action") or "").upper()
        if expected and actual != expected:
            return None
        return {
            "action": actual,
            "parameters": deepcopy(suggestion.get("parameters") or {}),
            "reason": suggestion.get("reason") or "Applied reusable profile policy to current machine suggestion.",
            "origin": "REUSABLE_PROFILE_CURRENT_SUGGESTION",
        }

    if mode == "DECISION_TEMPLATE":
        action = str(resolution.get("action") or "").upper()
        if not action:
            return None
        params = deepcopy(resolution.get("parameters") or {})
        loc = item.get("location") or {}
        if "sheet" in params:
            params["sheet"] = loc.get("sheet")
        if "target" in params:
            params["target"] = loc.get("target")
        return {
            "action": action,
            "parameters": params,
            "reason": policy.get("reason") or "Applied reusable profile known fix.",
            "origin": "REUSABLE_PROFILE",
        }

    return None
