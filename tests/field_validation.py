from __future__ import annotations

import re

from cleaner_core.card_map import scan_all_card_maps
from cleaner_core.contracts import Finding
from cleaner_core.status_library import load_status_library
from cleaner_core.field_schema import (
    discover_jalali_tokens,
    has_date_context_marker,
    infer_all_slot_schemas,
    is_valid_jalali,
    iter_role_slots,
    normalize_discovered_jalali_text,
    normalize_embedded_jalali_text,
    normalize_jalali,
    normalize_reference,
    normalize_status,
)

TEST_META = {
    "id": "FIELD_VALIDATION",
    "title": "Date, Reference, Status and Relationship Validation",
    "kind": "test",
    "profile_rule": "data_model.field_validation",
    "snapshot_mode": "openpyxl",
}


def _set_value_fix(*, field_key, sheet, target, observed, value, reason):
    return {
        "action": "SET_VALUE",
        "execution_kind": "WORKBOOK_CHANGE",
        "parameters": {
            "field_key": field_key,
            "sheet": sheet,
            "target": target,
            "value": value,
            "expected_old_value": observed,
        },
        "reason": reason,
    }


def _validation_config(profile: dict) -> dict:
    configured = profile.get("data_model", {}).get("field_validation", {})
    audit = configured.get("global_date_audit", {})
    relation = configured.get("receive_status_relation", {})
    chronology = configured.get("date_chronology", {})
    return {
        "global_date_audit": bool(audit.get("enabled", True)),
        "short_year_with_context": bool(audit.get("short_year_with_context", True)),
        "receive_status_relation": bool(relation.get("enabled", True)),
        "date_chronology": bool(chronology.get("enabled", True)),
    }


def _slot_key(card, slot) -> tuple[int, str]:
    return (int(card.record_index), str(slot.address))


def _same_vertical_event(left, right) -> bool:
    return not (
        left.row_offset_end < right.row_offset_start
        or right.row_offset_end < left.row_offset_start
    )


def _transaction_index(schema, slot) -> int | None:
    if not schema.block_width:
        return None
    return (slot.col_start - schema.data_start_col) // schema.block_width


def _relationship_findings(*, sheet, scan, schema, config) -> tuple[list[Finding], int, int]:
    """Require a populated status when a valid receive-date event is present.

    This mirrors the useful rule in the user's earlier COM checker, but uses the
    derived card/merge geometry instead of scanning rows blindly.
    """
    if not config["receive_status_relation"] or not schema.block_width:
        return [], 0, 0

    findings: list[Finding] = []
    checked = failed = 0

    for card in scan.cards:
        role_slots = [(slot, schema.role_for_slot(card, slot)) for slot in card.slots]
        receive_slots = []
        for slot, role in role_slots:
            if role != "receive_date":
                continue
            raw = slot.value
            if raw is None or str(raw).strip() == "":
                continue
            normalized = normalize_jalali(raw)
            if normalized is None or not is_valid_jalali(normalized):
                continue
            receive_slots.append(slot)

        for receive_slot in receive_slots:
            checked += 1
            tx = _transaction_index(schema, receive_slot)
            status_slots = [
                slot
                for slot, role in role_slots
                if role == "status"
                and _transaction_index(schema, slot) == tx
                and _same_vertical_event(receive_slot, slot)
            ]
            populated = [
                slot for slot in status_slots
                if slot.value is not None and str(slot.value).strip() != ""
            ]
            if populated:
                continue

            failed += 1
            status_targets = [slot.address for slot in status_slots]
            reason = (
                f"Receive date at {sheet}!{receive_slot.address} has no populated corresponding "
                f"status in the same transaction/vertical event."
            )
            findings.append(Finding(
                test_id="FIELD_VALIDATION",
                status="FAIL",
                severity="HIGH",
                sheet=sheet,
                target=receive_slot.address,
                message=reason,
                expected="Every receive-date event has a corresponding non-empty status",
                observed=receive_slot.value,
                evidence={
                    "field_role": "receive_date",
                    "audit_kind": "RECEIVE_STATUS_RELATION",
                    "document_region": f"{card.start_row}:{card.end_row}",
                    "transaction_index": tx,
                    "status_targets": status_targets,
                },
                suggested_fix=None,
            ))

    return findings, checked, failed


def _chronology_findings(*, sheet, scan, schema, config) -> tuple[list[Finding], int, int]:
    """Flag receive dates that precede their paired send dates.

    This is intentionally review-only. It identifies a temporal inconsistency but
    never guesses which date is wrong.
    """
    if not config["date_chronology"] or not schema.block_width:
        return [], 0, 0

    findings: list[Finding] = []
    checked = failed = 0
    for card in scan.cards:
        role_slots = [(slot, schema.role_for_slot(card, slot)) for slot in card.slots]
        send_slots = [(slot, normalize_jalali(slot.value)) for slot, role in role_slots if role == "send_date"]
        receive_slots = [(slot, normalize_jalali(slot.value)) for slot, role in role_slots if role == "receive_date"]

        for receive_slot, receive_date in receive_slots:
            if receive_date is None or not is_valid_jalali(receive_date):
                continue
            tx = _transaction_index(schema, receive_slot)
            candidates = [
                (slot, send_date)
                for slot, send_date in send_slots
                if send_date is not None
                and is_valid_jalali(send_date)
                and _transaction_index(schema, slot) == tx
                and _same_vertical_event(receive_slot, slot)
            ]
            if not candidates:
                continue
            # Prefer the send slot with the largest vertical overlap.
            def overlap(item):
                slot, _ = item
                return min(receive_slot.row_offset_end, slot.row_offset_end) - max(receive_slot.row_offset_start, slot.row_offset_start) + 1
            send_slot, send_date = max(candidates, key=overlap)
            checked += 1
            if receive_date >= send_date:
                continue
            failed += 1
            reason = (
                f"Receive date {receive_date} at {sheet}!{receive_slot.address} precedes "
                f"send date {send_date} at {sheet}!{send_slot.address}."
            )
            findings.append(Finding(
                test_id="FIELD_VALIDATION",
                status="FAIL",
                severity="MEDIUM",
                sheet=sheet,
                target=receive_slot.address,
                message=reason,
                expected="Receive date is on or after the paired send date",
                observed=receive_slot.value,
                evidence={
                    "field_role": "receive_date",
                    "audit_kind": "DATE_CHRONOLOGY",
                    "document_region": f"{card.start_row}:{card.end_row}",
                    "transaction_index": tx,
                    "send_target": send_slot.address,
                    "send_date": send_date,
                    "receive_date": receive_date,
                },
                suggested_fix=None,
            ))
    return findings, checked, failed


def run(snapshot, profile, log):
    log(
        "START",
        "FIELD_VALIDATION validates inferred semantic fields, then performs a global Jalali-token safety audit across every mapped card slot. Passing values are silent.",
    )
    card_scans = scan_all_card_maps(snapshot, profile)
    schemas = infer_all_slot_schemas(snapshot, profile)
    config = _validation_config(profile)
    findings: list[Finding] = []

    status_library_config = profile.get("data_model", {}).get("status_library")
    status_library_path = None
    if isinstance(status_library_config, str):
        status_library_path = status_library_config
    elif isinstance(status_library_config, dict):
        status_library_path = status_library_config.get("path")
    status_library = load_status_library(status_library_path)

    for sheet, schema in schemas.items():
        scan = card_scans[sheet]
        date_checked = date_failed = 0
        ref_checked = ref_failed = 0
        status_checked = status_failed = 0
        explanation_checked = explanation_failed = 0
        audit_tokens_checked = audit_failed = 0

        # Cache the dynamic role of every physical sub-slot. This lets the
        # safety-net scan everything while avoiding duplicate findings for fields
        # already handled by semantic date/explanation validation.
        roles: dict[tuple[int, str], str | None] = {}
        for card in scan.cards:
            for slot in card.slots:
                roles[_slot_key(card, slot)] = schema.role_for_slot(card, slot)

        for card, slot, role in iter_role_slots(scan, schema):
            raw = slot.value
            if raw is None or str(raw).strip() == "":
                continue

            if role in {"send_date", "receive_date", "date"} or role.startswith("date_"):
                date_checked += 1
                normalized = normalize_jalali(raw)
                valid = normalized is not None and is_valid_jalali(normalized)
                raw_text = str(raw).strip()
                if valid and raw_text == normalized:
                    continue
                date_failed += 1
                reason = (
                    f"{role} at {sheet}!{slot.address} is not a canonical valid Jalali date; "
                    f"observed={raw_text!r}."
                )
                fix = None
                if valid and normalized is not None:
                    reason += f" Normalized valid value={normalized!r}."
                    fix = _set_value_fix(
                        field_key=role,
                        sheet=sheet,
                        target=slot.address,
                        observed=raw,
                        value=normalized,
                        reason=reason,
                    )
                findings.append(Finding(
                    test_id="FIELD_VALIDATION",
                    status="FAIL",
                    severity="HIGH",
                    sheet=sheet,
                    target=slot.address,
                    message=reason,
                    expected="Valid canonical Jalali date YYYY/MM/DD",
                    observed=raw,
                    evidence={
                        "field_role": role,
                        "audit_kind": "SEMANTIC_DATE",
                        "document_region": f"{card.start_row}:{card.end_row}",
                        "normalized": normalized,
                        "calendar_valid": valid,
                    },
                    suggested_fix=fix,
                ))
                continue

            if role == "explanation":
                explanation_checked += 1
                raw_text = str(raw).strip()
                normalized_text, embedded_dates, invalid_tokens = normalize_embedded_jalali_text(raw_text)
                if invalid_tokens:
                    explanation_failed += 1
                    reason = (
                        f"Explanation at {sheet}!{slot.address} contains invalid Jalali-like date "
                        f"token(s) {list(invalid_tokens)}; observed={raw_text!r}."
                    )
                    findings.append(Finding(
                        test_id="FIELD_VALIDATION",
                        status="FAIL",
                        severity="HIGH",
                        sheet=sheet,
                        target=slot.address,
                        message=reason,
                        expected="Explanation text with valid canonical embedded Jalali dates",
                        observed=raw,
                        evidence={
                            "field_role": "explanation",
                            "audit_kind": "EXPLANATION_DATE",
                            "document_region": f"{card.start_row}:{card.end_row}",
                            "invalid_embedded_dates": list(invalid_tokens),
                        },
                        suggested_fix=None,
                    ))
                    continue
                if normalized_text != raw_text:
                    explanation_failed += 1
                    reason = (
                        f"Explanation at {sheet}!{slot.address} contains non-canonical embedded Jalali "
                        f"date(s); observed={raw_text!r}, normalized={normalized_text!r}."
                    )
                    findings.append(Finding(
                        test_id="FIELD_VALIDATION",
                        status="FAIL",
                        severity="MEDIUM",
                        sheet=sheet,
                        target=slot.address,
                        message=reason,
                        expected="Explanation text with canonical embedded Jalali dates",
                        observed=raw,
                        evidence={
                            "field_role": "explanation",
                            "audit_kind": "EXPLANATION_DATE",
                            "document_region": f"{card.start_row}:{card.end_row}",
                            "embedded_dates": list(embedded_dates),
                            "normalized": normalized_text,
                        },
                        suggested_fix=_set_value_fix(
                            field_key="explanation",
                            sheet=sheet,
                            target=slot.address,
                            observed=raw,
                            value=normalized_text,
                            reason=reason,
                        ),
                    ))
                continue

            if role == "reference" and schema.reference_rule is not None:
                ref_checked += 1
                raw_text = str(raw).strip()
                normalized = normalize_reference(raw)
                pattern = schema.reference_rule.regex
                if re.fullmatch(pattern, raw_text):
                    continue
                ref_failed += 1
                normalized_matches = re.fullmatch(pattern, normalized) is not None
                reason = (
                    f"Reference at {sheet}!{slot.address} does not match majority regex {pattern!r}; "
                    f"observed={raw_text!r}."
                )
                fix = None
                if normalized_matches and normalized != raw_text:
                    reason += f" Normalized candidate={normalized!r} matches the inferred rule."
                    fix = _set_value_fix(
                        field_key="reference",
                        sheet=sheet,
                        target=slot.address,
                        observed=raw,
                        value=normalized,
                        reason=reason,
                    )
                findings.append(Finding(
                    test_id="FIELD_VALIDATION",
                    status="FAIL",
                    severity="MEDIUM",
                    sheet=sheet,
                    target=slot.address,
                    message=reason,
                    expected=f"Reference matching majority regex {pattern}",
                    observed=raw,
                    evidence={
                        "field_role": "reference",
                        "audit_kind": "REFERENCE_REGEX",
                        "document_region": f"{card.start_row}:{card.end_row}",
                        "reference_regex": pattern,
                        "rule_coverage": schema.reference_rule.coverage,
                        "normalized": normalized,
                    },
                    suggested_fix=fix,
                ))
                continue

            if role == "status" and schema.status_values:
                status_checked += 1
                normalized = normalize_status(raw)
                raw_text = str(raw).strip()
                inferred = normalized in schema.status_values
                catalog_definition = status_library.definition(normalized)
                catalog_known = catalog_definition is not None

                # Status frequency and status validity are different concepts.
                # A rare but catalogued status (e.g. RJ = Rejected) is valid
                # even when it did not occur often enough to enter this
                # workbook's inferred majority vocabulary.
                if inferred or catalog_known:
                    if inferred and raw_text != normalized:
                        # Preserve the historical normalization behavior for a
                        # code already learned from this workbook. Catalog aliases
                        # are accepted losslessly; they are not rewritten merely
                        # because an alias exists.
                        status_failed += 1
                        reason = (
                            f"Status at {sheet}!{slot.address} is non-canonical; observed={raw_text!r}, "
                            f"normalized={normalized!r}."
                        )
                        findings.append(Finding(
                            test_id="FIELD_VALIDATION",
                            status="FAIL",
                            severity="MEDIUM",
                            sheet=sheet,
                            target=slot.address,
                            message=reason,
                            expected=f"Canonical status {normalized!r}",
                            observed=raw,
                            evidence={
                                "field_role": "status",
                                "audit_kind": "STATUS_VOCABULARY",
                                "document_region": f"{card.start_row}:{card.end_row}",
                                "status_vocabulary": list(schema.status_values),
                                "status_library_match": (catalog_definition.to_dict() if catalog_definition else None),
                                "normalized": normalized,
                            },
                            suggested_fix=_set_value_fix(
                                field_key="status",
                                sheet=sheet,
                                target=slot.address,
                                observed=raw,
                                value=normalized,
                                reason=reason,
                            ),
                        ))
                    continue

                status_failed += 1
                reason = (
                    f"Status at {sheet}!{slot.address} is neither in the inferred vocabulary "
                    f"{list(schema.status_values)} nor in the reusable status library; "
                    f"observed={raw_text!r}."
                )
                findings.append(Finding(
                    test_id="FIELD_VALIDATION",
                    status="FAIL",
                    severity="MEDIUM",
                    sheet=sheet,
                    target=slot.address,
                    message=reason,
                    expected=(
                        f"Status in inferred vocabulary {list(schema.status_values)} "
                        f"or reusable library {list(status_library.known_codes)}"
                    ),
                    observed=raw,
                    evidence={
                        "field_role": "status",
                        "audit_kind": "STATUS_VOCABULARY",
                        "document_region": f"{card.start_row}:{card.end_row}",
                        "status_vocabulary": list(schema.status_values),
                        "status_library_codes": list(status_library.known_codes),
                        "status_coverage": schema.status_coverage,
                        "normalized": normalized,
                    },
                    suggested_fix=None,
                ))

        # ------------------------------------------------------------------
        # GLOBAL DATE SAFETY NET
        # ------------------------------------------------------------------
        # The old COM checker was useful because it searched every cell rather
        # than only cells already understood by the schema. We keep that strength
        # here, but validate each discovered token with the real Jalali calendar.
        if config["global_date_audit"]:
            for card in scan.cards:
                for slot in card.slots:
                    raw = slot.value
                    if raw is None or str(raw).strip() == "":
                        continue
                    role = roles.get(_slot_key(card, slot))

                    allow_short = bool(
                        config["short_year_with_context"] and has_date_context_marker(raw)
                    )
                    audits = discover_jalali_tokens(raw, allow_short=allow_short)
                    if not audits:
                        continue
                    audit_tokens_checked += len(audits)

                    # Semantic date/explanation validation already emits the richer
                    # finding for the same physical slot. Count every discovered
                    # token here, but do not duplicate an existing date finding.
                    already_reported = any(
                        f.sheet == sheet
                        and f.target == slot.address
                        and f.evidence.get("audit_kind") in {"SEMANTIC_DATE", "EXPLANATION_DATE"}
                        for f in findings
                    )

                    invalid = [item for item in audits if not item["valid"]]
                    noncanonical = [item for item in audits if item["valid"] and not item["canonical"]]
                    if invalid:
                        if already_reported:
                            continue
                        audit_failed += 1
                        reason = (
                            f"Global date audit found invalid Jalali-like token(s) "
                            f"{[x['token'] for x in invalid]} at {sheet}!{slot.address}; "
                            f"observed={str(raw).strip()!r}."
                        )
                        findings.append(Finding(
                            test_id="FIELD_VALIDATION",
                            status="FAIL",
                            severity="HIGH",
                            sheet=sheet,
                            target=slot.address,
                            message=reason,
                            expected="Every Jalali-looking token inside card data is calendar-valid",
                            observed=raw,
                            evidence={
                                "field_role": role,
                                "audit_kind": "GLOBAL_DATE_TOKEN_SCAN",
                                "document_region": f"{card.start_row}:{card.end_row}",
                                "date_tokens": list(audits),
                            },
                            suggested_fix=None,
                        ))
                        continue

                    if noncanonical:
                        if already_reported:
                            continue
                        audit_failed += 1
                        normalized_text, _ = normalize_discovered_jalali_text(
                            raw, allow_short=allow_short
                        )
                        reason = (
                            f"Global date audit found non-canonical valid Jalali token(s) "
                            f"{[x['token'] for x in noncanonical]} at {sheet}!{slot.address}; "
                            f"normalized={normalized_text!r}."
                        )
                        findings.append(Finding(
                            test_id="FIELD_VALIDATION",
                            status="FAIL",
                            severity="MEDIUM",
                            sheet=sheet,
                            target=slot.address,
                            message=reason,
                            expected="Canonical Jalali date tokens YYYY/MM/DD",
                            observed=raw,
                            evidence={
                                "field_role": role,
                                "audit_kind": "GLOBAL_DATE_TOKEN_SCAN",
                                "document_region": f"{card.start_row}:{card.end_row}",
                                "date_tokens": list(audits),
                                "normalized": normalized_text,
                            },
                            suggested_fix=_set_value_fix(
                                field_key="embedded_date",
                                sheet=sheet,
                                target=slot.address,
                                observed=raw,
                                value=normalized_text,
                                reason=reason,
                            ),
                        ))

        relation_findings, relation_checked, relation_failed = _relationship_findings(
            sheet=sheet,
            scan=scan,
            schema=schema,
            config=config,
        )
        findings.extend(relation_findings)

        chronology_findings, chronology_checked, chronology_failed = _chronology_findings(
            sheet=sheet,
            scan=scan,
            schema=schema,
            config=config,
        )
        findings.extend(chronology_findings)

        log(
            "SUMMARY",
            f"{sheet}: dates checked={date_checked}, failed={date_failed}; "
            f"references checked={ref_checked}, failed={ref_failed}; "
            f"explanations checked={explanation_checked}, failed={explanation_failed}; "
            f"statuses checked={status_checked}, failed={status_failed}; "
            f"global date tokens checked={audit_tokens_checked}, failed={audit_failed}; "
            f"receive/status relations checked={relation_checked}, failed={relation_failed}; "
            f"date chronology pairs checked={chronology_checked}, failed={chronology_failed}.",
        )
        if schema.reference_rule is None:
            log(
                "INFO",
                f"{sheet}: reference validation inactive because no high-confidence reference regex was inferred.",
            )

    log("DONE", f"FIELD_VALIDATION finished with {len(findings)} review finding(s).")
    return findings
