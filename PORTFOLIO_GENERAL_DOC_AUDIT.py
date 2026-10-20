#!/usr/bin/env python3
r"""Eight-project GENERAL_DOCUMENT audit, source retrieval, clean/replay and exception register.

Place in CLEANER ROOT (next to RUN_GENERAL_DOCUMENT_V05.py). Python standard library only.

Windows CMD:
  py .\PORTFOLIO_GENERAL_DOC_AUDIT.py --check
  py .\PORTFOLIO_GENERAL_DOC_AUDIT.py --run --status-date 1405/07/22
  py .\PORTFOLIO_GENERAL_DOC_AUDIT.py --run --fresh --status-date 1405/07/22

Default --run REPLAYS the latest existing run: six reviewed stages stay intact;
Board-to-Log, Coverage and Engineering are recalculated. --fresh creates new
independent run(s) on identical verified working copies; may need more reviews.
No original/network/working copies are overwritten. Existing run outputs may be
recomputed in replay mode; prior versions are archived inside this audit folder.
The audit output is CSV/JSON/Markdown in portfolio_audits/<timestamp>/.
Exit: 0=all processed (provisional permitted), 2=review/source blocker,
1=fatal/test failure. Always writes a combined register if possible.
"""
from __future__ import annotations
import argparse, csv, hashlib, json, os, re, shutil, subprocess, sys, traceback
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parent
PROJECTS=('AZD','JND','FSH','YSK','EYV','BFG','NKH','NGN')
KNOWN_RUNS={'AZD':'azd_20261014T071802','JND':'jnd_20261007T022038',
            'FSH':'fsh_20261007T024351','YSK':'ysk_20261016T212108',
            'EYV':'eyv_20261017T020820','BFG':'bfg_20261017T130419',
            'NKH':'nkh_20261017T053117','NGN':'ngn_20261017T143536'}
RUNNER='RUN_GENERAL_DOCUMENT_V06.py'
REPORT_DATE='1405/07/22'
KNOWN_SOURCE_PATHS={
'AZD':r'W:\00-1403\1403-02-05-230kV Azad\Letter\technical\updated Doc\General - Azad.xlsx',
'JND':r'W:\00-1403\1403-02-03-400-132kv Jondi Shapoor\Letter\technical\Updated Doc\General - Jondi Shapour.xlsx',
'FSH':r'W:\00-1403\1403-02-01-132kV Gostarsh Foulad shahryar\Letter\technical\GOSTARESH E FOLAD E SHAHRIAR - UPDATED DOC.xlsx',
'YSK':r'W:\00-1400\140002-03- 63kv hasan abad yasookand\letter\technical\updated Doc\Yasookand-General.xlsx',
'EYV':r'W:\00-1401\140102-09- 63kv Ivanaki\letter\technical\updated Doc\General-IVANAKI.xlsx',
'BFG':r'W:\00-1403\1403-02-02-132kv Foulad Bafgh Kasra and Ext. of Nakhlestan\Letter\technical\Baafgh\updated Doc\Baafgh..xlsx',
'NKH':r'W:\00-1403\1403-02-02-132kv Foulad Bafgh Kasra and Ext. of Nakhlestan\Letter\technical\Nakhlestan\updated Doc\Nakhlestan...xlsx',
'NGN':r'W:\00-1403\1403-02-04-Negin Boushehr\Letter\technical\پست سیار(جلسه فنی)\General - Negin.xlsx',
}

EXPORT_FIELDS=('project','run_id','family','source_proof','run_source_match','stage','exception_state',
               'severity','issue_type','source_sheet','source_cell','document_name','wbs',
               'revision','source_value','detail','action_for_team','owner_role','evidence_file','case_id')


def read_json(p:Path)->dict:
    try:
        data=json.loads(p.read_text(encoding='utf-8-sig'))
        return data if isinstance(data,dict) else {}
    except (OSError,ValueError):return {}

def hash_file(p:Path)->str:
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def verified_copy(source:Path,dest:Path,expected_hash:str)->None:
    if dest.exists():
        if hash_file(dest)!=expected_hash:raise ValueError(f'Existing audit source differs: {dest}')
        return
    dest.parent.mkdir(parents=True,exist_ok=True)
    tmp=dest.with_name(dest.name+'.part')
    if tmp.exists():raise ValueError(f'Unfinished/foreign temporary retrieval: {tmp}')
    try:
        shutil.copy2(source,tmp)
        if hash_file(tmp)!=expected_hash:raise ValueError(f'Source changed during retrieval: {source}')
        tmp.replace(dest)
    finally:tmp.unlink(missing_ok=True)

def stemname(v:str)->str:
    return re.sub(r'[^\w. -]+','_',v).strip()[:110]

def find_source_candidates(project:str)->list[tuple[str,Path]]:
    found=[]
    receipt=read_json(ROOT/'input'/'GENERAL_DOCUMENT'/project/'staging_receipt.json')
    if receipt.get('source_original_path'):found.append(('NETWORK_RECORDED',Path(receipt['source_original_path'])))
    # Older retrieval manifests have a distinct 'results' schema.
    for p in [ROOT/'input'/f'{project}_retrieval_manifest.json',ROOT/'input'/'GENERAL_DOCUMENT'/project/'retrieval_manifest.json']:
        for r in read_json(p).get('results',[]):
            if r.get('project_id')==project and r.get('source_path'):
                found.append(('NETWORK_RECORDED',Path(r['source_path'])))
    pdir=ROOT/'input'/'GENERAL_DOCUMENT'/project
    if pdir.exists():
        for p in sorted(pdir.glob('retrieval_*/retrieval_manifest.json'),reverse=True):
            for r in read_json(p).get('projects',[]):
                if r.get('project')==project and (r.get('selected') or {}).get('source'):
                    found.append(('NETWORK_RECORDED',Path(r['selected']['source'])))
    # Exact user-confirmed/retrieval-manifest paths; never scan whole W: drive.
    found.append(('NETWORK_KNOWN_PATH',Path(KNOWN_SOURCE_PATHS[project])))
    # Offline fallbacks are labelled: never call these a CURRENT network retrieval.
    for name in ('staged_source','working_copy'):
        if receipt.get(name):found.append(('LOCAL_RECEIPT_'+name.upper(),Path(receipt[name])))
    found.append(('LOCAL_STAGED',pdir/f'{project}_LATEST_GENERAL_DOC_UNAPPROVED.xlsx'))
    found.append(('LOCAL_WORKING',ROOT/'working'/'GENERAL_DOCUMENT'/project/f'{project}_GENERAL_DOC_CLEANER_WORKING.xlsx'))
    out=[]; seen=set()
    for kind,p in found:
        key=str(p).casefold()
        if key not in seen:
            seen.add(key);out.append((kind,p))
    return out

def find_run(project:str)->tuple[str,Path]|None:
    base=ROOT/'runs'; candidates=[]
    if not base.is_dir():return None
    for p in base.glob(project.lower()+'_*'):
        if not p.is_dir():continue
        m=read_json(p/'run_manifest.json')
        if str(m.get('profile_name','')).upper()==project and (p/'resolved_state.json').is_file():
            candidates.append((p.name,p))
    if candidates:
        finished=[item for item in candidates if (item[1]/'board_to_log.json').is_file() and (item[1]/'coverage_audit.json').is_file()]
        return sorted(finished or candidates,key=lambda x:x[0])[-1]
    preferred=base/KNOWN_RUNS[project]
    if (preferred/'run_manifest.json').is_file():return preferred.name,preferred
    return None

def retrieve(project:str,audit_dir:Path,run_dir:Path|None)->dict:
    manifest=read_json(run_dir/'run_manifest.json') if run_dir else {}
    run_hash=(manifest.get('workbook') or {}).get('sha256_at_run_start') or ''
    receipt=read_json(ROOT/'input'/'GENERAL_DOCUMENT'/project/'staging_receipt.json')
    expected=receipt.get('source_sha256') or run_hash
    source=None; kind='NONE'; remote_error=[]
    for k,p in find_source_candidates(project):
        if p.is_file():
            source=p;kind=k;break
        if k.startswith('NETWORK_'):remote_error.append(str(p))
    info={'project':project,'source_proof':'UNAVAILABLE','source_path':'','source_sha256':'',
          'original_path_recorded':remote_error[0] if remote_error else '',
          'run_start_sha256':run_hash,'run_source_match':'UNKNOWN','retrieved_path':'',
          'current_network_verified':False,'notes':''}
    if source is None:
        info['notes']='Neither recorded network file nor verified local source available'
        return info
    current_hash=hash_file(source)
    dest=audit_dir/'retrieval'/project/(stemname(source.name) or f'{project}.xlsx')
    verified_copy(source,dest,current_hash)
    info.update(source_proof=kind,source_path=str(source),source_sha256=current_hash,
                retrieved_path=str(dest),current_network_verified=kind.startswith('NETWORK_'),
                run_source_match=('MATCH' if run_hash and current_hash==run_hash else ('DRIFT' if run_hash else 'UNKNOWN')))
    if not kind.startswith('NETWORK_'):info['notes']='Local offline copy only; network freshness NOT verified'
    if expected and current_hash!=expected:info['notes']+=' | source changed vs staging receipt'
    return info

def register_row(project:str,run_id:str,src:dict,**kw)->dict:
    row={k:'' for k in EXPORT_FIELDS}
    row.update(project=project,run_id=run_id,family='GENERAL_DOCUMENT',
               source_proof=src.get('source_proof',''),run_source_match=src.get('run_source_match',''))
    row.update({k:str(v) if v is not None else '' for k,v in kw.items() if k in row})
    return row

def suggested_action(kind:str,state:str)->tuple[str,str]:
    t=kind.upper()
    if 'MISSING_REFERENCE' in t:return ('Enter original response reference or meeting-minutes label in RECEIVE reference cell; attach/minute-link evidence. Never invent number.','Engineering / Correspondence')
    if 'ORPHAN_REFERENCE' in t:return ('Verify send/receive date directly above reference, correct source date using guarded change, then re-extract.','Engineering / Correspondence')
    if 'MISSING_RECEIVE_STATUS' in t or 'UNKNOWN_RECEIVE_STATUS' in t:return ('Confirm approval code with consultant and enter it in STATUS lane (not DATE lane).','Engineering / Consultant')
    if 'DATE_INVERSION' in t or 'SAME_DAY' in t:return ('Compare board events with letters and minutes; record event order or retain investigated exception.','Engineering / Project Control')
    if 'UNDATED' in t:return ('Locate missing event dates from correspondence; preserve original unknown until verified.','Engineering / Project Control')
    if 'WBS' in t:return ('Confirm document-to-WBS mapping with project control; generated IDs are not official WBS.','Project Control')
    if 'M_LINE' in t or 'MERGE' in t:return ('Confirm intentional template separator/merge against approved board geometry.','Document Control')
    if state=='HISTORICAL_CORRECTION':return ('Verify correction against source; keep original-value and repair audit.','Document Control')
    return ('Inspect original board, corresponding letter/minutes, and update or document accepted exception.','Document Control / Project Control')

def parse_exception_rows(project:str,run_id:str,run_dir:Path,src:dict)->list[dict]:
    out=[]
    def add(stage,state,severity,kind,sheet='',cell='',doc='',wbs='',revision='',value='',detail='',evidence='',case_id=''):
        action,owner=suggested_action(kind,state)
        out.append(register_row(project,run_id,src,stage=stage,exception_state=state,severity=severity,
          issue_type=kind,source_sheet=sheet,source_cell=cell,document_name=doc,wbs=wbs,
          revision=revision,source_value=value,detail=detail,action_for_team=action,
          owner_role=owner,evidence_file=evidence,case_id=case_id))
    board=read_json(run_dir/'board_to_log.json')
    live_keys=set()
    historical_seen=set()
    for n,issue in enumerate(board.get('issues') or []):
        if not isinstance(issue,dict):continue
        kind=str(issue.get('kind') or 'EXTRACTION_ISSUE')
        sheet=str(issue.get('sheet') or '');cell=str(issue.get('address') or '')
        live_keys.add((kind,sheet,cell))
        ev=issue.get('evidence') or {}
        add('BOARD_TO_LOG','OPEN_REVIEWED' if (run_dir/'board_to_log_review.json').exists() else 'OPEN',
            'HIGH',kind,sheet,cell,str(issue.get('doc_name') or ''),revision=str(issue.get('revision') or ''),
            value=str(ev.get('value') or ''),detail=str(issue.get('message') or ''),
            evidence=str(run_dir/'board_to_log_issue_context.json'),case_id=f'{project}-BOARD-{n+1:04d}')
    eng=read_json(run_dir/'engineering_lists'/'engineering_three_lists.json')
    for n,diag in enumerate(eng.get('diagnostics') or []):
        if not isinstance(diag,dict):continue
        kind=str(diag.get('kind') or diag.get('reason') or diag.get('code') or 'REPORT_DIAGNOSTIC')
        detail=json.dumps({k:v for k,v in diag.items() if k not in ('source_sheet','doc_name','doc_wbs','kind')},ensure_ascii=False,default=str)
        add('ENGINEERING','OPEN_ACKNOWLEDGED' if (run_dir/'engineering_review.json').exists() else 'OPEN',
            'MEDIUM',kind,sheet=str(diag.get('source_sheet') or ''),doc=str(diag.get('doc_name') or ''),
            wbs=str(diag.get('doc_wbs') or ''),detail=detail,evidence=str(run_dir/'engineering_lists'/'engineering_three_lists.json'),
            case_id=f'{project}-ENG-{n+1:04d}')
    # Retain approved structural exceptions, including family template separators.
    ex=read_json(ROOT/'exceptions'/f'{project}.exceptions.json')
    for case in ex.get('cases') or []:
        if not isinstance(case,dict):continue
        match=case.get('match') or {}; history=case.get('history') or []
        latest=history[-1] if history else {}
        kind=str(match.get('audit_kind') or match.get('test_id') or 'REGISTERED_EXCEPTION')
        status=str(latest.get('workflow_status') or 'REGISTERED')
        add('EXCEPTION_REGISTRY',status,'INFO' if 'ACCEPTED' in status else 'MEDIUM',kind,
            sheet=str(match.get('sheet') or ''),cell=str(match.get('target') or ''),
            detail=str(latest.get('note') or ''),case_id=str(case.get('handle') or ''),
            evidence=str(ROOT/'exceptions'/f'{project}.exceptions.json'))
    # Recorded stage decisions remain discoverable, even when automated or corrected.
    resolved=read_json(run_dir/'resolved_state.json')
    for queue_file in sorted(run_dir.glob('*_review_queue.json')):
        stage=queue_file.name.removesuffix('_review_queue.json').upper()
        if stage in ('BOARD_TO_LOG',):continue
        decisions=read_json(run_dir/f'{stage.lower()}_review_decisions.json')
        by_id={str(d.get('review_id')):d.get('decision') or {} for d in decisions.get('decisions') or [] if isinstance(d,dict)}
        for item in read_json(queue_file).get('items') or []:
            if not isinstance(item,dict):continue
            rid=str(item.get('review_id') or ''); loc=item.get('location') or {}
            decision=by_id.get(rid)
            stage_reviewed=str(((resolved.get('stages') or {}).get(stage) or {}).get('status') or '')=='REVIEWED'
            state='REVIEW_DECIDED' if decision else 'REVIEWED_IN_STATE' if stage_reviewed else 'REVIEW_PENDING'
            kind=str((item.get('source') or {}).get('test_id') or stage)
            msg=str(item.get('message') or '')
            detail=msg+(f" | Decision: {decision.get('action')} {json.dumps(decision.get('parameters') or {},ensure_ascii=False)}" if decision else '')
            add(stage,state,'MEDIUM',kind,sheet=str(loc.get('sheet') or ''),cell=str(loc.get('target') or ''),
                value=str(item.get('observed') or ''),detail=detail,evidence=str(queue_file),case_id=rid)
    # Discover superseded board issues from archived runs without turning them into live defects.
    for old in list(run_dir.glob('discovery_history/**/board_to_log.json'))+list(run_dir.glob('board_to_log_repair_history/**/board_to_log.json')):
        for issue in read_json(old).get('issues') or []:
            if not isinstance(issue,dict):continue
            kind=str(issue.get('kind') or 'HISTORICAL_ISSUE');sheet=str(issue.get('sheet') or '');cell=str(issue.get('address') or '')
            if (kind,sheet,cell) in live_keys:continue
            # Stable signature avoids replay-history spam.
            key=(kind,sheet,cell)
            if key in historical_seen:continue
            historical_seen.add(key)
            add('DISCOVERY_HISTORY','HISTORICAL_CORRECTION','INFO',kind,sheet,cell,
                detail=str(issue.get('message') or ''),evidence=str(old))
    return out

def csv_save(path:Path,items:list[dict],fields:tuple[str,...]):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader()
        for entry in items:
            # Excel/CSV injection guard for untrusted workbook-derived text.
            safe={}
            for k,v in entry.items():
                if isinstance(v,str) and v.lstrip().startswith(('=','+','-','@')):
                    safe[k]="'"+v
                else:safe[k]=v
            w.writerow(safe)

def find_docs(run_dir:Path)->int|str:
    regions=read_json(run_dir/'document_regions.json')
    for info in (regions.get('sheets') or {}).values():
        if isinstance(info,dict) and isinstance(info.get('regions'),list):
            # Count all sheets below; processed after loop.
            return sum(len(v.get('regions') or []) for v in (regions.get('sheets') or {}).values() if isinstance(v,dict))
    for k in ('regions','document_regions'):
        val=regions.get(k)
        if isinstance(val,list):return len(val)
    cards=read_json(run_dir/'card_maps.json')
    if isinstance(cards.get('sheets'),dict):
        return sum(len(v.get('cards') or []) for v in cards['sheets'].values() if isinstance(v,dict))
    for k in ('cards','card_maps'):
        v=cards.get(k)
        if isinstance(v,list):return len(v)
    return ''

def summary_row(project:str,run_id:str,run_dir:Path|None,source:dict,status:str,detail:str='')->dict:
    row={'project':project,'run_id':run_id,'source_proof':source.get('source_proof',''),
         'source_sha256':source.get('source_sha256',''),'run_source_match':source.get('run_source_match',''),
         'remote_current':source.get('current_network_verified',False),'execution':status,
         'document_count':'','record_count':'','board_issues':'','mapped_slots':'','unretrieved_slots':'',
         'coverage_open_issues':'','report_diagnostics':'','not_sent':'','company_delay':'','consultant_delay':'',
         'detail':detail}
    if not run_dir:return row
    board=read_json(run_dir/'board_to_log.json');audit=read_json(run_dir/'coverage_audit.json')
    eng=read_json(run_dir/'engineering_lists'/'engineering_three_lists.json')
    bs=board.get('summary') or {};cs=audit.get('summary') or {}; cc=cs.get('counts') or {}; es=eng.get('summary') or {}
    row.update(document_count=find_docs(run_dir),record_count=bs.get('record_count',''),
       board_issues=len(board.get('issues') or []) if board else '',
       mapped_slots=cs.get('mapped_nonempty_count',''),
       unretrieved_slots=cc.get('SCANNED_NOT_RETRIEVED',''),
       coverage_open_issues=cc.get('UNRESOLVED_ISSUE',''),
       report_diagnostics=es.get('diagnostic_count',len(eng.get('diagnostics') or [])) if eng else '',
       not_sent=es.get('not_sent',''),company_delay=es.get('company_delay',''),consultant_delay=es.get('consultant_delay',''))
    return row

def snapshot_previous_outputs(run_dir:Path,dest:Path):
    """Immutable pre-replay copies; never erase prior correspondence evidence."""
    names=('board_to_log.json','board_to_log_issues.csv','board_to_log_issue_context.json',
           'coverage_audit.json','board_to_log_review.json','engineering_review.json',
           'general_doc_auto_progress.json','resolved_state.json')
    dest.mkdir(parents=True,exist_ok=False)
    manifest=[]
    for name in names:
        src=run_dir/name
        if src.is_file():
            shutil.copy2(src,dest/name)
            manifest.append({'path':str(src),'sha256':hash_file(dest/name)})
    eng=run_dir/'engineering_lists'
    if eng.is_dir():
        for src in eng.iterdir():
            if src.is_file():
                (dest/'engineering_lists').mkdir(exist_ok=True)
                shutil.copy2(src,dest/'engineering_lists'/src.name)
                manifest.append({'path':str(src),'sha256':hash_file(dest/'engineering_lists'/src.name)})
    (dest/'archive_manifest.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    return len(manifest)

def write_guide_index(out:Path,summary:list[dict],exceptions:list[dict],audit_id:str,status_date:str):
    counts=Counter(x['exception_state'] for x in exceptions)
    lines=[f'# GENERAL_DOCUMENT portfolio evidence — {audit_id}','',f'**Jalali reporting date:** {status_date}',
    '', '**Meaning:** this is a technical audit, not business sign-off. Network unavailable/locally sourced files are not current-verified.',
    '', '| Project | Source proof | Run hash | Execution | Records | Not retrieved | Open extraction | Diagnostics |',
    '|---|---|---|---|---:|---:|---:|---:|']
    for r in summary:
        def esc(v):return str(v).replace('|','/')
        lines.append('| '+' | '.join(esc(r.get(k,'')) for k in ('project','source_proof','run_source_match','execution','record_count','unretrieved_slots','board_issues','report_diagnostics'))+' |')
    lines+=['','## Exception inventory','',' '.join(f'{k}: {v}.' for k,v in sorted(counts.items())),
           '', 'See `exception_register.csv` for every row with a source pointer, owner, recommended action and historical status.',
           'See `source_inventory.csv` for original path, retrieved audit copy and SHA-256.',
           '', '### Review policy',
           '- OPEN issues are project-team tasks even when acknowledged for provisional continuation.',
           '- Historical/accepted items remain discoverable but must not be counted as current defects.',
           '- Zero unmapped source slots does not mean zero correspondence defects.',
           '- A corrected local working copy does not constitute a modified or approved network original.',
           '- Do not publish NGN-generated document keys as official WBS identifiers.',
           '- Source hash drift needs explicit reconciliation and a new run rather than reusing an old run.',
           '', 'Use `GENERAL_DOCUMENT_PROJECT_TEAM_GUIDE.md` for data entry and escalation rules.']
    (out/'PORTFOLIO_SUMMARY.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')

def runner_for(project:str,run_id:str|None,status_date:str,fresh:bool,interactive:bool,book:Path)->list[str]:
    cmd=[sys.executable,str(ROOT/RUNNER),'--project',project,'--status-date',status_date]
    cmd+=(['--new-run'] if fresh else ['--run-id',run_id])
    cmd+=['--workbook',str(book)]
    if not interactive:cmd+=['--non-interactive','--no-excel-navigation']
    return cmd

def selected_projects(raw:str)->list[str]:
    if raw.upper()=='ALL':return list(PROJECTS)
    names=[s.strip().upper() for s in raw.split(',') if s.strip()]
    if not names or len(names)!=len(set(names)) or any(s not in PROJECTS for s in names):
        raise ValueError('Projects must be ALL or a unique comma-separated subset of '+','.join(PROJECTS))
    return names

def create_audit_dir(base:Path,run:bool)->Path:
    base.mkdir(parents=True,exist_ok=True)
    date=datetime.now().strftime('%Y%m%dT%H%M%S')
    target=base/('portfolio_'+date+'_'+('RUN' if run else 'CHECK'))
    for i in range(1,100):
        choice=target if i==1 else Path(str(target)+f'_{i:02d}')
        try:choice.mkdir(exist_ok=False);return choice
        except FileExistsError:pass
    raise RuntimeError('Cannot allocate unique audit directory')

def main(argv=None)->int:
    parser=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check',action='store_true',help='Inventory & exception export only; no Cleaner rerun')
    mode.add_argument('--run',action='store_true',help='Re-run Cleaner extraction, coverage and Engineering for selected projects')
    parser.add_argument('--projects',default='ALL',help='ALL or comma-separated codes')
    parser.add_argument('--status-date',default=REPORT_DATE,help='Jalali YYYY/MM/DD')
    parser.add_argument('--fresh',action='store_true',help='Start new six-stage runs; may need reviews; does NOT overwrite earlier runs')
    parser.add_argument('--skip-tests',action='store_true',help='Do not run repo regression suite before --run')
    parser.add_argument('--non-interactive',action='store_true',help='No review prompts; log and continue other projects')
    parser.add_argument('--audit-root',default='portfolio_audits')
    args=parser.parse_args(argv)
    if args.fresh and not args.run:parser.error('--fresh requires --run')
    if not re.fullmatch(r'14\d{2}/\d{2}/\d{2}',args.status_date):parser.error('Invalid Jalali date')
    try:projects=selected_projects(args.projects)
    except ValueError as exc:parser.error(str(exc))
    if args.run and not (ROOT/RUNNER).is_file():parser.error(f'Missing {RUNNER}; copy into Cleaner root')
    audit_root=Path(args.audit_root);audit_root=audit_root if audit_root.is_absolute() else ROOT/audit_root
    out=create_audit_dir(audit_root,args.run)
    print('[AUDIT]',out,flush=True)
    env=os.environ.copy();env['PYTHONIOENCODING']='utf-8'
    for k in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):env[k]='1'
    can_run=True
    if args.run and not args.skip_tests:
        print('[TEST] Cleaner regression suite',flush=True)
        test=subprocess.run([sys.executable,'-m','pytest','-q','--ignore=payload','--import-mode=importlib'],
                            cwd=ROOT,env=env,capture_output=True,text=True,errors='replace')
        (out/'pytest_output.txt').write_text((test.stdout or '')+'\n'+(test.stderr or ''),encoding='utf-8')
        print('[TEST]',(test.stdout or test.stderr or '').strip().splitlines()[-1] if (test.stdout or test.stderr) else f'exit={test.returncode}',flush=True)
        if test.returncode!=0:can_run=False
    source_rows=[];summaries=[];exceptions=[];blocked=not can_run
    for project in projects:
        found=find_run(project)
        run_id,run_dir=found if found else ('',None)
        try:
            src=retrieve(project,out,run_dir)
        except Exception as exc:
            src={'project':project,'source_proof':'RETRIEVAL_ERROR','run_source_match':'UNKNOWN',
                 'notes':repr(exc),'source_sha256':'','retrieved_path':'','source_path':''}
        source_rows.append(src)
        status='CHECKED' if args.check else 'SKIPPED'
        detail='';active_run=run_dir;active_id=run_id
        if args.run:
            if not can_run:status='BLOCKED_TEST_FAILURE';detail='Fix pytest failures first'
            elif run_dir is None and not args.fresh:status='REVIEW_REQUIRED';detail='No existing run. Stage source and run --fresh.'
            elif src.get('run_source_match')=='DRIFT' and not args.fresh:
                status='SOURCE_DRIFT';detail='Retrieval differs from prior run. Reconcile profile and stage new source before --fresh.'
            else:
                staged=ROOT/'working'/'GENERAL_DOCUMENT'/project/f'{project}_GENERAL_DOC_CLEANER_WORKING.xlsx'
                existing_book=Path(str((read_json(run_dir/'run_manifest.json').get('workbook') or {}).get('path') or '')) if run_dir else staged
                working_book=staged if args.fresh else existing_book
                if not working_book.is_file():status='MISSING_WORKING_COPY';detail=str(working_book)
                elif not args.fresh and (read_json(run_dir/'run_manifest.json').get('workbook') or {}).get('sha256_at_run_start') and hash_file(working_book)!=(read_json(run_dir/'run_manifest.json').get('workbook') or {}).get('sha256_at_run_start'):
                    status='WORKBOOK_DRIFT';detail='Working workbook differs from run-start SHA256; requires source/overlay review'
                elif args.fresh and (src.get('source_sha256')!=hash_file(working_book)):
                    status='REVIEW_REQUIRED';detail='Fresh run requires matching source and working copy; never silently overwrite working copy'
                else:
                    print(f'[RUN] {project}: '+('new full run' if args.fresh else f'replay {run_id}'),flush=True)
                    old_run_dirs={p.name for p in (ROOT/'runs').glob(project.lower()+'_*')} if args.fresh else set()
                    if not args.fresh and run_dir:
                        n_archived=snapshot_previous_outputs(run_dir,out/'before_replay'/project)
                        print(f'   [ARCHIVE] {n_archived} existing run artifacts preserved',flush=True)
                    cmd=runner_for(project,run_id,args.status_date,args.fresh,not args.non_interactive,working_book)
                    logfile=out/f'{project}_pipeline.txt'
                    if args.non_interactive:
                        p=subprocess.run(cmd,cwd=ROOT,env=env,capture_output=True,text=True,errors='replace')
                        logfile.write_text((p.stdout or '')+'\n'+(p.stderr or ''),encoding='utf-8')
                        print('   ',(p.stdout or p.stderr or '').strip().splitlines()[-1] if p.stdout or p.stderr else f'exit={p.returncode}',flush=True)
                    else:
                        with logfile.open('w',encoding='utf-8') as lg:
                            # Parent prompts remain visible and interactive; transcript from generated output should be preserved by Cleaner run logs.
                            p=subprocess.run(cmd,cwd=ROOT,env=env)
                            lg.write('Interactive execution: see run-local review and state artifacts; returncode='+str(p.returncode)+'\n')
                    if args.fresh:
                        fresh_candidates=[]
                        for candidate in (ROOT/'runs').glob(project.lower()+'_*'):
                            if candidate.is_dir() and candidate.name not in old_run_dirs and (candidate/'run_manifest.json').is_file():
                                fresh_candidates.append(candidate)
                        if len(fresh_candidates)==1:
                            active_run=fresh_candidates[0];active_id=active_run.name
                        elif len(fresh_candidates)>1:
                            active_run=sorted(fresh_candidates)[-1];active_id=active_run.name
                        else:
                            active_run=None;active_id=''
                    progress=read_json(active_run/'general_doc_auto_progress.json') if active_run else {}
                    status=('COMPLETE' if p.returncode==0 else 'REVIEW_REQUIRED' if p.returncode==2 else 'RUN_ERROR')
                    detail=str(progress.get('status') or '')+ (' | '+str(progress.get('error')) if progress.get('error') else '')
        elif run_dir is None:status='MISSING_RUN';detail='No Cleaner run found'
        if args.run and status=='COMPLETE' and not src.get('current_network_verified'):
            status='COMPLETE_PROVISIONAL_OFFLINE'
            detail=(detail+' | ' if detail else '')+'Current W: source not verified at audit time'
        if status not in ('COMPLETE','CHECKED'):blocked=True
        row=summary_row(project,active_id,active_run,src,status,detail)
        if args.run and row.get('unretrieved_slots') not in ('',None,0,'0'):
            row['execution']='COVERAGE_INCOMPLETE';blocked=True
        summaries.append(row)
        if active_run:
            try:exceptions.extend(parse_exception_rows(project,active_id,active_run,src))
            except Exception as exc:
                exceptions.append(register_row(project,active_id,src,stage='PORTFOLIO',exception_state='AUDIT_ERROR',severity='HIGH',
                  issue_type='EXCEPTION_PARSE_ERROR',detail=repr(exc),action_for_team='Ask Cleaner owner to inspect source JSON',owner_role='Cleaner owner'))
        if src.get('run_source_match')=='DRIFT' or src.get('source_proof') in ('UNAVAILABLE','RETRIEVAL_ERROR'):
            exceptions.append(register_row(project,active_id,src,stage='RETRIEVAL',exception_state='SOURCE_REVIEW',severity='HIGH',
                issue_type='SOURCE_PROVENANCE',detail=src.get('notes','')+f"; SHA256={src.get('source_sha256') or ''}",
                action_for_team='Verify canonical W: source, obtain approval and compare hashes before publishing',owner_role='Document Control'))
        elif not src.get('current_network_verified'):
            exceptions.append(register_row(project,active_id,src,stage='RETRIEVAL',exception_state='SOURCE_FRESHNESS_UNVERIFIED',severity='MEDIUM',
                issue_type='OFFLINE_RETRIEVAL',detail=src.get('notes',''),
                action_for_team='Connect W: and verify current network source; local run is not fresh-source certified',owner_role='Document Control'))
    sf=tuple(summaries[0]) if summaries else ('project',)
    csv_save(out/'portfolio_summary.csv',summaries,sf)
    csv_save(out/'source_inventory.csv',source_rows,tuple(dict.fromkeys(k for x in source_rows for k in x)))
    csv_save(out/'exception_register.csv',exceptions,EXPORT_FIELDS)
    write_guide_index(out,summaries,exceptions,out.name,args.status_date)
    for guide_name in ('GENERAL_DOCUMENT_PROJECT_TEAM_GUIDE.md','راهنمای_ثبت_و_کنترل_مدارک_مهندسی.md'):
        guide=ROOT/guide_name
        if guide.is_file():shutil.copy2(guide,out/guide.name)
    payload={'schema':'general_document.portfolio_audit/0.1','created_at':datetime.now(timezone.utc).isoformat(),
       'status_date':args.status_date,'mode':'check' if args.check else 'fresh' if args.fresh else 'replay',
       'repo_root':str(ROOT),'portfolio_out':str(out),'projects':summaries,'exception_count':len(exceptions),
       'exception_states':dict(Counter(x['exception_state'] for x in exceptions)),
       'network_verified_projects':sum(bool(x.get('current_network_verified')) for x in source_rows),
       'business_signoff':False,'note':'Latest version of local Cleaner code used; no unverified remote files are declared current.'}
    (out/'portfolio_audit.json').write_text(json.dumps(payload,indent=2,ensure_ascii=False,default=str)+'\n',encoding='utf-8')
    print(f'[EXPORT] {out / "exception_register.csv"} ({len(exceptions)} cases)',flush=True)
    print(f'[EXPORT] {out / "portfolio_summary.csv"} ({len(summaries)} projects)',flush=True)
    print(f'[SOURCE] {payload["network_verified_projects"]}/{len(source_rows)} verified directly from recorded W: source',flush=True)
    print('[DONE] Portfolio test outputs written; business approval is separate.',flush=True)
    return 2 if blocked else 0

if __name__=='__main__':
    try:raise SystemExit(main())
    except KeyboardInterrupt:raise SystemExit(2)
