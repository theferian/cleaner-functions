#!/usr/bin/env python3
"""Resume or start one GENERAL_DOCUMENT Cleaner run; halt only at real review gates.

Place this file directly in the cleaner-functions repository root.
No dependencies beyond Python's standard library and the existing Cleaner commands.

Exit codes: 0 = complete; 2 = review required; 1 = execution/contract error.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parent
STAGES = ("M_LINE", "DOCUMENT_BOUNDARIES", "CARD_MAP", "SLOT_SCHEMA", "FIELD_VALIDATION", "IDENTIFIERS")
STATE_NAME = "resolved_state.json"
LOG_NAME = "board_to_log.json"
ENGINEERING_NAME = "engineering_three_lists.json"
RUN_ID_RE = re.compile(r"(?:\[STATE\]\s*)?Run ID\s*:\s*([A-Za-z0-9_.-]+)")
# A decision is not necessarily a repair. Deferred cases need intervention.
ACTIONABLE_DECISIONS = {"SET_VALUE", "REPLACE_VALUE", "CLEAR_CELL", "UNMERGE_RANGE", "MERGE_RANGE", "ACCEPT_EXCEPTION", "TRACK_EXCEPTION", "PROFILE_CHANGE", "TEST_RULE_CHANGE", "MANUAL_FIX"}


def load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("JSON root must be an object")
        return value
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"Cannot read required JSON {path}: {exc}") from exc


def status_line(message: str) -> None:
    print(message, flush=True)


def save_progress(run_dir: Path | None, data: dict[str, Any]) -> None:
    if run_dir is None or not run_dir.is_dir():
        return
    dst = run_dir / "general_doc_auto_progress.json"
    data["last_updated"] = datetime.now().isoformat(timespec="seconds")
    temp = dst.with_suffix(".json.tmp")
    temp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temp.replace(dst)


def run_cmd(command: list[str], *, cwd: Path) -> str:
    env = os.environ.copy()
    # Propagate to CLI-test/Excel subprocesses and suppress needless native BLAS threads.
    for key in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        env[key] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        proc = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, errors="replace", check=False)
    except OSError as exc:
        raise RuntimeError(f"Could not start {command[1]}: {exc}") from exc
    if proc.returncode != 0:
        combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
        last_lines = "\n".join(combined.strip().splitlines()[-35:])
        raise RuntimeError(f"Child exited {proc.returncode}: {' '.join(command[1:3])}\n{last_lines}")
    return (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")


def decisions_complete(run_dir: Path, stage: str) -> bool:
    """True when each item has an explicit correction, acceptance, or tracked decision."""
    queue_path = run_dir / f"{stage.lower()}_review_queue.json"
    decision_path = run_dir / f"{stage.lower()}_review_decisions.json"
    if not queue_path.exists() or not decision_path.exists():
        return False
    queue, decisions = load(queue_path), load(decision_path)
    items = queue.get("items")
    supplied = decisions.get("decisions")
    if not isinstance(items, list) or not isinstance(supplied, list):
        return False
    if not items:
        return False
    by_id = {str(item.get("review_id") or ""): item.get("decision") for item in supplied if isinstance(item, dict)}
    for item in items:
        rid = str(item.get("review_id") or "")
        decision = by_id.get(rid)
        if not rid or not isinstance(decision, dict) or str(decision.get("action") or "").upper() not in ACTIONABLE_DECISIONS:
            return False
    return True


def decision_files(run_dir: Path, previous_stage: str | None) -> list[str]:
    if previous_stage is None:
        return []
    out: list[str] = []
    for stage in STAGES:
        if STAGES.index(stage) > STAGES.index(previous_stage):
            break
        f = run_dir / f"{stage.lower()}_review_decisions.json"
        if f.exists() and decisions_complete(run_dir, stage):
            out += ["--decisions", str(f)]
    return out


def get_stage_status(run_dir: Path, stage: str) -> str | None:
    state_file = run_dir / STATE_NAME
    if not state_file.exists():
        return None
    state = load(state_file)
    return str((state.get("stages") or {}).get(stage, {}).get("status") or "") or None


def raise_review(stage: str, run_dir: Path, *, message: str, count: int = 0) -> None:
    status_line(f"[REVIEW REQUIRED] {stage}: {message}")
    if stage in STAGES:
        queue_path = run_dir / f"{stage.lower()}_review_queue.json"
        decisions_path = run_dir / f"{stage.lower()}_review_decisions.json"
        status_line(f"  Queue: {queue_path}")
        status_line(f'  Review command: py .\\dev\\review_findings.py "{queue_path}" --decisions "{decisions_path}" --accept-known')
    else:
        status_line(f"  Run directory: {run_dir}")
    raise ReviewNeeded(stage, message, count)


class ReviewNeeded(Exception):
    def __init__(self, stage: str, message: str, count: int = 0):
        super().__init__(message)
        self.stage = stage
        self.count = count


def choose_run(args: argparse.Namespace, book: Path, progress: dict[str, Any]) -> tuple[str, Path]:
    if args.run_id:
        run_id = args.run_id
        run_dir = ROOT / "runs" / run_id
        state_path = run_dir / STATE_NAME
        manifest_path = run_dir / "run_manifest.json"
        if not state_path.is_file() or not manifest_path.is_file():
            raise RuntimeError(f"Run not found or incomplete: {run_dir}")
        manifest = load(manifest_path)
        if str(manifest.get("profile_name", "")).upper() != args.project:
            raise RuntimeError(f"Run {run_id} belongs to {manifest.get('profile_name')}, not {args.project}")
        bound_book = Path(str((manifest.get("workbook") or {}).get("path") or ""))
        if os.path.normcase(str(bound_book)).casefold() != os.path.normcase(str(book)).casefold():
            raise RuntimeError(f"Workbook mismatch: run uses {bound_book}; requested {book}")
        return run_id, run_dir
    status_line(f"[START] {args.project}: creating new Cleaner run (M_LINE)")
    cmd = [sys.executable, str(ROOT / "pipeline" / "project_pipeline.py"), "--project", args.project,
           "--workbook", str(book), "--new-run", "--stage", "M_LINE"]
    out = run_cmd(cmd, cwd=ROOT)
    matches = RUN_ID_RE.findall(out)
    if not matches or len(set(matches)) != 1:
        raise RuntimeError("M_LINE finished, but its new run ID could not be determined; do not start another run. Check runs/ for the new directory.\n" + "\n".join(out.splitlines()[-25:]))
    run_id = matches[0]
    run_dir = ROOT / "runs" / run_id
    progress["run_id"] = run_id
    status_line(f"[RUN] {run_id}")
    return run_id, run_dir


def guarded_stage(args: argparse.Namespace, run_id: str, run_dir: Path, book: Path, stage: str) -> None:
    found = get_stage_status(run_dir, stage)
    if found == "REVIEWED":
        status_line(f"[OK] {stage} (already reviewed)")
        return
    if found and found != "REVIEWED":
        if decisions_complete(run_dir, stage):
            status_line(f"[OK] {stage} (review decisions recorded; will be ingested)")
            return
        raise_review(stage, run_dir, message=f"existing stage status {found}; unresolved review decisions")
    # M_LINE is created only by choose_run(). Existing runs should already contain it.
    if stage == "M_LINE":
        raise RuntimeError("Existing run lacks M_LINE. Do not silently create a new run.")
    status_line(f"[RUN] {stage}")
    previous = STAGES[STAGES.index(stage) - 1]
    cmd = [sys.executable, str(ROOT / "pipeline" / "project_pipeline.py"), "--project", args.project,
           "--workbook", str(book), "--run-id", run_id, "--stage", stage]
    cmd += decision_files(run_dir, previous)
    run_cmd(cmd, cwd=ROOT)
    found = get_stage_status(run_dir, stage)
    if found == "REVIEWED":
        status_line(f"[OK] {stage}")
        return
    if found and decisions_complete(run_dir, stage):
        status_line(f"[OK] {stage} (approved decisions present)")
        return
    raise_review(stage, run_dir, message=f"status {found or 'UNKNOWN'} requires operator decision")


def issue_group_summary(board: dict[str, Any]) -> tuple[int, dict[str, int]]:
    issues = board.get("issues") or []
    counts = Counter(str(issue.get("kind") or "UNKNOWN") for issue in issues if isinstance(issue, dict))
    return len(issues), dict(sorted(counts.items()))


def guarded_board_to_log(args: argparse.Namespace, run_dir: Path) -> dict[str, Any]:
    status_line("[RUN] Board->Log")
    cmd = [sys.executable, str(ROOT / "pipeline" / "weekly_report_pipeline.py"), "board-to-log",
           "--run-dir", str(run_dir), "--project", args.project, "--show-issue-context"]
    run_cmd(cmd, cwd=ROOT)
    board = load(run_dir / LOG_NAME)
    count, groups = issue_group_summary(board)
    summary = board.get("summary") or {}
    status_line(f"[BOARD->LOG] records={summary.get('record_count', '?')} issues={count}")
    if count:
        status_line("  Grouped issues: " + ", ".join(f"{kind}={n}" for kind, n in groups.items()))
        issues = board.get("issues") or []
        for issue in issues[:5]:
            status_line(f"  - {issue.get('sheet')}!{issue.get('address')} | {issue.get('kind')} | {str(issue.get('message') or '')[:140]}")
        status_line(f"  Context: {run_dir / 'board_to_log_issue_context.json'}")
        raise_review("BOARD_TO_LOG", run_dir, message=f"{count} extraction issue(s) in {len(groups)} group(s)", count=count)
    return board


def guarded_coverage(args: argparse.Namespace, run_dir: Path) -> dict[str, Any]:
    status_line("[RUN] Coverage Audit")
    cmd = [sys.executable, str(ROOT / "pipeline" / "weekly_report_pipeline.py"), "audit-coverage",
           "--run-dir", str(run_dir), "--project", args.project]
    wb = load(run_dir / "run_manifest.json").get("workbook") or {}
    original = Path(str(wb.get("path") or wb.get("name") or "workbook.xlsx"))
    default_output = run_dir / f"{original.stem}_COVERAGE_AUDIT{original.suffix or '.xlsx'}"
    if default_output.exists():
        # Never overwrite existing audit workbooks. A resumed run gets an additional copy.
        stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
        output = run_dir / f"{original.stem}_COVERAGE_AUDIT_AUTO_{stamp}{original.suffix or '.xlsx'}"
        if output.exists():
            raise RuntimeError(f"Coverage output already exists, refusing overwrite: {output}")
        cmd.extend(["--output", str(output)])
    run_cmd(cmd, cwd=ROOT)
    audit = load(run_dir / "coverage_audit.json")
    summary = audit.get("summary") or {}
    counts = summary.get("counts") or {}
    not_retrieved = int(counts.get("SCANNED_NOT_RETRIEVED", 0))
    unresolved = int(counts.get("UNRESOLVED_ISSUE", 0))
    status_line(f"[COVERAGE] mapped={summary.get('mapped_nonempty_count', '?')} not_retrieved={not_retrieved} unresolved={unresolved}")
    if not_retrieved or unresolved:
        raise_review("COVERAGE", run_dir, message=f"not retrieved={not_retrieved}; unresolved={unresolved}")
    return audit


def guarded_engineering(args: argparse.Namespace, run_dir: Path) -> dict[str, Any]:
    status_line("[RUN] Engineering Lists")
    cmd = [sys.executable, str(ROOT / "pipeline" / "weekly_report_pipeline.py"), "engineering-lists",
           "--run-dir", str(run_dir), "--project", args.project, "--status-date", args.status_date]
    run_cmd(cmd, cwd=ROOT)
    report = load(run_dir / "engineering_lists" / ENGINEERING_NAME)
    summary = report.get("summary") or {}
    diagnostics = int(summary.get("diagnostic_count", len(report.get("diagnostics") or [])))
    status_line(f"[ENGINEERING] not_sent={summary.get('not_sent')} company_delay={summary.get('company_delay')} consultant_delay={summary.get('consultant_delay')} diagnostics={diagnostics}")
    if diagnostics:
        kinds = Counter(str((d or {}).get("reason") or (d or {}).get("code") or (d or {}).get("kind") or "UNCLASSIFIED") for d in (report.get("diagnostics") or []) if isinstance(d, dict))
        status_line("  Diagnostics: " + ", ".join(f"{k}={n}" for k, n in sorted(kinds.items())))
        raise_review("ENGINEERING", run_dir, message=f"{diagnostics} reporting diagnostic(s); engineering outputs are provisional", count=diagnostics)
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run GENERAL_DOCUMENT stages in order; stop only for human review, never silently accept anomalies.")
    p.add_argument("--project", required=True, help="e.g. NKH, EYV, BFG")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--run-id", help="Resume an existing Cleaner run")
    mode.add_argument("--new-run", action="store_true", help="Start a new M_LINE run for the staged working copy")
    p.add_argument("--workbook", default=None, help="Working workbook; default working/GENERAL_DOCUMENT/PROJECT/PROJECT_GENERAL_DOC_CLEANER_WORKING.xlsx")
    p.add_argument("--status-date", required=True, help="Engineering status date, Jalali YYYY/MM/DD")
    args = p.parse_args(argv)
    args.project = args.project.strip().upper()
    if not re.fullmatch(r"[A-Z0-9_]+", args.project):
        p.error("Invalid project code")
    if not re.fullmatch(r"14\d{2}/\d{2}/\d{2}", args.status_date):
        p.error("--status-date must be Jalali YYYY/MM/DD")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    book = Path(args.workbook) if args.workbook else ROOT / "working" / "GENERAL_DOCUMENT" / args.project / f"{args.project}_GENERAL_DOC_CLEANER_WORKING.xlsx"
    if not book.is_absolute():
        book = ROOT / book
    book = book.resolve()
    if not book.is_file():
        status_line(f"[ERROR] Working copy missing: {book}; stage source first. No original files changed.")
        return 1
    progress: dict[str, Any] = {"project": args.project, "status_date": args.status_date, "workbook": str(book), "status": "RUNNING"}
    run_dir: Path | None = None
    try:
        run_id, run_dir = choose_run(args, book, progress)
        progress["run_id"] = run_id
        for stage in STAGES:
            guarded_stage(args, run_id, run_dir, book, stage)
            progress["last_stage"] = stage
            save_progress(run_dir, progress)
        guarded_board_to_log(args, run_dir)
        progress["last_stage"] = "BOARD_TO_LOG"
        save_progress(run_dir, progress)
        guarded_coverage(args, run_dir)
        progress["last_stage"] = "COVERAGE"
        save_progress(run_dir, progress)
        guarded_engineering(args, run_dir)
        progress["last_stage"] = "ENGINEERING"
        progress["status"] = "COMPLETE"
        save_progress(run_dir, progress)
        status_line(f"[COMPLETE] {args.project} {run_id}: no machine-detected review gates; business sign-off is separate")
        return 0
    except ReviewNeeded as exc:
        progress.update({"status": "REVIEW_REQUIRED", "pause_stage": exc.stage, "review_count": exc.count, "note": str(exc)})
        save_progress(run_dir, progress)
        status_line(f"[PAUSED] Review requested; resume with the same --run-id after the correction (do NOT use --new-run).")
        return 2
    except Exception as exc:
        progress.update({"status": "ERROR", "error": str(exc)})
        save_progress(run_dir, progress)
        status_line(f"[ERROR] {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
