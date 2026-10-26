"""Run the existing Cleaner with required report date and isolated working copies."""
from __future__ import annotations
import argparse
from datetime import datetime
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from cleaner_v07 import runtime as r
ROOT=Path(__file__).resolve().parent


def parse(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project',required=True)
    p.add_argument('--status-date',required=True,help='User-selected Jalali report date YYYY/MM/DD')
    g=p.add_mutually_exclusive_group(required=True)
    g.add_argument('--new-run',action='store_true');g.add_argument('--run-id')
    p.add_argument('--workbook',help='Retrieved workbook for new run; resumes use the run manifest')
    p.add_argument('--non-interactive',action='store_true')
    p.add_argument('--no-excel-navigation',action='store_true')
    p.add_argument('--review-engineering',action='store_true')
    p.add_argument('--edit-board-cell')
    p.add_argument('--color',choices=['auto','always','never'],default='auto')
    a=p.parse_args(argv);a.project=a.project.upper()
    if not re.fullmatch('[A-Z0-9_]+',a.project): p.error('Invalid project code')
    if a.run_id and not re.fullmatch('[A-Za-z0-9_-]+',a.run_id): p.error('Invalid run ID')
    from cleaner_core.field_schema import is_valid_jalali
    if not re.fullmatch(r'14\d{2}/\d{2}/\d{2}',a.status_date) or not is_valid_jalali(a.status_date):
        p.error('--status-date must be a valid Jalali date YYYY/MM/DD')
    if a.new_run and not a.workbook: p.error('--new-run requires --workbook')
    return a


def stage(a):
    if a.run_id:
        run=ROOT/'runs'/a.run_id;manifest=r.load(run/'run_manifest.json')
        if str(manifest.get('profile_name','')).upper()!=a.project: raise ValueError('Run belongs to another project')
        book=Path(manifest['workbook']['path']).resolve()
        if a.workbook and Path(a.workbook).resolve()!=book: raise ValueError('Resume workbook must match run manifest')
        progress=run/'general_doc_auto_progress.json'
        if progress.exists() and r.load(progress).get('status_date') not in (None,a.status_date):
            raise ValueError('Report date differs from saved run; start a new run for a different reporting date')
        return book
    source=Path(a.workbook).resolve()
    if not source.is_file(): raise FileNotFoundError(source)
    if source.suffix.lower()!='.xlsx': raise ValueError('V07 working-copy workflow currently supports .xlsx')
    stamp=datetime.now().strftime('%Y%m%dT%H%M%S%f')
    folder=ROOT/'working'/'GENERAL_DOCUMENT'/a.project/stamp
    folder.mkdir(parents=True)
    snapshot=folder/('RETRIEVED__'+source.name)
    book=folder/(a.project+'_GENERAL_DOC_CLEANER_WORKING.xlsx')
    shutil.copyfile(source,snapshot);shutil.copyfile(snapshot,book)
    r.save(folder/'source_lineage.json',dict(project=a.project,status_date=a.status_date,source=str(source),
        source_sha256=r.digest(source),snapshot=str(snapshot),working_copy=str(book),copied_at=datetime.now().astimezone().isoformat()))
    print('[STAGED]',book)
    return book


def main(argv=None):
    a=parse(argv);book=stage(a)
    m=r.import_path('_general_document_v06',ROOT/'RUN_GENERAL_DOCUMENT_V06.py')
    child=ROOT/'cleaner_v07'/'child.py'
    raw_run=subprocess.run
    # Route all existing V06 pipeline/reviewer child calls through scoped adapters.
    def adapted(command,*args,**kwargs):
        if isinstance(command,(list,tuple)) and len(command)>1:
            script=Path(str(command[1]))
            if script.name in {'project_pipeline.py','weekly_report_pipeline.py','review_findings.py'}:
                command=[command[0],str(child),*command[1:]]
        return raw_run(command,*args,**kwargs)
    original_review=m.interactive_stage_review
    def review(args,run_dir,stage):
        queue=run_dir/f'{stage.lower()}_review_queue.json'
        decisions=run_dir/f'{stage.lower()}_review_decisions.json'
        if queue.is_file():
            out=m.run_cmd([sys.executable,str(child),'known',str(queue),str(decisions)],cwd=ROOT)
            print(out.strip())
            if m.decisions_complete(run_dir,stage): return True
        return original_review(args,run_dir,stage)
    m.interactive_stage_review=review
    original_board=m.guarded_board_to_log
    def board(args,run_dir):
        print(m.run_cmd([sys.executable,str(child),'materialize',str(run_dir)],cwd=ROOT).strip())
        result=original_board(args,run_dir)
        # Interactive Board repairs can change the overlay within the call.
        print(m.run_cmd([sys.executable,str(child),'materialize',str(run_dir)],cwd=ROOT).strip())
        return result
    m.guarded_board_to_log=board
    forwarded=['--project',a.project,'--status-date',a.status_date,'--workbook',str(book),'--color',a.color]
    forwarded+=['--run-id',a.run_id] if a.run_id else ['--new-run']
    for flag in ('non_interactive','no_excel_navigation','review_engineering'):
        if getattr(a,flag): forwarded+=['--'+flag.replace('_','-')]
    if a.edit_board_cell: forwarded+=['--edit-board-cell',a.edit_board_cell]
    old_argv=sys.argv[:]
    try:
        subprocess.run=adapted
        sys.argv=[str(ROOT/'RUN_GENERAL_DOCUMENT_V06.py'),*forwarded]
        print('[REPORT DATE]',a.status_date)
        return m.main()
    finally:
        subprocess.run=raw_run;sys.argv=old_argv

if __name__=='__main__':
    try: raise SystemExit(main())
    except Exception as exc:
        print('[ERROR]',exc);raise SystemExit(1)
