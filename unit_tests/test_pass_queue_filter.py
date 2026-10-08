from review.queue import build_review_queue


def test_pass_findings_are_not_human_review_items():
    report = {
        "run_id": "r1",
        "script_id": "X",
        "kind": "test",
        "findings": [
            {"test_id": "X", "status": "PASS", "severity": "INFO", "message": "ok"},
            {"test_id": "X", "status": "FAIL", "severity": "HIGH", "message": "bad", "sheet": "S", "target": "A1"},
        ],
    }
    queue = build_review_queue(
        report=report,
        profile={"profile_name": "AZD"},
        package_manifest={},
        workbook={},
    )
    assert queue["summary"]["total_items"] == 1
    assert queue["items"][0]["source"]["status"] == "FAIL"


def test_date_chronology_finding_is_not_a_human_review_item():
    report = {
        "run_id": "r1",
        "script_id": "FIELD_VALIDATION",
        "kind": "test",
        "findings": [
            {
                "test_id": "FIELD_VALIDATION",
                "status": "FAIL",
                "severity": "MEDIUM",
                "message": "Receive date precedes send date.",
                "sheet": "230KV SS",
                "target": "N21",
                "evidence": {
                    "audit_kind": "DATE_CHRONOLOGY",
                    "field_role": "receive_date",
                    "send_target": "M21",
                    "send_date": "1404/08/11",
                    "receive_date": "1404/08/10",
                },
            }
        ],
    }

    queue = build_review_queue(
        report=report,
        profile={"profile_name": "AZD"},
        package_manifest={},
        workbook={},
    )

    assert queue["summary"]["total_items"] == 0
    assert queue["items"] == []
