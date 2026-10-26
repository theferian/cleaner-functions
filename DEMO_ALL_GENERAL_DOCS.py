#!/usr/bin/env python3
"""Multi-project General Document demo orchestration v0.3 for cleaner-functions.

Uses the repo's existing registered retrieval and RUN_GENERAL_DOCUMENT_V06.py.
Original network workbooks are never modified. Stdlib only.

Exit 0 = all selected reports complete; 2 = at least one review/incomplete;
1 = system/contract failure. Other projects continue when one cannot proceed.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime
import hashlib
import html
import json
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "DEMO_ALL_GENERAL_DOCS_CONFIG.json"
OUTPUTS = (
    ("not_sent", "01_Not_Sent.csv", "ALL_01_Not_Sent.csv"),
    ("company_delay", "02_Company_Delay.csv", "ALL_02_Company_Delay.csv"),
    ("consultant_delay", "03_Consultant_Delay.csv", "ALL_03_Consultant_Delay.csv"),
)
KNOWN_OPTIONAL = ("04_Delay_Register.csv", "engineering_three_lists.json")
RUNNER = "RUN_GENERAL_DOCUMENT_BATCH_V03.py"
PREPARER = ROOT / "pipeline" / "weekly_report_pipeline.py"


def read_json(path: Path) -> dict[str, Any]:
    result = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(result, dict):
        raise ValueError(f"Not a JSON object: {path}")
    return result


def write_json(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    temp.replace(path)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def path_same(a: Path, b: Path) -> bool:
    return os.path.normcase(os.path.abspath(str(a))).casefold() == os.path.normcase(os.path.abspath(str(b))).casefold()


def cmd_log(command: list[str], log: Path) -> int:
    log.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    for key in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        env[key] = "1"
    with log.open("w", encoding="utf-8") as f:
        f.write("COMMAND: " + json.dumps(command, ensure_ascii=False) + "\n\n")
        f.flush()
        try:
            proc = subprocess.run(command, cwd=ROOT, stdin=subprocess.DEVNULL,
                                  stdout=f, stderr=subprocess.STDOUT, env=env, check=False)
            f.write(f"\nEXIT_CODE: {proc.returncode}\n")
            return proc.returncode
        except OSError as exc:
            f.write(f"\nOS_ERROR: {exc}\n")
            return 1


def candidate_books(project: str) -> list[Path]:
    """Only trusted prior retrieval naming convention; no broad network guessing."""
    incoming = ROOT / "input"
    if not incoming.is_dir():
        return []
    # Exact project token prevents SHY/FSH and BFG/NKH mix-ups.
    pat = re.compile(rf"(?:^|[_-]){re.escape(project)}(?:[_-])LATEST_GENERAL_DOC(?:[_-]|\.)", re.I)
    return [p for p in incoming.rglob("*.xlsx")
            if p.is_file() and pat.search(p.name) and not p.name.startswith("~$")]


def jalali_suffix(path: Path) -> int:
    matches = re.findall(r"(?<!\d)(14\d{6})(?!\d)", path.stem)
    return max((int(x) for x in matches), default=-1)


def _prepare_receipt(pdir: Path, project: str) -> dict[str, str]:
    """Use the exact workbook selected by prepare-general-doc; mtime is not freshness.

    The PREPARE command can preserve the source workbook modification timestamp.
    Never compare its file mtime to the subprocess log creation time.
    """
    log = pdir / "retrieval.log"
    if not log.is_file():
        return {}
    content = log.read_text(encoding="utf-8-sig", errors="replace")
    if not re.search(r"(?m)^EXIT_CODE:\s*0\s*$", content):
        return {}
    def field(key: str) -> str:
        match = re.search(r"(?im)^\[PREPARE\]\s+" + re.escape(key) + r"\s*:\s*(.*?)\s*$", content)
        return match.group(1).strip() if match else ""
    if field("Project").upper() != project:
        return {}
    raw = field("Retrieved")
    if not raw:
        return {}
    # Prepare normally emits a relative input\PROJECT.xlsx path.
    candidate = Path(raw.replace("\\", os.sep))
    if not candidate.is_absolute():
        candidate = ROOT / candidate
    candidate = candidate.resolve()
    input_dir = (ROOT / "input").resolve()
    if not candidate.is_relative_to(input_dir) or not candidate.is_file():
        return {}
    if candidate.suffix.lower() != ".xlsx" or candidate.name.startswith("~$"):
        return {}
    if candidate not in candidate_books(project):
        return {}
    return {"file": str(candidate), "original": field("Source"),
            "manifest": field("Manifest"), "source_filename": PureWindowsPath(field("Source")).name,
            "selection": "PREPARER_SUCCESSFUL_RETRIEVAL"}


def resolve_source(project: str, cfg: dict[str, Any], state: dict[str, Any], pdir: Path,
                   do_retrieve: bool) -> tuple[Path | None, str]:
    # Source is frozen per batch, independently of later changes on network shares.
    if state.get("snapshot"):
        snap = Path(state["snapshot"])
        if not snap.is_file() or sha256(snap) != state.get("sha256"):
            raise RuntimeError("Existing batch source snapshot missing/changed. No automatic restart.")
        return snap, "RESUMED_VERIFIED_SNAPSHOT"

    mode = cfg.get("mode", "registered")
    if mode == "path":
        p = Path(cfg.get("path") or "")
        if not p.is_file():
            return None, f"MISSING_EXPLICIT_SOURCE: {p}"
        state["source_original_filename"] = p.name
        state["retrieval_time"] = datetime.now().astimezone().isoformat(timespec="seconds")
        state["source_original_path"] = str(p.resolve())
        return p, "CONFIGURED_EXPLICIT_SOURCE"
    if mode != "registered":
        raise RuntimeError(f"Unknown source mode {mode!r}")

    if do_retrieve:
        if not PREPARER.is_file():
            return None, f"MISSING_RETRIEVAL_COMMAND: {PREPARER}"
        rc = cmd_log([sys.executable, str(PREPARER), "prepare-general-doc", "--project", project,
                      "--overwrite"], pdir / "retrieval.log")
        if rc:
            return None, f"RETRIEVAL_FAILED ({rc}); see retrieval.log"
    receipt = _prepare_receipt(pdir, project)
    if receipt:
        src = Path(receipt["file"])
        # A successful prepare selects this workbook, even when old in content.
        # Re-validate the bytes against the upstream source when accessible.
        original = Path(receipt["original"]) if receipt["original"] else None
        if original is not None and original.is_file() and sha256(original) != sha256(src):
            return None, "RETRIEVAL_HASH_MISMATCH_WITH_NETWORK_SOURCE"
        state.update(source_original_path=receipt["original"],
                     source_original_filename=receipt["source_filename"],
                     retrieval_manifest=receipt["manifest"],
                     retrieved_input=receipt["file"],
                     retrieval_time=datetime.now().astimezone().isoformat(timespec="seconds"))
        return src, receipt["selection"]
    if do_retrieve:
        return None, "PREPARE_SUCCEEDED_BUT_CANNOT_VERIFY_RETRIEVED_PATH; see retrieval.log"
    # Explicit --skip-retrieval fallback: select latest present named candidate,
    # regardless of document age. Mark it as unverified for formal source signoff.
    books = candidate_books(project)
    if not books:
        return None, "NO_RETRIEVED_WORKBOOK"
    books.sort(key=lambda p: (jalali_suffix(p), p.stat().st_mtime_ns, p.name), reverse=True)
    state.update(retrieved_input=str(books[0].resolve()),
                 source_original_filename=books[0].name,
                 retrieval_time="NOT_RECORDED_EXISTING_INPUT")
    return books[0], "PREEXISTING_INPUT_BY_DATE_TOKEN_UNVERIFIED"


def snapshot_source(src: Path, pdir: Path, state: dict[str, Any], selected_by: str) -> Path:
    stamp = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%f%z")
    dest = pdir / "source" / f"{stamp}__{src.name}"
    h = sha256(src)
    if dest.exists():
        if sha256(dest) != h:
            raise RuntimeError("Snapshot collision with different content; start another batch")
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        temp = dest.with_name(dest.name + ".tmp")
        try:
            shutil.copyfile(src, temp)
            if sha256(temp) != h:
                raise RuntimeError("Source snapshot SHA256 mismatch")
            temp.replace(dest)
        finally:
            temp.unlink(missing_ok=True)
    state.update(snapshot=str(dest.resolve()), sha256=h,
                 original_source=state.get("source_original_path") or str(src.resolve()),
                 source_selection=selected_by,
                 source_filename=state.get("source_original_filename") or src.name,
                 retrieved_filename=src.name,
                 source_modified=datetime.fromtimestamp(src.stat().st_mtime).isoformat(timespec="seconds"))
    return dest


def find_run(project: str, book: Path) -> tuple[str | None, dict[str, Any]]:
    runs = ROOT / "runs"
    if not runs.exists():
        return None, {}
    found: list[tuple[float, Path, dict[str, Any]]] = []
    for p in runs.glob("*/run_manifest.json"):
        try:
            m = read_json(p)
            w = Path(str((m.get("workbook") or {}).get("path") or ""))
            if str(m.get("profile_name") or "").upper() == project and path_same(w, book):
                found.append((p.stat().st_mtime, p.parent, m))
        except (OSError, ValueError, TypeError):
            continue
    if not found:
        return None, {}
    found.sort(reverse=True, key=lambda x: x[0])
    return found[0][1].name, found[0][2]


def run_one(project: str, cfg: dict[str, Any], batch: Path,
            date: str, *, do_retrieve: bool, run_cleaner: bool, interactive: bool = False) -> dict[str, Any]:
    pdir = batch / "projects" / project
    pdir.mkdir(parents=True, exist_ok=True)
    sfile = pdir / "state.json"
    state = read_json(sfile) if sfile.exists() else {"project": project, "status_date": date}
    if state.get("status_date") != date:
        state.update(status="ERROR", reason="Status date changed inside batch; start a new batch")
        write_json(sfile, state)
        return state
    try:
        source, method = resolve_source(project, cfg, state, pdir, do_retrieve)
        if not source:
            state.update(status="SOURCE_REVIEW", reason=method)
            write_json(sfile, state)
            return state
        if not state.get("snapshot"):
            book = snapshot_source(source, pdir, state, method)
        else:
            book = source
        state.update(status="SOURCE_STAGED", reason="")
        write_json(sfile, state)
        if not run_cleaner:
            return state
        rid = state.get("run_id")
        if rid:
            cmd = [sys.executable, str(ROOT / RUNNER), "--project", project,
                   "--run-id", rid, "--workbook", str(book), "--status-date", date,
                   *([] if interactive else ["--non-interactive"])]
        else:
            cmd = [sys.executable, str(ROOT / RUNNER), "--project", project,
                   "--new-run", "--workbook", str(book), "--status-date", date,
                   *([] if interactive else ["--non-interactive"])]
        if interactive:
            print("[INTERACTIVE] Cleaner review / stage run:", project, flush=True)
            rc = subprocess.run(cmd, cwd=ROOT, check=False).returncode
            with (pdir / "cleaner.log").open("a", encoding="utf-8") as f:
                f.write(f"\nINTERACTIVE_COMMAND: {json.dumps(cmd, ensure_ascii=False)}\nEXIT_CODE: {rc}\n")
        else:
            rc = cmd_log(cmd, pdir / "cleaner.log")
        found_id, _ = find_run(project, book)
        if not rid and found_id:
            state["run_id"] = found_id
        elif rid and found_id != rid:
            raise RuntimeError("Existing run no longer uniquely matches the staged workbook")
        progress_path = ROOT / "runs" / str(state.get("run_id")) / "general_doc_auto_progress.json"
        progress = read_json(progress_path) if state.get("run_id") and progress_path.is_file() else {}
        state["review_items"] = progress.get("review_items", [])
        status = str(progress.get("status") or ("COMPLETE" if rc == 0 else "REVIEW_REQUIRED" if rc == 2 else "ERROR"))
        state.update(status=status, returncode=rc, last_stage=progress.get("last_stage", ""),
                     pause_stage=progress.get("pause_stage", ""), reason=progress.get("note") or progress.get("error") or "")
        write_json(sfile, state)
        return state
    except Exception as exc:
        state.update(status="ERROR", reason=str(exc))
        write_json(sfile, state)
        return state


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return [dict(r) for r in reader]


def write_csv(path: Path, rows: list[dict[str, Any]], preferred: list[str] | None = None) -> None:
    fields = list(preferred or [])
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    if not fields:
        fields = ["project"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _rows_from_report(obj: dict[str, Any], key: str) -> list[dict[str, Any]] | None:
    """Strict fallback for reports whose writer exposes JSON lists but not CSVs."""
    containers = [obj]
    for tag in ("lists", "results", "output"):
        if isinstance(obj.get(tag), dict):
            containers.append(obj[tag])
    for container in containers:
        value = container.get(key)
        if isinstance(value, list) and all(isinstance(item, dict) for item in value):
            return value
    return None


def _csv_candidate(eng: Path, key: str, expected: str) -> Path | None:
    exact = eng / expected
    if exact.is_file():
        return exact
    # Support export-name differences without interpreting the report itself.
    for f in sorted(eng.glob('*.csv')):
        normalized = re.sub(r'[^a-z0-9]+', '_', f.stem.lower()).strip('_')
        if key in normalized:
            return f
    return None


def gather(batch: Path, projects: list[str], cfg: dict[str, dict[str, Any]]) -> dict[str, Any]:
    portfolio: dict[str, Any] = {"generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                                  "projects": [], "lists": {}, "diagnostics": [], "reviews": []}
    concatenated = {key: [] for key, _, _ in OUTPUTS}
    for project in projects:
        pdir = batch / "projects" / project
        statepath = pdir / "state.json"
        s = read_json(statepath) if statepath.is_file() else {"project": project, "status": "NOT_RUN"}
        rid = s.get("run_id")
        run_dir = ROOT / "runs" / str(rid) if rid else None
        eng = run_dir / "engineering_lists" if run_dir else None
        dest = pdir / "outputs"
        entry: dict[str, Any] = {k: s.get(k, "") for k in (
            "project", "status", "run_id", "status_date", "sha256", "source_filename", "original_source",
            "source_modified", "source_selection", "retrieval_time", "retrieved_input", "retrieved_filename",
            "pause_stage", "last_stage", "reason")}
        entry["alias"] = cfg[project].get("alias", "")
        entry["source_original_filename"] = s.get("source_original_filename") or s.get("source_filename") or ""
        snapshot = Path(s["snapshot"]) if s.get("snapshot") else None
        entry["source_link"] = (snapshot.relative_to(batch).as_posix()
                                if snapshot is not None and snapshot.is_file() and snapshot.is_relative_to(batch) else "")
        receipt = _prepare_receipt(pdir, project)
        if receipt and not entry.get("retrieved_input"):
            # A previous preflight may have succeeded before the old controller rejected it.
            entry.update(retrieved_input=receipt["file"],
                         retrieved_filename=Path(receipt["file"]).name,
                         source_original_filename=receipt["source_filename"],
                         original_source=receipt["original"])
            log = pdir / "retrieval.log"
            entry["retrieval_time"] = "LOG_TIMESTAMP: " + datetime.fromtimestamp(log.stat().st_mtime).isoformat(timespec="seconds")
            entry["source_selection"] = "PREPARE_SUCCEEDED_SNAPSHOT_NOT_YET_STAGED"
        entry["retrieval_state"] = ("SNAPSHOT_VERIFIED" if snapshot and snapshot.is_file() and
                                    sha256(snapshot) == s.get("sha256") else
                                    "RETRIEVED_NOT_YET_STAGED" if receipt else "NOT_RETRIEVED")
        entry["report_available"] = False
        entry["report_status"] = "NOT_CALCULATED"
        summary: dict[str, Any] = {}
        report: dict[str, Any] = {}
        if eng and (eng / "engineering_three_lists.json").is_file():
            try:
                report = read_json(eng / "engineering_three_lists.json")
                summary = report.get("summary") or {}
                dest.mkdir(parents=True, exist_ok=True)
                shutil.copy2(eng / "engineering_three_lists.json", dest / "engineering_three_lists.json")
                entry["report_available"] = True
                for d in report.get("diagnostics") or []:
                    portfolio["diagnostics"].append({"project": project, "run_id": rid,
                                                     "detail": json.dumps(d, ensure_ascii=False, default=str)})
            except (OSError, ValueError) as exc:
                entry["report_parse_issue"] = str(exc)
        list_found = 0
        for key, filename, _ in OUTPUTS:
            source = _csv_candidate(eng, key, filename) if eng and eng.is_dir() else None
            rows = None
            if source:
                try:
                    rows = read_csv(source)
                except (UnicodeError, csv.Error, OSError) as exc:
                    entry[f"{key}_error"] = str(exc)
            elif report:
                rows = _rows_from_report(report, key)
            if rows is not None:
                dest.mkdir(parents=True, exist_ok=True)
                # Always publish the canonical filename in the project output folder.
                write_csv(dest / filename, rows)
                list_found += 1
                concatenated[key].extend([{**row, "project": project, "run_id": rid,
                                           "source_sha256": s.get("sha256", ""),
                                           "source_filename": entry.get("source_original_filename", ""),
                                           "retrieval_time": entry.get("retrieval_time", "")} for row in rows])
                entry[key] = len(rows)
            else:
                entry[key] = ""  # Not calculated is NOT zero.
        if eng and eng.is_dir():
            for filename in KNOWN_OPTIONAL[:1]:
                optional_file = eng / filename
                if optional_file.is_file():
                    dest.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(optional_file, dest / filename)
        if list_found == 3:
            entry["report_status"] = ("PROVISIONAL_REVIEW_PENDING" if s.get("status") in
                                      {"REVIEW_REQUIRED", "COMPLETE_WITH_REVIEWED_EXCEPTIONS"} else "CALCULATED")
        elif list_found:
            entry["report_status"] = "PARTIAL_OUTPUTS"
        elif report:
            entry["report_status"] = "REPORT_JSON_WITHOUT_LIST_ROWS"
        if list_found == 3 and not str(s.get("status", "")).startswith("COMPLETE"):
            entry["report_status"] = "PROVISIONAL_REVIEW_PENDING"
        entry["diagnostic_count"] = summary.get("diagnostic_count", "") if report else ""
        entry["review_queue_link"] = ""
        if run_dir and run_dir.is_dir():
            ev = pdir / "evidence"
            # Preserve all audits, worksheets, queues, decisions and nested evidence.
            shutil.copytree(run_dir, ev, dirs_exist_ok=True)
            for extra in ("board_to_log.json", "coverage_audit.json", "run_manifest.json", "general_doc_auto_progress.json"):
                f = run_dir / extra
                if f.is_file():
                    ev.mkdir(exist_ok=True)
                    shutil.copy2(f, ev / extra)
            for f in sorted(run_dir.glob('*_review_queue.json')):
                ev.mkdir(exist_ok=True)
                shutil.copy2(f, ev / f.name)
                if (s.get("pause_stage") or "").lower() in f.name.lower():
                    entry["review_queue_link"] = (ev / f.name).relative_to(batch).as_posix()
            if not entry["review_queue_link"]:
                queue_files = sorted(ev.glob('*_review_queue.json')) if ev.exists() else []
                if queue_files:
                    entry["review_queue_link"] = queue_files[-1].relative_to(batch).as_posix()
            entry["run_evidence_link"] = ((ev / "run_manifest.json").relative_to(batch).as_posix()
                                         if (ev / "run_manifest.json").is_file() else "")
        else:
            entry["run_evidence_link"] = ""
        entry["cleaner_log_link"] = ((pdir / "cleaner.log").relative_to(batch).as_posix()
                                     if (pdir / "cleaner.log").is_file() else "")
        entry["retrieval_log_link"] = ((pdir / "retrieval.log").relative_to(batch).as_posix()
                                       if (pdir / "retrieval.log").is_file() else "")
        # Collect actual queues without assuming every JSON schema uses "items".
        if run_dir and run_dir.is_dir():
            for queue in sorted(run_dir.rglob('*review_queue.json')):
                try:
                    payload = read_json(queue)
                    items = payload.get('items')
                    if not isinstance(items, list):
                        items = payload.get('findings')
                    if isinstance(items, list) and items:
                        for item in items:
                            portfolio['reviews'].append(dict(project=project, run_id=rid, kind='QUEUE_EVIDENCE',
                                stage=queue.stem, detail=json.dumps(item, ensure_ascii=False),
                                evidence=(pdir/'evidence'/queue.relative_to(run_dir)).relative_to(batch).as_posix()))
                except (OSError, ValueError) as exc:
                    portfolio['reviews'].append(dict(project=project, run_id=rid, kind='EVIDENCE_ERROR', detail=str(exc)))
        for item in s.get('review_items', []):
            portfolio['reviews'].append(dict(project=project, run_id=rid, kind='OPEN_GATE', **item))
        if not str(s.get('status', '')).startswith('COMPLETE'):
            portfolio['reviews'].append(dict(project=project, run_id=rid, kind='PROJECT_ACTION',
                stage=s.get('pause_stage', ''), detail=s.get('reason') or s.get('status'),
                evidence=entry.get('review_queue_link') or entry.get('cleaner_log_link') or entry.get('retrieval_log_link')))
        entry['audit_index'] = (pdir/'evidence'/'FILES.csv').relative_to(batch).as_posix() if run_dir and run_dir.is_dir() else ''
        if run_dir and run_dir.is_dir():
            write_csv(pdir/'evidence'/'FILES.csv', [dict(file=f.relative_to(run_dir).as_posix(), bytes=f.stat().st_size)
                for f in sorted(run_dir.rglob('*')) if f.is_file()], ['file', 'bytes'])
        portfolio["projects"].append(entry)
    for key, _, outfile in OUTPUTS:
        write_csv(batch / outfile, concatenated[key], ["project", "run_id", "source_sha256", "source_filename", "retrieval_time"])
        portfolio["lists"][key] = concatenated[key]
    write_csv(batch / 'REVIEW_REQUIRED.csv', portfolio['reviews'], ['project', 'run_id', 'kind', 'stage', 'detail', 'evidence'])
    write_json(batch / 'REVIEW_REQUIRED.json', {'items': portfolio['reviews']})
    write_csv(batch / "ALL_Diagnostics.csv", portfolio["diagnostics"], ["project", "run_id", "detail"])
    write_csv(batch / "PROJECT_STATUS.csv", portfolio["projects"], ["project", "status", "run_id", "status_date",
              "report_status", "retrieval_state", "source_original_filename", "retrieval_time", "original_source",
              "not_sent", "company_delay", "consultant_delay", "diagnostic_count", "sha256", "pause_stage", "reason"])
    write_csv(batch / "SOURCE_INVENTORY.csv", portfolio["projects"], ["project", "alias", "retrieval_state",
              "source_original_filename", "retrieved_filename", "retrieval_time", "source_modified", "original_source",
              "retrieved_input", "source_link", "sha256", "source_selection"])
    write_json(batch / "portfolio_manifest.json", {k: v for k, v in portfolio.items() if k != "lists"} |
               {"list_row_counts": {k: len(v) for k, v in portfolio["lists"].items()}})
    create_html(batch, portfolio)
    return portfolio


def create_html(batch: Path, portfolio: dict[str, Any]) -> None:
    # Fully offline: source text is inserted using textContent, never HTML parsing.
    data = json.dumps(portfolio, ensure_ascii=False).replace("<", "\\u003c").replace("</", "<\\/")
    out = r'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Cleaner | Engineering Portfolio Review</title><style>
:root{font-family:Segoe UI,Arial,sans-serif;color:#152134;background:#f5f7fb}body{margin:0 auto;max-width:1480px;padding:24px}
h1{font-size:25px;margin:0 0 8px}.hint{color:#566478;font-size:13px}.bar{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin:16px 0}
button,select,input{font:inherit;border:1px solid #ccd4df;border-radius:8px;padding:9px 12px;background:#fff}button{cursor:pointer}
button.active{background:#143d74;color:#fff}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin:18px 0}
.card{background:white;border:1px solid #e0e5ed;border-radius:10px;padding:14px}.card b{display:block;font-size:24px;margin:4px 0}
.panel{background:#fff;border:1px solid #e0e5ed;border-radius:10px;padding:14px;margin:15px 0}.scroll{overflow:auto;max-height:58vh}
table{border-collapse:collapse;min-width:100%;font-size:13px}td,th{padding:9px;border-bottom:1px solid #ebeff4;text-align:left;white-space:nowrap}th{position:sticky;top:0;background:#edf2fa}
tr:hover td{background:#f6f9fe}a{color:#174985}small{color:#5b6575}.muted{color:#58677a}
.note{font-size:13px;color:#5d6673;margin:8px 0}.tag{font-size:12px;padding:3px 7px;border:1px solid #dbe2ee;border-radius:20px}
</style></head><body>
<h1>Engineering control — multi-project review</h1>
<p class="hint">Latest available General Document per project → Cleaner → Board/Log → Coverage → 3 lists. Older source records are included. Review gates remain explicit; no missing output is counted as zero.</p>
<div class="cards" id="stats"></div><section class="panel"><h3>Review register</h3><p>OPEN_GATE and PROJECT_ACTION require attention. QUEUE_EVIDENCE preserves findings, including those with earlier decisions; it is not an unresolved-item count.</p><a href="REVIEW_REQUIRED.csv">Review CSV</a> · <a href="REVIEW_REQUIRED.json">Review JSON</a><div class="scroll"><table id="reviews"></table></div></section>
<section class="panel"><h3>Retrieved source inventory</h3><p class="note">Source file modified date and batch retrieval time are different concepts. Click "snapshot" to inspect the actual source copied for this batch.</p><div class="bar"><a href="SOURCE_INVENTORY.csv">Source inventory CSV</a></div><div class="scroll"><table id="sources"></table></div></section>
<section class="panel"><h3>Project processing and review</h3><div class="bar"><a href="PROJECT_STATUS.csv">Project status CSV</a><a href="ALL_Diagnostics.csv">Diagnostics CSV</a></div><div class="scroll"><table id="status"></table></div></section>
<div class="bar"><button data-key="not_sent" class="active">Not sent</button><button data-key="company_delay">Company delay</button><button data-key="consultant_delay">Consultant delay</button><button data-key="diagnostics">Diagnostics</button>
<select id="project"><option value="">All projects</option></select><input id="q" placeholder="Search documents / WBS / status" size="35"/><span id="count" class="hint"></span></div>
<section class="panel"><div class="bar"><a href="ALL_01_Not_Sent.csv">Not sent CSV</a><a href="ALL_02_Company_Delay.csv">Company delay CSV</a><a href="ALL_03_Consultant_Delay.csv">Consultant delay CSV</a></div><p id="reportNote" class="note"></p><div class="scroll"><table id="records"></table></div><p class="hint">Displays at most 400 matching rows; CSVs retain all generated rows. Blank count means not generated or missing, not zero.</p></section>
<script>const DATA=__DATA__;let kind='not_sent';let pdata=DATA.projects||[];
function makeTable(el,rows,keys){el.replaceChildren();let head=document.createElement('thead'),tr=document.createElement('tr');keys.forEach(k=>{let th=document.createElement('th');th.textContent=k;tr.append(th)});head.append(tr);el.append(head);let body=document.createElement('tbody');rows.forEach(r=>{let t=document.createElement('tr');keys.forEach(k=>{let td=document.createElement('td');if(k==='links'){let names=[['snapshot',r.source_link],['review',r.review_queue_link],['report',r.run_evidence_link],['cleaner',r.cleaner_log_link],['retrieval',r.retrieval_log_link],['all audits',r.audit_index]];names.filter(x=>x[1]).forEach(([name,url],i)=>{if(td.childNodes.length)td.append(' · ');let a=document.createElement('a');a.href=url;a.textContent=name;td.append(a)})}else td.textContent=String(r[k]??'');t.append(td)});body.append(t)});el.append(body)}
function stat(k,label){return `<div class="card"><small>${label}</small><b>${k}</b></div>`}let counts={};['not_sent','company_delay','consultant_delay'].forEach(k=>counts[k]=DATA.lists[k]?.length||0);
let calculated=pdata.filter(p=>p.report_status==='CALCULATED'||p.report_status==='PROVISIONAL_REVIEW_PENDING').length;
let staged=pdata.filter(p=>p.retrieval_state==='SNAPSHOT_VERIFIED').length;
let pending=pdata.filter(p=>p.status==='REVIEW_REQUIRED').length;
document.getElementById('stats').innerHTML=stat(staged+'/'+pdata.length,'Source snapshots')+stat(calculated+'/'+pdata.length,'Lists calculated')+stat(pending,'Projects pending review')+stat(counts.not_sent,'Not sent')+stat(counts.company_delay,'Company delay')+stat(counts.consultant_delay,'Consultant delay');
makeTable(document.getElementById('sources'),pdata,['project','source_original_filename','retrieved_filename','retrieval_time','source_modified','retrieval_state','original_source','links']);
makeTable(document.getElementById('status'),pdata,['project','status','report_status','run_id','not_sent','company_delay','consultant_delay','diagnostic_count','pause_stage','reason','links']);
makeTable(document.getElementById('reviews'),DATA.reviews||[],['project','kind','stage','reason','detail','evidence']);
let sel=document.getElementById('project');pdata.forEach(p=>{let o=document.createElement('option');o.value=p.project;o.textContent=p.project;sel.append(o)});
function refresh(){let rows=kind==='diagnostics'?DATA.diagnostics:(DATA.lists[kind]||[]),q=document.getElementById('q').value.toLocaleLowerCase(),p=sel.value;
let matched=rows.filter(r=>(!p||r.project===p)&&(!q||Object.values(r).some(v=>String(v??'').toLocaleLowerCase().includes(q))));let subset=matched.slice(0,400),keys=[];
subset.forEach(r=>Object.keys(r).forEach(k=>{if(!keys.includes(k))keys.push(k)}));makeTable(document.getElementById('records'),subset,keys.length?keys:['project']);
document.getElementById('count').textContent=matched.length+' matching rows';
let calculatedFor=p?pdata.filter(x=>x.project===p&&['CALCULATED','PROVISIONAL_REVIEW_PENDING'].includes(x.report_status)).length:calculated;
let scope=p?1:pdata.length;document.getElementById('reportNote').textContent=calculatedFor+' of '+scope+' project(s) have calculated all 3 lists. Provisional lists need review; unresolved structural dependencies block calculation.';}
document.querySelectorAll('button[data-key]').forEach(b=>b.addEventListener('click',()=>{kind=b.dataset.key;document.querySelectorAll('button[data-key]').forEach(x=>x.classList.toggle('active',x===b));refresh()}));sel.addEventListener('change',refresh);document.getElementById('q').addEventListener('input',refresh);refresh();</script></body></html>'''
    (batch / "index.html").write_text(out.replace("__DATA__", data), encoding="utf-8")


def review(project: str, batch: Path, date: str, cfg: dict[str, Any]) -> int:
    """Review also works if previous controller blocked source before a run existed."""
    sfile = batch / "projects" / project / "state.json"
    if not sfile.is_file():
        print(f"[INFO] No prior batch state for {project}; checking retrieved source.")
    elif read_json(sfile).get("status_date") != date:
        print("[ERROR] Status date mismatch. Use original batch date.")
        return 1
    state = run_one(project, cfg, batch, date, do_retrieve=False, run_cleaner=True, interactive=True)
    print("[REVIEW RESULT]", project, state.get("status"), state.get("run_id") or "-", state.get("reason") or "")
    if str(state.get("status", "")).startswith("COMPLETE"):
        return 0
    return 2 if state.get("status") in {"REVIEW_REQUIRED", "SOURCE_REVIEW"} else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Retrieve, clean, and consolidate latest General Docs without editing originals")
    p.add_argument("--status-date", required=True, help="Jalali YYYY/MM/DD, e.g. 1405/07/30")
    p.add_argument("--batch", default=None, help="Stable batch identifier; reuse to resume without resetting reviews")
    p.add_argument("--projects", default=None, help="Comma-separated project codes, defaults to all configured")
    p.add_argument("--collect-only", action="store_true", help="Rebuild dashboard from the batch's prior runs")
    p.add_argument("--retrieve-only", action="store_true", help="Fetch and snapshot sources, do not run Cleaner")
    p.add_argument("--skip-retrieval", action="store_true", help="Use existing registered retrieval copies (not guaranteed latest)")
    p.add_argument("--review", metavar="PROJECT", help="Interactively resume one project using its existing run ID")
    args = p.parse_args(argv)
    if not re.fullmatch(r"14\d{2}/\d{2}/\d{2}", args.status_date):
        p.error("--status-date must have format 14xx/mm/dd")
    if not CONFIG.is_file():
        p.error(f"Missing configuration: {CONFIG}")
    project_config = read_json(CONFIG).get("projects") or {}
    projects = [p.strip().upper() for p in args.projects.split(",")] if args.projects else list(project_config)
    for code in projects:
        if code not in project_config:
            p.error(f"Project not configured: {code}")
    if args.batch and not re.fullmatch(r"[A-Za-z0-9_-]+", args.batch):
        p.error("Invalid batch ID")
    if args.review and not args.batch:
        p.error("--review requires --batch")
    if args.review and args.review.upper() not in project_config:
        p.error(f"Project not configured: {args.review}")
    batch = ROOT / "demo_review" / (args.batch or datetime.now().strftime("%Y%m%dT%H%M%S"))
    batch.mkdir(parents=True, exist_ok=True)
    print("[BATCH]", batch)
    if args.review:
        rc = review(args.review.upper(), batch, args.status_date, project_config[args.review.upper()])
        gather(batch, list(dict.fromkeys(projects + [d.name for d in (batch / "projects").iterdir() if d.is_dir() and d.name in project_config])), project_config)
        print("[REVIEW] Updated report:", batch / "index.html")
        return rc
    if not args.collect_only and not args.retrieve_only and not (ROOT / RUNNER).is_file():
        print(f"[ERROR] Missing {RUNNER}; place V06 in the repo root")
        return 1
    for project in projects:
        if args.collect_only:
            break
        print(f"[PROJECT] {project}")
        state = run_one(project, project_config[project], batch, args.status_date,
                        do_retrieve=not args.skip_retrieval, run_cleaner=not args.retrieve_only)
        print("  ", state.get("status"), "|", state.get("run_id") or "-", "|", str(state.get("reason") or "")[:160])
    gathered = gather(batch, list(dict.fromkeys(projects + [d.name for d in (batch / "projects").iterdir() if d.is_dir() and d.name in project_config])), project_config)
    print("\n[PORTFOLIO]", batch / "index.html")
    print("[STATUS]", batch / "PROJECT_STATUS.csv")
    for p in gathered["projects"]:
        print(f"  {p['project']:4} {p.get('status','NOT_RUN'):32} {p.get('report_status','NOT_CALCULATED'):27} N={p.get('not_sent','')} C={p.get('company_delay','')} K={p.get('consultant_delay','')} D={p.get('diagnostic_count','')}")
    if args.retrieve_only:
        return 0 if all(x.get("status") == "SOURCE_STAGED" for x in gathered["projects"]) else 2
    return 0 if all(str(x.get("status", "")).startswith("COMPLETE") for x in gathered["projects"]) else 2


if __name__ == "__main__":
    raise SystemExit(main())
