#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only General Document evidence gallery from genuine Excel ranges.

Windows + Excel is required to take native screenshots. The script never saves a
source/working workbook. Approved Cleaner value overrides are rendered on an
isolated temporary copy. It NEVER manufactures an unapproved fix.

Inputs bundled alongside this script: GENERAL_DOC_REVIEW_GROUPS.csv (58 review
assignments), GENERAL_DOC_FINDINGS_103.csv (103 findings), and optional
GENERAL_DOC_CARD_CATALOG.csv (full card range discovery).
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime
import hashlib
import html
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from collections import Counter, defaultdict
from GENERAL_DOC_GALLERY_LOCALE import (TERMS, UI, RULES_FA, STATES_FA, rule_localized,
                                        state_label, comparison_note, owner_label)

PROJECTS = ('AZD','JND','FSH','YSK','EYV','BFG','NKH','NGN')
KNOWN_RUNS = {
    'AZD':'azd_20261014T071802','JND':'jnd_20261007T022038',
    'FSH':'fsh_20261007T024351','YSK':'ysk_20261016T212108',
    'EYV':'eyv_20261017T020820','BFG':'bfg_20261017T130419',
    'NKH':'nkh_20261017T053117','NGN':'ngn_20261017T143536',
}
KNOWN_SOURCE_PATHS = {
 'AZD':r'W:\00-1403\1403-02-05-230kV Azad\Letter\technical\updated Doc\General - Azad.xlsx',
 'JND':r'W:\00-1403\1403-02-03-400-132kv Jondi Shapoor\Letter\technical\Updated Doc\General - Jondi Shapour.xlsx',
 'FSH':r'W:\00-1403\1403-02-01-132kV Gostarsh Foulad shahryar\Letter\technical\GOSTARESH E FOLAD E SHAHRIAR - UPDATED DOC.xlsx',
 'YSK':r'W:\00-1400\140002-03- 63kv hasan abad yasookand\letter\technical\updated Doc\Yasookand-General.xlsx',
 'EYV':r'W:\00-1401\140102-09- 63kv Ivanaki\letter\technical\updated Doc\General-IVANAKI.xlsx',
 'BFG':r'W:\00-1403\1403-02-02-132kv Foulad Bafgh Kasra and Ext. of Nakhlestan\Letter\technical\Baafgh\updated Doc\Baafgh..xlsx',
 'NKH':r'W:\00-1403\1403-02-02-132kv Foulad Bafgh Kasra and Ext. of Nakhlestan\Letter\technical\Nakhlestan\updated Doc\Nakhlestan...xlsx',
 'NGN':r'W:\00-1403\1403-02-04-Negin Boushehr\Letter\technical\پست سیار(جلسه فنی)\General - Negin.xlsx',
}
RULES = {
 'M_LINE':('Structural boundary rule','No correspondence cell, merge, or document card may cross the established structural separator. Confirm the template geometry; do not erase an intentional separator.'),
 'DATE_CHRONOLOGY':('Event chronology','Compare source order, revision membership, and event dates separately. Verify a causal contradiction against letters; never reorder merely because cell order differs.'),
 'TEXT_IN_DATE_FIELD_POSITION':('Date lane contains narrative','A date field should contain a valid Jalali date or remain explicitly unresolved. Preserve explanatory text as a note after determining its meaning; never invent dates.'),
 'POSSIBLE_NARRATIVE_REFERENCE':('Reference-vs-note classification','Identify whether the text is a meeting/minutes reference or an explanation. Preserve meeting references; move true explanations to a note field only when the team approves.'),
 'RECEIVE_STATUS_ABSENT':('Receive-status field not present','Check whether a formal consultant response status exists. An absent status is not automatically N.A; preserve legitimate status-free receipts.'),
 'RECEIVE_STATUS_MISSING':('Receive status unpopulated','Verify status in original response and enter an approved code only if supported; otherwise leave explicitly unknown and assign follow-up.'),
 'MERGED_STATUS':('Shared or merged status region','Check whether the merged status cell intentionally describes a single response or spans multiple events. Preserve legitimate template merges; separate ambiguous statuses only with evidence.'),
 'REVISION_RECEIVE_WITHOUT_SEND':('Unpaired revision response','Trace the response to the correct SEND of the same revision; multiple sends can belong to one revision. Do not insert a made-up send event.'),
 'UNRESOLVED_UNDATED_EVENT_ORDER':('Undated correspondence ordering','Locate the referenced letter/minutes and date, or retain an undated evidence event with investigation status.'),
 'UNRESOLVED_UNDATED_EVENT':('Undated correspondence','Keep the actual reference/status and flag absent event date. Validate against the source document before any date correction.'),
 'MISSING_DATE':('Missing event date','Find exact date from correspondence; leave unresolved if source is unavailable. No guessed replacement.'),
 'MISSING_REFERENCE':('Missing correspondence reference','Retrieve the letter number or classify legitimate meeting/narrative evidence. Do not invent a reference.'),
 'MEETING_REFERENCE':('Meeting/minutes reference','Meeting identifiers (جلسه / صورتجلسه) may be legitimate event references; preserve their exact text and source evidence.'),
 'REFERENCE_YEAR_DATE_DISAGREEMENT':('Reference-year/date mismatch','Check whether the embedded reference year truly represents correspondence date. Verify both values against the actual letter; do not rewrite either from format expectations alone.'),
 'POTENTIAL_RECEIVE_BEFORE_SEND':('Possible causal inversion','Validate pairing of receive to the correct send; physical board order does not prove chronology.'),
 'RECEIVE_BEFORE_MATCHED_SEND':('Receive precedes paired send','Verify the SEND/RECEIVE linkage and exact dates. Correct only a demonstrated mismatch using official correspondence.'),
 'UNKNOWN_RECEIVE_STATUS':('Unknown business response status','Compare with approved response-status library; preserve original narrative; do not auto-classify unsupported phrases as a known status.'),
 'NO_DATED_EVENTS':('No verified event dates','Check whether the card really has correspondence. Preserve empty cells and flag missing evidence, not a date value of zero.'),
 'TALL_CARD':('Unusual card height','Inspect repeated SEND/RECEIVE records within the same revision; preserve all valid interactions instead of collapsing to one pair.'),
 'REPEATED_INTERACTIONS':('Multiple interactions within revision','Multiple SENDs and a smaller number of RECEIVEs may be legitimate: preserve every event and associate each with the correct revision.'),
 'RECEIVE_STATUS_RELATION':('Status-to-response consistency','Ensure any status is attached to its actual receive event, not an adjacent send or unrelated revision.'),
}
RANGE_RE = re.compile(r'\b\$?([A-Z]{1,3})\$?(\d+)(?::\$?([A-Z]{1,3})\$?(\d+))?\b',re.I)
COLOR_RESET='\033[0m'

def color(s, level='INFO'):
    if not (sys.stdout.isatty() and os.name=='nt'): return s
    try:
        import ctypes
        h=ctypes.windll.kernel32.GetStdHandle(-11); mode=ctypes.c_uint()
        if ctypes.windll.kernel32.GetConsoleMode(h,ctypes.byref(mode)):
            ctypes.windll.kernel32.SetConsoleMode(h,mode.value|4)
    except Exception: pass
    shade={'OK':'\033[92m','WARN':'\033[93m','ERROR':'\033[91m','INFO':'\033[96m','SKIP':'\033[90m'}.get(level,'')
    return shade+s+COLOR_RESET

def tell(level, msg): print(color(f'[{level}] {msg}',level),flush=True)

def read_csv(path):
    if not path.is_file(): raise FileNotFoundError(f'Missing evidence file: {path}')
    with path.open(encoding='utf-8-sig',newline='') as f: return list(csv.DictReader(f))

def read_json(path):
    try: return json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError,ValueError): return {}

def file_hash(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def col_num(col):
    v=0
    for c in col.upper(): v=v*26+ord(c)-64
    return v

def col_name(n):
    s=''
    while n:
        n,m=divmod(n-1,26);s=chr(65+m)+s
    return s

def parsed_range(s):
    m=RANGE_RE.fullmatch(str(s).strip().replace('$',''))
    if not m: return None
    a,b,c,d=m.groups(); c=c or a;d=d or b
    return (col_num(a),int(b),col_num(c),int(d))

def render_range(r): return f'{col_name(r[0])}{r[1]}:{col_name(r[2])}{r[3]}'

def parse_locations(s):
    return [(m.group(),parsed_range(m.group())) for m in RANGE_RE.finditer(str(s)) if parsed_range(m.group())]

def select_range(group,catalog):
    """Prefer a full card discovery region; else capture the reported source region."""
    locs=parse_locations(group.get('source_locations',''))
    proj=group['project'];sheet=group['sheet'];name=group['document'];revs=[x.strip() for x in group.get('revisions','').split(';')]
    matches=[r for r in catalog if r['project']==proj and r['sheet']==sheet and r['document']==name and (r.get('revision') in revs or revs==['-'] or revs==['?']) and parsed_range(r.get('card_range',''))]
    wanted=[]
    for _,q in locs:
        if q:wanted.append(q)
    if matches:
        cards=[parsed_range(r['card_range']) for r in matches]
        # Prefer discovered range that actually overlaps issue row; if no issue coords, first matching.
        overlapping=[c for c in cards if any(not(c[3]<w[1] or w[3]<c[1]) for w in wanted)]
        selected=overlapping or cards
        if wanted:
            # Preserve full card range with main finding, but don't accidentally include another document.
            row_sel=[w for w in wanted if any(not(c[3]<w[1] or w[3]<c[1]) for c in selected)]
            if row_sel: selected=selected+row_sel
        if selected:
            return render_range((min(x[0] for x in selected),min(x[1] for x in selected),max(x[2] for x in selected),max(x[3] for x in selected)))
    if not wanted:return None
    return render_range((min(x[0] for x in wanted),min(x[1] for x in wanted),max(x[2] for x in wanted),max(x[3] for x in wanted)))

def issues(group):return [x.strip() for x in group.get('issue_types','').split(';') if x.strip()]

def rule_text(group):
    out=[]
    for x in dict.fromkeys(issues(group)):
        title,fix=RULES.get(x,('Needs classification','Inspect source; determine a documented correction or track as an open exception.'))
        out.append({'id':x,'title':title,'fix':fix})
    return out

def get_paths(root,project,run_id,override_orig=None,override_clean=None):
    run=root/'runs'/run_id
    manifest=read_json(run/'run_manifest.json');bk=manifest.get('workbook') or {}
    receipt=read_json(root/'input'/'GENERAL_DOCUMENT'/project/'staging_receipt.json')
    primary=[Path(override_orig)] if override_orig else []
    primary += [Path(receipt['source_original_path'])] if receipt.get('source_original_path') else []
    primary += [Path(KNOWN_SOURCE_PATHS[project])]
    # If current W differs from run, flag source drift rather than claim before-after.
    auditdirs=sorted((root/'portfolio_audits').glob('portfolio_*_RUN'),reverse=True) if (root/'portfolio_audits').exists() else []
    for d in auditdirs:
        base=d/'retrieval'/project
        if base.is_dir():primary += sorted((f for f in base.iterdir() if f.suffix.lower() in ('.xlsx','.xls','.xlsm')),reverse=True)
    if receipt.get('staged_source'):primary.append(Path(receipt['staged_source']))
    working=root/'working'/'GENERAL_DOCUMENT'/project/f'{project}_GENERAL_DOC_CLEANER_WORKING.xlsx'
    # Some older projects don't have a canonical working location: manifest is authoritative.
    clean_candidates=([Path(override_clean)] if override_clean else [])+[Path(bk['path'])] if bk.get('path') else ([Path(override_clean)] if override_clean else [])
    clean_candidates += [working]
    orig=next((x for x in primary if x.is_file()),None)
    clean=next((x for x in clean_candidates if x.is_file()),None)
    return orig,clean,run,manifest

def image_capture(excel, workbook, sheet_name, addr, png, attempts=4):
    """Capture genuine Excel on-screen rendering via clipboard (or Excel chart PNG)."""
    import pythoncom
    from win32com.client import constants
    ws=workbook.Worksheets(sheet_name)
    region=ws.Range(addr)
    png.parent.mkdir(parents=True,exist_ok=True)
    last=''
    for attempt in range(attempts):
        obj=None
        try:
            try:
                ws.Activate();region.Select()
            except Exception:pass  # hidden Excel window may reject Select; CopyPicture still works
            region.CopyPicture(Appearance=1,Format=2)
            pythoncom.PumpWaitingMessages()
            try:
                from PIL import ImageGrab
                shot=ImageGrab.grabclipboard()
                if hasattr(shot,'save'):
                    shot.convert('RGB').save(str(png),'PNG')
                    excel.CutCopyMode=False
                    if png.is_file() and png.stat().st_size>100: return 'IMAGEGRAB'
            except ImportError:pass
            # Clipboard and Pillow sometimes disagree on merged/hidden Excel regions.
            obj=ws.ChartObjects().Add(Left=float(region.Left)+4,Top=float(region.Top)+4,
                                      Width=max(float(region.Width),180),Height=max(float(region.Height),70))
            obj.Chart.Paste()
            if obj.Chart.Export(str(png),'PNG'):
                if png.is_file() and png.stat().st_size>100:return 'EXCEL_CHART'
            last='Chart.Export returned false'
        except Exception as exc:
            last=str(exc)
        finally:
            if obj is not None:
                try: obj.Delete()
                except Exception: pass
            try: excel.CutCopyMode=False
            except Exception:pass
        time.sleep(.4*(attempt+1))
    raise RuntimeError('Cannot capture Excel Range.CopyPicture: '+last)

def com_retry(fn, *args, tries=5, **kw):
    for i in range(tries):
        try:return fn(*args,**kw)
        except Exception:
            if i==tries-1:raise
            try:
                import pythoncom
                pythoncom.PumpWaitingMessages()
            except Exception: pass
            time.sleep(.35*(i+1))

def safe_open(excel,path):
    return com_retry(excel.Workbooks.Open,Filename=str(path.resolve()),UpdateLinks=0,ReadOnly=True,
                     IgnoreReadOnlyRecommended=True,AddToMru=False,Notify=False)

def excel_value(cell):
    # Merged ranges resolve to anchor; Excel accepts string or None.
    try:
        m=cell.MergeArea
        if m and m.Cells.Count>1:return m.Cells(1,1)
    except Exception:pass
    return cell

def apply_approved_overlays(book,state,outcome,allowed_cells=None):
    """Apply guarded, approved value edits to disposable workbook in memory ONLY."""
    overrides=state.get('value_overrides') or {}
    touched=[]
    for key,row in overrides.items():
        if allowed_cells is not None and key.upper() not in allowed_cells:continue
        sheet=row.get('sheet');target=row.get('target');act=row.get('action')
        if act not in ('SET_VALUE','REPLACE_VALUE','CLEAR_CELL') or not sheet or not target:
            outcome.append({'cell':key,'status':'SKIPPED_UNSUPPORTED','why':str(act)})
            continue
        try:
            cell=excel_value(book.Worksheets(sheet).Range(target).Cells(1,1))
            old=cell.Value
            new=row.get('value')
            expected=row.get('expected_old_value')
            if expected is not None and str(old or '')!=str(expected or '') and str(old or '')!=str(new or ''):
                outcome.append({'cell':key,'status':'SKIPPED_PRECONDITION','why':f'{old!s} != {expected!s}'})
                continue
            if old==new:
                outcome.append({'cell':key,'status':'ALREADY_EQUAL','why':''})
                continue
            cell.Value=new
            touched.append({'cell':key,'status':'APPLIED_TO_TEMP_COPY','why':row.get('reason','')})
        except Exception as exc:
            outcome.append({'cell':key,'status':'OVERLAY_ERROR','why':str(exc)})
    outcome.extend(touched)
    return touched

def matching_overrides(state,sheet,addr):
    bounds=parsed_range(addr)
    if not bounds:return []
    hits=[]
    for key,data in (state.get('value_overrides') or {}).items():
        if (data.get('sheet') or '').casefold()!=sheet.casefold():continue
        other=parsed_range(data.get('target',''))
        if not other:continue
        if not(bounds[2]<other[0] or other[2]<bounds[0] or bounds[3]<other[1] or other[3]<bounds[1]):hits.append(key)
    return hits

def e(s):return html.escape(str(s or ''),quote=True)

def make_html(cards, summary, out, lang='en', langs=('fa', 'en')):
    # Render one self-contained, PDF-printable language-specific evidence report.

    # All source evidence is preserved; labels and actions are localized.
    if lang not in UI:raise ValueError(f'Unsupported locale: {lang}')
    d=UI[lang];fa=(lang=='fa')
    direction='rtl' if fa else 'ltr'
    def lbl(name):return e(d[name])
    def machine(value):return f'<bdi dir="ltr" class="machine">{e(value)}</bdi>'
    def desc(value):return f'<span dir="auto">{e(value)}</span>'
    items=[]
    for i,g in enumerate(cards,1):
        rules=[]
        for rule in g['rules']:
            title,fix=rule_localized(rule['id'],lang,RULES)
            rules.append(f'<details class="rule" open><summary>{machine(rule["id"])} — {e(title)}</summary><p>{e(fix)}</p></details>')
        findings=[]
        for f in g['findings']:
            title,fix=rule_localized(f.get('issue',''),lang,RULES)
            source=f'<div class="orig-evidence">{desc(f.get("original_detail"))}</div>'
            if fa:
                source+=f'<details class="english-original"><summary>{lbl("technical_original")}</summary>{desc(f.get("request"))}</details>'
            action=e(fix) if fa else e(f.get('request') or fix)
            findings.append(f'<tr><td>{machine(f.get("item_id"))}</td><td>{machine(f.get("issue"))}<span class="issue-title">{e(title)}</span></td><td>{machine(f.get("source_cells"))}</td><td>{source}</td><td>{action}</td></tr>')
        def figure(side, label):
            img=g.get(side+'_img')
            im=(f'<a href="{e(img)}" target="_blank"><img loading="lazy" src="{e(img)}" alt="{lbl("original") if side=="raw" else lbl("cleaner")}"></a>'
                if img else f'<div class="missing">{lbl("not_available")}<br>{lbl("see_warnings")}</div>')
            return f'<div class="panel {side}"><h3>{e(label)}</h3>{im}<small dir="auto">{e(g.get(side+"_path") or d["not_available"])}</small></div>'
        badge=g.get('comparison_status','UNRESOLVED')
        cls='yes' if badge=='APPROVED_OVERLAY_RENDERED' else 'warn'
        note=comparison_note(g,lang)
        project=e(g['project']);sheet=desc(g['sheet']);revision=machine(g['revisions'])
        tr=f'''<article id="{e(g['group_id'])}" data-project="{project}" data-query="{e((g['document']+' '+g['group_id']+' '+g['issue_types']).lower())}">
        <header class="casehead"><div><span class="seq">{i:02d}</span><strong>{machine(g['group_id'])}</strong> · {project} · {sheet} · {lbl('revision')}: {revision}
        <h2>{desc(g['document'])}</h2><p><b>WBS:</b> {machine(g['wbs'])} · <b>{lbl('excel_range')}:</b> {machine(g['range'] or d['unresolved'])} · <b>{lbl('reported_cells')}:</b> {machine(g['source_locations'])}</p></div>
        <b class="badge {cls}">{e(state_label(badge,lang))}</b></header>
        <div class="pair">{figure('raw',d['original'])}{figure('clean',d['cleaner'])}</div>
        <p class="note">{e(note)}</p><h3>{lbl('rules')}</h3>{''.join(rules)}
        <h3>{lbl('findings')} ({len(g['findings'])})</h3>
        <div class="tablewrap"><table><thead><tr><th>{lbl('finding_id')}</th><th>{lbl('issue')}</th><th>{lbl('source_cells')}</th><th>{lbl('original_evidence')}</th><th>{lbl('requested_fix')}</th></tr></thead><tbody>{''.join(findings)}</tbody></table></div>
        <footer>{lbl('owner')}: {e(owner_label(g['owner'],lang))} |
        {lbl('comparison_baseline')}: {e(state_label(g['comparison_mode'],lang))} |
        {lbl('hash_state')}: {e(state_label(g['hash_state'],lang))} |
        {lbl('applied')}: {machine(', '.join(g.get('applied_overrides',[])) if g.get('applied_overrides') else d['none'])}
        <p class="light">{lbl('warning')}</p></footer></article>'''
        items.append(tr)
    proj_count=Counter(x['project'] for x in cards)
    menu=''.join(f'<button type="button" data-project-filter="{p}">{p} ({proj_count.get(p,0)})</button>' for p in PROJECTS if proj_count[p])
    link_icons=''.join(f'<a class="lang-btn {"selected" if x==lang else ""}" href="GENERAL_DOCUMENT_REAL_EXCEL_GALLERY_{x.upper()}.html" lang="{x}">{e(d["language_fa"] if x=="fa" else d["language_en"])}</a>' for x in ('fa','en') if x in langs)
    css=r'''*{box-sizing:border-box}body{margin:0;background:#eef3f8;color:#18334e;font:14px/1.65 'Segoe UI',Arial,Tahoma,sans-serif}body[dir=rtl]{font-family:'B Nazanin','B Nazanin',Vazirmatn,Tahoma,Arial,sans-serif;font-size:15px;line-height:1.85}body[dir=rtl] .machine{font-family:Consolas,'Segoe UI',Arial,sans-serif;unicode-bidi:isolate;direction:ltr;display:inline-block}bdi{unicode-bidi:isolate}.mast{background:#132f50;color:white;padding:24px 5vw}.mast h1{margin:0;font-size:27px}.mast p{margin:8px 0 0;color:#d2e2ef}.mast .langs{float:inline-end;display:flex;gap:8px;align-items:center}.lang-btn{border:1px solid #95b5ce;border-radius:8px;color:white;padding:5px 13px;text-decoration:none;font-size:13px}.lang-btn.selected{background:white;color:#123655;font-weight:700}.controls{background:white;padding:14px 5vw;position:sticky;top:0;z-index:5;border-bottom:1px solid #d1dce8}.controls button{border:1px solid #abc3dd;background:#eef5fc;padding:7px 13px;border-radius:7px;margin:3px;cursor:pointer;color:#15375a}input{padding:9px;min-width:250px;max-width:100%;border:1px solid #abc3dd;border-radius:7px}main{max-width:1260px;margin:24px auto;padding:0 18px}article{background:white;padding:22px;margin:22px 0 30px;border:1px solid #d4dfe8;border-radius:10px;box-shadow:0 1px 4px #dbe1e7;break-inside:avoid}.casehead{display:flex;justify-content:space-between;gap:16px}.casehead h2{font-size:20px;margin:9px 0 5px}.casehead p{font-size:12px;color:#506175;margin:4px 0 14px}.seq{padding:7px;border-radius:50%;background:#123e66;color:white;margin-inline-end:8px}.badge{align-self:flex-start;border-radius:6px;padding:7px 10px;font-size:12px;max-width:43%;text-align:center}.badge.yes{background:#d7f9e2;color:#08703f}.badge.warn{background:#fff0bf;color:#7c5200}.pair{display:grid;grid-template-columns:1fr 1fr;gap:14px}.panel{border:1px solid #cbdded;border-radius:7px;background:#f6faff;min-height:125px;padding:12px;overflow:hidden}.panel h3{font-size:15px;margin:0 0 10px}.panel img{max-width:100%;width:auto;max-height:340px;object-fit:contain;background:white;border:1px solid #cdd8e3}.panel small{display:block;color:#708096;margin-top:9px;font-size:10px;overflow-wrap:anywhere}.missing{padding:28px;color:#9f391d;background:#fff4ea;border:1px dashed #e9c8b5}.note{padding:12px;border-inline-start:4px solid #e7b953;background:#fffaeb}.rule{padding:9px 11px;border-bottom:1px solid #e4ebf3;break-inside:avoid}.rule summary{cursor:pointer;font-weight:600}.rule p{margin:7px 0 4px}.rule code{font-weight:600;color:#0c5693}.tablewrap{overflow:auto}table{border-collapse:collapse;width:100%;font-size:12px;table-layout:fixed}th,td{border:1px solid #dbe5ee;padding:8px;vertical-align:top;text-align:start;overflow-wrap:anywhere;word-break:normal}th{background:#eaf1f8}tr:nth-child(even){background:#f7fafc}td:first-child{width:120px}td:nth-child(2){width:160px}td:nth-child(3){width:115px}.issue-title{display:block;color:#385d80;font-weight:500;margin-top:3px}.orig-evidence{white-space:pre-wrap;unicode-bidi:plaintext}.english-original{margin-top:5px;color:#58708a}.english-original summary{font-size:11px;cursor:pointer}article footer{padding-top:12px;margin-top:12px;border-top:1px solid #dfebf4;font-size:11px;color:#49617c}.light{color:#7b8796}.hidden{display:none}.notice{background:#fff9e3;padding:12px 5vw;border-bottom:1px solid #f0d999}@media(max-width:760px){.pair{grid-template-columns:1fr}.casehead{display:block}.badge{max-width:100%}}@page{size:A4 landscape;margin:11mm}@media print{body{background:white} .mast{padding:7px}.mast h1{font-size:20px}.mast p{font-size:11px}.controls,.langs{display:none!important}.notice{padding:6px;font-size:11px}main{padding:0;max-width:none;margin:0}article{break-before:page;break-inside:auto;box-shadow:none;border:0;border-radius:0;margin:0;padding:5px 0} .panel img{max-height:190px}table{font-size:9px}th,td{padding:4px}.casehead h2{font-size:15px}article:last-child{break-after:auto}}'''
    js='''let active='';function apply(){const term=document.querySelector('#search').value.toLowerCase();document.querySelectorAll('article').forEach(x=>x.classList.toggle('hidden',!!((active&&x.dataset.project!==active)||(term&&!x.dataset.query.includes(term)))))}document.querySelectorAll('[data-project-filter]').forEach(b=>b.addEventListener('click',()=>{active=b.dataset.projectFilter;apply()}));'''
    page=f'''<!DOCTYPE html><html lang="{lang}" dir="{direction}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{lbl('page_title')}</title><style>{css}</style></head><body dir="{direction}">
    <div class="mast"><div class="langs"><span>{lbl('language')}</span>{link_icons}</div><h1>{lbl('title')}</h1><p>{e(d['subtitle'].format(groups=len(cards),findings=sum(len(x['findings']) for x in cards),projects=len(proj_count)))}</p></div>
    <div class="notice"><strong>{lbl('source_fidelity')}:</strong> {lbl('notice')}</div>
    <div class="controls"><button type="button" data-project-filter="">{lbl('all')}</button>{menu}<input id="search" type="search" placeholder="{lbl('search')}" oninput="apply()"></div>
    <main>{''.join(items)}</main><script>{js}</script></body></html>'''
    out.write_text(page,encoding='utf-8')

def try_pdf(html_file,dir_path,browser,pdf_name=None):
    if browser:
        candidates=[Path(browser)]
    else:
        candidates=[]
        for path in [os.environ.get('PROGRAMFILES',''),os.environ.get('PROGRAMFILES(X86)','')]:
            if path:
                candidates += [Path(path)/'Microsoft'/'Edge'/'Application'/'msedge.exe',Path(path)/'Google'/'Chrome'/'Application'/'chrome.exe']
        for exe in ['msedge','chrome','chromium']:
            x=shutil.which(exe)
            if x:candidates.append(Path(x))
    candidate=next((p for p in candidates if p.is_file()),None)
    if not candidate:return 'NO_BROWSER: HTML can be printed to PDF from Edge via Ctrl+P'
    pdf=dir_path/(pdf_name or 'GENERAL_DOCUMENT_REAL_EXCEL_GALLERY.pdf')
    cmd=[str(candidate),'--headless','--disable-gpu','--no-first-run',f'--user-data-dir={str(dir_path/"_browser_profile")}',
         '--allow-file-access-from-files','--print-to-pdf-no-header',f'--print-to-pdf={str(pdf)}',html_file.resolve().as_uri()]
    try:
        run=subprocess.run(cmd,capture_output=True,text=True,timeout=240)
        if pdf.is_file() and pdf.stat().st_size>2000:return str(pdf)
        return f'PDF_FAILED exit={run.returncode} {run.stderr[-500:]}'
    except (OSError,subprocess.TimeoutExpired) as exc:return f'PDF_FAILED {exc}'

def build(args):
    root=Path(args.root).resolve()
    inputs=Path(args.input_dir).resolve() if args.input_dir else Path(__file__).resolve().parent
    groups=read_csv(inputs/'GENERAL_DOC_REVIEW_GROUPS.csv')
    findings=read_csv(inputs/'GENERAL_DOC_FINDINGS_103.csv')
    cat=read_csv(inputs/'GENERAL_DOC_CARD_CATALOG.csv') if (inputs/'GENERAL_DOC_CARD_CATALOG.csv').is_file() else []
    pset={x.strip().upper() for x in args.projects.split(',')} if args.projects else set(PROJECTS)
    groups=[g for g in groups if g['project'] in pset]
    by_group=defaultdict(list)
    for f in findings:by_group[f['group_id']].append(f)
    ts=datetime.now().strftime('%Y%m%dT%H%M%S')
    out=Path(args.out).resolve() if args.out else root/'portfolio_audits'/f'general_doc_real_excel_gallery_{ts}'
    out.mkdir(parents=True,exist_ok=True)
    (out/'images'/'original').mkdir(parents=True,exist_ok=True)
    (out/'images'/'cleaned').mkdir(parents=True,exist_ok=True)
    cards=[]; ledger=[]; outcome=[]; problems=[]
    capture=args.mode=='capture'
    excel=None
    if capture:
        try:
            import pythoncom,win32com.client
            pythoncom.CoInitialize()
            excel=win32com.client.DispatchEx('Excel.Application')
            excel.Visible=False
            excel.DisplayAlerts=False
            excel.AskToUpdateLinks=False
            excel.EnableEvents=False
            excel.ScreenUpdating=True
            tell('OK','Isolated Excel COM instance opened (existing Excel windows unchanged)')
        except Exception as exc:
            tell('ERROR',f'Excel automation unavailable: {exc}')
            return 2
    try:
        project_groups=defaultdict(list)
        for g in groups:project_groups[g['project']].append(g)
        for project in PROJECTS:
            if project not in pset:continue
            project_cases=project_groups.get(project,[])
            if not project_cases:continue
            run_id=KNOWN_RUNS[project]
            orig,clean,run,manifest=get_paths(root,project,run_id,args.source_path,args.clean_path)
            state=read_json(run/'resolved_state.json')
            expected_sha=str((manifest.get('workbook') or {}).get('sha256_at_run_start') or '')
            orig_hash=file_hash(orig) if orig else ''
            clean_hash=file_hash(clean) if clean else ''
            hash_state=('MATCH' if orig_hash and orig_hash==clean_hash and (not expected_sha or orig_hash==expected_sha) else
                        'DRIFT_OR_UNKNOWN' if orig and clean else 'SOURCE_MISSING')
            # Most official sources change after the reviewed run. Compare the exact
            # same *run input* before/after the approved logical overlays in that case.
            # Never pretend a newer network version is the historical unclean input.
            comparison_baseline=orig if hash_state=='MATCH' else clean
            comparison_mode='NETWORK_MATCHED' if hash_state=='MATCH' else ('RUN_INPUT_BASELINE' if clean else 'UNAVAILABLE')
            if orig and clean and orig_hash!=clean_hash:
                tell('WARN',f'{project}: network source differs; before/after will use the SAME reviewed working input (not current W:)')
            if not orig:tell('WARN',f'{project}: original source path unavailable. Use --source-path for single-project case.')
            if not clean:tell('WARN',f'{project}: Cleaner working copy not found; cannot capture cleaned view.')
            temp_dir=out/'_temp_working';temp_dir.mkdir(parents=True,exist_ok=True)
            staged=None; wb_orig=None;wb_clean=None; overlay_count=0
            try:
                if capture and clean:
                    staged=temp_dir/f'{project}{clean.suffix}'
                    shutil.copy2(clean,staged)
                    # Every edit is applied only to this disposable copied file, never to source/working.
                    wb_clean=safe_open(excel,staged)
                    allowed=set()
                    for c in project_cases:
                        span=select_range(c,cat)
                        if span:allowed.update(x.upper() for x in matching_overrides(state,c['sheet'],span))
                    modifications=apply_approved_overlays(wb_clean,state,outcome,allowed)
                    overlay_count=len(modifications)
                if capture and comparison_baseline:
                    wb_orig=safe_open(excel,comparison_baseline)
                for g in project_cases:
                    gid=g['group_id'];addr=select_range(g,cat)
                    record=dict(g)
                    record.update(range=addr,run_id=run_id,raw_path=str(comparison_baseline or ''),clean_path=str(clean or ''),
                                  network_source_path=str(orig or ''),comparison_mode=comparison_mode,
                                  hash_state=hash_state,findings=by_group.get(gid,[]),rules=rule_text(g),
                                  overrides=matching_overrides(state,g['sheet'],addr) if addr else [],
                                  raw_img='',clean_img='',owner='Engineering + Document Control',
                                  comparison_status='UNRESOLVED',comparison_note='')
                    changed=[x for x in record['overrides'] if any(y['cell'].upper()==x.upper() and y['status']=='APPLIED_TO_TEMP_COPY' for y in outcome)]
                    record['applied_overrides']=changed
                    if not addr:
                        record['comparison_note']='No validated Excel A1 range; user must locate the case manually. Neither side was synthesized.'
                        record['comparison_status']='MISSING_CELL_LOCATION'
                    elif not comparison_baseline or not clean:
                        record['comparison_note']='Original or Cleaner workbook is not accessible. Capture remains pending.'
                        record['comparison_status']='MISSING_WORKBOOK'
                    else:
                        record['comparison_note']='No approved cell-value repair intersects this region; the Cleaner may only have interpreted or acknowledged its findings. This is NOT a fixed source card.'
                        record['comparison_status']='UNRESOLVED' if not changed else 'APPROVED_OVERLAY_RENDERED'
                        if changed:record['comparison_note']='Approved guarded cell overrides are rendered in the temp clean screenshot; structural or business issues may remain unverified.'
                        if comparison_mode=='RUN_INPUT_BASELINE':
                            record['comparison_note'] += ' Source workbook has changed or was unavailable, so the unedited Cleaner RUN INPUT is used for a valid same-version comparison (not the latest W: file).'
                    if capture and addr:
                        stem=gid.replace('/','_')
                        if wb_orig:
                            img=out/'images'/'original'/f'{stem}.png'
                            try:
                                image_capture(excel,wb_orig,g['sheet'],addr,img)
                                record['raw_img']=img.relative_to(out).as_posix()
                            except Exception as exc:problems.append({'group_id':gid,'side':'ORIGINAL','error':str(exc)})
                        if wb_clean:
                            img=out/'images'/'cleaned'/f'{stem}.png'
                            try:
                                image_capture(excel,wb_clean,g['sheet'],addr,img)
                                record['clean_img']=img.relative_to(out).as_posix()
                            except Exception as exc:problems.append({'group_id':gid,'side':'CLEANED','error':str(exc)})
                    if capture and not record['raw_img'] or capture and not record['clean_img']:
                        record['comparison_status']='CAPTURE_INCOMPLETE'
                    cards.append(record)
                    for f in record['findings']:
                        ledger.append({'group_id':gid,'item_id':f['item_id'],'project':project,'document':g['document'],
                                       'revision':g['revisions'],'issue':f['issue'],'rule_title':rule_localized(f['issue'],'en',RULES)[0],
                                       'source_cells':f['source_cells'],'capture_range':addr or '',
                                       'original_evidence':f['original_detail'],'recommended_action':f['request'],
                                       'original_png':record['raw_img'],'cleaner_png':record['clean_img'],
                                       'comparison_status':record['comparison_status'],'hash_state':hash_state,'comparison_mode':comparison_mode})
                tell('OK',f'{project}: groups={len(project_cases)} screenshots={sum(bool(x["raw_img"])+bool(x["clean_img"]) for x in cards if x["project"]==project)} overrides_in_temp={overlay_count}')
            except Exception as exc:
                problems.append({'group_id':project,'side':'PROJECT','error':repr(exc)})
                tell('ERROR',f'{project}: {exc}')
            finally:
                for w in (wb_orig,wb_clean):
                    if w:
                        try:com_retry(w.Close,SaveChanges=False)
                        except Exception as exc:problems.append({'group_id':project,'side':'EXCEL_CLOSE','error':str(exc)})
                if staged:
                    try:staged.unlink(missing_ok=True)
                    except Exception:pass
        write_csv(out/'all_103_findings_with_images.csv',ledger)
        summary=[{k: str(v) for k,v in g.items() if k not in ('findings','rules','overrides','applied_overrides')} for g in cards]
        write_csv(out/'all_58_grouped_cases.csv',summary)
        write_csv(out/'approved_overlay_outcomes.csv',outcome)
        write_csv(out/'capture_warnings.csv',problems)
        languages=('fa','en') if args.lang=='both' else (args.lang,)
        for lang in languages:
            make_html(cards,None,out/f'GENERAL_DOCUMENT_REAL_EXCEL_GALLERY_{lang.upper()}.html',lang=lang,langs=languages)
        # Backward-compatible default entry file opens the selected/default language.
        default_language='fa' if 'fa' in languages else 'en'
        shutil.copy2(out/f'GENERAL_DOCUMENT_REAL_EXCEL_GALLERY_{default_language.upper()}.html',
                     out/'GENERAL_DOCUMENT_REAL_EXCEL_GALLERY.html')
        # Bilingual exports preserve raw English evidence alongside translated rule/action text.
        for row in ledger:
            title,fix=rule_localized(row['issue'],'fa',RULES)
            row['issue_title_fa']=title
            row['recommended_action_fa']=fix
            row['comparison_status_fa']=state_label(row.get('comparison_status',''),'fa')
            row['owner_fa']='بخش مهندسی و کنترل اسناد'
        write_csv(out/'all_103_findings_bilingual.csv',ledger)
        for group in summary:
            group['issue_types_fa']='؛ '.join(rule_localized(i,'fa',RULES)[0] for i in issues(group))
            group['comparison_status_fa']=state_label(group.get('comparison_status',''),'fa')
        write_csv(out/'all_58_grouped_cases_bilingual.csv',summary)
        glossary=[{'category':'APPROVED_TERM','code':'','English':a,'فارسی':b,'description_en':'','شرح فارسی':''} for a,b in TERMS]
        glossary += [{'category':'INTERFACE_LABEL','code':key,'English':UI['en'][key],'فارسی':UI['fa'][key],
                       'description_en':'','شرح فارسی':''} for key in UI['en'] if key in UI['fa']
                       and key not in ('subtitle','notice','warning')]
        glossary += [{'category':'RULE','code':key,'English':value[0],'فارسی':RULES_FA[key][0],
                       'description_en':value[1],'شرح فارسی':RULES_FA[key][1]} for key,value in RULES.items()]
        glossary += [{'category':'STATUS','code':key,'English':key,'فارسی':fa,
                       'description_en':'','شرح فارسی':''} for key,fa in STATES_FA.items()]
        write_csv(out/'BILINGUAL_TERMS.csv',glossary)
        (out/'gallery_summary.json').write_text(json.dumps({'groups':len(cards),'findings':len(ledger),
             'captured_original':sum(bool(x['raw_img']) for x in cards),
             'captured_cleaner':sum(bool(x['clean_img']) for x in cards),
             'approved_changes_in_comparison':sum(x['comparison_status']=='APPROVED_OVERLAY_RENDERED' for x in cards),
             'comparison_states':dict(Counter(x['comparison_status'] for x in cards)),
             'capture_warnings':len(problems)},indent=2),encoding='utf-8')
        tell('INFO',f'Groups={len(cards)} | findings={len(ledger)} | original shots={sum(bool(x["raw_img"]) for x in cards)} | cleaner shots={sum(bool(x["clean_img"]) for x in cards)}')
        for lang in languages:
            tell('INFO',f'HTML {lang.upper()}: {out/f"GENERAL_DOCUMENT_REAL_EXCEL_GALLERY_{lang.upper()}.html"}')
        if args.pdf and capture:
            for lang in languages:
                result=try_pdf(out/f'GENERAL_DOCUMENT_REAL_EXCEL_GALLERY_{lang.upper()}.html',out,args.browser,
                               pdf_name=f'GENERAL_DOCUMENT_REAL_EXCEL_GALLERY_{lang.upper()}.pdf')
                tell('OK' if result.lower().endswith('.pdf') else 'WARN',f'PDF {lang.upper()}: {result}')
        tell('OK',f'Gallery created: {out}')
    finally:
        if excel is not None:
            try:excel.Quit()
            except Exception:pass
        try:
            import pythoncom
            pythoncom.CoUninitialize()
        except Exception:pass
    return 0 if capture and not problems else 0 if not capture else 1

def write_csv(file,records):
    fieldnames=list(dict.fromkeys(k for row in records for k in row)) or ['empty']
    with file.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fieldnames,extrasaction='ignore');w.writeheader();w.writerows(records)

def parse_args(argv=None):
    p=argparse.ArgumentParser(description='Real Excel screenshot evidence gallery for 58 grouped General Document cases / 103 findings')
    p.add_argument('--root',default='.',help='cleaner-functions repository root')
    p.add_argument('--lang',choices=('both','fa','en'),default='both',help='Report language(s); default both Persian RTL and English LTR')
    p.add_argument('--input-dir',default=None,help='Directory with bundled 3 CSV evidence files (default: script directory)')
    p.add_argument('--out',default=None,help='Output directory; default portfolio_audits/timestamp')
    p.add_argument('--projects',default=','.join(PROJECTS),help='Comma-separated project codes')
    p.add_argument('--mode',choices=('capture','inventory'),default='capture',help='inventory works without Windows/Excel and generates all rules/finding details')
    p.add_argument('--source-path',default=None,help='Override original/source workbook path for a single project')
    p.add_argument('--clean-path',default=None,help='Override Cleaner working workbook path for a single project')
    p.add_argument('--pdf',action=argparse.BooleanOptionalAction,default=True,help='Print HTML to PDF using locally installed Edge/Chrome (default on)')
    p.add_argument('--browser',default=None,help='Optional full path to Edge/Chrome executable')
    args=p.parse_args(argv)
    if (args.source_path or args.clean_path) and len(args.projects.split(','))>1:
        p.error('--source-path/--clean-path require one --projects code')
    return args

if __name__=='__main__':
    raise SystemExit(build(parse_args()))
