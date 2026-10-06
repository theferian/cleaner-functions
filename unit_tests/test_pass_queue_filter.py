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
