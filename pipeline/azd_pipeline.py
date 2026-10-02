from __future__ import annotations

import argparse
from datetime import datetime
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from cleaner_core import (
    RunReport,
    attach_excel_workbook,
    build_resolved_context,
    ingest_review_decisions_file,
    load_profile,
    load_resolved_state,
    load_snapshot,
    mark_stage_run,
    save_resolved_state,
    snapshot_live_workbook,
    scan_all_document_regions,
)
from cleaner_core.logging import RunLogger
from review.queue import build_review_queue, write_review_queue
from tests.m_line_check import run as m_line_check
from tests.document_boundaries import run as document_boundaries_check
from tests.identifier_check import run as identifier_check


STAGES = ["M_LINE", "DOCUMENT_BOUNDARIES", "IDENTIFIERS"]
RUNNERS = {
    "M_LINE": m_line_check,
    "DOCUMENT_BOUNDARIES": document_boundaries_check,
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
        raise ValueError(f"Unknown AZD pipeline stage: {stage_id}")

    assert_stage_allowed(state, stage_id)
    resolved_snapshot, resolved_profile = build_resolved_context(
        snapshot, profile, state
    )

    logger("PIPELINE", f"Running stage {stage_id} against resolved-state overlay.")
    return RUNNERS[stage_id](resolved_snapshot, resolved_profile, logger)


def _default_run_id() -> str:
    return f"azd_{datetime.now().strftime('%Y%m%dT%H%M%S')}"


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Run one ordered AZD cleaner stage. Later stages consume reviewed "
            "decisions from earlier stages through resolved_state.json."
        )
    )
    parser.add_argument("--stage", choices=STAGES, required=True)
    parser.add_argument("--run-id", default=None)
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
    parser.add_argument("--keep-snapshot", action="store_true")
    args = parser.parse_args()

    stage_id = args.stage.upper()
    logger = RunLogger(stream=True)

    wb = attach_excel_workbook(args.workbook)
    workbook_meta = {
        "name": str(wb.Name),
        "path": str(wb.FullName),
        "saved_state": "saved" if wb.Saved else "unsaved",
    }

    run_id = args.run_id or _default_run_id()
    run_dir = PROJECT_ROOT / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    state_path = run_dir / "resolved_state.json"

    profile = load_profile(args.profile)
    state = load_resolved_state(
        state_path,
        create=True,
        run_id=run_id,
        profile_name=profile.get("profile_name"),
        workbook=workbook_meta,
    )

    for decision_path in args.decisions:
        logger("STATE", f"Ingesting reviewed decisions: {decision_path}")
        ingest_review_decisions_file(state, decision_path)
    save_resolved_state(state, state_path)

    assert_stage_allowed(state, stage_id)

    logger("CONNECT", f"Workbook: {workbook_meta['name']}")
    logger("STATE", f"Run ID: {run_id}")
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
    )
    write_review_queue(queue, queue_path)

    mark_stage_run(
        state,
        stage_id,
        finding_count=len(findings),
        report_path=str(report_path),
        review_queue_path=str(queue_path),
    )
    save_resolved_state(state, state_path)

    print("\n=== PIPELINE STAGE COMPLETE ===")
    print(f"Run ID       : {run_id}")
    print(f"Stage        : {stage_id}")
    print(f"Findings     : {len(findings)}")
    print(f"Report       : {report_path}")
    print(f"Review queue : {queue_path}")
    print(f"State        : {state_path}")
    if stage_artifacts.get("document_regions"):
        print(f"Regions      : {stage_artifacts['document_regions']}")
    print("\nReview this stage with:")
    print(
        f'python .\\dev\\review_findings.py "{queue_path}" '
        f'--decisions "{decisions_path}" --accept-known'
    )

    nxt = None
    index = STAGES.index(stage_id)
    if index + 1 < len(STAGES):
        nxt = STAGES[index + 1]
    if nxt:
        print("\nThen run the next stage with the same run-id and decisions:")
        print(
            f'python .\\pipeline\\azd_pipeline.py --run-id "{run_id}" '
            f'--stage {nxt} --decisions "{decisions_path}"'
        )

    if not args.keep_snapshot:
        Path(snapshot_path).unlink(missing_ok=True)
        logger("SNAPSHOT", "Temporary snapshot deleted.")


if __name__ == "__main__":
    main()
