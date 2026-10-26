from __future__ import annotations
import hashlib
import importlib.util
import json
import re
import shutil
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def save(path, data):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str)+'\n', encoding='utf-8')
    temp.replace(path)

def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''): h.update(b)
    return h.hexdigest()

def import_path(name,path):
    import sys
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module
    spec.loader.exec_module(module)
    return module

def retry(fn):
    # Only transient Excel busy/rejected-call errors are retryable.
    for attempt in range(6):
        try: return fn()
        except Exception as exc:
            code=getattr(exc,'hresult',None)
            if code is None and exc.args: code=exc.args[0]
            if code not in (-2147418111,-2147417846) or attempt==5: raise
            try:
                import pythoncom
                pythoncom.PumpWaitingMessages()
            except ImportError: pass
            time.sleep(0.15*(attempt+1))

class ExcelOwner:
    """Own exactly one private Excel application; never attach to user sessions."""
    def __init__(self, visible=False, factory=None):
        self.app=None; self.books=[]; self.initialized=False
        if factory is None:
            import pythoncom
            import win32com.client
            pythoncom.CoInitialize(); self.initialized=True
            factory=lambda:win32com.client.DispatchEx('Excel.Application')
        try:
            self.app=retry(factory)
            # Visibility is cosmetic and cannot abort the work.
            try: retry(lambda:setattr(self.app,'Visible',visible))
            except Exception: pass
            try: self.app.DisplayAlerts=False
            except Exception: pass
            try: self.app.AutomationSecurity=3
            except Exception: pass
        except BaseException:
            self.close();raise
    def open(self,path,readonly=False):
        book=retry(lambda:self.app.Workbooks.Open(str(Path(path).resolve()),UpdateLinks=0,ReadOnly=readonly))
        self.books.append(book);return book
    def close(self):
        errors=[]
        for book in reversed(self.books):
            try: retry(lambda:book.Close(SaveChanges=False))
            except Exception as exc: errors.append(str(exc))
        self.books=[]
        if self.app is not None:
            try: retry(self.app.Quit)
            except Exception as exc: errors.append(str(exc))
            self.app=None
        if self.initialized:
            import pythoncom
            pythoncom.CoUninitialize();self.initialized=False
        if errors: print('[EXCEL CLEANUP] '+ '; '.join(errors))

OWNERS=[]

def cleanup():
    while OWNERS: OWNERS.pop().close()

def verify_changes(book,changes,executor,execution=None):
    checks=[]
    resolved={(x['sheet'],x['target'],x['kind']):x.get('resolved_anchor')
              for x in ((execution or {}).get('applied',[])+(execution or {}).get('already_applied',[]))}
    for c in changes:
        ws=book.Worksheets(c.sheet); rng=ws.Range(c.target)
        if c.kind=='UNMERGE_RANGE':
            valid=all(not bool(cell.MergeCells) for cell in executor._physical_anchors(rng))
        elif c.kind=='MERGE_RANGE':
            valid=bool(rng.MergeCells)
        else:
            address=resolved.get((c.sheet,c.target,c.kind))
            anchor=ws.Range(address) if address else executor._resolve_value_anchor(rng,c)
            wanted=None if c.kind=='CLEAR_CELL' else c.value
            valid=executor._normalized(anchor.Value2)==executor._normalized(wanted)
        checks.append(dict(sheet=c.sheet,target=c.target,kind=c.kind,passed=valid))
        if not valid: raise RuntimeError(f'Physical correction verification failed: {c.sheet}!{c.target}')
    return checks

def plan_signature(plan):
    return hashlib.sha256(json.dumps([x.to_dict() for x in plan],sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()

def materialize(run_dir):
    from functions.cleaner.service import finalize_run
    from functions.cleaner import executor
    run=finalize_run(run_dir)
    plan=executor.build_change_plan(run.state())
    source=Path(run.workbook['path']).resolve()
    target=run.run_dir/'working'/'GENERAL_DOC_CLEANED_WORKING.xlsx'
    marker=run.run_dir/'working_copy_execution.json'
    signature=plan_signature(plan);source_hash=digest(source)
    if marker.exists():
        old=load(marker)
        if (old.get('source_sha256')==source_hash and old.get('plan_sha256')==signature
            and old.get('links_version')==1 and target.is_file() and digest(target)==old.get('cleaned_sha256')):
            return target
    target.parent.mkdir(parents=True,exist_ok=True)
    temp=target.with_name('GENERAL_DOC_CLEANED_PENDING.xlsx')
    shutil.copyfile(source,temp)
    owner=None
    try:
        if plan:
            owner=ExcelOwner();book=owner.open(temp)
            execution=retry(lambda:executor.apply_change_plan_com(book,plan))
            checks=retry(lambda:verify_changes(book,plan,executor,execution))
            retry(book.Save)
            owner.close();owner=None
            # Reopen saved bytes read-only to establish persistence, not just COM memory.
            owner=ExcelOwner();book=owner.open(temp,readonly=True)
            retry(lambda:verify_changes(book,plan,executor,execution))
            owner.close();owner=None
        else:
            execution={'planned':0,'applied_count':0,'already_applied_count':0}; checks=[]
        from .links import original_source, rewrite_links
        from zipfile import is_zipfile
        origin=original_source(source,ROOT,getattr(run,'profile_name',''))
        links=None
        if not origin and is_zipfile(temp):
            print('[LINKS REVIEW] Original network location not found in retrieval manifest; link conversion not performed')
        if origin and is_zipfile(temp):
            links=rewrite_links(temp,origin)
            Path(str(temp)+'.links.json').unlink(missing_ok=True)
        temp.replace(target)
        save(marker,dict(schema='cleaner.working_execution/0.7',source=str(source),source_sha256=source_hash,
            cleaned_workbook=str(target.resolve()),cleaned_sha256=digest(target),plan_sha256=signature,
            execution=execution,verification=checks,status='VERIFIED',links_version=1,
            absolute_links=links,link_origin_status='RESOLVED' if origin else 'NO_MATCHING_RETRIEVAL_MANIFEST'))
        print(f'[WORKING COPY] {target} | verified corrections={len(plan)}')
        return target
    finally:
        if owner: owner.close()
        temp.unlink(missing_ok=True)

def install_executor():
    from functions.cleaner import executor
    def create(run,*,output_path=None,overwrite=False):
        source=materialize(run.run_dir)
        destination=Path(output_path or executor.default_published_path(run)).resolve()
        if destination==source: raise RuntimeError('Audit output must differ from corrected working copy')
        if destination.exists() and not overwrite: raise FileExistsError(destination)
        destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,destination)
        owner=ExcelOwner();OWNERS.append(owner)
        try:
            book=owner.open(destination)
            info=load(run.run_dir/'working_copy_execution.json')
            class AuditBook:
                def __getattr__(self,name): return getattr(book,name)
                def Close(self,**kwargs):
                    retry(lambda:book.Close(**kwargs))
                    owner.books=[b for b in owner.books if b is not book]
            return owner.app,AuditBook(),destination,dict(info['execution'],working_copy=str(source),working_sha256=info['cleaned_sha256'])
        except BaseException:
            owner.close();raise
    executor.create_cleaned_copy_com=create

def start_row(record):
    # A merged date is anchored at its first row. Reference/status cells do not
    # create a later event merely because they occupy lower rows in that block.
    if record.source_row is not None: return int(record.source_row)
    m=re.match(r'\$?[A-Za-z]+\$?(\d+)',str(record.date_source or ''))
    return int(m.group(1)) if m else None

def sequence_key(record):
    row=start_row(record)
    if row is None or record.block_index is None:
        raise ValueError('Missing revision/row geometry; chronology needs review')
    return int(record.block_index),row,0 if record.send_or_receive=='send' else 1

def _wbs_token(value):
    if value is None: return None
    text=str(value).strip()
    return text if text and text.casefold() not in {'none','null','nan','-','n/a','na'} else None

def install_ordering():
    from functions.engineering_control import three_lists as t
    original=t.build_three_engineering_lists
    t._sequence_key=sequence_key
    def build(records,*args,**kwargs):
        from dataclasses import replace
        records=list(records); groups={}; issues=[]; evidence=[]; bad=set()
        for r in records: groups.setdefault((r.source_sheet,int(r.document_index)),[]).append(r)
        inventory=list(kwargs.get('document_inventory') or [])
        inventory_map={(str(x.get('source_sheet')),int(x.get('document_index'))):x for x in inventory}
        for key in sorted(set(groups)|set(inventory_map)):
            items=groups.get(key,[]); item=inventory_map.get(key) or {}
            values={token for token in (_wbs_token(x.doc_wbs) for x in items) if token}
            inventory_wbs=_wbs_token(item.get('doc_wbs'))
            if inventory_wbs: values.add(inventory_wbs)
            if not values:
                bad.add(key);issues.append(dict(kind='DOCUMENT_WBS_REQUIRED',source_sheet=key[0],document_index=key[1],message='Every document must have exactly one assigned WBS; this document has none.'))
            elif len(values)>1:
                bad.add(key);issues.append(dict(kind='DOCUMENT_WBS_CONFLICT',source_sheet=key[0],document_index=key[1],wbs_values=sorted(values),message='Every document must have exactly one assigned WBS; conflicting values were found.'))
        for key,items in groups.items():
            try: ordered=sorted(items,key=sequence_key)
            except ValueError as exc:
                bad.add(key);issues.append(dict(kind='CHRONOLOGY_GEOMETRY_MISSING',source_sheet=key[0],document_index=key[1],message=str(exc)));continue
            # SEND and RECEIVE dates are separate vertical lanes in General
            # Document cards. A later-position SEND may predate an earlier
            # RECEIVE when submissions overlap; compare chronology within each
            # lane, then compare a SEND/RECEIVE pair only when they share a row.
            for side in ('send','receive'):
                last_dated=None
                for r in (x for x in ordered if x.send_or_receive==side):
                    if t._jalali_parts(r.letter_date):
                        if last_dated is not None and t.jalali_day_difference(r.letter_date,last_dated.letter_date)<0:
                            bad.add(key);issues.append(dict(kind='CHRONOLOGY_DATE_POSITION_CONFLICT',source_sheet=key[0],document_index=key[1],message=f'{side.title()} dates contradict their own board order; review before assigning delay responsibility'))
                        last_dated=r
            paired={}
            for r in ordered:
                row_key=(int(r.block_index),start_row(r))
                paired.setdefault(row_key,{}).setdefault(r.send_or_receive,[]).append(r)
            has_aligned_lanes=any(row_events.get('send') and row_events.get('receive') for row_events in paired.values())
            for row_events in paired.values():
                sends=[x for x in row_events.get('send',[]) if t._jalali_parts(x.letter_date)]
                receives=[x for x in row_events.get('receive',[]) if t._jalali_parts(x.letter_date)]
                if sends and receives and t.jalali_day_difference(receives[0].letter_date,sends[0].letter_date)<0:
                    bad.add(key);issues.append(dict(kind='CHRONOLOGY_DATE_POSITION_CONFLICT',source_sheet=key[0],document_index=key[1],message='A same-row RECEIVE date is earlier than its SEND date; review the paired transaction'))
            if not has_aligned_lanes:
                last_dated=None
                for r in ordered:
                    if t._jalali_parts(r.letter_date):
                        if last_dated is not None and t.jalali_day_difference(r.letter_date,last_dated.letter_date)<0:
                            bad.add(key);issues.append(dict(kind='CHRONOLOGY_DATE_POSITION_CONFLICT',source_sheet=key[0],document_index=key[1],message='Dates contradict revision/row order; review before assigning delay responsibility'))
                        last_dated=r
            seen=set()
            for r in ordered:
                k=sequence_key(r)
                if k in seen:
                    bad.add(key);issues.append(dict(kind='CHRONOLOGY_POSITION_TIE',source_sheet=key[0],document_index=key[1],message='Multiple same-side events share revision/row position'))
                seen.add(k)
            evidence.append(dict(source_sheet=key[0],document_index=key[1],events=[dict(side=r.send_or_receive,revision=r.doc_rev,block=r.block_index,row=start_row(r),date=r.letter_date,reference=r.letter_reference,date_source=r.date_source) for r in ordered]))
        # Keep ambiguous documents out of responsibility lists and explicitly in diagnostics.
        valid=[r for r in records if (r.source_sheet,int(r.document_index)) not in bad]
        if 'document_inventory' in kwargs:
            kwargs['document_inventory']=[r for r in inventory if (r['source_sheet'],int(r['document_index'])) not in bad]
        # Normalize the separate side counters for existing downstream functions
        # that independently sort by event_index rather than calling _sequence_key.
        index={id(r):i+1 for items in groups.values() if (items[0].source_sheet,int(items[0].document_index)) not in bad for i,r in enumerate(sorted(items,key=sequence_key))}
        valid=[replace(r,event_index=index[id(r)]) for r in valid]
        result=original(valid,*args,**kwargs)
        # Same-day direction is not a data error; preserve the underlying dates
        # and computed list rows, and remove only this review diagnostic.
        result.diagnostics[:]=[d for d in result.diagnostics if
            str(d.get('reason') or d.get('code') or d.get('kind') or '')!='SAME_DAY_DIRECTION_ORDER_UNVERIFIED']
        for issue in issues:
            items=groups.get((issue['source_sheet'],issue['document_index']),[])
            if items:
                issue.update(doc_name=items[0].doc_name,doc_wbs=items[0].doc_wbs)
        result.diagnostics.extend(issues)
        for rid in {r.source_run_id for r in records}:
            if re.fullmatch(r'[A-Za-z0-9_-]+',rid or ''):
                save(ROOT/'runs'/rid/'chronology_v07.json',dict(order='revision block, physical event row, send before receive on same row',documents=evidence,diagnostics=issues))
        return result
    t.build_three_engineering_lists=build
    import functions.engineering_control as exports
    exports.build_three_engineering_lists=build

def install_live_excel():
    import cleaner_core
    import cleaner_core.live_excel as live
    opened={}
    def ensure(path,*,visible=True):
        key=str(Path(path).resolve()).casefold()
        if key not in opened:
            owner=ExcelOwner(visible=visible);OWNERS.append(owner)
            opened[key]=owner.open(path,readonly=True)
        return opened[key]
    def attach(name=None):
        if name:
            key=str(Path(name).resolve()).casefold()
            if key in opened: return opened[key]
            for path,book in opened.items():
                if Path(path).name.casefold()==str(name).casefold(): return book
            if Path(name).is_file(): return ensure(name)
        if len(opened)==1: return next(iter(opened.values()))
        raise live.ExcelConnectionError('No pipeline-owned workbook matches requested source')
    old_snapshot=live.snapshot_live_workbook
    def snapshot(*a,**k): return retry(lambda:old_snapshot(*a,**k))
    for target in (live,cleaner_core):
        target.ensure_excel_workbook_open=ensure
        target.attach_excel_workbook=attach
        target.snapshot_live_workbook=snapshot

def auto_known(queue_path,decisions_path):
    r=import_path('_v07_reviewer',ROOT/'dev'/'review_findings.py')
    queue=load(queue_path)
    count=r.accept_known_resolutions(queue,reviewer='V07 approved memory')
    from cleaner_core.field_schema import normalize_embedded_jalali_text
    for item in queue.get('items',[]):
        if item.get('review_state')!='PENDING': continue
        ev=item.get('evidence') or {}
        if (item.get('source') or {}).get('test_id')!='FIELD_VALIDATION': continue
        if ev.get('audit_kind')!='EXPLANATION_DATE' or ev.get('field_role')!='explanation': continue
        raw=item.get('observed')
        if not isinstance(raw,str): continue
        normalized,dates,invalid=normalize_embedded_jalali_text(raw)
        suggestion=(item.get('machine_suggestion') or {}).get('suggested_fix') or {}
        params=suggestion.get('parameters') or {}
        loc=item.get('location') or {}
        if (invalid or not dates or normalized==raw or suggestion.get('action')!='SET_VALUE'
            or params.get('value')!=normalized or params.get('sheet')!=loc.get('sheet')
            or params.get('target')!=loc.get('target')): continue
        params=dict(params,expected_old_value=raw)
        decision=r.make_decision('SET_VALUE',parameters=params,reason='V07 approved explanation-date normalization; calendar and source guard checked',reviewer='V07 approved rule')
        decision['origin']='V07_EXPLANATION_DATE_RULE'
        r.apply_decision_to_queue(queue,item['review_id'],decision);count+=1
    r.update_summary(queue);save(queue_path,queue)
    written=r.write_decisions_file(queue,decisions_path)
    project=str((queue.get('profile') or {}).get('profile_name') or '')
    if not re.fullmatch('[A-Za-z0-9_]+',project): raise ValueError('Queue has no valid project identity')
    path=ROOT/'project_solutions'/f'{project}.solutions.json'
    solutions=r.load_project_solutions(path,project_id=project,create=True)
    r.sync_project_solutions_from_decisions_file(solutions,written)
    r.save_project_solutions(solutions,path)
    print(f'[MEMORY] Reused/normalized={count}; pending={queue["summary"]["pending_review"]}')
    return queue
