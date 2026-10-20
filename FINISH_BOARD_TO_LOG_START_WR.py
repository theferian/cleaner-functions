#!/usr/bin/env python3
r"""Close board-to-log work safely and start weekly-report extraction branch.

  py .\FINISH_BOARD_TO_LOG_START_WR.py --check
  py .\FINISH_BOARD_TO_LOG_START_WR.py --apply

Never removes original workbooks, review runs, profiles, exception state or local history.
"""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

OLD = "feature/board-to-log"
NEW = "feature/weekly-report-cleaner-template"
SEED = "weekly_report_branch_seed"
NON_CODE_ROOT = {"root.zip", "GeneralDoc_ProjectTeam_Input.zip", "AZD_WR_CLEANER_SERVICE_v01.zip",
                 "NEXT_GENERAL_DOC_STAGE.pyz", "azd_mline_report.json", "azd_review_queue.json", "azd_review_decisions.json"}
EXCLUDED_DIRS = {"runs", "working", "portfolio_audits", "input", "payload", ".pytest_cache", "__pycache__",
                 "toProjectReport", "weekly_report_branch_seed"}
CODE_DIRS = {"cleaner_core", "cleaners", "configs", "dev", "discoveries", "docs", "exceptions",
             "functions", "pipeline", "profiles", "project_solutions", "review", "tests", "tools", "unit_tests",
             "wr_cleaner", "azd_wr_cleaner_v01"}
CODE_EXTS = {".py", ".json", ".md", ".txt", ".csv", ".patch", ".toml", ".yaml", ".yml",
             ".ini", ".cfg", ".sql", ".js", ".ts", ".tsx", ".html", ".css"}
ROOT_ALLOWED = {".gitignore", "README.md", "requirements.txt", "cleaner.package.json"}
PER_FILE_MAX = 10 * 1024 * 1024
TOTAL_STAGE_MAX = 35 * 1024 * 1024
IGNORE_LINES = ["/working/", "/portfolio_audits/", "/.pytest_cache/", "__pycache__/", "*.pyc"]


def command(args, cwd: Path, check=True, output=True, **kw):
    r = subprocess.run(args, cwd=str(cwd), capture_output=True, text=True, errors="replace", **kw)
    if output and r.stdout.strip():
        print(r.stdout.strip())
    if output and r.stderr.strip():
        print(r.stderr.strip())
    if check and r.returncode:
        raise RuntimeError(f"Command failed ({r.returncode}): {' '.join(map(str,args))}")
    return r


def git(root: Path, *args, check=True):
    return command(["git", *args], root, check=check, output=False)


def splitz(data: bytes):
    return [x.decode("utf-8", "surrogateescape") for x in data.split(b"\0") if x]


def git_paths(root, args):
    return splitz(subprocess.run(["git", *args, "-z"], cwd=root, check=True, capture_output=True).stdout)


def git_root(root):
    p = git(root, "rev-parse", "--show-toplevel").stdout.strip()
    if Path(p).resolve() != root.resolve():
        raise RuntimeError(f"Start from repository root: {p}")
    branch = git(root, "branch", "--show-current").stdout.strip()
    if branch != OLD:
        raise RuntimeError(f"Expected {OLD}, found {branch}; no changes made")
    if git(root, "branch", "--list", NEW).stdout.strip():
        raise RuntimeError(f"Target branch already exists: {NEW}; no changes made")
    if git_paths(root, ["diff", "--cached", "--name-only"]):
        raise RuntimeError("Git index already has staged changes. Commit/review those first; this tool will not mix them.")
    if git(root, "status", "--porcelain", "--untracked-files=no").returncode:
        raise RuntimeError("Cannot obtain git status")
    return branch


def is_archive_candidate(path: Path):
    n = path.name
    if path.is_file():
        return n in NON_CODE_ROOT or path.suffix.lower() in {".zip", ".patch", ".pyz"}
    return path.is_dir() and (n.endswith("_backup") or n.startswith("_auto_wbs_backup_")
           or n.startswith("_bfg_") or n.startswith("_hold_comment_backup_")
           or n.startswith("_meeting_reference_backup_") or n.startswith("_ngn_optional_wbs_backup_")
           or n.startswith("_portfolio_runner_v06_backup_") or n.startswith(".engineering_status_backup")
           or n.startswith(".azd_wr_profile_backup"))


def safe_code(path: str):
    parts = Path(path).parts
    if not parts or any(p in EXCLUDED_DIRS for p in parts):
        return False
    if len(parts) == 1:
        return path in ROOT_ALLOWED or Path(path).suffix.lower() in {".py", ".md", ".txt"} or path in {
            "GENERAL_DOC_CARD_CATALOG.csv", "GENERAL_DOC_FINDINGS_103.csv", "GENERAL_DOC_REVIEW_GROUPS.csv"}
    return parts[0] in CODE_DIRS and Path(path).suffix.lower() in CODE_EXTS


def has_tracked(root: Path, p: Path, tracked: set[str]):
    rel = p.relative_to(root).as_posix()
    return rel in tracked or any(t.startswith(rel + "/") for t in tracked)


def plans(root: Path):
    tracked = set(git_paths(root, ["ls-files"]))
    dirty = git_paths(root, ["diff", "--name-only"])
    untracked = git_paths(root, ["ls-files", "--others", "--exclude-standard"])
    archive = [p for p in root.iterdir() if is_archive_candidate(p) and not has_tracked(root, p, tracked)]
    move_set = set()
    for p in archive:
        prefix = p.relative_to(root).as_posix()
        move_set.add(prefix)
    def archived(s):
        return any(s == p or s.startswith(p + "/") for p in move_set)
    to_stage = sorted(set([s for s in dirty if safe_code(s)] +
                          [s for s in untracked if safe_code(s) and not archived(s)]))
    protected_dirty = sorted(s for s in dirty if not safe_code(s))
    unclassified = sorted(s for s in untracked if not safe_code(s) and not archived(s) and not s.startswith(SEED+"/"))
    return tracked, archive, to_stage, protected_dirty, unclassified


def show_plan(root: Path):
    _, archive, to_stage, protected, others = plans(root)
    print(f"[BRANCH] {OLD} -> {NEW}")
    print(f"[ARCHIVE] {len(archive)} root artifacts/backup folders outside repository")
    for p in archive[:18]: print("  ->", p.name)
    if len(archive)>18: print(f"  ... {len(archive)-18} more")
    print(f"[STAGE] {len(to_stage)} changed/new source, tests, profiles and review-policy files")
    print(f"[PROTECTED TRACKED CHANGES] {len(protected)}")
    for p in protected[:15]: print("  !!",p)
    print(f"[UNCLASSIFIED UNTRACKED] {len(others)} (preserved, never staged automatically)")
    for p in others[:12]: print("  ??",p)
    print("[PRESERVED] runs/, input/, working/, portfolio_audits/, toProjectReport/, payload/")
    print("[NEXT] --apply runs tests, archives safe artifacts, commits, switches branch and seeds WR inspector")
    return not protected


def sha_file(p):
    h=hashlib.sha256()
    with p.open("rb") as f:
        for block in iter(lambda: f.read(1024*1024),b""):
            h.update(block)
    return h.hexdigest()


def archive_artifacts(root, selected, archive):
    archive.mkdir(parents=True, exist_ok=False)
    records=[]
    for p in selected:
        dst=archive/p.name
        if dst.exists(): raise RuntimeError(f"Archive collision: {dst}")
        checksum=sha_file(p) if p.is_file() else None
        shutil.move(str(p),str(dst))
        records.append({"source":str(p),"archive":str(dst),"sha256":checksum})
        print("[ARCHIVED]",p.name)
    (archive/"manifest.json").write_text(json.dumps(records,indent=2,ensure_ascii=False),encoding="utf-8")
    return records


def append_ignore(root):
    p=root/".gitignore"
    s=p.read_text(encoding="utf-8") if p.exists() else ""
    additions=[x for x in IGNORE_LINES if x not in s.splitlines()]
    if additions:
        p.write_text(s.rstrip()+"\n\n# Generated local Cleaner outputs (not source or profiles)\n"+"\n".join(additions)+"\n",encoding="utf-8")


def stage_files(root, files):
    for s in files:
        p=root/s
        if p.is_file() and p.stat().st_size>PER_FILE_MAX:
            raise RuntimeError(f"Refusing large source staging ({p.stat().st_size} bytes): {s}")
    total=sum((root/s).stat().st_size for s in files if (root/s).is_file())
    if total>TOTAL_STAGE_MAX: raise RuntimeError(f"Staged source exceeds safety budget: {total} bytes")
    # Batch to stay under Windows command-line length limits.
    batch=[]; length=0
    for s in files:
        if batch and (len(batch)>=55 or length+len(s)>4400):
            git(root,"add","-A","--",*batch)
            batch=[]; length=0
        batch.append(s); length+=len(s)+3
    if batch: git(root,"add","-A","--",*batch)


def run_tests(root):
    env=os.environ.copy()
    for key in ["OPENBLAS_NUM_THREADS","OMP_NUM_THREADS","MKL_NUM_THREADS","NUMEXPR_NUM_THREADS"]:
        env[key]="1"
    args=[sys.executable,"-m","pytest","-q","--ignore=payload","--import-mode=importlib"]
    print("[TEST]"," ".join(args))
    res=command(args,root,check=False,output=False,env=env)
    lines=(res.stdout+"\n"+res.stderr).splitlines()
    for line in lines[-12:]:print(line)
    if res.returncode: raise RuntimeError("Cleaner tests failed. No branch closure performed.")


def close_handoff(root, archive, n):
    out=root/"docs"/"handoffs"/"GENERAL_DOCUMENT_BRANCH_CLOSE_20261020.md"
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text("""# General Document branch handoff

Branch: `feature/board-to-log`. Closure focus: General Document family.

## Preserved work
- Family-profile structure, M_LINE, correspondence cards, send/receive logbook, coverage audit and Engineering reporting.
- Review-driven overlays, project-specific exceptions, statuses, and eight run workspaces under `runs/`.
- Bilingual real-Excel gallery with 58 grouped team review tasks and 103 source-linked findings.
- Portfolio as-of evaluation: machine-reported coverage is separate from business sign-off.
- The General Document workbook is a living file; future source version tracking is on hold.
- OCR verification is deferred, not represented as complete.

## Current project runs (do not reset)
AZD `azd_20261014T071802`; JND `jnd_20261007T022038`;
FSH `fsh_20261007T024351`; YSK `ysk_20261016T212108`;
EYV `eyv_20261017T020820`; BFG `bfg_20261017T130419`;
NKH `nkh_20261017T053117`; NGN `ngn_20261017T143536`.

## Next branch
`feature/weekly-report-cleaner-template`: read/report a weekly workbook, discover schema and report date,
extract source-linked data, verify WBS mapping, then populate an explicit template **without editing source**.
Keep source date, derived/report date and any generated value distinguishable.

## Cleanup
Known untracked installers/packages/patch bundles and backup directories are moved to an archive
**outside** this Git repo. Git source and run evidence remain in place. Archive path:

`"""+str(archive)+"""`

Archived root items: """+str(n)+""". Avoid deleting this archive until independently backed up.
""",encoding="utf-8")
    return out


def apply(root: Path):
    git_root(root)
    if not (root/SEED).is_dir():
        raise RuntimeError(f"Missing {SEED}/. Extract the whole ZIP at the repository root.")
    if not show_plan(root):
        raise RuntimeError("Modified tracked runtime/output files were found; resolve them before applying.")
    git(root,"var","GIT_AUTHOR_IDENT")
    git(root,"var","GIT_COMMITTER_IDENT")
    planned_targets=[root/q for q in ["tools/weekly_report/inspect_workbook.py",
        "tests/test_weekly_report_inspector.py","docs/weekly_report/START_HERE.md"]]
    if any(p.exists() for p in planned_targets):
        raise RuntimeError("A Weekly Report starter file already exists; will not overwrite it.")
    for p in planned_targets:
        src=root/SEED/p.relative_to(root)
        if not src.is_file():raise RuntimeError(f"Seed file missing: {src}")
    # Run all tests before any moves/staging, so failures do not disturb repo.
    run_tests(root)
    tracked, selected, _, protected, _ = plans(root)
    if protected:raise RuntimeError("Tracked operational files became dirty; refusing closure")
    utc=dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive=root.parent/"_cleaner_branch_archives"/("board_to_log_"+utc)
    archive_artifacts(root,selected,archive)
    append_ignore(root)
    close_handoff(root,archive,len(selected))
    _,_,to_stage,protected,other=plans(root)
    if protected:raise RuntimeError(f"Refusing to stage protected files: {protected[:5]}")
    stage_files(root,to_stage)
    changed=git_paths(root,["diff","--cached","--name-only"])
    if not changed:raise RuntimeError("No source changes to commit (unexpected)")
    print(f"[COMMIT] {len(changed)} source/history paths on {OLD}")
    git(root,"commit","-m","Finalize General Document Cleaner, review evidence and bilingual gallery")
    # Switching after commit: leftover untracked files are preserved.
    git(root,"switch","-c",NEW)
    seed_root=root/SEED
    copied=[]
    for dst in planned_targets:
        source=seed_root/dst.relative_to(root)
        dst.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source,dst)
        copied.append(dst.relative_to(root).as_posix())
    print("[WR] Seeded read-only Weekly Report inspector, tests, and handoff")
    r=command([sys.executable,"-m","pytest","-q","tests/test_weekly_report_inspector.py"],root,check=False,output=False)
    print("\n".join((r.stdout+"\n"+r.stderr).splitlines()[-8:]))
    if r.returncode:
        raise RuntimeError("Weekly Report starter tests failed; new branch exists but starter not committed.")
    stage_files(root,copied)
    git(root,"commit","-m","Start Weekly Report workbook discovery and extraction contract")
    # Keep seed recoverable, but outside the repository to unclutter the root.
    shutil.move(str(seed_root),str(archive/SEED))
    print("[DONE] General Document branch committed; now on",git(root,"branch","--show-current").stdout.strip())
    print("[ARCHIVE]",archive)
    print("[INSPECT] py .\\tools\\weekly_report\\inspect_workbook.py --file \"C:\\path\\to\\LATEST_WR.xlsx\"")
    status=git(root,"status","--short").stdout.strip()
    if status:print("[NOTE] Preserved unclassified/untouched files still present:\n"+"\n".join(status.splitlines()[:20]))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check",action="store_true")
    group.add_argument("--apply",action="store_true")
    args=parser.parse_args()
    root=Path.cwd()
    try:
        git_root(root)
        if args.check:show_plan(root)
        else:apply(root)
        return 0
    except (RuntimeError,OSError,subprocess.CalledProcessError) as exc:
        print("[STOP]",exc,file=sys.stderr)
        return 2

if __name__=="__main__":
    raise SystemExit(main())
