"""Open a company letter directly in the *existing* Adaptive Document Annotator v0.6.

Does NOT alter source PDF, Cleaner state, solutions, or templates until the
user explicitly chooses Save & Learn in the native UI. Field labels are
proposals only and are not an evidence-verification decision.

Windows CMD (from Cleaner root):
  python .\\tools\\adaptive_document_reader\\open_letter_in_reader.py
  python .\\tools\\adaptive_document_reader\\open_letter_in_reader.py --pdf "C:\\my letter.pdf"
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path
import re
import sys
import tkinter as tk
from tkinter import ttk, messagebox

import adaptive_document_annotator_v0_6 as native


DEFAULT_PDF = Path(
    r"W:\00-1403\1403-02-05-230kV Azad\Letter\technical\send\1404-3003.pdf"
)
DEFAULT_REFERENCE = "1404/ES/S/3003"
DEFAULT_DATE = "1404/07/19"
DEFAULT_FAMILY = "ENGINEERING_CORRESPONDENCE_OUTGOING"

PERSIAN_TO_ASCII = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
DATE_RE = re.compile(r"(?<!\d)(?:13|14)\d{2}\s*[/.-]\s*\d{1,2}\s*[/.-]\s*\d{1,2}(?!\d)")
FULL_REF_RE = re.compile(r"(?<!\w)(?:13|14)\d{2}\s*[/\-]\s*ES\s*[/\-]\s*S\s*[/\-]\s*\d+(?!\d)", re.I)

FIELD_HINTS = (
    ("subject_label", ("موضوع", "subject:")),
    ("date_label", ("تاریخ", "date:")),
    ("reference_label", ("شماره", "ref:", "reference:")),
    ("attachment_label", ("پیوست", "attachment:")),
    ("recipient_label", ("گیرنده", "to:")),
)


def norm(s: str) -> str:
    return str(s).translate(PERSIAN_TO_ASCII)


def canonical_date(value: str) -> str:
    items = re.split(r"[/.-]", re.sub(r"\s+", "", norm(value)))
    if len(items) != 3:
        return norm(value)
    return f"{int(items[0]):04d}/{int(items[1]):02d}/{int(items[2]):02d}"


def canonical_reference(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", norm(value).upper())


def text_line_candidates(pdf_page, expected_reference: str, expected_date: str):
    """Read native-PDF text lines; never OCR or infer a missing field.

    Return tuples (PDF bounding box, role, observed, confidence). Output is
    suitable for editable overlay proposals, *not* field verification.
    """
    lines = defaultdict(list)
    for w in pdf_page.get_text("words"):
        if len(w) < 8:
            continue
        lines[(int(w[5]), int(w[6]))].append(w)

    found = []
    seen = set()
    all_dates = set()
    serial = expected_reference.split("/")[-1].strip()
    full_ref_found = False
    expected_date_found = False

    for line_words in lines.values():
        line_words.sort(key=lambda w: int(w[7]))
        line = norm(" ".join(str(w[4]) for w in line_words))
        rect = (
            min(w[0] for w in line_words),
            min(w[1] for w in line_words),
            max(w[2] for w in line_words),
            max(w[3] for w in line_words),
        )
        proposals = []
        for match in DATE_RE.finditer(line):
            date = canonical_date(match.group(0))
            all_dates.add(date)
            if date == expected_date:
                expected_date_found = True
            proposals.append(("date_candidate", date, 0.80))
        for match in FULL_REF_RE.finditer(line):
            val = match.group(0)
            if canonical_reference(val) == canonical_reference(expected_reference):
                full_ref_found = True
            proposals.append(("reference_candidate", val, 0.85))
        if serial and re.search(rf"(?<!\d){re.escape(serial)}(?!\d)", line):
            proposals.append(("serial_candidate", serial, 0.55))
        for role, hints in FIELD_HINTS:
            if any(hint.lower() in line.lower() for hint in hints):
                proposals.append((role, line[:100], 0.45))

        # One editable overlay per text line, with all its candidate roles.
        if proposals:
            labels = sorted(set(f"{role}={value}" for role, value, _ in proposals))
            key = (round(rect[0], 1), round(rect[1], 1), tuple(labels))
            if key not in seen:
                seen.add(key)
                found.append({
                    "bbox_pdf": list(rect),
                    "role": "; ".join(labels)[:250],
                    "confidence": max(p[2] for p in proposals),
                    "observed_text": line[:500],
                })

    return found, {
        "full_reference_found": full_ref_found,
        "expected_date_found": expected_date_found,
        "observed_dates": sorted(all_dates),
    }


class DirectLetterApp(native.App):
    """Thin extension of user's v0.6 GUI, preserving all editing and learning."""

    def __init__(self, root, path: Path, reference: str, expected_date: str, family: str):
        super().__init__(root)
        self.target_path = path
        self.expected_reference = reference
        self.expected_date = canonical_date(expected_date)
        self.family_var.set(family)
        self.refresh_learning_status()
        self.prepared_pages: set[int] = set()
        self.evidence_by_page: dict[int, dict] = {}
        self.evidence_label = tk.StringVar(value="Opening source letter...")
        evidence_bar = ttk.Frame(self.root, padding=(10, 4))
        ttk.Label(evidence_bar, text="SOURCE EVIDENCE (unverified)", foreground="#995a08").pack(side=tk.LEFT, padx=(0, 15))
        ttk.Label(evidence_bar, textvariable=self.evidence_label).pack(side=tk.LEFT, fill=tk.X, expand=True)
        evidence_bar.pack(fill=tk.X, before=self.notebook)
        self.root.title(f"Adaptive Document Reader — {path.name}")

    def open_target(self):
        """Directly load the specified PDF; bypass the Open dialog."""
        path = self.target_path
        if not path.is_file():
            messagebox.showerror("File unavailable", f"Cannot access source letter:\n{path}")
            self.evidence_label.set("FILE_NOT_FOUND — verify W: mapping or use --pdf")
            return
        try:
            if self.doc is not None:
                self.doc.close()
            self.path = path
            self.is_pdf = True
            self.page_index = 0
            self.page_states = {}
            self.prepared_pages.clear()
            self.doc = native.pymupdf.open(str(path))
            if len(self.doc) == 0:
                raise ValueError("PDF has no pages")
            self.load_page()
            self.register_current_document_in_job()
            self._prepare_current_page()
        except Exception as exc:
            messagebox.showerror("Open", f"{type(exc).__name__}: {exc}")
            self.evidence_label.set("OPEN_FAILED — review file or reader dependencies")

    def _prepare_current_page(self):
        index = self.page_index
        if index in self.prepared_pages:
            self._update_evidence_line()
            return

        # Native v0.6 detection & template memory, then native editable layers.
        self.run_detection()
        if not self.detection_result:
            self.evidence_label.set("DETECTION_FAILED — see Detection Lab")
            return
        self.send_to_edit()

        page = self.doc[index]
        proposals, evidence = text_line_candidates(page, self.expected_reference, self.expected_date)
        self.evidence_by_page[index] = evidence
        if proposals:
            group = self.create_group("Field candidates — UNVERIFIED")
            scale_x = self.rgb.shape[1] / page.rect.width
            scale_y = self.rgb.shape[0] / page.rect.height
            for p in proposals:
                x0, y0, x1, y1 = p["bbox_pdf"]
                self.add_region(
                    "form_field",
                    [x0 * scale_x, y0 * scale_y, x1 * scale_x, y1 * scale_y],
                    source="pdf_text_candidate_unverified",
                    confidence=p["confidence"],
                    role=p["role"],
                    group_id=group.id,
                )

        self.prepared_pages.add(index)
        self.refresh_layer_tree()
        self.redraw_edit()
        self.snapshot_current_page()
        self._update_evidence_line()
        self.status_var.set(
            "PDF opened directly in Human Edit. Blue/green boxes: native detection; "
            "'Field candidates' group: UNVERIFIED proposals. Review and Save & Learn."
        )

    def _update_evidence_line(self):
        evidence = self.evidence_by_page.get(self.page_index, {})
        dates = ", ".join(evidence.get("observed_dates", [])) or "none"
        rf = "found" if evidence.get("full_reference_found") else "not found"
        ed = "found" if evidence.get("expected_date_found") else "not found"
        self.evidence_label.set(
            f"Page {self.page_index + 1}/{len(self.doc)} | "
            f"Full ref: {rf} | Approved date {self.expected_date}: {ed} | "
            f"Native-text dates: {dates}"
        )

    def next_page(self):
        before = self.page_index
        super().next_page()
        if self.page_index != before:
            self._prepare_current_page()

    def prev_page(self):
        before = self.page_index
        super().prev_page()
        if self.page_index != before:
            self._prepare_current_page()


def make_parser():
    p = argparse.ArgumentParser(description="Open PDF directly in the existing Adaptive Document Annotator v0.6")
    p.add_argument("--pdf", type=Path, default=DEFAULT_PDF, help="PDF to open (defaults to AZD outgoing letter 1404-3003.pdf)")
    p.add_argument("--reference", default=DEFAULT_REFERENCE, help="General Doc reference to investigate")
    p.add_argument("--expected-date", default=DEFAULT_DATE, help="Approved date to check, never auto-apply")
    p.add_argument("--family", default=DEFAULT_FAMILY, help="Existing adaptive learning family")
    p.add_argument("--smoke-test", action="store_true", help=argparse.SUPPRESS)
    return p


def main(argv=None):
    args = make_parser().parse_args(argv)
    if not args.pdf.is_file():
        print(f"[ERROR] PDF not found: {args.pdf}", file=sys.stderr)
        print("[HINT] Check W: mapping or supply --pdf with the actual file path.", file=sys.stderr)
        return 2
    root = tk.Tk()
    app = DirectLetterApp(root, args.pdf, args.reference, args.expected_date, args.family)
    root.after(100, app.open_target)
    if args.smoke_test:
        def smoke():
            if not app.prepared_pages:
                print("[SMOKE] FAILED — no pages prepared", flush=True)
                root.destroy()
                return
            print(f"[SMOKE] PASS pages_opened={len(app.doc)} prepared={len(app.prepared_pages)} regions={len(app.regions)} candidates={len(app.evidence_by_page.get(0,{}).get('observed_dates',[]))}", flush=True)
            root.destroy()
        root.after(2500, smoke)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
