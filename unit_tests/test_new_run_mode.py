import pytest

from pipeline.azd_pipeline import assert_run_identity, resolve_run_mode


def test_new_run_requires_first_stage():
    with pytest.raises(ValueError, match="must start at M_LINE"):
        resolve_run_mode(
            stage_id="FIELD_VALIDATION",
            requested_run_id=None,
            new_run=True,
            profile_name="AZD",
        )


def test_new_run_and_run_id_are_mutually_exclusive():
    with pytest.raises(ValueError, match="mutually exclusive"):
        resolve_run_mode(
            stage_id="M_LINE",
            requested_run_id="azd_existing",
            new_run=True,
            profile_name="AZD",
        )


def test_run_mode_must_be_explicit():
    with pytest.raises(ValueError, match="Choose exactly one run mode"):
        resolve_run_mode(
            stage_id="M_LINE",
            requested_run_id=None,
            new_run=False,
            profile_name="AZD",
        )


def test_existing_run_id_continues_run():
    run_id, is_new = resolve_run_mode(
        stage_id="FIELD_VALIDATION",
        requested_run_id="azd_20261006T060000",
        new_run=False,
        profile_name="AZD",
    )
    assert run_id == "azd_20261006T060000"
    assert is_new is False


def test_new_run_generates_project_prefixed_id():
    run_id, is_new = resolve_run_mode(
        stage_id="M_LINE",
        requested_run_id=None,
        new_run=True,
        profile_name="AZD",
    )
    assert run_id.startswith("azd_")
    assert is_new is True


def test_run_identity_rejects_different_workbook():
    state = {
        "run_id": "azd_1",
        "profile_name": "AZD",
        "workbook": {"name": "old.xlsx", "path": r"C:\\data\\old.xlsx"},
    }
    with pytest.raises(RuntimeError, match="different workbook"):
        assert_run_identity(
            state,
            run_id="azd_1",
            profile_name="AZD",
            workbook={"name": "fresh.xlsx", "path": r"C:\\data\\fresh.xlsx"},
        )


def test_run_identity_accepts_same_workbook_case_insensitively():
    state = {
        "run_id": "azd_1",
        "profile_name": "AZD",
        "workbook": {"name": "AZD.XLSX", "path": r"C:\\Data\\AZD.XLSX"},
    }
    assert_run_identity(
        state,
        run_id="azd_1",
        profile_name="AZD",
        workbook={"name": "azd.xlsx", "path": r"c:\\data\\azd.xlsx"},
    )
