from __future__ import annotations

import argparse
from pathlib import Path
import sys

# Allow this orchestration script to be executed directly from pipeline/.
# When Python runs ``python .\pipeline\weekly_report_pipeline.py``, only
# pipeline/ is placed on sys.path, so sibling packages such as functions/ are
# otherwise invisible.  The orchestration layer deliberately lives one level
# above the function packages, so make the repository root importable first.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from functions.cleaner import (
    create_cleaned_copy_com,
    finalize_run,
    build_general_document_profile,
    inspect_general_document_workbook,
    export_structure_quality_schema,
)
from functions.retrieval import load_retrieval_config, retrieve_project_set, write_retrieval_manifest
from functions.engineering_control import (
    build_three_engineering_lists,
    document_inventory_from_cleaner,
    write_three_lists_csv,
    write_three_lists_json,
)
from functions.board_to_log import (
    build_issue_contexts,
    extract_board_to_log,
    write_csv,
    write_excel_com,
    write_issues_csv,
    write_json,
    write_logbook_to_workbook_com,
    validate_logbook_workbook_com,
    build_coverage_audit,
    apply_coverage_highlights_com,
)



def retrieval_step(args) -> int:
    config = load_retrieval_config(args.config)
    families = args.family or None
    results = retrieve_project_set(
        config,
        project_id=args.project,
        families=families,
        destination=args.destination,
        retrieval_date=args.retrieval_date,
        overwrite=args.overwrite,
    )

    destination = Path(
        args.destination
        or config.get("retrieval_workspace")
        or "./input"
    )
    manifest_path = (
        Path(args.manifest)
        if args.manifest
        else destination / f"{str(args.project).upper()}_retrieval_manifest.json"
    )
    write_retrieval_manifest(results, manifest_path)

    for item in results:
        print(
            f"[RETRIEVAL] Project     : {item.project_id}"
        )
        print(
            f"[RETRIEVAL] Family      : {item.family}"
        )
        print(
            f"[RETRIEVAL] Source      : {item.source_path}"
        )
        print(
            f"[RETRIEVAL] Retrieved   : {item.retrieved_path}"
        )
        print(
            f"[RETRIEVAL] Candidates  : {item.candidate_count}; "
            f"selected_date={item.selected_date or '-'}"
        )
        print(
            f"[RETRIEVAL] SHA-256     : {(item.sha256 or '')[:12]}..."
        )
    print(f"[RETRIEVAL] Manifest    : {manifest_path}")
    return 0



def prepare_general_doc_step(args) -> int:
    config = load_retrieval_config(args.config)
    project = str(args.project).strip().upper()
    results = retrieve_project_set(
        config,
        project_id=project,
        families=["GENERAL_DOCUMENT"],
        destination=args.destination,
        retrieval_date=args.retrieval_date,
        overwrite=args.overwrite,
    )
    if len(results) != 1:
        raise RuntimeError(f"Expected one GENERAL_DOCUMENT retrieval result for {project}, got {len(results)}.")
    result = results[0]

    destination = Path(args.destination or config.get("retrieval_workspace") or "./input")
    manifest_path = Path(args.manifest) if args.manifest else destination / f"{project}_retrieval_manifest.json"
    write_retrieval_manifest(results, manifest_path)

    base_profile = Path(args.base_profile) if args.base_profile else PROJECT_ROOT / "profiles" / "families" / "GENERAL_DOCUMENT.base.json"
    profile_path = Path(args.profile) if args.profile else PROJECT_ROOT / "profiles" / f"{project}.profile.json"
    explicit_sheets = args.sheet or None
    if profile_path.exists() and not args.overwrite_profile:
        probes = inspect_general_document_workbook(result.retrieved_path)
        profile_action = "existing_profile_kept"
    else:
        project_cfg = (config.get("projects") or {}).get(project) or {}
        profile_overrides = (project_cfg.get("cleaner_profiles") or {}).get("GENERAL_DOCUMENT") or {}
        profile_path, profile = build_general_document_profile(
            project_id=project,
            workbook_path=result.retrieved_path,
            base_profile_path=base_profile,
            output_path=profile_path,
            sheets=explicit_sheets,
            overwrite=args.overwrite_profile,
            profile_overrides=profile_overrides,
        )
        probes = inspect_general_document_workbook(result.retrieved_path)
        profile_action = "profile_created"

    print(f"[PREPARE] Project      : {project}")
    print(f"[PREPARE] Source       : {result.source_path}")
    print(f"[PREPARE] Retrieved    : {result.retrieved_path}")
    print(f"[PREPARE] Manifest     : {manifest_path}")
    print(f"[PREPARE] Profile      : {profile_path} ({profile_action})")
    print("[PREPARE] Workbook sheets:")
    for probe in probes:
        flag = "DATA" if probe.selected else "skip"
        hits = ",".join(probe.header_hits) or "-"
        print(
            f"          [{flag:4}] {probe.sheet!r}: rows={probe.max_row}, cols={probe.max_col}, "
            f"identifier_rows={probe.identifier_rows}, board_cells={probe.transaction_cells}, headers={hits}"
        )
    print("[PREPARE] Next         :")
    print(
        f"          python ./pipeline/project_pipeline.py --project {project} "
        "--stage M_LINE --new-run"
    )
    return 0

def board_to_log_step(args) -> int:
    run = finalize_run(args.run_dir)
    result = extract_board_to_log(run, project_id=args.project)

    json_path = Path(args.json_out) if args.json_out else run.run_dir / "board_to_log.json"
    write_json(result, json_path)
    print(f"[PIPELINE] Cleaner run : {run.run_id}")
    payload = result.to_dict()
    summary = payload.get("summary") or {}
    print(f"[PIPELINE] Board->Log   : records={len(result.records)}, issues={len(result.issues)}")
    print(
        "[PIPELINE] Events       : "
        f"send={summary.get('send_count', 0)}, receive={summary.get('receive_count', 0)}"
    )
    print(
        "[PIPELINE] Preserved    : "
        f"narrative={summary.get('preserved_narrative_count', 0)}, "
        f"status_only_receive={summary.get('status_only_receive_count', 0)}, "
        f"unclassified={result.diagnostics.get('unclassified_content_count', 0)}"
    )
    issue_counts = summary.get("issues_by_kind") or {}
    if issue_counts:
        print("[PIPELINE] Issue types  :")
        for kind, count in sorted(issue_counts.items(), key=lambda item: (-int(item[1]), item[0])):
            print(f"             {kind}={count}")
    else:
        print("[PIPELINE] Issue types  : none")
    print(f"[PIPELINE] Log artifact: {json_path}")

    issues_path = Path(args.issues_csv) if args.issues_csv else run.run_dir / "board_to_log_issues.csv"
    write_issues_csv(result, issues_path)
    print(f"[PIPELINE] Issues CSV   : {issues_path}")

    if args.csv_out:
        csv_path = write_csv(result, args.csv_out)
        print(f"[PIPELINE] CSV         : {csv_path}")

    if args.show_issue_context and result.issues:
        contexts = build_issue_contexts(run, result)
        context_path = run.run_dir / "board_to_log_issue_context.json"
        import json
        context_path.write_text(json.dumps(contexts, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[PIPELINE] Issue context: {context_path}")
        for context in contexts:
            issue = context["issue"]
            print(
                f"[CONTEXT {context['issue_no']:02d}] {issue['kind']} | "
                f"{issue['sheet']}!{issue.get('address')} | rev={context.get('revision')} | "
                f"doc={context['document_identity'].get('name')!r}"
            )
            for slot in context.get("slots", []):
                print(
                    "    "
                    f"{slot['address']:<12} role={str(slot.get('role')):<12} "
                    f"side={str(slot.get('side_hint')):<7} value={ascii(slot.get('value'))}"
                )

    if args.excel_workbook:
        summary = write_excel_com(
            result,
            workbook_path=args.excel_workbook,
            sheet_name=args.sheet,
            save=not args.no_save,
        )
        print(f"[PIPELINE] Excel       : {summary}")
    return 0



def publish_logbook_step(args) -> int:
    import json

    run = finalize_run(args.run_dir)
    result = extract_board_to_log(run, project_id=args.project)
    if result.issues and not args.allow_issues:
        raise RuntimeError(
            f"Board->Log has {len(result.issues)} unresolved issue(s). "
            "Review them first or rerun with --allow-issues to acknowledge publishing with known issues."
        )

    excel, workbook, output_path, execution = create_cleaned_copy_com(
        run,
        output_path=args.output,
        overwrite=args.overwrite,
    )
    try:
        write_summary = write_logbook_to_workbook_com(
            workbook, result, sheet_name=args.sheet
        )
        validation = validate_logbook_workbook_com(
            workbook, result, sheet_name=args.sheet
        )
        workbook.Save()
    except Exception:
        try:
            workbook.Close(SaveChanges=False)
        finally:
            raise
    else:
        workbook.Close(SaveChanges=False)

    manifest = {
        "schema": "weekly_report.publish/0.1",
        "run_id": run.run_id,
        "project_id": result.project_id,
        "source_workbook": run.workbook,
        "output_workbook": str(output_path),
        "cleaner_execution": execution,
        "board_to_log": result.to_dict().get("summary"),
        "known_issues": [x.to_dict() for x in result.issues],
        "logbook_write": write_summary,
        "validation": validation,
    }
    manifest_path = run.run_dir / "publish_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )

    print(f"[PUBLISH] Cleaner run   : {run.run_id}")
    print(f"[PUBLISH] Workbook      : {output_path}")
    print(
        "[PUBLISH] Cleaner fixes : "
        f"applied={execution['applied_count']}, already={execution['already_applied_count']}"
    )
    print(
        "[PUBLISH] Logbook       : "
        f"records={len(result.records)}, issues={len(result.issues)}, sheet={args.sheet}"
    )
    print(
        "[PUBLISH] Validation    : "
        f"PASS records={validation['record_count']} digest={validation['digest'][:12]}..."
    )
    print(f"[PUBLISH] Manifest      : {manifest_path}")
    return 0



def coverage_audit_step(args) -> int:
    import json

    run = finalize_run(args.run_dir)
    result = extract_board_to_log(run, project_id=args.project)
    audit = build_coverage_audit(run, result)

    source_path = Path(str(run.workbook.get("path") or run.workbook.get("name") or "workbook.xlsx"))
    suffix = source_path.suffix or ".xlsx"
    default_output = run.run_dir / f"{source_path.stem}_COVERAGE_AUDIT{suffix}"
    output_path = Path(args.output) if args.output else default_output

    excel, workbook, output_path, execution = create_cleaned_copy_com(
        run,
        output_path=output_path,
        overwrite=args.overwrite,
    )
    try:
        logbook_write = write_logbook_to_workbook_com(workbook, result, sheet_name=args.sheet)
        validation = validate_logbook_workbook_com(workbook, result, sheet_name=args.sheet)
        highlight = apply_coverage_highlights_com(
            workbook, audit, legend_sheet=args.legend_sheet
        )
        workbook.Save()
    except Exception:
        try:
            workbook.Close(SaveChanges=False)
        finally:
            raise
    else:
        workbook.Close(SaveChanges=False)

    audit_path = run.run_dir / "coverage_audit.json"
    audit_path.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    summary = audit.get("summary") or {}
    counts = summary.get("counts") or {}
    print(f"[COVERAGE] Cleaner run   : {run.run_id}")
    print(f"[COVERAGE] Workbook      : {output_path}")
    print(f"[COVERAGE] Logbook       : records={len(result.records)}, issues={len(result.issues)}")
    print(
        "[COVERAGE] Mapped slots   : "
        f"total={summary.get('mapped_nonempty_count', 0)}, "
        f"transaction={counts.get('CAPTURED_TRANSACTION', 0)}, "
        f"narrative={counts.get('CAPTURED_NARRATIVE', 0)}, "
        f"identity={counts.get('CAPTURED_IDENTITY', 0)}, "
        f"not_retrieved={counts.get('SCANNED_NOT_RETRIEVED', 0)}, "
        f"issues={counts.get('UNRESOLVED_ISSUE', 0)}"
    )
    print(
        "[COVERAGE] Validation    : "
        f"PASS records={validation['record_count']} digest={validation['digest'][:12]}..."
    )
    print(f"[COVERAGE] Legend        : {args.legend_sheet}")
    print(f"[COVERAGE] Audit JSON    : {audit_path}")
    return 0


def engineering_lists_step(args) -> int:
    run = finalize_run(args.run_dir)
    board = extract_board_to_log(run, project_id=args.project)
    result = build_three_engineering_lists(
        board.records,
        status_date=args.status_date,
        document_inventory=document_inventory_from_cleaner(run),
        company_allowance_days=args.company_allowance_days,
        consultant_allowance_days=args.consultant_allowance_days,
        company_response_statuses=args.company_response_status or None,
        status_library_path=args.status_library,
    )
    output_dir = Path(args.output_dir) if args.output_dir else run.run_dir / "engineering_lists"
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = write_three_lists_json(result, output_dir / "engineering_three_lists.json")
    csv_paths = write_three_lists_csv(result, output_dir)
    summary = result.to_dict()["summary"]
    print(f"[ENGINEERING] Status date      : {args.status_date}")
    print(f"[ENGINEERING] Not sent         : {summary['not_sent']}")
    print(f"[ENGINEERING] Company delay    : {summary['company_delay']}")
    print(f"[ENGINEERING] Consultant delay : {summary['consultant_delay']}")
    print(f"[ENGINEERING] Delay register    : {summary['delay_register']}")
    if summary.get("company_delay_by_unit"):
        units = ", ".join(f"{unit}={count}" for unit, count in sorted(summary["company_delay_by_unit"].items()))
        print(f"[ENGINEERING] Company by unit  : {units}")
    print(f"[ENGINEERING] Needs review/date: {summary['diagnostic_count']}")
    print(f"[ENGINEERING] JSON             : {json_path}")
    for name, path in csv_paths.items():
        print(f"[ENGINEERING] {name:<18}: {path}")
    return 0


def export_structure_schema_step(args) -> int:
    output, payload = export_structure_quality_schema(
        args.run_dir,
        project_id=args.project,
        orchestration_run_id=args.orchestration_run_id,
        source_artifact_id=args.source_artifact_id,
        workbook_path=args.workbook,
        source_sha256=args.source_sha256,
        contract_version=args.contract_version,
        output_path=args.output,
    )
    state = payload["quality_state"]
    source = payload["identity"]["source"]
    print(f"[SCHEMA] Cleaner run       : {payload['identity']['cleaner_run_id']}")
    print(f"[SCHEMA] Orchestration run : {payload['identity']['orchestration_run_id']}")
    print(f"[SCHEMA] Source artifact   : {source['artifact_id']}")
    print(f"[SCHEMA] Source SHA-256    : {source['sha256']}")
    print(
        "[SCHEMA] State             : "
        f"discovered={state['structure_discovered']}, "
        f"reviewed={state['structure_reviewed']}, "
        f"validated={state['data_validated']}, "
        f"coverage={state['coverage_verified']}, "
        f"writes_approved={state['write_targets_approved']}"
    )
    print(f"[SCHEMA] Output            : {output}")
    return 0

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Weekly-report orchestration layer above Cleaner and Board->Log functions."
    )
    subs = parser.add_subparsers(dest="command", required=True)

    ret = subs.add_parser(
        "retrieve",
        help="Discover and copy configured Project Control source documents into the retrieval workspace.",
    )
    ret.add_argument("--config", required=True)
    ret.add_argument("--project", required=True)
    ret.add_argument(
        "--family",
        action="append",
        default=[],
        help="Source family to retrieve. Repeat for more than one; omit to retrieve every enabled family.",
    )
    ret.add_argument("--destination", default=None)
    ret.add_argument("--retrieval-date", default=None)
    ret.add_argument("--manifest", default=None)
    ret.add_argument("--overwrite", action="store_true")
    ret.set_defaults(func=retrieval_step)


    prep = subs.add_parser(
        "prepare-general-doc",
        help="Retrieve one project General Document and bootstrap a project Cleaner profile from its actual sheets.",
    )
    prep.add_argument("--config", default=str(PROJECT_ROOT / "configs" / "project_control_sources.json"))
    prep.add_argument("--project", required=True)
    prep.add_argument("--destination", default=None)
    prep.add_argument("--retrieval-date", default=None)
    prep.add_argument("--manifest", default=None)
    prep.add_argument("--profile", default=None)
    prep.add_argument("--base-profile", default=None)
    prep.add_argument("--sheet", action="append", default=[], help="Explicit data sheet; repeat to override automatic sheet selection.")
    prep.add_argument("--overwrite", action="store_true", help="Replace the retrieved working copy if it already exists with different content.")
    prep.add_argument("--overwrite-profile", action="store_true", help="Rebuild an existing project profile. Project-specific learned knowledge may be lost.")
    prep.set_defaults(func=prepare_general_doc_step)

    btl = subs.add_parser("board-to-log", help="Build canonical log records from a reviewed Cleaner run.")
    btl.add_argument("--run-dir", required=True)
    btl.add_argument("--project", default=None)
    btl.add_argument("--json-out", default=None)
    btl.add_argument("--csv-out", default=None)
    btl.add_argument("--issues-csv", default=None)
    btl.add_argument("--show-issue-context", action="store_true")
    btl.add_argument("--excel-workbook", default=None)
    btl.add_argument("--sheet", default="Logbook")
    btl.add_argument("--no-save", action="store_true")
    btl.set_defaults(func=board_to_log_step)


    cov = subs.add_parser(
        "audit-coverage",
        help="Create a coloured QA copy showing which mapped source slots reached the canonical Logbook.",
    )
    cov.add_argument("--run-dir", required=True)
    cov.add_argument("--project", default=None)
    cov.add_argument("--output", default=None)
    cov.add_argument("--sheet", default="Logbook")
    cov.add_argument("--legend-sheet", default="Coverage_Audit")
    cov.add_argument("--overwrite", action="store_true")
    cov.set_defaults(func=coverage_audit_step)

    eng = subs.add_parser(
        "engineering-lists",
        help="Build the three engineering exception lists from the canonical document log.",
    )
    eng.add_argument("--run-dir", required=True)
    eng.add_argument("--project", default=None)
    eng.add_argument("--status-date", required=True, help="Jalali YYYY/MM/DD")
    eng.add_argument("--company-allowance-days", type=int, default=0)
    eng.add_argument("--consultant-allowance-days", type=int, default=0)
    eng.add_argument(
        "--company-response-status",
        action="append",
        default=[],
        help="Receive status that puts responsibility back on us; repeat as needed. If omitted, use status-library semantics plus legacy CM/RJ defaults.",
    )
    eng.add_argument(
        "--status-library",
        default=None,
        help="Optional path to reusable status-library JSON. Default: configs/status_library.json.",
    )
    eng.add_argument("--output-dir", default=None)
    eng.set_defaults(func=engineering_lists_step)

    schema_export = subs.add_parser(
        "export-structure-schema",
        help="Publish a run-bound Document Structure Discovery & Quality schema snapshot.",
    )
    schema_export.add_argument("--run-dir", required=True)
    schema_export.add_argument("--project", required=True)
    schema_export.add_argument("--orchestration-run-id", required=True)
    schema_export.add_argument("--source-artifact-id", required=True)
    schema_export.add_argument("--workbook", default=None, help="Approved source copy to hash read-only. If omitted, the run-manifest path is used when accessible.")
    schema_export.add_argument("--source-sha256", default=None, help="Expected SHA-256 from the approved artifact registry. If --workbook is supplied, mismatch is fatal.")
    schema_export.add_argument("--contract-version", default="0.2.1")
    schema_export.add_argument("--output", default=None)
    schema_export.set_defaults(func=export_structure_schema_step)

    pub = subs.add_parser(
        "publish-logbook",
        help="Create a controlled cleaned workbook copy and write/validate the canonical Logbook.",
    )
    pub.add_argument("--run-dir", required=True)
    pub.add_argument("--project", default=None)
    pub.add_argument("--output", default=None)
    pub.add_argument("--sheet", default="Logbook")
    pub.add_argument("--allow-issues", action="store_true")
    pub.add_argument("--overwrite", action="store_true")
    pub.set_defaults(func=publish_logbook_step)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
