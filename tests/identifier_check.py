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

    wbs_pattern = str(
        wbs_def.get("validation", {}).get("pattern")
        or r"^\d+(?:\.\d+)*$"
    )
    wbs_cleaning = wbs_def.get("cleaning", {})
    name_cleaning = name_def.get("cleaning", {})

    findings = []

    log(
        "START",
        "IDENTIFIERS checks required Name and WBS fields on derived DocumentRegion anchors."
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
        log(
            "STAGE",
            f"{sheet}: checking {len(boundary_scan.regions)} derived document "
            f"region(s) from row {boundary_cfg['first_data_row']}; "
            f"Name={get_column_letter(mapped['name'])}, "
            f"WBS={get_column_letter(mapped['wbs'])}."
        )

        if boundary_scan.ambiguities:
            log(
                "WARNING",
                f"{sheet}: boundary detector still reports "
                f"{len(boundary_scan.ambiguities)} ambiguity/ambiguities. "
                "The pipeline should normally review DOCUMENT_BOUNDARIES before IDENTIFIERS."
            )

        wbs_state = WbsProposalState(
            sequence_start=int(wbs_cleaning.get("sequence_start", 1000)),
            separator=str(wbs_cleaning.get("separator", ".")),
            fallback_root_start=int(wbs_cleaning.get("fallback_root_start", 1000)),
        )

        scanned_records = 0
        name_errors = 0
        wbs_errors = 0

        for region in boundary_scan.regions:
            scanned_records += 1
            row = region.anchor_row
            name_state = region.field("name")
            wbs_state_cell = region.field("wbs")

            if name_state is None or wbs_state_cell is None:
                # Mapping completeness is checked above; this is only a guard
                # against a malformed detector result.
                continue

            # ---- Name
            if is_empty_name(name_state.value):
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

            # ---- WBS
            raw_wbs = wbs_state_cell.value
            if is_valid_wbs(raw_wbs, wbs_pattern):
                wbs_state.observe_valid(raw_wbs)
            else:
                wbs_errors += 1
                proposed, parent = wbs_state.propose()
                normalized_raw = normalize_digits(raw_wbs)
                reason = (
                    f"Required WBS is empty/invalid at {sheet}!{wbs_state_cell.address}; "
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
                    target=wbs_state_cell.address,
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
                    target=wbs_state_cell.address,
                    message=reason,
                    expected=f"WBS matching {wbs_pattern}",
                    observed=raw_wbs,
                    evidence={
                        "field_key": "wbs",
                        "row": row,
                        "document_region": region.target,
                        "merge": wbs_state_cell.merge,
                        "nearest_valid_wbs_above": parent,
                        "proposed_wbs": proposed,
                    },
                    suggested_fix=fix,
                ))

        log(
            "SUMMARY",
            f"{sheet}: document regions checked={scanned_records}, "
            f"empty Name={name_errors}, invalid/empty WBS={wbs_errors}."
        )

        if name_errors == 0 and wbs_errors == 0:
            findings.append(Finding(
                test_id="IDENTIFIERS",
                status="PASS",
                severity="INFO",
                sheet=sheet,
                message=(
                    f"{sheet}: all derived document regions have a non-empty Name "
                    "and a valid WBS."
                ),
                evidence={"document_regions_checked": scanned_records},
            ))

    log("DONE", f"IDENTIFIERS finished with {len(findings)} finding(s).")
    return findings
