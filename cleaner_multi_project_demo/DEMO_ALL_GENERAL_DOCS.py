#!/usr/bin/env python3
"""Multi-project General Document demo orchestration for cleaner-functions.

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
from pathlib import Path
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
RUNNER = "RUN_GENERAL_DOCUMENT_V06.py"
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


def resolve_source(project: str, cfg: dict[str, Any], state: dict[str, Any], pdir: Path,
                   do_retrieve: bool) -> tuple[Path | None, str]:
    # Resuming a batch MUST reuse the source bytes originally bound to its review decisions.
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

    books = candidate_books(project)
    if not books:
        return None, "NO_RETRIEVED_WORKBOOK"
    books.sort(key=lambda p: (jalali_suffix(p), p.stat().st_mtime_ns, p.name), reverse=True)
    # For a new retrieval, the most recent registry output must be fresh; do not silently use stale input.
    if do_retrieve:
        log_time = (pdir / "retrieval.log").stat().st_mtime
        if books[0].stat().st_mtime < log_time - 120:
            return None, "RETRIEVAL_NO_FRESH_CANDIDATE"
    # The date-stamped registry artefact ranks first, and the source choice is audited.
    return books[0], "REGISTERED_RETRIEVAL_BY_DATE_TOKEN_THEN_MTIME"


def snapshot_source(src: Path, pdir: Path, state: dict[str, Any], selected_by: str) -> Path:
    dest = pdir / "source" / src.name
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
    state.update(snapshot=str(dest.resolve()), sha256=h, original_source=str(src.resolve()),
                 source_selection=selected_by, source_filename=src.name,
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
            date: str, *, do_retrieve: bool, run_cleaner: bool) -> dict[str, Any]:
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
                   "--non-interactive"]
        else:
            cmd = [sys.executable, str(ROOT / RUNNER), "--project", project,
                   "--new-run", "--workbook", str(book), "--status-date", date,
                   "--non-interactive"]
        rc = cmd_log(cmd, pdir / "cleaner.log")
        found_id, _ = find_run(project, book)
        if not rid and found_id:
            state["run_id"] = found_id
        elif rid and found_id != rid:
            raise RuntimeError("Existing run no longer uniquely matches the staged workbook")
        progress_path = ROOT / "runs" / str(state.get("run_id")) / "general_doc_auto_progress.json"
        progress = read_json(progress_path) if state.get("run_id") and progress_path.is_file() else {}
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


def gather(batch: Path, projects: list[str], cfg: dict[str, dict[str, Any]]) -> dict[str, Any]:
    portfolio: dict[str, Any] = {"generated_at": datetime.now().isoformat(timespec="seconds"),
                                  "projects": [], "lists": {}, "diagnostics": []}
    concatenated = {key: [] for key, _, _ in OUTPUTS}
    for project in projects:
        pdir = batch / "projects" / project
        statepath = pdir / "state.json"
        s = read_json(statepath) if statepath.is_file() else {"project": project, "status": "NOT_RUN"}
        rid = s.get("run_id")
        eng = ROOT / "runs" / str(rid) / "engineering_lists" if rid else Path("__no_run__")
        dest = pdir / "outputs"
        entry: dict[str, Any] = {k: s.get(k, "") for k in ("project", "status", "run_id", "status_date", "sha256",
                        "source_filename", "original_source", "source_modified", "source_selection", "pause_stage", "reason")}
        entry["alias"] = cfg[project].get("alias", "")
        summary: dict[str, Any] = {}
        src_json = eng / "engineering_three_lists.json"
        if src_json.is_file():
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_json, dest / src_json.name)
            try:
                obj = read_json(src_json)
                summary = obj.get("summary") or {}
                for d in obj.get("diagnostics") or []:
                    portfolio["diagnostics"].append({"project": project, "run_id": rid, "detail": json.dumps(d, ensure_ascii=False)})
            except (ValueError, OSError):
                entry["report_parse_issue"] = "Invalid engineering_three_lists.json"
        entry["report_available"] = src_json.is_file()
        for key, filename, _ in OUTPUTS:
            f = eng / filename
            if f.is_file():
                dest.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, dest / filename)
                try:
                    rows = read_csv(f)
                    concatenated[key].extend([{"project": project, "run_id": rid,
                                               "source_sha256": s.get("sha256", ""), **row} for row in rows])
                    entry[key] = len(rows)
                except (UnicodeError, csv.Error) as exc:
                    entry[key] = ""
                    entry[f"{key}_error"] = str(exc)
            else:
                entry[key] = ""  # Do not misrepresent missing reports as zero rows.
        for filename in KNOWN_OPTIONAL[:1]:
            optional_file = eng / filename
            if optional_file.is_file():
                dest.mkdir(parents=True, exist_ok=True)
                shutil.copy2(optional_file, dest / filename)
        entry["diagnostic_count"] = summary.get("diagnostic_count", len([x for x in portfolio["diagnostics"] if x["project"] == project])) if src_json.is_file() else ""
        for extra in ("board_to_log.json", "coverage_audit.json", "run_manifest.json", "general_doc_auto_progress.json"):
            f = ROOT / "runs" / str(rid) / extra if rid else Path("__missing__")
            if f.is_file():
                (pdir / "evidence").mkdir(exist_ok=True)
                shutil.copy2(f, pdir / "evidence" / extra)
        portfolio["projects"].append(entry)
    for key, _, outfile in OUTPUTS:
        write_csv(batch / outfile, concatenated[key], ["project", "run_id", "source_sha256"])
        portfolio["lists"][key] = concatenated[key]
    write_csv(batch / "ALL_Diagnostics.csv", portfolio["diagnostics"], ["project", "run_id", "detail"])
    write_csv(batch / "PROJECT_STATUS.csv", portfolio["projects"], ["project", "status", "run_id", "status_date",
              "not_sent", "company_delay", "consultant_delay", "diagnostic_count", "source_filename",
              "sha256", "pause_stage", "reason"])
    write_json(batch / "portfolio_manifest.json", {k: v for k, v in portfolio.items() if k != "lists"} |
               {"list_row_counts": {k: len(v) for k, v in portfolio["lists"].items()}})
    create_html(batch, portfolio)
    return portfolio


def create_html(batch: Path, portfolio: dict[str, Any]) -> None:
    # Static offline dashboard. Its contents are derived only from the generated CSV/JSON.
    # JS uses textContent, not innerHTML, for all source text and document values.
    data = json.dumps(portfolio, ensure_ascii=False).replace("<", "\\u003c").replace("</", "<\\/")
    out = r'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Cleaner | Engineering Portfolio Review</title><style>
:root{font-family:Segoe UI,Arial,sans-serif;color:#152134;background:#f5f7fb}body{margin:0 auto;max-width:1440px;padding:28px}
h1{font-size:27px;margin:0 0 8px}.hint{color:#566478;font-size:13px} .bar{display:flex;gap:9px;flex-wrap:wrap;align-items:center;margin:16px 0}
button,select,input{font:inherit;border:1px solid #ccd4df;border-radius:8px;padding:9px 12px;background:#fff}button{cursor:pointer}
button.active{background:#143d74;color:#fff}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(185px,1fr));gap:12px;margin:22px 0}
.card{background:white;border:1px solid #e0e5ed;border-radius:10px;padding:14px}.card b{display:block;font-size:25px;margin:4px 0}
.panel{background:#fff;border:1px solid #e0e5ed;border-radius:10px;padding:14px;margin:18px 0}.scroll{overflow:auto;max-height:66vh}
table{border-collapse:collapse;min-width:100%;font-size:13px}td,th{padding:10px;border-bottom:1px solid #ebeff4;text-align:left;white-space:nowrap}th{position:sticky;top:0;background:#edf2fa}
tr:hover td{background:#f6f9fe}a{color:#174985}small{color:#5b6575}.muted{color:#58677a}
</style></head><body><h1>Engineering control — portfolio review</h1><p class="hint">General Documents → Cleaner → Board/Log → Coverage → 3 Engineering Lists. Missing outputs are blank, not zero. Source files are read-only snapshots. Business sign-off remains separate.</p>
<div class="cards" id="stats"></div>
<section class="panel"><h3>Project run status</h3><div class="scroll"><table id="status"></table></div></section>
<div class="bar"><button data-key="not_sent" class="active">Not sent</button><button data-key="company_delay">Company delay</button><button data-key="consultant_delay">Consultant delay</button><button data-key="diagnostics">Diagnostics</button>
<select id="project"><option value="">All projects</option></select><input id="q" placeholder="Search documents / WBS / status" size="35"/><span id="count" class="hint"></span></div>
<section class="panel"><div class="bar"><a href="PROJECT_STATUS.csv">Project status CSV</a><a href="ALL_01_Not_Sent.csv">Not sent CSV</a><a href="ALL_02_Company_Delay.csv">Company delay CSV</a><a href="ALL_03_Consultant_Delay.csv">Consultant delay CSV</a><a href="ALL_Diagnostics.csv">Diagnostics CSV</a></div><div class="scroll"><table id="records"></table></div><p class="hint">Displaying at most 400 matching rows; CSVs contain every row. View a project's outputs and evidence from the links in the project status table.</p></section>
<script>const DATA=__DATA__;let kind='not_sent';let pdata=DATA.projects||[];
function makeTable(el,rows,keys){el.replaceChildren();let head=document.createElement('thead'),tr=document.createElement('tr');keys.forEach(k=>{let th=document.createElement('th');th.textContent=k;tr.append(th)});head.append(tr);el.append(head);let body=document.createElement('tbody');rows.forEach(r=>{let t=document.createElement('tr');keys.forEach(k=>{let td=document.createElement('td');if(k==='links'){let p=r.project;[['outputs','projects/'+p+'/outputs/01_Not_Sent.csv'],['evidence','projects/'+p+'/evidence/run_manifest.json'],['log','projects/'+p+'/cleaner.log']].forEach(([name,url],i)=>{if(i)td.append(' · ');let a=document.createElement('a');a.href=url;a.textContent=name;td.append(a)})}else td.textContent=String(r[k]??'');t.append(td)});body.append(t)});el.append(body)}
function stat(k,label){return `<div class="card"><small>${label}</small><b>${k}</b></div>`} let counts={};['not_sent','company_delay','consultant_delay'].forEach(k=>counts[k]=DATA.lists[k]?.length||0);
let completed=pdata.filter(p=>String(p.status).startsWith('COMPLETE')).length;document.getElementById('stats').innerHTML=stat(pdata.length,'Projects in scope')+stat(completed,'Cleaner completed')+stat(counts.not_sent,'Not sent')+stat(counts.company_delay,'Company delay')+stat(counts.consultant_delay,'Consultant delay');
makeTable(document.getElementById('status'),pdata,['project','status','run_id','not_sent','company_delay','consultant_delay','diagnostic_count','source_filename','pause_stage','reason','links']);
let sel=document.getElementById('project');pdata.forEach(p=>{let o=document.createElement('option');o.value=p.project;o.textContent=p.project;sel.append(o)});
function refresh(){let rows=kind==='diagnostics'?DATA.diagnostics:(DATA.lists[kind]||[]),q=document.getElementById('q').value.toLocaleLowerCase(),p=sel.value;let matched=rows.filter(r=>(!p||r.project===p)&&(!q||Object.values(r).some(v=>String(v??'').toLocaleLowerCase().includes(q))));let subset=matched.slice(0,400),keys=[];subset.forEach(r=>Object.keys(r).forEach(k=>{if(!keys.includes(k))keys.push(k)}));makeTable(document.getElementById('records'),subset,keys.length?keys:['project']);document.getElementById('count').textContent=matched.length+' matching rows';}
document.querySelectorAll('button[data-key]').forEach(b=>b.addEventListener('click',()=>{kind=b.dataset.key;document.querySelectorAll('button[data-key]').forEach(x=>x.classList.toggle('active',x===b));refresh()}));sel.addEventListener('change',refresh);document.getElementById('q').addEventListener('input',refresh);refresh();</script></body></html>'''
    (batch / "index.html").write_text(out.replace("__DATA__", data), encoding="utf-8")


def review(project: str, batch: Path, date: str) -> int:
    sfile = batch / "projects" / project / "state.json"
    if not sfile.is_file():
        print(f"[ERROR] No batch state for {project}")
        return 1
    state = read_json(sfile)
    if state.get("status_date") != date:
        print("[ERROR] Status date mismatch. Use original batch date.")
        return 1
    if not state.get("run_id") or not state.get("snapshot"):
        print("[ERROR] No resumable run. Run the batch first.")
        return 1
    cmd = [sys.executable, str(ROOT / RUNNER), "--project", project,
           "--run-id", state["run_id"], "--workbook", state["snapshot"],
           "--status-date", date]
    if sha256(Path(state["snapshot"])) != state.get("sha256"):
        print("[ERROR] Batch snapshot SHA256 changed; cannot safely resume review")
        return 1
    print("[REVIEW]", project, state["run_id"])
    rc = subprocess.run(cmd, cwd=ROOT, check=False).returncode
    progress_path = ROOT / "runs" / state["run_id"] / "general_doc_auto_progress.json"
    progress = read_json(progress_path) if progress_path.is_file() else {}
    state.update(status=str(progress.get("status") or ("COMPLETE" if rc == 0 else "REVIEW_REQUIRED" if rc == 2 else "ERROR")),
                 returncode=rc, last_stage=progress.get("last_stage", ""),
                 pause_stage=progress.get("pause_stage", ""),
                 reason=progress.get("note") or progress.get("error") or "")
    write_json(sfile, state)
    return rc


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
    batch = ROOT / "demo_review" / (args.batch or datetime.now().strftime("%Y%m%dT%H%M%S"))
    batch.mkdir(parents=True, exist_ok=True)
    print("[BATCH]", batch)
    if args.review:
        rc = review(args.review.upper(), batch, args.status_date)
        gather(batch, projects, project_config)
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
    gathered = gather(batch, projects, project_config)
    print("\n[PORTFOLIO]", batch / "index.html")
    print("[STATUS]", batch / "PROJECT_STATUS.csv")
    for p in gathered["projects"]:
        print(f"  {p['project']:4} {p.get('status','NOT_RUN'):36} N={p.get('not_sent','')} C={p.get('company_delay','')} K={p.get('consultant_delay','')} D={p.get('diagnostic_count','')}")
    if args.retrieve_only:
        return 0 if all(x.get("status") == "SOURCE_STAGED" for x in gathered["projects"]) else 2
    return 0 if all(str(x.get("status", "")).startswith("COMPLETE") for x in gathered["projects"]) else 2


if __name__ == "__main__":
    raise SystemExit(main())
