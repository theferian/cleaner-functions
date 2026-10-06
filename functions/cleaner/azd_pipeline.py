from __future__ import annotations

import argparse
from datetime import datetime
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from cleaner_core import (
    RunReport,
    attach_excel_workbook,
    ensure_excel_workbook_open,
    build_resolved_context,
    ingest_review_decisions_file,
    load_profile,
    load_resolved_state,
    load_snapshot,
    mark_stage_run,
    save_resolved_state,
    snapshot_live_workbook,
    scan_all_document_regions,
    scan_all_document_structures,
    scan_all_card_maps,
    infer_all_slot_schemas,
)
from cleaner_core.exceptions import (
    load_exception_registry,
    save_exception_registry,
    sync_registry_from_decisions_file,
    reconcile_stage_findings,
    retire_profile_covered_cases,
)
from cleaner_core.logging import RunLogger
from cleaner_core.context import attach_document_context
from cleaner_core.solutions import (
    load_project_solutions,
    save_project_solutions,
    sync_project_solutions_from_decisions_file,
)
from review.queue import build_review_queue, write_review_queue
from tests.m_line_check import run as m_line_check
from tests.document_boundaries import run as document_boundaries_check
from tests.document_structure import run as document_structure_check
from tests.card_map import run as card_map_check
from tests.slot_schema import run as slot_schema_check
from tests.field_validation import run as field_validation_check
from tests.identifier_check import run as identifier_check


STAGES = ["M_LINE", "DOCUMENT_BOUNDARIES", "CARD_MAP", "SLOT_SCHEMA", "FIELD_VALIDATION", "IDENTIFIERS"]
RUNNERS = {
    "M_LINE": m_line_check,
    "DOCUMENT_BOUNDARIES": document_boundaries_check,
    "DOCUMENT_STRUCTURE": document_structure_check,
    "CARD_MAP": card_map_check,
    "SLOT_SCHEMA": slot_schema_check,
    "FIELD_VALIDATION": field_validation_check,
    "IDENTIFIERS": identifier_check,
}


def previous_stage(stage_id: str) -> str | None:
    stage_id = stage_id.upper()
    index = STAGES.index(stage_id)
    return STAGES[index - 1] if index > 0 else None


def assert_stage_allowed(state: dict, stage_id: str) -> None:
    previous = previous_stage(stage_id)
    if previous is None:
        return

    previous_state = state.get("stages", {}).get(previous, {})
    if previous_state.get("status") != "REVIEWED":
        raise RuntimeError(
            f"{stage_id} cannot run yet. Review {previous} first and ingest "
            "its decision file with --decisions."
        )


def run_stage(
    *,
    stage_id: str,
    snapshot,
    profile: dict,
    state: dict,
    logger,
):
    stage_id = stage_id.upper()
    if stage_id not in RUNNERS:
        raise ValueError(f"Unknown Cleaner pipeline stage: {stage_id}")

    assert_stage_allowed(state, stage_id)
    resolved_snapshot, resolved_profile = build_resolved_context(
        snapshot, profile, state
    )

    logger("PIPELINE", f"Running stage {stage_id} against resolved-state overlay.")
    return RUNNERS[stage_id](resolved_snapshot, resolved_profile, logger)


def _default_run_id(profile_name: str | None = None) -> str:
    prefix = str(profile_name or "azd").strip().lower().replace(" ", "_") or "azd"
    return f"{prefix}_{datetime.now().strftime('%Y%m%dT%H%M%S')}"


def resolve_run_mode(
    *,
    stage_id: str,
    requested_run_id: str | None,
    new_run: bool,
    profile_name: str | None = None,
) -> tuple[str, bool]:
    """Resolve run identity without touching the filesystem.

    Returns ``(run_id, is_new_run)``.  ``--new-run`` is intentionally
    restricted to the first pipeline stage so a fresh workbook cannot inherit
    later-stage state by accident.
    """
    stage_id = str(stage_id).upper()
    if new_run and requested_run_id:
        raise ValueError("--new-run and --run-id are mutually exclusive.")
    if new_run and stage_id != STAGES[0]:
        raise ValueError(f"--new-run must start at {STAGES[0]}, not {stage_id}.")
    if requested_run_id:
        return str(requested_run_id), False
    if not new_run:
        raise ValueError(
            "Choose exactly one run mode: --new-run for a fresh workbook or "
            "--run-id <existing-run> to continue a run."
        )
    return _default_run_id(profile_name), True


def assert_run_identity(
    state: dict,
    *,
    run_id: str,
    profile_name: str | None,
    workbook: dict,
) -> None:
    """Refuse to continue a run against a different profile/workbook.

    Workbook matching deliberately uses name + full path.  We do not bind to
    a content hash because review-time edits/undos in the live workbook should
    not make the run unusable.
    """
    if str(state.get("run_id") or "") != str(run_id):
        raise RuntimeError(
            f"Run-state ID mismatch: state={state.get('run_id')!r}, requested={run_id!r}."
        )

    existing_profile = state.get("profile_name")
    if existing_profile and profile_name and str(existing_profile) != str(profile_name):
        raise RuntimeError(
            f"Run {run_id} belongs to profile {existing_profile!r}, not {profile_name!r}."
        )

    existing_wb = state.get("workbook") or {}
    for key in ("name", "path"):
        old = str(existing_wb.get(key) or "").casefold()
        new = str(workbook.get(key) or "").casefold()
        if old and new and old != new:
            raise RuntimeError(
                f"Run {run_id} is bound to a different workbook {key}: "
                f"{existing_wb.get(key)!r} != {workbook.get(key)!r}. "
                "Start with --new-run for the freshly retrieved workbook."
            )


def write_run_manifest(
    path: Path,
    *,
    run_id: str,
    profile: dict,
    workbook: dict,
    exception_registry_path: Path,
    project_solutions_path: Path,
    profile_path: str | Path | None = None,
) -> Path:
    manifest_path = path / "run_manifest.json"
    payload = {
        "schema": "cleaner.run_manifest/0.1",
        "run_id": run_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "profile_name": profile.get("profile_name"),
        "profile_path": str(profile_path) if profile_path is not None else None,
        "workbook": workbook,
        "pipeline": list(STAGES),
        "exception_registry": str(exception_registry_path),
        "project_solutions": str(project_solutions_path),
    }
    manifest_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    return manifest_path


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Run one ordered project Cleaner stage. Later stages consume reviewed "
            "decisions from earlier stages through resolved_state.json."
        )
    )
    parser.add_argument("--stage", choices=STAGES, required=True)
    parser.add_argument("--run-id", default=None)
    parser.add_argument(
        "--new-run",
        action="store_true",
        help=(
            "Start a brand-new run. Must be used with M_LINE and may not be "
            "combined with --run-id."
        ),
    )
    parser.add_argument("--workbook")
    parser.add_argument(
        "--profile",
        default=str(PROJECT_ROOT / "profiles" / "AZD.profile.json"),
    )
    parser.add_argument(
        "--decisions",
        action="append",
        default=[],
        help=(
            "Review-decision JSON from an earlier stage. May be supplied more "
            "than once. Decisions are ingested before this stage runs."
        ),
    )
    parser.add_argument(
        "--exception-registry",
        default=None,
        help="Optional project exception-registry JSON path.",
    )
    parser.add_argument(
        "--project-solutions",
        default=None,
        help="Optional persistent project-solution registry JSON path.",
    )
    parser.add_argument("--keep-snapshot", action="store_true")
    parser.add_argument(
        "--open-workbook",
        action="store_true",
        help=(
            "Open --workbook as a retrieved working copy when it is not already "
            "open. Intended for the generic multi-project launcher."
        ),
    )
    args = parser.parse_args(argv)

    stage_id = args.stage.upper()
    logger = RunLogger(stream=True)

    wb = (
        ensure_excel_workbook_open(args.workbook, visible=True)
        if args.open_workbook
        else attach_excel_workbook(args.workbook)
    )
    workbook_meta = {
        "name": str(wb.Name),
        "path": str(wb.FullName),
        "saved_state": "saved" if wb.Saved else "unsaved",
    }

    profile = load_profile(args.profile)
    profile_name = str(profile.get("profile_name") or "PROJECT")
    run_id, is_new_run = resolve_run_mode(
        stage_id=stage_id,
        requested_run_id=args.run_id,
        new_run=args.new_run,
        profile_name=profile_name,
    )
    run_dir = PROJECT_ROOT / "runs" / run_id
    state_path = run_dir / "resolved_state.json"

    if is_new_run:
        if run_dir.exists():
            raise RuntimeError(
                f"Fresh run directory already exists: {run_dir}. "
                "Choose a new run or remove the unused directory explicitly."
            )
        run_dir.mkdir(parents=True, exist_ok=False)
    else:
        if not state_path.exists():
            raise RuntimeError(
                f"Run ID {run_id!r} does not exist ({state_path}). "
                "Use --new-run --stage M_LINE for a freshly retrieved workbook."
            )

    exception_registry_path = Path(args.exception_registry) if args.exception_registry else (
        PROJECT_ROOT / "exceptions" / f"{profile_name}.exceptions.json"
    )
    exception_registry = load_exception_registry(
        exception_registry_path,
        profile_name=profile_name,
        create=True,
    )
    project_solutions_path = Path(args.project_solutions) if args.project_solutions else (
        PROJECT_ROOT / "project_solutions" / f"{profile_name}.solutions.json"
    )
    project_solutions = load_project_solutions(
        project_solutions_path,
        project_id=profile_name,
        create=True,
    )
    registry_hygiene = retire_profile_covered_cases(exception_registry, profile)
    if registry_hygiene.get("retired_handles"):
        logger(
            "EXCEPTIONS",
            "Retired profile-covered case(s): "
            + ", ".join(registry_hygiene["retired_handles"]),
        )
        save_exception_registry(exception_registry, exception_registry_path)
    state = load_resolved_state(
        state_path,
        create=is_new_run,
        run_id=run_id,
        profile_name=profile.get("profile_name"),
        workbook=workbook_meta,
    )
    if not is_new_run:
        assert_run_identity(
            state,
            run_id=run_id,
            profile_name=profile.get("profile_name"),
            workbook=workbook_meta,
        )

    if is_new_run:
        run_manifest_path = write_run_manifest(
            run_dir,
            run_id=run_id,
            profile=profile,
            workbook=workbook_meta,
            exception_registry_path=exception_registry_path,
            project_solutions_path=project_solutions_path,
            profile_path=args.profile,
        )
    else:
        run_manifest_path = run_dir / "run_manifest.json"

    for decision_path in args.decisions:
        logger("STATE", f"Ingesting reviewed decisions: {decision_path}")
        ingest_review_decisions_file(state, decision_path)
        exc_report = sync_registry_from_decisions_file(exception_registry, decision_path)
        solution_report = sync_project_solutions_from_decisions_file(project_solutions, decision_path)
        solution_handles = solution_report.get("created_handles", []) + solution_report.get("updated_handles", [])
        if solution_handles:
            logger(
                "SOLUTIONS",
                "Project solution(s) persisted: " + ", ".join(solution_handles),
            )
        if exc_report.get("updated_handles"):
            logger(
                "EXCEPTIONS",
                "Tracked exception case(s): " + ", ".join(exc_report["updated_handles"]),
            )
    save_resolved_state(state, state_path)
    save_exception_registry(exception_registry, exception_registry_path)
    save_project_solutions(project_solutions, project_solutions_path)

    assert_stage_allowed(state, stage_id)

    logger("CONNECT", f"Workbook: {workbook_meta['name']}")
    logger("STATE", f"Run ID: {run_id}")
    if is_new_run:
        logger("STATE", "Run mode: NEW (fresh state; no prior review decisions inherited).")
        logger("STATE", f"Run manifest: {run_manifest_path}")
    logger("STATE", f"Resolved state: {state_path}")

    started = time.perf_counter()
    snapshot_path = snapshot_live_workbook(wb)
    logger(
        "TIMING",
        f"Snapshot created in {time.perf_counter() - started:.2f}s: {snapshot_path}",
    )

    stage_artifacts = {}
    snap = load_snapshot(snapshot_path)
    try:
        findings = run_stage(
            stage_id=stage_id,
            snapshot=snap,
            profile=profile,
            state=state,
            logger=logger,
        )
        resolved_snapshot, resolved_profile = build_resolved_context(snap, profile, state)
        attach_document_context(findings, resolved_snapshot, resolved_profile)
        exception_reconcile = reconcile_stage_findings(
            exception_registry,
            findings,
            stage_id=stage_id,
            run_id=run_id,
        )
        save_exception_registry(exception_registry, exception_registry_path)
        if exception_reconcile.get("detected_open_cases") or exception_reconcile.get("auto_resolved_cases"):
            logger(
                "EXCEPTIONS",
                f"open detected={exception_reconcile['detected_open_cases']}; "
                f"auto-resolved={exception_reconcile['auto_resolved_cases']}",
            )

        if stage_id == "DOCUMENT_BOUNDARIES":
            resolved_snapshot, resolved_profile = build_resolved_context(
                snap, profile, state
            )
            scans = scan_all_document_regions(resolved_snapshot, resolved_profile)
            regions_path = run_dir / "document_regions.json"
            regions_payload = {
                "schema": "cleaner.document_regions/0.1",
                "run_id": run_id,
                "profile_name": resolved_profile.get("profile_name"),
                "workbook": workbook_meta,
                "sheets": {
                    sheet: scan.to_dict()
                    for sheet, scan in scans.items()
                },
            }
            regions_path.write_text(
                json.dumps(
                    regions_payload,
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                ) + "\n",
                encoding="utf-8",
            )
            stage_artifacts["document_regions"] = str(regions_path)
            logger(
                "ARTIFACT",
                f"Derived document-region catalog: {regions_path}",
            )

        if stage_id == "CARD_MAP":
            resolved_snapshot, resolved_profile = build_resolved_context(
                snap, profile, state
            )
            scans = scan_all_card_maps(resolved_snapshot, resolved_profile)
            card_map_path = run_dir / "card_maps.json"
            card_map_payload = {
                "schema": "cleaner.card_map/0.1",
                "run_id": run_id,
                "profile_name": resolved_profile.get("profile_name"),
                "workbook": workbook_meta,
                "sheets": {sheet: scan.to_dict() for sheet, scan in scans.items()},
            }
            card_map_path.write_text(
                json.dumps(card_map_payload, ensure_ascii=False, indent=2, default=str) + "\n",
                encoding="utf-8",
            )
            stage_artifacts["card_map"] = str(card_map_path)
            logger("ARTIFACT", f"Derived card/data map: {card_map_path}")

        if stage_id == "SLOT_SCHEMA":
            resolved_snapshot, resolved_profile = build_resolved_context(
                snap, profile, state
            )
            schemas = infer_all_slot_schemas(resolved_snapshot, resolved_profile)
            schema_path = run_dir / "slot_schema.json"
            schema_payload = {
                "schema": "cleaner.slot_schema/0.1",
                "run_id": run_id,
                "profile_name": resolved_profile.get("profile_name"),
                "workbook": workbook_meta,
                "sheets": {sheet: schema.to_dict() for sheet, schema in schemas.items()},
            }
            schema_path.write_text(
                json.dumps(schema_payload, ensure_ascii=False, indent=2, default=str) + "\n",
                encoding="utf-8",
            )
            stage_artifacts["slot_schema"] = str(schema_path)
            logger("ARTIFACT", f"Derived slot/field schema: {schema_path}")

        if stage_id == "DOCUMENT_STRUCTURE":
            resolved_snapshot, resolved_profile = build_resolved_context(
                snap, profile, state
            )
            scans = scan_all_document_structures(resolved_snapshot, resolved_profile)
            catalog_path = run_dir / "document_structure_catalog.json"
            catalog_payload = {
                "schema": "cleaner.document_structure/0.1",
                "run_id": run_id,
                "profile_name": resolved_profile.get("profile_name"),
                "workbook": workbook_meta,
                "sheets": {sheet: scan.to_dict() for sheet, scan in scans.items()},
            }
            catalog_path.write_text(
                json.dumps(catalog_payload, ensure_ascii=False, indent=2, default=str) + "\n",
                encoding="utf-8",
            )
            stage_artifacts["document_structure_catalog"] = str(catalog_path)
            logger("ARTIFACT", f"Derived document-structure catalog: {catalog_path}")
    finally:
        snap.close()

    report = RunReport(
        kind="azd_pipeline_stage",
        script_id=stage_id,
        logs=logger.records,
        findings=findings,
        snapshot_path=str(snapshot_path),
    )
    payload = report.to_dict()
    payload["run_id"] = run_id
    payload["pipeline_stage"] = stage_id
    payload["resolved_state_path"] = str(state_path)
    if stage_artifacts:
        payload["derived_artifacts"] = stage_artifacts

    stem = stage_id.lower()
    report_path = run_dir / f"{stem}_report.json"
    queue_path = run_dir / f"{stem}_review_queue.json"
    decisions_path = run_dir / f"{stem}_review_decisions.json"

    report_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )

    manifest = json.loads(
        (PROJECT_ROOT / "cleaner.package.json").read_text(encoding="utf-8")
    )
    queue = build_review_queue(
        report=payload,
        profile=profile,
        package_manifest=manifest,
        workbook=workbook_meta,
        report_path=str(report_path),
        exception_registry=exception_registry,
        project_solutions=project_solutions,
    )
    write_review_queue(queue, queue_path)

    review_count = int(queue.get("summary", {}).get("total_items", len(queue.get("items", []))))
    mark_stage_run(
        state,
        stage_id,
        finding_count=review_count,
        report_path=str(report_path),
        review_queue_path=str(queue_path),
    )
    save_resolved_state(state, state_path)

    print("\n=== PIPELINE STAGE COMPLETE ===")
    print(f"Run ID       : {run_id}")
    print(f"Stage        : {stage_id}")
    print(f"Findings     : {len(findings)}")
    print(f"Review items : {review_count}")
    print(f"Report       : {report_path}")
    print(f"Review queue : {queue_path}")
    print(f"State        : {state_path}")
    print(f"Run manifest : {run_manifest_path}")
    print(f"Exceptions   : {exception_registry_path}")
    print(f"Solutions    : {project_solutions_path}")
    if stage_artifacts.get("document_regions"):
        print(f"Regions      : {stage_artifacts['document_regions']}")
    if stage_artifacts.get("document_structure_catalog"):
        print(f"Structure    : {stage_artifacts['document_structure_catalog']}")
    if stage_artifacts.get("card_map"):
        print(f"Card map     : {stage_artifacts['card_map']}")
        print("\nOptional visual inspection of every derived card/data boundary:")
        print(f'python .\\dev\\inspect_card_map.py "{stage_artifacts["card_map"]}"')
    if review_count:
        print("\nReview this stage with:")
        print(
            f'python .\\dev\\review_findings.py "{queue_path}" '
            f'--decisions "{decisions_path}" --accept-known'
        )
    else:
        print("\nNo review is required for this stage; it was marked REVIEWED automatically.")

    nxt = None
    index = STAGES.index(stage_id)
    if index + 1 < len(STAGES):
        nxt = STAGES[index + 1]
    if nxt:
        project_code = str(profile_name or "AZD").strip().upper()
        if project_code == "AZD":
            launcher = f'python .\\pipeline\\azd_pipeline.py --run-id "{run_id}"'
        else:
            launcher = (
                f'python .\\pipeline\\project_pipeline.py --project {project_code} '
                f'--run-id "{run_id}"'
            )
        if review_count:
            print("\nThen run the next stage with the same run-id and decisions:")
            print(
                f'{launcher} --stage {nxt} --decisions "{decisions_path}"'
            )
        else:
            print("\nThen run the next stage with the same run-id:")
            print(f'{launcher} --stage {nxt}')

    if not args.keep_snapshot:
        Path(snapshot_path).unlink(missing_ok=True)
        logger("SNAPSHOT", "Temporary snapshot deleted.")


if __name__ == "__main__":
    main()
