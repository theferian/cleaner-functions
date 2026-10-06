from __future__ import annotations

import json
from pathlib import Path


def test_project_source_registry_contains_supplied_general_documents():
    root = Path(__file__).resolve().parents[1]
    cfg = json.loads((root / "configs" / "project_control_sources.json").read_text(encoding="utf-8"))
    projects = cfg["projects"]
    expected = {
        "AZD": r"W:\00-1403\1403-02-05-230kV Azad\Letter\technical\updated Doc\General - Azad.xlsx",
        "JND": r"W:\00-1403\1403-02-03-400-132kv Jondi Shapoor\Letter\technical\Updated Doc\General - Jondi Shapour.xlsx",
        "FSH": r"W:\00-1403\1403-02-01-132kV Gostarsh Foulad shahryar\Letter\technical\GOSTARESH E FOLAD E SHAHRIAR - UPDATED DOC.xlsx",
        "BFG": r"W:\00-1403\1403-02-02-132kv Foulad Bafgh Kasra and Ext. of Nakhlestan\Letter\technical\Baafgh\updated Doc\Baafgh..xlsx",
        "NKH": r"W:\00-1403\1403-02-02-132kv Foulad Bafgh Kasra and Ext. of Nakhlestan\Letter\technical\Nakhlestan\updated Doc\Nakhlestan...xlsx",
        "EYV": r"W:\00-1401\140102-09- 63kv Ivanaki\letter\technical\updated Doc\General-IVANAKI.xlsx",
        "YSK": r"W:\00-1400\140002-03- 63kv hasan abad yasookand\letter\technical\updated Doc\Yasookand-General.xlsx",
    }
    for project, path in expected.items():
        assert projects[project]["sources"]["GENERAL_DOCUMENT"]["path"] == path
    assert projects["NGN"]["enabled"] is False
