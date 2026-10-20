from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import json

from cleaner_core.general_doc_auto_wbs import accept_general_document_wbs
from cleaner_core.state import ingest_review_decisions_file, new_resolved_state
from review.decisions import write_decisions_file


def profile(family="GENERAL_DOCUMENT", strategy="NEAREST_VALID_ABOVE_APPEND_SEQUENCE"):
    return {"family": family, "data_model": {"family_fields": [
        {"key": "wbs", "cleaning": {"strategy": strategy}},
    ]}}


def item(target="C71", value="1.2.3.1000", observed=None, key="wbs", parent="1.2.3"):
    return {
        "review_id": f"IDENTIFIERS_Sheet_{target}", "review_state": "PENDING",
        "source": {"test_id": "IDENTIFIERS", "status": "FAIL"},
        "location": {"sheet": "Sheet", "target": target},
        "observed": observed,
        "evidence": {"field_key": key, "nearest_valid_wbs_above": parent},
        "machine_suggestion": {"suggested_fix": {
            "action": "SET_VALUE", "parameters": {
                "field_key": key, "sheet": "Sheet", "target": target,
                "value": value, "expected_old_value": observed,
            }, "reason": "Nearest valid WBS above + sequence."}},
    }


def queue(*items):
    return {"run": {"script_id": "IDENTIFIERS"},
            "summary": {"total_items": len(items), "pending_review": len(items)},
            "items": list(items)}


def test_auto_accepts_missing_wbs_and_preserves_audit_overlay(tmp_path):
    q = queue(item("D71", "1.2.3.1000"), item("D73", "1.2.3.1001"))
    assert accept_general_document_wbs(q, profile(), {"1.2.3"}) == 2
    assert q["summary"]["pending_review"] == 0
    assert q["summary"]["resolved"] == 2
    assert all(x["decision"]["origin"] == "GENERAL_DOCUMENT_AUTO_WBS_V1" for x in q["items"])
    assert all(x["decision"]["reviewer"] == "GENERAL_DOCUMENT_FAMILY_POLICY" for x in q["items"])
    path = tmp_path / "decisions.json"
    q.update({"run": {"script_id": "IDENTIFIERS", "run_id": "test"}})
    write_decisions_file(q, path)
    state = new_resolved_state(run_id="test", profile_name="EYV")
    ingest_review_decisions_file(state, path)
    assert state["stages"]["IDENTIFIERS"]["status"] == "REVIEWED"
    assert state["value_overrides"]["SHEET!D71"]["value"] == "1.2.3.1000"
    assert len(state["decision_audit"]) == 2


def test_does_not_accept_nonempty_invalid_wbs_or_root_fallback():
    q = queue(item("D71", observed="1.2.??"), item("D73", value="1000", parent=""))
    assert accept_general_document_wbs(q, profile(), set()) == 0
    assert q["summary"]["pending_review"] == 2


def test_does_not_accept_when_existing_wbs_or_two_suggestions_collide():
    q = queue(item("C71"), item("C73"))
    assert accept_general_document_wbs(q, profile(), {"1.2.3"}) == 1
    assert q["summary"]["pending_review"] == 1
    q2 = queue(item())
    assert accept_general_document_wbs(q2, profile(), {"1.2.3.1000"}) == 0


def test_does_not_accept_other_family_or_disabled_strategy():
    for prof in (profile("WEEKLY_REPORT_TEMPLATE"), profile(strategy="MANUAL")):
        q = queue(item())
        assert accept_general_document_wbs(q, prof, set()) == 0
        assert q["items"][0]["review_state"] == "PENDING"


def test_does_not_accept_other_identifier_fields_or_wrong_target():
    x = item(key="code")
    y = item(target="C73")
    y["machine_suggestion"]["suggested_fix"]["parameters"]["target"] = "C74"
    q = queue(x, y)
    assert accept_general_document_wbs(q, profile(), set()) == 0


def test_does_not_accept_partial_or_unvalidated_wbs():
    q = queue(item(value="1.2.3.999"), item("C73",value="1.2.3.1000",parent="NaN"))
    assert accept_general_document_wbs(q, profile(), set()) == 0


def test_numeric_zero_is_not_treated_as_empty():
    q = queue(item(observed=0))
    assert accept_general_document_wbs(q, profile(), set()) == 0


def test_manual_override_remains_possible():
    q = queue(item())
    assert accept_general_document_wbs(q, profile(), set()) == 1
    q["items"][0]["review_state"] = "PENDING"
    q["items"][0]["decision"] = None
    assert q["items"][0]["decision"] is None
