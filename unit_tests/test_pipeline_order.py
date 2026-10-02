import pytest

from pipeline.azd_pipeline import assert_stage_allowed


def test_boundaries_wait_for_mline_review():
    state = {"stages": {"M_LINE": {"status": "AWAITING_REVIEW"}}}
    with pytest.raises(RuntimeError):
        assert_stage_allowed(state, "DOCUMENT_BOUNDARIES")


def test_boundaries_allowed_after_mline_review():
    state = {"stages": {"M_LINE": {"status": "REVIEWED"}}}
    assert_stage_allowed(state, "DOCUMENT_BOUNDARIES")


def test_card_map_waits_for_boundary_review():
    state = {"stages": {"M_LINE": {"status": "REVIEWED"}, "DOCUMENT_BOUNDARIES": {"status": "AWAITING_REVIEW"}}}
    with pytest.raises(RuntimeError):
        assert_stage_allowed(state, "CARD_MAP")


def test_card_map_allowed_after_boundary_review():
    state = {"stages": {"M_LINE": {"status": "REVIEWED"}, "DOCUMENT_BOUNDARIES": {"status": "REVIEWED"}}}
    assert_stage_allowed(state, "CARD_MAP")


def test_identifiers_wait_for_card_map_review():
    state = {"stages": {"M_LINE": {"status": "REVIEWED"}, "DOCUMENT_BOUNDARIES": {"status": "REVIEWED"}, "CARD_MAP": {"status": "AWAITING_REVIEW"}}}
    with pytest.raises(RuntimeError):
        assert_stage_allowed(state, "IDENTIFIERS")


def test_identifiers_allowed_after_card_map_review():
    state = {"stages": {"M_LINE": {"status": "REVIEWED"}, "DOCUMENT_BOUNDARIES": {"status": "REVIEWED"}, "CARD_MAP": {"status": "REVIEWED"}}}
    assert_stage_allowed(state, "IDENTIFIERS")
