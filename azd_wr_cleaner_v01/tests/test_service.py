from pathlib import Path
import json

from wr_cleaner.service import inspect_file, validate_file, extract_file

BASE = Path(__file__).resolve().parents[1]
PROFILE = BASE / "profiles" / "projects" / "AZD.WEEKLY_REPORT_TEMPLATE.profile.json"
WORKBOOK = Path(r'W:/پیگیری پروژه ها/گزارش هفتگی پروژه ها/1405/1405.07.15/7- سد آزاد.xlsx')


def test_base_inspection_matches_all_eight_sheets():
    result = inspect_file(WORKBOOK, PROFILE)
    assert result["sheet_count"] == 8
    assert all(x["matched_sheet"] for x in result["profile_matches"])


def test_base_validation_has_no_errors():
    result = validate_file(WORKBOOK, PROFILE)
    assert result["counts"]["errors"] == 0
    assert result["counts"]["wbs_rows"] >= 800


def test_base_extraction_recognizes_core_regions_and_progress():
    result = extract_file(WORKBOOK, PROFILE)
    counts = result["master_progress"]["counts"]
    assert counts["total"] >= 800
    assert counts["summary"] > 100
    assert counts["leaf"] > 600
    assert len(result["regions"]) >= 15
    assert any(r["region_type"] == "COMPANY_DELAY_LIST" and r["anchor_cell"] for r in result["regions"])


def test_status_aliases_are_canonicalized():
    result = extract_file(WORKBOOK, PROFILE)
    counts = result["engineering_status_counts"]
    assert "A" in counts
    assert "AN" in counts
    assert "CM" in counts
