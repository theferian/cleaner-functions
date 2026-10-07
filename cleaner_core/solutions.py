from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path
import hashlib
import json
import re
from typing import Any

from .context import document_relative_target
from .ranges import parse_range


SCHEMA = "cleaner.project_solutions/0.1"
WORKBOOK_ACTIONS = {"SET_VALUE", "CLEAR_CELL", "REPLACE_VALUE", "UNMERGE_RANGE", "MERGE_RANGE"}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _norm(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().split()).casefold()


def _project_slug(project: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", str(project or "PROJECT").upper()).strip("-")
    return slug or "PROJECT"


def new_registry(project_id: str) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "project_id": str(project_id),
        "next_sequence": 1,
        "solutions": [],
    }


def load_project_solutions(path: str | Path, *, project_id: str, create: bool = False) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        if not create:
            raise FileNotFoundError(path)
        return new_registry(project_id)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.setdefault("schema", SCHEMA)
    payload.setdefault("project_id", str(project_id))
    payload.setdefault("next_sequence", 1)
    payload.setdefault("solutions", [])
    return payload


def save_project_solutions(registry: dict[str, Any], path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(registry, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    return path


def _solution_handle(registry: dict[str, Any]) -> str:
    seq = int(registry.get("next_sequence") or 1)
    registry["next_sequence"] = seq + 1
    return f"{_project_slug(registry.get('project_id'))}-SOL-{seq:04d}"


def _identity_from_item(item: dict) -> dict[str, Any]:
    evidence = item.get("evidence") or {}
    identity = deepcopy(evidence.get("document_identity") or {})
    # record_index is useful evidence but not a durable matcher because rows and
    # ordering can change between weekly revisions.
    identity.pop("record_index", None)
    return {k: v for k, v in identity.items() if v not in (None, "")}


def _semantic_from_parts(params: dict, evidence: dict) -> dict[str, Any]:
    """Build one canonical semantic identity for project-solution matching.

    ``field_key`` and ``field_role`` historically overlapped.  Prefer the role
    emitted by the validator when present, and use field_key mainly for stages
    such as IDENTIFIERS.  The document-relative target makes multiple repairs
    inside one logical document distinct while surviving absolute row moves.
    """
    semantic: dict[str, Any] = {}
    field_role = evidence.get("field_role") or params.get("field_role")
    field_key = params.get("field_key") or evidence.get("field_key")
    audit_kind = evidence.get("audit_kind") or params.get("audit_kind")

    if field_role not in (None, ""):
        semantic["field_role"] = field_role
    elif field_key not in (None, ""):
        semantic["field_key"] = field_key

    if audit_kind not in (None, ""):
        semantic["audit_kind"] = audit_kind

    for key in ("transaction_index", "nearest_valid_wbs_above"):
        value = evidence.get(key) if evidence.get(key) not in (None, "") else params.get(key)
        if value not in (None, ""):
            semantic[key] = value

    relative = evidence.get("document_relative_target")
    if relative not in (None, ""):
        semantic["document_relative_target"] = relative
    return semantic


def _semantic_from_item(item: dict) -> dict[str, Any]:
    evidence = item.get("evidence") or {}
    params = (item.get("decision") or {}).get("parameters") or {}
    return _semantic_from_parts(params, evidence)


def _stable_signature(match: dict[str, Any]) -> str:
    raw = json.dumps(match, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def solution_from_decision(item: dict, *, project_id: str, run_id: str | None = None) -> dict | None:
    decision = item.get("decision") or {}
    action = str(decision.get("action") or "").upper()
    if action not in WORKBOOK_ACTIONS:
        return None
    # A project solution represents an approved repair, not an unresolved case.
    # Decisions auto-applied from an existing project solution are still useful:
    # they can enrich an older exact-target solution with newly available logical
    # document identity after a later pipeline version/run.

    source = item.get("source") or {}
    location = item.get("location") or {}
    params = deepcopy(decision.get("parameters") or {})
    sheet = params.get("sheet") or location.get("sheet")
    target = params.get("target") or location.get("target")
    test_id = source.get("test_id")
    if not test_id or not sheet or not target:
        return None

    identity = _identity_from_item(item)
    semantic = _semantic_from_item(item)
    observed = item.get("observed")
    # Identifier placeholders may legitimately alternate between "-" and blank
    # across weekly revisions.  The stable document identity + WBS field is the
    # project contract, so do not bind that repair to one placeholder spelling.
    if str(test_id).upper() == "IDENTIFIERS" and (semantic.get("field_key") == "wbs"):
        observed = None

    match = {
        "test_id": str(test_id),
        "status": str(source.get("status") or ""),
        "sheet": str(sheet),
        "document_identity": identity,
        "semantic": semantic,
        "observed": observed,
        "target_fallback": str(target),
    }

    # Keep the approved project value. Unlike a family-level generic cleaner,
    # project-specific repairs should remain stable from one weekly revision to
    # the next when the same document/problem is rediscovered.
    resolution = {
        "mode": "PROJECT_DECISION_TEMPLATE",
        "action": action,
        "parameters": params,
    }

    signature_match = {k: deepcopy(v) for k, v in match.items() if k != "target_fallback"}
    # Old/contextless repairs must remain distinct by physical target until they
    # can be enriched with document identity.  Once identity exists, absolute
    # row position is intentionally excluded so the solution can follow a moved
    # document in later revisions.
    if not identity:
        signature_match["target_fallback"] = str(target)

    return {
        "handle": None,
        "enabled": True,
        "project_id": str(project_id),
        "kind": "WORKBOOK_FIX",
        "signature": _stable_signature(signature_match),
        "match": match,
        "resolution": resolution,
        "reason": decision.get("reason") or item.get("message") or "Approved project repair.",
        "created_at": _now(),
        "updated_at": _now(),
        "times_confirmed": 1,
        "source": {
            "run_id": run_id,
            "review_id": item.get("review_id"),
            "decision_origin": decision.get("origin") or "HUMAN_REVIEW",
            "project_solution_handle": decision.get("project_solution_handle"),
        },
        "history": [],
    }


def _same_solution(existing: dict, candidate: dict) -> bool:
    return str(existing.get("signature") or "") == str(candidate.get("signature") or "")


def upsert_solution(registry: dict[str, Any], candidate: dict) -> tuple[dict, bool]:
    for existing in registry.get("solutions", []):
        if not existing.get("enabled", True) and existing.get("superseded_by"):
            continue
        if not _same_solution(existing, candidate):
            continue
        old_source = existing.get("source") or {}
        new_source = candidate.get("source") or {}
        same_review_event = (
            str(old_source.get("run_id") or "") == str(new_source.get("run_id") or "")
            and str(old_source.get("review_id") or "") == str(new_source.get("review_id") or "")
        )
        if not same_review_event:
            existing.setdefault("history", []).append({
                "at": _now(),
                "resolution": deepcopy(existing.get("resolution") or {}),
                "reason": existing.get("reason"),
                "source": deepcopy(old_source),
            })
            existing["times_confirmed"] = int(existing.get("times_confirmed") or 1) + 1
        existing["resolution"] = deepcopy(candidate["resolution"])
        existing["reason"] = candidate.get("reason") or existing.get("reason")
        existing["updated_at"] = _now()
        existing["source"] = deepcopy(new_source)
        existing["enabled"] = True
        return existing, False

    candidate = deepcopy(candidate)
    candidate["handle"] = _solution_handle(registry)
    registry.setdefault("solutions", []).append(candidate)
    return candidate, True


def _decision_items(payload: dict) -> list[dict]:
    return [x for x in payload.get("decisions", []) if isinstance(x, dict)]


def _enrich_existing_solution(existing: dict, candidate: dict) -> dict:
    """Refresh a known solution from a later matched finding without changing its handle."""
    old_match = existing.get("match") or {}
    new_match = candidate.get("match") or {}
    old_identity = old_match.get("document_identity") or {}
    new_identity = new_match.get("document_identity") or {}
    if new_identity and not old_identity:
        old_match["document_identity"] = deepcopy(new_identity)
    old_semantic = old_match.get("semantic") or {}
    new_semantic = new_match.get("semantic") or {}
    if new_semantic:
        merged = dict(old_semantic)
        merged.update(new_semantic)
        old_match["semantic"] = merged
    if new_match.get("observed") not in (None, ""):
        old_match["observed"] = new_match.get("observed")
    if new_match.get("target_fallback"):
        old_match["target_fallback"] = new_match.get("target_fallback")
    existing["match"] = old_match
    signature_match = {k: deepcopy(v) for k, v in old_match.items() if k != "target_fallback"}
    if not (old_match.get("document_identity") or {}):
        signature_match["target_fallback"] = old_match.get("target_fallback")
    existing["signature"] = _stable_signature(signature_match)
    existing["updated_at"] = _now()
    existing["source"] = deepcopy(candidate.get("source") or {})
    return existing


def sync_project_solutions_from_decisions_payload(registry: dict[str, Any], payload: dict) -> dict[str, Any]:
    project_id = registry.get("project_id") or (payload.get("profile") or {}).get("profile_name") or "PROJECT"
    run_id = (payload.get("run") or {}).get("run_id")
    created = []
    updated = []
    skipped = []
    for item in _decision_items(payload):
        candidate = solution_from_decision(item, project_id=str(project_id), run_id=run_id)
        if candidate is None:
            skipped.append(item.get("review_id"))
            continue
        source_handle = (candidate.get("source") or {}).get("project_solution_handle")
        if source_handle:
            existing = next(
                (x for x in registry.get("solutions", []) if x.get("handle") == source_handle),
                None,
            )
            if existing is not None:
                solution = _enrich_existing_solution(existing, candidate)
                updated.append(solution.get("handle"))
                continue
        solution, is_new = upsert_solution(registry, candidate)
        (created if is_new else updated).append(solution.get("handle"))
    return {
        "created_handles": created,
        "updated_handles": updated,
        "skipped_review_ids": skipped,
    }


def sync_project_solutions_from_decisions_file(registry: dict[str, Any], path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return sync_project_solutions_from_decisions_payload(registry, payload)


def _identity_matches(expected: dict, actual: dict) -> bool:
    # Prefer stable Name. Document type and valid WBS further constrain if they
    # exist on both sides, but a WBS repair can match without an existing WBS.
    expected_name = _norm(expected.get("name"))
    actual_name = _norm(actual.get("name"))
    if expected_name:
        if not actual_name or expected_name != actual_name:
            return False
    elif expected:
        # If there is some identity but no name, compare available durable keys.
        for key in ("document_type", "document_type_a", "document_type_b", "category", "type", "code", "wbs"):
            ev = _norm(expected.get(key))
            if ev and ev != _norm(actual.get(key)):
                return False
    else:
        return False

    for key in ("document_type", "document_type_a", "document_type_b", "category", "type", "code", "wbs"):
        ev = _norm(expected.get(key))
        av = _norm(actual.get(key))
        if ev and av and ev != av:
            return False
    return True


def _semantic_matches(expected: dict, actual: dict) -> bool:
    for key, expected_value in expected.items():
        actual_value = actual.get(key)
        if str(expected_value) != str(actual_value):
            return False
    return True


def match_project_solution(registry: dict[str, Any] | None, finding: dict[str, Any]) -> dict | None:
    if not registry:
        return None
    test_id = _norm(finding.get("test_id"))
    status = _norm(finding.get("status"))
    sheet = _norm(finding.get("sheet"))
    target = _norm(finding.get("target"))
    evidence = finding.get("evidence") or {}
    actual_identity = evidence.get("document_identity") or {}
    actual_semantic = _semantic_from_parts({}, evidence)
    observed = finding.get("observed")

    identity_matches = []
    fallback_matches = []
    for solution in registry.get("solutions", []):
        if not solution.get("enabled", True):
            continue
        match = solution.get("match") or {}
        if _norm(match.get("test_id")) != test_id:
            continue
        if _norm(match.get("sheet")) != sheet:
            continue
        expected_status = _norm(match.get("status"))
        if expected_status and expected_status != status:
            continue
        expected_semantic = match.get("semantic") or {}
        if expected_semantic and not _semantic_matches(expected_semantic, actual_semantic):
            continue
        expected_observed = match.get("observed")
        if expected_observed not in (None, "") and _norm(expected_observed) != _norm(observed):
            continue

        expected_identity = match.get("document_identity") or {}
        if _identity_matches(expected_identity, actual_identity):
            identity_matches.append(solution)
            continue
        if target and _norm(match.get("target_fallback")) == target:
            fallback_matches.append(solution)

    # Identity-based project memory is stronger than old cell-address memory.
    if len(identity_matches) == 1:
        result = deepcopy(identity_matches[0])
        result["match_mode"] = "DOCUMENT_IDENTITY"
        return result
    if len(identity_matches) > 1:
        # Ambiguous project memory must never auto-apply.
        return None
    if len(fallback_matches) == 1:
        result = deepcopy(fallback_matches[0])
        result["match_mode"] = "TARGET_FALLBACK"
        return result
    return None


def decision_from_project_solution(solution: dict, finding: dict) -> dict | None:
    resolution = solution.get("resolution") or {}
    if str(resolution.get("mode") or "").upper() != "PROJECT_DECISION_TEMPLATE":
        return None
    action = str(resolution.get("action") or "").upper()
    if action not in WORKBOOK_ACTIONS:
        return None
    params = deepcopy(resolution.get("parameters") or {})
    # Project memory follows the logical finding to its current physical cell.
    params["sheet"] = finding.get("sheet")
    params["target"] = finding.get("target")
    return {
        "action": action,
        "parameters": params,
        "reason": solution.get("reason") or f"Applied project solution {solution.get('handle')}",
        "origin": "PROJECT_SOLUTION",
        "project_solution_handle": solution.get("handle"),
    }


def _identity_from_region_dict(region: dict) -> dict[str, Any]:
    identity: dict[str, Any] = {}
    fields = region.get("fields") or {}
    for key in (
        "document_type", "document_type_a", "document_type_b",
        "category", "type", "name", "code", "wbs",
    ):
        field = fields.get(key) or {}
        value = field.get("value")
        if value in (None, ""):
            continue
        text = str(value).strip()
        if not text:
            continue
        if key == "wbs" and re.fullmatch(r"\d+(?:\.\d+)*", text) is None:
            continue
        if key == "code" and text in {"-", "–", "—"}:
            continue
        identity[key] = value
    return identity


def _context_from_regions_payload(
    regions_payload: dict | None,
    *,
    sheet: str | None,
    target: str | None,
) -> tuple[dict[str, Any], str | None]:
    if not regions_payload or not sheet or not target:
        return {}, None
    try:
        row = parse_range(str(target)).r1
    except Exception:
        return {}, None
    sheet_payload = (regions_payload.get("sheets") or {}).get(str(sheet)) or {}
    for region in sheet_payload.get("regions", []):
        try:
            start = int(region.get("start_row"))
            end = int(region.get("end_row"))
        except (TypeError, ValueError):
            continue
        if start <= row <= end:
            return (
                _identity_from_region_dict(region),
                document_relative_target(str(target), start),
            )
    return {}, None


def _canonicalize_semantic(semantic: dict[str, Any] | None) -> dict[str, Any]:
    semantic = dict(semantic or {})
    role = semantic.get("field_role")
    key = semantic.get("field_key")
    if role not in (None, ""):
        # Historical solutions often stored both aliases.  Keeping both makes a
        # later finding fail to match because findings normally expose role only.
        semantic.pop("field_key", None)
    elif key in (None, ""):
        semantic.pop("field_key", None)
    return {k: v for k, v in semantic.items() if v not in (None, "")}


def _signature_for_match(match: dict[str, Any]) -> str:
    payload = {k: deepcopy(v) for k, v in match.items() if k != "target_fallback"}
    if not (match.get("document_identity") or {}):
        payload["target_fallback"] = match.get("target_fallback")
    return _stable_signature(payload)


def _semantic_from_reason(reason: str | None) -> dict[str, Any]:
    text = str(reason or "")
    low = text.casefold()
    if "global date audit" in low:
        return {"audit_kind": "GLOBAL_DATE_TOKEN_SCAN"}
    if "explanation at" in low and ("jalali" in low or "date" in low):
        return {"field_role": "explanation", "audit_kind": "EXPLANATION_DATE"}
    if "required wbs" in low or "proposed wbs" in low:
        return {"field_key": "wbs"}
    return {}


def _observed_from_reason(reason: str | None) -> Any:
    text = str(reason or "")
    # Current validator messages consistently print observed=<repr>.  Keep this
    # deliberately conservative: if parsing is uncertain, return None rather
    # than inventing a project-memory precondition.
    m = re.search(r"observed=(['\"])(.*?)\1", text)
    if m:
        return m.group(2)
    m = re.search(r"observed='([^']*)'", text)
    if m:
        return m.group(1)
    return None


def _resolution_target(solution: dict) -> str | None:
    params = ((solution.get("resolution") or {}).get("parameters") or {})
    value = params.get("target")
    return str(value) if value not in (None, "") else None


def _resolution_value_key(solution: dict) -> tuple[Any, ...]:
    resolution = solution.get("resolution") or {}
    params = resolution.get("parameters") or {}
    return (
        str(resolution.get("action") or "").upper(),
        params.get("value"),
        params.get("new_value"),
    )


def repair_project_solutions_registry(
    registry: dict[str, Any],
    *,
    document_regions_payload: dict | None = None,
) -> dict[str, Any]:
    """Repair legacy project-solution identity/collision issues in place.

    This is intentionally migration-oriented.  It never deletes history:
    superseded duplicates remain in the registry with ``enabled=false`` and a
    ``superseded_by`` handle.
    """
    enriched: list[str] = []
    split_created: list[str] = []
    superseded: list[str] = []

    # 1) Canonicalize semantics, enrich with current document identity and
    # document-relative target, and detect old signature collisions where one
    # solution's match target differs from its current resolution target.
    originals = list(registry.get("solutions", []))
    for solution in originals:
        if not solution.get("enabled", True):
            continue
        match = solution.setdefault("match", {})
        match["semantic"] = _canonicalize_semantic(match.get("semantic") or {})
        match_target = match.get("target_fallback")
        resolution_target = _resolution_target(solution)

        # Historical bug: target_fallback was excluded from signatures even when
        # no document identity existed.  Two contextless fixes could therefore
        # collapse into one solution.  If current resolution points elsewhere,
        # restore the original target's resolution from history and split the
        # current target into its own solution.
        if match_target and resolution_target and _norm(match_target) != _norm(resolution_target):
            current_resolution = deepcopy(solution.get("resolution") or {})
            current_reason = solution.get("reason")
            current_source = deepcopy(solution.get("source") or {})

            historic = None
            for event in reversed(solution.get("history") or []):
                params = ((event.get("resolution") or {}).get("parameters") or {})
                if _norm(params.get("target")) == _norm(match_target):
                    historic = event
                    break
            if historic is not None:
                solution["resolution"] = deepcopy(historic.get("resolution") or {})
                solution["reason"] = historic.get("reason") or solution.get("reason")
                solution["source"] = deepcopy(historic.get("source") or solution.get("source") or {})
                inferred = _semantic_from_reason(solution.get("reason"))
                if inferred:
                    match["semantic"] = inferred

            identity, relative = _context_from_regions_payload(
                document_regions_payload,
                sheet=match.get("sheet"),
                target=resolution_target,
            )
            split_match = {
                "test_id": match.get("test_id"),
                "status": match.get("status"),
                "sheet": match.get("sheet"),
                "document_identity": identity,
                "semantic": _semantic_from_reason(current_reason),
                "observed": _observed_from_reason(current_reason),
                "target_fallback": resolution_target,
            }
            if relative:
                split_match["semantic"]["document_relative_target"] = relative
            split = {
                "handle": None,
                "enabled": True,
                "project_id": registry.get("project_id"),
                "kind": solution.get("kind") or "WORKBOOK_FIX",
                "signature": _signature_for_match(split_match),
                "match": split_match,
                "resolution": current_resolution,
                "reason": current_reason,
                "created_at": _now(),
                "updated_at": _now(),
                "times_confirmed": 1,
                "source": current_source,
                "history": [],
                "migration_note": f"Split from collided legacy solution {solution.get('handle')}",
            }
            new_solution, is_new = upsert_solution(registry, split)
            if is_new:
                split_created.append(new_solution.get("handle"))

        identity, relative = _context_from_regions_payload(
            document_regions_payload,
            sheet=match.get("sheet"),
            target=match.get("target_fallback"),
        )
        changed = False
        if identity and not (match.get("document_identity") or {}):
            match["document_identity"] = identity
            changed = True
        semantic = _canonicalize_semantic(match.get("semantic") or {})
        if relative and not semantic.get("document_relative_target"):
            semantic["document_relative_target"] = relative
            changed = True
        match["semantic"] = semantic
        if _norm(match.get("test_id")) == "identifiers" and semantic.get("field_key") == "wbs":
            if match.get("observed") not in (None, ""):
                match["observed"] = None
                changed = True
        solution["match"] = match
        solution["signature"] = _signature_for_match(match)
        if changed:
            solution["updated_at"] = _now()
            enriched.append(solution.get("handle"))

    # 2) Consolidate exact physical duplicates created while the richer identity
    # layer was being introduced.  Keep the earlier handle, enrich it from the
    # richer duplicate, and retain the duplicate as a disabled audit record.
    active = [x for x in registry.get("solutions", []) if x.get("enabled", True)]
    for i, keeper in enumerate(active):
        if not keeper.get("enabled", True):
            continue
        km = keeper.get("match") or {}
        for duplicate in active[i + 1:]:
            if not duplicate.get("enabled", True):
                continue
            dm = duplicate.get("match") or {}
            same_physical = (
                _norm(km.get("test_id")) == _norm(dm.get("test_id"))
                and _norm(km.get("sheet")) == _norm(dm.get("sheet"))
                and _norm(km.get("target_fallback")) == _norm(dm.get("target_fallback"))
                and _resolution_value_key(keeper) == _resolution_value_key(duplicate)
            )
            same_signature = keeper.get("signature") == duplicate.get("signature")
            if not (same_physical or same_signature):
                continue

            kid = km.get("document_identity") or {}
            did = dm.get("document_identity") or {}
            if did and not kid:
                km["document_identity"] = deepcopy(did)
            ks = _canonicalize_semantic(km.get("semantic") or {})
            ds = _canonicalize_semantic(dm.get("semantic") or {})
            merged_semantic = dict(ks)
            for key, value in ds.items():
                if key not in merged_semantic or merged_semantic[key] in (None, ""):
                    merged_semantic[key] = value
            km["semantic"] = merged_semantic
            keeper["match"] = km
            keeper["signature"] = _signature_for_match(km)
            keeper.setdefault("history", []).append({
                "at": _now(),
                "migration": "MERGED_DUPLICATE_PROJECT_SOLUTION",
                "duplicate_handle": duplicate.get("handle"),
                "duplicate_match": deepcopy(dm),
                "duplicate_resolution": deepcopy(duplicate.get("resolution") or {}),
            })
            duplicate["enabled"] = False
            duplicate["superseded_by"] = keeper.get("handle")
            duplicate["superseded_at"] = _now()
            duplicate["migration_note"] = "Superseded by richer/equivalent project solution."
            superseded.append(duplicate.get("handle"))

    return {
        "enriched_handles": [x for x in enriched if x],
        "split_created_handles": [x for x in split_created if x],
        "superseded_handles": [x for x in superseded if x],
        "active_count": sum(1 for x in registry.get("solutions", []) if x.get("enabled", True)),
    }


def make_manual_project_solution(
    registry: dict[str, Any],
    *,
    test_id: str,
    sheet: str,
    target: str,
    value: Any,
    observed: Any = None,
    field_role: str | None = None,
    field_key: str | None = None,
    audit_kind: str | None = None,
    document_regions_payload: dict | None = None,
    reason: str = "Manual project-solution migration.",
) -> tuple[dict, bool]:
    identity, relative = _context_from_regions_payload(
        document_regions_payload, sheet=sheet, target=target
    )
    evidence: dict[str, Any] = {"document_identity": identity}
    if relative:
        evidence["document_relative_target"] = relative
    if field_role:
        evidence["field_role"] = field_role
    if field_key:
        evidence["field_key"] = field_key
    if audit_kind:
        evidence["audit_kind"] = audit_kind
    item = {
        "review_id": f"MANUAL_PROJECT_SOLUTION_{test_id}_{sheet}_{target}",
        "source": {"test_id": test_id, "status": "FAIL"},
        "location": {"sheet": sheet, "target": target},
        "message": reason,
        "observed": observed,
        "evidence": evidence,
        "decision": {
            "action": "SET_VALUE",
            "parameters": {
                "sheet": sheet,
                "target": target,
                "value": value,
                **({"field_key": field_key} if field_key else {}),
            },
            "reason": reason,
            "origin": "MANUAL_MIGRATION",
        },
    }
    candidate = solution_from_decision(
        item, project_id=str(registry.get("project_id") or "PROJECT"), run_id="MIGRATION"
    )
    if candidate is None:
        raise ValueError("Unable to create project solution from manual migration arguments.")
    return upsert_solution(registry, candidate)
