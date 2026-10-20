#!/usr/bin/env python3
"""Read-only GENERAL_DOCUMENT card morphology discovery and visual exception gallery.

Run in cleaner-functions root, with standard-library Python 3.10+:
  py .\\CARD_MORPHOLOGY_GALLERY_V01.py
  py .\\CARD_MORPHOLOGY_GALLERY_V01.py --examples-per-type 3

No workbook or run artifacts are edited; this is an observation, not approval.
"""
from __future__ import annotations
import argparse, csv, html, json, re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECTS=('AZD','JND','FSH','YSK','EYV','BFG','NKH','NGN')
RUN_IDS={'AZD':'azd_20261014T071802','JND':'jnd_20261007T022038',
         'FSH':'fsh_20261007T024351','YSK':'ysk_20261016T212108',
         'EYV':'eyv_20261017T020820','BFG':'bfg_20261017T130419',
         'NKH':'nkh_20261017T053117','NGN':'ngn_20261017T143536'}
CAT_FIELDS=['project','run_id','sheet','document_index','document','wbs','revision','card_range',
            'morphology','send_count','receive_count','status_count','source_date_count','flags',
            'send_sources','receive_sources','status_sources','suggested_action','case_id']
QUEUE_FIELDS=CAT_FIELDS+['review_state','reason','evidence_board_issue']
BOARD_FIELDS=['project','run_id','kind','sheet','document_index','revision','address','source_value','message']
EVENT_FIELDS=['project','run_id','sheet','document_index','document','wbs','revision','direction',
              'letter_date','letter_reference','doc_status','date_source','reference_source','status_source',
              'source_row','source_col','source_cell_order_rank','date_order_rank','original_log_sequence']
MEETING_RE=re.compile(r'(?:صورت\s*جلسه|صورتجلسه|جلسه|meeting\s*minutes)',re.IGNORECASE)
CELL_RE=re.compile(r'\$?([A-Z]{1,3})\$?(\d+)', re.I)


def read(path:Path)->dict:
    try:
        value=json.loads(path.read_text(encoding='utf-8-sig'))
        return value if isinstance(value,dict) else {}
    except (OSError,ValueError): return {}


def csv_write(path:Path,rows:list[dict],fields:list[str])->None:
    with path.open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');writer.writeheader();writer.writerows(rows)


def esc(v:Any)->str:
    return html.escape('' if v is None else str(v),quote=True)


def cell_col(address:Any)->int|None:
    m=CELL_RE.search(str(address or ''))
    if not m:return None
    col=0
    for c in m.group(1).upper():col=col*26+ord(c)-64
    return col


def cell_row(address:Any)->int|None:
    m=CELL_RE.search(str(address or ''))
    return int(m.group(2)) if m else None


def col_label(n:int)->str:
    a=''
    while n:n,v=divmod(n-1,26);a=chr(65+v)+a
    return a


def source_text(rec:dict)->str:
    return str(rec.get('letter_reference') or '')


def is_narrative_reference(value:Any)->bool:
    s=str(value or '').strip()
    if not s or MEETING_RE.search(s):return False
    if (' ' not in s and len(s)<42) or (re.fullmatch(r'[\d\s/\-.A-Za-z]+',s) and len(s)<48):return False
    return len(s)>48 or (len(s.split())>3) or bool(re.search(r'[\u0600-\u06ff]',s))


def case_morphology(send:int,receive:int)->str:
    if send==1 and receive==1:return 'STANDARD_PAIR'
    if send==0 and receive==0:return 'NO_DATED_EVENTS'
    if send==1 and receive==0:return 'SEND_ONLY'
    if send==0 and receive>=1:return 'RECEIVE_WITHOUT_SEND'
    if send>1 and receive==0:return 'MULTIPLE_SEND_ONLY'
    if send>1 and receive==1:return 'MULTIPLE_SEND_ONE_RECEIVE'
    if send==1 and receive>1:return 'ONE_SEND_MULTIPLE_RECEIVE'
    return 'MULTIPLE_SEND_MULTIPLE_RECEIVE'


def action_for(flags:set[str],morph:str)->str:
    if 'SOURCE_SLOT_ISSUE' in flags:return 'Investigate flagged source slot and original correspondence; correct only with evidence.'
    if 'POSSIBLE_NARRATIVE_REFERENCE' in flags:return 'Check text in reference lane; classify note or obtain correct letter reference. Preserve original text.'
    if 'MISSING_DATE' in flags:return 'Locate event date in original correspondence; leave undated until verified.'
    if 'RECEIVE_STATUS_MISSING' in flags:return 'Confirm whether an official consultant response status is required and available.'
    if morph=='RECEIVE_WITHOUT_SEND':return 'Check whether submission was logged elsewhere or omitted from this revision.'
    if morph.startswith('MULTIPLE') or morph=='ONE_SEND_MULTIPLE_RECEIVE':return 'Confirm all interactions belong to this revision; do not force one-to-one send/receive pairing.'
    if morph=='NO_DATED_EVENTS':return 'Confirm whether this revision is unused or correspondence data is missing.'
    return 'Observe; no structural correction inferred from the event counts alone.'


def needs_investigation(flags:set[str],morph:str,card:dict)->bool:
    urgent={'SOURCE_SLOT_ISSUE','POSSIBLE_NARRATIVE_REFERENCE','MISSING_DATE',
            'MISSING_REFERENCE','RECEIVE_STATUS_MISSING'}
    if flags.intersection(urgent) or morph=='RECEIVE_WITHOUT_SEND':return True
    # A zero-event card with actual nonempty correspondence slots might signal
    # extraction loss; a completely empty card is normal and not an exception.
    if morph=='NO_DATED_EVENTS':
        return any(slot.get('value') is not None and str(slot.get('value')).strip()
                   for slot in (card.get('slots') or []))
    return False


def interesting(flags:set[str],morph:str)->bool:
    return bool(flags) or morph not in {'STANDARD_PAIR','SEND_ONLY'}


def card_grid(card:dict,records:list[dict],revision:str,block_width:int=3)->str:
    """Source-card visualization from recorded cell values; NOT an Excel screenshot."""
    if not card:return '<p class="muted">Card range not available in the run artifacts.</p>'
    start=int(card.get('start_row') or card.get('anchor_row') or 1)
    end=int(card.get('end_row') or start)
    # Keep large ranges short; source ranges are reported in full above.
    if end-start>9:end=start+9
    all_cols=[]
    for rec in records:
        for field in ('date_source','reference_source','status_source'):
            col=cell_col(rec.get(field))
            if col:all_cols.append(col)
    if all_cols:
        lo=max(int(card.get('data_start_col') or 4),min(all_cols)-1)
        hi=max(all_cols)+1
        hi=min(int(card.get('data_end_col') or hi),hi)
        lo=min(lo,hi)
    else:
        lo=int(card.get('data_start_col') or 4)
        hi=min(int(card.get('data_end_col') or lo+2),lo+max(2,block_width-1))
    if hi-lo>=12: hi=lo+11
    # Preserve anchor-only content by indexing recorded slots across merged ranges.
    slots=card.get('slots') or []
    anchors={}
    for slot in slots:
        a=str(slot.get('address') or '')
        row=cell_row(a);col=cell_col(a)
        if row is not None and col is not None:
            value=slot.get('value')
            if value is not None:anchors[(row,col)]=str(value)
    # Recent logical overlays may not be present in card-map snapshots. Show recorded transaction values too.
    for rec in records:
        for f,key in (('date_source','letter_date'),('reference_source','letter_reference'),('status_source','doc_status')):
            addr=rec.get(f);row=cell_row(addr);col=cell_col(addr)
            if row is not None and col is not None and rec.get(key) is not None:
                anchors[(row,col)]=str(rec[key])
    out=['<div class="grid-scroll"><table class="cell-grid"><thead><tr><th>Row</th>']
    for c in range(lo,hi+1):out.append('<th>'+col_label(c)+'</th>')
    out.append('</tr></thead><tbody>')
    for row in range(start,end+1):
        out.append('<tr><th>'+str(row)+'</th>')
        for col in range(lo,hi+1):
            value=anchors.get((row,col),'')
            out.append('<td title="'+col_label(col)+str(row)+'">'+esc(value)+'</td>')
        out.append('</tr>')
    out.append('</tbody></table></div>')
    return ''.join(out)


def build_records(project:str,run_id:str,run_dir:Path)->tuple[list[dict],list[dict],dict]:
    if not (run_dir/'board_to_log.json').is_file() or not (run_dir/'card_maps.json').is_file():
        absent=[x for x in ('board_to_log.json','card_maps.json') if not (run_dir/x).is_file()]
        return [],[],{'project':project,'run_id':run_id,'status':'MISSING_ARTIFACTS: '+', '.join(absent),'items':0}
    board=read(run_dir/'board_to_log.json');maps=read(run_dir/'card_maps.json');slot=read(run_dir/'slot_schema.json')
    if not isinstance(board.get('records'),list) or not maps.get('sheets'):
        return [],[],{'project':project,'run_id':run_id,'status':'UNREADABLE_ARTIFACTS','items':0}
    doc_records=defaultdict(list);rev_records=defaultdict(list);doc_cards={}
    for sheet,sh in (maps.get('sheets') or {}).items():
        for card in (sh.get('cards') or []):
            doc_cards[(sheet,str(card.get('record_index')))] = card
    for rec in (board.get('records') or []):
        if not isinstance(rec,dict):continue
        doc=(str(rec.get('source_sheet') or ''),str(rec.get('document_index') or ''))
        rev=str(rec.get('doc_rev') if rec.get('doc_rev') is not None else '?')
        doc_records[doc].append(rec);rev_records[(doc[0],doc[1],rev)].append(rec)
    issues=defaultdict(list)
    for issue in (board.get('issues') or []):
        if not isinstance(issue,dict):continue
        sheet=str(issue.get('sheet') or issue.get('source_sheet') or '')
        index=str(issue.get('document_index') or '')
        rev=str(issue.get('revision') or (issue.get('evidence') or {}).get('revision') or '')
        issues[(sheet,index,rev)].append(issue)
    keys=set(rev_records)
    for sheet,index,rev in issues:
        if sheet and index and rev and (sheet,index) in doc_cards:
            keys.add((sheet,index,rev))
    # Include card-only documents, even when there is no usable event to extract.
    for doc in doc_cards:
        if doc not in doc_records: keys.add((doc[0],doc[1],'?'))
    rows=[];gallery=[]
    for sheet,index,rev in sorted(keys,key=lambda x:(x[0],int(x[1]) if x[1].isdigit() else 999999,x[2])):
        recs=rev_records.get((sheet,index,rev),[])
        docrecs=doc_records.get((sheet,index),[])
        send=[r for r in recs if str(r.get('send_or_receive') or '').lower()=='send']
        receive=[r for r in recs if str(r.get('send_or_receive') or '').lower()=='receive']
        if not recs and docrecs and not issues.get((sheet,index,rev)):continue
        card=doc_cards.get((sheet,index),{})
        first=(recs or docrecs or [{}])[0]
        count_send=len(send);count_receive=len(receive)
        morphology=case_morphology(count_send,count_receive)
        related=list(issues.get((sheet,index,rev),[])) + list(issues.get((sheet,index,''),[]))
        flags=set()
        if related:flags.add('SOURCE_SLOT_ISSUE')
        if any(not r.get('letter_date') for r in recs):flags.add('MISSING_DATE')
        if any(not r.get('letter_reference') for r in recs):flags.add('MISSING_REFERENCE')
        if any(not r.get('doc_status') for r in receive):flags.add('RECEIVE_STATUS_MISSING')
        if any(is_narrative_reference(r.get('letter_reference')) for r in recs):flags.add('POSSIBLE_NARRATIVE_REFERENCE')
        if any(MEETING_RE.search(source_text(r)) for r in recs):flags.add('MEETING_REFERENCE')
        if int(card.get('end_row') or card.get('start_row') or 0)-int(card.get('start_row') or 0)>=3:flags.add('TALL_CARD')
        if any(':' in str(r.get('status_source') or '') for r in receive):flags.add('MERGED_STATUS')
        if count_send>1 or count_receive>1:flags.add('REPEATED_INTERACTIONS')
        issue_text='; '.join(str(x.get('kind') or '')+': '+str(x.get('address') or '') for x in related)
        source_list=lambda arr: '; '.join(str(r.get('date_source') or '-')+' / '+str(r.get('reference_source') or '-') for r in arr)
        case_id=f'{project}-{re.sub(r"[^A-Za-z0-9]+","_",sheet)}-{index}-REV-{rev}'
        row={'project':project,'run_id':run_id,'sheet':sheet,'document_index':index,
             'document':str(first.get('doc_name') or ((first.get('document_fields') or {}).get('name')) or ''),
             'wbs':str(first.get('doc_wbs') or ''),'revision':rev,
             'card_range':str(card.get('data_range') or ''),'morphology':morphology,
             'send_count':count_send,'receive_count':count_receive,
             'status_count':sum(bool(r.get('doc_status')) for r in receive),
             'source_date_count':sum(bool(r.get('letter_date')) for r in recs),
             'flags':'; '.join(sorted(flags)),
             'send_sources':source_list(send),'receive_sources':source_list(receive),
             'status_sources':'; '.join(str(r.get('status_source') or '-') for r in receive),
             'suggested_action':action_for(flags,morphology),'case_id':case_id}
        rows.append(row)
        if interesting(flags,morphology):
            queue=dict(row,review_state='INVESTIGATE' if needs_investigation(flags,morphology,card) else 'OBSERVED_VARIATION',
                       reason=f'{morphology}; {row["flags"]}'.strip('; '),evidence_board_issue=issue_text)
            gallery.append((queue,card,recs,slot.get('sheets',{}).get(sheet,{})))
    return rows,gallery,{'project':project,'run_id':run_id,'status':'READ_ONLY_SCANNED','items':len(rows),
                          'original_board_issues':len(board.get('issues') or [])}


def gallery_html(selected:list[tuple[dict,dict,list[dict],dict]], project_states:list[dict],totals:Counter,
                 total_rows:int, total_flagged:int,missing:list[str])->str:
    css='''body{font:14px system-ui,Segoe UI,Tahoma,sans-serif;margin:30px auto;padding:0 20px;max-width:1300px;background:#f8fafc;color:#182338}
    .summary,.card{background:#fff;border:1px solid #dce4ed;border-radius:9px;padding:18px;margin:16px 0;box-shadow:0 1px 3px #dfe5ee}
    .card{break-inside:avoid}.tag{display:inline-block;background:#eef2fa;border-radius:4px;padding:4px 7px;margin:2px;font-size:12px}
    .flag{background:#fff1d4}small,.muted{color:#64748b}h1{font-size:26px}h2{font-size:18px}h3{font-size:15px}
    .details{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:6px}
    .grid-scroll{overflow:auto;max-height:480px}.cell-grid{border-collapse:collapse;min-width:420px;direction:ltr}
    .cell-grid td,.cell-grid th{border:1px solid #b5bfca;padding:5px 8px;min-width:90px;max-width:270px;overflow-wrap:anywhere;font:12px Tahoma,Segoe UI,sans-serif;vertical-align:top}
    .cell-grid th{background:#e8edf4;position:sticky;top:0}.cell-grid td{background:#fff}
    .events{width:100%;border-collapse:collapse;table-layout:fixed}.events td,.events th{border-bottom:1px solid #e5e9ee;padding:5px;text-align:left;overflow-wrap:anywhere}
    .events td:nth-child(3),.events td:nth-child(4){direction:auto}a{color:#2355a5}code{font:12px Consolas,monospace}
    @media print{body{margin:0;background:#fff}.card{page-break-inside:avoid}.grid-scroll{max-height:none}}'''
    out=['<!doctype html><html lang="en"><head><meta charset="utf-8"><title>General Document — Card Morphology Gallery</title><style>',css,'</style></head><body>']
    out+=['<h1>General Document — Card Morphology & Exception Gallery</h1>',
          '<p class="muted">Read-only snapshot of current run artifacts. Cell grids are reconstructed from captured Cleaner card slots and transactions, <strong>not pixel screenshots of Excel</strong>. Validate findings against the workbook before correcting. A SEND without a response is not automatically an error.</p>',
          '<div class="summary"><h2>Discovery overview</h2>',
          '<p><strong>'+str(total_rows)+'</strong> document/revision combinations · <strong>'+str(total_flagged)+'</strong> review candidates · <strong>'+str(len(selected))+'</strong> visual examples</p>',
          '<p>'+''.join('<span class="tag">'+esc(k)+' '+str(v)+'</span>' for k,v in totals.most_common())+'</p>',
          '<p>'+''.join('<span class="tag">'+esc(s['project'])+': '+esc(s['status'])+' ('+str(s['items'])+')</span>' for s in project_states)+'</p>']
    if missing:out.append('<p><strong>Missing:</strong> '+esc(', '.join(missing))+'</p>')
    out.append('</div>')
    for r,card,recs,schema in selected:
        out+=['<section class="card" id="'+esc(r['case_id'])+'"><h2>'+esc(r['project'])+' / '+esc(r['sheet'])+' — '+esc(r['document'] or '(unknown document)')+'</h2>',
              '<div class="details"><div><strong>WBS:</strong> '+esc(r['wbs'] or '(none)')+'</div>',
              '<div><strong>Revision:</strong> '+esc(r['revision'])+'</div><div><strong>Source:</strong> '+esc(r['sheet']+'!'+r['card_range'])+'</div>',
              '<div><strong>Case:</strong> <code>'+esc(r['case_id'])+'</code></div></div>',
              '<p><span class="tag">'+esc(r['morphology'])+'</span><span class="tag">'+str(r['send_count'])+' SEND / '+str(r['receive_count'])+' RECEIVE</span>']
        for flag in r['flags'].split('; '):
            if flag:out.append('<span class="tag flag">'+esc(flag)+'</span>')
        out.append('</p><h3>Source cell excerpt (recorded values)</h3>')
        if r.get('_image_rel'):
            out.append('<figure><img loading="lazy" alt="Native Excel range image" style="max-width:100%;max-height:540px;object-fit:contain;border:1px solid #cbd5e1" src="'+esc(r['_image_rel'])+'"><figcaption><small>Native Excel CopyPicture excerpt (read-only source).</small></figcaption></figure>')
        else:
            out.append(card_grid(card,recs,r['revision'],int(schema.get('block_width') or 3)))
        out.append('<h3>Extracted events — board order retained</h3><table class="events"><thead><tr><th>Direction</th><th>Date</th><th>Reference</th><th>Status</th><th>Source cells</th></tr></thead><tbody>')
        for rec in recs:
            out.append('<tr>'+''.join('<td>'+esc(x)+'</td>' for x in (rec.get('send_or_receive'),rec.get('letter_date'),rec.get('letter_reference'),rec.get('doc_status'),
                 ' / '.join(str(rec.get(k) or '-') for k in ('date_source','reference_source','status_source'))))+'</tr>')
        out.append('</tbody></table><p><strong>Suggested investigation:</strong> '+esc(r['suggested_action'])+'</p>')
        if r.get('evidence_board_issue'):out.append('<p><strong>Recorded extraction issues:</strong> '+esc(r['evidence_board_issue'])+'</p>')
        out.append('<p><small>Source: '+esc(r['run_id'])+' / card_maps.json + board_to_log.json; zero source edits.</small></p></section>')
    out.append('</body></html>')
    return ''.join(out)


def event_orders(repo:Path,projects:list[str])->list[dict]:
    out=[]
    for project in projects:
        run=repo/'runs'/RUN_IDS[project]
        board=read(run/'board_to_log.json')
        per_doc=defaultdict(list)
        for n,r in enumerate(board.get('records') or []):
            if not isinstance(r,dict):continue
            key=(str(r.get('source_sheet') or ''),str(r.get('document_index') or ''))
            per_doc[key].append((n,r))
        for (sheet,index),entries in per_doc.items():
            by_source=sorted(entries,key=lambda t:(int(t[1].get('source_row') or cell_row(t[1].get('date_source')) or 10**9),
                              int(t[1].get('source_col') or cell_col(t[1].get('date_source')) or 10**9), t[0]))
            source_ranks={n:i+1 for i,(n,_) in enumerate(by_source)}
            # This is only a date-field ordering. Chronology validation is Phase 2;
            # unknown/malformed Jalali values are not silently guessed or changed.
            valid_date=lambda d:bool(re.fullmatch(r'1[34]\d{2}/(?:0[1-9]|1[0-2])/(?:0[1-9]|[12]\d|3[01])',str(d or '')))
            dated=sorted(((n,r) for n,r in entries if valid_date(r.get('letter_date'))),
                         key=lambda t:(str(t[1].get('letter_date')),source_ranks[t[0]]))
            date_ranks={n:i+1 for i,(n,_) in enumerate(dated)}
            for n,r in entries:
                out.append({'project':project,'run_id':RUN_IDS[project],'sheet':sheet,'document_index':index,
                            'document':r.get('doc_name') or '','wbs':r.get('doc_wbs') or '',
                            'revision':r.get('doc_rev') if r.get('doc_rev') is not None else '?',
                            'direction':r.get('send_or_receive') or '',
                            'letter_date':r.get('letter_date') or '',
                            'letter_reference':r.get('letter_reference') or '',
                            'doc_status':r.get('doc_status') or '',
                            'date_source':r.get('date_source') or '',
                            'reference_source':r.get('reference_source') or '',
                            'status_source':r.get('status_source') or '',
                            'source_row':r.get('source_row') or '',
                            'source_col':r.get('source_col') or '',
                            'source_cell_order_rank':source_ranks[n],
                            'date_order_rank':date_ranks.get(n,''),
                            'original_log_sequence':n+1})
    return out


def capture_excel_images(repo:Path,out:Path,selected:list[tuple[dict,dict,list[dict],dict]],limit:int)->tuple[int,list[str]]:
    """Optional Windows Excel CopyPicture capture. Uses clipboard; never saves Excel file.

    This is opt-in as Excel COM may be busy and clipboard contents will change.
    Failures are reported and HTML cell visualizations remain available.
    """
    if limit<=0:return 0,[]
    try:
        import win32com.client
        from PIL import ImageGrab
    except (ImportError,OSError) as exc:return 0,[f'Native images unavailable (pywin32/Pillow): {exc}']
    folder=out/'excel_range_images';folder.mkdir(parents=True,exist_ok=True)
    warnings=[];count=0;excel=None
    try:
        excel=win32com.client.DispatchEx('Excel.Application')
        excel.Visible=False
        excel.DisplayAlerts=False
        excel.AskToUpdateLinks=False
        for project in PROJECTS:
            samples=[t for t in selected[:limit] if t[0]['project']==project and t[1].get('data_range')]
            if not samples or count>=limit:continue
            m=read(repo/'runs'/RUN_IDS[project]/'run_manifest.json')
            workbook_path=str((m.get('workbook') or {}).get('path') or '')
            if not workbook_path or not Path(workbook_path).is_file():
                warnings.append(f'{project}: working workbook unavailable for native range image')
                continue
            wb=None
            try:
                wb=excel.Workbooks.Open(workbook_path,0,True)
                for r,card,case_events,schema in samples:
                    if count>=limit:break
                    try:
                        ws=wb.Worksheets(r['sheet'])
                        # Limit image width to revision's actual event columns plus context.
                        cols=[]
                        for rec in case_events:
                            for field in ('date_source','reference_source','status_source'):
                                cellnum=cell_col(rec.get(field))
                                if cellnum:cols.append(cellnum)
                        r1=int(card.get('start_row') or card.get('anchor_row') or 1)
                        r2=min(int(card.get('end_row') or r1),r1+13)
                        c1=max(int(card.get('data_start_col') or 4),min(cols)-1) if cols else int(card.get('data_start_col') or 4)
                        c2=min(int(card.get('data_end_col') or c1+2),max(cols)+1) if cols else c1+2
                        c2=min(max(c1,c2),c1+9)
                        span=ws.Range(ws.Cells(r1,c1),ws.Cells(r2,c2))
                        span.CopyPicture(Appearance=1,Format=2)
                        photo=ImageGrab.grabclipboard()
                        if photo is None or not hasattr(photo,'save'):
                            raise RuntimeError('Excel did not place an image onto clipboard')
                        name=re.sub(r'[^a-zA-Z0-9_\-]+','_',r['case_id'])[:130]+'.png'
                        path=folder/name
                        photo.save(path,format='PNG')
                        r['_image_rel']='excel_range_images/'+name
                        count+=1
                    except Exception as exc:
                        warnings.append(f'{project}:{r["case_id"]}: {type(exc).__name__}: {exc}')
            except Exception as exc:
                warnings.append(f'{project}: Excel open failed: {exc}')
            finally:
                if wb is not None:
                    try:wb.Close(SaveChanges=False)
                    except Exception as exc:warnings.append(f'{project}: Excel read-only close: {exc}')
    except Exception as exc:
        warnings.append(f'Excel capture unavailable: {exc}')
    finally:
        if excel is not None:
            try:excel.Quit()
            except Exception:pass
    return count,warnings


def board_issue_inventory(repo:Path,projects:list[str])->list[dict]:
    rows=[]
    for project in projects:
        board=read(repo/'runs'/RUN_IDS[project]/'board_to_log.json')
        for issue in (board.get('issues') or []):
            if not isinstance(issue,dict):continue
            evidence=issue.get('evidence') or {}
            rows.append({'project':project,'run_id':RUN_IDS[project],
                         'kind':str(issue.get('kind') or ''),'sheet':str(issue.get('sheet') or ''),
                         'document_index':str(issue.get('document_index') or ''),
                         'revision':str(issue.get('revision') or evidence.get('revision') or ''),
                         'address':str(issue.get('address') or ''),'source_value':str(evidence.get('value') or ''),
                         'message':str(issue.get('message') or '')})
    return rows


def execute(repo:Path,out:Path,projects:list[str],examples:int,excel_images:int=0)->dict:
    if examples<1:raise ValueError('examples-per-type must be 1 or greater')
    rows=[];candidates=[];statuses=[];missing=[]
    for project in projects:
        run_id=RUN_IDS[project]
        run=repo/'runs'/run_id
        current,cases,state=build_records(project,run_id,run)
        statuses.append(state);rows.extend(current);candidates.extend(cases)
        if state['status']!='READ_ONLY_SCANNED':missing.append(project)
        print(f'[{"OK" if current else "MISSING"}] {project}: {len(current)} revision cards, {len(cases)} gallery candidates; {state["status"]}')
    if not rows:raise FileNotFoundError('No card-map and Board-to-Log run data found; verify the repository and run IDs.')
    out.mkdir(parents=True,exist_ok=True)
    csv_write(out/'card_morphology_catalog.csv',rows,CAT_FIELDS)
    actions=[c for c in candidates if c[0]['review_state']=='INVESTIGATE']
    csv_write(out/'card_review_queue.csv',[c[0] for c in actions],QUEUE_FIELDS)
    board_issues=board_issue_inventory(repo,projects)
    csv_write(out/'board_issue_inventory.csv',board_issues,BOARD_FIELDS)
    ev_rows=event_orders(repo,projects)
    csv_write(out/'event_orderings.csv',ev_rows,EVENT_FIELDS)
    buckets=defaultdict(list)
    for case in candidates:
        r=case[0];buckets[(r['project'],r['morphology'])].append(case)
    selected=[]
    for k in sorted(buckets):
        sample=sorted(buckets[k],key=lambda item:(0 if 'SOURCE_SLOT_ISSUE' in item[0]['flags'] else 1,
            0 if 'POSSIBLE_NARRATIVE_REFERENCE' in item[0]['flags'] else 1,
            item[0]['sheet'],item[0]['document_index']))
        selected.extend(sample[:examples])
    # Interleave project examples so the first screenshot batch covers more of the portfolio.
    by_project=defaultdict(list)
    for case in selected:by_project[case[0]['project']].append(case)
    selected=[by_project[project][i] for i in range(max((len(v) for v in by_project.values()),default=0))
              for project in projects if i<len(by_project[project])]
    totals=Counter(r['morphology'] for r in rows)
    native_count,warnings=capture_excel_images(repo,out,selected,excel_images)
    (out/'card_exception_gallery.html').write_text(gallery_html(selected,statuses,totals,len(rows),len(actions),missing),encoding='utf-8')
    if excel_images:
        (out/'excel_capture_warnings.txt').write_text('\n'.join(warnings) if warnings else 'No capture warnings.',encoding='utf-8')
    with (out/'morphology_summary.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f);w.writerow(['project','morphology','count','review_candidate_count'])
        for project in projects:
            for typ in sorted(totals):
                kind_count=sum(x['project']==project and x['morphology']==typ for x in rows)
                if kind_count:w.writerow([project,typ,kind_count,sum(x[0]['project']==project and x[0]['morphology']==typ for x in actions)])
    md=['# General Document — Card Morphology Discovery','',
        '## Scope','', 'Read-only analysis of existing `card_maps.json`, `board_to_log.json` and `slot_schema.json` artifacts.',
        'No changes to workbook or approval state. Version comparison is out of scope.','',
        '## Preservation principles','',
        '- Never assume source-cell order, revision membership and date-based order are equivalent.',
        '- `event_orderings.csv` retains these separately. Date ranks are provisional and NOT causal evidence.',
        '- Group interactions by document and revision; unequal SEND/RECEIVE counts are not by themselves errors.',
        '- Keep meeting-minute references and narrative references intact. Investigate questionable entries.',
        '- Interpret `SEND_ONLY` as a workflow state, not automatically a defect.',
        '- Original source coordinates remain in `card_morphology_catalog.csv`.','',
        '## Observed card morphologies','', '| Type | Count |','|---|---:|']
    for k,v in totals.most_common():md.append(f'| {k} | {v} |')
    md+=['','## Portfolio overview','', '| Project | Cards | Review candidates | Source state |','|---|---:|---:|---|']
    for s in statuses:
        md.append(f'| {s["project"]} | {s["items"]} | '+str(sum(x[0]['project']==s['project'] for x in actions))+' | '+s['status']+' |')
    md+=['','## Outputs','',
         '- `card_morphology_catalog.csv`: ALL discovered document/revision card shapes.',
         '- `card_review_queue.csv`: suspected problems requiring investigation; **not verified errors**.',
         '- Routine geometry variations are catalogued but excluded from the action queue.',
         '- `card_exception_gallery.html`: selected visual excerpts reconstructed from the Cleaner cell values.',
         '- `morphology_summary.csv`: distribution by project and type.',
         '- `event_orderings.csv`: full source-cell ordering, revision membership, provisional date ordering.',
         '- `board_issue_inventory.csv`: all current extractor issues, including cases not linked to a decoded event.',
         f'- Native Excel range images captured: {native_count} (optional; overwrites clipboard).','',
         '## Next assessment','',
         'Review anomalous forms with the project team; nominate accepted card families and exceptions before changing extraction rules.',
         'Date chronology and original-PDF OCR are later workstreams.','']
    (out/'PHASE1_DISCOVERY.md').write_text('\n'.join(md),encoding='utf-8')
    return {'status':statuses,'cards':len(rows),'candidates':len(actions),'examples':len(selected),'missing':missing,'folder':str(out),'images':native_count}


def main()->int:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--projects',default=','.join(PROJECTS),help='Comma-separated project codes')
    ap.add_argument('--examples-per-type',type=int,default=2,help='Maximum gallery examples per morphology and project (default: 2)')
    ap.add_argument('--out',help='Output folder; default portfolio_audits/card_morphology_<timestamp>')
    ap.add_argument('--excel-images',type=int,default=0,metavar='MAX',help='OPTIONAL: max native Excel CopyPicture images; uses Windows Excel, pywin32, Pillow and clipboard')
    args=ap.parse_args();repo=Path(__file__).resolve().parent
    projects=[x.strip().upper() for x in args.projects.split(',') if x.strip()]
    if not projects or any(x not in PROJECTS for x in projects):ap.error('Unknown project; choose from '+','.join(PROJECTS))
    out=Path(args.out) if args.out else repo/'portfolio_audits'/('card_morphology_'+datetime.now().strftime('%Y%m%dT%H%M%S'))
    if not out.is_absolute():out=repo/out
    try:r=execute(repo,out,projects,args.examples_per_type,args.excel_images)
    except (OSError,ValueError) as exc:print(f'[ERROR] {exc}');return 1
    print(f'[SUMMARY] cards={r["cards"]} review_candidates={r["candidates"]} gallery_examples={r["examples"]}')
    print('[FILES] card_morphology_catalog.csv | card_review_queue.csv | board_issue_inventory.csv | event_orderings.csv | morphology_summary.csv | card_exception_gallery.html | PHASE1_DISCOVERY.md')
    print(f'[OUTPUT] {out}')
    if args.excel_images:print(f'[EXCEL IMAGES] {r["images"]}/{args.excel_images}; see excel_capture_warnings.txt for skipped images')
    print('[SAFE] Read-only; no original or Cleaner run artifacts modified.')
    return 2 if r['missing'] else 0


if __name__=='__main__':raise SystemExit(main())
