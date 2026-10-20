"""
document_layout_discovery.py

V1.4 - Document Discovery / Layout Annotation Workbench

Purpose
-------
Open a PDF, render pages, discover page regions, manually correct them,
label them, and export a structured JSON representation plus QA overlays.

This version intentionally focuses on:
    PDF -> page image -> regions -> labels -> JSON / QA image

It does NOT yet perform OCR or table-cell extraction.

Required packages
-----------------
    python -m pip install pymupdf pillow

Optional AI layout detection
----------------------------
    python -m pip install paddleocr paddlepaddle

The AI detector runs in an isolated subprocess using PP-DocLayout-S, ONNX Runtime, and CPU inference.
This prevents native AI/DLL crashes from closing the GUI. The first AI run may download model weights.
"""

from __future__ import annotations

import json
import os
import subprocess
import importlib.metadata
import sys
import tempfile
import traceback
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:
    import pymupdf
except ImportError:
    raise SystemExit(
        "PyMuPDF is required.\nInstall it with:\n    python -m pip install pymupdf"
    )

try:
    from PIL import Image, ImageTk, ImageDraw, ImageFont
except ImportError:
    raise SystemExit(
        "Pillow is required.\nInstall it with:\n    python -m pip install pillow"
    )


APP_TITLE = "Document Layout Discovery v1.4"
RENDER_DPI = 160

LAYOUT_LABELS = [
    "title", "heading", "text", "table", "image", "chart", "list",
    "header", "footer", "page_number", "stamp", "signature",
    "form_field", "handwriting", "unknown",
]

LABEL_COLORS = {
    "title": "#d32f2f", "heading": "#f57c00", "text": "#1976d2",
    "table": "#388e3c", "image": "#7b1fa2", "chart": "#512da8",
    "list": "#0097a7", "header": "#455a64", "footer": "#607d8b",
    "page_number": "#795548", "stamp": "#c2185b", "signature": "#5d4037",
    "form_field": "#00796b", "handwriting": "#303f9f", "unknown": "#616161",
}

PADDLE_TO_LOCAL = {
    "document_title": "title", "paragraph_title": "heading", "figure_title": "heading",
    "text": "text", "content": "text", "abstract": "text", "references": "text",
    "footnote": "text", "sidebar_text": "text", "table_of_contents": "list",
    "table": "table", "table_caption": "heading", "image": "image", "figure": "image",
    "figure_caption": "heading", "header": "header", "header_image": "header",
    "footer": "footer", "footer_image": "footer", "page_number": "page_number",
    "seal": "stamp", "stamp": "stamp", "formula": "text", "formula_number": "text",
    "algorithm": "text",
}


@dataclass
class Region:
    id: str
    page: int
    layout_type: str
    semantic_type: str
    bbox: list[float]
    confidence: Optional[float]
    source: str
    reading_order: int = 0
    native_text: str = ""

    def to_json(self, page_w: int, page_h: int) -> dict:
        x1, y1, x2, y2 = self.bbox
        d = asdict(self)
        d["bbox"] = [round(v, 2) for v in self.bbox]
        d["bbox_normalized"] = [
            round(x1 / page_w, 6), round(y1 / page_h, 6),
            round(x2 / page_w, 6), round(y2 / page_h, 6),
        ]
        return d


class LayoutDiscoveryApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title(APP_TITLE)
        root.geometry("1450x900")
        root.minsize(1100, 700)

        self.pdf_path: Optional[Path] = None
        self.doc = None
        self.page_index = 0
        self.regions: dict[int, list[Region]] = {}
        self.page_images: dict[int, Image.Image] = {}

        self.display_scale = 1.0
        self.photo = None
        self.canvas_image_id = None
        self.selected_region_id: Optional[str] = None
        self.draw_mode = False
        self.drag_start = None
        self.temp_rect = None
        self.paddle_model = None

        self._build_ui()
        self._bind_keys()

    # --------------------------- UI ---------------------------------

    def _build_ui(self):
        toolbar = ttk.Frame(self.root, padding=5)
        toolbar.pack(side=tk.TOP, fill=tk.X)

        ttk.Button(toolbar, text="Open PDF", command=self.open_pdf).pack(side=tk.LEFT, padx=2)
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=5)
        ttk.Button(toolbar, text="◀ Previous", command=self.prev_page).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Next ▶", command=self.next_page).pack(side=tk.LEFT, padx=2)

        self.page_var = tk.StringVar(value="No PDF")
        ttk.Label(toolbar, textvariable=self.page_var, width=20).pack(side=tk.LEFT, padx=8)

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=5)
        ttk.Button(toolbar, text="Native blocks", command=self.detect_native_blocks).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="AI Layout", command=self.detect_ai_layout).pack(side=tk.LEFT, padx=2)

        self.draw_btn = ttk.Button(toolbar, text="Draw region", command=self.toggle_draw_mode)
        self.draw_btn.pack(side=tk.LEFT, padx=2)

        ttk.Button(toolbar, text="Delete", command=self.delete_selected).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Auto order", command=self.auto_reading_order).pack(side=tk.LEFT, padx=2)

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=5)
        ttk.Button(toolbar, text="Export JSON", command=self.export_json).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Export QA PNG", command=self.export_qa_png).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Export crops", command=self.export_crops).pack(side=tk.LEFT, padx=2)

        paned = ttk.Panedwindow(self.root, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        canvas_frame = ttk.Frame(paned)
        paned.add(canvas_frame, weight=5)

        self.canvas = tk.Canvas(canvas_frame, background="#333333", highlightthickness=0, cursor="arrow")
        xscroll = ttk.Scrollbar(canvas_frame, orient=tk.HORIZONTAL, command=self.canvas.xview)
        yscroll = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=xscroll.set, yscrollcommand=yscroll.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        canvas_frame.rowconfigure(0, weight=1)
        canvas_frame.columnconfigure(0, weight=1)

        self.canvas.bind("<ButtonPress-1>", self.canvas_press)
        self.canvas.bind("<B1-Motion>", self.canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self.canvas_release)
        self.canvas.bind("<MouseWheel>", self.on_mousewheel)

        side = ttk.Frame(paned, padding=8)
        paned.add(side, weight=2)
        ttk.Label(side, text="Page regions", font=("", 11, "bold")).pack(anchor="w")

        columns = ("order", "layout", "semantic", "confidence", "source")
        self.tree = ttk.Treeview(side, columns=columns, show="headings", height=18)
        for col, title in [
            ("order", "#"), ("layout", "Layout"), ("semantic", "Semantic"),
            ("confidence", "Conf."), ("source", "Source")
        ]:
            self.tree.heading(col, text=title)
        self.tree.column("order", width=38, anchor="center")
        self.tree.column("layout", width=95)
        self.tree.column("semantic", width=130)
        self.tree.column("confidence", width=60, anchor="center")
        self.tree.column("source", width=90)
        self.tree.pack(fill=tk.BOTH, expand=True, pady=(5, 8))
        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)

        editor = ttk.LabelFrame(side, text="Selected region", padding=8)
        editor.pack(fill=tk.X)

        row1 = ttk.Frame(editor); row1.pack(fill=tk.X, pady=2)
        ttk.Label(row1, text="Layout:", width=10).pack(side=tk.LEFT)
        self.layout_var = tk.StringVar(value="text")
        self.layout_combo = ttk.Combobox(row1, textvariable=self.layout_var, values=LAYOUT_LABELS,
                                         state="readonly", width=20)
        self.layout_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)

        row2 = ttk.Frame(editor); row2.pack(fill=tk.X, pady=2)
        ttk.Label(row2, text="Semantic:", width=10).pack(side=tk.LEFT)
        self.semantic_var = tk.StringVar(value="")
        ttk.Entry(row2, textvariable=self.semantic_var).pack(side=tk.LEFT, fill=tk.X, expand=True)

        row3 = ttk.Frame(editor); row3.pack(fill=tk.X, pady=2)
        ttk.Label(row3, text="Order:", width=10).pack(side=tk.LEFT)
        self.order_var = tk.StringVar(value="0")
        ttk.Entry(row3, textvariable=self.order_var, width=8).pack(side=tk.LEFT)

        ttk.Button(editor, text="Apply changes", command=self.apply_region_changes).pack(fill=tk.X, pady=(6, 0))

        details = ttk.LabelFrame(side, text="Region details", padding=8)
        details.pack(fill=tk.BOTH, pady=(8, 0))
        self.detail_text = tk.Text(details, height=10, wrap="word")
        self.detail_text.pack(fill=tk.BOTH, expand=True)
        self.detail_text.configure(state="disabled")

        self.status_var = tk.StringVar(value="Open a PDF to begin.")
        ttk.Label(self.root, textvariable=self.status_var, relief=tk.SUNKEN, anchor="w").pack(
            side=tk.BOTTOM, fill=tk.X
        )

    def _bind_keys(self):
        self.root.bind("<Delete>", lambda e: self.delete_selected())
        self.root.bind("<Left>", lambda e: self.prev_page())
        self.root.bind("<Right>", lambda e: self.next_page())
        self.root.bind("<Escape>", lambda e: self.cancel_draw())

    # ------------------------- PDF ----------------------------------

    def open_pdf(self):
        path = filedialog.askopenfilename(
            title="Open PDF", filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")]
        )
        if not path:
            return
        try:
            if self.doc is not None:
                self.doc.close()
            self.pdf_path = Path(path)
            self.doc = pymupdf.open(path)
            self.page_index = 0
            self.regions = {}
            self.page_images = {}
            self.selected_region_id = None
            self.show_page()
            self.status(f"Opened {self.pdf_path.name} — {len(self.doc)} pages")
        except Exception as exc:
            messagebox.showerror("Open PDF", str(exc))

    def render_page(self, page_index: int) -> Image.Image:
        if page_index in self.page_images:
            return self.page_images[page_index]
        page = self.doc[page_index]
        pix = page.get_pixmap(dpi=RENDER_DPI, alpha=False)
        mode = "RGB" if pix.n == 3 else "RGBA"
        img = Image.frombytes(mode, (pix.width, pix.height), pix.samples)
        if mode == "RGBA":
            img = img.convert("RGB")
        self.page_images[page_index] = img
        return img

    def show_page(self):
        if self.doc is None:
            return
        img = self.render_page(self.page_index)
        self.root.update_idletasks()
        canvas_w = max(self.canvas.winfo_width() - 30, 500)
        self.display_scale = min(1.0, canvas_w / img.width)
        self.redraw_canvas()
        self.refresh_tree()
        self.page_var.set(f"Page {self.page_index + 1} / {len(self.doc)}")
        self.selected_region_id = None
        self.update_region_editor(None)

    def redraw_canvas(self):
        if self.doc is None:
            return
        img = self.render_page(self.page_index)
        dw = max(1, int(img.width * self.display_scale))
        dh = max(1, int(img.height * self.display_scale))
        display = img.resize((dw, dh), Image.Resampling.LANCZOS) if self.display_scale != 1.0 else img
        self.photo = ImageTk.PhotoImage(display)
        self.canvas.delete("all")
        self.canvas_image_id = self.canvas.create_image(0, 0, image=self.photo, anchor="nw")
        self.canvas.config(scrollregion=(0, 0, dw, dh))
        for region in self.current_regions():
            self.draw_region_on_canvas(region)

    def prev_page(self):
        if self.doc and self.page_index > 0:
            self.page_index -= 1
            self.show_page()

    def next_page(self):
        if self.doc and self.page_index < len(self.doc) - 1:
            self.page_index += 1
            self.show_page()

    # ----------------------- Regions --------------------------------

    def current_regions(self) -> list[Region]:
        return self.regions.setdefault(self.page_index, [])

    def find_region(self, region_id: str) -> Optional[Region]:
        return next((r for r in self.current_regions() if r.id == region_id), None)

    def new_region(self, bbox, layout_type="unknown", semantic_type="", confidence=None,
                   source="manual", native_text="") -> Region:
        r = Region(
            id=f"R-{uuid.uuid4().hex[:8]}", page=self.page_index + 1,
            layout_type=layout_type, semantic_type=semantic_type,
            bbox=[float(v) for v in bbox], confidence=confidence, source=source,
            reading_order=len(self.current_regions()) + 1, native_text=native_text,
        )
        self.current_regions().append(r)
        return r

    def draw_region_on_canvas(self, region: Region):
        x1, y1, x2, y2 = [v * self.display_scale for v in region.bbox]
        color = LABEL_COLORS.get(region.layout_type, "#ffffff")
        width = 4 if region.id == self.selected_region_id else 2
        self.canvas.create_rectangle(x1, y1, x2, y2, outline=color, width=width,
                                     tags=("region", region.id))
        label = f"{region.reading_order}: {region.layout_type}"
        if region.semantic_type:
            label += f" / {region.semantic_type}"
        label_w = max(90, min(260, len(label) * 7))
        self.canvas.create_rectangle(x1, max(0, y1 - 18), x1 + label_w, y1,
                                     fill=color, outline=color, tags=("region", region.id))
        self.canvas.create_text(x1 + 4, max(1, y1 - 9), text=label, fill="white",
                                anchor="w", font=("", 9, "bold"), tags=("region", region.id))

    # ---------------- Manual drawing / selection -------------------

    def toggle_draw_mode(self):
        if self.doc is None:
            messagebox.showinfo("Draw region", "Open a PDF first.")
            return
        self.draw_mode = not self.draw_mode
        self.draw_btn.configure(text="Drawing..." if self.draw_mode else "Draw region")
        self.canvas.configure(cursor="crosshair" if self.draw_mode else "arrow")
        self.status("Drag on the page to create a region." if self.draw_mode else "Draw mode off.")

    def cancel_draw(self):
        self.draw_mode = False
        self.draw_btn.configure(text="Draw region")
        self.canvas.configure(cursor="arrow")
        self.drag_start = None
        if self.temp_rect:
            self.canvas.delete(self.temp_rect)
            self.temp_rect = None

    def _canvas_xy(self, event):
        return self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)

    def canvas_press(self, event):
        if self.doc is None:
            return
        cx, cy = self._canvas_xy(event)
        if self.draw_mode:
            self.drag_start = (cx, cy)
            if self.temp_rect:
                self.canvas.delete(self.temp_rect)
            self.temp_rect = self.canvas.create_rectangle(
                cx, cy, cx, cy, outline="#ffeb3b", width=2, dash=(5, 3)
            )
            return

        px, py = cx / self.display_scale, cy / self.display_scale
        candidates = []
        for r in self.current_regions():
            x1, y1, x2, y2 = r.bbox
            if x1 <= px <= x2 and y1 <= py <= y2:
                candidates.append((max(1, (x2 - x1) * (y2 - y1)), r))
        if candidates:
            candidates.sort(key=lambda x: x[0])
            self.select_region(candidates[0][1].id)

    def canvas_drag(self, event):
        if not self.draw_mode or not self.drag_start or not self.temp_rect:
            return
        cx, cy = self._canvas_xy(event)
        x0, y0 = self.drag_start
        self.canvas.coords(self.temp_rect, x0, y0, cx, cy)

    def canvas_release(self, event):
        if not self.draw_mode or not self.drag_start:
            return
        cx, cy = self._canvas_xy(event)
        x0, y0 = self.drag_start
        self.drag_start = None
        if self.temp_rect:
            self.canvas.delete(self.temp_rect)
            self.temp_rect = None
        x1, x2 = sorted([x0, cx]); y1, y2 = sorted([y0, cy])
        if (x2 - x1) < 8 or (y2 - y1) < 8:
            return
        bbox = [x1 / self.display_scale, y1 / self.display_scale,
                x2 / self.display_scale, y2 / self.display_scale]
        img = self.render_page(self.page_index)
        bbox = [
            max(0, min(img.width, bbox[0])), max(0, min(img.height, bbox[1])),
            max(0, min(img.width, bbox[2])), max(0, min(img.height, bbox[3])),
        ]
        r = self.new_region(bbox=bbox, layout_type=self.layout_var.get() or "unknown",
                            semantic_type=self.semantic_var.get().strip(), source="manual")
        self.select_region(r.id)
        self.redraw_canvas(); self.refresh_tree()

    def on_mousewheel(self, event):
        if event.state & 0x0004:  # Ctrl
            self.zoom(1.12 if event.delta > 0 else 1 / 1.12)
        else:
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def zoom(self, factor):
        if self.doc is None:
            return
        self.display_scale = max(0.15, min(2.5, self.display_scale * factor))
        self.redraw_canvas()

    # ---------------- Tree / editor --------------------------------

    def refresh_tree(self):
        self.tree.delete(*self.tree.get_children())
        for r in sorted(self.current_regions(), key=lambda x: (x.reading_order, x.id)):
            conf = "" if r.confidence is None else f"{r.confidence:.2f}"
            self.tree.insert("", "end", iid=r.id,
                             values=(r.reading_order, r.layout_type, r.semantic_type, conf, r.source))
        if self.selected_region_id and self.tree.exists(self.selected_region_id):
            self.tree.selection_set(self.selected_region_id)

    def on_tree_select(self, _event=None):
        selection = self.tree.selection()
        if selection:
            self.select_region(selection[0], sync_tree=False)

    def select_region(self, region_id: str, sync_tree=True):
        r = self.find_region(region_id)
        if not r:
            return
        self.selected_region_id = region_id
        if sync_tree and self.tree.exists(region_id):
            self.tree.selection_set(region_id); self.tree.see(region_id)
        self.update_region_editor(r)
        self.redraw_canvas()

    def update_region_editor(self, region: Optional[Region]):
        if region is None:
            self.detail_text.configure(state="normal")
            self.detail_text.delete("1.0", tk.END)
            self.detail_text.configure(state="disabled")
            return
        self.layout_var.set(region.layout_type)
        self.semantic_var.set(region.semantic_type)
        self.order_var.set(str(region.reading_order))
        x1, y1, x2, y2 = region.bbox
        info = (
            f"ID: {region.id}\nSource: {region.source}\nConfidence: {region.confidence}\n"
            f"BBox: {x1:.1f}, {y1:.1f}, {x2:.1f}, {y2:.1f}\n"
            f"Size: {x2-x1:.1f} × {y2-y1:.1f}px\n"
        )
        if region.native_text:
            info += "\nNative PDF text:\n" + region.native_text[:1200]
        self.detail_text.configure(state="normal")
        self.detail_text.delete("1.0", tk.END)
        self.detail_text.insert("1.0", info)
        self.detail_text.configure(state="disabled")

    def apply_region_changes(self):
        if not self.selected_region_id:
            return
        r = self.find_region(self.selected_region_id)
        if not r:
            return
        r.layout_type = self.layout_var.get() or "unknown"
        r.semantic_type = self.semantic_var.get().strip()
        try:
            r.reading_order = max(0, int(self.order_var.get()))
        except ValueError:
            messagebox.showerror("Reading order", "Order must be an integer.")
            return
        self.refresh_tree(); self.redraw_canvas(); self.update_region_editor(r)

    def delete_selected(self):
        if not self.selected_region_id:
            return
        self.regions[self.page_index] = [
            r for r in self.current_regions() if r.id != self.selected_region_id
        ]
        self.selected_region_id = None
        self.refresh_tree(); self.redraw_canvas(); self.update_region_editor(None)

    def auto_reading_order(self):
        rs = self.current_regions()
        if not rs:
            return
        def key(r):
            x1, y1, _, _ = r.bbox
            return (round(y1 / 40.0), x1, y1)
        for i, r in enumerate(sorted(rs, key=key), start=1):
            r.reading_order = i
        self.refresh_tree(); self.redraw_canvas()
        self.status("Reading order recalculated.")

    # ---------------- Native PDF geometry ---------------------------

    def detect_native_blocks(self):
        if self.doc is None:
            return
        page = self.doc[self.page_index]
        img = self.render_page(self.page_index)
        sx = img.width / page.rect.width
        sy = img.height / page.rect.height
        try:
            blocks = page.get_text("blocks")
        except Exception as exc:
            messagebox.showerror("Native blocks", str(exc)); return

        count = 0
        for block in blocks:
            if len(block) < 7:
                continue
            x0, y0, x1, y1 = block[:4]
            text = block[4] if isinstance(block[4], str) else ""
            block_type = block[6]
            layout = "text" if block_type == 0 else "image" if block_type == 1 else "unknown"
            if layout == "text" and not text.strip():
                continue
            self.new_region(
                bbox=[x0 * sx, y0 * sy, x1 * sx, y1 * sy], layout_type=layout,
                confidence=1.0, source="pdf_native", native_text=text.strip()
            )
            count += 1

        self.auto_reading_order(); self.refresh_tree(); self.redraw_canvas()
        if count == 0:
            messagebox.showinfo(
                "Native blocks",
                "No native text/image blocks were found.\n\n"
                "This page may be scanned. Try AI Layout or draw regions manually."
            )
        else:
            self.status(f"Added {count} native PDF blocks.")

    # ---------------- Optional PaddleOCR ----------------------------

    def detect_ai_layout(self):
        """Run PaddleOCR layout detection in an isolated child process.

        v1.2 always attempts to read the worker JSON result even when the
        worker returns a non-zero exit code.  This exposes the real Python
        exception instead of hiding it behind only "exit code 2".
        """
        if self.doc is None:
            return

        img = self.render_page(self.page_index)
        image_path = None
        result_path = None
        progress_path = None

        try:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                image_path = tmp.name
            img.save(image_path, "PNG")

            # Do NOT pre-create the JSON result file.  Let the worker create it.
            result_path = tempfile.mktemp(suffix=".json")
            progress_path = tempfile.mktemp(suffix=".log")

            self.status("AI Layout: starting isolated worker (CPU / Paddle Static / oneDNN OFF)...")
            self.root.update()

            cmd = [
                sys.executable,
                str(Path(__file__).resolve()),
                "--ai-worker",
                image_path,
                result_path,
                progress_path,
            ]

            completed = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=300,
            )

            # Read worker payload FIRST, regardless of return code.
            payload = None
            payload_read_error = None

            if result_path and Path(result_path).exists():
                try:
                    with open(result_path, "r", encoding="utf-8") as f:
                        payload = json.load(f)
                except Exception as exc:
                    payload_read_error = f"{type(exc).__name__}: {exc}"

            progress_text = ""
            if progress_path and Path(progress_path).exists():
                try:
                    progress_text = Path(progress_path).read_text(
                        encoding="utf-8", errors="replace"
                    )
                except Exception:
                    pass

            if completed.returncode != 0:
                unsigned_code = completed.returncode & 0xFFFFFFFF

                diagnostic = (
                    "The isolated AI worker failed safely.\n\n"
                    f"Exit code: {completed.returncode} "
                    f"(0x{unsigned_code:08X})\n\n"
                )

                if payload and not payload.get("ok", False):
                    diagnostic += (
                        "ACTUAL PYTHON ERROR:\n"
                        + payload.get("error", "Unknown worker error")
                        + "\n\n"
                    )

                    stage = payload.get("stage")
                    if stage:
                        diagnostic += f"FAILED STAGE:\n{stage}\n\n"

                    versions = payload.get("versions", {})
                    if versions:
                        diagnostic += "PACKAGE VERSIONS:\n"
                        for key, value in versions.items():
                            diagnostic += f"  {key}: {value}\n"
                        diagnostic += "\n"

                    tb = payload.get("traceback", "")
                    if tb:
                        diagnostic += "TRACEBACK:\n" + tb[-7000:] + "\n\n"

                elif payload_read_error:
                    diagnostic += (
                        "The worker result file could not be read:\n"
                        + payload_read_error
                        + "\n\n"
                    )

                if progress_text.strip():
                    diagnostic += "WORKER STAGES:\n" + progress_text[-2500:] + "\n\n"

                if unsigned_code == 0xC0000005:
                    diagnostic += (
                        "Windows reported ACCESS_VIOLATION (0xC0000005).\n"
                        "That points to a native DLL/runtime failure.\n\n"
                    )

                if completed.stderr.strip():
                    diagnostic += "STDERR:\n" + completed.stderr[-5000:] + "\n\n"

                if completed.stdout.strip():
                    diagnostic += "STDOUT:\n" + completed.stdout[-3000:] + "\n\n"

                diagnostic += (
                    f"Interpreter:\n{sys.executable}\n"
                )

                messagebox.showerror("AI Layout worker failed", diagnostic)
                self.status("AI Layout failed safely; see the diagnostic dialog.")
                return

            if payload is None:
                diagnostic = (
                    "The AI worker exited successfully but produced no readable JSON result."
                )
                if payload_read_error:
                    diagnostic += "\n\n" + payload_read_error
                if progress_text.strip():
                    diagnostic += "\n\nWorker stages:\n" + progress_text[-2500:]
                messagebox.showerror("AI Layout", diagnostic)
                return

            if not payload.get("ok", False):
                details = payload.get("error", "Unknown AI worker error")
                stage = payload.get("stage", "unknown")
                tb = payload.get("traceback", "")
                messagebox.showerror(
                    "AI Layout",
                    f"{details}\n\nStage: {stage}"
                    + ("\n\n" + tb[-7000:] if tb else "")
                )
                self.status("AI Layout returned a Python-level error.")
                return

            boxes = payload.get("boxes", [])
            added = 0

            for b in boxes:
                coord = b.get("coordinate") or b.get("bbox")
                if not coord or len(coord) != 4:
                    continue

                original_label = str(b.get("label", "unknown"))
                local_label = PADDLE_TO_LOCAL.get(original_label, "unknown")

                score = b.get("score")
                try:
                    score = float(score) if score is not None else None
                except Exception:
                    score = None

                self.new_region(
                    bbox=[float(v) for v in coord],
                    layout_type=local_label,
                    semantic_type=original_label if local_label == "unknown" else "",
                    confidence=score,
                    source="paddle_layout_paddle_static_cpu",
                )
                added += 1

            self.auto_reading_order()
            self.refresh_tree()
            self.redraw_canvas()

            model = payload.get("model", "layout model")
            self.status(f"AI layout detection added {added} regions using {model}.")

            if added == 0:
                messagebox.showwarning(
                    "AI Layout",
                    "The AI worker completed successfully but returned no layout boxes."
                )

        except subprocess.TimeoutExpired:
            messagebox.showerror(
                "AI Layout timeout",
                "The isolated AI worker did not finish within 5 minutes.\n\n"
                "The GUI remains usable."
            )
            self.status("AI Layout timed out.")

        except Exception as exc:
            traceback.print_exc()
            messagebox.showerror("AI Layout", f"{type(exc).__name__}: {exc}")
            self.status("AI Layout failed.")

        finally:
            for p in (image_path, result_path, progress_path):
                if p:
                    try:
                        os.remove(p)
                    except OSError:
                        pass

    # ---------------- Export ----------------------------------------

    def document_json(self) -> dict:
        if self.doc is None or self.pdf_path is None:
            return {}
        pages = []
        for page_index in range(len(self.doc)):
            img = self.render_page(page_index)
            page = self.doc[page_index]
            rs = sorted(self.regions.get(page_index, []), key=lambda r: (r.reading_order, r.id))
            pages.append({
                "page": page_index + 1,
                "render_dpi": RENDER_DPI,
                "image_width_px": img.width,
                "image_height_px": img.height,
                "pdf_width_pt": round(page.rect.width, 3),
                "pdf_height_pt": round(page.rect.height, 3),
                "regions": [r.to_json(img.width, img.height) for r in rs],
            })
        return {
            "schema": "document-layout-discovery/v1",
            "document": self.pdf_path.name,
            "source_path": str(self.pdf_path),
            "page_count": len(self.doc),
            "coordinate_system": (
                "bbox = rendered page pixels at page.render_dpi; "
                "bbox_normalized = [x1,y1,x2,y2] in 0..1 page coordinates"
            ),
            "pages": pages,
        }

    def export_json(self):
        if self.doc is None or self.pdf_path is None:
            return
        default = self.pdf_path.with_name(self.pdf_path.stem + "_layout.json")
        path = filedialog.asksaveasfilename(
            title="Export document layout JSON", initialfile=default.name,
            initialdir=str(default.parent), defaultextension=".json",
            filetypes=[("JSON", "*.json")]
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.document_json(), f, ensure_ascii=False, indent=2)
            self.status(f"JSON exported: {path}")
        except Exception as exc:
            messagebox.showerror("Export JSON", str(exc))

    def annotated_image(self) -> Image.Image:
        img = self.render_page(self.page_index).copy()
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("arial.ttf", 22)
        except Exception:
            font = ImageFont.load_default()
        for r in self.current_regions():
            x1, y1, x2, y2 = [int(round(v)) for v in r.bbox]
            color = LABEL_COLORS.get(r.layout_type, "#616161")
            draw.rectangle([x1, y1, x2, y2], outline=color, width=4)
            label = f"{r.reading_order}: {r.layout_type}"
            if r.semantic_type:
                label += f" / {r.semantic_type}"
            try:
                tb = draw.textbbox((x1, y1), label, font=font)
                tw, th = tb[2] - tb[0] + 10, tb[3] - tb[1] + 8
            except Exception:
                tw, th = max(100, len(label) * 10), 26
            ly = max(0, y1 - th)
            draw.rectangle([x1, ly, x1 + tw, ly + th], fill=color)
            draw.text((x1 + 5, ly + 3), label, fill="white", font=font)
        return img

    def export_qa_png(self):
        if self.doc is None or self.pdf_path is None:
            return
        default_name = f"{self.pdf_path.stem}_page_{self.page_index + 1:03d}_QA.png"
        path = filedialog.asksaveasfilename(
            title="Export annotated QA image", initialfile=default_name,
            initialdir=str(self.pdf_path.parent), defaultextension=".png",
            filetypes=[("PNG", "*.png")]
        )
        if not path:
            return
        try:
            self.annotated_image().save(path, "PNG")
            self.status(f"QA image exported: {path}")
        except Exception as exc:
            messagebox.showerror("Export QA PNG", str(exc))

    def export_crops(self):
        if self.doc is None or self.pdf_path is None:
            return
        folder = filedialog.askdirectory(title="Choose folder for region crops")
        if not folder:
            return
        folder = Path(folder)
        img = self.render_page(self.page_index)
        count = 0
        for r in sorted(self.current_regions(), key=lambda x: (x.reading_order, x.id)):
            x1, y1, x2, y2 = [int(round(v)) for v in r.bbox]
            x1 = max(0, min(img.width, x1)); x2 = max(0, min(img.width, x2))
            y1 = max(0, min(img.height, y1)); y2 = max(0, min(img.height, y2))
            if x2 <= x1 or y2 <= y1:
                continue
            crop = img.crop((x1, y1, x2, y2))
            safe_sem = "".join(c if c.isalnum() or c in "-_" else "_"
                               for c in (r.semantic_type or r.layout_type))
            name = (
                f"{self.pdf_path.stem}_p{self.page_index + 1:03d}_"
                f"{r.reading_order:03d}_{safe_sem}_{r.id}.png"
            )
            crop.save(folder / name, "PNG")
            count += 1
        self.status(f"Exported {count} region crops to {folder}")

    def status(self, message: str):
        self.status_var.set(message)
        self.root.update_idletasks()


def _extract_result_dict(res):
    """Convert a PaddleOCR result object into a plain dict."""
    raw = getattr(res, "json", None)
    if callable(raw):
        raw = raw()

    if isinstance(raw, str):
        raw = json.loads(raw)

    if isinstance(raw, dict):
        return raw

    try:
        return dict(res)
    except Exception:
        return {}


def _package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except Exception:
        return "not installed / unknown"


def _append_progress(progress_path: str, message: str):
    try:
        with open(progress_path, "a", encoding="utf-8") as f:
            f.write(message + "\n")
            f.flush()
    except Exception:
        pass


def run_ai_worker(image_path: str, result_path: str, progress_path: str) -> int:
    """Child-process entry point for layout inference only.

    Each important stage is written immediately to a tiny progress log.
    If a native process crash happens, the parent can still see the last
    completed stage.
    """
    stage = "worker_start"

    versions = {
        "python": sys.version.replace("\n", " "),
        "paddleocr": _package_version("paddleocr"),
        "paddlex": _package_version("paddlex"),
        "paddlepaddle": _package_version("paddlepaddle"),
        "onnxruntime": _package_version("onnxruntime"),
        "numpy": _package_version("numpy"),
        "pillow": _package_version("pillow"),
    }

    payload = {
        "ok": False,
        "stage": stage,
        "versions": versions,
        "boxes": [],
    }

    _append_progress(progress_path, f"stage={stage}")
    _append_progress(progress_path, f"python={sys.executable}")
    for k, v in versions.items():
        _append_progress(progress_path, f"{k}={v}")

    try:
        stage = "configure_cpu_backend"
        _append_progress(progress_path, f"stage={stage}")
        # Defensive environment flags: disable oneDNN/MKLDNN before Paddle imports.
        os.environ["FLAGS_use_mkldnn"] = "0"
        os.environ["FLAGS_use_onednn"] = "0"

        stage = "import_paddleocr"
        _append_progress(progress_path, f"stage={stage}")
        from paddleocr import LayoutDetection

        stage = "construct_layout_model"
        _append_progress(progress_path, f"stage={stage}")

        # PP-DocLayout-S is distributed as a Paddle inference model by the
        # official model source.  Use Paddle's native static inference engine.
        # This avoids the ONNX-package lookup that fails for this model.
        # PaddlePaddle 3.3.0/3.3.1 has a known CPU oneDNN/PIR regression
        # for some inference models:
        #   ConvertPirAttribute2RuntimeAttribute not support
        #   [pir::ArrayAttribute<pir::DoubleAttribute>]
        #
        # Keep the native Paddle static engine, but disable MKL-DNN/oneDNN.
        model = LayoutDetection(
            model_name="PP-DocLayout-S",
            engine="paddle_static",
            device="cpu",
            enable_mkldnn=False,
            cpu_threads=4,
        )

        stage = "predict"
        _append_progress(progress_path, f"stage={stage}")

        output = model.predict(
            image_path,
            batch_size=1,
            layout_nms=True,
        )

        stage = "parse_results"
        _append_progress(progress_path, f"stage={stage}")

        boxes = []

        for res in output:
            raw = _extract_result_dict(res)
            body = raw.get("res", raw) if isinstance(raw, dict) else {}
            current = body.get("boxes", []) if isinstance(body, dict) else []
            if isinstance(current, list):
                boxes.extend(current)

        safe_boxes = []

        for b in boxes:
            if not isinstance(b, dict):
                continue

            coord = b.get("coordinate") or b.get("bbox")
            if coord is None:
                continue

            safe_boxes.append(
                {
                    "cls_id": (
                        int(b.get("cls_id"))
                        if b.get("cls_id") is not None
                        else None
                    ),
                    "label": str(b.get("label", "unknown")),
                    "score": (
                        float(b.get("score"))
                        if b.get("score") is not None
                        else None
                    ),
                    "coordinate": [float(v) for v in coord],
                }
            )

        stage = "write_success"
        _append_progress(progress_path, f"stage={stage}")

        payload = {
            "ok": True,
            "stage": stage,
            "versions": versions,
            "engine": "paddle_static",
            "device": "cpu",
            "enable_mkldnn": False,
            "cpu_threads": 4,
            "model": "PP-DocLayout-S",
            "boxes": safe_boxes,
        }
        rc = 0

    except Exception as exc:
        error_text = f"{type(exc).__name__}: {exc}"
        if "ConvertPirAttribute2RuntimeAttribute" in str(exc):
            error_text += (
                "\n\nThis is the known PaddlePaddle 3.3.x CPU oneDNN/PIR regression. "
                "v1.4 already disables MKL-DNN. If it still appears, the next fallback "
                "is to pin paddlepaddle==3.2.2."
            )

        if stage == "construct_layout_model" and (
            "paddle" in str(exc).lower()
            or versions.get("paddlepaddle", "").startswith("not installed")
        ):
            error_text += (
                "\n\nPaddlePaddle is required for PP-DocLayout-S native inference. "
                "Install it in .venv_layout with:\n"
                "  .\\.venv_layout\\Scripts\\python.exe -m pip install paddlepaddle==3.3.1"
            )

        payload = {
            "ok": False,
            "stage": stage,
            "versions": versions,
            "error": error_text,
            "traceback": traceback.format_exc(),
            "boxes": [],
        }
        _append_progress(
            progress_path,
            f"python_exception={type(exc).__name__}: {exc}"
        )
        rc = 2

    try:
        with open(result_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception:
        traceback.print_exc()
        _append_progress(progress_path, "stage=result_write_failed")
        return 3

    return rc


def main():
    root = tk.Tk()
    LayoutDiscoveryApp(root)
    root.mainloop()


if __name__ == "__main__":
    if len(sys.argv) >= 5 and sys.argv[1] == "--ai-worker":
        raise SystemExit(
            run_ai_worker(sys.argv[2], sys.argv[3], sys.argv[4])
        )
    main()
