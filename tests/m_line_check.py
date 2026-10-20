from __future__ import annotations

import re

from cleaner_core.contracts import Finding
from cleaner_core.ranges import (
    crosses_vertical_boundary,
    contiguous_groups,
    col_letter,
)


TEST_META = {
    "id": "M_LINE",
    "title": "Middle Line Check",
    "kind": "test",
    "profile_rule": "structure.m_line",
    "snapshot_mode": "openpyxl",
}


def _family_horizontal_separator(snapshot, profile: dict, sheet: str, rect, cfg: dict) -> dict | None:
    """Recognize a document-group divider, never a normal cross-boundary merge.

    Safely recognize the GENERAL_DOCUMENT family convention: an entire-sheet-
    width, two-row merge anchored in column A. It is a horizontal separator,
    not a correspondence/document cell. Long narrative/date-bearing text is
    deliberately left for human review.
    """
    if str(profile.get("family") or "").upper() != "GENERAL_DOCUMENT":
        return None

    rule = cfg.get("family_horizontal_separators") or {}
    if not rule.get("enabled", True):
        return None

    max_row, max_col = snapshot.dimensions(sheet)
    first_data_row = int(profile.get("data_model", {}).get("document_boundaries", {}).get("first_data_row", 3))
    if not (
        rect.c1 == 1
        and rect.c2 == max_col
        and rect.row_span == 2
        and rect.col_span >= 8
        and first_data_row <= rect.r1
        and rect.r2 <= max_row
    ):
        return None

    anchor = snapshot.anchor_value(sheet, rect)
    label = "" if anchor is None else str(anchor).strip()
    if (
        len(label) > 80
        or "\n" in label
        or re.search(r"\d{2,4}[/\-]\d{1,2}[/\-]\d{1,4}", label)
        or (anchor is not None and not isinstance(anchor, str))
    ):
        return None

    return {
        "rule": "GENERAL_DOCUMENT_FULL_WIDTH_TWO_ROW_SEPARATOR",
        "anchor_label": label or None,
        "rows": list(rect.rows()),
        "full_width_columns": max_col,
        "recognition": "GEOMETRY_AND_NON_TRANSACTION_ANCHOR",
    }


def _exception_rows(profile: dict, sheet: str) -> tuple[set[int], list[dict]]:
    rows = set()
    rules = []

    for exc in profile.get("known_exceptions", []):
        if not exc.get("enabled", True):
            continue
        match = exc.get("match", {})
        if str(match.get("test_id", "")).upper() != "M_LINE":
            continue

        match_sheet = match.get("sheet", "*")
        if match_sheet not in ("*", "", None, sheet):
            continue

        these = {int(x) for x in match.get("rows", [])}
        if these:
            rows.update(these)
            rules.append(exc)

    return rows, rules


def _window_signature(crossings, start: int, end: int, boundary: int):
    sig = []
    for rect in crossings:
        if start <= rect.r1 and rect.r2 <= end:
            sig.append((
                rect.r1 - start,
                rect.r2 - start,
                rect.c1 - boundary,
                rect.c2 - boundary,
            ))
    return tuple(sorted(sig))


def _learn_templates(crossings, known_rows: set[int], boundary: int, log):
    templates = []
    for start, end in contiguous_groups(known_rows):
        sig = _window_signature(crossings, start, end, boundary)
        if not sig:
            log("WARNING", f"Known exception rows {start}-{end}: no crossing geometry exists in this sheet.")
            continue
        templates.append({
            "start": start,
            "end": end,
            "height": end - start + 1,
            "signature": sig,
        })
        log("INFO", f"Learned known-exception signature from rows {start}-{end}: {sig}")
    return templates


def _candidate_groups(crossings, templates, known_rows: set[int], boundary: int):
    results = []
    seen = set()

    crossing_rows = sorted({
        row
        for rect in crossings
        for row in range(rect.r1, rect.r2 + 1)
    })

    for template in templates:
        height = template["height"]
        for row in crossing_rows:
            for offset in range(height):
                start = row - offset
                if start < 1:
                    continue
                end = start + height - 1

                if set(range(start, end + 1)).issubset(known_rows):
                    continue

                sig = _window_signature(crossings, start, end, boundary)
                if sig != template["signature"] or not sig:
                    continue

                key = (start, end, sig)
                if key in seen:
                    continue
                seen.add(key)

                results.append({
                    "start": start,
                    "end": end,
                    "signature": sig,
                    "template": template,
                })

    return results


def run(snapshot, profile, log):
    cfg = profile.get("structure", {}).get("m_line", {})
    project_id = str(profile.get("profile_name") or "PROJECT").strip().upper()

    if not cfg.get("enabled", True):
        log("SKIP", "M_LINE is disabled in the profile.")
        return []

    boundary = cfg.get("boundary_after_col")
    if boundary is None:
        msg = "Profile has no structure.m_line.boundary_after_col. Run profile discovery first."
        log("PROFILE_MISMATCH", msg)
        return [Finding(
            test_id="M_LINE",
            status="PROFILE_MISMATCH",
            severity="CRITICAL",
            message=msg,
        )]

    boundary = int(boundary)
    left = col_letter(boundary)
    right = col_letter(boundary + 1)

    target_sheets = cfg.get("target_sheets") or snapshot.sheet_names()
    findings = []

    log("START", f"M_LINE using stored profile boundary {left}|{right}. No title discovery is performed.")

    for sheet in target_sheets:
        if not snapshot.has_sheet(sheet):
            msg = f"{sheet}: expected target sheet is not present."
            log("FAIL", msg)
            findings.append(Finding(
                test_id="M_LINE",
                status="FAIL",
                severity="HIGH",
                sheet=sheet,
                message=msg,
                expected="Target sheet present",
                observed="Missing sheet",
            ))
            continue

        log("STAGE", f"{sheet}: reading merged-range geometry from snapshot.")

        all_merges = snapshot.merged_ranges(sheet)
        crossings = sorted(
            [x for x in all_merges if crosses_vertical_boundary(x, boundary)],
            key=lambda x: (x.r1, x.r2, x.c1, x.c2),
        )

        log(
            "INFO",
            f"{sheet}: {len(all_merges)} total merged range(s); "
            f"{len(crossings)} cross {left}|{right}."
        )

        known_rows, exception_rules = _exception_rows(profile, sheet)
        if known_rows:
            log("INFO", f"{sheet}: known exception groups = {contiguous_groups(known_rows)}")

        templates = _learn_templates(crossings, known_rows, boundary, log)
        candidates = (
            _candidate_groups(crossings, templates, known_rows, boundary)
            if cfg.get("candidate_exception_detection", {}).get("enabled", True)
            else []
        )

        for candidate in candidates:
            log(
                "DISCOVERY",
                f"{sheet}: rows {candidate['start']}-{candidate['end']} "
                "match a known exception geometry signature."
            )

        known_count = possible_count = fail_count = 0

        for rect in crossings:
            rect_rows = set(rect.rows())

            separator = _family_horizontal_separator(snapshot, profile, sheet, rect, cfg)
            if separator is not None:
                known_count += 1
                msg = f"GENERAL_DOCUMENT horizontal section separator: {sheet}!{rect.address}."
                log("FAMILY_SEPARATOR", msg)
                findings.append(Finding(
                    test_id="M_LINE",
                    status="PASS",  # Audited but requires no repeat review.
                    severity="INFO",
                    sheet=sheet,
                    target=rect.address,
                    message=msg,
                    expected="Full-width two-row non-transaction divider",
                    observed=rect.address,
                    evidence=separator,
                ))
                continue

            if rect_rows and rect_rows.issubset(known_rows):
                known_count += 1
                rule_ids = [
                    rule.get("id")
                    for rule in exception_rules
                    if rect_rows.intersection(
                        {int(v) for v in rule.get("match", {}).get("rows", [])}
                    )
                ]

                msg = f"Known {project_id} M-line exception: {sheet}!{rect.address}."
                log("KNOWN_EXCEPTION", msg)
                findings.append(Finding(
                    test_id="M_LINE",
                    status="KNOWN_EXCEPTION",
                    severity="INFO",
                    sheet=sheet,
                    target=rect.address,
                    message=msg,
                    expected=f"No ordinary merge crosses {left}|{right}",
                    observed=rect.address,
                    evidence={
                        "boundary_after_col": boundary,
                        "rows": sorted(rect_rows),
                        "exception_rule_ids": rule_ids,
                    },
                ))
                continue

            matched_candidate = None
            for candidate in candidates:
                if rect_rows.issubset(set(range(candidate["start"], candidate["end"] + 1))):
                    matched_candidate = candidate
                    break

            if matched_candidate:
                possible_count += 1
                start = matched_candidate["start"]
                end = matched_candidate["end"]
                msg = (
                    f"Possible repeated {project_id} exception: {sheet}!{rect.address}; "
                    f"rows {start}-{end} match known exception geometry."
                )
                log("POSSIBLE_EXCEPTION", msg)
                findings.append(Finding(
                    test_id="M_LINE",
                    status="POSSIBLE_EXCEPTION",
                    severity="WARNING",
                    sheet=sheet,
                    target=rect.address,
                    message=msg,
                    expected=f"No ordinary merge crosses {left}|{right}",
                    observed=rect.address,
                    evidence={
                        "boundary_after_col": boundary,
                        "candidate_rows": list(range(start, end + 1)),
                        "signature": matched_candidate["signature"],
                        "learned_from_rows": [
                            matched_candidate["template"]["start"],
                            matched_candidate["template"]["end"],
                        ],
                    },
                    suggested_exception={
                        "id": f"{project_id}_MLINE_EXCEPTION_{sheet.replace(' ', '_')}_R{start}_{end}",
                        "enabled": True,
                        "reason": (
                            "Candidate repeated Category/Type boundary exception "
                            "discovered from matching known M-line geometry; requires human confirmation."
                        ),
                        "match": {
                            "test_id": "M_LINE",
                            "sheet": sheet,
                            "rows": list(range(start, end + 1)),
                        },
                    },
                ))
                continue

            fail_count += 1
            msg = f"Unexpected M-line crossing: {sheet}!{rect.address}."
            log("FAIL", msg)
            findings.append(Finding(
                test_id="M_LINE",
                status="FAIL",
                severity="HIGH",
                sheet=sheet,
                target=rect.address,
                message=msg,
                expected=f"No ordinary merge crosses {left}|{right}",
                observed=rect.address,
                evidence={
                    "boundary_after_col": boundary,
                    "rows": sorted(rect_rows),
                    "known_exception_rows": sorted(known_rows),
                },
            ))

        if not crossings:
            msg = f"{sheet}: no merge crosses stored M-line {left}|{right}."
            log("PASS", msg)
            findings.append(Finding(
                test_id="M_LINE",
                status="PASS",
                severity="INFO",
                sheet=sheet,
                message=msg,
                expected=f"No ordinary merge crosses {left}|{right}",
                observed="0 crossings",
                evidence={"boundary_after_col": boundary},
            ))

        log(
            "SUMMARY",
            f"{sheet}: known={known_count}, possible={possible_count}, unexpected={fail_count}."
        )

    log("DONE", f"M_LINE finished with {len(findings)} finding(s).")
    return findings
