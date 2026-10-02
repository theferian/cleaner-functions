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
from tests.identifier_check import run as identifier_check
from review.queue import build_review_queue, write_review_queue


def main():
    parser = argparse.ArgumentParser(
        description="Run current AZD health checks against live Excel."
    )
    parser.add_argument("--workbook")
    parser.add_argument(
        "--profile",
        default=str(PROJECT_ROOT / "profiles" / "AZD.profile.json"),
    )
    parser.add_argument("--discover-mline", action="store_true")
    parser.add_argument("--review", action="store_true")
    parser.add_argument("--keep-snapshot", action="store_true")
    args = parser.parse_args()

    logger = RunLogger(stream=True)
    wb = attach_excel_workbook(args.workbook)

    workbook_meta = {
        "name": str(wb.Name),
        "path": str(wb.FullName),
        "saved_state": "saved" if wb.Saved else "unsaved",
    }

    logger("CONNECT", f"Workbook: {workbook_meta['name']}")
    logger("CONNECT", f"Path: {workbook_meta['path']}")
    logger("CONNECT", f"Excel saved state: {workbook_meta['saved_state']}")

    started = time.perf_counter()
    snapshot_path = snapshot_live_workbook(wb)
    logger(
        "TIMING",
        f"Snapshot created in {time.perf_counter() - started:.2f}s: {snapshot_path}"
    )

    profile = load_profile(args.profile)
    manifest = json.loads(
        (PROJECT_ROOT / "cleaner.package.json").read_text(encoding="utf-8")
    )
    snap = load_snapshot(snapshot_path)

    report = RunReport(
        kind="azd_health",
        script_id="AZD_HEALTH",
        snapshot_path=str(snapshot_path),
    )
    run_id = f"azd_health_{datetime.now().strftime('%Y%m%dT%H%M%S')}"

    try:
        if args.discover_mline:
            logger("STAGE", "Running optional M-line profile discovery.")
            report.candidates.extend(discover_m_line(snap, profile, logger))

        logger("STAGE", "Running M_LINE.")
        report.findings.extend(m_line_check(snap, profile, logger))

        logger("STAGE", "Running IDENTIFIERS.")
        report.findings.extend(identifier_check(snap, profile, logger))
    finally:
        snap.close()

    report.logs = logger.records
    payload = report.to_dict()
    payload["run_id"] = run_id

    report_path = PROJECT_ROOT / "azd_health_report.json"
    report_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )

    queue = build_review_queue(
        report=payload,
        profile=profile,
        package_manifest=manifest,
        workbook=workbook_meta,
        report_path=str(report_path),
    )
    queue_path = write_review_queue(
        queue,
        PROJECT_ROOT / "azd_health_review_queue.json",
    )

    print("\n=== FINAL HEALTH REVIEW LIST ===")
    for idx, item in enumerate(queue["items"], start=1):
        suggestion = item.get("machine_suggestion", {}).get("suggested_fix")
        s = ""
        if suggestion:
            p = suggestion.get("parameters", {})
            s = f" => {suggestion['action']} {p.get('target')}={p.get('value')!r}"
        print(
            f"{idx:>2}. {item['source']['test_id']:<12} "
            f"{item['source']['status']:<20} "
            f"{(item['location']['sheet'] or ''):<18} "
            f"{(item['location']['target'] or ''):<12} "
            f"{item['message']}{s}"
        )

    print(f"\n[RAW REPORT]   {report_path}")
    print(f"[REVIEW QUEUE] {queue_path}")

    if args.review:
        subprocess.run(
            [
                sys.executable,
                str(PROJECT_ROOT / "dev" / "review_findings.py"),
                str(queue_path),
                "--decisions",
                str(PROJECT_ROOT / "azd_health_review_decisions.json"),
            ],
            check=False,
        )

    if not args.keep_snapshot:
        Path(snapshot_path).unlink(missing_ok=True)
        logger("SNAPSHOT", "Temporary snapshot deleted.")


if __name__ == "__main__":
    main()
