from __future__ import annotations

from pathlib import Path
from hashlib import sha256
import json
import re
from typing import Any

from .xlsx import XlsxWorkbook, split_ref, col_to_num, normalize_text
from .semantic import extract_semantic_content

WBS_RE = re.compile(r"^\d+(?:\.\d+)*$")
JALALI_RE = re.compile(r"^14\d{2}/(?:0?[1-9]|1[0-2])/(?:0?[1-9]|[12]\d|3[01])$")


def load_profile(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _hash(path: Path) -> str:
    h = sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _find_sheet(wb: XlsxWorkbook, declaration: dict) -> str | None:
    names = declaration.get("match", {}).get("exact_names", [])
    normalized = {normalize_text(x): x for x in wb.sheet_names()}
    for name in names:
        if normalize_text(name) in normalized:
            return normalized[normalize_text(name)]
    return None


def _jalali_tuple(value: object) -> tuple[int, int, int] | None:
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not JALALI_RE.fullmatch(raw):
        return None
    y, m, d = raw.split("/")
    return int(y), int(m), int(d)


def _authoritative_status_date(wb: XlsxWorkbook, profile: dict) -> str | None:
    authority = profile.get("status_date_authority") or {}
    sheet_id = authority.get("sheet_id")
    cell = authority.get("cell")
    if not sheet_id or not cell:
        return None
    decl = next((x for x in profile.get("sheets", []) if x.get("sheet_id") == sheet_id), None)
    if not decl:
        return None
    sheet = _find_sheet(wb, decl)
    if not sheet:
        return None
    value = wb.cell(sheet, cell).value
    return value.strip() if _jalali_tuple(value) else None


def _required_for_status_date(decl: dict, status_date: str | None) -> bool:
    required = bool(decl.get("required", False))
    threshold = decl.get("required_from_status_date")
    if threshold and status_date:
        current = _jalali_tuple(status_date)
        start = _jalali_tuple(threshold)
        if current and start:
            required = current >= start
    return required


def inspect_file(workbook_path: str | Path, profile_path: str | Path) -> dict:
    path = Path(workbook_path)
    profile = load_profile(profile_path)
    wb = XlsxWorkbook(path)
    matched = []
    for decl in profile["sheets"]:
        actual = _find_sheet(wb, decl)
        matched.append({
            "sheet_id": decl["sheet_id"],
            "role": decl["role"],
            "required": decl.get("required", False),
            "matched_sheet": actual,
            "dimension": wb.dimensions.get(actual) if actual else None,
            "merge_count": len(wb.merges.get(actual, [])) if actual else 0,
            "formula_count": sum(1 for c in wb.iter_cells(actual) if c.formula) if actual else 0,
        })
    return {
        "schema": "cleaner.weekly_report.inspection/0.1",
        "project_id": profile["project_id"],
        "document_family": profile["document_family"],
        "file": {
            "path": str(path),
            "name": path.name,
            "size_bytes": path.stat().st_size,
            "sha256": _hash(path),
        },
        "sheet_count": len(wb.sheet_names()),
        "sheets": wb.sheet_names(),
        "profile_matches": matched,
        "formula_reference_errors": wb.formula_error_refs(),
    }


def validate_file(workbook_path: str | Path, profile_path: str | Path) -> dict:
    path = Path(workbook_path)
    profile = load_profile(profile_path)
    wb = XlsxWorkbook(path)
    issues: list[dict] = []
    evidence: list[dict] = []
    actual_by_id: dict[str, str] = {}
    authoritative_status_date = _authoritative_status_date(wb, profile)

    for decl in profile["sheets"]:
        actual = _find_sheet(wb, decl)
        required_now = _required_for_status_date(decl, authoritative_status_date)
        if actual:
            actual_by_id[decl["sheet_id"]] = actual
            evidence.append({"kind": "SHEET_MATCH", "sheet_id": decl["sheet_id"], "sheet": actual, "role": decl["role"]})
        elif required_now:
            issues.append({"severity": "ERROR", "kind": "MISSING_REQUIRED_SHEET", "sheet_id": decl["sheet_id"]})
        elif decl.get("required_from_status_date"):
            evidence.append({"kind": "OPTIONAL_HISTORICAL_SHEET_ABSENT", "sheet_id": decl["sheet_id"], "required_from_status_date": decl["required_from_status_date"], "status_date": authoritative_status_date})

    # Project title and status-date evidence.
    report_dates = []
    for decl in profile["sheets"]:
        actual = actual_by_id.get(decl["sheet_id"])
        if not actual:
            continue
        title_cell = decl.get("project_title_cell")
        if title_cell:
            title = wb.cell(actual, title_cell).value
            if title and not any(normalize_text(token) in normalize_text(title) for token in profile["identity"].get("project_title_contains", [])):
                issues.append({"severity": "ERROR", "kind": "PROJECT_IDENTITY_MISMATCH", "sheet": actual, "cell": title_cell, "value": title})
        for ref in decl.get("status_date_cells", []):
            value = wb.cell(actual, ref).value
            report_dates.append({"sheet": actual, "cell": ref, "value": value})
            if not isinstance(value, str) or not JALALI_RE.fullmatch(value.strip()):
                issues.append({"severity": "ERROR", "kind": "INVALID_STATUS_DATE", "sheet": actual, "cell": ref, "value": value})

        for ref, expected in decl.get("expected_headers", {}).items():
            actual_value = wb.cell(actual, ref).value
            if normalize_text(actual_value) != normalize_text(expected):
                issues.append({"severity": "ERROR", "kind": "MASTER_HEADER_MISMATCH", "sheet": actual, "cell": ref, "expected": expected, "actual": actual_value})

        for region in decl.get("regions", []):
            anchor = region.get("anchor_contains")
            if anchor:
                occurrences = wb.find_text(actual, anchor)
                wanted = int(region.get("occurrence", 1))
                if len(occurrences) < wanted:
                    issues.append({"severity": "ERROR", "kind": "REGION_ANCHOR_MISSING", "sheet": actual, "region_id": region["region_id"], "anchor": anchor, "occurrence": wanted})
                else:
                    evidence.append({"kind": "REGION_ANCHOR", "sheet": actual, "region_id": region["region_id"], "anchor_cell": occurrences[wanted - 1]})

    visible_date_values = [str(x["value"]).strip() for x in report_dates if isinstance(x["value"], str) and JALALI_RE.fullmatch(str(x["value"]).strip())]
    if visible_date_values and len(set(visible_date_values)) > 1:
        issues.append({"severity": "ERROR", "kind": "REPORT_DATE_MISMATCH", "dates": report_dates})

    # Master WBS/progress validation.
    master_decl = next((x for x in profile["sheets"] if x["sheet_id"] == "master"), None)
    master_sheet = actual_by_id.get("master")
    wbs_rows = []
    if master_decl and master_sheet:
        cells = wb.sheets[master_sheet]
        max_row = 0
        for ref in cells:
            _, r = split_ref(ref)
            max_row = max(max_row, r)
        seen: dict[str, list[int]] = {}
        for r in range(2, max_row + 1):
            raw_wbs = wb.cell(master_sheet, f"A{r}").value
            task = wb.cell(master_sheet, f"C{r}").value
            if raw_wbs in (None, ""):
                continue
            wbs = str(raw_wbs).strip()
            if not WBS_RE.fullmatch(wbs):
                issues.append({"severity": "WARNING", "kind": "INVALID_WBS", "sheet": master_sheet, "cell": f"A{r}", "value": raw_wbs})
                continue
            seen.setdefault(wbs, []).append(r)
            plan = wb.cell(master_sheet, f"E{r}").value
            actual = wb.cell(master_sheet, f"F{r}").value
            weight = wb.cell(master_sheet, f"D{r}").value
            for field, value in (("plan_pct", plan), ("actual_pct", actual)):
                if isinstance(value, (int, float)) and not (0 <= float(value) <= 100):
                    issues.append({"severity": "ERROR", "kind": "PROGRESS_OUT_OF_RANGE", "sheet": master_sheet, "cell": f"{'E' if field == 'plan_pct' else 'F'}{r}", "value": value})
            if isinstance(weight, (int, float)) and float(weight) < 0:
                issues.append({"severity": "ERROR", "kind": "NEGATIVE_WEIGHT", "sheet": master_sheet, "cell": f"D{r}", "value": weight})
            wbs_rows.append({"row": r, "wbs": wbs, "task": task})
        for wbs, rows in seen.items():
            if len(rows) > 1:
                duplicate_tasks = [normalize_text(wb.cell(master_sheet, f"C{r}").value) for r in rows]
                known_terminal_collapse = wbs == "1.1" and any("پایان" in task for task in duplicate_tasks)
                issue = {
                    "severity": "WARNING" if known_terminal_collapse else "ERROR",
                    "kind": "DUPLICATE_WBS",
                    "wbs": wbs,
                    "rows": rows,
                }
                if known_terminal_collapse:
                    issue["known_anomaly_id"] = "AZD-WR-001"
                issues.append(issue)

    semantic = extract_semantic_content(wb, profile, actual_by_id)
    issues.extend(semantic.get("issues", []))
    evidence.append({"kind": "SEMANTIC_EXTRACTION", **semantic.get("counts", {})})

    for err in wb.formula_error_refs():
        issues.append({"severity": "WARNING", "kind": "FORMULA_REFERENCE_ERROR", **err})

    errors = [x for x in issues if x["severity"] == "ERROR"]
    warnings = [x for x in issues if x["severity"] == "WARNING"]
    return {
        "schema": "cleaner.weekly_report.validation/0.1",
        "project_id": profile["project_id"],
        "document_family": profile["document_family"],
        "profile_version": profile["profile_version"],
        "file_sha256": _hash(path),
        "status": "passed" if not errors else "needs_review",
        "counts": {"errors": len(errors), "warnings": len(warnings), "evidence": len(evidence), "wbs_rows": len(wbs_rows)},
        "report_dates": report_dates,
        "issues": issues,
        "evidence": evidence,
    }


def _canonical_status(profile: dict, value: object) -> str | None:
    if value in (None, ""):
        return None
    raw = str(value).strip()
    blank_tokens = {str(x).strip().upper() for x in profile.get("status_semantics", {}).get("blank_tokens", [])}
    if raw.upper() in blank_tokens:
        return None
    token = raw.upper()
    for code, info in profile.get("status_semantics", {}).get("canonical", {}).items():
        if token == code.upper() or token in {str(x).upper() for x in info.get("aliases", [])}:
            return code
    return token


def _classify_wbs_rows(rows: list[dict]) -> None:
    wbs_values = [x["wbs"] for x in rows]
    for item in rows:
        prefix = item["wbs"] + "."
        item["row_type"] = "SUMMARY" if any(x.startswith(prefix) for x in wbs_values) else "LEAF"
        task = normalize_text(item.get("task"))
        if item["row_type"] == "LEAF" and ("شروع" in task or "پایان" in task):
            item["row_type"] = "MILESTONE"


def extract_file(workbook_path: str | Path, profile_path: str | Path) -> dict:
    path = Path(workbook_path)
    profile = load_profile(profile_path)
    wb = XlsxWorkbook(path)
    actual_by_id = {decl["sheet_id"]: _find_sheet(wb, decl) for decl in profile["sheets"]}

    report_dates = []
    publication_status_date_targets = []
    semantic = extract_semantic_content(wb, profile, actual_by_id)
    discovered_regions = semantic["regions"]
    procurement = semantic["procurement_reports"]
    engineering_lists = semantic["engineering_lists"]

    for decl in profile["sheets"]:
        sheet = actual_by_id.get(decl["sheet_id"])
        if not sheet:
            continue
        for ref in decl.get("status_date_cells", []):
            report_dates.append({"sheet_id": decl["sheet_id"], "sheet": sheet, "cell": ref, "value": wb.cell(sheet, ref).value})
        for ref in decl.get("publication_status_date_cells", decl.get("status_date_cells", [])):
            publication_status_date_targets.append({"sheet_id": decl["sheet_id"], "sheet": sheet, "cell": ref, "current_value": wb.cell(sheet, ref).value})
    master_sheet = actual_by_id.get("master")
    master_rows = []
    status_tokens: dict[str, int] = {}
    if master_sheet:
        max_row = _max_row(wb, master_sheet)
        status_cols = ["M", "R", "W", "AB", "AG", "AL", "AQ", "AV"]
        for r in range(2, max_row + 1):
            raw_wbs = wb.cell(master_sheet, f"A{r}").value
            if raw_wbs in (None, ""):
                continue
            wbs = str(raw_wbs).strip()
            if not WBS_RE.fullmatch(wbs):
                continue
            item = {
                "row": r,
                "wbs": wbs,
                "task": wb.cell(master_sheet, f"C{r}").value,
                "weight_factor": wb.cell(master_sheet, f"D{r}").value,
                "plan_pct": wb.cell(master_sheet, f"E{r}").value,
                "actual_pct": wb.cell(master_sheet, f"F{r}").value,
                "delay": wb.cell(master_sheet, f"G{r}").value,
                "start": wb.cell(master_sheet, f"H{r}").value,
                "finish": wb.cell(master_sheet, f"I{r}").value,
            }
            master_rows.append(item)
            for col in status_cols:
                v = wb.cell(master_sheet, f"{col}{r}").value
                canon = _canonical_status(profile, v)
                if canon:
                    status_tokens[canon] = status_tokens.get(canon, 0) + 1
        _classify_wbs_rows(master_rows)

    return {
        "schema": "cleaner.weekly_report.extraction/0.2",
        "project_id": profile["project_id"],
        "document_family": profile["document_family"],
        "profile_version": profile["profile_version"],
        "source": {"path": str(path), "name": path.name, "sha256": _hash(path)},
        "report_dates": report_dates,
        "publication_status_date_targets": publication_status_date_targets,
        "regions": discovered_regions,
        "master_progress": {
            "rows": master_rows,
            "counts": {
                "total": len(master_rows),
                "summary": sum(1 for x in master_rows if x["row_type"] == "SUMMARY"),
                "leaf": sum(1 for x in master_rows if x["row_type"] == "LEAF"),
                "milestone": sum(1 for x in master_rows if x["row_type"] == "MILESTONE")
            }
        },
        "engineering_status_counts": status_tokens,
        "current_engineering_report_lists": engineering_lists,
        "procurement_reports": procurement,
        "semantic_quality": {"counts": semantic["counts"], "issues": semantic["issues"]},
    }


def run_profile(workbook_path: str | Path, profile_path: str | Path) -> dict:
    return {
        "inspection": inspect_file(workbook_path, profile_path),
        "validation": validate_file(workbook_path, profile_path),
        "extraction": extract_file(workbook_path, profile_path),
    }


def _max_row(wb: XlsxWorkbook, sheet: str) -> int:
    result = 0
    for c in wb.iter_cells(sheet):
        _, row = split_ref(c.ref)
        result = max(result, row)
    return result


def _range_parts(rng: str):
    a, b = rng.split(":")
    ca, ra = split_ref(a)
    cb, rb = split_ref(b)
    return col_to_num(ca), ra, col_to_num(cb), rb


def _num_to_col(n: int) -> str:
    out = ""
    while n:
        n, rem = divmod(n - 1, 26)
        out = chr(65 + rem) + out
    return out
