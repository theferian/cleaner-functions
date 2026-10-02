from __future__ import annotations

from cleaner_core.contracts import DiscoveryCandidate
from cleaner_core.ranges import intersects_window, col_letter


DISCOVERY_META = {
    "id": "DISCOVER_M_LINE",
    "title": "M-Line Profile Discovery",
    "kind": "profile_discovery",
}


def run(snapshot, profile, log):
    cfg = profile.get("structure", {}).get("m_line", {})
    target_sheets = cfg.get("target_sheets") or snapshot.sheet_names()
    window = cfg.get("discovery", {}).get("title_window", {})

    r1 = int(window.get("row_start", 1))
    r2 = int(window.get("row_end", 10))
    c1 = int(window.get("col_start", 1))
    c2 = int(window.get("col_end", 6))

    candidates = []
    log("START", f"DISCOVER_M_LINE scanning title window R{r1}:R{r2}, C{c1}:C{c2}.")

    for sheet in target_sheets:
        if not snapshot.has_sheet(sheet):
            log("WARNING", f"{sheet}: sheet not present in snapshot.")
            continue

        log("STAGE", f"{sheet}: inspecting merged ranges in the configured title window.")

        sheet_candidates = []
        for rect in snapshot.merged_ranges(sheet):
            if rect.col_span < 2:
                continue
            if not intersects_window(rect, r1, r2, c1, c2):
                continue

            value = snapshot.anchor_value(sheet, rect)
            if value in (None, ""):
                continue

            boundary_after = rect.c2
            item = DiscoveryCandidate(
                discovery_id="DISCOVER_M_LINE",
                sheet=sheet,
                target=rect.address,
                message=(
                    f"{sheet}: merged title candidate {rect.address} ends at "
                    f"{col_letter(boundary_after)}, implying {col_letter(boundary_after)}|{col_letter(boundary_after + 1)}."
                ),
                evidence={
                    "value": str(value),
                    "merge": rect.address,
                    "boundary_after_col": boundary_after,
                    "boundary_label": f"{col_letter(boundary_after)}|{col_letter(boundary_after + 1)}",
                },
                suggested_profile_patch={
                    "path": "structure.m_line.boundary_after_col",
                    "value": boundary_after,
                    "sheet": sheet,
                },
            )
            sheet_candidates.append(item)
            candidates.append(item)
            log("DISCOVERY", item.message + f" Value={str(value)[:100]!r}")

        if not sheet_candidates:
            log("INFO", f"{sheet}: no merged title candidate found in the discovery window.")

    log("DONE", f"DISCOVER_M_LINE produced {len(candidates)} candidate(s).")
    return candidates
