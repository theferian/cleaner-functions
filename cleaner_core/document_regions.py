from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

from openpyxl.utils import get_column_letter

from .ranges import parse_range


@dataclass(frozen=True)
class FieldAnchor:
    field_key: str
    column: int
    address: str
    value: Any
    own_anchor: bool
    continuation: bool
    covered_by_external_merge: bool
    merge: str | None = None
    span_start_row: int | None = None
    span_end_row: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DocumentRegion:
    sheet: str
    record_index: int
    anchor_row: int
    start_row: int
    end_row: int
    fields: dict[str, FieldAnchor]
    signal_fields: tuple[str, ...] = ()
    boundary_fields: tuple[str, ...] = ()
    source: str = "MAPPED_FIELD_ANCHORS"

    @property
    def row_count(self) -> int:
        return self.end_row - self.start_row + 1

    @property
    def target(self) -> str:
        return (
            str(self.start_row)
            if self.start_row == self.end_row
            else f"{self.start_row}:{self.end_row}"
        )

    def field(self, key: str) -> FieldAnchor | None:
        return self.fields.get(key)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["row_count"] = self.row_count
        payload["target"] = self.target
        return payload


@dataclass
class BoundaryScan:
    sheet: str
    regions: list[DocumentRegion] = field(default_factory=list)
    excluded_separator_ranges: list[str] = field(default_factory=list)
    ambiguities: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sheet": self.sheet,
            "regions": [region.to_dict() for region in self.regions],
            "excluded_separator_ranges": list(self.excluded_separator_ranges),
            "ambiguities": list(self.ambiguities),
            "summary": {
                "region_count": len(self.regions),
                "separator_count": len(self.excluded_separator_ranges),
                "ambiguity_count": len(self.ambiguities),
            },
        }


def fields_by_key(profile: dict) -> dict[str, dict]:
    return {
        str(item.get("key")): item
        for item in profile.get("data_model", {}).get("family_fields", [])
        if item.get("key")
    }


def column_for(
    profile: dict,
    sheet: str,
    field_key: str,
    field_def: dict,
) -> int | None:
    instance = profile.get("data_model", {}).get("instances", {}).get(sheet, {})
    mapped = instance.get("field_map", {}).get(field_key)
    if isinstance(mapped, dict) and mapped.get("column") is not None:
        return int(mapped["column"])

    default = field_def.get("default_locator", {})
    if default.get("kind") == "COLUMN" and default.get("column") is not None:
        return int(default["column"])

    return None


def field_anchor(snapshot, sheet: str, row: int, field_key: str, col: int) -> FieldAnchor:
    address = f"{get_column_letter(col)}{row}"
    info = snapshot.merge_info(sheet, address)

    if not info["merged"]:
        return FieldAnchor(
            field_key=field_key,
            column=col,
            address=address,
            value=info["value"],
            own_anchor=True,
            continuation=False,
            covered_by_external_merge=False,
            span_start_row=row,
            span_end_row=row,
        )

    rect = parse_range(str(info["range"]))
    anchor_row = int(info["anchor_row"])
    anchor_col = int(info["anchor_col"])

    if anchor_col != col:
        return FieldAnchor(
            field_key=field_key,
            column=col,
            address=address,
            value=None,
            own_anchor=False,
            continuation=False,
            covered_by_external_merge=True,
            merge=rect.address,
            span_start_row=rect.r1,
            span_end_row=rect.r2,
        )

    if anchor_row != row:
        return FieldAnchor(
            field_key=field_key,
            column=col,
            address=address,
            value=info["value"],
            own_anchor=False,
            continuation=True,
            covered_by_external_merge=False,
            merge=rect.address,
            span_start_row=rect.r1,
            span_end_row=rect.r2,
        )

    return FieldAnchor(
        field_key=field_key,
        column=col,
        address=address,
        value=info["value"],
        own_anchor=True,
        continuation=False,
        covered_by_external_merge=False,
        merge=rect.address,
        span_start_row=rect.r1,
        span_end_row=rect.r2,
    )


def _has_value(anchor: FieldAnchor | None) -> bool:
    if anchor is None or not anchor.own_anchor:
        return False
    value = anchor.value
    return value is not None and str(value).strip() != ""


def boundary_config(profile: dict) -> dict[str, Any]:
    data_model = profile.get("data_model", {})
    legacy = data_model.get("record_detection", {})
    configured = data_model.get("document_boundaries", {})

    return {
        "enabled": configured.get("enabled", True),
        "method": configured.get("method", "IDENTIFIER_FIELD_MERGE_SPAN"),
        "first_data_row": int(
            configured.get("first_data_row", legacy.get("first_data_row", 3))
        ),
        "signal_fields": list(
            configured.get(
                "signal_fields",
                legacy.get("signal_fields", ["document_type", "name", "wbs"]),
            )
        ),
        "boundary_fields": list(
            configured.get("boundary_fields", ["name", "wbs"])
        ),
        "separator_fields": list(
            configured.get("separator_fields", ["name", "wbs"])
        ),
    }


def scan_document_regions(snapshot, profile: dict, sheet: str) -> BoundaryScan:
    scan = BoundaryScan(sheet=sheet)
    if not snapshot.has_sheet(sheet):
        scan.ambiguities.append({
            "kind": "SHEET_NOT_FOUND",
            "row": None,
            "message": f"{sheet}: sheet not found.",
        })
        return scan

    config = boundary_config(profile)
    fields = fields_by_key(profile)
    mapped: dict[str, int] = {}
    for key, field_def in fields.items():
        col = column_for(profile, sheet, key, field_def)
        if col is not None:
            mapped[key] = col

    boundary_fields = [key for key in config["boundary_fields"] if key in mapped]
    signal_fields = [key for key in config["signal_fields"] if key in mapped]
    separator_fields = [key for key in config["separator_fields"] if key in mapped]

    if not boundary_fields:
        scan.ambiguities.append({
            "kind": "PROFILE_MAPPING",
            "row": None,
            "message": f"{sheet}: no mapped boundary fields are available.",
            "configured_boundary_fields": config["boundary_fields"],
            "mapped_fields": mapped,
        })
        return scan

    max_row, _ = snapshot.dimensions(sheet)
    first_row = config["first_data_row"]
    separator_ranges: set[str] = set()
    candidates: list[dict[str, Any]] = []

    for row in range(first_row, max_row + 1):
        anchors = {
            key: field_anchor(snapshot, sheet, row, key, col)
            for key, col in mapped.items()
        }

        # A row that is merely the second/later row of a Name/WBS vertical
        # merge belongs to the region anchored above; it is not a new record.
        if any(
            anchors[key].continuation
            for key in boundary_fields
            if key in anchors
        ):
            continue

        external_separator = [
            anchors[key]
            for key in separator_fields
            if key in anchors and anchors[key].covered_by_external_merge
        ]
        if separator_fields and len(external_separator) == len(separator_fields):
            for anchor in external_separator:
                if anchor.merge:
                    separator_ranges.add(anchor.merge)
            continue

        active_signals = [
            key for key in signal_fields
            if key in anchors and _has_value(anchors[key])
        ]
        if not active_signals:
            continue

        own_boundary_anchors = [
            anchors[key]
            for key in boundary_fields
            if key in anchors and anchors[key].own_anchor
        ]

        if own_boundary_anchors:
            end_row = max(
                int(anchor.span_end_row or row)
                for anchor in own_boundary_anchors
            )
        else:
            end_row = row

        ambiguous_reasons: list[dict[str, Any]] = []
        externally_covered = [
            key for key in boundary_fields
            if key in anchors and anchors[key].covered_by_external_merge
        ]
        if externally_covered:
            ambiguous_reasons.append({
                "kind": "EXTERNAL_IDENTIFIER_MERGE",
                "fields": externally_covered,
                "message": (
                    "One or more boundary fields are covered by a merge anchored "
                    "outside their mapped column while another signal marks this row "
                    "as a possible document."
                ),
            })

        if not own_boundary_anchors:
            ambiguous_reasons.append({
                "kind": "NO_BOUNDARY_ANCHOR",
                "fields": boundary_fields,
                "message": (
                    "A signal field marks this row as a possible document, but none "
                    "of the configured boundary fields owns a cell/merge anchor here."
                ),
            })

        candidates.append({
            "row": row,
            "end_row": end_row,
            "anchors": anchors,
            "active_signals": active_signals,
            "ambiguities": ambiguous_reasons,
        })

    # Protect against malformed/overlapping boundary merges. A genuine region
    # may not consume the next detected document anchor.
    for index, candidate in enumerate(candidates):
        row = int(candidate["row"])
        end_row = int(candidate["end_row"])
        next_row = (
            int(candidates[index + 1]["row"])
            if index + 1 < len(candidates)
            else None
        )
        if next_row is not None and end_row >= next_row:
            candidate["ambiguities"].append({
                "kind": "OVERLAPPING_REGION",
                "next_anchor_row": next_row,
                "original_end_row": end_row,
                "message": (
                    f"Detected boundary span reaches row {end_row}, but another "
                    f"document anchor begins at row {next_row}."
                ),
            })
            candidate["end_row"] = next_row - 1

        region = DocumentRegion(
            sheet=sheet,
            record_index=index + 1,
            anchor_row=row,
            start_row=row,
            end_row=max(row, int(candidate["end_row"])),
            fields=candidate["anchors"],
            signal_fields=tuple(candidate["active_signals"]),
            boundary_fields=tuple(boundary_fields),
        )
        scan.regions.append(region)

        if candidate["ambiguities"]:
            scan.ambiguities.append({
                "kind": "AMBIGUOUS_DOCUMENT_REGION",
                "row": row,
                "target": region.target,
                "region": region.to_dict(),
                "reasons": candidate["ambiguities"],
                "message": (
                    f"{sheet}: document boundary at row {row} requires review."
                ),
            })

    scan.excluded_separator_ranges = sorted(separator_ranges)
    return scan


def scan_all_document_regions(snapshot, profile: dict) -> dict[str, BoundaryScan]:
    target_sheets = (
        profile.get("structure", {}).get("m_line", {}).get("target_sheets")
        or snapshot.sheet_names()
    )
    return {
        sheet: scan_document_regions(snapshot, profile, sheet)
        for sheet in target_sheets
    }
