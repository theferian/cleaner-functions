#!/usr/bin/env python3
"""General Document Phase 2: read-only, evidence-grounded chronology audit.

Requirements: Python 3.10+, standard library only. Run from cleaner-functions root:
  py CHRONOLOGY_TEST_SUITE_V01.py --phase1-dir portfolio_audits/card_morphology_20261018T044939 --status-date 1405/07/22

Reads existing Phase 1 CSV files, NEVER edits original Excel files or Cleaner runs.
Preserves distinct source-cell, revision-membership and date orderings.
"""
from __future__ import annotations
import argparse
import csv
import html
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

DATE_RE=re.compile(r'^\s*(\d{4})[/-](\d{1,2})[/-](\d{1,2})\s*$')
REF_YEAR_RE=re.compile(r'^\s*(1[34]\d{2})\s*[/\-]\s*[A-Za-z]{1,6}\s*[/\-]\s*[A-Za-z]{1,6}\s*[/\-]\s*\d+')
CASE_FIELDS=['case_id','project','sheet','document_index','document','wbs','revision','test_id',
             'test','category','severity','finding','date_a','date_b','source_a','source_b',
             'reference_a','reference_b','evidence_basis','recommended_action','review_state']
EVENT_FIELDS=['project','sheet','document_index','document','wbs','revision','direction',
              'letter_date','date_validity','letter_reference','doc_status','date_source',
              'reference_source','status_source','source_cell_order_rank','date_order_rank',
              'original_log_sequence','chronology_rank_verified','run_id']
SUMMARY_FIELDS=['project','records','revisions','action_findings','investigations','observations',
                'invalid_dates','potential_response_inversions','undated_events','source_order_observations',
                'card_count_mismatches']
# Empirical civil Jalali 33-year leap cycle for the historical EPC range
# 1350..1420. Extend with an authoritative calendar implementation if a
# workbook contains earlier/later years rather than silently guessing.
LEAP_REMAINDERS=frozenset((1,5,9,13,17,22,26,30))


def is_leap_jalali(y:int)->bool:
    if not 1350<=y<=1420:
        raise ValueError('Jalali leap-year lookup is only verified for 1350..1420')
    return y%33 in LEAP_REMAINDERS


def jalali_date(value:object)->tuple[tuple[int,int,int]|None,str]:
    s=str(value or '').strip()
    if not s:return None,'MISSING'
    m=DATE_RE.fullmatch(s)
    if not m:return None,'BAD_FORMAT'
    y,mo,d=map(int,m.groups())
    if not (1350<=y<=1420):return None,'YEAR_OUTSIDE_SUPPORTED_CALENDAR_RANGE'
    if not (1<=mo<=12):return None,'INVALID_MONTH'
    max_day=31 if mo<=6 else 30 if mo<=11 else 30 if is_leap_jalali(y) else 29
    if not (1<=d<=max_day):return None,'INVALID_DAY'
    return (y,mo,d),'VALID'


def parse_csv(path:Path)->list[dict]:
    if not path.is_file():raise FileNotFoundError(f'Phase 1 file missing: {path}')
    with path.open(newline='',encoding='utf-8-sig') as f:return list(csv.DictReader(f))


def write_csv(path:Path,rows:list[dict],columns:list[str]):
    with path.open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=columns,extrasaction='ignore');w.writeheader();w.writerows(rows)


def as_int(s,default:int=0)->int:
    try:return int(s)
    except (ValueError,TypeError):return default


def make_issue(r:dict,test_id:str,test:str,category:str,severity:str,finding:str,
               a:dict|None=None,b:dict|None=None,basis:str='',action:str='') -> dict:
    a=a or {};b=b or {}
    return {'case_id':'', 'project':r.get('project',''),'sheet':r.get('sheet',''),
      'document_index':r.get('document_index',''),'document':r.get('document',''),
      'wbs':r.get('wbs',''),'revision':r.get('revision',''),
      'test_id':test_id,'test':test,'category':category,'severity':severity,'finding':finding,
      'date_a':a.get('letter_date',''),'date_b':b.get('letter_date',''),
      'source_a':a.get('date_source',''),'source_b':b.get('date_source',''),
      'reference_a':a.get('letter_reference',''),'reference_b':b.get('letter_reference',''),
      'evidence_basis':basis,'recommended_action':action,
      'review_state':'OPEN_INVESTIGATION' if category=='INVESTIGATE' else 'OBSERVATION' if category=='OBSERVE' else 'OPEN_ACTION'}


def group_key(e:dict)->tuple:
    return tuple(e.get(k,'') for k in ('project','sheet','document_index','revision'))


def compact_evidence(events:list[dict])->str:
    return '; '.join(f"{e.get('direction','?').upper()} {e.get('letter_date','?')} {e.get('date_source','?')} {e.get('letter_reference','')}" for e in events[:6])


def evaluate(events:list[dict],cards:list[dict],status_date:str)->tuple[list[dict],list[dict],list[dict]]:
    cutoff,valid=jalali_date(status_date)
    if valid!='VALID':raise ValueError(f'Invalid --status-date {status_date!r}: {valid}')
    findings=[]
    enriched=[]
    groups=defaultdict(list)
    documents=defaultdict(list)
    for e in events:
        item=dict(e)
        item['_date'],item['date_validity']=jalali_date(item.get('letter_date'))
        item['chronology_rank_verified']=''
        enriched.append(item)
        groups[group_key(item)].append(item)
        documents[group_key(item)[:3]].append(item)
        if item['date_validity']=='MISSING':
            # An extracted event with no date is actionable if it carries a reference or status.
            if item.get('letter_reference') or item.get('doc_status'):
                findings.append(make_issue(item,'C07','UNRESOLVED_UNDATED_EVENT','INVESTIGATE','MEDIUM',
                    'An event has a reference/status but no usable date.',item,basis='Original board event has an empty date.',
                    action='Verify the date in the linked letter or minutes; do not invent one.'))
        elif item['date_validity']!='VALID':
            findings.append(make_issue(item,'C01','INVALID_JALALI_DATE','ACTION','HIGH',
                f"Date {item.get('letter_date')!r} fails {item['date_validity']} validation.",item,
                basis='Jalali calendar/date format validation.',
                action='Inspect the original correspondence and correct the specific source cell if verified.'))
        elif item['_date']>cutoff:
            findings.append(make_issue(item,'C11','EVENT_AFTER_REPORTING_CUTOFF','OBSERVE','INFO',
                'This is a future event relative to the reporting cut-off, not necessarily bad source data.',item,
                basis=f'Status date {status_date}; current source retains the later event.',
                action='Exclude this event from as-of reporting; preserve it in source event history.'))
        match=REF_YEAR_RE.match(str(item.get('letter_reference') or ''))
        if match and item['_date'] and item.get('direction','').strip().lower()=='send':
            ref_y=int(match.group(1))
            if ref_y!=item['_date'][0]:
                findings.append(make_issue(item,'C08','REFERENCE_YEAR_DATE_DISAGREEMENT','INVESTIGATE','MEDIUM',
                    f"The reference begins with year {ref_y}, but the event is dated {item.get('letter_date')}; may reflect an entry error or legitimate reference reuse.",item,
                    basis='Explicit four-digit year in a standardized SEND reference.',
                    action='Compare reference and date with the original sent correspondence.'))
    for key,grp in groups.items():
        # Ranks in this group reflect date alone. Source order remains separate and unchanged.
        dated=sorted((x for x in grp if x['_date'] is not None),
                     key=lambda x:(x['_date'],as_int(x.get('source_cell_order_rank'),999999),as_int(x.get('original_log_sequence'))))
        for rank,e in enumerate(dated,1):e['chronology_rank_verified']=rank
        by_source=sorted(grp,key=lambda x:(as_int(x.get('source_cell_order_rank'),999999),as_int(x.get('original_log_sequence'))))
        for left,right in zip(by_source,by_source[1:]):
            if left['_date'] and right['_date'] and left['_date']>right['_date']:
                findings.append(make_issue(left,'C04','PHYSICAL_SOURCE_DATE_INVERSION','OBSERVE','INFO',
                  'Date goes backwards in board-cell traversal; this alone does not prove an error.',left,right,
                  basis='Adjacent extracted events within the same revision, sorted by source-cell order.',
                  action='No correction without independent causal or source-document evidence.'))
        sends=[x for x in grp if x.get('direction','').strip().lower()=='send' and x['_date']]
        receives=[x for x in grp if x.get('direction','').strip().lower()=='receive' and x['_date']]
        # Exactly one send and one receive within same revision supports a tentative pair only.
        # Same revision DOES NOT prove the response explicitly refers to that send.
        if len(sends)==len(receives)==1:
            s,rec=sends[0],receives[0]
            if rec['_date']<s['_date']:
                findings.append(make_issue(rec,'C02','POTENTIAL_RECEIVE_BEFORE_SEND','INVESTIGATE','HIGH',
                    'Single SEND/RECEIVE pair in the revision has a response date before its submission date; linkage is not yet verified.',s,rec,
                    basis='One SEND and one RECEIVE in the same revision; no confirmed reference relationship.',
                    action='Check the original receive letter and its referenced submission before correcting a date.'))
            elif rec['_date']==s['_date']:
                findings.append(make_issue(rec,'C06','SAME_DAY_DIRECTION_ORDER_UNVERIFIED','OBSERVE','INFO',
                    'Send and receive share a date. Time-of-day/causal order is unverified.',s,rec,
                    basis='Exactly one SEND and RECEIVE in the same revision on the same Jalali day.',
                    action='Keep date-level equivalence; only investigate if a reporting rule requires an ordering.'))
        if receives and not any(x.get('direction','').strip().lower()=='send' for x in grp):
            findings.append(make_issue(receives[0],'C12','REVISION_RECEIVE_WITHOUT_SEND','INVESTIGATE','MEDIUM',
                'Response exists without a SEND in this revision; the send may exist in another revision.',receives[0],
                basis='Event counts inside revision only, not a verified correspondence chain.',
                action='Confirm correct revision assignment or locate the corresponding submission.'))
        for x in grp:
            if x.get('direction','').strip().lower()=='receive' and not str(x.get('doc_status') or '').strip():
                findings.append(make_issue(x,'C10','RECEIVE_STATUS_ABSENT','INVESTIGATE','MEDIUM',
                    'Received correspondence has no recognizable extracted status.',x,
                    basis='Receive event has an empty doc_status field.',
                    action='Check whether a formal response status was required; retain genuinely status-free receipts.'))
        # Duplicate extraction only when source cells repeat identically (not when different transmissions share a reference).
        seen={}
        for x in grp:
            token=(x.get('direction'),x.get('letter_date'),x.get('letter_reference'),x.get('date_source'),x.get('reference_source'))
            if token in seen:
                findings.append(make_issue(x,'C15','DUPLICATE_EXTRACTED_SOURCE_EVENT','ACTION','HIGH',
                    'One identical event and source-cell pair appears more than once in Board→Log.',seen[token],x,
                    basis='All five event/source identity fields match within the same revision.',
                    action='Inspect the extractor for duplicate parsing; do not delete source cells.'))
            else:seen[token]=x
        if str(key[3]).strip() in ('','?','None'):
            findings.append(make_issue(grp[0],'C03','UNVERIFIED_REVISION_MEMBERSHIP','INVESTIGATE','MEDIUM',
                 'Event revision membership is missing or uncertain.',grp[0],
                 basis='No defined revision label on extracted event.',
                 action='Confirm source revision heading and update the mapping rather than guessing.'))
    # Cross-artifact invariants verify we did not lose event counts in a card.
    card_by_key={group_key(c):c for c in cards}
    for key,card in card_by_key.items():
        grp=groups.get(key,[])
        counts=(sum(x.get('direction','').strip().lower()=='send' for x in grp),
                sum(x.get('direction','').strip().lower()=='receive' for x in grp))
        declared=(as_int(card.get('send_count')),as_int(card.get('receive_count')))
        if counts!=declared:
            findings.append(make_issue(card,'C05','CARD_LOG_EVENT_COUNT_MISMATCH','ACTION','HIGH',
                  f'Card catalog says SEND/RECEIVE={declared}, event export says {counts}.',grp[0] if grp else None,
                  basis='Cross-check morphology catalog and individual events using project, sheet, document index and revision.',
                  action='Rebuild event ordering from the same run artifacts; inspect mismatched extraction; do not invent events.'))
    # Duplicate reference uses are observations: one letter can legitimately cover multiple documents/revisions.
    for key,grp in documents.items():
        refs=defaultdict(list)
        for x in grp:
            ref=str(x.get('letter_reference') or '').strip().upper()
            if ref:refs[(x.get('direction','').strip().lower(),ref)].append(x)
        for (direction,ref),items in refs.items():
            unique_cells={(x.get('date_source'),x.get('reference_source')) for x in items}
            if len(unique_cells)>1:
                findings.append(make_issue(items[0],'C09','REFERENCE_REUSED_WITHIN_DOCUMENT','OBSERVE','INFO',
                    f'{direction.upper()} reference {ref!r} appears in {len(unique_cells)} different source positions; may be legitimate.',items[0],items[1],
                    basis='Same document, direction and reference text in distinct source cells.',
                    action='No automatic deduplication; investigate only with evidence of a collision.'))
    # Stable case id: unique within this one audit, allows reviewers to cite C02/YSK/... cases.
    finding_counter=Counter()
    for f in findings:
        prefix=f['project']+'-'+f['test_id']
        finding_counter[prefix]+=1
        f['case_id']=prefix+'-'+str(finding_counter[prefix]).zfill(4)
    ordered=sorted(findings,key=lambda f:('ACTION','INVESTIGATE','OBSERVE').index(f['category']) if f['category'] in ('ACTION','INVESTIGATE','OBSERVE') else 9)
    # Derived values no longer carry private convenience fields into file output.
    for e in enriched:e.pop('_date',None)
    summary=[]
    for project in sorted({e['project'] for e in enriched}|{c['project'] for c in cards}):
        p=[f for f in ordered if f['project']==project]
        ev=[e for e in enriched if e['project']==project]
        cr=[c for c in cards if c['project']==project]
        summary.append({'project':project,'records':len(ev),'revisions':len(cr),
           'action_findings':sum(f['category']=='ACTION' for f in p),
           'investigations':sum(f['category']=='INVESTIGATE' for f in p),
           'observations':sum(f['category']=='OBSERVE' for f in p),
           'invalid_dates':sum(f['test_id']=='C01' for f in p),
           'potential_response_inversions':sum(f['test_id']=='C02' for f in p),
           'undated_events':sum(f['test_id']=='C07' for f in p),
           'source_order_observations':sum(f['test_id']=='C04' for f in p),
           'card_count_mismatches':sum(f['test_id']=='C05' for f in p)})
    return ordered,enriched,summary


def esc(x:object)->str:return html.escape(str(x or ''),quote=True)


def make_html(findings:list[dict],events:list[dict],summary:list[dict],status_date:str)->str:
    by_group=defaultdict(list)
    for e in events:by_group[group_key(e)].append(e)
    css='''body{font:14px Segoe UI,Arial,sans-serif;max-width:1250px;margin:24px auto;padding:0 20px;background:#f5f7fa;color:#182536}
    h1{font-size:24px}h2{font-size:18px}h3{font-size:15px;margin:4px 0}small,.muted{color:#58677b}
    table{border-collapse:collapse;width:100%}td,th{padding:7px;border:1px solid #dce2ec;text-align:left;vertical-align:top}th{background:#eef1f6}
    section{background:#fff;border:1px solid #dfe5ef;border-radius:10px;padding:18px;margin:14px 0;break-inside:avoid}
    .chip{display:inline-block;border-radius:4px;background:#e9eff9;padding:3px 7px;margin-right:6px;font-size:12px}
    .ACTION{border-left:5px solid #b91c1c}.INVESTIGATE{border-left:5px solid #d58a05}.OBSERVE{border-left:5px solid #64748b}
    summary{cursor:pointer;color:#17365d;font-weight:600;margin:8px 0}.scroll{max-height:350px;overflow:auto}
    code{font-family:Consolas,monospace;font-size:12px}.note{background:#ecf3fd;padding:12px;border-radius:8px}
    @media print{body{background:white;margin:0}.scroll{max-height:none}}'''
    top=['<!doctype html><html lang="en"><meta charset="utf-8"><title>Chronology investigations</title><style>',css,'</style><body>',
         '<h1>General Document — Chronology Test Suite</h1>',
         '<p class="note">Read-only investigation register. Source-cell order, revision membership, and date order are independent. A reverse cell sequence is NOT proof of an incorrect date. No event linkage is assumed solely from physical adjacency. Reporting cut-off: <strong>'+esc(status_date)+'</strong>.</p>',
         '<h2>Portfolio summary</h2><table><tr><th>Project</th><th>Events</th><th>Revision cards</th><th>Action</th><th>Investigate</th><th>Observe</th></tr>']
    for s in summary:top.append('<tr>'+''.join('<td>'+esc(s[k])+'</td>' for k in ('project','records','revisions','action_findings','investigations','observations'))+'</tr>')
    top.append('</table><h2>Findings and source evidence</h2>')
    for f in findings:
        category=f['category']; key=group_key(f)
        entries=sorted(by_group.get(key,[]),key=lambda e:as_int(e.get('source_cell_order_rank'),999999))
        top.append('<section class="'+category+'"><div><span class="chip">'+esc(f['case_id'])+'</span><span class="chip">'+esc(category)+'</span><span class="chip">'+esc(f['severity'])+'</span></div>')
        top.append('<h3>'+esc(f['test'])+' — '+esc(f['project'])+' / '+esc(f['document'])+'</h3>')
        top.append('<p><strong>Sheet:</strong> '+esc(f['sheet'])+' &nbsp; <strong>WBS:</strong> '+esc(f['wbs'])+' &nbsp; <strong>Revision:</strong> '+esc(f['revision'])+'</p>')
        top.append('<p>'+esc(f['finding'])+'<br><small>Evidence: '+esc(f['evidence_basis'])+'</small></p>')
        top.append('<p><strong>Source cells:</strong> '+esc(f['source_a'])+' → '+esc(f['source_b'])+' &nbsp; <strong>Dates:</strong> '+esc(f['date_a'])+' → '+esc(f['date_b'])+'</p>')
        top.append('<p><strong>Proposed review:</strong> '+esc(f['recommended_action'])+'</p>')
        top.append('<details><summary>Show all events in this revision (source-cell order)</summary><div class="scroll"><table><tr><th>Cell order</th><th>Date order</th><th>Direction</th><th>Date</th><th>Reference</th><th>Status</th><th>Source date / reference</th></tr>')
        for e in entries:
            top.append('<tr>'+''.join('<td>'+esc(e.get(k,''))+'</td>' for k in ('source_cell_order_rank','chronology_rank_verified','direction','letter_date','letter_reference','doc_status'))+'<td>'+esc(e.get('date_source'))+' / '+esc(e.get('reference_source'))+'</td></tr>')
        top.append('</table></div></details></section>')
    top.append('</body></html>')
    return ''.join(top)


def find_phase1(repo:Path)->Path:
    base=repo/'portfolio_audits'
    candidates=[p for p in base.glob('card_morphology_*') if (p/'event_orderings.csv').exists()]
    if not candidates:raise FileNotFoundError('Phase 1 output not found. Pass --phase1-dir explicitly.')
    return sorted(candidates,key=lambda p:p.name)[-1]


def run(phase1:Path,out:Path,status_date:str,projects:set[str]|None=None)->dict:
    events=parse_csv(phase1/'event_orderings.csv')
    cards=parse_csv(phase1/'card_morphology_catalog.csv')
    if projects:
        events=[e for e in events if e.get('project') in projects]
        cards=[c for c in cards if c.get('project') in projects]
    if not events or not cards:raise ValueError('No matching event records or morphology cards in Phase 1 data.')
    findings,enriched,summary=evaluate(events,cards,status_date)
    out.mkdir(parents=True,exist_ok=True)
    write_csv(out/'chronology_findings_all.csv',findings,CASE_FIELDS)
    write_csv(out/'chronology_team_investigations.csv',[f for f in findings if f['category']!='OBSERVE'],CASE_FIELDS)
    write_csv(out/'chronology_observations.csv',[f for f in findings if f['category']=='OBSERVE'],CASE_FIELDS)
    write_csv(out/'chronology_event_orders.csv',enriched,EVENT_FIELDS)
    write_csv(out/'chronology_summary.csv',summary,SUMMARY_FIELDS)
    (out/'chronology_exception_gallery.html').write_text(make_html(findings,enriched,summary,status_date),encoding='utf-8')
    counts=Counter(f['test'] for f in findings)
    md=['# Phase 2 — General Document Chronology Test Suite','',
        '**Read-only examination** of Phase 1 extracted events. No workbook, overlay or Cleaner state was modified.','',
        f'Source: `{phase1}`  ', f'Reporting cut-off: `{status_date}`','',
        '## Three independent orderings','',
        '1. Source-cell order: recorded positions and extraction traversal.','2. Revision membership: extracted document/revision bucket.','3. Date order: validated Jalali dates only; not evidence of send-response causality.','',
        '## Portfolio totals','', '| Project | Events | Revision cards | Action | Investigate | Observe |',
        '|---|---:|---:|---:|---:|---:|']
    for s in summary:
        md.append('| '+' | '.join(str(s[k]) for k in ('project','records','revisions','action_findings','investigations','observations'))+' |')
    md+=['','## Finding types','', '| Test | Count |','|---|---:|']
    for key,count in counts.most_common():md.append(f'| {key} | {count} |')
    md+=['','## Investigation policy','',
         '- The team queue excludes observational source-cell inversions and same-day order ambiguity.','- One SEND + one RECEIVE in a revision gives a **tentative** link, not a proven causal link.','- Multiple sends and unequal send/receive counts are valid structures until contradicted by actual evidence.',
         '- Repeated references are preserved and merely listed as observations; never auto-deduplicated.','- Report cutoff is applied as a flag only here; the suite does not assert engineering-list calculations.','- Missing dates are flagged for original-letter examination; never invented.','- Document family label remains human-designated; source versioning out of scope.','',
         '## Outputs','',
         '- `chronology_team_investigations.csv`: actionable or uncertain cases for the project team.',
         '- `chronology_observations.csv`: noteworthy patterns with no presumed correction.',
         '- `chronology_event_orders.csv`: evidence with three separate orderings.',
         '- `chronology_exception_gallery.html`: source evidence and per-revision event timelines.',
         '- `chronology_summary.csv`: per-project assessment.','',
         '## Next workstream','',
         'Evidence Retrieval & OCR: search linked correspondence, compare extracted dates/references and request review for low-confidence crops.','']
    (out/'PHASE2_CHRONOLOGY_REPORT.md').write_text('\n'.join(md),encoding='utf-8')
    return {'records':len(enriched),'cards':len(cards),'findings':len(findings),
            'action':sum(f['category']=='ACTION' for f in findings),
            'investigation':sum(f['category']=='INVESTIGATE' for f in findings),
            'observation':sum(f['category']=='OBSERVE' for f in findings),
            'output':str(out),'phase1':str(phase1)}


def main()->int:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--phase1-dir',help='Existing Phase 1 output; default newest card_morphology_* folder')
    ap.add_argument('--out',help='Output folder; default portfolio_audits/chronology_<timestamp>')
    ap.add_argument('--status-date',default='1405/07/22',help='Jalali reporting cut-off')
    ap.add_argument('--projects',help='Optional comma-separated project codes')
    args=ap.parse_args()
    repo=Path(__file__).resolve().parent
    try:
        phase1=Path(args.phase1_dir) if args.phase1_dir else find_phase1(repo)
        if not phase1.is_absolute():phase1=repo/phase1
        out=Path(args.out) if args.out else repo/'portfolio_audits'/('chronology_'+datetime.now().strftime('%Y%m%dT%H%M%S'))
        if not out.is_absolute():out=repo/out
        requested=set(v.strip().upper() for v in args.projects.split(',') if v.strip()) if args.projects else None
        result=run(phase1,out,args.status_date,requested)
    except (OSError,ValueError) as exc:
        print('[ERROR] '+str(exc));return 1
    print(f'[CHRONOLOGY] events={result["records"]} revision_cards={result["cards"]}')
    print(f'[FINDINGS] action={result["action"]} investigate={result["investigation"]} observe={result["observation"]}')
    print('[FILES] chronology_team_investigations.csv | chronology_observations.csv | chronology_event_orders.csv | chronology_summary.csv | chronology_exception_gallery.html | PHASE2_CHRONOLOGY_REPORT.md')
    print('[OUTPUT] '+result['output'])
    print('[SAFE] Read-only; no source or existing Cleaner artifacts modified.')
    return 0

if __name__=='__main__':sys.exit(main())
