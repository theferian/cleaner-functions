"""Guided source verification workbench v0.4.

Built on top of v0.3's journals/ledger, v0.2's OCR worker and the native Human Edit canvas.
Adds no PDF/General Doc writes; training approval and evidence verification are separate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tkinter as tk
from tkinter import ttk, messagebox

import adaptive_document_annotator_v0_6 as native
from card_verification_dashboard_v03 import CardVerificationDashboard
from card_workbench_core_v04 import (FAMILIES, SCOPES, REQUIRED, scoped, signature,
                                      normalise_rects, save_draft, load_draft, export_machine_results)
from ocr_auto_core_v02 import (append_journal, event_key, extract_regional_fields, readiness)
from verification_ledger_v03 import make_review


OCR_NEEDS_RETRY = {'OCR_UNAVAILABLE', 'OCR_TIMEOUT', 'OCR_FAILED'}


def find_tesseract(selected):
    """Return executable and a factual diagnostic. This is NOT an OCR success signal."""
    import os
    exe = str(selected or '').strip().strip('"')
    choices = [exe, shutil.which('tesseract') or '',
               r'C:\Program Files\Tesseract-OCR\tesseract.exe',
               str(Path(os.environ.get('LOCALAPPDATA', '')) / 'Tesseract-OCR' / 'tesseract.exe')]
    for choice in choices:
        if not choice: continue
        is_path = bool(Path(choice).is_file())
        if not is_path and not shutil.which(choice): continue
        try:
            result = subprocess.run([choice, '--list-langs'], capture_output=True,
                                    text=True, timeout=7)
        except (OSError, subprocess.TimeoutExpired): continue
        if result.returncode != 0:
            return choice, 'OCR ENGINE ERROR: ' + (result.stderr or '')[-150:]
        langs = set(result.stdout.splitlines()) | set(result.stderr.splitlines())
        missing = sorted({'fas', 'eng'} - langs)
        if missing:
            return choice, f"OCR SETUP REQUIRED: missing {', '.join(missing)} traineddata (available: {', '.join(sorted(langs))[:90]})"
        return choice, 'OCR READY (fas+eng)'
    return exe or 'tesseract', 'OCR NOT INSTALLED: locate tesseract.exe and fas/eng.traineddata'


def success_keys(journal):
    """Resume only true regional checks; missing engine is NOT counted as success."""
    latest = {}
    if Path(journal).is_file():
        for line in Path(journal).read_text(encoding='utf-8').splitlines():
            try: x=json.loads(line)
            except ValueError: continue
            if x.get('event_key'):latest[x['event_key']]=x
    return {key for key,x in latest.items() if x.get('processing_status') == 'COMPLETED' and
            x.get('evidence',{}).get('complete') and
            len(x.get('evidence',{}).get('fields',[])) >= 2 and
            all(str(f.get('ocr_status','')).startswith('OCR_OK') for f in x['evidence']['fields'])}


class CardSourceWorkbench(CardVerificationDashboard):
    def __init__(self, root, **kwargs):
        self._draft_ready = False
        self._draft_approval_sig = None
        self._manual_future = None
        self._new_ui_ready = False
        super().__init__(root, **kwargs)
        root.title('Adaptive Reader — General Doc Source Workbench v0.4')
        self.all_queue = list(self.queue)
        self.draft_dir = self.run_dir / 'source_verification' / 'field_drafts_v04'
        self.export_dir = self.run_dir / 'source_verification' / 'exports_v04'
        self.scope_var = tk.StringVar(value='Outgoing (our letters)')
        self.stage_var = tk.StringVar(value='1. Select a General Doc source PDF')
        self.ocr_ready_var = tk.StringVar(value='OCR engine: checking…')
        self.ocr_result_var = tk.StringVar(value='Date: not read  |  Reference: not read')
        self.box_state_var = tk.StringVar(value='Field boxes: no source opened')
        self.confirm_date_var = tk.StringVar(value='')
        self.confirm_ref_var = tk.StringVar(value='')
        self.show_advanced = tk.BooleanVar(value=False)
        self.ocr_exe, diagnostic = find_tesseract(self.tesseract)
        self.tesseract = self.ocr_exe
        self.ocr_ready = diagnostic.startswith('OCR READY')
        self.ocr_ready_var.set(diagnostic + '  |  ' + self.tesseract)
        self.completed = success_keys(self.journal)
        self._hide_legacy_chrome()
        self._build_guided_ui()
        self.ledger_table.configure(height=5)  # give the PDF canvas more vertical space
        self._new_ui_ready = True
        self.change_scope()
        self.root.after(100, self._restore_initial_selection)

    def _hide_legacy_chrome(self):
        self.legacy_chrome = []
        self.ledger_frame = None
        for child in self.root.pack_slaves():
            if isinstance(child, ttk.LabelFrame):
                title=child.cget('text')
                if title.startswith('GENERAL DOC VERIFICATION LEDGER'):
                    self.ledger_frame=child
                    # The table/filter remain. Hide the five old action buttons.
                    children=child.pack_slaves()
                    if len(children)>1:children[1].pack_forget()
                    continue
                if title.startswith(('GENERAL DOC →','AUTO-RUN —')):
                    child.pack_forget();self.legacy_chrome.append(child)
            elif isinstance(child, ttk.Frame) and child is not self.notebook:
                # Native global 'Open/Save' and job lifecycle live here; stay in Advanced.
                child.pack_forget();self.legacy_chrome.append(child)
        # Keep Human Edit in focus; Detection Lab available via Advanced.
        try:self.notebook.hide(self.detect_tab)
        except tk.TclError:pass
        self.notebook.select(self.edit_tab)

    def _build_guided_ui(self):
        outer=ttk.LabelFrame(self.root, text='GENERAL DOC → SOURCE → TEACH → OCR → CONFIRM → EXPORT', padding=7)
        outer.pack(fill=tk.X, before=self.ledger_frame or self.notebook)
        self.guide_frame=outer
        a=ttk.Frame(outer);a.pack(fill=tk.X,pady=2)
        ttk.Label(a,text='Document direction:').pack(side=tk.LEFT)
        selector=ttk.Combobox(a, state='readonly', textvariable=self.scope_var,
                              values=list(SCOPES),width=25)
        selector.pack(side=tk.LEFT,padx=5)
        selector.bind('<<ComboboxSelected>>',lambda e:self.change_scope())
        ttk.Label(a, textvariable=self.stage_var,foreground='#155980').pack(side=tk.LEFT,fill=tk.X,expand=True,padx=12)
        ttk.Checkbutton(a,text='Advanced',variable=self.show_advanced,
                        command=self.toggle_advanced).pack(side=tk.RIGHT,padx=4)
        b=ttk.Frame(outer);b.pack(fill=tk.X,pady=3)
        ttk.Button(b,text='1  OPEN SELECTED PDF',command=self.open_ledger_selected).pack(side=tk.LEFT,padx=3)
        ttk.Button(b,text='2  DRAW DATE',command=lambda:self.choose_field('letter_date')).pack(side=tk.LEFT,padx=3)
        ttk.Button(b,text='DRAW REFERENCE',command=lambda:self.choose_field('letter_reference')).pack(side=tk.LEFT,padx=3)
        ttk.Button(b,text='3  APPROVE BOXES',command=self.save_and_learn).pack(side=tk.LEFT,padx=6)
        ttk.Label(outer,textvariable=self.box_state_var,foreground='#78532b').pack(anchor='w',padx=4)
        c=ttk.Frame(outer);c.pack(fill=tk.X,pady=3)
        ttk.Button(c,text='4  READ OCR + COMPARE',command=self.ocr_current).pack(side=tk.LEFT,padx=3)
        ttk.Label(c,textvariable=self.ocr_ready_var,foreground='#6b4c25').pack(side=tk.LEFT,padx=9)
        ttk.Label(outer,textvariable=self.ocr_result_var,foreground='#155980',wraplength=1300,
                  justify=tk.LEFT).pack(fill=tk.X,anchor='w',padx=5,pady=2)
        d=ttk.Frame(outer);d.pack(fill=tk.X,pady=3)
        ttk.Label(d,text='5  PDF date:').pack(side=tk.LEFT)
        ttk.Entry(d,textvariable=self.confirm_date_var,width=18).pack(side=tk.LEFT,padx=3)
        ttk.Label(d,text='PDF reference:').pack(side=tk.LEFT,padx=(8,0))
        ttk.Entry(d,textvariable=self.confirm_ref_var,width=26).pack(side=tk.LEFT,padx=3)
        ttk.Button(d,text='CONFIRM SOURCE VALUES',command=self.confirm_source).pack(side=tk.LEFT,padx=9)
        ttk.Label(d,text='(Type what you SEE in PDF, never copy a machine guess)',
                  foreground='#6b4c25').pack(side=tk.LEFT)
        e=ttk.Frame(outer);e.pack(fill=tk.X,pady=4)
        self.guided_start=ttk.Button(e,text='▶ START AUTO-RUN',command=self.start_autorun)
        self.guided_start.pack(side=tk.LEFT,padx=3)
        self.guided_stop=ttk.Button(e,text='■ STOP',command=self.stop_autorun,state='disabled')
        self.guided_stop.pack(side=tk.LEFT,padx=3)
        ttk.Button(e,text='NEXT SOURCE',command=self.next_unchecked).pack(side=tk.LEFT,padx=4)
        ttk.Button(e,text='EXPORT JSON + CSV',command=self.export_outputs).pack(side=tk.RIGHT,padx=3)
        ttk.Label(e,textvariable=self.auto_status).pack(side=tk.LEFT,fill=tk.X,expand=True,padx=9)
        self.manual_note=ttk.Label(outer,text='Status: source values not yet confirmed',foreground='#964128')
        self.manual_note.pack(anchor='w',padx=5)

    def _restore_initial_selection(self):
        if not self.ledger_table.get_children():return
        # Original v0.3 initial card may point to incoming record; don't open until user chooses.
        if not self._selected_key():
            first=self.ledger_table.get_children()[0]
            self.ledger_table.selection_set(first)
            self.ledger_table.see(first)
        self._render_ledger_choice()
        self.ledger_table.bind('<<TreeviewSelect>>',lambda e:self._render_ledger_choice(),add='+')

    def _render_ledger_choice(self):
        row=self._selected_row()
        if not row:return
        self.confirm_date_var.set((row.get('review') or {}).get('manual',{}).get('letter_date',''))
        self.confirm_ref_var.set((row.get('review') or {}).get('manual',{}).get('letter_reference',''))
        self._update_result_preview(row)

    def _update_result_preview(self, row):
        pieces=[]
        for field,label in [('letter_date','DATE'),('letter_reference','REFERENCE')]:
            observation=next((f for f in ((row.get('evidence') or {}).get('evidence') or {}).get('fields',[])
                              if f.get('field') == field),{})
            guess=row['reconstructions'][field]
            values=', '.join(x['value'] for x in guess['independent_candidates']) or '—'
            pieces.append(f"{label}: Logbook [{row['date_expected'] if field=='letter_date' else row['reference_expected']}]  "
                          f"PDF candidates [{values}]  |  Native [{observation.get('native_text','')[:35]}]  "
                          f"OCR [{observation.get('ocr_text','')[:35]}] ({observation.get('ocr_status','NOT_RUN')})")
        self.ocr_result_var.set('\n'.join(pieces))
        self.manual_note.configure(text=f"Tracking: {row['status']}  /  Source review: {row['review_status']}",
                                   foreground='#206b49' if row['status']=='VERIFIED_CORRECT' else '#964128')

    def change_scope(self):
        if getattr(self,'running',False) or (self._manual_future and not self._manual_future.done()):
            messagebox.showwarning('Processing active','Stop processing before changing direction.')
            return
        self.queue=scoped(self.all_queue,self.scope_var.get());self.cursor=0
        self.progress['maximum']=max(1,len(self.queue));self.progress['value']=0
        self.refresh_ledger()
        self.stage_var.set(f"{len(self.queue)} {self.scope_var.get()} General Doc correspondence entries")
        self._restore_initial_selection()

    def toggle_advanced(self):
        if self.show_advanced.get():
            for bar in self.legacy_chrome[:2]:
                bar.pack(fill=tk.X,before=self.guide_frame)
            try:self.notebook.add(self.detect_tab,text='Detection Lab')
            except tk.TclError:pass
        else:
            for bar in self.legacy_chrome[:2]:bar.pack_forget()
            try:self.notebook.hide(self.detect_tab)
            except tk.TclError:pass
            self.notebook.select(self.edit_tab)

    def _persist_current_drawings(self):
        if not self._draft_ready or not self.path or self.rgb is None:return
        boxes=self._boxes()
        rectangles={f:items[0].bbox for f,items in boxes.items() if len(items)==1}
        # Persist even empty boxes: removing a drawing must not resurrect it on reopening.
        h,w=self.rgb.shape[:2]
        try:
            _,data=save_draft(self.draft_dir,self.path,self.family_var.get(),rectangles,w,h,
                              prior_approval=self._draft_approval_sig,page=1)
        except (OSError,ValueError) as exc:
            self.box_state_var.set('Could not save drawing: '+str(exc)[:110]);return
        self._draft_approval_sig=data.get('approved_box_signature')
        self.box_state_var.set(f"{Path(self.path).name}: {len(rectangles)} saved box(es)  |  " +
                               ('APPROVED teaching example' if self._draft_approval_sig else 'DRAFT — not approved'))

    def snapshot_current_page(self):
        super().snapshot_current_page()
        if getattr(self,'_draft_ready',False) and self.page_index == 0:
            self._persist_current_drawings()

    def open_selected_source(self):
        if self._draft_ready:self._persist_current_drawings()
        self._draft_ready=False
        self._draft_approval_sig=None
        try:
            super().open_selected_source()
            if self.path is None or self.rgb is None:return
            h,w=self.rgb.shape[:2]
            previous=load_draft(self.draft_dir,self.path,self.family_var.get(),w,h,page=1)
            if previous:
                self.regions=[];self.groups={};self.layer_order=[];self.selected_id=None
                for field,box in previous['boxes'].items():
                    self.add_region('form_field',box,source='saved_file_drawing',confidence=1.0,
                                    role='EXTRACT:'+field,modified=True)
                self.refresh_layer_tree();self.redraw_edit();self.snapshot_current_page()
                self._draft_approval_sig=previous['data'].get('approved_box_signature')
                self.box_state_var.set(f"RESTORED drawings from this exact PDF  |  " +
                                       ('APPROVED' if self._draft_approval_sig else 'DRAFT'))
            self._draft_ready=True
            self._persist_current_drawings()
            if self.page_index==0:self.notebook.select(self.edit_tab)
        finally:
            self._draft_ready=bool(self.path and self.rgb is not None)

    def choose_field(self, field):
        if self.running:return
        if self.doc is None:
            self.open_ledger_selected()
            if self.doc is None:return
        # Mark existing matching region rather than forcing another drawing.
        boxes=self._boxes()
        if len(boxes.get(field,[]))==1:
            self.select_region(boxes[field][0].id)
            self.edit_mode='select'
            self.redraw_edit()
            self.stage_var.set(f"Field {field} selected. Drag/resize existing box, or delete it to redraw.")
            return
        super().choose_field(field)
        self.stage_var.set(f"Draw one tight {field} region; the drawing is saved for this PDF automatically.")

    def save_and_learn(self):
        if not self.path or self.rgb is None:
            messagebox.showwarning('No PDF','First open the selected source PDF.');return
        boxes=self._boxes()
        if any(len(boxes.get(f,[]))!=1 for f in REQUIRED):
            messagebox.showwarning('Two fields required','Draw one date box and one reference box.');return
        h,w=self.rgb.shape[:2]
        all_boxes={f:parts[0].bbox for f,parts in boxes.items() if len(parts)==1}
        sig=signature(normalise_rects(all_boxes,w,h))
        if sig==self._draft_approval_sig:
            self.stage_var.set('Field locations for this file are ALREADY APPROVED. OCR or move on.')
            return
        if not messagebox.askyesno('APPROVE FIELD LOCATIONS FOR FAMILY',
             'Approve the DATE and REFERENCE box positions on this source PDF as a reusable training example?\n\n'
             'This teaches box locations only; it does NOT approve OCR readings or change General Doc.'):
            return
        original=self.regions;original_order=self.layer_order
        try:
            selected=[parts[0] for parts in boxes.values()]
            for r in selected:r.user_modified=True
            self.regions=selected;self.layer_order=[r.id for r in selected]
            native.App.save_and_learn(self)
        finally:
            self.regions=original;self.layer_order=original_order
            self.refresh_layer_tree();self.redraw_edit()
        self._draft_approval_sig=sig
        self.snapshot_current_page()
        self.box_state_var.set('APPROVED: field positions learned; no need to label this file again.')
        self.stage_var.set('3. Field locations approved. Now READ OCR + COMPARE.')

    def _current_item(self):
        row=self._selected_row()
        if row and row['item']['event_key'] in {q['event_key'] for q in self.queue}:
            return row['item']
        return None

    def _read_fields_for_item(self,item):
        if self.path != item['path']:
            self._set_selected(item)
        if self.rgb is None or self.doc is None:return None
        self._persist_current_drawings()
        boxes=self._boxes()
        if any(len(boxes.get(f,[]))!=1 for f in REQUIRED):
            messagebox.showwarning('Box location missing','Teach date and reference once; approve the locations.')
            return None
        h,w=self.rgb.shape[:2];page=self.doc[0]
        field_boxes={f:[b*page.rect.width/w if k%2==0 else b*page.rect.height/h
                         for k,b in enumerate(boxes[f][0].bbox)] for f in REQUIRED}
        return field_boxes

    def ocr_current(self):
        if self.running or (self._manual_future and not self._manual_future.done()):return
        if not self.ocr_ready:
            messagebox.showwarning('OCR not ready', self.ocr_ready_var.get() +
                '\n\nFix Tesseract executable / fas+eng models before reading. A missing OCR result is not verification.')
            self.stage_var.set('OCR SETUP REQUIRED — see engine diagnostic above')
            return
        item=self._current_item()
        if item is None:
            messagebox.showwarning('No entry selected','Select a source event from the ledger first.');return
        if item['locator']!='SINGLE_CANDIDATE':
            messagebox.showwarning('Missing source','This General Doc event has no unique source PDF.');return
        boxmap=self._read_fields_for_item(item)
        if boxmap is None:return
        self.active_item=item
        self.auto_stop.clear()
        expected={'letter_date':item['event']['date'],'letter_reference':item['event']['reference']}
        self.stage_var.set('4. OCR RUNNING — reading only the date and reference crops…')
        self._manual_future=self.worker.submit(extract_regional_fields,item['path'],boxmap,expected,
                                                self.tesseract,'fas+eng',7,300,self.auto_stop)
        def poll():
            if not self._manual_future.done():self.root.after(120,poll);return
            try: output=self._manual_future.result()
            except Exception as exc:output={'complete':False,'reason':'OCR_ERROR: '+str(exc)[:150], 'fields':[]}
            self._manual_future=None
            statuses=[f.get('ocr_status','') for f in output.get('fields',[])]
            healthy=bool(output.get('complete')) and len(statuses)>=2 and all(x=='OCR_OK' for x in statuses)
            self._audit(item,output,'COMPLETED' if healthy else 'NEEDS_REVIEW')
            if output.get('complete'):
                statuses=[f.get('ocr_status','') for f in output.get('fields',[])]
                if not all(x=='OCR_OK' for x in statuses):
                    self.stage_var.set('OCR DID NOT COMPLETE: '+', '.join(statuses)+'. Fix OCR setup and retry.')
                else:
                    self.stage_var.set('OCR executed; review the candidate or UNREADABLE outcome before confirming from the PDF.')
            else:self.stage_var.set('OCR NEEDS ATTENTION: '+output.get('reason','Unknown'))
            self.refresh_ledger(prefer_key=item['event_key'])
            row=self.row_lookup.get(item['event_key'])
            if row:self._update_result_preview(row)
        self.root.after(120,poll)

    def confirm_source(self):
        if self.running:return
        row=self._selected_row()
        if not row:return
        date=self.confirm_date_var.get().strip();ref=self.confirm_ref_var.get().strip()
        if not date and not ref:
            messagebox.showwarning('No source transcription','Read the PDF and type a date or reference first.');return
        if not row.get('evidence_hash'):
            messagebox.showwarning('OCR first','Read OCR + Compare first to tie your review to evidence.');return
        if hashlib.sha256(self.logbook_path.read_bytes()).hexdigest()!=self.logbook_start_hash:
            messagebox.showwarning('General Doc changed','Snapshot has changed: reload the workbench.');return
        path=row['item'].get('path')
        if not path or not path.is_file() or not self.path or Path(self.path).resolve()!=path.resolve():
            messagebox.showwarning('Wrong PDF','Open the selected source PDF and inspect the printed values.');return
        digest=hashlib.sha256()
        with path.open('rb') as fh:
            for block in iter(lambda:fh.read(2*1024*1024),b''):digest.update(block)
        if digest.hexdigest()!=(row['evidence'].get('evidence') or {}).get('pdf_sha256'):
            messagebox.showwarning('PDF changed','The PDF differs from the OCR evidence; OCR again.');return
        try:
            review=make_review(row,manual_date=date,manual_reference=ref)
        except ValueError as exc:
            messagebox.showwarning('Check transcription',str(exc));return
        result=review['field_decisions']
        if not messagebox.askyesno('CONFIRM SOURCE READING',
            f"PDF date: {date or '[not checked]'} — {result.get('letter_date','NOT_CHECKED')}\n"
            f"PDF reference: {ref or '[not checked]'} — {result.get('letter_reference','NOT_CHECKED')}\n\n"
            'Confirm that you READ these values directly from the PDF?\n'
            'This does not edit the General Doc or Cleaner.'):
            return
        append_journal(self.review_path,review)
        self.refresh_ledger(prefer_key=row['event_key'])
        self._update_result_preview(self.row_lookup[row['event_key']])
        self.stage_var.set('SOURCE REVIEW SAVED — Next source or export the ledger.')

    def next_unchecked(self):
        if self.running:return
        if self._draft_ready:self._persist_current_drawings()
        current=self._selected_key()
        rows=list(self.ledger_rows)
        start=next((i+1 for i,row in enumerate(rows) if row['event_key']==current),0)
        skip={'VERIFIED_CORRECT','VERIFIED_ERROR'}
        candidates=[r for r in rows[start:]+rows[:start] if r['status'] not in skip and r['item']['locator']=='SINGLE_CANDIDATE']
        if not candidates:
            self.stage_var.set('No unverified source events remain in this selected direction.');return
        row=candidates[0];key=row['event_key']
        if self.ledger_table.exists(key):
            self.ledger_table.selection_set(key);self.ledger_table.see(key)
        self.open_ledger_selected()
        self.stage_var.set('Next source opened. Review suggested boxes, then OCR.')

    def start_autorun(self):
        if not self.ocr_ready:
            messagebox.showwarning('OCR not ready',self.ocr_ready_var.get() + '\nSet up Tesseract before Auto-Run.')
            self.stage_var.set('Auto-Run blocked: OCR engine not ready')
            return
        if self._manual_future and not self._manual_future.done():
            messagebox.showwarning('OCR active','Finish or stop current OCR before starting the loop.');return
        self.completed=success_keys(self.journal)
        self.cursor=0
        super().start_autorun()
        if self.running:
            self.guided_start.config(state='disabled');self.guided_stop.config(state='normal')
            self.stage_var.set(f"AUTO-RUN active for {self.scope_var.get()} — errors will enter review queue.")

    def _ready_for_auto(self, boxes, meta):
        # Manually approved locations on this EXACT document do not require transferred ORB alignment.
        if self._draft_approval_sig and self.rgb is not None:
            h,w=self.rgb.shape[:2]
            b={f:rr[0].bbox for f,rr in boxes.items() if len(rr)==1}
            if all(f in b for f in REQUIRED) and signature(normalise_rects(b,w,h))==self._draft_approval_sig:
                return True,'APPROVED_SOURCE_BOXES'
        return readiness(boxes,meta,self.require_alignment.get(),self.min_inliers.get())

    def _step(self):
        """v0.2 OCR loop with scope, stop, retry, and on-source approval support."""
        if not self.running:return
        if self.pending is not None:
            if not self.pending.done():
                self.root.after(100,self._step);return
            try:output=self.pending.result()
            except Exception as exc:output={'complete':False,'reason':'OCR_ERROR: '+str(exc)[:150],'fields':[]}
            self.pending=None
            item=self.active_item
            if output.get('reason')=='STOPPED':
                self._stop_state('Stopped during OCR; unfinished file retained for retry');return
            statuses=[f.get('ocr_status','') for f in output.get('fields',[])]
            healthy=bool(output.get('complete')) and len(statuses)>=2 and all(x=='OCR_OK' for x in statuses)
            self._audit(item,output,'COMPLETED' if healthy else 'NEEDS_REVIEW')
            if healthy:
                self.completed.add(item['event_key']);self.auto_processed+=1
                if any(f.get('needs_review') for f in output.get('fields', [])):
                    self.auto_review+=1
            else:self.auto_review+=1
            verdict=' / '.join(f.get('result','?') for f in output.get('fields',[])) or output.get('reason','OCR_UNAVAILABLE')
            if not healthy:verdict='REVIEW: '+verdict+' / '+','.join(statuses)
            elif any(f.get('needs_review') for f in output.get('fields', [])):
                verdict+=' [REVIEW]'
            self._show(item,verdict);self.cursor+=1
            if any(st.startswith(('OCR_UNAVAILABLE', 'OCR_FAILED', 'OCR_TIMEOUT')) for st in statuses):
                self._stop_state('PAUSED: OCR engine failure. Fix the engine and retry; this record is not completed.')
                return
            row=self.row_lookup.get(item['event_key'])
            if row:self._update_result_preview(row)
        if self.auto_stop.is_set():self._stop_state('Stopped by operator');return
        while self.cursor<len(self.queue):
            item=self.queue[self.cursor]
            if item['event_key'] in self.completed:self.cursor+=1;continue
            if item['locator']!='SINGLE_CANDIDATE' or not item['path'] or not item['path'].is_file():
                self._audit(item,{'reason':item['locator']},'LOCATOR_REVIEW')
                self.auto_skipped+=1;self._show(item,item['locator']);self.cursor+=1;continue
            try:self._set_selected(item)
            except Exception as exc:
                self._audit(item,{'reason':'PDF_OPEN_FAILED: '+str(exc)[:150]},'NEEDS_REVIEW')
                self.auto_review+=1;self._show(item,'PDF_OPEN_FAILED');self.cursor+=1;continue
            self.active_item=item
            boxes=self._boxes();meta=self.proposal_origin.get(self.page_index,{})
            ok,why=self._ready_for_auto(boxes,meta)
            if not ok:
                self.auto_review+=1;self._show(item,why)
                self._stop_state('PAUSED: field boxes not ready. Teach/approve this source; restart Auto-Run.')
                return
            h,w=self.rgb.shape[:2];page=self.doc[0]
            field_boxes={f:[b*page.rect.width/w if k%2==0 else b*page.rect.height/h
                            for k,b in enumerate(boxes[f][0].bbox)] for f in REQUIRED}
            expected={'letter_date':item['event']['date'],'letter_reference':item['event']['reference']}
            self.pending=self.worker.submit(extract_regional_fields,item['path'],field_boxes,expected,
                                            self.tesseract,'fas+eng',7,300,self.auto_stop)
            self.stage_var.set(f"AUTO-RUN OCR: {item['path'].name} ({self.cursor+1}/{len(self.queue)})")
            self.root.after(100,self._step)
            return
        self._stop_state('Selected direction completed')

    def _stop_state(self,msg):
        super()._stop_state(msg)
        if self._new_ui_ready:
            self.guided_start.config(state='normal');self.guided_stop.config(state='disabled')
            self.stage_var.set(msg)

    def stop_autorun(self):
        self.auto_stop.set()
        if self.running:super().stop_autorun()
        else:self.stage_var.set('Stop requested; current OCR will be cancelled.')

    def export_outputs(self):
        self.refresh_ledger()
        scope=SCOPES[self.scope_var.get()]
        dest=self.export_dir / scope
        files=export_machine_results(self.ledger_rows,dest,
                                     run_dir=self.run_dir,scope=scope)
        self.stage_var.set(f"EXPORT SAVED: {len(self.ledger_rows)} events → {dest}")
        messagebox.showinfo('JSON + CSV ready','\n'.join(str(p) for p in files) +
                            '\n\nMachine suggestions remain unverified. Source PDFs/General Doc unchanged.')

    def close_window(self):
        if self._draft_ready:self._persist_current_drawings()
        if self._manual_future and not self._manual_future.done():
            self.auto_stop.set()
            messagebox.showinfo('Stopping OCR','Stop requested. Close again once the OCR finishes.');return
        super().close_window()


def main():
    p=argparse.ArgumentParser(description='General Doc source verification workbench v0.4')
    p.add_argument('--run-dir',type=Path,required=True)
    p.add_argument('--source-root',type=Path,required=True)
    p.add_argument('--focus-ref',default='1404/ES/S/3003')
    p.add_argument('--tesseract',default='tesseract')
    a=p.parse_args()
    if not (a.run_dir/'board_to_log.json').is_file():p.error('Missing board_to_log.json snapshot')
    if not a.source_root.is_dir():p.error('Missing source root (technical directory containing send/recive)')
    root=tk.Tk()
    CardSourceWorkbench(root,run_dir=a.run_dir,source_root=a.source_root,
                        focus_ref=a.focus_ref,tesseract=a.tesseract)
    root.mainloop()

if __name__=='__main__':main()
