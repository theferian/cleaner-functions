#!/usr/bin/env python3
"""Stage latest plausible General Documents from mapped W: drive, never edit originals.

Usage (Windows CMD): py retrieve_general_docs.py
Optional: py retrieve_general_docs.py --drive W:\\ --out "C:\\Users\\...\\Desktop\\General_Doc_Retrieval"

The files are CANDIDATES until explicitly operator approved.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
from datetime import datetime, timezone
from zipfile import ZipFile, ZIP_DEFLATED

PROJECTS = [
    dict(id='AZD', folder='00-1403', prefix='1403-02-05', known=['general - azad.xlsx']),
    dict(id='JND', folder='00-1403', prefix='1403-02-03', known=['general - jondi shapour.xlsx']),
    dict(id='FSH', folder='00-1403', prefix='1403-02-01', known=['gostaresh e folad e shahriar - updated doc.xlsx']),
    dict(id='YSK', folder='00-1400', prefix='140002-03', known=[]),
    dict(id='EYV', folder='00-1401', prefix='140102-09', known=['general-ivanaki.xlsx']),
    dict(id='BFG', folder='00-1403', prefix='1403-02-02', known=['baafgh..xlsx'], must_path=('baafgh', 'bafgh')),
    dict(id='NKH', folder='00-1403', prefix='1403-02-02', known=[], must_path=('nakhlestan', 'nakhl')),
]
EXTS = {'.xlsx', '.xlsm', '.xls', '.xlsb'}
EXCLUDED_PARTS = ('coverage_audit', 'weekly', 'report', 'progress', 'template', 'wbs', 'schedule', 'test', 'compare', 'backup', 'logbook', 'old version', 'transmittal', 'answer to comment', 'vendor')


def norm(value: str) -> str:
    return re.sub(r'\s+', ' ', value.casefold().strip())


def sha256(path: Path) -> str:
    d = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            d.update(chunk)
    return d.hexdigest()


def root_for(drive: Path, p: dict) -> Path | None:
    parent = drive / p['folder']
    if not parent.is_dir():
        return None
    try:
        items = [x for x in parent.iterdir() if x.is_dir() and norm(x.name).startswith(p['prefix'])]
    except OSError:
        return None
    return sorted(items, key=lambda x: len(x.name))[0] if items else None


def walk_files(root: Path, limit: int = 20000):
    """Walk in deterministic order; tolerate inaccessible subfolders; never follow links."""
    stack = [(root, 0)]
    seen = 0
    while stack:
        folder, depth = stack.pop()
        if depth > 10:
            continue
        try:
            entries = list(os.scandir(folder))
        except OSError:
            continue
        for e in sorted(entries, key=lambda e: e.name.casefold()):
            try:
                if e.is_file(follow_symlinks=False):
                    seen += 1
                    if seen > limit:
                        return
                    yield Path(e.path)
                elif e.is_dir(follow_symlinks=False) and depth < 10:
                    if e.name.casefold() not in {'.git', '__pycache__', 'node_modules'}:
                        stack.append((Path(e.path), depth + 1))
            except OSError:
                continue


def candidate(p: dict, path: Path, root: Path):
    if path.suffix.casefold() not in EXTS or path.name.startswith('~$'):
        return None
    filename = norm(path.name)
    rel = norm(str(path.relative_to(root)))
    if any(bad in filename for bad in EXCLUDED_PARTS):
        return None
    if p.get('must_path') and not any(token in rel for token in p['must_path']):
        return None
    known = filename in p['known']
    general = ('general' in filename or 'latest_general_doc' in filename)
    updated_name = ('updated doc' in filename or 'updated_doc' in filename)
    updated_dir = ('updated doc' in rel or 'updated_doc' in rel or 'updated document' in rel)
    # Avoid blindly selecting other technical XLSX files just because they reside in a project folder.
    if not (known or general or updated_name or updated_dir):
        return None
    score = (100 if known else 0) + (70 if general else 0) + (40 if updated_name else 0) + (20 if updated_dir else 0)
    if '/letter/' in rel.replace('\\', '/') or '\\letter\\' in rel:
        score += 5
    if p['id'] in {'BFG','NKH'} and p.get('must_path'):
        score += 20
    try:
        st=path.stat()
        if st.st_size == 0:
            return None
        return {'source':str(path), 'score':score, 'modified':st.st_mtime, 'bytes':st.st_size,
                'name':path.name, 'confidence': 'HIGH' if score>=70 else 'REVIEW_REQUIRED'}
    except OSError:
        return None


def main():
    pa = argparse.ArgumentParser(description=__doc__)
    pa.add_argument('--drive', default='W:\\', help='Root of mapped source drive, default W:\\')
    pa.add_argument('--out', help='Output folder; default %%USERPROFILE%%\\Desktop\\General_Doc_Retrieval_<timestamp>')
    pa.add_argument('--projects', default='all', help='Comma-separated project IDs, e.g. BFG or YSK,EYV,NKH (default: all)')
    a = pa.parse_args()
    drive = Path(a.drive)
    if not drive.is_dir():
        print(f'[ERROR] Source drive unavailable: {drive}')
        print('Connect W: drive and rerun. No original files were modified.')
        return 2
    stamp=datetime.now().strftime('%Y%m%d_%H%M%S')
    desktop=Path(os.environ.get('USERPROFILE', str(Path.home()))) / 'Desktop'
    out=Path(a.out) if a.out else desktop / f'General_Doc_Retrieval_{stamp}'
    out.mkdir(parents=True, exist_ok=False) if not out.exists() else out.mkdir(parents=True)
    manifest={'generated_at_utc':datetime.now(timezone.utc).isoformat(), 'source_drive':str(drive),
              'selection_policy':'Highest project-specific General Document match score, then newest modification time within equal scores; unapproved pending review',
              'projects':[]}
    rows=[]; copied=[]
    wanted={x.strip().upper() for x in a.projects.split(',') if x.strip()}
    if 'ALL' not in wanted:
        unknown = wanted - {p['id'] for p in PROJECTS} - {'NGN'}
        if unknown:
            pa.error(f'Unknown project(s): {sorted(unknown)}')
    targets = PROJECTS if 'ALL' in wanted else [p for p in PROJECTS if p['id'] in wanted]
    for p in targets:
        root=root_for(drive,p)
        rec={'project':p['id'], 'project_root':str(root) if root else None,
             'status':'PROJECT_FOLDER_MISSING' if root is None else 'NO_CANDIDATES',
             'selected':None, 'candidates':[]}
        if root:
            found=[d for file in walk_files(root) if (d:=candidate(p,file,root))]
            # Prefer credible General Document title over unrelated but newer transmittals.
            found.sort(key=lambda c:(c['score'],c['modified'],c['bytes']),reverse=True)
            rec['candidates']=found[:15]
            if found:
                selected=found[0]
                dest=out/p['id']/selected['name']
                dest.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(selected['source'],dest)
                digest=sha256(dest)
                if digest!=sha256(Path(selected['source'])):
                    raise IOError(f'Hash mismatch for {p["id"]}: {selected["source"]}')
                rec['status']='COPIED_REVIEW_REQUIRED'
                rec['selected']={**selected, 'copy':str(dest), 'sha256':digest}
                copied.append(dest)
        print(f"{p['id']:>3} : {rec['status']}")
        if rec['selected']:
            s=rec['selected']
            print(f"      {s['name']} | {s['confidence']} | {datetime.fromtimestamp(s['modified']).isoformat(timespec='seconds')} | {s['bytes']:,} bytes")
            print(f"      SOURCE: {s['source']}")
        manifest['projects'].append(rec)
        rows.append({'project':p['id'], 'status':rec['status'],
                     'filename':rec['selected']['name'] if rec['selected'] else '',
                     'source':rec['selected']['source'] if rec['selected'] else '',
                     'source_modified_local':datetime.fromtimestamp(rec['selected']['modified']).isoformat(timespec='seconds') if rec['selected'] else '',
                     'sha256':rec['selected']['sha256'] if rec['selected'] else '',
                     'confidence':rec['selected']['confidence'] if rec['selected'] else '',
                     'candidates_found':len(rec['candidates'])})
    if 'ALL' in wanted or 'NGN' in wanted:
        manifest['projects'].append({'project':'NGN','status':'NO_DOCUMENTS_EXPECTED','selected':None,'candidates':[]})
        rows.append({'project':'NGN', 'status':'NO_DOCUMENTS_EXPECTED', 'filename':'', 'source':'', 'source_modified_local':'', 'sha256':'', 'confidence':'', 'candidates_found':0})
    jpath=out/'retrieval_manifest.json'
    jpath.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    cpath=out/'retrieval_manifest.csv'
    with cpath.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    zpath=out/'General_Doc_Retrieval.zip'
    with ZipFile(zpath,'w',ZIP_DEFLATED,compresslevel=4) as z:
        for source in copied:
            z.write(source, source.relative_to(out).as_posix())
        z.write(jpath,jpath.name);z.write(cpath,cpath.name)
    print(f'\n[RESULT] {len(copied)}/{len(targets)} copied into {out}')
    print(f'[ZIP] {zpath}')
    print('[NOTE] Highest-confidence candidate selected; newest only among equally strong matches. Review before approving.')
    return 0 if len(copied)==len(targets) else 1


if __name__ == '__main__':
    raise SystemExit(main())
