"""Safe, additive Mass Reader V02 bugfix installer. Run from cleaner-functions root."""
from __future__ import annotations
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import sys
import tempfile
from datetime import datetime, timezone

FILES = [
    'mass_reader_v01/core.py',
    'mass_reader_v01/static/app.js',
    'mass_reader_v01/static/app.css',
    'mass_reader_v01/static/index.html',
    'tests/test_mass_reader_v02.py',
]

def digest(p):
    h = hashlib.sha256()
    with p.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024),b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    p=argparse.ArgumentParser(description='Mass Reader V02: prompt stop + stable dashboard')
    mode=p.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check',action='store_true')
    mode.add_argument('--apply',action='store_true')
    p.add_argument('--allow-modified',action='store_true',help='Explicitly allow replacing locally modified V01 source files (backups still created)')
    args=p.parse_args()
    root=Path(__file__).resolve().parent
    payload=root/'mass_reader_v02_update'
    if not (root/'MASS_READER_V01.py').is_file() or not (root/'mass_reader_v01/core.py').is_file():
        print('[ERROR] Extract package to cleaner-functions root (next to MASS_READER_V01.py)');return 2
    expected={
        'mass_reader_v01/core.py': '109734efd60a16d9d7f5930bf9cef96592352aa53ee309b0d298c3382722ce7d',
        'mass_reader_v01/static/app.js': '476a9e7c31f94d6a9a8f954ee869066e906fc26c39e0db6c63c1904409e11b52',
        'mass_reader_v01/static/app.css': '65beb7063fab5b543cbf9cc199cb260e6cc2cd41a0ba70cd94d292265325827e',
        'mass_reader_v01/static/index.html': '8407694a90a4c26acc9dfbb1b7d80b05d4c8f74863dd2d10d6415c6d8ce4c62c',
    }
    changes=[];unexpected=[]
    for name in FILES:
        src=payload/name;dst=root/name
        if not src.is_file():
            print('[ERROR] Missing payload:',src);return 2
        if dst.exists() and digest(dst)==digest(src):
            print('[ALREADY UPDATED]',name)
            continue
        if dst.exists() and name in expected and digest(dst)!=expected[name]:
            unexpected.append(name)
        changes.append((src,dst,name))
        print('[PATCH]',name,('(new)' if not dst.exists() else '(back up and replace)'))
    if unexpected:
        print('[NOTICE] Modified/unrecognized V01 code:',', '.join(unexpected))
        print('[SAFETY] These files will be backed up. Use --allow-modified with --apply if changes are intentional.')
    if args.check:
        print('[CHECK] Changes:',len(changes),'| Database untouched: working\\mass_reader\\state.sqlite3')
        return 0
    if unexpected and not args.allow_modified:
        print('[BLOCKED] Run --check, inspect local changes, or explicitly add --allow-modified.');return 3
    if not changes:
        print('[DONE] Already installed');return 0
    backup=root/'working'/'mass_reader'/'patch_backups'/('v02_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    backup.mkdir(parents=True,exist_ok=True)
    for src,dst,name in changes:
        if dst.exists():
            dest=backup/name;dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(dst,dest)
    print('[BACKUP]',backup)
    for src,dst,name in changes:
        dst.parent.mkdir(parents=True,exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=dst.parent,prefix='.mr_v02_',delete=False) as f:
            temp=Path(f.name)
            f.write(src.read_bytes())
        try:os.replace(temp,dst)
        finally:temp.unlink(missing_ok=True)
        print('[INSTALLED]',name)
    print('[DONE] Restart Mass Reader on port 8877 and hard-refresh Edge (Ctrl+Shift+R).')
    return 0

if __name__=='__main__':raise SystemExit(main())
