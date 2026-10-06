from copy import deepcopy

from cleaner_core.knowledge import decision_from_known_policy
from cleaner_core.solutions import (
    new_registry,
    sync_project_solutions_from_decisions_payload,
    match_project_solution,
    repair_project_solutions_registry,
)
from review.queue import finding_to_review_item


def _decision_payload(target="C9", name="Transformer Schedule"):
    return {
        "run": {"run_id": "azd_week_1"},
        "profile": {"profile_name": "AZD"},
        "decisions": [
            {
                "review_id": "IDENTIFIERS_230KV_SS_C9_old",
                "source": {"test_id": "IDENTIFIERS", "status": "FAIL", "severity": "HIGH"},
                "location": {"sheet": "230KV SS", "target": target},
                "message": "bad WBS",
                "observed": "-",
                "evidence": {
                    "field_key": "wbs",
                    "document_identity": {
                        "record_index": 4,
                        "name": name,
                        "document_type": "Drawing",
                    },
                },
                "decision": {
                    "action": "SET_VALUE",
                    "parameters": {
                        "field_key": "wbs",
                        "sheet": "230KV SS",
                        "target": target,
                        "value": "1.5.1.1000",
                    },
                    "reason": "Approved AZD WBS repair",
                    "origin": "HUMAN_REVIEW",
                },
            }
        ],
    }


def test_project_solution_follows_document_after_row_move():
    registry = new_registry("AZD")
    report = sync_project_solutions_from_decisions_payload(registry, _decision_payload())
    assert report["created_handles"] == ["AZD-SOL-0001"]

    finding = {
        "test_id": "IDENTIFIERS",
        "status": "FAIL",
        "severity": "HIGH",
        "sheet": "230KV SS",
        "target": "C27",  # moved in next weekly revision
        "message": "bad WBS again",
        "observed": "-",
        "evidence": {
            "field_key": "wbs",
            "document_identity": {
                "record_index": 12,
                "name": "Transformer Schedule",
                "document_type": "Drawing",
            },
        },
        "suggested_fix": {
            "action": "SET_VALUE",
            "parameters": {"sheet": "230KV SS", "target": "C27", "value": "9.9.9.1000"},
        },
    }

    solution = match_project_solution(registry, finding)
    assert solution is not None
    assert solution["handle"] == "AZD-SOL-0001"
    assert solution["match_mode"] == "DOCUMENT_IDENTITY"

    item = finding_to_review_item(finding, {"profile_name": "AZD", "known_fixes": []}, project_solutions=registry)
    assert item["current_policy"]["state"] == "PROJECT_SOLUTION"
    decision = decision_from_known_policy(item)
    assert decision["origin"] == "PROJECT_SOLUTION"
    assert decision["parameters"]["target"] == "C27"
    # Project-specific approved value sticks instead of recomputing a new one.
    assert decision["parameters"]["value"] == "1.5.1.1000"


def test_project_solution_does_not_follow_different_document_name():
    registry = new_registry("AZD")
    sync_project_solutions_from_decisions_payload(registry, _decision_payload())
    finding = {
        "test_id": "IDENTIFIERS",
        "status": "FAIL",
        "sheet": "230KV SS",
        "target": "C27",
        "observed": "-",
        "evidence": {
            "field_key": "wbs",
            "document_identity": {"name": "Different Document", "document_type": "Drawing"},
        },
    }
    assert match_project_solution(registry, finding) is None


def test_solution_sync_is_idempotent_for_same_review_event():
    registry = new_registry("AZD")
    payload = _decision_payload()
    sync_project_solutions_from_decisions_payload(registry, payload)
    sync_project_solutions_from_decisions_payload(registry, payload)
    assert len(registry["solutions"]) == 1
    assert registry["solutions"][0]["times_confirmed"] == 1


def test_target_fallback_supports_legacy_or_contextless_solution():
    registry = new_registry("AZD")
    payload = _decision_payload(target="H13", name="")
    # Remove durable identity to simulate an old/contextless decision.
    payload["decisions"][0]["evidence"]["document_identity"] = {}
    sync_project_solutions_from_decisions_payload(registry, payload)
    finding = {
        "test_id": "IDENTIFIERS",
        "status": "FAIL",
        "sheet": "230KV SS",
        "target": "H13",
        "observed": "-",
        "evidence": {"field_key": "wbs", "document_identity": {}},
    }
    solution = match_project_solution(registry, finding)
    assert solution is not None
    assert solution["match_mode"] == "TARGET_FALLBACK"


def test_existing_target_only_solution_is_enriched_after_project_solution_reuse():
    registry = new_registry("AZD")
    payload = _decision_payload(target="H13", name="")
    payload["decisions"][0]["evidence"]["document_identity"] = {}
    sync_project_solutions_from_decisions_payload(registry, payload)
    handle = registry["solutions"][0]["handle"]
    assert registry["solutions"][0]["match"]["document_identity"] == {}

    later = _decision_payload(target="H13", name="Cable Schedule")
    later["run"]["run_id"] = "azd_week_2"
    later_decision = later["decisions"][0]["decision"]
    later_decision["origin"] = "PROJECT_SOLUTION"
    later_decision["project_solution_handle"] = handle
    sync_project_solutions_from_decisions_payload(registry, later)

    assert len(registry["solutions"]) == 1
    assert registry["solutions"][0]["handle"] == handle
    assert registry["solutions"][0]["match"]["document_identity"]["name"] == "Cable Schedule"


def test_contextless_solutions_on_different_targets_do_not_collapse():
    registry = new_registry("AZD")
    one = _decision_payload(target="H13", name="")
    one["decisions"][0]["evidence"]["document_identity"] = {}
    one["decisions"][0]["observed"] = "140/08/10"
    one["decisions"][0]["decision"]["parameters"] = {
        "sheet": "63KV SS", "target": "H13", "value": "1404/08/10"
    }
    two = deepcopy(one)
    two["decisions"][0]["review_id"] = "FIELD_VALIDATION_63KV_SS_D23_old"
    two["decisions"][0]["location"] = {"sheet": "63KV SS", "target": "D23"}
    two["decisions"][0]["observed"] = "1404/010/20"
    two["decisions"][0]["decision"]["parameters"] = {
        "sheet": "63KV SS", "target": "D23", "value": "1404/10/20"
    }
    one["decisions"][0]["source"]["test_id"] = "FIELD_VALIDATION"
    two["decisions"][0]["source"]["test_id"] = "FIELD_VALIDATION"

    r1 = sync_project_solutions_from_decisions_payload(registry, one)
    r2 = sync_project_solutions_from_decisions_payload(registry, two)

    assert len(registry["solutions"]) == 2
    assert len(r1["created_handles"]) == 1
    assert len(r2["created_handles"]) == 1
    assert {x["match"]["target_fallback"] for x in registry["solutions"]} == {"H13", "D23"}


def test_field_key_alias_does_not_block_explanation_solution_match():
    registry = new_registry("AZD")
    payload = {
        "run": {"run_id": "week1"},
        "profile": {"profile_name": "AZD"},
        "decisions": [{
            "review_id": "r1",
            "source": {"test_id": "FIELD_VALIDATION", "status": "FAIL"},
            "location": {"sheet": "230KV SS", "target": "H11:H12"},
            "observed": "note 04/06/03",
            "evidence": {
                "field_role": "explanation",
                "audit_kind": "EXPLANATION_DATE",
                "document_relative_target": "H+0:H+1",
                "document_identity": {"name": "PROJECT CHART"},
            },
            "decision": {
                "action": "SET_VALUE",
                "parameters": {
                    "sheet": "230KV SS",
                    "target": "H11:H12",
                    "value": "note 1404/06/03",
                    "field_key": "explanation",
                },
            },
        }],
    }
    sync_project_solutions_from_decisions_payload(registry, payload)
    semantic = registry["solutions"][0]["match"]["semantic"]
    assert "field_key" not in semantic
    assert semantic["field_role"] == "explanation"

    finding = {
        "test_id": "FIELD_VALIDATION",
        "status": "FAIL",
        "sheet": "230KV SS",
        "target": "H31:H32",
        "observed": "note 04/06/03",
        "evidence": {
            "field_role": "explanation",
            "audit_kind": "EXPLANATION_DATE",
            "document_relative_target": "H+0:H+1",
            "document_identity": {"name": "PROJECT CHART"},
        },
    }
    assert match_project_solution(registry, finding) is not None


def test_project_solution_can_match_moved_row_using_relative_target():
    registry = new_registry("AZD")
    payload = {
        "run": {"run_id": "week1"},
        "profile": {"profile_name": "AZD"},
        "decisions": [{
            "review_id": "r1",
            "source": {"test_id": "FIELD_VALIDATION", "status": "FAIL"},
            "location": {"sheet": "230KV SS", "target": "E19:E22"},
            "observed": "جلسه مورخ 04/02/22",
            "evidence": {
                "field_role": "explanation",
                "audit_kind": "EXPLANATION_DATE",
                "document_relative_target": "E+0:E+3",
                "document_identity": {"name": "PROT & CONTROL SINGLE LINE DIAGRAM"},
            },
            "decision": {
                "action": "SET_VALUE",
                "parameters": {
                    "sheet": "230KV SS", "target": "E19:E22",
                    "value": "جلسه مورخ 1404/02/22",
                },
            },
        }],
    }
    sync_project_solutions_from_decisions_payload(registry, payload)
    moved = {
        "test_id": "FIELD_VALIDATION",
        "status": "FAIL",
        "sheet": "230KV SS",
        "target": "E41:E44",
        "observed": "جلسه مورخ 04/02/22",
        "evidence": {
            "field_role": "explanation",
            "audit_kind": "EXPLANATION_DATE",
            "document_relative_target": "E+0:E+3",
            "document_identity": {"name": "PROT & CONTROL SINGLE LINE DIAGRAM"},
        },
    }
    solution = match_project_solution(registry, moved)
    assert solution is not None
    assert solution["match_mode"] == "DOCUMENT_IDENTITY"


def test_repair_splits_legacy_collision_and_supersedes_duplicate():
    registry = new_registry("AZD")
    legacy = {
        "run": {"run_id": "old"},
        "profile": {"profile_name": "AZD"},
        "decisions": [{
            "review_id": "h11-old",
            "source": {"test_id": "FIELD_VALIDATION", "status": "FAIL"},
            "location": {"sheet": "230KV SS", "target": "H11:H12"},
            "message": "Explanation at 230KV SS!H11:H12 contains date; observed='note 04/06/03'.",
            "observed": "note 04/06/03",
            "evidence": {"field_role": "explanation", "audit_kind": "EXPLANATION_DATE"},
            "decision": {
                "action": "SET_VALUE",
                "parameters": {"sheet": "230KV SS", "target": "H11:H12", "value": "note 1404/06/03"},
            },
        }],
    }
    sync_project_solutions_from_decisions_payload(registry, legacy)
    collided = registry["solutions"][0]
    collided["history"].append({
        "at": "old",
        "resolution": deepcopy(collided["resolution"]),
        "reason": collided["reason"],
        "source": deepcopy(collided["source"]),
    })
    # Simulate the historical signature-collision bug: H11 match but E19 resolution.
    collided["resolution"] = {
        "mode": "PROJECT_DECISION_TEMPLATE",
        "action": "SET_VALUE",
        "parameters": {"sheet": "230KV SS", "target": "E19:E22", "value": "meeting 1404/02/22"},
    }
    collided["reason"] = (
        "Explanation at 230KV SS!E19:E22 contains non-canonical embedded Jalali dates; "
        "observed='meeting 04/02/22'."
    )

    rich = deepcopy(legacy)
    rich["run"]["run_id"] = "new"
    rich["decisions"][0]["review_id"] = "h11-rich"
    rich["decisions"][0]["evidence"]["document_identity"] = {"name": "PROJECT CHART"}
    rich["decisions"][0]["evidence"]["document_relative_target"] = "H+0:H+1"
    sync_project_solutions_from_decisions_payload(registry, rich)
    assert len([x for x in registry["solutions"] if x.get("enabled", True)]) == 2

    regions = {
        "sheets": {
            "230KV SS": {
                "regions": [
                    {"start_row": 11, "end_row": 14, "fields": {"name": {"value": "PROJECT CHART"}}},
                    {"start_row": 19, "end_row": 22, "fields": {"name": {"value": "PROT & CONTROL SINGLE LINE DIAGRAM"}}},
                ]
            }
        }
    }
    report = repair_project_solutions_registry(registry, document_regions_payload=regions)
    active = [x for x in registry["solutions"] if x.get("enabled", True)]
    assert report["active_count"] == 2
    assert len(active) == 2
    assert {x["match"]["target_fallback"] for x in active} == {"H11:H12", "E19:E22"}
    names = {x["match"]["target_fallback"]: x["match"]["document_identity"].get("name") for x in active}
    assert names["H11:H12"] == "PROJECT CHART"
    assert names["E19:E22"] == "PROT & CONTROL SINGLE LINE DIAGRAM"
    assert report["split_created_handles"]
    assert report["superseded_handles"]
