#!/usr/bin/env python3
r"""Find NGN General Document only inside Negin Boushehr's mapped project folder.

Windows CMD (from cleaner-functions root):
  py .\RETRIEVE_AND_RUN_NGN.py --status-date 1405/07/22
  py .\RETRIEVE_AND_RUN_NGN.py --list
  py .\RETRIEVE_AND_RUN_NGN.py --source "W:\00-1403\1403-02-04-Negin   Boushehr\...\FILE.xlsx"

Copying does not approve the source. The existing staging/runner enforce
structural review and keep the original workbook unchanged.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
from tempfile import NamedTemporaryFile
from typing import Iterator

HERE = Path(__file__).resolve().parent
DEFAULT_PROJECT_ROOT = r"W:\00-1403\1403-02-04-Negin   Boushehr"
NEGATIVE = ("transmittal", "weekly", "coverage_audit", "progress", "schedule", "purchase", "invoice", "budget", "claim", "backup", "old version", "template", "report")
SKIP_DIRS = {".git", "__pycache__", "node_modules", "$recycle.bin", "system volume information"}


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def scan(root: Path, max_depth: int = 8, max_files: int = 18000) -> Iterator[Path]:
    todo = [(root, 0)]
    seen = 0
    while todo:
        folder, depth = todo.pop()
        try:
            entries = sorted(os.scandir(folder), key=lambda x: x.name.casefold())
        except OSError:
            continue
        for ent in entries:
            try:
                if ent.is_file(follow_symlinks=False):
                    seen += 1
                    if seen > max_files:
                        raise RuntimeError(f"Scoped scan exceeded {max_files} files; provide --source exact path")
                    p = Path(ent.path)
                    if p.suffix.casefold() in {'.xlsx', '.xlsm', '.xls', '.xlsb'} and not p.name.startswith('~$'):
                        yield p
                elif depth < max_depth and ent.is_dir(follow_symlinks=False) and ent.name.casefold() not in SKIP_DIRS:
                    todo.append((Path(ent.path), depth + 1))
            except OSError:
                continue


def score(path: Path, project_root: Path) -> int:
    nm = path.name.casefold()
    rel = str(path.relative_to(project_root)).casefold().replace('/', '\\')
    if any(w in nm for w in NEGATIVE):
        return -100
    n = 0
    if 'general' in nm: n += 105
    if 'latest_general_doc' in nm: n += 50
    if 'document' in nm: n += 35
    if 'correspondence' in nm: n += 30
    if 'updated doc' in nm or 'updated_doc' in nm: n += 30
    if 'doc' in nm and 'document' not in nm: n += 14
    if 'negin' in nm or 'نگین' in nm: n += 8
    if 'updated doc' in rel or 'updated_doc' in rel: n += 25
    if '\\technical\\' in rel: n += 15
    if '\\letter\\' in rel: n += 12
    if '\\project control\\' in rel: n += 6
    return n


def candidate_info(path: Path, root: Path) -> dict:
    st = path.stat()
    return {"path": str(path), "name": path.name, "score": score(path, root),
            "modified": st.st_mtime, "size_bytes": st.st_size}


def is_inside(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=True).relative_to(root.resolve(strict=True))
        return True
    except (ValueError, OSError):
        return False


def safe_copy(src: Path, dest: Path, expected: str):
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        if digest(dest) != expected:
            raise RuntimeError(f"Existing staged candidate differs; refusing overwrite: {dest}")
        return 'EXISTING_VERIFIED'
    with NamedTemporaryFile(dir=dest.parent, prefix='.retrieve_', delete=False) as tmp:
        temp = Path(tmp.name)
    try:
        shutil.copyfile(src, temp)
        if digest(temp) != expected:
            raise RuntimeError('SHA-256 mismatch after local copy; no candidate approved')
        temp.replace(dest)
        return 'CREATED'
    finally:
        temp.unlink(missing_ok=True)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project-root', default=DEFAULT_PROJECT_ROOT, help='Exact Negin project root, not W: drive root')
    p.add_argument('--source', help='Exact full path for the NGN workbook, inside the known project root')
    p.add_argument('--list', action='store_true', help='Read-only ranked shortlist; do not stage or run')
    p.add_argument('--status-date', default='1405/07/22')
    p.add_argument('--out', default=r'input\GENERAL_DOCUMENT\NGN\retrieval_20261017')
    p.add_argument('--run-id', help='Resume specific NGN run if one exists')
    a = p.parse_args(argv)
    root = Path(a.project_root)
    if not root.is_dir():
        print(f'[STOP] NGN project root not accessible: {root}')
        print('[ACTION] Connect the W: mapping or specify --project-root; no files changed.')
        return 2
    if not (HERE / 'pipeline' / 'project_pipeline.py').is_file():
        print('[STOP] Run from cleaner-functions root (where pipeline/ exists).')
        return 2
    candidates = [candidate_info(q, root) for q in scan(root) if q.is_file() and q.stat().st_size > 0]
    candidates.sort(key=lambda x: (x['score'], x['modified'], x['size_bytes']), reverse=True)
    print(f'[SCOPE] {root} | Excel candidates={len(candidates)} (.xlsx eligible; other formats listed for review)')
    for c in candidates[:15]:
        print(f"  score={c['score']:>4} {c['name']} ({c['size_bytes']:,} bytes) -> {c['path']}")
    chosen = None
    if a.source:
        source = Path(a.source)
        if not source.is_file() or source.suffix.casefold() != '.xlsx' or not is_inside(source, root):
            print('[STOP] --source must identify an existing .xlsx INSIDE the NGN project root.')
            return 2
        chosen = next((x for x in candidates if Path(x['path']).resolve() == source.resolve()), None)
        if chosen is None:
            print('[STOP] Selected file was not found during bounded scanning; specify a nearer --project-root.')
            return 2
    elif candidates and Path(candidates[0]['path']).suffix.casefold() == '.xlsx' and candidates[0]['score'] >= 95 and (len(candidates) == 1 or candidates[0]['score'] - candidates[1]['score'] >= 35):
        chosen = candidates[0]
    if a.list:
        print('[LIST] No files copied or modified.')
        return 0
    if chosen is None:
        print('[REVIEW REQUIRED] No uniquely convincing General Document. Inspect the shortlist.')
        print('  Rerun with --source "<full W: path>" to choose the correct workbook.')
        return 2
    source = Path(chosen['path'])
    original_sha = digest(source)
    out = Path(a.out)
    if not out.is_absolute():
        out = HERE / out
    dest = out / 'NGN' / source.name
    result = safe_copy(source, dest, original_sha)
    rec = {"project":"NGN", "status":"COPIED_REVIEW_REQUIRED", "project_root":str(root),
           "selected": {**chosen, "source":str(source), "copy":str(dest), "sha256":original_sha,
                        "confidence":"HIGH" if chosen['score']>=95 else "USER_SELECTED"},
           "candidates":candidates[:15]}
    manifest = {"generated_at_utc":datetime.now(timezone.utc).isoformat(),
                "source_drive":str(root), "selection_policy":"NGN folder-scoped scan, or verified user-specified path; provisional",
                "projects":[rec]}
    out.mkdir(parents=True, exist_ok=True)
    manifest_file=out/'retrieval_manifest.json'
    if manifest_file.exists():
        prev = json.loads(manifest_file.read_text(encoding='utf-8'))
        entries = [x for x in prev.get('projects',[]) if x.get('project')=='NGN']
        if not entries or entries[0].get('selected',{}).get('sha256')!=original_sha:
            raise RuntimeError('Existing NGN retrieval manifest identifies a different source; choose a new --out path')
    else:
        manifest_file.write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(f'[RETRIEVED] {result} | NGN | {source.name} | sha256={original_sha}')
    print('[RECEIPT]', manifest_file)
    if digest(dest)!=original_sha:
        raise RuntimeError('Staged digest unexpectedly changed')
    launcher = HERE/'STAGE_AND_RUN_GENERAL_DOC_V03.py'
    if not launcher.exists():
        print(f'[READY] Download STAGE_AND_RUN_GENERAL_DOC_V03.py into root. Candidate is staged and verified.')
        return 2
    import subprocess
    cmd=[sys.executable,str(launcher),'--project','NGN','--retrieval',str(out),'--status-date',a.status_date]
    if a.run_id: cmd+=['--run-id',a.run_id]
    print('[NEXT] Launching structural inspection and review-driven Cleaner V03.',flush=True)
    return subprocess.call(cmd, cwd=str(HERE))

if __name__ == '__main__':
    try:
        sys.exit(main())
    except (RuntimeError,OSError,ValueError,KeyError) as exc:
        print(f'[STOP] {exc}', file=sys.stderr)
        sys.exit(1)
