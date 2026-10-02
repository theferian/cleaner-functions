import json
from pathlib import Path

from review.queue import build_review_queue
from review.decisions import make_decision, apply_decision_to_queue


def test_review_queue_and_fix_decision():
    report = {
        "run_id": "run_1",
        "kind": "azd_mline",
        "script_id": "AZD_M_LINE",
        "findings": [
            {
                "test_id": "M_LINE",
                "status": "FAIL",
                "severity": "HIGH",
                "sheet": "63KV SS",
                "target": "B9:X10",
                "message": "Unexpected crossing",
                "expected": "No crossing",
                "observed": "B9:X10",
                "evidence": {"rows": [9, 10]},
                "suggested_exception": None,
            }
        ],
    }

    profile = {
        "schema_version": "0.3",
        "family": "GENERAL_DOCUMENT",
        "profile_name": "AZD",
    }
    manifest = {
        "package_id": "cleaner_functions",
        "version": "0.4.0",
        "review_schema": "0.1",
        "decision_schema": "0.1",
    }
    workbook = {
        "name": "AZD.xlsx",
        "path": r"C:\AZD.xlsx",
        "saved_state": "unsaved",
    }

    queue = build_review_queue(
        report=report,
        profile=profile,
        package_manifest=manifest,
        workbook=workbook,
    )

    assert queue["summary"]["total_items"] == 1
    item = queue["items"][0]
    assert item["review_state"] == "PENDING"

    decision = make_decision(
        "UNMERGE_RANGE",
        parameters={"sheet": "63KV SS", "target": "B9:X10"},
        reason="This merge should not cross the middle line.",
    )
    apply_decision_to_queue(queue, item["review_id"], decision)

    assert item["review_state"] == "RESOLVED"
    assert item["decision"]["execution_kind"] == "WORKBOOK_CHANGE"
    assert item["decision"]["execution_state"] == "PENDING"


def test_known_exception_is_still_reviewable():
    report = {
        "run_id": "run_2",
        "kind": "azd_mline",
        "script_id": "AZD_M_LINE",
        "findings": [
            {
                "test_id": "M_LINE",
                "status": "KNOWN_EXCEPTION",
                "severity": "INFO",
                "sheet": "230KV SS",
                "target": "A15:AA16",
                "message": "Known exception",
                "expected": None,
                "observed": None,
                "evidence": {"rows": [15, 16]},
                "suggested_exception": None,
            }
        ],
    }
    queue = build_review_queue(
        report=report,
        profile={"schema_version":"0.3","family":"GENERAL_DOCUMENT","profile_name":"AZD"},
        package_manifest={"package_id":"cleaner_functions","version":"0.4.0","review_schema":"0.1","decision_schema":"0.1"},
        workbook={"name":"AZD.xlsx","path":"x","saved_state":"unsaved"},
    )
    item = queue["items"][0]

    assert item["current_policy"]["state"] == "CURRENTLY_ACCEPTED_BY_PROFILE"
    actions = {x["action"] for x in item["allowed_actions"]}
    assert "ACCEPT_EXCEPTION" in actions
    assert "UNMERGE_RANGE" in actions
    assert "PROFILE_CHANGE" in actions
