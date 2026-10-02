import pytest

from pipeline.azd_pipeline import assert_stage_allowed


def test_identifiers_wait_for_mline_review():
    state = {"stages": {"M_LINE": {"status": "AWAITING_REVIEW"}}}
    with pytest.raises(RuntimeError):
        assert_stage_allowed(state, "IDENTIFIERS")


def test_identifiers_allowed_after_mline_review():
    state = {"stages": {"M_LINE": {"status": "REVIEWED"}}}
    assert_stage_allowed(state, "IDENTIFIERS")
