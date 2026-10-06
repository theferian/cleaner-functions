from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from cleaner_core.solutions import (
    load_project_solutions,
    save_project_solutions,
    sync_project_solutions_from_decisions_file,
    repair_project_solutions_registry,
    make_manual_project_solution,
)


def _default_path(project: str) -> Path:
    return PROJECT_ROOT / "project_solutions" / f"{project}.solutions.json"


def _load_regions(run_dir: str | None):
    if not run_dir:
        return None
    path = Path(run_dir) / "document_regions.json"
    if not path.exists():
        raise SystemExit(f"document_regions.json not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description="Inspect, sync, repair or add persistent project solutions.")
    parser.add_argument("command", choices=["list", "sync", "repair", "add"])
    parser.add_argument("paths", nargs="*", help="Decision JSON files for sync.")
    parser.add_argument("--project", default="AZD")
    parser.add_argument("--registry", default="")
    parser.add_argument("--run-dir", default="", help="Run directory used to enrich solutions with document identity.")

    # Manual migration/add fields.  This is intentionally explicit so a legacy
    # repair can be recovered without hard-coding project data into the engine.
    parser.add_argument("--test-id", default="FIELD_VALIDATION")
    parser.add_argument("--sheet", default="")
    parser.add_argument("--target", default="")
    parser.add_argument("--value", default=None)
    parser.add_argument("--observed", default=None)
    parser.add_argument("--field-role", default="")
    parser.add_argument("--field-key", default="")
    parser.add_argument("--audit-kind", default="")
    parser.add_argument("--reason", default="Manual project-solution migration.")
    args = parser.parse_args()

    path = Path(args.registry) if args.registry else _default_path(args.project)
    registry = load_project_solutions(path, project_id=args.project, create=True)

    if args.command == "sync":
        if not args.paths:
            raise SystemExit("sync requires at least one review_decisions.json file")
        for decision_path in args.paths:
            report = sync_project_solutions_from_decisions_file(registry, decision_path)
            created = report.get("created_handles", [])
            updated = report.get("updated_handles", [])
            print(f"{decision_path}: created={len(created)} updated={len(updated)}")
            for handle in created:
                print(f"  + {handle}")
            for handle in updated:
                print(f"  ~ {handle}")
        save_project_solutions(registry, path)
        print(f"Saved: {path}")
        return

    if args.command == "repair":
        regions = _load_regions(args.run_dir)
        report = repair_project_solutions_registry(
            registry,
            document_regions_payload=regions,
        )
        save_project_solutions(registry, path)
        print(f"Registry : {path}")
        print(f"Active   : {report['active_count']}")
        if report["enriched_handles"]:
            print("Enriched : " + ", ".join(report["enriched_handles"]))
        if report["split_created_handles"]:
            print("Split    : " + ", ".join(report["split_created_handles"]))
        if report["superseded_handles"]:
            print("Retired  : " + ", ".join(report["superseded_handles"]))
        if not any(report[k] for k in ("enriched_handles", "split_created_handles", "superseded_handles")):
            print("No migration changes were required.")
        return

    if args.command == "add":
        if not args.sheet or not args.target or args.value is None:
            raise SystemExit("add requires --sheet, --target and --value")
        regions = _load_regions(args.run_dir)
        solution, is_new = make_manual_project_solution(
            registry,
            test_id=args.test_id,
            sheet=args.sheet,
            target=args.target,
            value=args.value,
            observed=args.observed,
            field_role=args.field_role or None,
            field_key=args.field_key or None,
            audit_kind=args.audit_kind or None,
            document_regions_payload=regions,
            reason=args.reason,
        )
        save_project_solutions(registry, path)
        prefix = "+" if is_new else "~"
        print(f"{prefix} {solution.get('handle')}")
        print(f"Saved: {path}")
        return

    solutions = [x for x in registry.get("solutions", []) if x.get("enabled", True)]
    print(f"Project : {registry.get('project_id')}")
    print(f"Registry: {path}")
    print(f"Active  : {len(solutions)}")
    for item in solutions:
        match = item.get("match") or {}
        identity = match.get("document_identity") or {}
        semantic = match.get("semantic") or {}
        resolution = item.get("resolution") or {}
        params = resolution.get("parameters") or {}
        print(
            f"{item.get('handle')} | {match.get('test_id')} | {match.get('sheet')} | "
            f"name={identity.get('name')!r} | rel={semantic.get('document_relative_target')!r} | "
            f"field={semantic.get('field_key') or semantic.get('field_role') or semantic.get('audit_kind')} | "
            f"{resolution.get('action')} -> {params.get('value', params.get('new_value'))!r}"
        )


if __name__ == "__main__":
    main()
