"""v0.3 append-only verification dashboard over the existing v0.2 OCR loop.

Installation: drop new files in original Cleaner tree, preserve v0.1/v0.2.
"""
from __future__ import annotations

import argparse
import hashlib
from datetime import datetime
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

from card_teaching_autorun_v02 import CardTeachingAutoApp
from verification_ledger_v03 import (build_ledger, make_review, overview, export_csv)
from ocr_auto_core_v02 import append_journal


class CardVerificationDashboard(CardTeachingAutoApp):
    def __init__(self, root, **kwargs):
        super().__init__(root, **kwargs)
        self.root.title('Adaptive Reader — General Doc Source Verification / OCR / Review')
        self.review_path = self.run_dir / 'source_verification' / 'card_verification_reviews_v03.jsonl'
        self.ledger_dir = self.run_dir / 'source_verification'
        self.ledger_rows = []
        self.row_lookup = {}
        self.ledger_filter = tk.StringVar(value='All')
        self.summary_var = tk.StringVar(value='Loading source verification ledger…')
        self.ledger_note = tk.StringVar(value='General Doc values come from this run\'s board_to_log.json snapshot, not live Excel. Machine matches are unverified.')
        self.logbook_path = self.run_dir / 'board_to_log.json'
        self.logbook_start_hash = hashlib.sha256(self.logbook_path.read_bytes()).hexdigest()
        frame = ttk.LabelFrame(root, text='GENERAL DOC VERIFICATION LEDGER — SOURCE / OCR / HUMAN REVIEW',padding=6)
        frame.pack(fill=tk.BOTH, expand=False, before=self.notebook)
        first=ttk.Frame(frame);first.pack(fill=tk.X)
        ttk.Label(first, textvariable=self.summary_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Label(first, text='Filter:').pack(side=tk.LEFT, padx=3)
        filt=ttk.Combobox(first, values=['All','Not checked','Needs review','Possible errors',
                                         'Human verified','Machine candidates','Missing source'],
                          state='readonly',textvariable=self.ledger_filter,width=20)
        filt.pack(side=tk.LEFT);filt.bind('<<ComboboxSelected>>',lambda e:self._refresh_table())
        cmds=ttk.Frame(frame);cmds.pack(fill=tk.X,pady=3)
        ttk.Button(cmds, text='Open selected PDF',command=self.open_ledger_selected).pack(side=tk.LEFT,padx=2)
        ttk.Button(cmds, text='Inspect OCR evidence',command=self.inspect_evidence).pack(side=tk.LEFT,padx=2)
        ttk.Button(cmds, text='Record what I read in PDF',command=self.record_human_reading).pack(side=tk.LEFT,padx=2)
        ttk.Button(cmds, text='Refresh ledger',command=self.refresh_ledger).pack(side=tk.LEFT,padx=2)
        ttk.Button(cmds, text='Export CSV',command=self.export_ledger).pack(side=tk.LEFT,padx=2)
        ttk.Label(frame, textvariable=self.ledger_note,foreground='#6a532f').pack(anchor='w',pady=(0,4))
        columns=('card','pdf','date_entry','date_read','date_status','ref_entry','ref_read','ref_status','overall')
        row=ttk.Frame(frame);row.pack(fill=tk.BOTH,expand=True)
        self.ledger_table=ttk.Treeview(row,columns=columns,show='headings',height=9,selectmode='browse')
        titles={'card':'General Doc card','pdf':'Source PDF','date_entry':'Entry: date',
                'date_read':'Read: date','date_status':'Date comparison','ref_entry':'Entry: reference',
                'ref_read':'Read: reference','ref_status':'Reference comparison','overall':'Tracking status'}
        widths={'card':165,'pdf':145,'date_entry':105,'date_read':110,'date_status':175,
                'ref_entry':150,'ref_read':160,'ref_status':205,'overall':215}
        for col in columns:
            self.ledger_table.heading(col,text=titles[col]);self.ledger_table.column(col,width=widths[col],stretch=False)
        vsb=ttk.Scrollbar(row,orient='vertical',command=self.ledger_table.yview)
        hsb=ttk.Scrollbar(row,orient='horizontal',command=self.ledger_table.xview)
        self.ledger_table.configure(yscrollcommand=vsb.set,xscrollcommand=hsb.set)
        row.grid_columnconfigure(0,weight=1);row.grid_rowconfigure(0,weight=1)
        self.ledger_table.grid(row=0,column=0,sticky='nsew')
        vsb.grid(row=0,column=1,sticky='ns');hsb.grid(row=1,column=0,sticky='ew')
        self.ledger_table.tag_configure('verified',foreground='#197049')
        self.ledger_table.tag_configure('error',foreground='#ad3535')
        self.ledger_table.tag_configure('pending',foreground='#75622d')
        self.ledger_table.bind('<Double-1>',lambda e:self.open_ledger_selected())
        self.refresh_ledger()

    def _audit(self,item,payload,status):
        entry = super()._audit(item,payload,status)
        if hasattr(self,'ledger_table'):
            self.refresh_ledger(prefer_key=item['event_key'])
        return entry

    def refresh_ledger(self,prefer_key=None):
        prev=prefer_key or self._selected_key()
        self.ledger_rows=build_ledger(self.queue,self.journal,self.review_path)
        self.row_lookup={x['event_key']:x for x in self.ledger_rows}
        counts=overview(self.ledger_rows)
        self.summary_var.set(f"Cards {counts['CARDS_FULLY_VERIFIED']}/{counts['CARDS_TOTAL']} fully verified | "
                             f"Events {counts['HUMAN_VERIFIED']}/{counts['TOTAL']} reviewed | "
                             f"OCR {counts['OCR_PROCESSED']} | "
                             f"Verified errors {counts.get('VERIFIED_ERROR',0)} | "
                             f"Not started {counts.get('NOT_CHECKED',0)} | "
                             f"Needs attention {counts['REQUIRES_ATTENTION']}")
        self._refresh_table(select=prev)

    def _selected_key(self):
        if not hasattr(self,'ledger_table'):return None
        ids=self.ledger_table.selection()
        return ids[0] if ids else None

    def _selected_row(self):
        key=self._selected_key()
        return self.row_lookup.get(key) if key else None

    def _included(self,row):
        filt=self.ledger_filter.get();s=row['status']
        if filt=='All': return True
        if filt=='Not checked':return s=='NOT_CHECKED'
        if filt=='Human verified':return s in ('VERIFIED_CORRECT','VERIFIED_ERROR')
        if filt=='Machine candidates':return s=='MACHINE_MATCH_UNVERIFIED'
        if filt=='Missing source':return s in ('SOURCE_MISSING','SOURCE_AMBIGUOUS')
        if filt=='Possible errors':return s in ('VERIFIED_ERROR','POSSIBLE_MISMATCH','READER_CONFLICT')
        if filt=='Needs review':return s not in ('VERIFIED_CORRECT','VERIFIED_ERROR','MACHINE_MATCH_UNVERIFIED','NOT_CHECKED')
        return True

    def _refresh_table(self,select=None):
        for rid in self.ledger_table.get_children():self.ledger_table.delete(rid)
        for row in self.ledger_rows:
            if not self._included(row):continue
            key=row['event_key']; ev=row['item']['event']; d=row['reconstructions'];f=row['field_status']
            def read(field):
                return ' / '.join(dict.fromkeys(v['value'] for v in d[field]['independent_candidates'])) or '—'
            card=row['card']
            tag = ('verified' if row['status']=='VERIFIED_CORRECT' else
                   'error' if row['status'] in ('VERIFIED_ERROR','STALE_REVIEW') else
                   'pending')
            self.ledger_table.insert('',tk.END,iid=key,tags=(tag,),values=(
                f"{card.get('sheet','')}#{card.get('index','')}",
                Path(row['source_path']).name if row['source_path'] else '—',
                row['date_expected'],read('letter_date'),f['letter_date'],
                row['reference_expected'],read('letter_reference'),f['letter_reference'],row['status']))
        if select and self.ledger_table.exists(select):
            self.ledger_table.selection_set(select);self.ledger_table.see(select)

    def open_ledger_selected(self):
        if self.running:
            messagebox.showinfo('Auto-Run active','Stop Auto-Run before manually opening a different source PDF.')
            return
        row=self._selected_row()
        if row is None:return
        if row['item']['locator']!='SINGLE_CANDIDATE' or not row['item']['path'] or not row['item']['path'].is_file():
            messagebox.showwarning('Source not resolved','A unique source PDF must be found before opening.');return
        try:
            self._set_selected(row['item'])
            self.ledger_note.set(f"Opened {Path(row['source_path']).name}: inspect actual date/reference in the PDF.")
        except Exception as exc: messagebox.showerror('Could not open PDF',str(exc))

    def inspect_evidence(self):
        row=self._selected_row()
        if row is None:return
        snap=row.get('evidence') or {}
        fields=(snap.get('evidence') or {}).get('fields') or []
        lines=[f"General Doc card: {row['card'].get('sheet')} / {row['card'].get('index')}",
               f"PDF: {row['source_path'] or '[not found]'}",f"Status: {row['status']}",
               f"Review: {row['review_status']}",'']
        for f in fields:
            label=f.get('field','?');recon=row['reconstructions'].get(label,{})
            lines.extend([label, f"  General Doc: {f.get('expected','')}",
                          f"  Raw native: {f.get('native_text','')}",
                          f"  Raw OCR: {f.get('ocr_text','')}",
                          f"  OCR state: {f.get('ocr_status','')}",
                          f"  Normalized candidates: {json.dumps(recon.get('independent_candidates',[]),ensure_ascii=False)}",
                          f"  Expected-guided hint (NOT evidence): {recon.get('expected_guided_hint')}",
                          f"  PDF box: {f.get('bbox_pdf')}",''])
        if not fields: lines.append('No successful regional OCR evidence. OCR this source first.')
        dialog=tk.Toplevel(self.root);dialog.title('Read-only OCR evidence — NOT independently verified')
        dialog.geometry('840x480')
        area=tk.Text(dialog,wrap='word',font=('Consolas',10));area.pack(fill='both',expand=True)
        area.insert('1.0','\n'.join(lines));area.configure(state='disabled')

    def record_human_reading(self):
        if self.running:
            messagebox.showinfo('Auto-Run active','Stop the automatic loop before reviewing individual documents.');return
        row=self._selected_row()
        if row is None:return
        if not row['evidence_hash']:
            messagebox.showwarning('Missing source evidence','Run OCR current source first, then review the PDF.')
            return
        if hashlib.sha256(self.logbook_path.read_bytes()).hexdigest() != self.logbook_start_hash:
            messagebox.showwarning('General Doc snapshot changed',
                'board_to_log.json has changed since this session started. Reopen the dashboard to refresh the card queue and expected values.')
            return
        path=row['item']['path']
        if not path or not path.is_file():
            messagebox.showwarning('Missing PDF','Source PDF is unavailable.');return
        # Verify the current PDF bytes match the source used for OCR.
        try:
            fingerprint=hashlib.sha256()
            with path.open('rb') as reader:
                for block in iter(lambda:reader.read(2*1024*1024),b''):
                    fingerprint.update(block)
            if fingerprint.hexdigest() != row['evidence']['evidence']['pdf_sha256']:
                messagebox.showwarning('Source PDF changed','The PDF differs from the OCR evidence. OCR this file again before confirming.')
                return
        except (OSError,KeyError) as exc:
            messagebox.showerror('Cannot verify PDF fingerprint',str(exc));return
        # The PDF must be open in this workspace; users cannot certify unseen content.
        if not self.path or str(Path(self.path).resolve()) != str(Path(path).resolve()):
            messagebox.showwarning('PDF not open','First select Open selected PDF, inspect the printed fields, then record what you read.')
            return
        date=simpledialog.askstring('Manual source reading — date',
            'Read the printed date directly from the PDF. Type it below.\nLeave blank to review only the reference.\nDo NOT copy the General Doc value without checking the PDF.',parent=self.root)
        if date is None:return
        ref=simpledialog.askstring('Manual source reading — reference',
            'Read the printed reference directly from the PDF. Type it below.\nLeave blank to review only the date.\nAbbreviated references will remain REVIEW REQUIRED.',parent=self.root)
        if ref is None:return
        note=simpledialog.askstring('Review note (optional)',
            'Optional evidence note (e.g. handwriting unclear, letterhead variation):',parent=self.root)
        if note is None:return
        try:
            review=make_review(row,manual_date=date,manual_reference=ref,note=note,
                               at=datetime.now().astimezone().isoformat(timespec='seconds'))
        except ValueError as exc:
            messagebox.showerror('Review not saved',str(exc));return
        decisions=review['field_decisions']
        if not messagebox.askyesno('Confirm source transcription',
            f"Date: {date or '[not reviewed]'} → {decisions.get('letter_date','NOT_REVIEWED')}\n"
            f"Reference: {ref or '[not reviewed]'} → {decisions.get('letter_reference','NOT_REVIEWED')}\n\n"
            'You are recording what is printed on the SOURCE PDF, not approving OCR guesses.\n'
            'This will NOT edit the General Doc or Cleaner. Save your decision?'):
            return
        append_journal(self.review_path,review)
        self.refresh_ledger(prefer_key=row['event_key'])
        self.ledger_note.set('Source review saved. If PDF, OCR evidence or General Doc expectation changes, review becomes stale.')

    def export_ledger(self):
        self.refresh_ledger()
        target=self.ledger_dir/'card_verification_ledger_v03.csv'
        try: export_csv(self.ledger_rows,target)
        except OSError as exc: messagebox.showerror('Export failed',str(exc));return
        messagebox.showinfo('Read-only ledger exported',str(target))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--run-dir',type=Path,required=True)
    parser.add_argument('--source-root',type=Path,required=True)
    parser.add_argument('--focus-ref',default='1404/ES/S/3003')
    parser.add_argument('--tesseract',default='tesseract')
    args=parser.parse_args()
    if not (args.run_dir/'board_to_log.json').is_file():parser.error('Missing board_to_log.json in run-dir')
    if not args.source_root.is_dir():parser.error('Missing source-root')
    root=tk.Tk()
    CardVerificationDashboard(root,run_dir=args.run_dir,source_root=args.source_root,
                              focus_ref=args.focus_ref,tesseract=args.tesseract)
    root.mainloop()

if __name__=='__main__':main()
