from cleaner_core.knowledge import (
    decision_from_known_policy,
    promote_decisions_to_profile,
)
from review.queue import finding_to_review_item


def identifier_decisions():
    return {
        "run": {"run_id": "run_week_1", "script_id": "IDENTIFIERS"},
        "decisions": [
            {
                "review_id": "id1",
                "source": {
                    "test_id": "IDENTIFIERS",
                    "status": "FAIL",
                    "severity": "HIGH",
                },
                "location": {"sheet": "230KV SS", "target": "C9"},
                "decision": {
                    "action": "SET_VALUE",
                    "parameters": {
                        "sheet": "230KV SS",
                        "target": "C9",
                        "value": "1.2.3.1000",
                    },
                    "reason": "accepted generated WBS",
                },
            }
        ],
    }


def test_identifier_promotion_uses_current_machine_suggestion():
    profile = {
        "profile_name": "AZD",
        "known_exceptions": [],
        "known_fixes": [],
    }
    updated, report = promote_decisions_to_profile(profile, identifier_decisions())

    assert report["promoted_fix_count"] == 1
    fix = updated["known_fixes"][0]
    assert fix["resolution"]["mode"] == "CURRENT_MACHINE_SUGGESTION"
    assert fix["match"] == {
        "test_id": "IDENTIFIERS",
        "sheet": "230KV SS",
        "target": "C9",
        "status": "FAIL",
    }

    # Week 2 produces a different context-dependent WBS. The reusable policy
    # must use this new suggestion, not last week's 1.2.3.1000.
    finding = {
        "test_id": "IDENTIFIERS",
        "status": "FAIL",
        "severity": "HIGH",
        "sheet": "230KV SS",
        "target": "C9",
        "message": "bad WBS",
        "suggested_fix": {
            "action": "SET_VALUE",
            "parameters": {
                "sheet": "230KV SS",
                "target": "C9",
                "value": "9.8.7.1000",
            },
            "reason": "current workbook suggestion",
        },
    }
    item = finding_to_review_item(finding, updated)
    assert item["current_policy"]["state"] == "KNOWN_REUSABLE_RESOLUTION"

    decision = decision_from_known_policy(item)
    assert decision["action"] == "SET_VALUE"
    assert decision["parameters"]["value"] == "9.8.7.1000"


def test_known_exception_promotion_is_sheet_specific_and_deduplicated():
    profile = {
        "profile_name": "AZD",
        "known_exceptions": [
            {
                "id": "global",
                "enabled": True,
                "match": {
                    "test_id": "M_LINE",
                    "sheet": "*",
                    "rows": [15, 16],
                },
            }
        ],
        "known_fixes": [],
    }
    payload = {
        "run": {"run_id": "run_week_1", "script_id": "M_LINE"},
        "decisions": [
            {
                "review_id": "e1",
                "source": {"test_id": "M_LINE", "status": "KNOWN_EXCEPTION"},
                "location": {"sheet": "230KV SS", "target": "A15:AA16"},
                "decision": {
                    "action": "ACCEPT_EXCEPTION",
                    "parameters": {
                        "test_id": "M_LINE",
                        "sheet": "230KV SS",
                        "target": "A15:AA16",
                        "rows": [15, 16],
                    },
                },
            },
            {
                "review_id": "e2",
                "source": {"test_id": "M_LINE", "status": "POSSIBLE_EXCEPTION"},
                "location": {"sheet": "63KV SS", "target": "A47:X48"},
                "decision": {
                    "action": "ACCEPT_EXCEPTION",
                    "parameters": {
                        "test_id": "M_LINE",
                        "sheet": "63KV SS",
                        "target": "A47:X48",
                        "rows": [47, 48],
                    },
                },
            },
        ],
    }

    updated, report = promote_decisions_to_profile(profile, payload)
    assert report["promoted_exception_count"] == 1
    assert report["skipped_count"] == 1
    promoted = next(x for x in updated["known_exceptions"] if x["id"].startswith("PROMOTED_EXCEPTION"))
    assert promoted["match"]["sheet"] == "63KV SS"
    assert promoted["match"]["rows"] == [47, 48]
