"""Field-learning workspace for General Doc cards using Adaptive Annotator v0.6.

Launch (from Cleaner root):
  python tools/adaptive_document_reader/card_teaching_workspace_v01.py
    --run-dir runs/azd_20261014T071802 --source-root C:/data/technical

All source PDF operations are read-only. Suggestions are never approved facts.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

import adaptive_document_annotator_v0_6 as native
from card_teaching_core import load_card_queue, pdf_index, locate_candidates, compare_field

FAMILIES = {"send": "OFFICIAL_OUTGOING_LETTER_FIELDS_v01",
            "receive": "CONSULTANT_INCOMING_LETTER_FIELDS_v01"}
DEFAULT_FIELDS = ("letter_date", "letter_reference")


class CardTeachingApp(native.App):
    def __init__(self, root, *, run_dir: Path, source_root: Path, focus_ref="", tesseract="tesseract"):
        super().__init__(root)
        self.root.title("Adaptive Reader — General Doc Card Teaching")
        self.run_dir = run_dir
        self.source_root = source_root
        self.tesseract = tesseract
        logbook = run_dir / "board_to_log.json"
        self.cards = load_card_queue(logbook)
        self.index = pdf_index(source_root)
        self.selection_items = []
        self.current_event = None
        self.user_approved_pages = set()
        self.proposal_origin = {}
        self.review_output = run_dir / "source_verification" / "card_field_trials.jsonl"
        self.card_var = tk.StringVar()
        self.letter_var = tk.StringVar()
        self.teaching_var = tk.StringVar(value="Choose a card and source letter; mark date and reference fields.")
        self.card_labels = [f"{c['sheet']} | {c['index']} | {c['name']}" for c in self.cards]
        self.card_lookup = {s:c for s,c in zip(self.card_labels,self.cards)}
        bar = ttk.LabelFrame(root, text="GENERAL DOC → SOURCE PDF → TEACH → SUGGEST → VERIFY", padding=5)
        bar.pack(fill=tk.X, before=self.notebook)
        a = ttk.Frame(bar); a.pack(fill=tk.X)
        ttk.Label(a, text="Card:").pack(side=tk.LEFT)
        combo = ttk.Combobox(a, textvariable=self.card_var, values=self.card_labels, width=66, state="readonly")
        combo.pack(side=tk.LEFT, padx=4)
        combo.bind("<<ComboboxSelected>>", lambda e: self.refresh_card())
        ttk.Label(a, text="Source:").pack(side=tk.LEFT)
        source = ttk.Combobox(a, textvariable=self.letter_var, width=68, state="readonly")
        source.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        self.source_combo = source
        ttk.Button(a, text="Open source PDF", command=self.open_selected_source).pack(side=tk.LEFT, padx=3)
        b = ttk.Frame(bar); b.pack(fill=tk.X, pady=4)
        ttk.Button(b, text="1  Teach date", command=lambda:self.choose_field("letter_date")).pack(side=tk.LEFT, padx=3)
        ttk.Button(b, text="2  Teach reference", command=lambda:self.choose_field("letter_reference")).pack(side=tk.LEFT, padx=3)
        ttk.Button(b, text="+ Other field", command=self.custom_field).pack(side=tk.LEFT, padx=3)
        ttk.Button(b, text="Evaluate extracted fields", command=self.evaluate_fields).pack(side=tk.LEFT, padx=8)
        ttk.Button(b, text="Approve boxes + learn", command=self.save_and_learn).pack(side=tk.LEFT, padx=3)
        ttk.Button(b, text="Next source", command=self.next_source).pack(side=tk.LEFT, padx=3)
        ttk.Label(bar, textvariable=self.teaching_var, foreground="#64522b").pack(anchor="w")
        if self.card_labels:
            chosen = next((label for label,c in zip(self.card_labels,self.cards) if
                           any(focus_ref and focus_ref in e.get("reference","") for e in c["events"])),self.card_labels[0])
            self.card_var.set(chosen)
            self.refresh_card()

    def refresh_card(self):
        card=self.card_lookup.get(self.card_var.get())
        if card is None: return
        self.selection_items=[]
        for ev in card["events"]:
            match=locate_candidates(ev,self.index)
            if not match["paths"]:
                self.selection_items.append((f"[NOT FOUND] {ev['direction']} {ev['reference']}",ev,None,match))
            else:
                for p in match["paths"]:
                    self.selection_items.append((f"[{match['status']}] {ev['direction']} {ev['reference']} → {Path(p).name}",ev,Path(p),match))
        self.source_combo.configure(values=[x[0] for x in self.selection_items])
        self.letter_var.set(self.selection_items[0][0] if self.selection_items else "")
        self.teaching_var.set(f"{card['name']} / WBS {card['wbs']} — {len(card['events'])} logged references; {len(self.selection_items)} locator entries")

    def current_selection(self):
        for item in self.selection_items:
            if item[0] == self.letter_var.get():
                return item
        return None

    def open_selected_source(self):
        item=self.current_selection()
        if not item or item[2] is None:
            messagebox.showwarning("Source unavailable","No matching PDF filename. Review the source file registry; don't invent a file.")
            return
        _,ev,path,match=item
        if not path.is_file():
            messagebox.showerror("Source unavailable",str(path));return
        if self.doc is not None: self.doc.close()
        self.path = path; self.is_pdf=True; self.doc=native.pymupdf.open(str(path))
        if not len(self.doc): raise ValueError("PDF has zero pages")
        self.page_index=0; self.page_states={}; self.user_approved_pages=set(); self.proposal_origin={}
        self.current_event=ev
        family=FAMILIES[ev["direction"]]
        self.family_var.set(family)
        self.load_page()
        self.prepare_proposals()

    def prepare_proposals(self):
        self.run_detection()  # reuse native ORB-aligned family memory
        self.send_to_edit()
        self.regions=[r for r in self.regions if r.role.startswith("EXTRACT:")]
        self.layer_order=[r.id for r in self.regions]
        self.selected_id=None
        meta=self.detection_result.get("template_meta",{}) if self.detection_result else {}
        self.proposal_origin[self.page_index]=meta
        self.refresh_layer_tree();self.redraw_edit();self.snapshot_current_page()
        self.teaching_var.set(
            f"{self.path.name} | suggestions={len(self.regions)} | template={meta.get('example') or 'none'} | "
            f"alignment={meta.get('alignment','none')} | proposals NOT VERIFIED"
        )

    def choose_field(self, field):
        if self.rgb is None:
            messagebox.showwarning("No document","Open a source PDF first");return
        self.layout_var.set("form_field")
        self.role_var.set("EXTRACT:"+field)
        if self.edit_mode != "draw":
            self.toggle_draw()
        self.notebook.select(self.edit_tab)
        self.status_var.set(f"Draw a tight rectangle around {field}; or select and edit its proposed box.")

    def custom_field(self):
        field=simpledialog.askstring("Add field","Field name (e.g. subject):",parent=self.root)
        if field and field.replace("_","").isalnum(): self.choose_field(field)

    def _boxes(self):
        boxes={}
        for r in self.regions:
            if r.role.startswith("EXTRACT:"):
                name=r.role.removeprefix("EXTRACT:")
                boxes.setdefault(name,[]).append(r)
        return boxes

    def evaluate_fields(self):
        if self.doc is None or self.current_event is None: return
        boxes=self._boxes()
        if not boxes:
            messagebox.showwarning("No fields","Draw date and reference rectangles first.")
            return
        results=[]
        for name,rr in boxes.items():
            if len(rr)!=1:
                results.append({"field":name,"result":"NEEDS_REVIEW_MULTIPLE_BOXES","count":len(rr)})
                continue
            r=rr[0]
            page=self.doc[self.page_index]
            h,w=self.rgb.shape[:2]
            factorx=page.rect.width/w; factory=page.rect.height/h
            bbox=native.pymupdf.Rect(r.bbox[0]*factorx,r.bbox[1]*factory,r.bbox[2]*factorx,r.bbox[3]*factory)
            native_text=page.get_text("text",clip=bbox,sort=True).strip()
            pix=page.get_pixmap(matrix=native.pymupdf.Matrix(3,3),clip=bbox,alpha=False)
            with tempfile.TemporaryDirectory() as temp:
                crop=Path(temp)/"field.png"; pix.save(str(crop))
                try:
                    p=subprocess.run([self.tesseract,str(crop),"stdout","-l","fas+eng","--psm","6"],
                                     capture_output=True,text=True,timeout=40)
                    ocr_text=p.stdout if p.returncode==0 else ""
                    ocr_state="OK" if p.returncode==0 else "OCR_FAILED"
                except (FileNotFoundError, subprocess.TimeoutExpired):
                    ocr_text="";ocr_state="OCR_UNAVAILABLE"
            expected=self.current_event.get("date" if name=="letter_date" else "reference","")
            entry=compare_field(name,native_text,ocr_text,expected) if name in DEFAULT_FIELDS else {
                "field":name,"result":"VALUE_REVIEW_REQUIRED","native_text":native_text,"ocr_text":ocr_text}
            entry.update({"page":self.page_index+1,"bbox_pdf":list(bbox),
                          "native_text":native_text[:500],"ocr_text":ocr_text[:500],"ocr_status":ocr_state})
            results.append(entry)
        envelope={"schema":"cleaner.card_field_trial/0.1","generated_at":datetime.now().isoformat(),
                  "card":{k:self.card_lookup[self.card_var.get()][k] for k in ("sheet","index","name","wbs")},
                  "source_pdf":str(self.path),"pdf_sha256":hashlib.sha256(self.path.read_bytes()).hexdigest(),
                  "source_event":self.current_event,"family":self.family_var.get(),
                  "template":self.proposal_origin.get(self.page_index,{}),"results":results,
                  "verified":False,"cleaner_written":False}
        self.review_output.parent.mkdir(parents=True,exist_ok=True)
        with self.review_output.open("a",encoding="utf-8") as f: f.write(json.dumps(envelope,ensure_ascii=False)+"\n")
        summary="; ".join(f"{x.get('field')}={x['result']}" for x in results)
        self.teaching_var.set(summary)
        messagebox.showinfo("Field evidence (not approved)",summary+"\n\nSaved: "+str(self.review_output))

    def save_and_learn(self):
        if self.rgb is None: return
        boxes=self._boxes()
        if any(len(v)!=1 for v in boxes.values()) or any(x not in boxes for x in DEFAULT_FIELDS):
            messagebox.showwarning("Incomplete teaching","Provide exactly one rectangle for each required field: date and reference.")
            return
        if not messagebox.askyesno("Approve field locations?",
            "Have you reviewed/corrected BOTH date and reference boxes on this page?\n\n"
            "Save locations as a TRAINING EXAMPLE for this family?\n"
            "This does not verify any extracted value or edit Cleaner data."):
            return
        orig_regions=self.regions; orig_order=self.layer_order
        try:
            selected=[v[0] for v in boxes.values()]
            for r in selected: r.user_modified=True
            self.regions=selected;self.layer_order=[r.id for r in selected]
            super().save_and_learn()
        finally:
            self.regions=orig_regions;self.layer_order=orig_order
            self.refresh_layer_tree();self.redraw_edit();self.snapshot_current_page()
        self.teaching_var.set(f"Approved example stored for {self.family_var.get()} — next file will receive field suggestions.")

    def next_page(self):
        before=self.page_index; super().next_page()
        if self.page_index != before:
            if self.page_index == 0 and self.page_index not in self.proposal_origin:
                self.prepare_proposals()
            elif self.page_index > 0:
                self.teaching_var.set("First-page field model only. Other pages: inspect manually; no automatic suggestion.")
    def prev_page(self):
        before=self.page_index; super().prev_page()
        if self.page_index != before and self.page_index == 0 and self.page_index not in self.proposal_origin:
            self.prepare_proposals()

    def next_source(self):
        idx=next((i for i,x in enumerate(self.selection_items) if x[0]==self.letter_var.get()),-1)
        if idx+1<len(self.selection_items):
            self.letter_var.set(self.selection_items[idx+1][0]);self.open_selected_source();return
        ci=self.card_labels.index(self.card_var.get()) if self.card_var.get() in self.card_labels else -1
        if ci+1<len(self.card_labels):
            self.card_var.set(self.card_labels[ci+1]);self.refresh_card()
            self.teaching_var.set("Next card selected. Open its source to continue teaching.")


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--run-dir",type=Path,required=True)
    p.add_argument("--source-root",type=Path,required=True)
    p.add_argument("--focus-ref",default="1404/ES/S/3003")
    p.add_argument("--tesseract",default="tesseract")
    args=p.parse_args()
    if not (args.run_dir/"board_to_log.json").exists():p.error("board_to_log.json not found in --run-dir")
    if not args.source_root.is_dir():p.error("--source-root not found")
    root=tk.Tk()
    app=CardTeachingApp(root,run_dir=args.run_dir,source_root=args.source_root,
                        focus_ref=args.focus_ref,tesseract=args.tesseract)
    root.mainloop()


if __name__=="__main__":main()
