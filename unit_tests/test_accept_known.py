from dev.review_findings import accept_known_resolutions, update_summary
from review.queue import build_review_queue


def test_accept_known_resolves_only_profile_covered_items():
    report = {
        "run_id": "week2",
        "kind": "azd_pipeline_stage",
        "script_id": "IDENTIFIERS",
        "findings": [
            {
                "test_id": "IDENTIFIERS",
                "status": "FAIL",
                "severity": "HIGH",
                "sheet": "230KV SS",
                "target": "C9",
                "message": "known recurring WBS",
                "suggested_fix": {
                    "action": "SET_VALUE",
                    "parameters": {
                        "sheet": "230KV SS",
                        "target": "C9",
                        "value": "1.9.1000",
                    },
                    "reason": "current suggestion",
                },
            },
            {
                "test_id": "IDENTIFIERS",
                "status": "FAIL",
                "severity": "HIGH",
                "sheet": "230KV SS",
                "target": "C11",
                "message": "new WBS problem",
                "suggested_fix": {
                    "action": "SET_VALUE",
                    "parameters": {
                        "sheet": "230KV SS",
                        "target": "C11",
                        "value": "1.9.1001",
                    },
                },
            },
        ],
    }
    profile = {
        "schema_version": "0.4",
        "family": "GENERAL_DOCUMENT",
        "profile_name": "AZD",
        "known_fixes": [
            {
                "id": "KNOWN_C9",
                "enabled": True,
                "match": {
                    "test_id": "IDENTIFIERS",
                    "sheet": "230KV SS",
                    "target": "C9",
                    "status": "FAIL",
                },
                "resolution": {
                    "mode": "CURRENT_MACHINE_SUGGESTION",
                    "expected_action": "SET_VALUE",
                },
            }
        ],
    }
    queue = build_review_queue(
        report=report,
        profile=profile,
        package_manifest={
            "package_id": "cleaner_functions",
            "version": "0.4.1",
            "review_schema": "0.1",
            "decision_schema": "0.1",
        },
        workbook={"name": "AZD.xlsx", "path": "x", "saved_state": "saved"},
    )

    count = accept_known_resolutions(queue)
    update_summary(queue)

    assert count == 1
    c9 = next(x for x in queue["items"] if x["location"]["target"] == "C9")
    c11 = next(x for x in queue["items"] if x["location"]["target"] == "C11")
    assert c9["review_state"] == "RESOLVED"
    assert c9["decision"]["parameters"]["value"] == "1.9.1000"
    assert c9["decision"]["origin"].startswith("REUSABLE_PROFILE")
    assert c11["review_state"] == "PENDING"
    assert queue["summary"]["pending_review"] == 1
