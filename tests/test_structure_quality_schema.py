from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from functions.cleaner.structure_quality_schema import export_structure_quality_schema


def _write_json(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _fixture(tmp_path: Path):
    root = tmp_path / "repo"
    run = root / "runs" / "azd_test_run"
    profile = root / "profiles" / "AZD.profile.json"
    workbook = root / "approved.xlsx"
    workbook.parent.mkdir(parents=True, exist_ok=True)
    workbook.write_bytes(b"approved-azd-source")
    source_hash = hashlib.sha256(workbook.read_bytes()).hexdigest()

    _write_json(profile, {
        "schema_version": "0.4",
        "family": "GENERAL_DOCUMENT",
        "profile_name": "AZD",
        "workbook": {"expected_sheets": ["230KV SS"]},
        "known_exceptions": [{"id": "E1"}],
        "known_fixes": [{"id": "F1"}],
        "data_model": {
            "family_fields": [
                {"key": "name", "label": "Name", "data_type": "TEXT", "required": True, "validation": {"kind": "NON_EMPTY"}, "cleaning": {}},
                {"key": "wbs", "label": "WBS", "data_type": "WBS", "required": True, "validation": {"kind": "REGEX", "pattern": r"^\\d+(?:\\.\\d+)*$"}, "cleaning": {}},
            ],
            "instances": {"230KV SS": {"instance_type": "SHEET", "field_map": {"name": {"kind": "COLUMN", "column": 2}, "wbs": {"kind": "COLUMN", "column": 3}}}},
            "document_boundaries": {"first_data_row": 3},
            "field_validation": {
                "receive_status_relation": {"rule": "RECEIVE_DATE_REQUIRES_STATUS_IN_SAME_TRANSACTION_EVENT"},
                "date_chronology": {"rule": "RECEIVE_DATE_ON_OR_AFTER_SEND_DATE_IN_SAME_TRANSACTION_EVENT"},
            },
        },
    })
    _write_json(run / "run_manifest.json", {
        "schema": "cleaner.run_manifest/0.1",
        "run_id": "azd_test_run",
        "profile_name": "AZD",
        "profile_path": str(profile),
        "workbook": {"name": workbook.name, "path": str(workbook), "saved_state": "saved"},
        "exception_registry": str(root / "exceptions" / "AZD.exceptions.json"),
        "project_solutions": str(root / "project_solutions" / "AZD.solutions.json"),
    })
    stages = {
        stage: {"status": "REVIEWED", "finding_count": 0, "decision_count": 0, "auto_reviewed": True}
        for stage in ("M_LINE", "DOCUMENT_BOUNDARIES", "CARD_MAP", "SLOT_SCHEMA", "FIELD_VALIDATION", "IDENTIFIERS")
    }
    _write_json(run / "resolved_state.json", {
        "schema": "cleaner.resolved_state/0.1",
        "run_id": "azd_test_run",
        "profile_name": "AZD",
        "stages": stages,
    })
    _write_json(
        run / "document_regions.json",
        {
            "schema": "cleaner.document_regions/0.1",
            "run_id": "azd_test_run",
            "profile_name": "AZD",
            "sheets": {
                "230KV SS": {
                    "regions": [
                        {
                            "record_index": 1,
                            "anchor_row": 3,
                            "start_row": 3,
                            "end_row": 4,
                            "target": "3:4",
                            "source": "MAPPED_FIELD_ANCHORS",
                            "fields": {
                                "name": {"address": "B3", "value": "DOC", "merge": "B3:B4", "own_anchor": True},
                                "wbs": {"address": "C3", "value": "1.2.3", "merge": "C3:C4", "own_anchor": True},
                            },
                        }
                    ]
                }
            },
        },
    )
    _write_json(run / "card_maps.json", {
        "schema": "cleaner.card_map/0.1",
        "sheets": {"230KV SS": {"data_start_col": 4, "data_end_col": 12, "cards": [{"record_index": 1, "data_range": "D3:L4"}]}}
    })
    _write_json(run / "slot_schema.json", {
        "schema": "cleaner.slot_schema/0.1",
        "sheets": {"230KV SS": {"block_width": 3, "block_confidence": 1.0, "block_source": "SEMANTIC_ANCHOR_SPACING", "roles_by_offset": {"0": "send_date", "1": "receive_date", "2": "status"}, "role_confidence_by_offset": {"0": 1.0, "1": 1.0, "2": 1.0}, "columns": [{"column": 4, "letter": "D", "headers": ["send"], "semantic_type": "COMPOSITE", "semantic_confidence": 1.0, "inferred_role": "send_date", "role_confidence": 1.0, "role_source": "SLOT_LANES"}]}}
    })
    _write_json(run / "coverage_audit.json", {
        "schema": "board_to_log.coverage_audit/0.1",
        "summary": {"counts": {"SCANNED_NOT_RETRIEVED": 0, "UNRESOLVED_ISSUE": 0}},
    })
    _write_json(run / "board_to_log.json", {"schema": "board_to_log.logbook/0.1", "summary": {"record_count": 2, "issue_count": 0}})
    return root, run, profile, workbook, source_hash


def test_export_structure_quality_schema_separates_quality_states(tmp_path):
    root, run, profile, workbook, source_hash = _fixture(tmp_path)
    output, payload = export_structure_quality_schema(
        run,
        project_id="AZD",
        orchestration_run_id="20261013T225747Z_4011c1bf",
        source_artifact_id="R06e86d9ebfa5",
        workbook_path=workbook,
        source_sha256=source_hash,
    )

    assert output.exists()
    assert payload["schema"] == "cleaner.document_structure_quality/0.1"
    assert payload["contract_version"] == "0.2.1"
    assert payload["identity"]["source"]["artifact_id"] == "R06e86d9ebfa5"
    assert payload["identity"]["source"]["hash_verified_against_expected"] is True
    assert payload["quality_state"] == {
        "structure_discovered": True,
        "structure_reviewed": True,
        "data_validated": True,
        "coverage_verified": True,
        "write_targets_approved": False,
    }
    assert payload["operations"]["write_targets"]["approved"] is False
    assert payload["workbook_structure"]["formulas"]["status"] == "NOT_MODELED_BY_CURRENT_CLEANER"
    sheet = payload["workbook_structure"]["sheets"][0]
    assert sheet["name"] == "230KV SS"
    assert sheet["logical_table"]["document_count"] == 1
    assert sheet["wbs_keys"][0]["value"] == "1.2.3"
    assert sheet["transaction_schema"]["block_width"] == 3
    bridge = payload["structural_bridge"]
    assert bridge["schema_version"] == "0.1.0"
    assert bridge["run_id"] == "20261013T225747Z_4011c1bf"
    assert bridge["workbooks"][0]["workbook_type"] == "GENERAL_DOCUMENT"
    assert bridge["workbooks"][0]["artifact_id"] == "R06e86d9ebfa5"
    assert bridge["workbooks"][0]["worksheets"][0]["sheet_index"] is None
    assert bridge["workbooks"][0]["worksheets"][0]["index_status"] == "NOT_CAPTURED_BY_CURRENT_CLEANER"
    assert workbook.read_bytes() == b"approved-azd-source"


def test_export_rejects_approved_hash_mismatch(tmp_path):
    root, run, profile, workbook, source_hash = _fixture(tmp_path)
    with pytest.raises(RuntimeError, match="hash mismatch"):
        export_structure_quality_schema(
            run,
            project_id="AZD",
            orchestration_run_id="run-1",
            source_artifact_id="artifact-1",
            workbook_path=workbook,
            source_sha256="0" * 64,
        )


def test_coverage_does_not_imply_write_approval(tmp_path):
    root, run, profile, workbook, source_hash = _fixture(tmp_path)
    output, payload = export_structure_quality_schema(
        run,
        project_id="AZD",
        orchestration_run_id="run-1",
        source_artifact_id="artifact-1",
        workbook_path=workbook,
    )
    assert payload["quality_state"]["coverage_verified"] is True
    assert payload["quality_state"]["write_targets_approved"] is False
    assert payload["identity"]["source"]["binding_mode"] == "COMPUTED_FROM_APPROVED_ARTIFACT"


def test_export_can_bind_external_hash_when_workbook_is_not_local(tmp_path):
    root, run, profile, workbook, source_hash = _fixture(tmp_path)
    # Remove the local source and point the manifest at a path unavailable to this machine.
    workbook.unlink()
    manifest = json.loads((run / "run_manifest.json").read_text(encoding="utf-8"))
    manifest["workbook"]["path"] = r"W:\approved\AZD.xlsx"
    _write_json(run / "run_manifest.json", manifest)

    output, payload = export_structure_quality_schema(
        run,
        project_id="AZD",
        orchestration_run_id="run-1",
        source_artifact_id="artifact-1",
        source_sha256=source_hash,
    )
    assert payload["identity"]["source"]["binding_mode"] == "EXTERNAL_APPROVED_HASH"
    assert payload["identity"]["source"]["computed_sha256"] is None
    assert payload["identity"]["source"]["sha256"] == source_hash
