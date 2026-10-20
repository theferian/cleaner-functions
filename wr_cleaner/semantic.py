from __future__ import annotations

import re
from typing import Any

from .xlsx import XlsxWorkbook, split_ref, col_to_num, normalize_text

DATE_TOKEN_RE = re.compile('14\\d{2}/(?:1[0-2]|0?[1-9])/(?:3[01]|[12]\\d|0?[1-9])')
REV_RE = re.compile(r"\(\s*Rev(?:ision)?\s*([A-Za-z0-9._-]+)\s*\)", re.IGNORECASE)
STATUS_COLORS = {"قرمز", "نارنجی", "زرد", "سبز"}
PLACEHOLDERS = {"", "-", "_", "—", "ندارد.", "ندارد"}


def _num_to_col(n: int) -> str:
    out = ""
    while n:
        n, rem = divmod(n - 1, 26)
        out = chr(65 + rem) + out
    return out


def _range_parts(rng: str) -> tuple[int, int, int, int]:
    a, b = rng.split(":")
    ca, ra = split_ref(a)
    cb, rb = split_ref(b)
    return col_to_num(ca), ra, col_to_num(cb), rb


def _find_anchor(wb: XlsxWorkbook, sheet: str, region: dict) -> str | None:
    anchor = region.get("anchor_contains")
    if not anchor:
        return None
    occurrences = wb.find_text(sheet, anchor)
    wanted = int(region.get("occurrence", 1))
    return occurrences[wanted - 1] if len(occurrences) >= wanted else None


def _effective_region_range(region: dict, anchor_cell: str | None) -> tuple[int, int, int, int] | None:
    fallback = region.get("fallback_range")
    if not fallback:
        return None
    c1, r1, c2, r2 = _range_parts(fallback)
    if anchor_cell and region.get("boundary_strategy") == "ANCHOR_SHIFTED_PROFILE_RANGE":
        _, anchor_row = split_ref(anchor_cell)
        delta = anchor_row - r1
        r1 += delta
        r2 += delta
    return c1, r1, c2, r2


def _dates(value: object) -> list[str]:
    if value in (None, ""):
        return []
    return DATE_TOKEN_RE.findall(str(value))


def _semantic_value(value: object) -> object:
    if isinstance(value, str) and value.strip() in PLACEHOLDERS:
        return None
    return value


def _merged_anchor_value(wb: XlsxWorkbook, sheet: str, ref: str) -> object:
    col, row = split_ref(ref)
    ci = col_to_num(col)
    direct = wb.cell(sheet, ref).value
    if direct not in (None, ""):
        return direct
    for rng in wb.merges.get(sheet, []):
        c1, r1, c2, r2 = _range_parts(rng)
        if c1 <= ci <= c2 and r1 <= row <= r2:
            return wb.cell(sheet, f"{_num_to_col(c1)}{r1}").value
    return direct


def _document_parts(value: object) -> tuple[str | None, str | None, str | None]:
    if value in (None, ""):
        return None, None, None
    raw = str(value).strip()
    label = raw
    for marker in (" فنی:", "\nفنی:", " پروژه:", "\nپروژه:", " بازرگانی:", "\nبازرگانی:"):
        if marker in label:
            label = label.split(marker, 1)[0].strip()
    m = REV_RE.search(label)
    revision = m.group(1).upper() if m else None
    name = REV_RE.sub("", label).strip()
    name = re.sub(r"\s+", " ", name)
    return name or None, revision, raw


def _responsibility_unit(text: object) -> str | None:
    if not isinstance(text, str):
        return None
    clean = normalize_text(text)
    marker = normalize_text("از تاریخ")
    if marker in clean:
        before = clean.split(marker, 1)[0].strip()
        return before or None
    return None


def _engineering_record(wb: XlsxWorkbook, sheet: str, region: dict, row: int, c1: int, c2: int) -> dict | None:
    values = { _num_to_col(c): wb.cell(sheet, f"{_num_to_col(c)}{row}").value for c in range(c1, c2 + 1) }
    if not any(v not in (None, "") for v in values.values()):
        return None
    kind = region.get("region_type")
    scope = region.get("scope")

    if kind == "NOT_SENT_LIST":
        source = next((values.get(c) for c in values if values.get(c) not in (None, "")), None)
        name, revision, raw_label = _document_parts(source)
        record = {
            "row": row, "list_type": kind, "scope": scope, "state": "NOT_SENT",
            "document_name": name, "revision": revision, "document_label_raw": raw_label,
        }
    elif kind == "COMPANY_DELAY_LIST":
        holder_text = values.get("A") or values.get("B")
        doc_value = next((values.get(c) for c in "DEFGHI" if values.get(c) not in (None, "")), None)
        name, revision, raw_label = _document_parts(doc_value)
        delay = _semantic_value(values.get("C"))
        record = {
            "row": row, "list_type": kind, "scope": scope, "current_holder": "COMPANY",
            "responsibility_unit_text": _responsibility_unit(holder_text),
            "responsibility_since": (_dates(holder_text) or [None])[0],
            "delay_days": delay if isinstance(delay, (int, float)) else None,
            "document_name": name, "revision": revision, "document_label_raw": raw_label,
        }
    elif kind == "CONSULTANT_DELAY_LIST":
        doc_value = next((values.get(c) for c in "DEFGHI" if values.get(c) not in (None, "")), None)
        name, revision, raw_label = _document_parts(doc_value)
        delay = _semantic_value(values.get("A"))
        record = {
            "row": row, "list_type": kind, "scope": scope, "current_holder": "CONSULTANT",
            "delay_days": delay if isinstance(delay, (int, float)) else None,
            "document_name": name, "revision": revision, "document_label_raw": raw_label,
        }
    else:
        return None

    record["provenance"] = {
        "sheet": sheet,
        "row": row,
        "source_range": f"{_num_to_col(c1)}{row}:{_num_to_col(c2)}{row}",
        "raw_values": values,
    }
    return record


def _procurement_item(wb: XlsxWorkbook, sheet: str, decl: dict, row: int) -> dict | None:
    equipment = wb.cell(sheet, f"M{row}").value
    if equipment in (None, ""):
        return None
    status_raw = _merged_anchor_value(wb, sheet, f"A{row}")
    status = str(status_raw).strip() if status_raw not in (None, "") else None
    raw = {c: wb.cell(sheet, f"{c}{row}").value for c in "ABCDEFGHIJKLM"}
    date_fields = {
        "order_contract_date": raw["E"],
        "technical_approval": raw["F"],
        "vendor_drawing_received": raw["G"],
        "purchase_request": raw["H"],
        "mto_date": raw["I"],
    }
    item = {
        "row": row,
        "status": status,
        "notes": raw["B"] if raw["B"] not in (None, "") else raw["C"],
        "manufacture_delivery_duration": _semantic_value(raw["D"]),
        "order_contract_date": _semantic_value(raw["E"]),
        "technical_approval": _semantic_value(raw["F"]),
        "vendor_drawing_received": _semantic_value(raw["G"]),
        "purchase_request": _semantic_value(raw["H"]),
        "mto_date": _semantic_value(raw["I"]),
        "delay_ratio": _semantic_value(raw["J"]),
        "actual_ratio": _semantic_value(raw["K"]),
        "plan_ratio": _semantic_value(raw["L"]),
        "equipment": str(equipment).strip(),
        "date_tokens": {key: _dates(value) for key, value in date_fields.items()},
        "provenance": {
            "sheet": sheet,
            "row": row,
            "source_range": f"A{row}:M{row}",
            "raw_values": raw,
            "status_source": "MERGED_A_ANCHOR" if raw["A"] in (None, "") and status_raw not in (None, "") else "A_CELL",
        },
    }
    return item


def extract_semantic_content(wb: XlsxWorkbook, profile: dict, actual_by_id: dict[str, str | None]) -> dict:
    regions: list[dict] = []
    engineering_lists: list[dict] = []
    procurement_reports: list[dict] = []
    issues: list[dict] = []

    for decl in profile.get("sheets", []):
        sheet = actual_by_id.get(decl.get("sheet_id"))
        if not sheet:
            continue
        for region in decl.get("regions", []):
            anchor_cell = _find_anchor(wb, sheet, region)
            effective = _effective_region_range(region, anchor_cell)
            meta = {
                "sheet_id": decl.get("sheet_id"), "sheet": sheet,
                "region_id": region.get("region_id"), "region_type": region.get("region_type"),
                "scope": region.get("scope"), "anchor_cell": anchor_cell,
                "fallback_range": region.get("fallback_range"), "ownership": region.get("ownership"),
                "boundary_strategy": region.get("boundary_strategy", "PROFILE_RANGE"),
            }
            if effective:
                c1, r1, c2, r2 = effective
                meta.update({
                    "effective_range": f"{_num_to_col(c1)}{r1}:{_num_to_col(c2)}{r2}",
                    "header_row": r1,
                    "data_start_row": r1 + 1,
                    "data_end_row": r2,
                    "capacity_rows": max(0, r2 - r1),
                })
            regions.append(meta)

            if region.get("region_type") in {"NOT_SENT_LIST", "COMPANY_DELAY_LIST", "CONSULTANT_DELAY_LIST"} and effective:
                c1, r1, c2, r2 = effective
                records = []
                for row in range(r1 + 1, r2 + 1):
                    rec = _engineering_record(wb, sheet, region, row, c1, c2)
                    if rec:
                        records.append(rec)
                        if not rec.get("document_name"):
                            issues.append({"severity": "WARNING", "kind": "ENGINEERING_DOCUMENT_NAME_MISSING", "sheet": sheet, "region_id": region.get("region_id"), "row": row})
                        if region.get("region_type") in {"COMPANY_DELAY_LIST", "CONSULTANT_DELAY_LIST"} and rec.get("delay_days") is None:
                            issues.append({"severity": "WARNING", "kind": "ENGINEERING_DELAY_DAYS_INVALID", "sheet": sheet, "region_id": region.get("region_id"), "row": row})
                meta["populated_rows"] = len(records)
                engineering_lists.append({
                    "region_id": region.get("region_id"), "region_type": region.get("region_type"),
                    "scope": region.get("scope"), "sheet": sheet,
                    "effective_range": meta.get("effective_range"),
                    "capacity_rows": meta.get("capacity_rows"),
                    "record_count": len(records),
                    "records": records,
                    # Backward-compatible alias during v0.3 migration.
                    "rows": records,
                })

        if decl.get("role") == "PROCUREMENT_REPORT":
            start = int(decl.get("item_start_row", 8))
            max_row = max((split_ref(c.ref)[1] for c in wb.iter_cells(sheet)), default=0)
            items = []
            for row in range(start, max_row + 1):
                item = _procurement_item(wb, sheet, decl, row)
                if not item:
                    continue
                items.append(item)
                if item.get("status") not in STATUS_COLORS:
                    issues.append({"severity": "WARNING", "kind": "PROCUREMENT_STATUS_UNKNOWN", "sheet": sheet, "row": row, "value": item.get("status")})
                for key in ("delay_ratio", "actual_ratio", "plan_ratio"):
                    value = item.get(key)
                    if value is not None and (not isinstance(value, (int, float)) or not 0 <= float(value) <= 1):
                        issues.append({"severity": "WARNING", "kind": "PROCUREMENT_RATIO_INVALID", "sheet": sheet, "row": row, "field": key, "value": value})
            procurement_reports.append({
                "sheet_id": decl.get("sheet_id"), "sheet": sheet,
                "record_count": len(items), "items": items,
            })

    return {
        "regions": regions,
        "engineering_lists": engineering_lists,
        "procurement_reports": procurement_reports,
        "issues": issues,
        "counts": {
            "regions": len(regions),
            "engineering_records": sum(x["record_count"] for x in engineering_lists),
            "procurement_items": sum(x["record_count"] for x in procurement_reports),
            "semantic_warnings": len(issues),
        },
    }
