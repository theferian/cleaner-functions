from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from cleaner_core.profile import load_profile
from cleaner_core.exceptions import (
    load_exception_registry,
    save_exception_registry,
    sync_registry_from_decisions_file,
)


def main():
    parser = argparse.ArgumentParser(
        description="Import existing cleaner review decisions into the project exception registry."
    )
    parser.add_argument("--decisions", required=True)
    parser.add_argument(
        "--profile",
        default=str(PROJECT_ROOT / "profiles" / "AZD.profile.json"),
    )
    parser.add_argument("--registry", default=None)
    args = parser.parse_args()

    profile = load_profile(args.profile)
    profile_name = str(profile.get("profile_name") or "PROJECT")
    registry_path = Path(args.registry) if args.registry else (
        PROJECT_ROOT / "exceptions" / f"{profile_name}.exceptions.json"
    )
    registry = load_exception_registry(
        registry_path,
        profile_name=profile_name,
        create=True,
    )
    report = sync_registry_from_decisions_file(registry, args.decisions)
    save_exception_registry(registry, registry_path)

    print(f"Registry : {registry_path}")
    print(f"Cases    : {report['case_count']}")
    print(f"Updated  : {len(report['updated_handles'])}")
    for handle in report["updated_handles"]:
        case = next(x for x in registry["cases"] if x.get("handle") == handle)
        print(
            f"  {handle} | {case.get('case_state')} | "
            f"{case.get('workflow_status')} | {case.get('title')}"
        )


if __name__ == "__main__":
    main()
