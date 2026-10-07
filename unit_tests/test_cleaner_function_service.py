import json
from pathlib import Path

from functions.cleaner.service import (
    confirm_reusable_status_alias,
    finalize_run,
    register_reusable_status,
)


def _write(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_finalize_run_ingests_fully_reviewed_final_stage(tmp_path):
    root = tmp_path
    run_dir = root / "runs" / "azd_final"
    run_dir.mkdir(parents=True)
    (root / "profiles").mkdir()

    _write(root / "profiles" / "AZD.profile.json", {
        "schema_version": "0.4",
        "family": "GENERAL_DOCUMENT",
        "profile_name": "AZD",
    })
    _write(run_dir / "run_manifest.json", {
        "schema": "cleaner.run_manifest/0.1",
        "run_id": "azd_final",
        "profile_name": "AZD",
        "workbook": {"name": "AZD.xlsx", "path": "C:/AZD.xlsx"},
        "exception_registry": str(root / "exceptions" / "AZD.exceptions.json"),
        "project_solutions": str(root / "project_solutions" / "AZD.solutions.json"),
    })
    _write(run_dir / "resolved_state.json", {
        "schema": "cleaner.resolved_state/0.1",
        "run_id": "azd_final",
        "profile_name": "AZD",
        "workbook": {"name": "AZD.xlsx", "path": "C:/AZD.xlsx"},
        "stages": {"IDENTIFIERS": {"status": "AWAITING_REVIEW"}},
        "value_overrides": {},
    })
    # Required Board→Log artifacts can be minimal for this service test.
    _write(run_dir / "document_regions.json", {"schema": "cleaner.document_regions/0.1", "sheets": {}})
    _write(run_dir / "card_maps.json", {"schema": "cleaner.card_map/0.1", "sheets": {}})
    _write(run_dir / "slot_schema.json", {"schema": "cleaner.slot_schema/0.1", "sheets": {}})

    decision = {
        "action": "SET_VALUE",
        "parameters": {"sheet": "230KV SS", "target": "C9", "value": "1.5.1000", "field_key": "wbs"},
        "reason": "known WBS",
        "decided_at": "2026-10-06T12:00:00",
        "execution_kind": "WORKBOOK_CHANGE",
        "execution_state": "PENDING",
    }
    _write(run_dir / "identifiers_review_queue.json", {
        "items": [{
            "review_id": "ID1",
            "review_state": "RESOLVED",
            "decision": decision,
        }]
    })
    _write(run_dir / "identifiers_review_decisions.json", {
        "schema": "cleaner.review_decisions/0.1",
        "run": {"script_id": "IDENTIFIERS", "run_id": "azd_final"},
        "decisions": [{
            "review_id": "ID1",
            "source": {"test_id": "IDENTIFIERS"},
            "location": {"sheet": "230KV SS", "target": "C9"},
            "decision": decision,
        }],
    })

    run = finalize_run(run_dir)
    state = json.loads(run.state_path.read_text(encoding="utf-8"))
    assert state["stages"]["IDENTIFIERS"]["status"] == "REVIEWED"
    assert state["value_overrides"]["230KV SS!C9"]["value"] == "1.5.1000"


def test_finalize_run_reingests_latest_decisions_even_when_stage_already_reviewed(tmp_path):
    root = tmp_path
    run_dir = root / "runs" / "azd_reviewed"
    run_dir.mkdir(parents=True)
    (root / "profiles").mkdir()

    _write(root / "profiles" / "AZD.profile.json", {
        "schema_version": "0.4",
        "family": "GENERAL_DOCUMENT",
        "profile_name": "AZD",
    })
    _write(run_dir / "run_manifest.json", {
        "schema": "cleaner.run_manifest/0.1",
        "run_id": "azd_reviewed",
        "profile_name": "AZD",
        "workbook": {"name": "AZD.xlsx", "path": "C:/AZD.xlsx"},
        "exception_registry": str(root / "exceptions" / "AZD.exceptions.json"),
        "project_solutions": str(root / "project_solutions" / "AZD.solutions.json"),
    })
    _write(run_dir / "resolved_state.json", {
        "schema": "cleaner.resolved_state/0.1",
        "run_id": "azd_reviewed",
        "profile_name": "AZD",
        "workbook": {"name": "AZD.xlsx", "path": "C:/AZD.xlsx"},
        "stages": {"FIELD_VALIDATION": {"status": "REVIEWED"}},
        "value_overrides": {},
    })
    _write(run_dir / "document_regions.json", {"schema": "cleaner.document_regions/0.1", "sheets": {}})
    _write(run_dir / "card_maps.json", {"schema": "cleaner.card_map/0.1", "sheets": {}})
    _write(run_dir / "slot_schema.json", {"schema": "cleaner.slot_schema/0.1", "sheets": {}})

    decision = {
        "action": "SET_VALUE",
        "parameters": {
            "sheet": "230KV SS",
            "target": "E165",
            "value": "1404/09/23",
            "expected_old_value": "14040/09/23",
        },
        "reason": "five-digit Jalali year typo",
        "decided_at": "2026-10-07T00:00:00",
        "execution_kind": "WORKBOOK_CHANGE",
        "execution_state": "PENDING",
    }
    _write(run_dir / "field_validation_review_queue.json", {
        "items": [{
            "review_id": "FV_E165",
            "review_state": "RESOLVED",
            "decision": decision,
        }]
    })
    _write(run_dir / "field_validation_review_decisions.json", {
        "schema": "cleaner.review_decisions/0.1",
        "run": {"script_id": "FIELD_VALIDATION", "run_id": "azd_reviewed"},
        "decisions": [{
            "review_id": "FV_E165",
            "source": {"test_id": "FIELD_VALIDATION"},
            "location": {"sheet": "230KV SS", "target": "E165"},
            "decision": decision,
        }],
    })

    run = finalize_run(run_dir)
    state = json.loads(run.state_path.read_text(encoding="utf-8"))
    assert state["stages"]["FIELD_VALIDATION"]["status"] == "REVIEWED"
    assert state["value_overrides"]["230KV SS!E165"]["value"] == "1404/09/23"

def test_status_service_can_register_canonical_and_confirm_alias(tmp_path):
    library_path = tmp_path / "status_library.json"

    registered = register_reusable_status(
        "CM",
        library_path=library_path,
        notes="Meaning pending",
    )
    assert registered["canonical"] == "CM"

    mapped = confirm_reusable_status_alias(
        "C.M",
        "CM",
        library_path=library_path,
    )
    assert mapped["alias"] == "C.M"
    assert mapped["canonical"] == "CM"

    from cleaner_core.status_library import load_status_library

    library = load_status_library(library_path)
    assert library.canonicalize("C.M") == "CM"
    assert library.definition("CM").meaning is None
