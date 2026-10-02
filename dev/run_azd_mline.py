from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from cleaner_core import (
    attach_excel_workbook,
    snapshot_live_workbook,
    load_snapshot,
    load_profile,
    RunReport,
)
from cleaner_core.logging import RunLogger
from discoveries.discover_m_line import run as discover_m_line
from tests.m_line_check import run as m_line_check
from review.queue import build_review_queue, write_review_queue


def main():
    parser = argparse.ArgumentParser(
        description="Run AZD M-line discovery/check against the currently open Excel workbook."
    )
    parser.add_argument(
        "--workbook",
        help="Optional workbook name/path. If omitted, use Excel's active workbook.",
    )
    parser.add_argument(
        "--mode",
        choices=["discover", "check", "both"],
        default="both",
    )
    parser.add_argument(
        "--profile",
        default=str(PROJECT_ROOT / "profiles" / "AZD.profile.json"),
    )
    parser.add_argument(
        "--report",
        default=str(PROJECT_ROOT / "azd_mline_report.json"),
    )
    parser.add_argument(
        "--review-queue",
        default=str(PROJECT_ROOT / "azd_review_queue.json"),
    )
    parser.add_argument(
        "--review",
        action="store_true",
        help="Open the terminal review queue after the run.",
    )
    parser.add_argument(
        "--keep-snapshot",
        action="store_true",
    )
    args = parser.parse_args()

    logger = RunLogger(stream=True)

    logger("CONNECT", "Attaching to running Excel.")
    wb = attach_excel_workbook(args.workbook)

    workbook_meta = {
        "name": str(wb.Name),
        "path": str(wb.FullName),
        "saved_state": "saved" if wb.Saved else "unsaved",
    }

    logger("CONNECT", f"Workbook: {workbook_meta['name']}")
    logger("CONNECT", f"Path: {workbook_meta['path']}")
    logger("CONNECT", f"Excel saved state: {workbook_meta['saved_state']}")

    snapshot_started = time.perf_counter()
    logger("SNAPSHOT", "Creating temporary SaveCopyAs snapshot of the live workbook.")
    snapshot_path = snapshot_live_workbook(wb)
    logger(
        "TIMING",
        f"Excel SaveCopyAs snapshot created in {time.perf_counter() - snapshot_started:.2f}s: {snapshot_path}"
    )

    profile = load_profile(args.profile)
    manifest = json.loads(
        (PROJECT_ROOT / "cleaner.package.json").read_text(encoding="utf-8")
    )
    snap = load_snapshot(snapshot_path)

    report = RunReport(
        kind="azd_mline",
        script_id="AZD_M_LINE",
        snapshot_path=str(snapshot_path),
    )
    report_dict_extra = {
        "run_id": f"azd_mline_{datetime.now().strftime('%Y%m%dT%H%M%S')}",
    }

    try:
        if args.mode in ("discover", "both"):
            started = time.perf_counter()
            logger("STAGE", "Running profile-development discovery.")
            report.candidates.extend(discover_m_line(snap, profile, logger))
            logger(
                "TIMING",
                f"M-line discovery finished in {time.perf_counter() - started:.2f}s."
            )

        if args.mode in ("check", "both"):
            started = time.perf_counter()
            logger("STAGE", "Running profile-driven M-line health check.")
            report.findings.extend(m_line_check(snap, profile, logger))
            logger(
                "TIMING",
                f"M-line health check finished in {time.perf_counter() - started:.2f}s."
            )
    finally:
        snap.close()

    report.logs = logger.records
    report_payload = report.to_dict()
    report_payload.update(report_dict_extra)

    report_path = Path(args.report)
    report_path.write_text(
        json.dumps(report_payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )

    review_queue = build_review_queue(
        report=report_payload,
        profile=profile,
        package_manifest=manifest,
        workbook=workbook_meta,
        report_path=str(report_path),
    )
    review_path = write_review_queue(review_queue, args.review_queue)

    print("\n=== FINAL REVIEW LIST ===")
    if not review_queue["items"]:
        print("(no review items)")
    for idx, item in enumerate(review_queue["items"], start=1):
        print(
            f"{idx:>2}. "
            f"{item['source']['status']:<20} "
            f"{(item['location']['sheet'] or ''):<18} "
            f"{(item['location']['target'] or ''):<16} "
            f"{item['message']}"
        )

    print("\n=== DISCOVERY CANDIDATES ===")
    if not report.candidates:
        print("(none)")
    for candidate in report.candidates:
        print(
            f"{candidate.sheet:<20} "
            f"{candidate.target:<18} "
            f"{candidate.message}"
        )

    print(f"\n[RAW REPORT]   {report_path}")
    print(f"[REVIEW QUEUE] {review_path}")
    print(
        "[NEXT] Review decisions are recorded separately and do not modify "
        "the workbook/profile until a later execution stage."
    )

    if args.review:
        subprocess.run(
            [
                sys.executable,
                str(PROJECT_ROOT / "dev" / "review_findings.py"),
                str(review_path),
            ],
            check=False,
        )

    if not args.keep_snapshot:
        try:
            Path(snapshot_path).unlink(missing_ok=True)
            logger("SNAPSHOT", "Temporary snapshot deleted.")
        except Exception as exc:
            logger("WARNING", f"Could not delete temporary snapshot: {exc}")


if __name__ == "__main__":
    main()
