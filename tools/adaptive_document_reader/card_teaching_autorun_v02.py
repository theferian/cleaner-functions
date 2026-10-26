"""OCR + Start/Stop unattended checking, extending Adaptive Card Teaching v0.1.

Only approved human examples train memory. Auto-run never writes back to Excel.
"""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import threading
import tkinter as tk
from tkinter import ttk, messagebox

from card_teaching_workspace_v01 import CardTeachingApp
from card_teaching_core import locate_candidates
from ocr_auto_core_v02 import (append_journal, event_key, extract_regional_fields,
                               load_completed, make_queue, readiness)


class CardTeachingAutoApp(CardTeachingApp):
    def __init__(self, root, **kwargs):
        super().__init__(root, **kwargs)
        self.root.title("Adaptive Reader — Teach Fields / Auto-Run OCR")
        self.auto_stop = threading.Event()
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="card-ocr")
        self.pending = None
        self.queue = make_queue(self.cards, self.index)
        self.cursor = 0
        self.running = False
        self.active_item = None
        self.journal = self.run_dir / "source_verification" / "card_field_autorun_v02.jsonl"
        self.completed = load_completed(self.journal)
        self.auto_processed = 0
        self.auto_review = 0
        self.auto_skipped = 0
        self.require_alignment = tk.BooleanVar(value=True)
        self.min_inliers = tk.IntVar(value=8)
        self.auto_status = tk.StringVar(value="Teach date/reference first; Start Auto-Run when ready.")
        bar = ttk.LabelFrame(root, text="AUTO-RUN — REGIONAL OCR / VERIFIED COMPARISON CANDIDATES", padding=5)
        bar.pack(fill=tk.X, before=self.notebook)
        row = ttk.Frame(bar); row.pack(fill=tk.X)
        self.start_btn = ttk.Button(row, text="▶ Start Auto-Run", command=self.start_autorun)
        self.start_btn.pack(side=tk.LEFT, padx=3)
        self.stop_btn = ttk.Button(row, text="■ Stop after current OCR", command=self.stop_autorun, state="disabled")
        self.stop_btn.pack(side=tk.LEFT, padx=3)
        ttk.Button(row, text="OCR current source", command=self.ocr_current).pack(side=tk.LEFT, padx=8)
        ttk.Button(row, text="Recheck all", command=self.recheck_all).pack(side=tk.LEFT, padx=4)
        ttk.Checkbutton(row, text="Require ORB alignment", variable=self.require_alignment).pack(side=tk.LEFT, padx=6)
        ttk.Label(row, text="Min inliers:").pack(side=tk.LEFT)
        ttk.Spinbox(row, from_=8, to=30, textvariable=self.min_inliers, width=4).pack(side=tk.LEFT)
        self.progress = ttk.Progressbar(row, mode="determinate", maximum=max(1, len(self.queue)), length=160)
        self.progress.pack(side=tk.LEFT, padx=8)
        ttk.Label(bar, textvariable=self.auto_status).pack(anchor="w")
        self.results = ttk.Treeview(bar, columns=("doc", "direction", "date", "ref", "outcome"),
                                    show="headings", height=5)
        for c, title, width in (("doc", "Document", 220), ("direction", "Side", 75),
                                ("date", "Date", 135), ("ref", "Reference", 160), ("outcome", "Result", 240)):
            self.results.heading(c, text=title); self.results.column(c, width=width, stretch=(c in ("doc", "outcome")))
        self.results.pack(fill=tk.X, pady=(4, 0))
        self.root.protocol("WM_DELETE_WINDOW", self.close_window)

    def _show(self, item, verdict):
        ev = item["event"]
        self.results.insert("", 0, values=(item["card"]["name"][:50], ev["direction"],
                                             ev["date"], ev["reference"], verdict))
        children = self.results.get_children()
        if len(children) > 100:
            for rid in children[100:]: self.results.delete(rid)
        self.auto_status.set(f"Checked {self.auto_processed} | review {self.auto_review} | skipped {self.auto_skipped} | " + verdict)
        self.progress["value"] = self.cursor

    def _audit(self, item, payload, status):
        record = {"schema": "cleaner.card_field_autorun/0.2",
                  "at": datetime.now().isoformat(timespec="seconds"),
                  "event_key": item["event_key"],
                  "card": {k:item["card"].get(k) for k in ("sheet", "index", "name", "wbs")},
                  "source_event": item["event"],
                  "locator": item["locator"],
                  "source_pdf": str(item["path"]) if item["path"] else None,
                  "family": self.family_var.get() if item is self.active_item else None,
                  "template": self.proposal_origin.get(0,{}) if item is self.active_item else None,
                  "processing_status": status, "evidence": payload,
                  "auto_corrections": 0, "source_confirmed": False}
        append_journal(self.journal, record)
        return record

    def _set_selected(self, item):
        card = item["card"]
        label = next((name for name, c in self.card_lookup.items() if
                      c["sheet"] == card["sheet"] and c["index"] == card["index"]), None)
        if not label:
            raise ValueError("card lookup failed")
        self.card_var.set(label)
        self.refresh_card()
        p = item["path"]
        name = next((text for text, ev, path, match in self.selection_items if
                     path is not None and path == p and ev["direction"] == item["event"]["direction"]
                     and ev["reference"] == item["event"]["reference"]), None)
        if name is None:
            raise ValueError("source selection failed")
        self.letter_var.set(name)
        self.open_selected_source()
        self.current_event = item["event"]

    def start_autorun(self):
        if self.running: return
        if not messagebox.askyesno("Enable continuous checking?",
            "Auto-Run will OCR each source PDF using your TRAINED FIELD BOXES, then continue until you stop it.\n\n"
            "Mismatch and unreadable results go to a review journal. Nothing is approved or written into Cleaner.\n\n"
            "Have you taught and checked date/reference boxes on representative letters?"):
            return
        self.running=True; self.auto_stop.clear()
        self.start_btn.config(state="disabled"); self.stop_btn.config(state="normal")
        self._start_at_selection()
        self.root.after(50, self._step)

    def _start_at_selection(self):
        sel=self.current_selection()
        if sel and sel[2]:
            card=self.card_lookup.get(self.card_var.get())
            if card:
                key=event_key(card, sel[1], sel[2])
                pos=next((i for i,q in enumerate(self.queue) if q["event_key"]==key), None)
                if pos is not None: self.cursor=pos

    def recheck_all(self):
        if self.running:
            messagebox.showinfo("Auto-Run active", "Stop the loop before resetting the checks.")
            return
        if not messagebox.askyesno("Recheck all?", "Reprocess previously checked files using your current learned boxes?\nThe existing evidence journal will be preserved."):
            return
        self.completed.clear()
        self.cursor=0
        self.auto_status.set("Recheck reset. Choose the first source and Start Auto-Run. Earlier evidence is preserved.")

    def stop_autorun(self):
        self.auto_stop.set()
        self.auto_status.set("Stop requested. Finishing/cancelling current OCR; processed evidence is saved.")

    def _stop_state(self, msg):
        self.running=False
        self.start_btn.config(state="normal"); self.stop_btn.config(state="disabled")
        self.auto_status.set(msg + f" | checked {self.auto_processed}, review {self.auto_review}, skipped {self.auto_skipped}")

    def _step(self):
        if not self.running:return
        if self.pending is not None:
            if not self.pending.done():
                self.root.after(100,self._step);return
            try:
                output=self.pending.result()
            except Exception as exc:
                output={"complete":False,"reason":"EXTRACTION_ERROR: " + str(exc)[:150]}
            self.pending=None
            item=self.active_item
            if output.get("reason") == "STOPPED":
                self._stop_state("Stopped during current OCR; unfinished document not marked processed")
                return
            if output.get("complete"):
                self._audit(item, output, "COMPLETED")
                self.completed.add(item["event_key"])
                self.auto_processed+=1
                outcomes=[f["result"] for f in output.get("fields",[])]
                if any(f.get("needs_review") for f in output.get("fields",[])): self.auto_review+=1
                verdict=" / ".join(outcomes) or "NO_FIELDS"
                if any(f.get("needs_review") for f in output.get("fields",[])):
                    verdict += " [REVIEW]"
            else:
                self.auto_review+=1
                self._audit(item,output,"NEEDS_REVIEW")
                verdict=output.get("reason", "EXTRACTION_ERROR")
            self._show(item, verdict)
            self.cursor+=1
        if self.auto_stop.is_set():
            self._stop_state("Stopped by operator")
            return
        while self.cursor<len(self.queue):
            item=self.queue[self.cursor]
            if item["event_key"] in self.completed:
                self.cursor+=1;continue
            if item["locator"] != "SINGLE_CANDIDATE" or not item["path"] or not item["path"].is_file():
                self._audit(item,{"reason":item["locator"]},"LOCATOR_REVIEW")
                self.auto_skipped+=1
                self._show(item,item["locator"])
                self.cursor+=1
                continue
            try:
                self._set_selected(item)
            except Exception as exc:
                self._audit(item,{"reason":"PDF_OPEN_FAILED: " + str(exc)[:150]},"NEEDS_REVIEW")
                self.auto_review+=1;self._show(item,"PDF_OPEN_FAILED")
                self.cursor+=1;continue
            self.active_item=item
            boxes=self._boxes()
            meta=self.proposal_origin.get(self.page_index,{})
            ok, reason=readiness(boxes,meta,self.require_alignment.get(),self.min_inliers.get())
            if not ok:
                self.auto_review+=1
                self._show(item,reason)
                self._stop_state("Paused for teaching/review: " +reason+ ". Correct boxes, approve & learn, then restart.")
                return
            h,w=self.rgb.shape[:2]
            page=self.doc[self.page_index]
            field_boxes={}
            for f in ("letter_date","letter_reference"):
                r=boxes[f][0]
                field_boxes[f]=[r.bbox[0]*page.rect.width/w,r.bbox[1]*page.rect.height/h,
                                r.bbox[2]*page.rect.width/w,r.bbox[3]*page.rect.height/h]
            expected={"letter_date":item["event"]["date"],"letter_reference":item["event"]["reference"]}
            self.pending=self.worker.submit(extract_regional_fields,item["path"],field_boxes,expected,
                                            self.tesseract,"fas+eng",6,300,self.auto_stop)
            self.auto_status.set(f"OCR running: {item['path'].name} | item {self.cursor+1}/{len(self.queue)}")
            self.root.after(100,self._step)
            return
        self._stop_state("Batch complete")

    def ocr_current(self):
        if self.running:
            messagebox.showinfo("Auto-Run active", "Stop the loop before evaluating this document manually.")
            return
        item=self.current_selection()
        if item is None or item[2] is None:
            messagebox.showwarning("Missing PDF","Select and open a source PDF first.");return
        if self.doc is None or self.path != item[2]: self.open_selected_source()
        card=self.card_lookup[self.card_var.get()]
        q={"card":card,"event":item[1],"path":item[2],"locator":item[3]["status"],
           "event_key":event_key(card,item[1],item[2])}
        self.active_item=q
        boxes=self._boxes()
        if any(len(boxes.get(x,[]))!=1 for x in ("letter_date","letter_reference")):
            messagebox.showwarning("Missing boxes","Teach date and reference first.");return
        h,w=self.rgb.shape[:2]; page=self.doc[self.page_index]
        field_boxes={f:[r[0]*page.rect.width/w,r[1]*page.rect.height/h,
                         r[2]*page.rect.width/w,r[3]*page.rect.height/h]
                     for f,(r,) in ((f,[x.bbox for x in boxes[f]]) for f in ("letter_date","letter_reference"))}
        self.auto_stop.clear()
        # Same threaded OCR processing as auto-run; never block the GUI.
        expected={"letter_date":item[1]["date"],"letter_reference":item[1]["reference"]}
        future=self.worker.submit(extract_regional_fields,item[2],field_boxes,expected,
                                  self.tesseract,"fas+eng",6,300,self.auto_stop)
        self.auto_status.set("OCR current source..." )
        def poll():
            if not future.done():self.root.after(100,poll);return
            try: value=future.result()
            except Exception as e:value={"complete":False,"reason":str(e)}
            self._audit(q,value,"COMPLETED" if value.get("complete") else "NEEDS_REVIEW")
            messagebox.showinfo("OCR result — not verified","\n".join(
                f"{f['field']}: {f['result']}\nOCR: {f['ocr_text'][:70]}\nNative: {f['native_text'][:70]}"
                for f in value.get("fields",[])) or str(value.get("reason")))
            self.auto_status.set("OCR current completed; review the audit journal.")
        self.root.after(100,poll)

    def close_window(self):
        if self.running or (self.pending is not None and not self.pending.done()):
            self.auto_stop.set()
            messagebox.showinfo("Stopping", "OCR cancellation requested. Close again after the current operation stops.")
            return
        self.worker.shutdown(wait=False, cancel_futures=True)
        self.root.destroy()


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--run-dir",type=Path,required=True)
    p.add_argument("--source-root",type=Path,required=True)
    p.add_argument("--focus-ref",default="1404/ES/S/3003")
    p.add_argument("--tesseract",default="tesseract")
    args=p.parse_args()
    if not (args.run_dir/"board_to_log.json").exists():p.error("Missing board_to_log.json")
    if not args.source_root.is_dir():p.error("Source root missing")
    root=tk.Tk()
    CardTeachingAutoApp(root, run_dir=args.run_dir,source_root=args.source_root,
                        focus_ref=args.focus_ref,tesseract=args.tesseract)
    root.mainloop()

if __name__=="__main__":main()
