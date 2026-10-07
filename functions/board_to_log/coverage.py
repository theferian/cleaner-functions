from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from functions.cleaner.service import CleanerRun

from .contracts import BoardToLogResult


@dataclass(frozen=True)
class CoverageItem:
    sheet: str
    address: str
    classification: str
    value: Any = None
    document_index: int | None = None
    source_kind: str | None = None
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


CLASSIFICATION_MEANINGS = {
    "CAPTURED_TRANSACTION": "Transaction value emitted into the canonical Logbook.",
    "CAPTURED_NARRATIVE": "Narrative receive value emitted losslessly into the canonical Logbook.",
    "CAPTURED_IDENTITY": "Document identity field used by the canonical Logbook.",
    "UNRESOLVED_ISSUE": "Board-to-Log identified unresolved transaction content at this source slot.",
    "SCANNED_NOT_RETRIEVED": "Non-empty mapped board slot was scanned but did not feed a canonical Logbook field.",
}


def _effective_value(state: dict[str, Any], sheet: str, address: str, fallback: Any) -> Any:
    key = f"{sheet}!{address}".upper()
    override = (state.get("value_overrides") or {}).get(key)
    return fallback if override is None else override.get("value")


def _nonempty(value: Any) -> bool:
    return value is not None and str(value).strip() != ""


def build_coverage_audit(run: CleanerRun, result: BoardToLogResult) -> dict[str, Any]:
    """Compare mapped Cleaner source slots with Board-to-Log consumption.

    This is deliberately artifact-driven.  It does not rescan Excel geometry;
    the purpose is to answer a QA question: of the non-empty slots Cleaner
    already mapped, which ones actually reached the canonical Logbook?
    """
    state = run.state()
    cards = run.card_maps()
    regions = run.document_regions()

    transaction_sources: dict[tuple[str, str], list[str]] = defaultdict(list)
    narrative_sources: set[tuple[str, str]] = {
        (str(item.get("sheet")), str(item.get("address")))
        for item in (result.diagnostics.get("preserved_narrative_sources") or [])
        if item.get("sheet") and item.get("address")
    }
    for record in result.records:
        mode = str((record.raw or {}).get("mode") or "")
        for kind, address in (
            ("date", record.date_source),
            ("reference", record.reference_source),
            ("status", record.status_source),
        ):
            if not address:
                continue
            key = (record.source_sheet, str(address))
            transaction_sources[key].append(kind)
            if mode.startswith("narrative_receive") and kind in {"date", "reference"}:
                narrative_sources.add(key)

    issue_sources: dict[tuple[str, str], list[str]] = defaultdict(list)
    for issue in result.issues:
        if issue.address:
            issue_sources[(issue.sheet, str(issue.address))].append(issue.kind)

    identity_sources: dict[tuple[str, str], tuple[int, Any, str]] = {}
    for sheet, payload in (regions.get("sheets") or {}).items():
        for region in payload.get("regions", []):
            doc_index = int(region.get("record_index"))
            for field_key, field in (region.get("fields") or {}).items():
                address = str(field.get("address") or "")
                if not address:
                    continue
                value = _effective_value(state, sheet, address, field.get("value"))
                if _nonempty(value):
                    identity_sources[(sheet, address)] = (doc_index, value, str(field_key))

    items: list[CoverageItem] = []
    seen: set[tuple[str, str]] = set()

    # Identity cells are separate from card transaction slots.
    for (sheet, address), (doc_index, value, field_key) in sorted(identity_sources.items()):
        seen.add((sheet, address))
        items.append(CoverageItem(
            sheet=sheet,
            address=address,
            classification="CAPTURED_IDENTITY",
            value=value,
            document_index=doc_index,
            source_kind=field_key,
        ))

    for sheet, payload in (cards.get("sheets") or {}).items():
        for card in payload.get("cards", []):
            doc_index = int(card.get("record_index"))
            for slot in card.get("slots", []):
                address = str(slot.get("address") or "")
                if not address:
                    continue
                value = _effective_value(state, sheet, address, slot.get("value"))
                if not _nonempty(value):
                    continue
                key = (sheet, address)
                if key in seen:
                    continue
                seen.add(key)
                if key in issue_sources:
                    classification = "UNRESOLVED_ISSUE"
                    source_kind = ",".join(sorted(set(issue_sources[key])))
                    note = "Board-to-Log issue"
                elif key in narrative_sources:
                    classification = "CAPTURED_NARRATIVE"
                    source_kind = ",".join(sorted(set(transaction_sources[key]))) or "narrative"
                    note = "Narrative content preserved losslessly as source provenance"
                elif key in transaction_sources:
                    classification = "CAPTURED_TRANSACTION"
                    source_kind = ",".join(sorted(set(transaction_sources[key])))
                    note = None
                else:
                    classification = "SCANNED_NOT_RETRIEVED"
                    source_kind = None
                    note = "Mapped non-empty slot did not populate a canonical Logbook field"
                items.append(CoverageItem(
                    sheet=sheet,
                    address=address,
                    classification=classification,
                    value=value,
                    document_index=doc_index,
                    source_kind=source_kind,
                    note=note,
                ))

    counts = Counter(x.classification for x in items)
    for classification in CLASSIFICATION_MEANINGS:
        counts.setdefault(classification, 0)
    by_sheet: dict[str, Counter[str]] = defaultdict(Counter)
    for item in items:
        by_sheet[item.sheet][item.classification] += 1

    return {
        "schema": "board_to_log.coverage_audit/0.1",
        "run_id": run.run_id,
        "project_id": result.project_id,
        "source_workbook": result.source_workbook,
        "summary": {
            "mapped_nonempty_count": len(items),
            "counts": dict(sorted(counts.items())),
            "sheets": {
                sheet: dict(sorted(counter.items()))
                for sheet, counter in sorted(by_sheet.items())
            },
        },
        "legend": dict(CLASSIFICATION_MEANINGS),
        "items": [x.to_dict() for x in items],
    }


# Excel uses the integer 0x00BBGGRR representation for Color properties.
def _excel_rgb(red: int, green: int, blue: int) -> int:
    return int(red) + (int(green) << 8) + (int(blue) << 16)


COVERAGE_STYLE = {
    "CAPTURED_TRANSACTION": {
        "fill": _excel_rgb(226, 239, 218),
        "font": _excel_rgb(0, 97, 0),
    },
    "CAPTURED_NARRATIVE": {
        "fill": _excel_rgb(221, 235, 247),
        "font": _excel_rgb(31, 78, 121),
    },
    "CAPTURED_IDENTITY": {
        "fill": _excel_rgb(231, 230, 230),
        "font": _excel_rgb(64, 64, 64),
    },
    "UNRESOLVED_ISSUE": {
        "fill": _excel_rgb(244, 176, 132),
        "font": _excel_rgb(156, 0, 6),
    },
    "SCANNED_NOT_RETRIEVED": {
        "fill": _excel_rgb(255, 235, 156),
        "font": _excel_rgb(156, 101, 0),
    },
}


def apply_coverage_highlights_com(
    workbook,
    audit: dict[str, Any],
    *,
    legend_sheet: str = "Coverage_Audit",
) -> dict[str, Any]:
    """Colour a controlled workbook copy for visual coverage QA."""
    excel = workbook.Application
    old_alerts = excel.DisplayAlerts
    applied = Counter()
    try:
        excel.DisplayAlerts = False
        # Recreate legend if this is a repeated audit run.
        for ws in workbook.Worksheets:
            if ws.Name == legend_sheet:
                ws.Delete()
                break

        for item in audit.get("items", []):
            style = COVERAGE_STYLE.get(str(item.get("classification")))
            if not style:
                continue
            ws = workbook.Worksheets(str(item["sheet"]))
            rng = ws.Range(str(item["address"]))
            rng.Interior.Color = style["fill"]
            rng.Font.Color = style["font"]
            applied[str(item["classification"])] += 1

        legend = workbook.Worksheets.Add()
        legend.Name = legend_sheet
        headers = ("Class", "Meaning", "Count")
        legend.Range(legend.Cells(1, 1), legend.Cells(1, 3)).Value2 = (headers,)
        legend.Rows(1).Font.Bold = True
        for row, (classification, meaning) in enumerate(CLASSIFICATION_MEANINGS.items(), start=2):
            legend.Cells(row, 1).Value2 = classification
            legend.Cells(row, 2).Value2 = meaning
            legend.Cells(row, 3).Value2 = int(applied.get(classification, 0))
            style = COVERAGE_STYLE[classification]
            legend.Cells(row, 1).Interior.Color = style["fill"]
            legend.Cells(row, 1).Font.Color = style["font"]
        legend.Columns(1).ColumnWidth = 28
        legend.Columns(2).ColumnWidth = 75
        legend.Columns(3).ColumnWidth = 12
        return {
            "legend_sheet": legend_sheet,
            "highlighted_count": sum(applied.values()),
            "counts": dict(sorted(applied.items())),
        }
    finally:
        excel.DisplayAlerts = old_alerts
