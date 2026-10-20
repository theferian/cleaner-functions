#!/usr/bin/env python3
r"""Safe local pointer update: portfolio auditor invokes V06 review UI instead of V05.

Run from cleaner-functions root:
  py .\ENABLE_PORTFOLIO_REVIEW_V06.py --check
  py .\ENABLE_PORTFOLIO_REVIEW_V06.py --apply

Source workbooks, historical runs, and review files are never touched.
"""
from __future__ import annotations
import argparse
from datetime import datetime
from pathlib import Path
import shutil
import sys
ROOT=Path(__file__).resolve().parent
OLD="RUNNER='RUN_GENERAL_DOCUMENT_V05.py'"
NEW="RUNNER='RUN_GENERAL_DOCUMENT_V06.py'"

def main(argv=None):
 p=argparse.ArgumentParser(description=__doc__)
 g=p.add_mutually_exclusive_group(required=True)
 g.add_argument('--check',action='store_true')
 g.add_argument('--apply',action='store_true')
 args=p.parse_args(argv)
 target=ROOT/'PORTFOLIO_GENERAL_DOC_AUDIT.py'
 version=ROOT/'RUN_GENERAL_DOCUMENT_V06.py'
 if not target.is_file() or not version.is_file():
  print('[STOP] Missing portfolio auditor or V06 runner in repository root; no files changed.');return 1
 raw=target.read_text(encoding='utf-8')
 if raw.count(OLD)==0 and raw.count(NEW)==1:
  print('[ALREADY ENABLED] Portfolio auditor uses V06; no files changed.');return 0
 if raw.count(OLD)!=1 or raw.count(NEW):
  print('[STOP] Unknown portfolio runner declaration; refusing to edit. No files changed.');return 1
 print('[CHECK] Replace only the exact portfolio RUNNER assignment: V05 -> V06.')
 if args.check:
  print('[CHECK] No files changed.');return 0
 backup=ROOT/f'_portfolio_runner_v06_backup_{datetime.now().strftime("%Y%m%d_%H%M%S%f")}'
 backup.mkdir(exist_ok=False)
 shutil.copy2(target,backup/target.name)
 temp=target.with_suffix('.py.v06_tmp')
 temp.write_text(raw.replace(OLD,NEW),encoding='utf-8')
 try:
  compile(temp.read_text(encoding='utf-8'),str(temp),'exec')
  temp.replace(target)
 finally:
  if temp.exists():temp.unlink()
 print(f'[DONE] Portfolio auditor now invokes V06. Backup: {backup}')
 return 0

if __name__=='__main__':
 sys.exit(main())
