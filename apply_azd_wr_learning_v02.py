from __future__ import annotations

from pathlib import Path
import json
import shutil
from datetime import datetime

ROOT = Path.cwd()
SERVICE = ROOT / "wr_cleaner" / "service.py"
PROFILE = ROOT / "profiles" / "projects" / "AZD.WEEKLY_REPORT_TEMPLATE.profile.json"

for p in (SERVICE, PROFILE):
    if not p.exists():
        raise SystemExit(f"[ERROR] missing required file: {p}")

stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
backup = ROOT / ".azd_wr_profile_backup" / stamp
backup.mkdir(parents=True, exist_ok=True)
shutil.copy2(SERVICE, backup / "service.py")
shutil.copy2(PROFILE, backup / PROFILE.name)

# ---------------- profile ----------------
profile = json.loads(PROFILE.read_text(encoding="utf-8"))
profile["profile_version"] = "0.2.0"
profile["status"] = "HISTORICALLY_VALIDATED_PENDING_FINAL_REVIEW"
profile["status_date_authority"] = {
    "sheet_id": "execution_substations",
    "cell": "A1",
    "purpose": "Canonical report/status date used for schema-era validation."
}
profile["schema_evolution"] = [
    {
        "id": "AZD-WR-EVOL-001",
        "change": "procurement_line230 sheet introduced into the weekly-report family",
        "effective_from_status_date": "1405/06/04",
        "validation_policy": "OPTIONAL_BEFORE_REQUIRED_FROM_DATE"
    },
    {
        "id": "AZD-WR-EVOL-002",
        "change": "execution_substations J1 became populated in later reports",
        "validation_policy": "A1_AUTHORITATIVE_J1_PUBLICATION_TARGET"
    }
]

for sheet in profile["sheets"]:
    sid = sheet.get("sheet_id")
    if sid == "execution_substations":
        sheet["status_date_cells"] = ["A1"]
        sheet["publication_status_date_cells"] = ["A1", "J1"]
        sheet["status_date_notes"] = "A1 is authoritative for validation; A1 and J1 are both publication write targets."
    elif sheet.get("status_date_cells"):
        sheet.setdefault("publication_status_date_cells", list(sheet["status_date_cells"]))
    if sid == "procurement_line230":
        sheet["required"] = False
        sheet["required_from_status_date"] = "1405/06/04"
        sheet["historical_presence_policy"] = "OPTIONAL_BEFORE_REQUIRED_FROM_DATE"

for anomaly in profile.get("validation_policy", {}).get("known_anomalies", []):
    if anomaly.get("id") == "AZD-WR-001":
        anomaly.pop("location", None)
        anomaly["matcher"] = {
            "sheet_id": "master",
            "wbs": "1.1",
            "duplicate_task_contains": "پایان"
        }
        anomaly["issue"] = "Terminal 'پایان' row is stored as WBS 1.1, likely numeric collapse of intended 1.10; row position varies historically."
        anomaly["policy"] = "WARN_KNOWN_WBS_COLLAPSE"
    elif anomaly.get("id") == "AZD-WR-002":
        anomaly["location"] = "اجرا پست های 230 و 63!J1"
        anomaly["issue"] = "J1 is a publication write target but was blank in older reports; A1 is authoritative for validation."
        anomaly["policy"] = "NON_BLOCKING_PUBLICATION_TARGET"

PROFILE.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

# ---------------- service ----------------
text = SERVICE.read_text(encoding="utf-8")

needle = '''def _find_sheet(wb: XlsxWorkbook, declaration: dict) -> str | None:\n    names = declaration.get("match", {}).get("exact_names", [])\n    normalized = {normalize_text(x): x for x in wb.sheet_names()}\n    for name in names:\n        if normalize_text(name) in normalized:\n            return normalized[normalize_text(name)]\n    return None\n\n\n'''
insert = needle + '''def _jalali_tuple(value: object) -> tuple[int, int, int] | None:\n    if not isinstance(value, str):\n        return None\n    raw = value.strip()\n    if not JALALI_RE.fullmatch(raw):\n        return None\n    y, m, d = raw.split("/")\n    return int(y), int(m), int(d)\n\n\ndef _authoritative_status_date(wb: XlsxWorkbook, profile: dict) -> str | None:\n    authority = profile.get("status_date_authority") or {}\n    sheet_id = authority.get("sheet_id")\n    cell = authority.get("cell")\n    if not sheet_id or not cell:\n        return None\n    decl = next((x for x in profile.get("sheets", []) if x.get("sheet_id") == sheet_id), None)\n    if not decl:\n        return None\n    sheet = _find_sheet(wb, decl)\n    if not sheet:\n        return None\n    value = wb.cell(sheet, cell).value\n    return value.strip() if _jalali_tuple(value) else None\n\n\ndef _required_for_status_date(decl: dict, status_date: str | None) -> bool:\n    required = bool(decl.get("required", False))\n    threshold = decl.get("required_from_status_date")\n    if threshold and status_date:\n        current = _jalali_tuple(status_date)\n        start = _jalali_tuple(threshold)\n        if current and start:\n            required = current >= start\n    return required\n\n\n'''
if needle not in text:
    raise SystemExit("[ERROR] service.py anchor _find_sheet not found; no files were intentionally left unbacked-up")
text = text.replace(needle, insert, 1)

old = '''    issues: list[dict] = []\n    evidence: list[dict] = []\n    actual_by_id: dict[str, str] = {}\n\n    for decl in profile["sheets"]:\n        actual = _find_sheet(wb, decl)\n        if actual:\n            actual_by_id[decl["sheet_id"]] = actual\n            evidence.append({"kind": "SHEET_MATCH", "sheet_id": decl["sheet_id"], "sheet": actual, "role": decl["role"]})\n        elif decl.get("required"):\n            issues.append({"severity": "ERROR", "kind": "MISSING_REQUIRED_SHEET", "sheet_id": decl["sheet_id"]})\n'''
new = '''    issues: list[dict] = []\n    evidence: list[dict] = []\n    actual_by_id: dict[str, str] = {}\n    authoritative_status_date = _authoritative_status_date(wb, profile)\n\n    for decl in profile["sheets"]:\n        actual = _find_sheet(wb, decl)\n        required_now = _required_for_status_date(decl, authoritative_status_date)\n        if actual:\n            actual_by_id[decl["sheet_id"]] = actual\n            evidence.append({"kind": "SHEET_MATCH", "sheet_id": decl["sheet_id"], "sheet": actual, "role": decl["role"]})\n        elif required_now:\n            issues.append({"severity": "ERROR", "kind": "MISSING_REQUIRED_SHEET", "sheet_id": decl["sheet_id"]})\n        elif decl.get("required_from_status_date"):\n            evidence.append({"kind": "OPTIONAL_HISTORICAL_SHEET_ABSENT", "sheet_id": decl["sheet_id"], "required_from_status_date": decl["required_from_status_date"], "status_date": authoritative_status_date})\n'''
if old not in text:
    raise SystemExit("[ERROR] service.py validation sheet block not found")
text = text.replace(old, new, 1)

old = '''        for wbs, rows in seen.items():\n            if len(rows) > 1:\n                severity = "WARNING" if wbs == "1.1" and 876 in rows else "ERROR"\n                issues.append({"severity": severity, "kind": "DUPLICATE_WBS", "wbs": wbs, "rows": rows})\n'''
new = '''        for wbs, rows in seen.items():\n            if len(rows) > 1:\n                duplicate_tasks = [normalize_text(wb.cell(master_sheet, f"C{r}").value) for r in rows]\n                known_terminal_collapse = wbs == "1.1" and any("پایان" in task for task in duplicate_tasks)\n                issue = {\n                    "severity": "WARNING" if known_terminal_collapse else "ERROR",\n                    "kind": "DUPLICATE_WBS",\n                    "wbs": wbs,\n                    "rows": rows,\n                }\n                if known_terminal_collapse:\n                    issue["known_anomaly_id"] = "AZD-WR-001"\n                issues.append(issue)\n'''
if old not in text:
    raise SystemExit("[ERROR] service.py duplicate-WBS block not found")
text = text.replace(old, new, 1)

old = '''    report_dates = []\n    discovered_regions = []\n    procurement = []\n    engineering_lists = []\n'''
new = '''    report_dates = []\n    publication_status_date_targets = []\n    discovered_regions = []\n    procurement = []\n    engineering_lists = []\n'''
if old not in text:
    raise SystemExit("[ERROR] service.py extraction init block not found")
text = text.replace(old, new, 1)

old = '''        for ref in decl.get("status_date_cells", []):\n            report_dates.append({"sheet_id": decl["sheet_id"], "sheet": sheet, "cell": ref, "value": wb.cell(sheet, ref).value})\n        for region in decl.get("regions", []):\n'''
new = '''        for ref in decl.get("status_date_cells", []):\n            report_dates.append({"sheet_id": decl["sheet_id"], "sheet": sheet, "cell": ref, "value": wb.cell(sheet, ref).value})\n        for ref in decl.get("publication_status_date_cells", decl.get("status_date_cells", [])):\n            publication_status_date_targets.append({"sheet_id": decl["sheet_id"], "sheet": sheet, "cell": ref, "current_value": wb.cell(sheet, ref).value})\n        for region in decl.get("regions", []):\n'''
if old not in text:
    raise SystemExit("[ERROR] service.py extraction date block not found")
text = text.replace(old, new, 1)

old = '''        "report_dates": report_dates,\n        "regions": discovered_regions,\n'''
new = '''        "report_dates": report_dates,\n        "publication_status_date_targets": publication_status_date_targets,\n        "regions": discovered_regions,\n'''
if old not in text:
    raise SystemExit("[ERROR] service.py extraction return block not found")
text = text.replace(old, new, 1)

SERVICE.write_text(text, encoding="utf-8")

print("[DONE] AZD WR learning patch v0.2 applied")
print(f"[BACKUP] {backup}")
print(f"[PROFILE] {PROFILE}")
print(f"[SERVICE] {SERVICE}")
