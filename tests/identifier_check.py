from __future__ import annotations

from openpyxl.utils import get_column_letter

from cleaner_core.contracts import Finding
from cleaners.identifier_cleaner import (
    WbsProposalState,
    is_empty_name,
    is_valid_wbs,
    normalize_digits,
    propose_empty_name,
    proposed_set_value_fix,
)


TEST_META = {
    "id": "IDENTIFIERS",
    "title": "Identifier Name and WBS Check",
    "kind": "test",
    "profile_rule": "data_model",
    "snapshot_mode": "openpyxl",
}


def _fields_by_key(profile: dict) -> dict:
    fields = profile.get("data_model", {}).get("family_fields", [])
    return {str(x.get("key")): x for x in fields if x.get("key")}


def _column_for(profile: dict, sheet: str, field_key: str, field_def: dict) -> int | None:
    instance = profile.get("data_model", {}).get("instances", {}).get(sheet, {})
    mapped = instance.get("field_map", {}).get(field_key)
    if isinstance(mapped, dict) and mapped.get("column") is not None:
        return int(mapped["column"])

    default = field_def.get("default_locator", {})
    if default.get("kind") == "COLUMN" and default.get("column") is not None:
        return int(default["column"])

    return None


def _field_state(snapshot, sheet: str, row: int, col: int):
    address = f"{get_column_letter(col)}{row}"
    info = snapshot.merge_info(sheet, address)

    if not info["merged"]:
        return {
            "address": address,
            "candidate_anchor": True,
            "continuation": False,
            "covered_by_external_merge": False,
            "value": info["value"],
            "merge": None,
        }

    anchor_row = info["anchor_row"]
    anchor_col = info["anchor_col"]

    if anchor_col != col:
        return {
            "address": address,
            "candidate_anchor": False,
            "continuation": False,
            "covered_by_external_merge": True,
            "value": None,
            "merge": info["range"],
        }

    if anchor_row != row:
        return {
            "address": address,
            "candidate_anchor": False,
            "continuation": True,
            "covered_by_external_merge": False,
            "value": info["value"],
            "merge": info["range"],
        }

    return {
        "address": address,
        "candidate_anchor": True,
        "continuation": False,
        "covered_by_external_merge": False,
        "value": info["value"],
        "merge": info["range"],
    }


def _is_signal(state: dict) -> bool:
    if state["covered_by_external_merge"] or state["continuation"]:
        return False
    value = state["value"]
    return value is not None and str(value).strip() != ""


def run(snapshot, profile, log):
    data_model = profile.get("data_model", {})
    fields = _fields_by_key(profile)

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
    first_data_row = int(
        data_model.get("record_detection", {}).get("first_data_row", 3)
    )
    signal_keys = data_model.get("record_detection", {}).get(
        "signal_fields", ["document_type", "name", "wbs"]
    )

    wbs_pattern = str(
        wbs_def.get("validation", {}).get("pattern")
        or r"^\d+(?:\.\d+)*$"
    )
    wbs_cleaning = wbs_def.get("cleaning", {})
    name_cleaning = name_def.get("cleaning", {})

    findings = []

    log(
        "START",
        "IDENTIFIERS checks required Name and WBS fields using profile field mappings."
    )
    log(
        "INFO",
        f"WBS validation pattern: {wbs_pattern!r}; "
        f"invalid WBS suggestions use nearest valid WBS above + sequence from "
        f"{wbs_cleaning.get('sequence_start', 1000)}."
    )

    for sheet in target_sheets:
        if not snapshot.has_sheet(sheet):
            log("WARNING", f"{sheet}: sheet not found; identifier check skipped.")
            continue

        max_row, _ = snapshot.dimensions(sheet)

        mapped = {}
        for key, fdef in fields.items():
            col = _column_for(profile, sheet, key, fdef)
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

        log(
            "STAGE",
            f"{sheet}: scanning logical identifier anchors from row "
            f"{first_data_row} to {max_row}; "
            f"Name={get_column_letter(mapped['name'])}, "
            f"WBS={get_column_letter(mapped['wbs'])}."
        )

        wbs_state = WbsProposalState(
            sequence_start=int(wbs_cleaning.get("sequence_start", 1000)),
            separator=str(wbs_cleaning.get("separator", ".")),
            fallback_root_start=int(wbs_cleaning.get("fallback_root_start", 1000)),
        )

        scanned_records = 0
        name_errors = 0
        wbs_errors = 0

        for row in range(first_data_row, max_row + 1):
            states = {
                key: _field_state(snapshot, sheet, row, col)
                for key, col in mapped.items()
            }

            # Ignore continuation rows of vertical merges.
            if states["name"]["continuation"] or states["wbs"]["continuation"]:
                continue

            # Ignore separator/background rows where our identifier columns are
            # merely covered by a merge anchored somewhere else (e.g. A15:AA16).
            if (
                states["name"]["covered_by_external_merge"]
                and states["wbs"]["covered_by_external_merge"]
            ):
                continue

            # Until explicit data boundaries are added, require at least one
            # mapped signal field to carry its own value on this row.
            signal_present = False
            for key in signal_keys:
                state = states.get(key)
                if state and _is_signal(state):
                    signal_present = True
                    break

            if not signal_present:
                continue

            scanned_records += 1

            name_state = states["name"]
            wbs_state_cell = states["wbs"]

            # ---- Name
            if is_empty_name(name_state["value"]):
                name_errors += 1
                proposed = propose_empty_name(row, name_cleaning)
                reason = (
                    f"Required Name is empty at {sheet}!{name_state['address']}; "
                    f"proposed deterministic placeholder {proposed!r}."
                )
                fix = proposed_set_value_fix(
                    field_key="name",
                    sheet=sheet,
                    target=name_state["address"],
                    value=proposed,
                    reason=reason,
                    expected_old_value=name_state["value"],
                )
                log("FAIL", reason)
                findings.append(Finding(
                    test_id="IDENTIFIERS",
                    status="FAIL",
                    severity="HIGH",
                    sheet=sheet,
                    target=name_state["address"],
                    message=reason,
                    expected="Non-empty Name",
                    observed=name_state["value"],
                    evidence={
                        "field_key": "name",
                        "row": row,
                        "merge": name_state["merge"],
                    },
                    suggested_fix=fix,
                ))

            # ---- WBS
            raw_wbs = wbs_state_cell["value"]
            if is_valid_wbs(raw_wbs, wbs_pattern):
                wbs_state.observe_valid(raw_wbs)
            else:
                wbs_errors += 1
                proposed, parent = wbs_state.propose()
                normalized_raw = normalize_digits(raw_wbs)
                reason = (
                    f"Required WBS is empty/invalid at {sheet}!{wbs_state_cell['address']}; "
                    f"observed={normalized_raw!r}. Proposed WBS={proposed!r}"
                    + (
                        f" using nearest valid WBS above {parent!r}."
                        if parent is not None
                        else " using fallback root placeholder sequence."
                    )
                )
                fix = proposed_set_value_fix(
                    field_key="wbs",
                    sheet=sheet,
                    target=wbs_state_cell["address"],
                    value=proposed,
                    reason=reason,
                    expected_old_value=raw_wbs,
                )
                log("FAIL", reason)
                findings.append(Finding(
                    test_id="IDENTIFIERS",
                    status="FAIL",
                    severity="HIGH",
                    sheet=sheet,
                    target=wbs_state_cell["address"],
                    message=reason,
                    expected=f"WBS matching {wbs_pattern}",
                    observed=raw_wbs,
                    evidence={
                        "field_key": "wbs",
                        "row": row,
                        "merge": wbs_state_cell["merge"],
                        "nearest_valid_wbs_above": parent,
                        "proposed_wbs": proposed,
                    },
                    suggested_fix=fix,
                ))

        log(
            "SUMMARY",
            f"{sheet}: logical records checked={scanned_records}, "
            f"empty Name={name_errors}, invalid/empty WBS={wbs_errors}."
        )

        if name_errors == 0 and wbs_errors == 0:
            findings.append(Finding(
                test_id="IDENTIFIERS",
                status="PASS",
                severity="INFO",
                sheet=sheet,
                message=(
                    f"{sheet}: all detected identifier records have a non-empty Name "
                    "and a valid WBS."
                ),
                evidence={"logical_records_checked": scanned_records},
            ))

    log("DONE", f"IDENTIFIERS finished with {len(findings)} finding(s).")
    return findings
