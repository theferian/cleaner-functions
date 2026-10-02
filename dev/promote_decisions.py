from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from cleaner_core.knowledge import promote_decisions_to_profile, save_profile
from cleaner_core.profile import load_profile


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Promote reviewed cleaner decisions into reusable profile knowledge. "
            "Preview is the default; use --apply to update the profile."
        )
    )
    parser.add_argument("decisions", nargs="+", help="One or more review-decision JSON files.")
    parser.add_argument(
        "--profile",
        default=str(PROJECT_ROOT / "profiles" / "AZD.profile.json"),
    )
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    profile_path = Path(args.profile)
    profile = load_profile(profile_path)
    reports = []

    for decision_path in args.decisions:
        path = Path(decision_path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        profile, report = promote_decisions_to_profile(profile, payload)
        report["source_file"] = str(path)
        reports.append(report)

    total_exc = sum(x["promoted_exception_count"] for x in reports)
    total_fix = sum(x["promoted_fix_count"] for x in reports)
    total_skip = sum(x["skipped_count"] for x in reports)

    print("=== REUSABLE KNOWLEDGE PROMOTION ===")
    print(f"Profile              : {profile_path}")
    print(f"Promoted exceptions  : {total_exc}")
    print(f"Promoted known fixes : {total_fix}")
    print(f"Skipped              : {total_skip}")

    for report in reports:
        print(f"\nSource: {report['source_file']}")
        print(
            f"  exceptions={report['promoted_exception_count']} "
            f"fixes={report['promoted_fix_count']} skipped={report['skipped_count']}"
        )
        for item in report["promoted_exceptions"]:
            print(f"  + exception {item['id']} -> {item['match']}")
        for item in report["promoted_fixes"]:
            print(
                f"  + fix {item['id']} -> {item['match']} "
                f"[{item['resolution']['mode']}]"
            )
        for item in report["skipped"]:
            print(f"  - skip {item.get('review_id')}: {item['reason']}")

    if args.apply:
        save_profile(profile, profile_path)
        print(f"\nAPPLIED: reusable knowledge written to {profile_path}")
    else:
        print("\nPREVIEW ONLY: profile was not changed. Re-run with --apply to persist.")


if __name__ == "__main__":
    main()
