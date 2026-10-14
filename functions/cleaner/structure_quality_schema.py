from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any


SCHEMA_ID = "cleaner.document_structure_quality/0.1"
DEFAULT_CONTRACT_VERSION = "0.2.1"
STRUCTURE_STAGES = ("M_LINE", "DOCUMENT_BOUNDARIES", "CARD_MAP", "SLOT_SCHEMA")
DATA_VALIDATION_STAGES = ("FIELD_VALIDATION", "IDENTIFIERS")


def _load_json(path: Path, *, required: bool = False) -> dict[str, Any] | None:
    if not path.exists():
        if required:
            raise FileNotFoundError(path)
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_descriptor(run_dir: Path, name: str) -> dict[str, Any]:
    path = run_dir / name
    if not path.exists():
        return {
            "name": name,
            "relative_path": name,
            "exists": False,
            "schema": None,
            "sha256": None,
        }
    schema = None
    if path.suffix.lower() == ".json":
        try:
            payload = _load_json(path)
            schema = payload.get("schema") if payload else None
        except Exception:
            schema = None
    return {
        "name": name,
        "relative_path": name,
        "exists": True,
        "schema": schema,
        "sha256": _sha256_file(path),
    }


def _stage_snapshot(state: dict[str, Any], stage_id: str) -> dict[str, Any]:
    stage = (state.get("stages") or {}).get(stage_id) or {}
    return {
        "status": stage.get("status") or "NOT_RUN",
        "finding_count": int(stage.get("finding_count") or 0),
        "decision_count": int(stage.get("decision_count") or 0),
        "auto_reviewed": bool(stage.get("auto_reviewed", False)),
        "last_run_at": stage.get("last_run_at"),
        "reviewed_at": stage.get("reviewed_at"),
        "report_path": stage.get("report_path"),
        "review_queue_path": stage.get("review_queue_path"),
    }


def _stage_reviewed(state: dict[str, Any], stage_id: str) -> bool:
    return str(((state.get("stages") or {}).get(stage_id) or {}).get("status") or "").upper() == "REVIEWED"


def _profile_path(run_manifest: dict[str, Any], run_dir: Path, profile_name: str) -> Path:
    configured = str(run_manifest.get("profile_path") or "").strip()
    if configured:
        candidate = Path(configured)
        if candidate.exists():
            return candidate
    # Historical manifests can carry an absolute path from another machine.
    project_root = run_dir.resolve().parents[1]
    fallback = project_root / "profiles" / f"{profile_name}.profile.json"
    if fallback.exists():
        return fallback
    raise FileNotFoundError(
        f"Profile for {profile_name} not found. Manifest path={configured!r}; fallback={fallback}"
    )


def _resolve_source_binding(
    *,
    run_manifest: dict[str, Any],
    workbook_path: str | Path | None,
    expected_sha256: str | None,
    source_artifact_id: str,
) -> dict[str, Any]:
    manifest_workbook = run_manifest.get("workbook") or {}
    supplied = Path(workbook_path).resolve() if workbook_path else None
    if supplied is None:
        manifest_path = str(manifest_workbook.get("path") or "").strip()
        if manifest_path:
            candidate = Path(manifest_path)
            if candidate.exists():
                supplied = candidate.resolve()

    expected = str(expected_sha256 or "").strip().lower() or None
    actual = None
    verification = "EXTERNAL_APPROVED_HASH"
    verified = None
    if supplied is not None:
        if not supplied.exists():
            raise FileNotFoundError(f"Approved source workbook does not exist: {supplied}")
        actual = _sha256_file(supplied)
        verification = "COMPUTED"
        if expected:
            verified = actual.lower() == expected
            verification = "COMPUTED_AND_VERIFIED" if verified else "HASH_MISMATCH"
            if not verified:
                raise RuntimeError(
                    f"Approved source hash mismatch for {supplied}: expected {expected}, actual {actual}"
                )
        else:
            expected = actual
            verified = None
            verification = "COMPUTED_FROM_APPROVED_ARTIFACT"
    elif not expected:
        raise RuntimeError(
            "Schema export requires a source binding. Provide --workbook for read-only hashing "
            "or --source-sha256 from the approved artifact registry."
        )

    manifest_name = manifest_workbook.get("name")
    supplied_name = supplied.name if supplied is not None else None
    return {
        "artifact_id": source_artifact_id,
        "manifest_workbook_name": manifest_name,
        "workbook_name": supplied_name or manifest_name,
        "workbook_path": str(supplied) if supplied is not None else None,
        "sha256": expected,
        "computed_sha256": actual,
        "hash_verified_against_expected": verified,
        "binding_mode": verification,
        "company_original_modified": False,
    }


def _family_fields(profile: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = ((profile.get("data_model") or {}).get("family_fields") or [])
    return {str(item.get("key")): item for item in rows if item.get("key")}


def _sheet_schema(
    sheet_name: str,
    *,
    profile: dict[str, Any],
    document_regions: dict[str, Any] | None,
    card_maps: dict[str, Any] | None,
    slot_schema: dict[str, Any] | None,
) -> dict[str, Any]:
    regions_sheet = ((document_regions or {}).get("sheets") or {}).get(sheet_name) or {}
    cards_sheet = ((card_maps or {}).get("sheets") or {}).get(sheet_name) or {}
    slot_sheet = ((slot_schema or {}).get("sheets") or {}).get(sheet_name) or {}
    profile_instance = (((profile.get("data_model") or {}).get("instances") or {}).get(sheet_name) or {})
    field_map = profile_instance.get("field_map") or {}
    field_defs = _family_fields(profile)

    identifiers = []
    for key, locator in field_map.items():
        definition = field_defs.get(str(key)) or {}
        identifiers.append({
            "key": key,
            "label": definition.get("label"),
            "data_type": definition.get("data_type"),
            "required": bool(definition.get("required", False)),
            "locator": locator,
            "validation": definition.get("validation") or {},
            "cleaning": definition.get("cleaning") or {},
        })

    document_rows = []
    wbs_keys = []
    for region in regions_sheet.get("regions") or []:
        fields = region.get("fields") or {}
        document_rows.append({
            "record_index": region.get("record_index"),
            "anchor_row": region.get("anchor_row"),
            "start_row": region.get("start_row"),
            "end_row": region.get("end_row"),
            "target": region.get("target"),
            "source": region.get("source"),
            "fields": {
                key: {
                    "address": value.get("address"),
                    "value": value.get("value"),
                    "merge": value.get("merge"),
                    "own_anchor": value.get("own_anchor"),
                }
                for key, value in fields.items()
                if isinstance(value, dict)
            },
        })
        wbs = fields.get("wbs") if isinstance(fields, dict) else None
        if isinstance(wbs, dict):
            wbs_keys.append({
                "record_index": region.get("record_index"),
                "address": wbs.get("address"),
                "value": wbs.get("value"),
            })

    semantic_columns = []
    for col in slot_sheet.get("columns") or []:
        semantic_columns.append({
            "column": col.get("column"),
            "letter": col.get("letter"),
            "headers": col.get("headers") or [],
            "semantic_type": col.get("semantic_type"),
            "semantic_confidence": col.get("semantic_confidence"),
            "inferred_role": col.get("inferred_role"),
            "role_confidence": col.get("role_confidence"),
            "role_source": col.get("role_source"),
        })

    return {
        "name": sheet_name,
        "logical_table": {
            "kind": "DOCUMENT_CARD_REGION_SET",
            "document_count": len(regions_sheet.get("regions") or []),
            "first_data_row": ((profile.get("data_model") or {}).get("document_boundaries") or {}).get("first_data_row"),
            "identifier_fields": identifiers,
            "document_boundaries": document_rows,
        },
        "wbs_keys": wbs_keys,
        "data_area": {
            "start_column": cards_sheet.get("data_start_col"),
            "end_column": cards_sheet.get("data_end_col"),
            "card_count": len(cards_sheet.get("cards") or []),
            "cell_map": {
                "status": "REFERENCED_BY_RUN_ARTIFACT",
                "artifact": "card_maps.json",
                "note": "Full per-card slot addresses remain in the run-bound card map artifact; they are not duplicated here.",
            },
        },
        "transaction_schema": {
            "block_width": slot_sheet.get("block_width"),
            "block_confidence": slot_sheet.get("block_confidence"),
            "block_source": slot_sheet.get("block_source"),
            "roles_by_offset": slot_sheet.get("roles_by_offset") or {},
            "role_confidence_by_offset": slot_sheet.get("role_confidence_by_offset") or {},
            "semantic_columns": semantic_columns,
        },
        "formulas": {
            "status": "NOT_MODELED_BY_CURRENT_CLEANER",
            "ranges": [],
        },
    }



def _bridge_workbook_projection(
    *,
    project: str,
    orchestration_run_id: str,
    source_binding: dict[str, Any],
    sheets: list[dict[str, Any]],
    structure_reviewed: bool,
) -> dict[str, Any]:
    """Compatibility projection for the Chat 03 structural bridge contract.

    Sheet indexes are intentionally left null because the current Cleaner stores
    selected sheet names, not authoritative Excel workbook ordinals.
    """
    review_status = "reviewed" if structure_reviewed else "pending_review"
    worksheets = []
    regions = []
    fields = []
    for sheet in sheets:
        sheet_name = sheet.get("name")
        worksheets.append({
            "sheet_name": sheet_name,
            "sheet_index": None,
            "sheet_identity": None,
            "review_status": review_status,
            "index_status": "NOT_CAPTURED_BY_CURRENT_CLEANER",
        })
        logical = sheet.get("logical_table") or {}
        for document in logical.get("document_boundaries") or []:
            regions.append({
                "region_id": f"{sheet_name}:DOC:{document.get('record_index')}",
                "sheet_name": sheet_name,
                "sheet_index": None,
                "range_definition": {
                    "start_row": document.get("start_row"),
                    "end_row": document.get("end_row"),
                    "target": document.get("target"),
                },
                "row_boundaries": {
                    "anchor_row": document.get("anchor_row"),
                    "start_row": document.get("start_row"),
                    "end_row": document.get("end_row"),
                },
                "column_definitions": [],
                "growth_rules": {},
                "merged_anchors": [
                    value.get("merge")
                    for value in (document.get("fields") or {}).values()
                    if isinstance(value, dict) and value.get("merge")
                ],
                "formula_dependencies": [],
                "review_status": review_status,
            })
        for identifier in logical.get("identifier_fields") or []:
            locator = identifier.get("locator") or {}
            fields.append({
                "field_id": f"{sheet_name}.{identifier.get('key')}",
                "workbook_type": "GENERAL_DOCUMENT",
                "sheet_name": sheet_name,
                "sheet_index": None,
                "cell_address": None,
                "range_definition": locator,
                "value_type": identifier.get("data_type"),
                "semantic_role": identifier.get("key"),
                "read_policy": "read_only",
                "write_policy": "deny_until_reviewed",
                "validation_rules": [identifier.get("validation") or {}],
                "dependencies": [],
                "discovery_status": "inspected",
                "review_status": review_status,
                "evidence": [{"source": "cleaner", "stage": "DOCUMENT_BOUNDARIES"}],
                "schema_version": "0.1.0",
                "source_artifact_sha256": source_binding.get("sha256"),
            })
        for column in (sheet.get("transaction_schema") or {}).get("semantic_columns") or []:
            role = column.get("inferred_role")
            if not role:
                continue
            fields.append({
                "field_id": f"{sheet_name}.transaction.{column.get('letter')}.{role}",
                "workbook_type": "GENERAL_DOCUMENT",
                "sheet_name": sheet_name,
                "sheet_index": None,
                "cell_address": None,
                "range_definition": {"column": column.get("column"), "letter": column.get("letter")},
                "value_type": column.get("semantic_type"),
                "semantic_role": role,
                "read_policy": "read_only",
                "write_policy": "deny_until_reviewed",
                "validation_rules": [],
                "dependencies": [],
                "discovery_status": "inferred",
                "review_status": review_status,
                "evidence": [{
                    "source": "cleaner",
                    "stage": "SLOT_SCHEMA",
                    "confidence": column.get("role_confidence"),
                    "role_source": column.get("role_source"),
                }],
                "schema_version": "0.1.0",
                "source_artifact_sha256": source_binding.get("sha256"),
            })
    return {
        "schema_version": "0.1.0",
        "project_code": project,
        "run_id": orchestration_run_id,
        "workbooks": [{
            "workbook_type": "GENERAL_DOCUMENT",
            "format": "EXCEL",
            "artifact_id": source_binding.get("artifact_id"),
            "source_artifact_sha256": source_binding.get("sha256"),
            "worksheets": worksheets,
            "regions": regions,
            "fields": fields,
        }],
    }

def export_structure_quality_schema(
    run_dir: str | Path,
    *,
    project_id: str | None,
    orchestration_run_id: str,
    source_artifact_id: str,
    workbook_path: str | Path | None = None,
    source_sha256: str | None = None,
    contract_version: str = DEFAULT_CONTRACT_VERSION,
    output_path: str | Path | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Publish a read-only, run-bound structural schema snapshot.

    The exporter consumes existing Cleaner artifacts only. It never writes to the
    approved workbook and it never infers write-target approval from coverage.
    """
    run_dir = Path(run_dir).resolve()
    run_manifest = _load_json(run_dir / "run_manifest.json", required=True) or {}
    state = _load_json(run_dir / "resolved_state.json", required=True) or {}
    profile_name = str(run_manifest.get("profile_name") or state.get("profile_name") or project_id or "").strip().upper()
    if not profile_name:
        raise RuntimeError("Cannot determine Cleaner profile/project identity.")
    project = str(project_id or profile_name).strip().upper()
    if project != profile_name:
        raise RuntimeError(f"Project/profile mismatch: project={project}, profile={profile_name}")

    profile_path = _profile_path(run_manifest, run_dir, profile_name)
    profile = _load_json(profile_path, required=True) or {}
    source_binding = _resolve_source_binding(
        run_manifest=run_manifest,
        workbook_path=workbook_path,
        expected_sha256=source_sha256,
        source_artifact_id=source_artifact_id,
    )

    document_regions = _load_json(run_dir / "document_regions.json")
    card_maps = _load_json(run_dir / "card_maps.json")
    slot_schema = _load_json(run_dir / "slot_schema.json")
    coverage = _load_json(run_dir / "coverage_audit.json")
    board = _load_json(run_dir / "board_to_log.json")
    engineering = _load_json(run_dir / "engineering_lists" / "engineering_three_lists.json")
    publish_manifest = _load_json(run_dir / "publish_manifest.json")

    stage_ids = list(dict.fromkeys([*STRUCTURE_STAGES, *DATA_VALIDATION_STAGES]))
    stage_review = {stage: _stage_snapshot(state, stage) for stage in stage_ids}
    structure_discovered = all((run_dir / name).exists() for name in ("document_regions.json", "card_maps.json", "slot_schema.json"))
    structure_reviewed = all(_stage_reviewed(state, stage) for stage in STRUCTURE_STAGES)
    data_validated = all(_stage_reviewed(state, stage) for stage in DATA_VALIDATION_STAGES)
    counts = (((coverage or {}).get("summary") or {}).get("counts") or {})
    coverage_verified = bool(coverage) and int(counts.get("SCANNED_NOT_RETRIEVED") or 0) == 0

    expected_sheets = list(((profile.get("workbook") or {}).get("expected_sheets") or []))
    discovered_sheets = []
    for payload in (document_regions, card_maps, slot_schema):
        for name in ((payload or {}).get("sheets") or {}).keys():
            if name not in discovered_sheets:
                discovered_sheets.append(name)
    sheet_names = expected_sheets + [x for x in discovered_sheets if x not in expected_sheets]

    artifact_names = [
        "run_manifest.json",
        "resolved_state.json",
        "document_regions.json",
        "card_maps.json",
        "slot_schema.json",
        "field_validation_report.json",
        "identifiers_report.json",
        "board_to_log.json",
        "coverage_audit.json",
        "publish_manifest.json",
        "chronology_issues.json",
    ]
    artifacts = [_artifact_descriptor(run_dir, name) for name in artifact_names]
    engineering_path = run_dir / "engineering_lists" / "engineering_three_lists.json"
    artifacts.append({
        "name": "engineering_lists/engineering_three_lists.json",
        "relative_path": "engineering_lists/engineering_three_lists.json",
        "exists": engineering_path.exists(),
        "schema": engineering.get("schema") if engineering else None,
        "sha256": _sha256_file(engineering_path) if engineering_path.exists() else None,
    })

    profile_rel = None
    try:
        profile_rel = str(profile_path.resolve().relative_to(run_dir.resolve().parents[1]))
    except ValueError:
        profile_rel = str(profile_path)

    schema = {
        "schema": SCHEMA_ID,
        "schema_version": "0.1.0",
        "project_code": project,
        "run_id": orchestration_run_id,
        "contract_version": str(contract_version),
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "identity": {
            "project_id": project,
            "cleaner_run_id": run_manifest.get("run_id") or state.get("run_id") or run_dir.name,
            "orchestration_run_id": orchestration_run_id,
            "source": source_binding,
            "profile": {
                "name": profile_name,
                "schema_version": profile.get("schema_version"),
                "family": profile.get("family"),
                "relative_path": profile_rel,
                "sha256": _sha256_file(profile_path),
            },
        },
        "quality_state": {
            "structure_discovered": structure_discovered,
            "structure_reviewed": structure_reviewed,
            "data_validated": data_validated,
            "coverage_verified": coverage_verified,
            "write_targets_approved": False,
        },
        "quality_evidence": {
            "stage_review": stage_review,
            "coverage": {
                "available": coverage is not None,
                "scanned_not_retrieved": int(counts.get("SCANNED_NOT_RETRIEVED") or 0) if coverage else None,
                "unresolved_issue_count": int(counts.get("UNRESOLVED_ISSUE") or 0) if coverage else None,
                "summary": (coverage or {}).get("summary"),
            },
            "board_to_log": {
                "available": board is not None,
                "schema": (board or {}).get("schema"),
                "summary": (board or {}).get("summary"),
            },
            "engineering_reporting": {
                "available": engineering is not None,
                "schema": (engineering or {}).get("schema"),
                "summary": (engineering or {}).get("summary"),
            },
        },
        "workbook_structure": {
            "format": "EXCEL",
            "expected_sheets": expected_sheets,
            "sheets": [
                _sheet_schema(
                    sheet,
                    profile=profile,
                    document_regions=document_regions,
                    card_maps=card_maps,
                    slot_schema=slot_schema,
                )
                for sheet in sheet_names
            ],
            "relationships": [
                {
                    "kind": "DOCUMENT_TO_TRANSACTION",
                    "key": ["sheet", "record_index"],
                    "description": "DocumentRegion/Card identity owns repeating Board transaction blocks on the same sheet and record index.",
                },
                {
                    "kind": "WBS_DOCUMENT_KEY",
                    "field": "wbs",
                    "validation": next((x.get("validation") for x in _family_fields(profile).values() if x.get("key") == "wbs"), {}),
                },
                {
                    "kind": "RECEIVE_STATUS_RELATION",
                    "rule": ((((profile.get("data_model") or {}).get("field_validation") or {}).get("receive_status_relation") or {}).get("rule")),
                },
                {
                    "kind": "DATE_CHRONOLOGY",
                    "rule": ((((profile.get("data_model") or {}).get("field_validation") or {}).get("date_chronology") or {}).get("rule")),
                },
            ],
            "formulas": {
                "status": "NOT_MODELED_BY_CURRENT_CLEANER",
                "ranges": [],
                "note": "Formula dependency discovery is not implemented by the current General Document Cleaner.",
            },
        },
        "operations": {
            "company_original": {
                "mode": "READ_ONLY",
                "permitted": ["READ", "HASH", "DISCOVER_STRUCTURE", "VALIDATE"],
            },
            "controlled_working_copy": {
                "permitted_after_review": [
                    "SET_VALUE", "CLEAR_CELL", "REPLACE_VALUE", "UNMERGE_RANGE", "MERGE_RANGE",
                    "WRITE_LOGBOOK", "WRITE_COVERAGE_HIGHLIGHTS",
                ],
                "evidence_source": "resolved_state.json decision audit and published Cleaner execution",
            },
            "write_targets": {
                "approved": False,
                "status": "NOT_MODELED_BY_CURRENT_CLEANER",
                "approved_targets": [],
                "note": "Coverage success proves retrieval completeness only. It never authorizes workbook write locations.",
            },
        },
        "persistent_knowledge": {
            "known_exception_count": len(profile.get("known_exceptions") or []),
            "known_fix_count": len(profile.get("known_fixes") or []),
            "exception_registry": run_manifest.get("exception_registry"),
            "project_solutions": run_manifest.get("project_solutions"),
            "reuse_policy": "Profile-known exceptions/fixes and project solutions are reused across fresh runs; run-specific review decisions remain in resolved_state and decision files.",
        },
        "artifact_manifest": artifacts,
        "unsupported": [
            "Excel formula/dependency graph discovery",
            "Explicit workbook write-target approval contract",
            "MSP structural parsing",
            "P6 XER/XML structural parsing",
            "CSV structural parsing beyond existing retrieval support",
        ],
    }

    schema["structural_bridge"] = _bridge_workbook_projection(
        project=project,
        orchestration_run_id=orchestration_run_id,
        source_binding=source_binding,
        sheets=schema["workbook_structure"]["sheets"],
        structure_reviewed=structure_reviewed,
    )

    # Preserve evidence that a controlled publish may exist, without promoting it
    # into write-target approval.
    if publish_manifest:
        schema["quality_evidence"]["published_logbook"] = {
            "available": True,
            "schema": publish_manifest.get("schema"),
            "output_workbook": publish_manifest.get("output_workbook"),
            "validation": publish_manifest.get("validation"),
        }
    else:
        schema["quality_evidence"]["published_logbook"] = {"available": False}

    output = Path(output_path) if output_path else run_dir / "document_structure_quality_schema.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(schema, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    return output, schema
