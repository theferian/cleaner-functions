from __future__ import annotations

from openpyxl.utils import get_column_letter

from cleaner_core.contracts import Finding
from cleaner_core.document_regions import (
    boundary_config,
    column_for,
    fields_by_key,
    scan_document_regions,
)
from cleaners.identifier_cleaner import (
    WbsProposalState,
    is_empty_name,
    is_valid_sequence_identifier,
    normalize_digits,
    propose_empty_name,
    proposed_set_value_fix,
)


TEST_META = {
    "id": "IDENTIFIERS",
    "title": "Required Identifier Check",
    "kind": "test",
    "profile_rule": "data_model",
    "snapshot_mode": "openpyxl",
}


def _sequence_fields(fields: dict[str, dict]) -> dict[str, dict]:
    """Fields repaired by nearest-valid-above + deterministic suffix.

    WBS is the original use case. Project dialects may opt another required
    identifier (for example FSH Code) into exactly the same strategy by profile.
    """
    result: dict[str, dict] = {}
    for key, fdef in fields.items():
        cleaning = fdef.get("cleaning") or {}
        strategy = str(cleaning.get("strategy") or "").upper()
        if key == "wbs" and not fdef.get("required", True):
            continue
        if key == "wbs" or strategy == "NEAREST_VALID_ABOVE_APPEND_SEQUENCE":
            result[key] = fdef
    return result


def _expected_description(label: str, validation: dict) -> str:
    kind = str(validation.get("kind") or "NON_EMPTY").upper()
    if kind == "REGEX" and validation.get("pattern"):
        return f"{label} matching {validation['pattern']}"
    return f"Non-empty {label}"


def run(snapshot, profile, log):
    fields = fields_by_key(profile)
    name_def = fields.get("name")
    wbs_def = fields.get("wbs")

    if not name_def or not wbs_def:
        msg = "Profile must define family fields 'name' and 'wbs'."
        log("PROFILE_MISMATCH", msg)
        return [Finding(
            test_id="IDENTIFIERS",
            status="PROFILE_MISMATCH",
            severity="CRITICAL",
            message=msg,
        )]

    target_sheets = (
        profile.get("structure", {}).get("m_line", {}).get("target_sheets")
        or snapshot.sheet_names()
    )
    boundary_cfg = boundary_config(profile)
    name_cleaning = name_def.get("cleaning", {})
    seq_defs = _sequence_fields(fields)

    findings = []
    log(
        "START",
        "IDENTIFIERS checks required mapped identifier fields on derived DocumentRegion anchors.",
    )
    if seq_defs:
        details = []
        for key, fdef in seq_defs.items():
            cleaning = fdef.get("cleaning") or {}
            details.append(
                f"{fdef.get('label') or key}: nearest valid above + sequence from "
                f"{cleaning.get('sequence_start', 1000)}"
            )
        log("INFO", "Deterministic sequence repairs: " + "; ".join(details) + ".")

    for sheet in target_sheets:
        if not snapshot.has_sheet(sheet):
            log("WARNING", f"{sheet}: sheet not found; identifier check skipped.")
            continue

        mapped = {}
        for key, fdef in fields.items():
            col = column_for(profile, sheet, key, fdef)
            if col is not None:
                mapped[key] = col

        if "name" not in mapped or "wbs" not in mapped:
            msg = f"{sheet}: Name/WBS column mapping is incomplete."
            log("PROFILE_MISMATCH", msg)
            findings.append(Finding(
                test_id="IDENTIFIERS",
                status="PROFILE_MISMATCH",
                severity="CRITICAL",
                sheet=sheet,
                message=msg,
                evidence={"field_map": mapped},
            ))
            continue

        boundary_scan = scan_document_regions(snapshot, profile, sheet)
        mapped_text = ", ".join(
            f"{fields[key].get('label') or key}={get_column_letter(col)}"
            for key, col in sorted(mapped.items(), key=lambda kv: kv[1])
        )
        log(
            "STAGE",
            f"{sheet}: checking {len(boundary_scan.regions)} derived document "
            f"region(s) from row {boundary_cfg['first_data_row']}; {mapped_text}.",
        )

        if boundary_scan.ambiguities:
            log(
                "WARNING",
                f"{sheet}: boundary detector still reports "
                f"{len(boundary_scan.ambiguities)} ambiguity/ambiguities. "
                "The pipeline should normally review DOCUMENT_BOUNDARIES before IDENTIFIERS.",
            )

        seq_states: dict[str, WbsProposalState] = {}
        for key, fdef in seq_defs.items():
            if key not in mapped:
                continue
            cleaning = fdef.get("cleaning") or {}
            seq_states[key] = WbsProposalState(
                sequence_start=int(cleaning.get("sequence_start", 1000)),
                separator=str(cleaning.get("separator", ".")),
                fallback_root_start=int(cleaning.get("fallback_root_start", 1000)),
            )

        scanned_records = 0
        name_errors = 0
        sequence_errors = {key: 0 for key in seq_states}

        for region in boundary_scan.regions:
            scanned_records += 1
            row = region.anchor_row
            name_state = region.field("name")

            if name_state is not None and is_empty_name(name_state.value):
                name_errors += 1
                proposed = propose_empty_name(row, name_cleaning)
                reason = (
                    f"Required Name is empty at {sheet}!{name_state.address}; "
                    f"proposed deterministic placeholder {proposed!r}."
                )
                fix = proposed_set_value_fix(
                    field_key="name",
                    sheet=sheet,
                    target=name_state.address,
                    value=proposed,
                    reason=reason,
                    expected_old_value=name_state.value,
                )
                log("FAIL", reason)
                findings.append(Finding(
                    test_id="IDENTIFIERS",
                    status="FAIL",
                    severity="HIGH",
                    sheet=sheet,
                    target=name_state.address,
                    message=reason,
                    expected="Non-empty Name",
                    observed=name_state.value,
                    evidence={
                        "field_key": "name",
                        "row": row,
                        "document_region": region.target,
                        "merge": name_state.merge,
                    },
                    suggested_fix=fix,
                ))

            for key, proposal_state in seq_states.items():
                anchor = region.field(key)
                if anchor is None:
                    continue
                fdef = seq_defs[key]
                label = str(fdef.get("label") or key.upper())
                validation = fdef.get("validation") or {}
                raw = anchor.value
                if is_valid_sequence_identifier(raw, validation):
                    proposal_state.observe_valid(raw)
                    continue

                sequence_errors[key] += 1
                proposed, parent = proposal_state.propose()
                normalized_raw = normalize_digits(raw)
                reason = (
                    f"Required {label} is empty/invalid at {sheet}!{anchor.address}; "
                    f"observed={normalized_raw!r}. Proposed {label}={proposed!r}"
                    + (
                        f" using nearest valid {label} above {parent!r}."
                        if parent is not None
                        else " using fallback root placeholder sequence."
                    )
                )
                fix = proposed_set_value_fix(
                    field_key=key,
                    sheet=sheet,
                    target=anchor.address,
                    value=proposed,
                    reason=reason,
                    expected_old_value=raw,
                )
                log("FAIL", reason)
                findings.append(Finding(
                    test_id="IDENTIFIERS",
                    status="FAIL",
                    severity="HIGH",
                    sheet=sheet,
                    target=anchor.address,
                    message=reason,
                    expected=_expected_description(label, validation),
                    observed=raw,
                    evidence={
                        "field_key": key,
                        "row": row,
                        "document_region": region.target,
                        "merge": anchor.merge,
                        f"nearest_valid_{key}_above": parent,
                        f"proposed_{key}": proposed,
                    },
                    suggested_fix=fix,
                ))

        error_text = ", ".join(
            [f"empty Name={name_errors}"]
            + [f"invalid/empty {seq_defs[key].get('label') or key}={count}" for key, count in sequence_errors.items()]
        )
        log(
            "SUMMARY",
            f"{sheet}: document regions checked={scanned_records}, {error_text}.",
        )

        if name_errors == 0 and all(count == 0 for count in sequence_errors.values()):
            findings.append(Finding(
                test_id="IDENTIFIERS",
                status="PASS",
                severity="INFO",
                sheet=sheet,
                message=f"{sheet}: all derived document regions satisfy required identifier rules.",
                evidence={"document_regions_checked": scanned_records},
            ))

    log("DONE", f"IDENTIFIERS finished with {len(findings)} finding(s).")
    return findings
