#!/usr/bin/env python3
"""Review-driven GENERAL_DOCUMENT runner v0.6: evidence-rich diagnostic review and terminal severity colours.

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


# Colours are presentation-only: audit/log files stay readable plain text.
ANSI = {"PASS": "\x1b[32m", "RUN": "\x1b[36m", "REVIEW": "\x1b[33m",
        "ERROR": "\x1b[31m", "WARN": "\x1b[35m", "INFO": "\x1b[34m",
        "DIM": "\x1b[90m", "RESET": "\x1b[0m"}
COLOR_MODE = "auto"
EVENT_LOG: Path | None = None


def enable_windows_ansi() -> bool:
    if os.name != "nt":
        return True
    try:
        import ctypes
        kernel = ctypes.windll.kernel32
        handle = kernel.GetStdHandle(-11)
        mode = ctypes.c_uint()
        if not kernel.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        if mode.value & 0x0004:
            return True
        return bool(kernel.SetConsoleMode(handle, mode.value | 0x0004))
    except (AttributeError, OSError):
        return False


def colors_enabled() -> bool:
    if COLOR_MODE == "never" or os.environ.get("NO_COLOR") is not None:
        return False
    if COLOR_MODE == "always":
        return True
    return sys.stdout.isatty() and os.environ.get("TERM") != "dumb" and enable_windows_ansi()


def line_level(message: str) -> str:
    tag = re.match(r"^\[([^]]+)\]", message)
    label = tag.group(1) if tag else ""
    if label in {"ERROR", "FAIL", "STOP"}: return "ERROR"
    if label in {"PAUSED", "REVIEW", "REVIEW REQUIRED", "REPORT REVIEW", "DIAGNOSTIC", "CELL REVIEW AVAILABLE"}: return "REVIEW"
    if label in {"OK", "PASS", "DONE", "COMPLETE", "COMPLETE_WITH_REVIEWED_EXCEPTIONS", "ACKNOWLEDGED", "REVIEWED", "APPLIED TO RUN OVERLAY"}: return "PASS"
    if label in {"RUN", "START", "RECHECK"}: return "RUN"
    if label in {"CHANGED", "HISTORY", "WARNING", "COVERAGE", "BOARD->LOG"}:
        return "WARN" if ("unresolved=" in message and "unresolved=0" not in message) or label in {"WARNING", "CHANGED"} else "INFO"
    return "DIM" if not message.strip() else "INFO"


def style(message: str, level: str | None = None) -> str:
    category = level or line_level(message)
    if not colors_enabled():
        return message
    # Colour the tag/prefix, not every character of long source paths or data.
    match = re.match(r"^(\[[^]]+\]|\s{0,2}\d+[.)])", message)
    if not match:
        return ANSI[category] + message + ANSI["RESET"] if message.strip() else message
    return ANSI[category] + match.group(0) + ANSI["RESET"] + message[match.end():]


def status_line(message: str) -> None:
    print(style(message), flush=True)
    if EVENT_LOG is not None:
        with EVENT_LOG.open("a", encoding="utf-8") as log:
            log.write(f"{datetime.now().isoformat(timespec='seconds')} | {line_level(message)} | {message}\n")


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
            choice = input(style(message, "REVIEW")).strip().lower()
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


# BOARD_TO_LOG_CELL_REVIEW_V04
class BoardRepairApplied(Exception):
    """A verified run-local change was recorded; the extractor must run again."""


def _effective_source_cell(run_dir: Path, sheet: str, address: str) -> tuple[Any, Any]:
    """Return current logical and original workbook values for a single source cell."""
    from openpyxl import load_workbook
    from openpyxl.utils.cell import coordinate_from_string
    coordinate_from_string(address)  # Refuse ranges/invalid targets for this workflow.
    manifest = load(run_dir / 'run_manifest.json')
    source_path = Path(str((manifest.get('workbook') or {}).get('path') or ''))
    if not source_path.is_file():
        raise RuntimeError('Cannot verify working workbook for cell-level review: '+str(source_path))
    wb = load_workbook(source_path, read_only=True, data_only=False)
    try:
        if sheet not in wb.sheetnames:
            raise RuntimeError(f'Unknown source sheet {sheet}')
        original = wb[sheet][address].value
    finally:
        wb.close()
    state = load(run_dir / STATE_NAME)
    override = (state.get('value_overrides') or {}).get(f'{sheet}!{address}'.upper())
    current = override['value'] if override is not None else original
    return current, original


def _make_board_cell_review_queue(args: argparse.Namespace, run_dir: Path, issue: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Adapt a Board->Log issue to the same queue contract as standard Cleaner reviews."""
    sheet, address = str(issue.get('sheet') or ''), str(issue.get('address') or '')
    observed, original = _effective_source_cell(run_dir, sheet, address)
    source_observed = (issue.get('evidence') or {}).get('value')
    if source_observed is not None and str(observed) != str(source_observed):
        raise RuntimeError(f'Unsafe/stale review target {sheet}!{address}: current={observed!r}, issue={source_observed!r}')
    manifest = load(run_dir / 'run_manifest.json')
    identity = context.get('document_identity') or {}
    review_id = f"BOARD_TO_LOG_{re.sub('[^A-Za-z0-9]+', '_', sheet)}_{address}_{json_signature(issue)[:12]}"
    message = (f"{issue.get('kind')}: {identity.get('name') or identity.get('doc_name') or 'document'}; "
               f"source {sheet}!{address}={observed!r}. Review this source cell, not the entire issue group.")
    item = {
        'review_id': review_id, 'review_state': 'PENDING',
        'source': {'kind': 'TEST_FINDING', 'test_id': 'BOARD_TO_LOG', 'status': 'FAIL', 'severity': 'HIGH'},
        'location': {'sheet': sheet, 'target': address},
        'message': message, 'observed': observed, 'expected': 'Correct source value or documented exception',
        'evidence': {'source_value': original, 'issue_kind': issue.get('kind'),
                     'source_issue': issue, 'source_context': context},
        'machine_suggestion': {},
        'current_policy': {'state': 'UNRESOLVED_ERROR', 'note': 'A human decision is required. Workbook original is not changed by this reviewer.'},
    }
    return {
        'schema': 'cleaner.review_queue/0.1',
        'package': {'package_id': 'cleaner_functions', 'package_version': '0.4.0',
                    'review_schema': '0.1', 'decision_schema': '0.1'},
        'run': {'run_id': run_dir.name, 'script_id': 'BOARD_TO_LOG', 'kind': 'board_to_log'},
        'profile': {'family': 'GENERAL_DOCUMENT', 'profile_name': args.project},
        'workbook': manifest.get('workbook') or {},
        'summary': {'total_items': 1, 'by_status': {'FAIL': 1}, 'pending_review': 1, 'resolved': 0, 'deferred': 0},
        'items': [item],
    }


def _archive_repair_evidence(run_dir: Path, sheet: str, address: str, decision: dict[str, Any]) -> Path:
    """Retain the pre-correction extraction and every previous review artifact."""
    import shutil
    history = run_dir / 'board_to_log_repair_history'
    stamp = datetime.now().strftime('%Y%m%dT%H%M%S%f')
    folder = history / f'{stamp}_{re.sub("[^A-Za-z0-9]+", "_", sheet)}_{address}'
    folder.mkdir(parents=True, exist_ok=False)
    for name in ('board_to_log.json', 'board_to_log_issues.csv', 'board_to_log_issue_context.json',
                 'board_to_log_review.json', 'resolved_state.json', 'board_to_log_review_queue.json',
                 'board_to_log_repair_decisions.json'):
        existing = run_dir / name
        if existing.is_file():
            shutil.copy2(existing, folder / name)
    (folder / 'decision.json').write_text(json.dumps(decision, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    return folder


def _run_board_cell_reviewer(args: argparse.Namespace, run_dir: Path, issue: dict[str, Any], context: dict[str, Any]) -> None:
    """Use the established interactive Cleaner reviewer, then ingest a guarded overlay."""
    queue = _make_board_cell_review_queue(args, run_dir, issue, context)
    queue_path = run_dir / 'board_to_log_review_queue.json'
    decision_path = run_dir / 'board_to_log_repair_decisions.json'
    # The auditor archives prior evidence on successful repair. Do not reuse stale decisions.
    if decision_path.exists():
        old_decisions = load(decision_path)
        ids = {x.get('review_id') for x in old_decisions.get('decisions') or []}
        if ids == {queue['items'][0]['review_id']}:
            status_line('[REVIEW] Existing decision for this exact evidence; reopening as a new interactive review.')
        # Retain prior decisions even if this attempt is paused or interrupted.
        hist = run_dir / 'board_to_log_repair_history' / 'previous_reviews'
        hist.mkdir(parents=True, exist_ok=True)
        tag = datetime.now().strftime('%Y%m%dT%H%M%S%f')
        import shutil
        shutil.copy2(decision_path, hist / (f'board_review_{tag}.json'))
    queue_path.write_text(json.dumps(queue, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    if decision_path.exists():
        decision_path.unlink()
    status_line(f"[REVIEW] Opening Cleaner reviewer for {issue.get('sheet')}!{issue.get('address')}")
    cmd = [sys.executable, str(ROOT / 'dev' / 'review_findings.py'), str(queue_path), '--decisions', str(decision_path),
           '--project-solutions', str(run_dir / 'board_to_log_run_solutions.json')]
    if args.no_excel_navigation:
        cmd.append('--no-excel-navigation')
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    for key in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):
        env[key] = '1'
    rc = subprocess.run(cmd, cwd=ROOT, env=env, check=False).returncode
    if rc != 0 or not decision_path.exists():
        raise_review('BOARD_TO_LOG', run_dir, message='Cell review not completed', count=1)
    decisions = load(decision_path).get('decisions') or []
    if len(decisions) != 1 or decisions[0].get('review_id') != queue['items'][0]['review_id']:
        raise_review('BOARD_TO_LOG', run_dir, message='Cell review has no matching decision', count=1)
    dec = decisions[0]['decision']
    action = str(dec.get('action') or '').upper()
    if action not in {'REPLACE_VALUE', 'SET_VALUE', 'CLEAR_CELL'}:
        status_line(f'[REVIEW] {action}: recorded in individual review file, not a source correction.')
        raise_review('BOARD_TO_LOG', run_dir, message='Individual decision recorded; no automatic source correction was applied', count=1)
    params = dec.get('parameters') or {}
    sheet, address = str(issue.get('sheet') or ''), str(issue.get('address') or '')
    if params.get('sheet') != sheet or params.get('target') != address:
        raise RuntimeError('Guard failed: reviewer targeted a different source cell.')
    current, original = _effective_source_cell(run_dir, sheet, address)
    expected = params.get('expected_old_value')
    # SET_VALUE is also allowed, but only with the exact original/current precondition.
    if expected is None and action == 'SET_VALUE':
        expected = decisions[0].get('observed')
        params['expected_old_value'] = expected
    if expected is None or str(expected) != str(current):
        raise RuntimeError(f'Guard failed at {sheet}!{address}: expected_old_value={expected!r}, actual={current!r}. '
                           'Use REPLACE_VALUE and enter the exact old value.')
    new_value = params.get('new_value') if action == 'REPLACE_VALUE' else (None if action == 'CLEAR_CELL' else params.get('value'))
    if new_value is not None and str(new_value) == str(current):
        raise_review('BOARD_TO_LOG', run_dir, message='New value is unchanged; nothing to re-extract', count=1)
    # Save the corrected decision precondition so the audit and executor agree.
    dec['parameters'] = params
    payload = load(decision_path)
    payload['decisions'][0]['decision'] = dec
    decision_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    folder = _archive_repair_evidence(run_dir, sheet, address, payload)
    from cleaner_core.state import ingest_review_decisions, save_resolved_state
    state_path = run_dir / STATE_NAME
    state = load(state_path)
    ingest_review_decisions(state, payload)
    save_resolved_state(state, state_path)
    status_line(f'[APPLIED TO RUN OVERLAY] {sheet}!{address}: {current!r} -> {new_value!r}; source workbook unchanged')
    status_line(f'[DISCOVERY HISTORY] {folder}')
    raise BoardRepairApplied()


def offer_board_issue_edit(args: argparse.Namespace, run_dir: Path, board: dict[str, Any]) -> None:
    """Give user individual cell-edit option BEFORE accepting an entire issue group."""
    issues = board.get('issues') or []
    candidates = [issue for issue in issues if issue.get('kind') == 'ORPHAN_REFERENCE']
    if not candidates or not use_interactive(args):
        return
    status_line(f'[CELL REVIEW AVAILABLE] {len(candidates)} orphan source observation(s).')
    for idx, issue in enumerate(candidates, 1):
        status_line(f"  {idx}. {issue.get('sheet')}!{issue.get('address')} {((issue.get('evidence') or {}).get('value'))!r}")
    choice = prompt_choice('  [e] Open individual Cleaner reviewer  [a] Continue to exception review  [p] Pause: ', {'e','a','p'})
    if choice == 'p':
        raise_review('BOARD_TO_LOG', run_dir, message='Cell-level review deferred', count=len(candidates))
    if choice != 'e':
        return
    selected = 0
    if len(candidates) > 1:
        while True:
            token = input(f'  Issue number [1-{len(candidates)}] (default 1): ').strip() or '1'
            if token.isdigit() and 1 <= int(token) <= len(candidates):
                selected = int(token)-1
                break
            status_line('  Invalid issue number.')
    issue = candidates[selected]
    context = context_index(run_dir)
    key = (str(issue.get('kind') or ''),str(issue.get('sheet') or ''),
           str(issue.get('address') or ''),str(issue.get('document_index') or ''))
    found = context.get(key)
    if not found:
        raise RuntimeError('Board review context missing for '+str(key))
    _run_board_cell_reviewer(args, run_dir, issue, found)


def force_board_cell_review(args: argparse.Namespace, run_dir: Path, board: dict[str, Any]) -> None:
    """Reopen a particular orphan cell even after the entire issue group was accepted.

    Deliberately checks a live issue and its source evidence; old acceptance is not
    removed until extraction is re-run and the new evidence is evaluated.
    """
    address = str(args.edit_board_cell or "").upper()
    if not address:
        return
    matches = [i for i in board.get("issues") or []
               if str(i.get("address") or "").upper() == address
               and i.get("kind") == "ORPHAN_REFERENCE"]
    if len(matches) != 1:
        raise_review("BOARD_TO_LOG", run_dir,
                     message=f"--edit-board-cell {address} matched {len(matches)} ORPHAN_REFERENCE issue(s); "
                             "expected exactly one. No previous approval or source was changed.",
                     count=len(matches))
    issue = matches[0]
    key = (str(issue.get('kind') or ''), str(issue.get('sheet') or ''),
           str(issue.get('address') or ''), str(issue.get('document_index') or ''))
    context = context_index(run_dir).get(key)
    if context is None:
        raise_review("BOARD_TO_LOG", run_dir, message=f"No evidence context for {key}; cannot edit", count=1)
    status_line(f"[FORCED CELL REVIEW] {issue.get('sheet')}!{address}: opening individual Cleaner reviewer "
                "even though this issue group was previously acknowledged.")
    _run_board_cell_reviewer(args, run_dir, issue, context)


def review_board(args: argparse.Namespace, run_dir: Path, board: dict[str, Any]) -> None:
    issues = board.get("issues") or []
    index = context_index(run_dir)
    signature = json_signature({"project": args.project, "issues": issues,
                                "record_count": (board.get("summary") or {}).get("record_count"),
                                "contexts": [index[k] for k in sorted(index)]})
    evidence_path = run_dir / "board_to_log_review.json"
    if not reviewed_evidence(evidence_path, signature):
        offer_board_issue_edit(args, run_dir, board)
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


DIAGNOSTIC_GUIDANCE = {
    "SOURCE_SEQUENCE_DATE_INVERSION": (
        "Source-order dates go backwards between consecutive recorded interactions.",
        "Compare the original event dates and references; correct a typo only with source evidence."
    ),
    "SAME_DAY_DIRECTION_ORDER_UNVERIFIED": (
        "A send and receive share a date; their actual order cannot be proven from dates alone.",
        "Verify chronology using the correspondence register or letter timestamps."
    ),
    "UNRESOLVED_UNDATED_EVENT_ORDER": (
        "An event without a verified date might affect which response is latest.",
        "Find the missing date or reference in original correspondence; do not guess."
    ),
    "UNKNOWN_RECEIVE_STATUS": (
        "The response status is absent, unrecognized, or cannot be assigned meaning safely.",
        "Verify the status in the consultant response and enter it in the status field, not a date field."
    ),
}


class EngineeringRepairApplied(Exception):
    """An engineering review changed the run-local source overlay; recompute downstream outputs."""


def diagnostic_kind(d: dict[str, Any]) -> str:
    return str(d.get("reason") or d.get("code") or d.get("kind") or "UNCLASSIFIED")


def diagnostic_identity(d: dict[str, Any]) -> str:
    return f"{d.get('source_sheet') or '?'} | {str(d.get('doc_name') or 'Unnamed').replace(chr(10),' ')[:67]} | WBS={d.get('doc_wbs') or 'NONE'}"


def diagnostic_summary(d: dict[str, Any], idx: int) -> str:
    kind = diagnostic_kind(d)
    detail = ""
    ex = (d.get("examples") or [])
    if kind == "SOURCE_SEQUENCE_DATE_INVERSION" and ex:
        x=ex[0]; detail=f" | dates: {x.get('earlier_source_date')} -> {x.get('later_source_date')}"
    elif kind == "SAME_DAY_DIRECTION_ORDER_UNVERIFIED":
        detail=f" | {d.get('letter_date') or 'unknown date'}"
    elif kind == "UNRESOLVED_UNDATED_EVENT_ORDER":
        detail=f" | latest dated: {d.get('latest_dated_event') or '?'}"
    elif kind == "UNKNOWN_RECEIVE_STATUS":
        detail=f" | response: {d.get('value') or d.get('status') or 'blank'}"
    return f" {idx:>3}. {kind} | {diagnostic_identity(d)}{detail}"


def relevant_records(run_dir: Path, d: dict[str, Any]) -> list[dict[str, Any]]:
    board_path = run_dir / LOG_NAME
    if not board_path.is_file():
        return []
    board = load(board_path)
    matches=[]
    for rec in board.get('records') or []:
        if not isinstance(rec, dict): continue
        if str(rec.get('source_sheet')) != str(d.get('source_sheet')): continue
        if rec.get('document_index') != d.get('document_index'): continue
        matches.append(rec)
    return sorted(matches, key=lambda r:(r.get('source_row') or 0,r.get('source_col') or 0,str(r.get('date_source') or '')))


def diagnostic_details(run_dir: Path, d: dict[str, Any], idx: int, total: int) -> list[dict[str, Any]]:
    kind=diagnostic_kind(d)
    why, next_step=DIAGNOSTIC_GUIDANCE.get(kind,('This diagnostic is not yet classified.', 'Inspect the source and preserve this item for a project-team review.'))
    status_line(f"[DIAGNOSTIC] {idx}/{total} {kind}")
    status_line(f"  Document: {diagnostic_identity(d)}")
    for key, title in [('revision','Revision'),('responsible_unit','Unit'),('status','Status'),('value','Observed value'),('count','Occurrences')]:
        val=d.get(key)
        if val is not None: status_line(f"  {title}: {val}")
    status_line(f"  Meaning: {why}")
    status_line(f"  Follow-up: {next_step}")
    if d.get('examples'):
        for ex in d['examples'][:8]:
            status_line('  Date/order evidence: '+json.dumps(ex, ensure_ascii=False, default=str))
    if d.get('events'):
        for event in d['events'][:10]:
            status_line('  Direction evidence: '+json.dumps(event, ensure_ascii=False, default=str))
    records=relevant_records(run_dir,d)
    status_line(f"  Source events ({len(records)}; original board order, not inferred chronology):")
    for i,rec in enumerate(records[:24],1):
        status_line(f"   {i:>2}. {str(rec.get('send_or_receive') or '?').upper():7} "
                    f"date={rec.get('letter_date') or '-'} [{rec.get('date_source') or '-'}] "
                    f"ref={rec.get('letter_reference') or '-'} [{rec.get('reference_source') or '-'}] "
                    f"status={rec.get('doc_status') or '-'} [{rec.get('status_source') or '-'}]")
    if len(records)>24: status_line(f"  ... +{len(records)-24} more source events")
    return records


def engineering_candidate_cells(records: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    choices=[]; seen=set()
    for rec in records:
        sheet=str(rec.get('source_sheet') or '')
        for field,label in (('date_source','DATE'),('reference_source','REFERENCE'),('status_source','STATUS')):
            address=str(rec.get(field) or '').split(':',1)[0]
            # For a merged status range, propose its top-left anchor only.
            if not re.fullmatch(r'[A-Za-z]{1,3}[1-9][0-9]{0,6}',address):continue
            key=(sheet,address.upper())
            if key not in seen:
                seen.add(key); choices.append((sheet,address.upper(),label))
    return choices


def edit_engineering_cell(args: argparse.Namespace, run_dir: Path, d: dict[str, Any], records: list[dict[str, Any]]) -> None:
    choices=engineering_candidate_cells(records)
    if not choices:
        status_line('[WARNING] No unambiguous editable cell detected; preserve as investigation.')
        return
    status_line('[REVIEW] Exact source-cell correction. Original workbook is never modified.')
    for i,(sheet,address,label) in enumerate(choices,1):
        value,original=_effective_source_cell(run_dir,sheet,address)
        status_line(f'  {i}. {sheet}!{address} [{label}] current={value!r} original={original!r}')
    token=input(style('  Cell number (Enter cancels): ','REVIEW')).strip()
    if not token: return
    if not token.isdigit() or not 1 <= int(token) <= len(choices):
        status_line('[WARNING] Invalid cell selection; no change made.')
        return
    sheet, address, label=choices[int(token)-1]
    observed,_ = _effective_source_cell(run_dir,sheet,address)
    pseudo_issue={'kind':'ENGINEERING_DIAGNOSTIC', 'sheet':sheet, 'address':address,
                  'document_index':d.get('document_index'), 'evidence':{'value':observed}}
    context={'issue':pseudo_issue,'document_identity':{'name':d.get('doc_name')},
             'revision':d.get('revision'), 'records':records, 'slots':[]}
    try:
        _run_board_cell_reviewer(args,run_dir,pseudo_issue,context)
    except BoardRepairApplied as exc:
        raise EngineeringRepairApplied('Recalculate after verified engineering source-cell correction') from exc


def engineering_case_key(diagnostic:dict[str,Any], index:int) -> str:
    return json_signature({'ordinal':index,'diagnostic':diagnostic})


def save_engineering_case_review(run_dir:Path, signature:str, diagnostic:dict[str,Any], index:int, action:str, note:str='') -> None:
    path=run_dir/'engineering_case_reviews.json'
    data=load(path) if path.exists() else {'schema':'general_doc.engineering_case_reviews/0.1','cases':{}}
    cases=data.setdefault('cases',{})
    digest=engineering_case_key(diagnostic,index)
    if digest in cases:
        data.setdefault('history',[]).append(cases[digest])
    cases[digest]={'evidence_sha256':digest,'report_sha256':signature,'diagnostic':diagnostic,
                   'action':action, 'note':note, 'decided_at':datetime.now().isoformat(timespec='seconds')}
    tmp=path.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    tmp.replace(path)


def review_engineering(args: argparse.Namespace, run_dir: Path, report: dict[str, Any]) -> bool:
    diagnostics = [d for d in (report.get('diagnostics') or []) if isinstance(d,dict)]
    signature = json_signature({'project':args.project,'status_date':args.status_date,
                                'diagnostics':diagnostics,'summary':report.get('summary')})
    review_path = run_dir/'engineering_review.json'
    if reviewed_evidence(review_path,signature) and not getattr(args,'review_engineering',False):
        status_line(f'[REVIEWED] {len(diagnostics)} unchanged reporting findings remain open; provisional report retained.')
        return True
    counts=Counter(diagnostic_kind(d) for d in diagnostics)
    status_line(f'[REPORT REVIEW] {args.project} | {args.status_date} | {len(diagnostics)} open diagnostic(s)')
    for kind,count in sorted(counts.items()):
        meaning=DIAGNOSTIC_GUIDANCE.get(kind,('Unclassified: investigate.',))[0]
        status_line(f'  {kind}: {count} | {meaning}')
    for i,d in enumerate(diagnostics[:10],1):
        status_line(diagnostic_summary(d,i))
    if len(diagnostics)>10:status_line(f'  ... {len(diagnostics)-10} more (choose [l] to list every case).')
    if not use_interactive(args):
        return False
    saved=run_dir/'engineering_case_reviews.json'
    while True:
        decisions=load(saved).get('cases',{}) if saved.exists() else {}
        marked=sum(engineering_case_key(d,i) in decisions and decisions[engineering_case_key(d,i)].get('report_sha256')==signature for i,d in enumerate(diagnostics,1))
        status_line(f'[REVIEW] {marked}/{len(diagnostics)} individual case decisions recorded. Open findings are never erased.')
        status_line('  [r] Review one case  [l] List all  [a] Acknowledge remaining as OPEN (confirmation)  [p] Pause')
        choice=prompt_choice('  Select: ',{'r','l','a','p'})
        if choice=='p':return False
        if choice=='l':
            for i,d in enumerate(diagnostics,1):status_line(diagnostic_summary(d,i))
            continue
        if choice=='r':
            token=input(style(f'  Case number [1-{len(diagnostics)}] (Enter cancels): ','REVIEW')).strip()
            if not token:continue
            if not token.isdigit() or not 1<=int(token)<=len(diagnostics):
                status_line('[WARNING] Invalid case number.'); continue
            ix=int(token)-1; d=diagnostics[ix]
            records=diagnostic_details(run_dir,d,ix+1,len(diagnostics))
            status_line('  [e] Edit exact source cell  [m] Mark for project-team investigation')
            status_line('  [a] Acknowledge THIS finding provisionally  [b] Back')
            action=prompt_choice('  Decision: ',{'e','m','a','b'})
            if action=='b':continue
            if action=='e':
                edit_engineering_cell(args,run_dir,d,records)
                continue
            if action=='m':
                note=input(style('  Investigation note (required): ','REVIEW')).strip()
                if not note:
                    status_line('[WARNING] Empty note; no decision recorded.');continue
                save_engineering_case_review(run_dir,signature,d,ix+1,'INVESTIGATE',note)
                status_line('[REVIEWED] Investigation request recorded; diagnostic remains open.')
                continue
            save_engineering_case_review(run_dir,signature,d,ix+1,'ACKNOWLEDGE_OPEN')
            status_line('[REVIEWED] Individual acknowledgement recorded; diagnostic remains open.')
            continue
        # Bulk acknowledgement is explicit, evidence-bound, and not a correction.
        remaining=[(i,d) for i,d in enumerate(diagnostics,1) if engineering_case_key(d,i) not in decisions or decisions[engineering_case_key(d,i)].get('report_sha256')!=signature]
        status_line(f'[REVIEW] {len(remaining)} unreviewed case(s); all will remain OPEN in reporting.')
        for i,d in remaining:status_line(diagnostic_summary(d,i))
        confirmation=input(style('  Type ACKNOWLEDGE to accept these OPEN findings provisionally (Enter cancels): ','REVIEW')).strip()
        if confirmation!='ACKNOWLEDGE':
            status_line('[PAUSED] Bulk acknowledgement cancelled.');continue
        for i,d in remaining: save_engineering_case_review(run_dir,signature,d,i,'ACKNOWLEDGE_OPEN')
        final=load(saved).get('cases',{}) if saved.exists() else {}
        known={engineering_case_key(d,i) for i,d in enumerate(diagnostics,1)}
        if any(digest not in final or final[digest].get('report_sha256')!=signature for digest in known):
            status_line('[WARNING] Some cases are not recorded; no report approval.');continue
        # If a previous sign-off has identical evidence, archive before intentional re-review.
        if review_path.exists() and reviewed_evidence(review_path,signature):
            import shutil
            history=run_dir/'review_history';history.mkdir(exist_ok=True)
            archive=history/f'engineering_review_manual_reopen_{datetime.now().strftime("%Y%m%dT%H%M%S%f")}.json'
            shutil.copy2(review_path,archive);review_path.unlink()
            status_line(f'[HISTORY] Previous sign-off archived: {archive}')
        write_review(review_path,{
            'schema':'general_doc.review/0.6','project':args.project,'run_id':run_dir.name,
            'stage':'ENGINEERING','decision':'ACCEPT_WITH_EXCEPTIONS','scope':'THIS_RUN_AND_STATUS_DATE_ONLY',
            'status_date':args.status_date,'diagnostic_count':len(diagnostics),'evidence_sha256':signature,
            'decided_at':datetime.now().isoformat(timespec='seconds'),
            'individual_case_review_file':str(saved),
            'case_review_counts':dict(Counter(final[digest]['action'] for digest in known)),
            'note':'Evidence reviewed; dates/statuses unchanged unless individually corrected. All diagnostics remain open for project teams.'})
        status_line(f'[ACKNOWLEDGED] {len(diagnostics)} open reporting findings; auditable review: {review_path}')
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
    forced_review_attempted = False
    for attempt in range(1, 13):
        status_line('[RUN] Board->Log' + (f' (recheck {attempt})' if attempt > 1 else ''))
        cmd = [sys.executable, str(ROOT / 'pipeline' / 'weekly_report_pipeline.py'), 'board-to-log',
               '--run-dir', str(run_dir), '--project', args.project, '--show-issue-context']
        run_cmd(cmd, cwd=ROOT)
        board = load(run_dir / LOG_NAME)
        count, groups = issue_group_summary(board)
        summary = board.get('summary') or {}
        status_line(f"[BOARD->LOG] records={summary.get('record_count', '?')} issues={count}")
        if count:
            status_line('  Grouped issues: ' + ', '.join(f'{k}={v}' for k,v in groups.items()))
            for issue in (board.get('issues') or [])[:5]:
                status_line(f"  - {issue.get('sheet')}!{issue.get('address')} | {issue.get('kind')} | {str(issue.get('message') or '')[:140]}")
            status_line(f"  Context: {run_dir / 'board_to_log_issue_context.json'}")
            try:
                if args.edit_board_cell and not forced_review_attempted:
                    forced_review_attempted = True
                    force_board_cell_review(args, run_dir, board)
                review_board(args, run_dir, board)
            except BoardRepairApplied:
                status_line('[RECHECK] Reviewed cell correction saved; rerunning Board->Log before further decisions.')
                continue
        elif args.edit_board_cell and not forced_review_attempted:
            status_line('[ALREADY RESOLVED] No Board->Log issue remains at '
                        f'{args.edit_board_cell}; the forced review was not opened.')
            forced_review_attempted = True
        return board
    raise RuntimeError('Too many consecutive Board->Log repair cycles (12); review the run manually.')


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
    for attempt in range(1,9):
        status_line('[RUN] Engineering Lists'+(f' (recheck {attempt})' if attempt>1 else ''))
        cmd=[sys.executable,str(ROOT/'pipeline'/'weekly_report_pipeline.py'),'engineering-lists',
             '--run-dir',str(run_dir),'--project',args.project,'--status-date',args.status_date]
        run_cmd(cmd,cwd=ROOT)
        report=load(run_dir/'engineering_lists'/ENGINEERING_NAME)
        summary=report.get('summary') or {}
        diagnostics=int(summary.get('diagnostic_count',len(report.get('diagnostics') or [])))
        status_line(f"[ENGINEERING] not_sent={summary.get('not_sent')} company_delay={summary.get('company_delay')} "
                    f"consultant_delay={summary.get('consultant_delay')} diagnostics={diagnostics}")
        if not diagnostics:return report
        try:
            if not review_engineering(args,run_dir,report):
                raise_review('ENGINEERING',run_dir,message=f'{diagnostics} reporting diagnostic(s); review pending',count=diagnostics)
            return report
        except EngineeringRepairApplied:
            status_line('[RECHECK] Engineering correction recorded; re-extracting Board->Log and Coverage before retry.')
            guarded_board_to_log(args,run_dir)
            guarded_coverage(args,run_dir)
    raise_review('ENGINEERING',run_dir,message='Maximum 8 source correction cycles; resume current run after inspecting audit history.')


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
    p.add_argument("--review-engineering", action="store_true", help="Reopen engineering diagnostics even when previously acknowledged")
    p.add_argument("--color", choices=("auto","always","never"), default="auto", help="Terminal colours; file logs are always plain text")
    p.add_argument("--edit-board-cell", default=None, metavar="CELL",
                   help="Force single-cell review of an ORPHAN_REFERENCE, even if accepted before (e.g. G7)")
    args = p.parse_args(argv)
    args.project = args.project.strip().upper()
    if not re.fullmatch(r"[A-Z0-9_]+", args.project):
        p.error("Invalid project code")
    if not re.fullmatch(r"14\d{2}/\d{2}/\d{2}", args.status_date):
        p.error("--status-date must be Jalali YYYY/MM/DD")
    if args.review_engineering and args.non_interactive:
        p.error("--review-engineering requires interactive review")
    if args.edit_board_cell:
        args.edit_board_cell = args.edit_board_cell.strip().upper()
        if not re.fullmatch(r"[A-Z]{1,3}[1-9][0-9]{0,6}", args.edit_board_cell):
            p.error("--edit-board-cell must be one Excel cell, e.g. G7")
        if args.non_interactive:
            p.error("--edit-board-cell requires interactive review")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    global COLOR_MODE, EVENT_LOG
    COLOR_MODE = args.color
    EVENT_LOG = None
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
        EVENT_LOG = run_dir / "general_doc_console.log"
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
