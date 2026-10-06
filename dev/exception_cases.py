from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from cleaner_core.profile import load_profile
from cleaner_core.exceptions import load_exception_registry, save_exception_registry


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _registry_path(profile_name: str, explicit: str | None) -> Path:
    if explicit:
        return Path(explicit)
    return PROJECT_ROOT / "exceptions" / f"{profile_name}.exceptions.json"


def _find_case(registry: dict, handle: str) -> dict:
    wanted = handle.strip().upper()
    for case in registry.get("cases", []):
        if str(case.get("handle") or "").upper() == wanted:
            return case
    raise SystemExit(f"Exception case not found: {handle}")


def _print_case(case: dict) -> None:
    match = case.get("match") or {}
    print(f"{case.get('handle')} | {case.get('case_state')} | {case.get('workflow_status')}")
    print(f"Title    : {case.get('title')}")
    print(f"Location : {match.get('sheet')}!{match.get('target')}")
    print(f"Test     : {match.get('test_id')} / {match.get('audit_kind') or '-'}")
    print(f"Severity : {case.get('severity')}")
    print(f"Tags     : {', '.join(case.get('tags') or [])}")
    print(f"Owner    : {case.get('owner') or '-'}")
    print(f"Note     : {case.get('note') or '-'}")
    print(f"First    : {case.get('first_seen_at')}")
    print(f"Last     : {case.get('last_seen_at')}")
    print(f"Detected : {case.get('detection_count', 0)}")


def main():
    parser = argparse.ArgumentParser(description="Inspect and maintain Cleaner exception cases.")
    parser.add_argument(
        "--profile",
        default=str(PROJECT_ROOT / "profiles" / "AZD.profile.json"),
    )
    parser.add_argument("--registry", default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="List exception cases.")
    p_list.add_argument("--state", default="", help="Filter by case_state, e.g. OPEN or RESOLVED.")
    p_list.add_argument("--status", default="", help="Filter by workflow_status, e.g. INVESTIGATE.")

    p_show = sub.add_parser("show", help="Show one exception case.")
    p_show.add_argument("handle")

    p_update = sub.add_parser("update", help="Update workflow metadata for one case.")
    p_update.add_argument("handle")
    p_update.add_argument("--status", default=None, help="Workflow status, e.g. INVESTIGATE or WAITING_INPUT.")
    p_update.add_argument("--state", default=None, help="Case state, e.g. OPEN, RESOLVED, ACCEPTED.")
    p_update.add_argument("--note", default=None)
    p_update.add_argument("--owner", default=None)
    p_update.add_argument("--tags", default=None, help="Comma-separated tags; replaces current tags.")

    args = parser.parse_args()
    profile = load_profile(args.profile)
    profile_name = str(profile.get("profile_name") or "PROJECT")
    path = _registry_path(profile_name, args.registry)
    registry = load_exception_registry(path, profile_name=profile_name, create=True)

    if args.command == "list":
        cases = registry.get("cases", [])
        if args.state:
            cases = [x for x in cases if str(x.get("case_state") or "").upper() == args.state.upper()]
        if args.status:
            cases = [x for x in cases if str(x.get("workflow_status") or "").upper() == args.status.upper()]
        print(f"Registry: {path}")
        print(f"Cases   : {len(cases)}")
        for case in cases:
            match = case.get("match") or {}
            print(
                f"{case.get('handle'):12} | {case.get('case_state'):8} | "
                f"{case.get('workflow_status'):18} | {match.get('sheet')}!{match.get('target')} | "
                f"{case.get('title')}"
            )
        return

    if args.command == "show":
        _print_case(_find_case(registry, args.handle))
        return

    if args.command == "update":
        case = _find_case(registry, args.handle)
        before = {
            "case_state": case.get("case_state"),
            "workflow_status": case.get("workflow_status"),
            "note": case.get("note"),
            "owner": case.get("owner"),
            "tags": list(case.get("tags") or []),
        }
        if args.status is not None:
            case["workflow_status"] = args.status.strip().upper()
        if args.state is not None:
            case["case_state"] = args.state.strip().upper()
        if args.note is not None:
            case["note"] = args.note.strip()
        if args.owner is not None:
            case["owner"] = args.owner.strip()
        if args.tags is not None:
            case["tags"] = [x.strip().lower().replace(" ", "-") for x in args.tags.split(",") if x.strip()]
        case.setdefault("history", []).append({
            "at": _now(),
            "event": "MANUAL_CASE_UPDATE",
            "before": before,
            "after": {
                "case_state": case.get("case_state"),
                "workflow_status": case.get("workflow_status"),
                "note": case.get("note"),
                "owner": case.get("owner"),
                "tags": list(case.get("tags") or []),
            },
        })
        save_exception_registry(registry, path)
        print(f"Updated: {case.get('handle')}")
        _print_case(case)


if __name__ == "__main__":
    main()
