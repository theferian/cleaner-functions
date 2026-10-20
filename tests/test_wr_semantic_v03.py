import os
from pathlib import Path

import pytest

from wr_cleaner.service import extract_file, validate_file

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "profiles" / "projects" / "AZD.WEEKLY_REPORT_TEMPLATE.profile.json"
WORKBOOK = Path(os.environ.get(
    "AZD_WR_TEST_WORKBOOK",
    r"W:/پیگیری پروژه ها/گزارش هفتگی پروژه ها/1405/1405.07.15/7- سد آزاد.xlsx",
))

pytestmark = pytest.mark.skipif(not WORKBOOK.exists(), reason="AZD WR integration workbook not available")


def test_v03_validation_remains_non_blocking():
    result = validate_file(WORKBOOK, PROFILE)
    assert result["status"] == "passed"
    assert result["profile_version"] == "0.3.0"


def test_v03_engineering_records_are_typed():
    result = extract_file(WORKBOOK, PROFILE)
    lists = result["current_engineering_report_lists"]
    company = next(x for x in lists if x["region_id"] == "LINE_230_COMPANY_DELAY")
    foundation = next(x for x in company["records"] if x["document_name"] == "FOUNDATION DRAWING")
    assert foundation["current_holder"] == "COMPANY"
    assert foundation["responsibility_since"] == "1404/11/04"
    assert foundation["delay_days"] == 250
    assert foundation["revision"] == "A"


def test_v03_procurement_merged_status_is_inherited():
    result = extract_file(WORKBOOK, PROFILE)
    reports = {x["sheet_id"]: x for x in result["procurement_reports"]}
    line15 = reports["procurement_line63_15"]
    assert line15["record_count"] == 3
    assert [x["status"] for x in line15["items"]] == ["سبز", "سبز", "سبز"]


def test_v03_region_boundaries_are_explicit():
    result = extract_file(WORKBOOK, PROFILE)
    regions = {x["region_id"]: x for x in result["regions"]}
    r = regions["LINE_230_COMPANY_DELAY"]
    assert r["effective_range"] == "A19:I26"
    assert r["header_row"] == 19
    assert r["data_start_row"] == 20
    assert r["data_end_row"] == 26
    assert r["capacity_rows"] == 7


def test_jalali_two_digit_day_is_not_truncated():
    from wr_cleaner.semantic import DATE_TOKEN_RE
    assert DATE_TOKEN_RE.findall("فنی از تاریخ 1404/02/24") == ["1404/02/24"]
    assert DATE_TOKEN_RE.findall("1405/11/30") == ["1405/11/30"]
