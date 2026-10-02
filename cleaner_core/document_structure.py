from __future__ import annotations

from dataclasses import dataclass, field, asdict
import hashlib
import json
from typing import Any

from .document_regions import DocumentRegion, scan_document_regions
from .ranges import Rect


@dataclass(frozen=True)
class StructurePattern:
    pattern_id: str
    row_count: int
    transaction_start_col: int
    merges: tuple[tuple[int, int, int, int], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "pattern_id": self.pattern_id,
            "row_count": self.row_count,
            "transaction_start_col": self.transaction_start_col,
            "merges": [list(x) for x in self.merges],
        }


@dataclass(frozen=True)
class RegionStructure:
    sheet: str
    target: str
    anchor_row: int
    start_row: int
    end_row: int
    pattern: StructurePattern
    boundary_crossing_merges: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "sheet": self.sheet,
            "target": self.target,
            "anchor_row": self.anchor_row,
            "start_row": self.start_row,
            "end_row": self.end_row,
            "pattern": self.pattern.to_dict(),
            "boundary_crossing_merges": list(self.boundary_crossing_merges),
        }


@dataclass
class StructureScan:
    sheet: str
    regions: list[RegionStructure] = field(default_factory=list)
    patterns: dict[str, dict[str, Any]] = field(default_factory=dict)
    hazards: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sheet": self.sheet,
            "regions": [x.to_dict() for x in self.regions],
            "patterns": self.patterns,
            "hazards": list(self.hazards),
            "summary": {
                "region_count": len(self.regions),
                "pattern_count": len(self.patterns),
                "hazard_count": len(self.hazards),
            },
        }


def document_structure_config(profile: dict) -> dict[str, Any]:
    data_model = profile.get("data_model", {})
    configured = data_model.get("document_structure", {})
    boundary_after_col = int(
        profile.get("structure", {}).get("m_line", {}).get("boundary_after_col", 3)
    )
    return {
        "enabled": configured.get("enabled", True),
        "method": configured.get("method", "NORMALIZED_MERGE_SIGNATURE"),
        "transaction_start_col": int(
            configured.get("transaction_start_col", boundary_after_col + 1)
        ),
        "known_patterns": list(configured.get("known_patterns", [])),
        "unknown_pattern_status": str(
            configured.get("unknown_pattern_status", "POSSIBLE_EXCEPTION")
        ).upper(),
        "crossing_hazard_policy": str(
            configured.get(
                "crossing_hazard_policy",
                "OWNED_BOUNDARY_FIELDS_ONLY",
            )
        ).upper(),
    }


def _intersects_rows(rect: Rect, start_row: int, end_row: int) -> bool:
    return not (rect.r2 < start_row or rect.r1 > end_row)


def _pattern_id(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    return f"STRUCT_{digest}"


def _boundary_columns(region: DocumentRegion) -> set[int]:
    """Return mapped columns that actually define this DocumentRegion boundary."""
    return {
        int(region.fields[key].column)
        for key in region.boundary_fields
        if key in region.fields
    }


def _is_owned_boundary_crossing(
    rect: Rect,
    region: DocumentRegion,
    *,
    policy: str,
) -> bool:
    """Classify whether a row-crossing merge is a document-structure hazard.

    DocumentRegion boundaries are defined by the configured boundary fields
    (for AZD, Name/WBS). Long merges in contextual columns such as Document Type
    or in the transaction area may legitimately span several documents. They are
    therefore not hazards merely because their row span overlaps this region.

    A merge is owned by this region when its top-left anchor row starts inside
    the region. Under the default policy, only an owned crossing merge that also
    covers a boundary-field column is treated as a structural hazard.
    """
    policy = str(policy or "OWNED_BOUNDARY_FIELDS_ONLY").upper()
    if policy in {"NONE", "DISABLED"}:
        return False
    if policy == "ALL_CROSSING_MERGES":
        return True
    if policy != "OWNED_BOUNDARY_FIELDS_ONLY":
        raise ValueError(f"Unknown document-structure crossing hazard policy: {policy}")

    if not (region.start_row <= rect.r1 <= region.end_row):
        return False

    boundary_cols = _boundary_columns(region)
    return any(rect.c1 <= col <= rect.c2 for col in boundary_cols)


def structure_pattern_for_region(
    *,
    region: DocumentRegion,
    merged_ranges: list[Rect],
    transaction_start_col: int,
    crossing_hazard_policy: str = "OWNED_BOUNDARY_FIELDS_ONLY",
) -> tuple[StructurePattern, tuple[str, ...]]:
    """
    Build a row-position-independent geometry signature for one document region.

    Merge rows are stored relative to the region start, so the same physical card
    layout produces the same signature even when it moves up/down next week.
    Values are intentionally excluded from the fingerprint.
    """
    normalized: list[tuple[int, int, int, int]] = []
    crossing: list[str] = []

    for rect in merged_ranges:
        if not _intersects_rows(rect, region.start_row, region.end_row):
            continue

        if rect.r1 < region.start_row or rect.r2 > region.end_row:
            if _is_owned_boundary_crossing(
                rect,
                region,
                policy=crossing_hazard_policy,
            ):
                crossing.append(rect.address)
            continue

        normalized.append((
            rect.r1 - region.start_row,
            rect.r2 - region.start_row,
            rect.c1,
            rect.c2,
        ))

    normalized.sort()
    payload = {
        "row_count": region.row_count,
        "transaction_start_col": int(transaction_start_col),
        "merges": [list(x) for x in normalized],
    }
    pattern = StructurePattern(
        pattern_id=_pattern_id(payload),
        row_count=region.row_count,
        transaction_start_col=int(transaction_start_col),
        merges=tuple(normalized),
    )
    return pattern, tuple(sorted(set(crossing)))


def _known_pattern_ids(profile: dict, sheet: str) -> set[str]:
    known: set[str] = set()
    for item in document_structure_config(profile)["known_patterns"]:
        if not item.get("enabled", True):
            continue
        scope = str(item.get("sheet") or "*")
        if scope not in {"*", sheet}:
            continue
        pid = str(item.get("pattern_id") or "")
        if pid:
            known.add(pid)
    return known


def scan_document_structure(snapshot, profile: dict, sheet: str) -> StructureScan:
    config = document_structure_config(profile)
    scan = StructureScan(sheet=sheet)
    if not snapshot.has_sheet(sheet):
        scan.hazards.append({
            "kind": "SHEET_NOT_FOUND",
            "message": f"{sheet}: sheet not found.",
        })
        return scan

    boundary_scan = scan_document_regions(snapshot, profile, sheet)

    merged_ranges = snapshot.merged_ranges(sheet)
    known_ids = _known_pattern_ids(profile, sheet)

    for region in boundary_scan.regions:
        pattern, crossing = structure_pattern_for_region(
            region=region,
            merged_ranges=merged_ranges,
            transaction_start_col=config["transaction_start_col"],
            crossing_hazard_policy=config["crossing_hazard_policy"],
        )
        item = RegionStructure(
            sheet=sheet,
            target=region.target,
            anchor_row=region.anchor_row,
            start_row=region.start_row,
            end_row=region.end_row,
            pattern=pattern,
            boundary_crossing_merges=crossing,
        )
        scan.regions.append(item)

        bucket = scan.patterns.setdefault(pattern.pattern_id, {
            "pattern": pattern.to_dict(),
            "count": 0,
            "known": pattern.pattern_id in known_ids,
            "targets": [],
        })
        bucket["count"] += 1
        bucket["targets"].append(region.target)

        if crossing:
            scan.hazards.append({
                "kind": "MERGE_CROSSES_DOCUMENT_BOUNDARY",
                "target": region.target,
                "pattern_id": pattern.pattern_id,
                "ranges": list(crossing),
                "message": (
                    f"{sheet}!{region.target}: one or more merged ranges cross the "
                    "derived document boundary."
                ),
            })

    return scan


def scan_all_document_structures(snapshot, profile: dict) -> dict[str, StructureScan]:
    target_sheets = (
        profile.get("structure", {}).get("m_line", {}).get("target_sheets")
        or snapshot.sheet_names()
    )
    return {
        sheet: scan_document_structure(snapshot, profile, sheet)
        for sheet in target_sheets
    }
