from cleaner_core.exceptions import (
    new_exception_registry,
    sync_registry_from_decisions_payload,
    reconcile_stage_findings,
    case_for_finding,
)


def _decision_payload(action="DEFER", reason="investigate chronology"):
    return {
        "run": {"run_id": "azd_test_run", "script_id": "FIELD_VALIDATION"},
        "decisions": [
            {
                "review_id": "FIELD_VALIDATION_230KV_SS_N21_x",
                "source": {
                    "kind": "TEST_FINDING",
                    "test_id": "FIELD_VALIDATION",
                    "status": "FAIL",
                    "severity": "MEDIUM",
                },
                "location": {"sheet": "230KV SS", "target": "N21"},
                "message": "Receive date precedes send date.",
                "evidence": {
                    "audit_kind": "DATE_CHRONOLOGY",
                    "field_role": "receive_date",
                    "send_target": "M21",
                },
                "decision": {
                    "action": action,
                    "parameters": {},
                    "reason": reason,
                    "decided_at": "2026-10-06T01:00:00",
                },
            }
        ],
    }


def _finding():
    return {
        "test_id": "FIELD_VALIDATION",
        "status": "FAIL",
        "severity": "MEDIUM",
        "sheet": "230KV SS",
        "target": "N21",
        "message": "Receive date precedes send date.",
        "evidence": {
            "audit_kind": "DATE_CHRONOLOGY",
            "field_role": "receive_date",
            "send_target": "M21",
        },
    }


def test_defer_creates_human_tracked_exception_case():
    registry = new_exception_registry("AZD")
    report = sync_registry_from_decisions_payload(registry, _decision_payload())

    assert report["updated_handles"] == ["AZD-EXC-0001"]
    case = registry["cases"][0]
    assert case["handle"] == "AZD-EXC-0001"
    assert case["case_state"] == "OPEN"
    assert case["workflow_status"] == "INVESTIGATE"
    assert case["note"] == "investigate chronology"
    assert "date_chronology" in case["tags"]
    assert "investigate" in case["tags"]


def test_same_exception_review_updates_same_handle_not_duplicate():
    registry = new_exception_registry("AZD")
    sync_registry_from_decisions_payload(registry, _decision_payload())
    second = _decision_payload(reason="still needs investigation")
    second["run"]["run_id"] = "azd_test_run_2"
    sync_registry_from_decisions_payload(registry, second)

    assert len(registry["cases"]) == 1
    assert registry["cases"][0]["handle"] == "AZD-EXC-0001"
    assert registry["cases"][0]["note"] == "still needs investigation"


def test_tracked_exception_is_linked_when_finding_reappears():
    registry = new_exception_registry("AZD")
    sync_registry_from_decisions_payload(registry, _decision_payload())

    case = case_for_finding(registry, _finding())
    assert case is not None
    assert case["handle"] == "AZD-EXC-0001"


def test_open_exception_auto_resolves_when_stage_no_longer_detects_it():
    registry = new_exception_registry("AZD")
    sync_registry_from_decisions_payload(registry, _decision_payload())

    report = reconcile_stage_findings(
        registry,
        [],
        stage_id="FIELD_VALIDATION",
        run_id="azd_clean_run",
    )

    assert report["auto_resolved_cases"] == 1
    case = registry["cases"][0]
    assert case["case_state"] == "RESOLVED"
    assert case["workflow_status"] == "NO_LONGER_DETECTED"


def test_accept_exception_is_tracked_separately_from_open_anomaly():
    registry = new_exception_registry("AZD")
    sync_registry_from_decisions_payload(
        registry,
        _decision_payload(action="ACCEPT_EXCEPTION", reason="legitimate business exception"),
    )

    case = registry["cases"][0]
    assert case["case_state"] == "ACCEPTED"
    assert case["workflow_status"] == "KNOWN_ACCEPTED"
    assert case["classification"] == "ACCEPTED_EXCEPTION"


def test_reusable_profile_decision_does_not_create_exception_case():
    registry = new_exception_registry("AZD")
    payload = _decision_payload(action="ACCEPT_EXCEPTION", reason="known geometry")
    payload["decisions"][0]["decision"]["origin"] = "REUSABLE_PROFILE"

    report = sync_registry_from_decisions_payload(registry, payload)

    assert registry["cases"] == []
    assert report["updated_handles"] == []
    assert report["ignored_reusable_profile_decisions"] == 1


def test_profile_covered_accepted_case_is_retired_not_deleted():
    from cleaner_core.exceptions import retire_profile_covered_cases

    registry = new_exception_registry("AZD")
    payload = {
        "run": {"run_id": "azd_old"},
        "decisions": [
            {
                "review_id": "M_LINE_230KV_SS_A15_AA16_x",
                "source": {"test_id": "M_LINE", "status": "FAIL", "severity": "INFO"},
                "location": {"sheet": "230KV SS", "target": "A15:AA16"},
                "evidence": {},
                "decision": {
                    "action": "ACCEPT_EXCEPTION",
                    "parameters": {},
                    "reason": "old duplicate case",
                },
            }
        ],
    }
    sync_registry_from_decisions_payload(registry, payload)
    handle = registry["cases"][0]["handle"]
    profile = {
        "known_exceptions": [
            {
                "id": "AZD_MLINE_CATEGORY_TYPE_BOUNDARY",
                "enabled": True,
                "match": {
                    "test_id": "M_LINE",
                    "sheet": "*",
                    "rows": [15, 16, 129, 130],
                },
            }
        ]
    }

    report = retire_profile_covered_cases(registry, profile)

    assert report["retired_handles"] == [handle]
    assert len(registry["cases"]) == 1
    case = registry["cases"][0]
    assert case["case_state"] == "RESOLVED"
    assert case["workflow_status"] == "SUPERSEDED_BY_PROFILE"
    assert case["profile_rule_id"] == "AZD_MLINE_CATEGORY_TYPE_BOUNDARY"


def test_profile_superseded_case_stays_retired_when_finding_reappears():
    from cleaner_core.exceptions import retire_profile_covered_cases

    registry = new_exception_registry("AZD")
    payload = {
        "run": {"run_id": "azd_old"},
        "decisions": [
            {
                "review_id": "M_LINE_230KV_SS_A15_AA16_x",
                "source": {"test_id": "M_LINE", "status": "FAIL", "severity": "INFO"},
                "location": {"sheet": "230KV SS", "target": "A15:AA16"},
                "evidence": {},
                "decision": {
                    "action": "ACCEPT_EXCEPTION",
                    "parameters": {},
                    "reason": "legacy duplicate of profile knowledge",
                },
            }
        ],
    }
    sync_registry_from_decisions_payload(registry, payload)
    profile = {
        "known_exceptions": [
            {
                "id": "AZD_MLINE_CATEGORY_TYPE_BOUNDARY",
                "enabled": True,
                "match": {
                    "test_id": "M_LINE",
                    "sheet": "230KV SS",
                    "target": "A15:AA16",
                },
            }
        ]
    }
    retire_profile_covered_cases(registry, profile)

    finding = {
        "test_id": "M_LINE",
        "status": "FAIL",
        "severity": "INFO",
        "sheet": "230KV SS",
        "target": "A15:AA16",
        "message": "Known AZD M-line exception.",
        "evidence": {},
    }
    report = reconcile_stage_findings(
        registry,
        [finding],
        stage_id="M_LINE",
        run_id="azd_fresh_run",
    )

    assert report["detected_open_cases"] == 0
    assert report["auto_resolved_cases"] == 0
    case = registry["cases"][0]
    assert case["case_state"] == "RESOLVED"
    assert case["workflow_status"] == "SUPERSEDED_BY_PROFILE"
    assert case["classification"] == "PROFILE_KNOWN_EXCEPTION"
    assert case_for_finding(registry, finding) is None
