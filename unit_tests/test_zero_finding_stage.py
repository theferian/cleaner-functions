from cleaner_core.state import new_resolved_state, mark_stage_run


def test_zero_finding_stage_is_auto_reviewed():
    state = new_resolved_state(run_id="r1", profile_name="AZD", workbook={})
    mark_stage_run(state, "CARD_MAP", finding_count=0)
    assert state["stages"]["CARD_MAP"]["status"] == "REVIEWED"
    assert state["stages"]["CARD_MAP"]["auto_reviewed"] is True


def test_stage_with_findings_still_waits_for_review():
    state = new_resolved_state(run_id="r1", profile_name="AZD", workbook={})
    mark_stage_run(state, "CARD_MAP", finding_count=1)
    assert state["stages"]["CARD_MAP"]["status"] == "AWAITING_REVIEW"
