#!/usr/bin/env python3
"""Review-driven GENERAL_DOCUMENT runner v0.3: mixed issue groups and unsafe review guard.

Place this file directly in the cleaner-functions repository root.
No dependencies beyond Python's standard library and the existing Cleaner commands.

Exit codes: 0 = complete; 2 = review required; 1 = execution/contract error.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
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


def use_interactive(args: argparse.Namespace) -> bool:
    return not args.non_interactive and sys.stdin.isatty()


def prompt_choice(message: str, options: set[str]) -> str:
    """Ask only on a real terminal; caller ensures use_interactive first."""
    while True:
        try:
            choice = input(message).strip().lower()
        except (EOFError, KeyboardInterrupt):
            status_line("\n[PAUSED] Review interrupted; no new decision recorded.")
            return "p"
        if choice in options:
            return choice
        status_line("  Choose " + ", ".join(sorted(options)))


def json_signature(data: Any) -> str:
    """Stable fingerprint so approvals never silently apply to changed evidence."""
    blob = json.dumps(data, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def write_review(path: Path, payload: dict[str, Any]) -> None:
    """Atomic, run-local review audit (never modifies the source workbook)."""
    if path.exists():
        earlier = load(path)
        if earlier.get("evidence_sha256") == payload.get("evidence_sha256"):
            raise RuntimeError(f"Review audit already exists for identical evidence: {path}")
        # Preserve prior sign-off before recording a new decision for changed data.
        history = path.parent / "review_history"
        history.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%dT%H%M%S%f")
        old_hash = str(earlier.get("evidence_sha256") or "unknown")[:12]
        archive = history / f"{path.stem}_{old_hash}_{stamp}.json"
        path.replace(archive)
        status_line(f"[HISTORY] Previous review archived: {archive}")
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def reviewed_evidence(path: Path, signature: str) -> bool:
    if not path.exists():
        return False
    data = load(path)
    return data.get("evidence_sha256") == signature and data.get("decision") == "ACCEPT_WITH_EXCEPTIONS"


def show_grouped_context(contexts: list[dict[str, Any]], *, max_entries: int | None = 10) -> None:
    for context in contexts[:max_entries]:
        issue = context.get("issue") or {}
        identity = context.get("document_identity") or {}
        status_line(f"  {issue.get('sheet')}!{issue.get('address')} | {identity.get('name') or identity.get('doc_name') or 'Unknown document'} | rev={context.get('revision')}")
        for slot in context.get("slots") or []:
            role = str(slot.get("role") or "")
            if role in {"explanation", "receive_date", "status"}:
                status_line(f"    {slot.get('address')} [{role}] {slot.get('value')!r}")


MEETING_MARKERS = ("صورتجلسه", "صورت جلسه", "جلسه")


def meeting_receive_evidence(context: dict[str, Any]) -> bool:
    """Conservative evidence check: no missing SEND reference and no invented response."""
    issue = context.get("issue") or {}
    if issue.get("kind") != "MISSING_REFERENCE" or (issue.get("evidence") or {}).get("side") != "receive":
        return False
    slots = context.get("slots") or []
    meeting = any(
        slot.get("role") == "explanation"
        and slot.get("side_hint") == "receive"
        and any(token in str(slot.get("value") or "") for token in MEETING_MARKERS)
        for slot in slots
    )
    records = context.get("records") or []
    response = any(
        rec.get("send_or_receive") == "receive"
        and rec.get("date_source") == issue.get("address")
        and not rec.get("letter_reference")
        and bool(rec.get("letter_date"))
        and bool(rec.get("doc_status"))
        for rec in records
    )
    return meeting and response


def context_index(run_dir: Path) -> dict[tuple[str, str, str, str], dict[str, Any]]:
    path = run_dir / "board_to_log_issue_context.json"
    try:
        contexts = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cannot inspect board issue evidence: {exc}") from exc
    if not isinstance(contexts, list):
        raise RuntimeError(f"Unexpected board issue context format: {path}")
    def key(issue: dict[str, Any]) -> tuple[str, str, str, str]:
        return (str(issue.get("kind") or ""), str(issue.get("sheet") or ""),
                str(issue.get("address") or ""), str(issue.get("document_index") or ""))
    indexed: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for c in contexts:
        if not isinstance(c, dict):
            continue
        k = key(c.get("issue") or {})
        if k in indexed:
            raise RuntimeError(f"Duplicate issue context: {k}")
        indexed[k] = c
    return indexed


def _review_unsupported_group(args: argparse.Namespace, issues: list[dict[str, Any]], contexts: list[dict[str, Any]], run_dir: Path) -> dict[str, Any]:
    """Require a documented human choice for references not attached to dates."""
    if not issues:
        return {"issue_count": 0, "decision": "NONE"}
    kinds = Counter(str(x.get("kind") or "UNKNOWN") for x in issues)
    status_line("[REVIEW REQUIRED] Additional issues: " + ", ".join(f"{k}={v}" for k, v in sorted(kinds.items())))
    show_grouped_context(contexts, max_entries=len(contexts))
    kinds_allowed = {"ORPHAN_REFERENCE", "MISSING_RECEIVE_STATUS"}
    if not set(kinds).issubset(kinds_allowed):
        raise_review("BOARD_TO_LOG", run_dir, message="Other extraction errors require targeted source correction", count=len(issues))
    if "ORPHAN_REFERENCE" in kinds:
        status_line("  Orphan letter references have no paired SEND/RECEIVE date in the register.")
        for issue in issues:
            if issue.get("kind") == "ORPHAN_REFERENCE":
                status_line(f"    UNPAIRED {issue.get('sheet')}!{issue.get('address')}: {((issue.get('evidence') or {}).get('value'))!r}")
    if "MISSING_RECEIVE_STATUS" in kinds:
        status_line("  Some receive dates lack a status. Reporting responsibility may remain undetermined.")
        status_line("  Do not put a status code into a DATE cell; verify the status lane separately.")
    status_line("  Acceptance preserves these as OPEN issues; it does not invent dates, references, or statuses.")
    if not use_interactive(args):
        raise_review("BOARD_TO_LOG", run_dir, message="Unresolved extraction issues require human decision", count=len(issues))
    choice = prompt_choice("  [a] Accept as OPEN extraction exceptions  [v] Show all source slots  [p] Pause: ", {"a", "v", "p"})
    if choice == "v":
        for ctx in contexts:
            issue = ctx.get("issue") or {}
            status_line(f"  {issue.get('sheet')}!{issue.get('address')}: " + json.dumps(issue.get('evidence') or {}, ensure_ascii=False))
            for slot in ctx.get('slots') or []:
                status_line(f"    {slot.get('address')} {slot.get('role')}: {slot.get('value')!r}")
            for record in ctx.get('records') or []:
                status_line("    RECORD " + json.dumps({k: record.get(k) for k in ('letter_date', 'letter_reference', 'doc_status', 'send_or_receive')}, ensure_ascii=False))
        choice = prompt_choice("  [a] Accept as OPEN exceptions  [p] Pause: ", {"a", "p"})
    if choice != "a":
        raise_review("BOARD_TO_LOG", run_dir, message="Unsupported issue group review deferred", count=len(issues))
    return {"issue_count": len(issues), "decision": "ACKNOWLEDGE_OPEN_UNRESOLVED_EXTRACTION_ISSUES", "issue_kinds": dict(kinds)}


def review_board(args: argparse.Namespace, run_dir: Path, board: dict[str, Any]) -> None:
    issues = board.get("issues") or []
    index = context_index(run_dir)
    signature = json_signature({"project": args.project, "issues": issues,
                                "record_count": (board.get("summary") or {}).get("record_count"),
                                "contexts": [index[k] for k in sorted(index)]})
    evidence_path = run_dir / "board_to_log_review.json"
    if reviewed_evidence(evidence_path, signature):
        status_line(f"[REVIEWED] Board->Log issues unchanged; accepted with exceptions ({len(issues)} issues).")
        return
    if evidence_path.exists():
        status_line("[CHANGED] Evidence changed since previous review; review again.")
    def key(issue: dict[str, Any]) -> tuple[str, str, str, str]:
        return (str(issue.get("kind") or ""), str(issue.get("sheet") or ""),
                str(issue.get("address") or ""), str(issue.get("document_index") or ""))
    contexts = [index.get(key(issue)) for issue in issues]
    if any(c is None for c in contexts):
        raise_review("BOARD_TO_LOG", run_dir, message="Issue context missing. No approval allowed.", count=len(issues))
    paired = list(zip(issues, contexts))
    meeting = [(issue, ctx) for issue, ctx in paired if meeting_receive_evidence(ctx)]
    remaining = [(issue, ctx) for issue, ctx in paired if not meeting_receive_evidence(ctx)]
    approvals: list[dict[str, Any]] = []
    if meeting:
        status_line(f"[PROPOSED REVIEW] {len(meeting)} meeting-based RECEIVE event(s) lack numbered response letters.")
        status_line("  Their dates/statuses and source meeting notes are preserved; extraction issues stay open.")
        show_grouped_context([c for _, c in meeting], max_entries=10)
        if not use_interactive(args):
            raise_review("BOARD_TO_LOG", run_dir, message="Meeting response group requires approval", count=len(meeting))
        choice = prompt_choice("  [a] Approve as OPEN meeting-response exceptions  [v] View source slots  [p] Pause: ", {"a", "v", "p"})
        if choice == "v":
            for _, ctx in meeting:
                issue = ctx.get("issue") or {}
                status_line(f"  {issue.get('sheet')}!{issue.get('address')}")
                for slot in ctx.get('slots') or []:
                    status_line(f"    {slot.get('address')} {slot.get('role')}: {slot.get('value')!r}")
            choice = prompt_choice("  [a] Approve as OPEN meeting-response exceptions  [p] Pause: ", {"a", "p"})
        if choice != "a":
            raise_review("BOARD_TO_LOG", run_dir, message="Meeting response group not approved", count=len(meeting))
        approvals.append({"issue_count": len(meeting), "decision": "ACKNOWLEDGE_MEETING_WITHOUT_LETTER"})
    if remaining:
        approvals.append(_review_unsupported_group(args, [i for i, _ in remaining], [c for _, c in remaining], run_dir))
    write_review(evidence_path, {
        "schema": "general_doc.review/0.3", "project": args.project, "run_id": run_dir.name,
        "stage": "BOARD_TO_LOG", "decision": "ACCEPT_WITH_EXCEPTIONS", "scope": "THIS_RUN_ONLY",
        "classification": "MIXED_REVIEWED_EXCEPTIONS" if remaining else "MEETING_BASED_RECEIVE_WITHOUT_FORMAL_REFERENCE",
        "issue_count": len(issues), "issue_kinds": dict(Counter(str(i.get('kind') or 'UNKNOWN') for i in issues)),
        "evidence_sha256": signature, "decided_at": datetime.now().isoformat(timespec="seconds"),
        "note": "Human reviewed each grouped category. All extractor issues remain visible; no fabricated status/date/reference.",
        "group_approvals": approvals,
        "sources": [{"sheet": c["issue"].get("sheet"), "address": c["issue"].get("address"),
                     "issue_kind": c["issue"].get("kind"), "evidence": c["issue"].get("evidence")}
                    for c in contexts],
    })
    status_line(f"[APPROVED WITH EXCEPTIONS] {len(issues)} source-slot issues remain open; audit: {evidence_path}")


def guard_wrong_field_replacement(run_dir: Path) -> None:
    """Don't let a missing-status finding be 'fixed' by overwriting its date."""
    path = run_dir / 'field_validation_review_decisions.json'
    if not path.exists():
        return
    payload = load(path)
    bad = []
    for item in payload.get('decisions') or []:
        message = str(item.get('message') or '')
        if not ('Receive date' in message and 'no populated corresponding status' in message):
            continue
        decision = item.get('decision') or {}
        action = str(decision.get('action') or '')
        if action not in {'SET_VALUE', 'REPLACE_VALUE', 'CLEAR_CELL'}:
            continue
        params = decision.get('parameters') or {}
        location = item.get('location') or {}
        if str(params.get('sheet') or '').upper() == str(location.get('sheet') or '').upper() and str(params.get('target') or '').upper() == str(location.get('target') or '').upper():
            bad.append(f"{location.get('sheet')}!{location.get('target')} -> {params.get('new_value', params.get('value'))!r}")
    if bad:
        raise_review('FIELD_VALIDATION', run_dir, message='Unsafe status-repair decision overwrites a RECEIVE DATE: ' + ', '.join(bad))


def review_engineering(args: argparse.Namespace, run_dir: Path, report: dict[str, Any]) -> bool:
    diagnostics = report.get("diagnostics") or []
    signature = json_signature({"project": args.project, "status_date": args.status_date, "diagnostics": diagnostics,
                                "summary": report.get("summary")})
    path = run_dir / "engineering_review.json"
    if reviewed_evidence(path, signature):
        status_line(f"[REVIEWED] {len(diagnostics)} reporting diagnostic(s) unchanged; report remains provisional.")
        return True
    if path.exists():
        status_line("[CHANGED] Reporting diagnostics differ from previous approval; new acknowledgement required.")
    counts = Counter(str(d.get("reason") or d.get("code") or d.get("kind") or "UNCLASSIFIED") for d in diagnostics if isinstance(d, dict))
    status_line("[REPORT REVIEW] " + ", ".join(f"{kind}={n}" for kind, n in sorted(counts.items())))
    if not use_interactive(args):
        return False
    choice = prompt_choice("  [a] Acknowledge provisional report with open diagnostics  [v] View diagnostics  [p] Pause: ", {"a", "v", "p"})
    if choice == "v":
        for d in diagnostics:
            status_line("  " + json.dumps(d, ensure_ascii=False, default=str))
        choice = prompt_choice("  [a] Acknowledge provisional report  [p] Pause: ", {"a", "p"})
    if choice != "a":
        return False
    write_review(path, {
        "schema": "general_doc.review/0.2", "project": args.project, "run_id": run_dir.name,
        "stage": "ENGINEERING", "decision": "ACCEPT_WITH_EXCEPTIONS", "scope": "THIS_RUN_AND_STATUS_DATE_ONLY",
        "status_date": args.status_date, "diagnostic_count": len(diagnostics),
        "evidence_sha256": signature, "decided_at": datetime.now().isoformat(timespec="seconds"),
        "note": "Reviewer acknowledged provisional report; diagnostics remain open and are not marked resolved.",
    })
    status_line(f"[ACKNOWLEDGED] {len(diagnostics)} reporting diagnostics remain open: {path}")
    return True


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


def interactive_stage_review(args: argparse.Namespace, run_dir: Path, stage: str) -> bool:
    if not use_interactive(args):
        return False
    queue = run_dir / f"{stage.lower()}_review_queue.json"
    decisions = run_dir / f"{stage.lower()}_review_decisions.json"
    if not queue.is_file():
        raise RuntimeError(f"Review queue missing: {queue}")
    status_line(f"[REVIEW] {stage}: launching existing Cleaner review interface.")
    cmd = [sys.executable, str(ROOT / "dev" / "review_findings.py"), str(queue),
           "--decisions", str(decisions), "--accept-known"]
    if args.no_excel_navigation:
        cmd.append("--no-excel-navigation")
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        env[name] = "1"
    # Inherit stdin/stdout; the reviewer must be fully interactive.
    rc = subprocess.run(cmd, cwd=ROOT, env=env, check=False).returncode
    if rc != 0:
        raise RuntimeError(f"Review interface exited with code {rc}")
    return decisions_complete(run_dir, stage)


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
        if interactive_stage_review(args, run_dir, stage):
            status_line(f"[REVIEWED] {stage} decisions recorded; continuing.")
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
    if interactive_stage_review(args, run_dir, stage):
        status_line(f"[REVIEWED] {stage} decisions recorded; continuing.")
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
        review_board(args, run_dir, board)
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
        stamp = datetime.now().strftime("%Y%m%dT%H%M%S%f")
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
    if not_retrieved:
        raise_review("COVERAGE", run_dir, message=f"not retrieved={not_retrieved} (not eligible for acceptance by Board issue review)")
    if unresolved:
        # Coverage marks acknowledged Board->Log problems as UNRESOLVED_ISSUE;
        # they must remain visible. A run-local approval can permit moving to
        # provisional reporting without falsely claiming zero issues.
        board = load(run_dir / LOG_NAME)
        issues = board.get("issues") or []
        contexts = context_index(run_dir)
        fingerprint = json_signature({"project": args.project, "issues": issues,
                                      "record_count": (board.get("summary") or {}).get("record_count"),
                                      "contexts": [contexts[k] for k in sorted(contexts)]})
        approved = reviewed_evidence(run_dir / "board_to_log_review.json", fingerprint)
        if not approved or unresolved != len(issues):
            raise_review("COVERAGE", run_dir, message=f"unresolved={unresolved}; no matching Board issue acceptance", count=unresolved)
        status_line(f"[COVERAGE] {unresolved} source-slot issue(s) remain visible; accepted for provisional continuation only.")
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
        if not review_engineering(args, run_dir, report):
            raise_review("ENGINEERING", run_dir, message=f"{diagnostics} reporting diagnostic(s); report is provisional", count=diagnostics)
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run GENERAL_DOCUMENT stages in order; stop only for human review, never silently accept anomalies.")
    p.add_argument("--project", required=True, help="e.g. NKH, EYV, BFG")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--run-id", help="Resume an existing Cleaner run")
    mode.add_argument("--new-run", action="store_true", help="Start a new M_LINE run for the staged working copy")
    p.add_argument("--workbook", default=None, help="Working workbook; default working/GENERAL_DOCUMENT/PROJECT/PROJECT_GENERAL_DOC_CLEANER_WORKING.xlsx")
    p.add_argument("--status-date", required=True, help="Engineering status date, Jalali YYYY/MM/DD")
    p.add_argument("--non-interactive", action="store_true", help="Never prompt; stop at review gates with exit 2")
    p.add_argument("--no-excel-navigation", action="store_true", help="Do not jump to Excel cells while reviewing")
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
        guard_wrong_field_replacement(run_dir)
        board = guarded_board_to_log(args, run_dir)
        progress["last_stage"] = "BOARD_TO_LOG"
        save_progress(run_dir, progress)
        guarded_coverage(args, run_dir)
        progress["last_stage"] = "COVERAGE"
        save_progress(run_dir, progress)
        report = guarded_engineering(args, run_dir)
        progress["last_stage"] = "ENGINEERING"
        open_exceptions = bool(board.get("issues") or report.get("diagnostics"))
        progress["status"] = "COMPLETE_WITH_REVIEWED_EXCEPTIONS" if open_exceptions else "COMPLETE"
        save_progress(run_dir, progress)
        status_line(f"[{progress['status']}] {args.project} {run_id}; business sign-off remains separate")
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
