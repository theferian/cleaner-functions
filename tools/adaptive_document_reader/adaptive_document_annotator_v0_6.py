
"""
adaptive_document_annotator_v0_6.py

Two-phase human-in-the-loop document layout system.

TAB 1 — DETECTION LAB
    - Smart/classical box detection
    - Intermediate views:
        Original, Binary, Rules, Components, Text lines, Text blocks, Regions
    - Tunable parameters:
        Adaptive block, Adaptive C, Line scale, Min component area,
        Character join X/Y, Block join X/Y
    - Send proposals into the Human Edit phase

TAB 2 — HUMAN EDIT
    - Photoshop-like layer/group panel on the LEFT
    - Visibility, lock, grouping and z-order controls
    - Draw / move / resize / relabel / delete
    - Zoom in / zoom out / fit page
    - Save corrections into family memory
    - Optional lightweight ML classifier

Core requirements:
    python -m pip install pymupdf pillow numpy opencv-python

Optional ML:
    python -m pip install scikit-learn
"""

from __future__ import annotations

import copy
import json
import math
import os
import pickle
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

try:
    import pymupdf
except ImportError:
    raise SystemExit("Install PyMuPDF: python -m pip install pymupdf")

try:
    import cv2
except ImportError:
    raise SystemExit("Install OpenCV: python -m pip install opencv-python")

try:
    import numpy as np
except ImportError:
    raise SystemExit("Install NumPy: python -m pip install numpy")

try:
    from PIL import Image, ImageTk
except ImportError:
    raise SystemExit("Install Pillow: python -m pip install pillow")


APP_TITLE = "Adaptive Document Annotator v0.6"
RENDER_DPI = 170
BASE_DIR = Path(__file__).resolve().parent
LEARNING_ROOT = BASE_DIR / "adaptive_document_learning"

LAYOUT_TYPES = [
    "text_block",
    "table",
    "title",
    "heading",
    "list",
    "image",
    "chart",
    "signature",
    "stamp",
    "form_field",
    "header",
    "footer",
    "unknown",
]

TYPE_COLORS = {
    "text_block": "#1976d2",
    "table": "#2e7d32",
    "title": "#c62828",
    "heading": "#ef6c00",
    "list": "#00838f",
    "image": "#7b1fa2",
    "chart": "#512da8",
    "signature": "#5d4037",
    "stamp": "#ad1457",
    "form_field": "#00796b",
    "header": "#455a64",
    "footer": "#607d8b",
    "unknown": "#616161",
}


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def safe_family_name(name: str) -> str:
    name = name.strip() or "default"
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name or "default"


def ensure_bbox(b, w, h):
    x1, y1, x2, y2 = map(float, b)
    x1, x2 = sorted([max(0.0, min(float(w), x1)), max(0.0, min(float(w), x2))])
    y1, y2 = sorted([max(0.0, min(float(h), y1)), max(0.0, min(float(h), y2))])
    return [x1, y1, x2, y2]


def box_iou(a, b) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    aa = max(1.0, (ax2 - ax1) * (ay2 - ay1))
    ba = max(1.0, (bx2 - bx1) * (by2 - by1))
    return inter / (aa + ba - inter)


def mask_rgb(mask):
    return cv2.cvtColor(mask, cv2.COLOR_GRAY2RGB)


def rotate_vector(x, y, angle_deg):
    a = math.radians(float(angle_deg))
    ca, sa = math.cos(a), math.sin(a)
    return x * ca - y * sa, x * sa + y * ca


def region_center_size(bbox):
    x1, y1, x2, y2 = bbox
    return (
        (x1 + x2) / 2.0,
        (y1 + y2) / 2.0,
        max(1.0, x2 - x1),
        max(1.0, y2 - y1),
    )


def rotated_region_corners(bbox, angle_deg):
    """Return TL, TR, BR, BL corners of a rotated rectangle."""
    cx, cy, w, h = region_center_size(bbox)
    local = [
        (-w / 2, -h / 2),
        ( w / 2, -h / 2),
        ( w / 2,  h / 2),
        (-w / 2,  h / 2),
    ]
    out = []
    for lx, ly in local:
        rx, ry = rotate_vector(lx, ly, angle_deg)
        out.append((cx + rx, cy + ry))
    return out


ANCHOR_NAMES = [
    "Center",
    "Top-left",
    "Top-right",
    "Bottom-left",
    "Bottom-right",
]


def anchor_local_offset(anchor, width, height):
    offsets = {
        "Center": (0.0, 0.0),
        "Top-left": (-width / 2.0, -height / 2.0),
        "Top-right": (width / 2.0, -height / 2.0),
        "Bottom-left": (-width / 2.0, height / 2.0),
        "Bottom-right": (width / 2.0, height / 2.0),
    }
    return offsets.get(anchor, (0.0, 0.0))


def region_anchor_point(bbox, angle_deg, anchor):
    cx, cy, w, h = region_center_size(bbox)
    ox, oy = anchor_local_offset(anchor, w, h)
    rx, ry = rotate_vector(ox, oy, angle_deg)
    return cx + rx, cy + ry


# ----------------------------------------------------------------------
# Data model
# ----------------------------------------------------------------------

@dataclass
class Region:
    id: str
    layout_type: str
    role: str
    bbox: list[float]
    source: str = "base"
    confidence: float = 0.0
    user_modified: bool = False
    group_id: str = ""
    visible: bool = True
    locked: bool = False
    angle: float = 0.0

    def normalized_bbox(self, w: int, h: int):
        x1, y1, x2, y2 = self.bbox
        return [x1 / w, y1 / h, x2 / w, y2 / h]


@dataclass
class LayerGroup:
    id: str
    name: str
    visible: bool = True
    locked: bool = False


# ----------------------------------------------------------------------
# Detection engine
# ----------------------------------------------------------------------

class DetectionEngine:
    """
    Transparent classical detector with inspectable intermediate stages.
    """

    def __init__(
        self,
        adaptive_block=31,
        adaptive_c=15,
        line_scale=35,
        min_component_area=8,
        char_join_x=18,
        char_join_y=3,
        block_join_x=12,
        block_join_y=18,
    ):
        self.adaptive_block = max(3, int(adaptive_block))
        if self.adaptive_block % 2 == 0:
            self.adaptive_block += 1
        self.adaptive_c = int(adaptive_c)
        self.line_scale = max(10, int(line_scale))
        self.min_component_area = max(1, int(min_component_area))
        self.char_join_x = max(1, int(char_join_x))
        self.char_join_y = max(1, int(char_join_y))
        self.block_join_x = max(1, int(block_join_x))
        self.block_join_y = max(1, int(block_join_y))

    def run(self, rgb):
        h, w = rgb.shape[:2]
        page_area = h * w

        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)

        binary = cv2.adaptiveThreshold(
            gray,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV,
            self.adaptive_block,
            self.adaptive_c,
        )

        # Clean minimal speckle.
        binary_clean = cv2.morphologyEx(
            binary,
            cv2.MORPH_OPEN,
            cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2)),
        )

        # Long rules.
        hlen = max(20, w // self.line_scale)
        vlen = max(20, h // self.line_scale)

        hk = cv2.getStructuringElement(cv2.MORPH_RECT, (hlen, 1))
        vk = cv2.getStructuringElement(cv2.MORPH_RECT, (1, vlen))

        horizontal = cv2.morphologyEx(binary_clean, cv2.MORPH_OPEN, hk)
        vertical = cv2.morphologyEx(binary_clean, cv2.MORPH_OPEN, vk)
        rules = cv2.bitwise_or(horizontal, vertical)
        intersections = cv2.bitwise_and(horizontal, vertical)

        # Remove rules before text grouping.
        grown_rules = cv2.dilate(
            rules,
            cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)),
            iterations=1,
        )
        textish = cv2.bitwise_and(binary_clean, cv2.bitwise_not(grown_rules))

        # Connected components.
        n, labels, stats, _ = cv2.connectedComponentsWithStats(textish, 8)
        component_mask = np.zeros_like(textish)
        component_boxes = []

        for i in range(1, n):
            area = int(stats[i, cv2.CC_STAT_AREA])
            if area < self.min_component_area:
                continue

            x = int(stats[i, cv2.CC_STAT_LEFT])
            y = int(stats[i, cv2.CC_STAT_TOP])
            bw = int(stats[i, cv2.CC_STAT_WIDTH])
            bh = int(stats[i, cv2.CC_STAT_HEIGHT])

            if bw * bh > page_area * 0.80:
                continue

            component_mask[labels == i] = 255
            component_boxes.append([x, y, x + bw, y + bh])

        # Join components into text lines.
        line_mask = cv2.dilate(
            component_mask,
            cv2.getStructuringElement(
                cv2.MORPH_RECT,
                (self.char_join_x, self.char_join_y),
            ),
            iterations=1,
        )
        contours, _ = cv2.findContours(
            line_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        line_boxes = []
        for c in contours:
            x, y, bw, bh = cv2.boundingRect(c)
            if bw < 6 or bh < 3:
                continue
            if bh > h * 0.12:
                continue
            line_boxes.append([x, y, x + bw, y + bh])

        # Join lines into blocks.
        line_seed = np.zeros_like(binary_clean)
        for x1, y1, x2, y2 in line_boxes:
            cv2.rectangle(line_seed, (x1, y1), (x2, y2), 255, -1)

        block_mask = cv2.dilate(
            line_seed,
            cv2.getStructuringElement(
                cv2.MORPH_RECT,
                (self.block_join_x, self.block_join_y),
            ),
            iterations=1,
        )
        contours, _ = cv2.findContours(
            block_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        block_boxes = []
        for c in contours:
            x, y, bw, bh = cv2.boundingRect(c)
            if bw < 12 or bh < 6:
                continue
            if bw * bh > page_area * 0.65:
                continue
            block_boxes.append([x, y, x + bw, y + bh])

        # Table candidates from rule connectivity + intersections.
        int_n, _, int_stats, _ = cv2.connectedComponentsWithStats(intersections, 8)
        centers = []
        for i in range(1, int_n):
            if int_stats[i, cv2.CC_STAT_AREA] >= 1:
                cx = (
                    int_stats[i, cv2.CC_STAT_LEFT]
                    + int_stats[i, cv2.CC_STAT_WIDTH] // 2
                )
                cy = (
                    int_stats[i, cv2.CC_STAT_TOP]
                    + int_stats[i, cv2.CC_STAT_HEIGHT] // 2
                )
                centers.append((cx, cy))

        grid_connected = cv2.dilate(
            rules,
            cv2.getStructuringElement(
                cv2.MORPH_RECT,
                (max(3, w // 250), max(3, h // 250)),
            ),
            iterations=2,
        )
        gc, _ = cv2.findContours(
            grid_connected, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        table_boxes = []
        for c in gc:
            x, y, bw, bh = cv2.boundingRect(c)
            if bw < w * 0.08 or bh < h * 0.03:
                continue
            if bw * bh > page_area * 0.90:
                continue

            b = [x, y, x + bw, y + bh]
            ints = sum(1 for cx, cy in centers if x <= cx <= x+bw and y <= cy <= y+bh)
            roi = rules[y:y+bh, x:x+bw]
            coverage = float(np.count_nonzero(roi)) / max(1, roi.size)

            if ints >= 4 or coverage >= 0.025:
                score = min(0.98, 0.45 + ints * 0.03 + coverage * 5)
                table_boxes.append((b, score, ints, coverage))

        # Final proposals.
        proposals = []

        for b, score, ints, coverage in table_boxes:
            proposals.append({
                "layout_type": "table",
                "bbox": b,
                "confidence": score,
                "source": f"base_table intersections={ints} coverage={coverage:.4f}",
            })

        table_rects = [b for b, _, _, _ in table_boxes]

        for b in block_boxes:
            if any(box_iou(b, tb) > 0.25 for tb in table_rects):
                continue

            x1, y1, x2, y2 = b
            roi = component_mask[y1:y2, x1:x2]
            density = float(np.count_nonzero(roi)) / max(1, roi.size)

            proposals.append({
                "layout_type": "text_block",
                "bbox": b,
                "confidence": min(0.88, 0.35 + density * 3),
                "source": f"base_text density={density:.4f}",
            })

        proposals.sort(key=lambda p: (p["bbox"][1], p["bbox"][0]))

        # Diagnostics.
        comp_vis = rgb.copy()
        for b in component_boxes:
            x1, y1, x2, y2 = b
            cv2.rectangle(comp_vis, (x1, y1), (x2, y2), (255, 140, 0), 1)

        line_vis = rgb.copy()
        for b in line_boxes:
            x1, y1, x2, y2 = b
            cv2.rectangle(line_vis, (x1, y1), (x2, y2), (0, 170, 60), 2)

        block_vis = rgb.copy()
        for b in block_boxes:
            x1, y1, x2, y2 = b
            cv2.rectangle(block_vis, (x1, y1), (x2, y2), (40, 100, 220), 3)

        rule_vis = rgb.copy()
        rule_vis[horizontal > 0] = [220, 50, 50]
        rule_vis[vertical > 0] = [50, 80, 220]
        rule_vis[intersections > 0] = [20, 220, 20]

        region_vis = rgb.copy()
        for p in proposals:
            x1, y1, x2, y2 = map(int, p["bbox"])
            if p["layout_type"] == "table":
                color = (30, 160, 30)
            else:
                color = (30, 100, 220)
            cv2.rectangle(region_vis, (x1, y1), (x2, y2), color, 4)
            cv2.putText(
                region_vis,
                f'{p["layout_type"]} {p["confidence"]:.2f}',
                (x1, max(20, y1 - 8)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                color,
                2,
                cv2.LINE_AA,
            )

        stages = {
            "Original": rgb,
            "Binary": mask_rgb(binary_clean),
            "Rules": rule_vis,
            "Components": comp_vis,
            "Text lines": line_vis,
            "Text blocks": block_vis,
            "Regions": region_vis,
        }

        stats_out = {
            "components": len(component_boxes),
            "text_lines": len(line_boxes),
            "text_blocks": len(block_boxes),
            "tables": len(table_boxes),
            "proposals": len(proposals),
            "horizontal_kernel": hlen,
            "vertical_kernel": vlen,
        }

        return {
            "proposals": proposals,
            "stages": stages,
            "stats": stats_out,
        }


# ----------------------------------------------------------------------
# Learning store
# ----------------------------------------------------------------------

class LearningStore:
    def __init__(self, root):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def family_dir(self, family):
        p = self.root / "families" / safe_family_name(family)
        p.mkdir(parents=True, exist_ok=True)
        return p

    def examples_dir(self, family):
        p = self.family_dir(family) / "examples"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def training_path(self, family):
        return self.family_dir(family) / "training.jsonl"

    def model_path(self, family):
        return self.family_dir(family) / "region_classifier.pkl"

    def jobs_dir(self):
        p = self.root / "jobs"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def create_job(self, name, family):
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        job_id = f"{stamp}_{safe_family_name(name or 'job')}"
        folder = self.jobs_dir() / job_id
        folder.mkdir(parents=True, exist_ok=False)

        job = {
            "schema": "adaptive-document-job/v0.6",
            "id": job_id,
            "name": name or job_id,
            "family": family,
            "status": "active",
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "finished_at": None,
            "documents": [],
            "events": [],
        }
        self.save_job(job)
        return job

    def save_job(self, job):
        folder = self.jobs_dir() / job["id"]
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "job.json").write_text(
            json.dumps(job, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def list_jobs(self):
        jobs = []
        for folder in sorted(self.jobs_dir().iterdir(), reverse=True):
            path = folder / "job.json"
            if not path.exists():
                continue
            try:
                jobs.append(json.loads(path.read_text(encoding="utf-8")))
            except Exception:
                pass
        return jobs

    def list_examples(self, family):
        return sorted(
            [p for p in self.examples_dir(family).glob("example_*") if p.is_dir()],
            key=lambda p: p.name,
            reverse=True,
        )

    def next_example_dir(self, family):
        examples = self.list_examples(family)
        n = 1
        if examples:
            try:
                n = max(int(p.name.split("_")[-1]) for p in examples) + 1
            except Exception:
                n = len(examples) + 1
        p = self.examples_dir(family) / f"example_{n:06d}"
        p.mkdir(parents=True, exist_ok=False)
        return p

    def status(self, family):
        examples = len(self.list_examples(family))
        training = self.training_path(family)
        samples = 0
        classes = set()

        if training.exists():
            for line in training.read_text(encoding="utf-8").splitlines():
                try:
                    d = json.loads(line)
                    samples += 1
                    if d.get("target"):
                        classes.add(d["target"])
                except Exception:
                    pass

        return {
            "examples": examples,
            "training_samples": samples,
            "classes": len(classes),
            "model_exists": self.model_path(family).exists(),
        }


# ----------------------------------------------------------------------
# Main app
# ----------------------------------------------------------------------

class App:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("1580x950")
        self.root.minsize(1180, 760)

        self.store = LearningStore(LEARNING_ROOT)

        self.path: Optional[Path] = None
        self.doc = None
        self.is_pdf = False
        self.page_index = 0
        self.rgb: Optional[np.ndarray] = None

        # In-session per-page workspace state.
        # Switching PDF pages should behave like switching artboards:
        # annotations and detection work remain exactly where the user left them.
        self.page_states: dict[int, dict] = {}

        self.detection_result = None

        self.regions: list[Region] = []
        self.groups: dict[str, LayerGroup] = {}
        self.layer_order: list[str] = []  # bottom -> top region IDs

        self.region_counter = 0
        self.group_counter = 0
        self.selected_id: Optional[str] = None
        self._suppress_layer_event = False

        # Editing state
        self.edit_mode = "select"
        self.drag_kind = None
        self.drag_start = None
        self.drag_origin_bbox = None
        self.resize_corner = None
        self.temp_rect = None

        # Zoom state
        self.detect_zoom = 1.0
        self.edit_zoom = 1.0
        self.detect_fit = True
        self.edit_fit = True
        self.detect_photo = None
        self.edit_photo = None

        # Job lifecycle and explainable template assistance.
        self.active_job = None
        self.job_name_var = tk.StringVar(value="")
        self.job_status_var = tk.StringVar(value="No active job")
        self.template_status_var = tk.StringVar(value="Template memory: not checked yet")

        # UI vars
        self.family_var = tk.StringVar(value="default")
        self.detect_stage_var = tk.StringVar(value="Assisted regions")
        self.layout_var = tk.StringVar(value="text_block")
        self.role_var = tk.StringVar(value="")

        # Geometry editor. X/Y always represent the currently selected
        # anchor point, not necessarily top-left.
        self.anchor_var = tk.StringVar(value="Center")
        self.geom_x_var = tk.StringVar(value="")
        self.geom_y_var = tk.StringVar(value="")
        self.geom_w_var = tk.StringVar(value="")
        self.geom_h_var = tk.StringVar(value="")
        self.angle_var = tk.StringVar(value="0")

        self.learning_status_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="Open a PDF or image.")

        self.detect_vars = {
            "adaptive_block": tk.IntVar(value=31),
            "adaptive_c": tk.IntVar(value=15),
            "line_scale": tk.IntVar(value=35),
            "min_component_area": tk.IntVar(value=8),
            "char_join_x": tk.IntVar(value=18),
            "char_join_y": tk.IntVar(value=3),
            "block_join_x": tk.IntVar(value=12),
            "block_join_y": tk.IntVar(value=18),
        }

        self._build_ui()
        self._bind_keys()
        self.refresh_learning_status()

    # ------------------------------------------------------------------
    # UI build
    # ------------------------------------------------------------------

    def _build_ui(self):
        # Global top bar
        top = ttk.Frame(self.root, padding=5)
        top.pack(fill=tk.X)

        ttk.Button(top, text="Open", command=self.open_file).pack(side=tk.LEFT, padx=2)
        ttk.Button(top, text="◀ Page", command=self.prev_page).pack(side=tk.LEFT, padx=2)
        ttk.Button(top, text="Page ▶", command=self.next_page).pack(side=tk.LEFT, padx=2)

        self.page_var = tk.StringVar(value="No document")
        ttk.Label(top, textvariable=self.page_var, width=22).pack(side=tk.LEFT, padx=6)

        ttk.Label(top, text="Document family:").pack(side=tk.LEFT, padx=(10, 3))
        family = ttk.Entry(top, textvariable=self.family_var, width=26)
        family.pack(side=tk.LEFT)
        family.bind("<FocusOut>", lambda e: self.refresh_learning_status())

        ttk.Button(
            top,
            text="Save correction + learn",
            command=self.save_and_learn,
        ).pack(side=tk.RIGHT, padx=4)

        # Explicit work-job lifecycle.
        jobbar = ttk.Frame(self.root, padding=(5, 1, 5, 4))
        jobbar.pack(fill=tk.X)

        ttk.Label(jobbar, text="Job:").pack(side=tk.LEFT)
        ttk.Entry(
            jobbar,
            textvariable=self.job_name_var,
            width=26,
        ).pack(side=tk.LEFT, padx=(3, 4))

        ttk.Button(
            jobbar,
            text="Start Job",
            command=self.start_job,
        ).pack(side=tk.LEFT, padx=2)

        ttk.Button(
            jobbar,
            text="End Job",
            command=self.end_job,
        ).pack(side=tk.LEFT, padx=2)

        ttk.Button(
            jobbar,
            text="Job History",
            command=self.show_job_history,
        ).pack(side=tk.LEFT, padx=6)

        ttk.Label(
            jobbar,
            textvariable=self.job_status_var,
            foreground="#555",
        ).pack(side=tk.LEFT, padx=10)

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        self.detect_tab = ttk.Frame(self.notebook)
        self.edit_tab = ttk.Frame(self.notebook)

        self.notebook.add(self.detect_tab, text="1  Detection Lab")
        self.notebook.add(self.edit_tab, text="2  Human Edit")

        self._build_detection_tab()
        self._build_edit_tab()

        ttk.Label(
            self.root,
            textvariable=self.status_var,
            relief=tk.SUNKEN,
            anchor="w",
        ).pack(fill=tk.X)

    def _build_detection_tab(self):
        tab = self.detect_tab

        left = ttk.Frame(tab)
        right = ttk.Frame(tab, padding=8)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        right.pack(side=tk.RIGHT, fill=tk.Y)

        toolbar = ttk.Frame(left, padding=4)
        toolbar.pack(fill=tk.X)

        ttk.Button(toolbar, text="Run detection", command=self.run_detection).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(
            toolbar,
            text="Send proposals → Human Edit",
            command=self.send_to_edit,
        ).pack(side=tk.LEFT, padx=6)

        ttk.Label(toolbar, text="View:").pack(side=tk.LEFT, padx=(10, 3))
        stage = ttk.Combobox(
            toolbar,
            textvariable=self.detect_stage_var,
            values=[
                "Original",
                "Binary",
                "Rules",
                "Components",
                "Text lines",
                "Text blocks",
                "Base regions",
                "Assisted regions",
            ],
            state="readonly",
            width=16,
        )
        stage.pack(side=tk.LEFT)
        stage.bind("<<ComboboxSelected>>", lambda e: self.redraw_detection())

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)
        ttk.Button(toolbar, text="−", width=3, command=lambda: self.zoom_detection(0.8)).pack(side=tk.LEFT)
        ttk.Label(toolbar, text="Zoom").pack(side=tk.LEFT, padx=3)
        ttk.Button(toolbar, text="+", width=3, command=lambda: self.zoom_detection(1.25)).pack(side=tk.LEFT)
        ttk.Button(toolbar, text="Fit", command=self.fit_detection).pack(side=tk.LEFT, padx=3)

        canvas_frame = ttk.Frame(left)
        canvas_frame.pack(fill=tk.BOTH, expand=True)

        self.detect_canvas = tk.Canvas(canvas_frame, bg="#333333", highlightthickness=0)
        dx = ttk.Scrollbar(canvas_frame, orient=tk.HORIZONTAL, command=self.detect_canvas.xview)
        dy = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=self.detect_canvas.yview)
        self.detect_canvas.configure(xscrollcommand=dx.set, yscrollcommand=dy.set)

        self.detect_canvas.grid(row=0, column=0, sticky="nsew")
        dy.grid(row=0, column=1, sticky="ns")
        dx.grid(row=1, column=0, sticky="ew")
        canvas_frame.rowconfigure(0, weight=1)
        canvas_frame.columnconfigure(0, weight=1)

        self.detect_canvas.bind(
            "<Control-MouseWheel>",
            lambda e: self.zoom_detection(1.15 if e.delta > 0 else 1/1.15),
        )

        ttk.Label(right, text="Detection parameters", font=("", 11, "bold")).pack(anchor="w")

        rows = [
            ("Adaptive block", "adaptive_block", "Local threshold window"),
            ("Adaptive C", "adaptive_c", "Foreground sensitivity"),
            ("Line scale", "line_scale", "Shorter/longer rule detection"),
            ("Min component", "min_component_area", "Small-mark filtering"),
            ("Character join X", "char_join_x", "Horizontal text grouping"),
            ("Character join Y", "char_join_y", "Vertical line tolerance"),
            ("Block join X", "block_join_x", "Block horizontal grouping"),
            ("Block join Y", "block_join_y", "Line-to-block grouping"),
        ]

        for label, key, hint in rows:
            row = ttk.Frame(right)
            row.pack(fill=tk.X, pady=3)
            ttk.Label(row, text=label, width=18).pack(side=tk.LEFT)
            ttk.Spinbox(
                row,
                textvariable=self.detect_vars[key],
                from_=1,
                to=301,
                width=7,
            ).pack(side=tk.LEFT)
            ttk.Label(row, text=hint, foreground="#666").pack(side=tk.LEFT, padx=5)

        ttk.Button(
            right,
            text="Apply / re-run",
            command=self.run_detection,
        ).pack(fill=tk.X, pady=(10, 4))

        ttk.Label(
            right,
            textvariable=self.template_status_var,
            wraplength=360,
            justify="left",
            foreground="#444",
        ).pack(anchor="w", fill=tk.X, pady=(8, 3))

        ttk.Label(right, text="Detection summary", font=("", 10, "bold")).pack(
            anchor="w", pady=(6, 3)
        )
        self.detect_stats_text = tk.Text(right, width=42, height=14, wrap="word")
        self.detect_stats_text.pack(fill=tk.BOTH, expand=True)

    def _build_edit_tab(self):
        tab = self.edit_tab

        # Scrollable Photoshop-like inspector on LEFT.
        # The whole inspector scrolls so Geometry / learning controls can
        # always be reached on smaller windows.
        layers_shell = ttk.Frame(tab, width=355)
        layers_shell.pack(side=tk.LEFT, fill=tk.Y)
        layers_shell.pack_propagate(False)

        self.inspector_canvas = tk.Canvas(
            layers_shell,
            highlightthickness=0,
            width=335,
        )
        inspector_scroll = ttk.Scrollbar(
            layers_shell,
            orient=tk.VERTICAL,
            command=self.inspector_canvas.yview,
        )
        self.inspector_canvas.configure(yscrollcommand=inspector_scroll.set)

        inspector_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.inspector_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        layers_panel = ttk.Frame(self.inspector_canvas, padding=6)
        self._inspector_window = self.inspector_canvas.create_window(
            (0, 0),
            window=layers_panel,
            anchor="nw",
        )

        def _sync_inspector_scroll(_event=None):
            self.inspector_canvas.configure(
                scrollregion=self.inspector_canvas.bbox("all")
            )
            self.inspector_canvas.itemconfigure(
                self._inspector_window,
                width=max(320, self.inspector_canvas.winfo_width()),
            )

        layers_panel.bind("<Configure>", _sync_inspector_scroll)
        self.inspector_canvas.bind("<Configure>", _sync_inspector_scroll)

        def _wheel(event):
            delta = -1 if event.delta > 0 else 1
            self.inspector_canvas.yview_scroll(delta * 3, "units")
            return "break"

        def _wheel_on(_event):
            self.root.bind_all("<MouseWheel>", _wheel)

        def _wheel_off(_event):
            self.root.unbind_all("<MouseWheel>")

        layers_shell.bind("<Enter>", _wheel_on)
        layers_shell.bind("<Leave>", _wheel_off)

        ttk.Label(layers_panel, text="Layers", font=("", 11, "bold")).pack(anchor="w")

        tree_frame = ttk.Frame(layers_panel)
        tree_frame.pack(fill=tk.X, pady=(4, 5))

        self.layer_tree = ttk.Treeview(
            tree_frame,
            columns=("visible", "lock", "type"),
            show="tree headings",
            selectmode="extended",
            height=18,
        )
        self.layer_tree.heading("#0", text="Layer / Group")
        self.layer_tree.heading("visible", text="Vis")
        self.layer_tree.heading("lock", text="Lock")
        self.layer_tree.heading("type", text="Type")

        self.layer_tree.column("#0", width=145)
        self.layer_tree.column("visible", width=38, anchor="center")
        self.layer_tree.column("lock", width=42, anchor="center")
        self.layer_tree.column("type", width=90)

        layer_tree_scroll = ttk.Scrollbar(
            tree_frame,
            orient=tk.VERTICAL,
            command=self.layer_tree.yview,
        )
        self.layer_tree.configure(yscrollcommand=layer_tree_scroll.set)
        self.layer_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        layer_tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.layer_tree.bind("<<TreeviewSelect>>", self.on_layer_select)
        self.layer_tree.bind("<Double-1>", self.on_layer_double_click)

        row = ttk.Frame(layers_panel)
        row.pack(fill=tk.X, pady=2)
        ttk.Button(row, text="New Group", command=self.new_group).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=1)
        ttk.Button(row, text="Group Selected", command=self.group_selected).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=1)

        row = ttk.Frame(layers_panel)
        row.pack(fill=tk.X, pady=2)
        ttk.Button(row, text="Ungroup", command=self.ungroup_selected).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=1)
        ttk.Button(row, text="Toggle Vis", command=self.toggle_layer_visibility).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=1)
        ttk.Button(row, text="Toggle Lock", command=self.toggle_layer_lock).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=1)

        row = ttk.Frame(layers_panel)
        row.pack(fill=tk.X, pady=2)
        ttk.Button(row, text="↑ Layer", command=lambda: self.move_layer(1)).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=1)
        ttk.Button(row, text="↓ Layer", command=lambda: self.move_layer(-1)).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=1)

        ttk.Separator(layers_panel, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=8)

        ttk.Label(layers_panel, text="Selected region", font=("", 10, "bold")).pack(anchor="w")

        r = ttk.Frame(layers_panel)
        r.pack(fill=tk.X, pady=2)
        ttk.Label(r, text="Type:", width=7).pack(side=tk.LEFT)
        ttk.Combobox(
            r,
            textvariable=self.layout_var,
            values=LAYOUT_TYPES,
            state="readonly",
            width=19,
        ).pack(side=tk.LEFT, fill=tk.X, expand=True)

        r = ttk.Frame(layers_panel)
        r.pack(fill=tk.X, pady=2)
        ttk.Label(r, text="Role:", width=7).pack(side=tk.LEFT)
        ttk.Entry(r, textvariable=self.role_var).pack(side=tk.LEFT, fill=tk.X, expand=True)

        ttk.Button(
            layers_panel,
            text="Apply type / role",
            command=self.apply_labels,
        ).pack(fill=tk.X, pady=4)

        geometry = ttk.LabelFrame(
            layers_panel,
            text="Geometry / rotation",
            padding=6,
        )
        geometry.pack(fill=tk.X, pady=(6, 2))

        row = ttk.Frame(geometry)
        row.pack(fill=tk.X, pady=2)
        ttk.Label(row, text="Anchor:", width=8).pack(side=tk.LEFT)
        anchor_combo = ttk.Combobox(
            row,
            textvariable=self.anchor_var,
            values=ANCHOR_NAMES,
            state="readonly",
            width=16,
        )
        anchor_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
        anchor_combo.bind(
            "<<ComboboxSelected>>",
            lambda e: self.update_geometry_fields(),
        )

        row = ttk.Frame(geometry)
        row.pack(fill=tk.X, pady=2)
        ttk.Label(row, text="X:", width=3).pack(side=tk.LEFT)
        ttk.Entry(row, textvariable=self.geom_x_var, width=9).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Label(row, text="Y:", width=3).pack(side=tk.LEFT)
        ttk.Entry(row, textvariable=self.geom_y_var, width=9).pack(side=tk.LEFT)

        row = ttk.Frame(geometry)
        row.pack(fill=tk.X, pady=2)
        ttk.Label(row, text="W:", width=3).pack(side=tk.LEFT)
        ttk.Entry(row, textvariable=self.geom_w_var, width=9).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Label(row, text="H:", width=3).pack(side=tk.LEFT)
        ttk.Entry(row, textvariable=self.geom_h_var, width=9).pack(side=tk.LEFT)

        row = ttk.Frame(geometry)
        row.pack(fill=tk.X, pady=2)
        ttk.Label(row, text="Angle:", width=8).pack(side=tk.LEFT)
        ttk.Spinbox(
            row,
            textvariable=self.angle_var,
            from_=-180,
            to=180,
            increment=1,
            width=9,
        ).pack(side=tk.LEFT)
        ttk.Label(row, text="degrees").pack(side=tk.LEFT, padx=4)

        row = ttk.Frame(geometry)
        row.pack(fill=tk.X, pady=(4, 2))
        ttk.Button(
            row,
            text="↺ 90°",
            command=lambda: self.rotate_selected(-90),
        ).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=1)
        ttk.Button(
            row,
            text="↻ 90°",
            command=lambda: self.rotate_selected(90),
        ).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=1)

        ttk.Button(
            geometry,
            text="Apply geometry",
            command=self.apply_geometry,
        ).pack(fill=tk.X, pady=(3, 0))

        ttk.Label(
            geometry,
            text=(
                "X/Y = selected anchor position. "
                "Changing W/H keeps that anchor fixed."
            ),
            wraplength=290,
            foreground="#666",
            justify="left",
        ).pack(anchor="w", pady=(5, 0))

        ttk.Label(
            layers_panel,
            textvariable=self.learning_status_var,
            justify="left",
            foreground="#555",
        ).pack(anchor="w", pady=(8, 0))

        # Center/right editing view.
        edit_area = ttk.Frame(tab)
        edit_area.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        toolbar = ttk.Frame(edit_area, padding=4)
        toolbar.pack(fill=tk.X)

        self.draw_btn = ttk.Button(toolbar, text="Draw region", command=self.toggle_draw)
        self.draw_btn.pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Delete", command=self.delete_selected).pack(side=tk.LEFT, padx=2)

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)
        ttk.Button(toolbar, text="−", width=3, command=lambda: self.zoom_edit(0.8)).pack(side=tk.LEFT)
        ttk.Label(toolbar, text="Zoom").pack(side=tk.LEFT, padx=3)
        ttk.Button(toolbar, text="+", width=3, command=lambda: self.zoom_edit(1.25)).pack(side=tk.LEFT)
        ttk.Button(toolbar, text="Fit", command=self.fit_edit).pack(side=tk.LEFT, padx=3)
        self.edit_zoom_label = ttk.Label(toolbar, text="100%")
        self.edit_zoom_label.pack(side=tk.LEFT, padx=6)

        canvas_frame = ttk.Frame(edit_area)
        canvas_frame.pack(fill=tk.BOTH, expand=True)

        self.edit_canvas = tk.Canvas(canvas_frame, bg="#333333", highlightthickness=0)
        ex = ttk.Scrollbar(canvas_frame, orient=tk.HORIZONTAL, command=self.edit_canvas.xview)
        ey = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=self.edit_canvas.yview)
        self.edit_canvas.configure(xscrollcommand=ex.set, yscrollcommand=ey.set)

        self.edit_canvas.grid(row=0, column=0, sticky="nsew")
        ey.grid(row=0, column=1, sticky="ns")
        ex.grid(row=1, column=0, sticky="ew")
        canvas_frame.rowconfigure(0, weight=1)
        canvas_frame.columnconfigure(0, weight=1)

        self.edit_canvas.bind("<ButtonPress-1>", self.edit_canvas_press)
        self.edit_canvas.bind("<B1-Motion>", self.edit_canvas_drag)
        self.edit_canvas.bind("<ButtonRelease-1>", self.edit_canvas_release)
        self.edit_canvas.bind(
            "<Control-MouseWheel>",
            lambda e: self.zoom_edit(1.15 if e.delta > 0 else 1/1.15),
        )

    def _bind_keys(self):
        self.root.bind("<Delete>", lambda e: self.delete_selected())
        self.root.bind("<Escape>", lambda e: self.cancel_draw())

    # ------------------------------------------------------------------
    # Job lifecycle / history
    # ------------------------------------------------------------------

    def start_job(self):
        if self.active_job is not None:
            messagebox.showinfo(
                "Job",
                f"A job is already active: {self.active_job['name']}\n"
                "End it before starting another job.",
            )
            return

        family = self.family_var.get().strip() or "default"
        name = self.job_name_var.get().strip()
        if not name:
            name = f"{family} work"
            self.job_name_var.set(name)

        self.active_job = self.store.create_job(name, family)
        self.job_status_var.set(
            f"ACTIVE — {name} | family: {family} | 0 documents"
        )

        if self.path is not None:
            self.register_current_document_in_job()

        self.status_var.set(
            f"Job started: {name}. Family is fixed to '{family}' for this job."
        )

    def end_job(self):
        if self.active_job is None:
            messagebox.showinfo("Job", "There is no active job.")
            return

        self.active_job["status"] = "completed"
        self.active_job["finished_at"] = datetime.now().isoformat(timespec="seconds")
        self.active_job["events"].append({
            "time": datetime.now().isoformat(timespec="seconds"),
            "type": "job_finished",
        })
        self.store.save_job(self.active_job)

        name = self.active_job["name"]
        docs = len(self.active_job.get("documents", []))
        self.active_job = None
        self.job_status_var.set(f"Completed: {name} | documents: {docs}")
        self.status_var.set(f"Job finished: {name}")

    def register_current_document_in_job(self):
        if self.active_job is None or self.path is None:
            return

        p = str(self.path)
        documents = self.active_job.setdefault("documents", [])
        existing = next((d for d in documents if d.get("path") == p), None)

        if existing is None:
            documents.append({
                "path": p,
                "name": self.path.name,
                "opened_at": datetime.now().isoformat(timespec="seconds"),
                "corrections": [],
            })
            self.active_job["events"].append({
                "time": datetime.now().isoformat(timespec="seconds"),
                "type": "document_opened",
                "path": p,
            })
            self.store.save_job(self.active_job)

        self.job_status_var.set(
            f"ACTIVE — {self.active_job['name']} | "
            f"family: {self.active_job['family']} | "
            f"{len(documents)} documents"
        )

    def record_job_correction(self, example_name, region_count):
        if self.active_job is None or self.path is None:
            return

        p = str(self.path)
        self.register_current_document_in_job()
        doc = next(
            (d for d in self.active_job["documents"] if d.get("path") == p),
            None,
        )
        if doc is None:
            return

        correction = {
            "time": datetime.now().isoformat(timespec="seconds"),
            "page": self.page_index + 1 if self.is_pdf else 1,
            "example": example_name,
            "regions": int(region_count),
        }
        doc.setdefault("corrections", []).append(correction)
        self.active_job["events"].append({
            "type": "correction_saved",
            "path": p,
            **correction,
        })
        self.store.save_job(self.active_job)

    def enforce_job_family(self):
        """An active job always uses the family it started with."""
        if self.active_job is None:
            return self.family_var.get().strip() or "default"

        family = self.active_job["family"]
        if self.family_var.get().strip() != family:
            self.family_var.set(family)
            self.refresh_learning_status()
        return family

    def show_job_history(self):
        jobs = self.store.list_jobs()

        win = tk.Toplevel(self.root)
        win.title("Job History")
        win.geometry("900x420")

        tree = ttk.Treeview(
            win,
            columns=("status", "family", "started", "finished", "docs"),
            show="tree headings",
        )
        tree.heading("#0", text="Job")
        tree.heading("status", text="Status")
        tree.heading("family", text="Family")
        tree.heading("started", text="Started")
        tree.heading("finished", text="Finished")
        tree.heading("docs", text="Documents")

        tree.column("#0", width=190)
        tree.column("status", width=90)
        tree.column("family", width=160)
        tree.column("started", width=150)
        tree.column("finished", width=150)
        tree.column("docs", width=80, anchor="center")

        scroll = ttk.Scrollbar(win, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        for job in jobs:
            tree.insert(
                "",
                "end",
                text=job.get("name", job.get("id", "")),
                values=(
                    job.get("status", ""),
                    job.get("family", ""),
                    job.get("started_at", ""),
                    job.get("finished_at") or "",
                    len(job.get("documents", [])),
                ),
            )

    # ------------------------------------------------------------------
    # File / page handling
    # ------------------------------------------------------------------

    def open_file(self):
        path = filedialog.askopenfilename(
            title="Open PDF / image",
            filetypes=[
                ("PDF / images", "*.pdf *.png *.jpg *.jpeg *.tif *.tiff *.bmp"),
                ("PDF", "*.pdf"),
                ("Images", "*.png *.jpg *.jpeg *.tif *.tiff *.bmp"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return

        try:
            if self.doc is not None:
                self.doc.close()
                self.doc = None

            self.path = Path(path)
            self.is_pdf = self.path.suffix.lower() == ".pdf"
            self.page_index = 0
            self.page_states = {}

            if self.is_pdf:
                self.doc = pymupdf.open(path)

            self.load_page()
            self.refresh_learning_status()
            self.register_current_document_in_job()
            self.status_var.set("Document loaded. Start in Detection Lab.")

        except Exception as exc:
            messagebox.showerror("Open", f"{type(exc).__name__}: {exc}")

    def load_page(self):
        if self.path is None:
            return

        if self.is_pdf:
            page = self.doc[self.page_index]
            pix = page.get_pixmap(dpi=RENDER_DPI, alpha=False)
            arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
                pix.height, pix.width, pix.n
            )
            if pix.n == 4:
                arr = cv2.cvtColor(arr, cv2.COLOR_RGBA2RGB)
            self.rgb = arr[:, :, :3].copy()
            self.page_var.set(f"Page {self.page_index + 1} / {len(self.doc)}")
        else:
            bgr = cv2.imread(str(self.path), cv2.IMREAD_COLOR)
            if bgr is None:
                raise RuntimeError("OpenCV could not read the image.")
            self.rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            self.page_var.set(self.path.name)

        # Restore this page's workspace if it has already been visited.
        # Otherwise initialise a fresh page workspace.
        if self.is_pdf and self.page_index in self.page_states:
            self.restore_page_state(self.page_index)
        else:
            self.detection_result = None
            self.regions = []
            self.groups = {}
            self.layer_order = []
            self.selected_id = None
            self.template_status_var.set("Template memory: not checked yet")

            self.detect_fit = True
            self.edit_fit = True

        self.redraw_detection()
        self.redraw_edit()
        self.refresh_layer_tree()
        self.update_geometry_fields()

    def prev_page(self):
        if self.is_pdf and self.page_index > 0:
            self.save_current_page_state()
            self.page_index -= 1
            self.load_page()

    def next_page(self):
        if self.is_pdf and self.page_index < len(self.doc) - 1:
            self.save_current_page_state()
            self.page_index += 1
            self.load_page()

    # ------------------------------------------------------------------
    # Per-page workspace persistence
    # ------------------------------------------------------------------

    def save_current_page_state(self):
        """Keep the current page workspace in memory before leaving the page."""
        if not self.is_pdf or self.rgb is None:
            return

        self.page_states[self.page_index] = {
            # Detection result includes diagnostic stage images. deepcopy makes
            # the saved state independent of later edits/re-runs on other pages.
            "detection_result": copy.deepcopy(self.detection_result),

            # Human-edit workspace.
            "regions": copy.deepcopy(self.regions),
            "groups": copy.deepcopy(self.groups),
            "layer_order": list(self.layer_order),
            "selected_id": self.selected_id,

            # View state.
            "detect_zoom": float(self.detect_zoom),
            "edit_zoom": float(self.edit_zoom),
            "detect_fit": bool(self.detect_fit),
            "edit_fit": bool(self.edit_fit),
            "detect_stage": self.detect_stage_var.get(),
            "template_status": self.template_status_var.get(),

            # Preserve counters so IDs never collide after returning to a page.
            "region_counter": int(self.region_counter),
            "group_counter": int(self.group_counter),
        }

    def restore_page_state(self, page_index):
        """Restore annotations, layers, selection and views for one PDF page."""
        state = self.page_states.get(page_index)
        if not state:
            return

        self.detection_result = copy.deepcopy(state.get("detection_result"))
        self.regions = copy.deepcopy(state.get("regions", []))
        self.groups = copy.deepcopy(state.get("groups", {}))
        self.layer_order = list(state.get("layer_order", []))
        self.selected_id = state.get("selected_id")

        self.detect_zoom = float(state.get("detect_zoom", 1.0))
        self.edit_zoom = float(state.get("edit_zoom", 1.0))
        self.detect_fit = bool(state.get("detect_fit", True))
        self.edit_fit = bool(state.get("edit_fit", True))

        stage = state.get("detect_stage")
        if stage:
            self.detect_stage_var.set(stage)

        self.template_status_var.set(
            state.get("template_status", "Template memory: not checked yet")
        )

        # Counters are document-global. Never move them backwards when
        # restoring an older page.
        self.region_counter = max(
            self.region_counter,
            int(state.get("region_counter", 0)),
        )
        self.group_counter = max(
            self.group_counter,
            int(state.get("group_counter", 0)),
        )

        # If a previously selected layer was deleted before page switch,
        # gracefully clear the stale selection.
        if self.selected_id and not self.get_region(self.selected_id):
            self.selected_id = None

    def snapshot_current_page(self):
        """Explicit alias used before operations that should persist page state."""
        self.save_current_page_state()

    # ------------------------------------------------------------------
    # Detection tab
    # ------------------------------------------------------------------

    def run_detection(self):
        if self.rgb is None:
            return

        try:
            family = self.enforce_job_family()

            engine = DetectionEngine(
                adaptive_block=self.detect_vars["adaptive_block"].get(),
                adaptive_c=self.detect_vars["adaptive_c"].get(),
                line_scale=self.detect_vars["line_scale"].get(),
                min_component_area=self.detect_vars["min_component_area"].get(),
                char_join_x=self.detect_vars["char_join_x"].get(),
                char_join_y=self.detect_vars["char_join_y"].get(),
                block_join_x=self.detect_vars["block_join_x"].get(),
                block_join_y=self.detect_vars["block_join_y"].get(),
            )

            result = engine.run(self.rgb)
            base_proposals = copy.deepcopy(result["proposals"])

            memory, meta = self.load_template_regions(family)

            assisted = copy.deepcopy(base_proposals)
            suppressed = 0

            if memory:
                mem_boxes = [m["bbox"] for m in memory]
                kept = []
                for p in assisted:
                    if any(box_iou(p["bbox"], mb) > 0.30 for mb in mem_boxes):
                        suppressed += 1
                    else:
                        kept.append(p)

                assisted = kept
                for m in memory:
                    assisted.append({
                        "layout_type": m["layout_type"],
                        "bbox": m["bbox"],
                        "confidence": m["confidence"],
                        "source": m["source"],
                        "role": m.get("role", ""),
                        "angle": m.get("angle", 0.0),
                    })

            assisted.sort(key=lambda p: (p["bbox"][1], p["bbox"][0]))

            # Preserve the engine's original region rendering as "Base regions".
            result["stages"]["Base regions"] = result["stages"].get(
                "Regions", self.rgb
            )

            assisted_vis = self.rgb.copy()
            for p in assisted:
                x1, y1, x2, y2 = map(int, p["bbox"])
                source = p.get("source", "")
                if source.startswith("template"):
                    color = (180, 70, 180)  # memory proposal
                elif p["layout_type"] == "table":
                    color = (30, 160, 30)
                else:
                    color = (30, 100, 220)

                cv2.rectangle(
                    assisted_vis,
                    (x1, y1),
                    (x2, y2),
                    color,
                    4,
                )
                label = p["layout_type"]
                if source.startswith("template"):
                    label = "MEMORY " + label
                cv2.putText(
                    assisted_vis,
                    label,
                    (x1, max(20, y1 - 7)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.52,
                    color,
                    2,
                    cv2.LINE_AA,
                )

            result["stages"]["Assisted regions"] = assisted_vis
            result["stages"]["Regions"] = assisted_vis

            result["base_proposals"] = base_proposals
            result["proposals"] = assisted
            result["template_meta"] = meta
            result["stats"]["base_proposals"] = len(base_proposals)
            result["stats"]["memory_regions"] = len(memory)
            result["stats"]["memory_suppressed"] = suppressed
            result["stats"]["proposals"] = len(assisted)

            self.detection_result = result

            if meta["operational"]:
                self.template_status_var.set(
                    "TEMPLATE MEMORY: ACTIVE\n"
                    f"Family: {family}\n"
                    f"Matched: {meta['example']}\n"
                    f"Alignment: {meta['alignment']}\n"
                    f"Match evidence: {meta['match_score']} "
                    f"(good={meta.get('good_matches', 0)}, "
                    f"inliers={meta.get('inliers', 0)})\n"
                    f"Transferred: {meta['regions_transferred']} regions; "
                    f"suppressed {suppressed} overlapping base proposals."
                )
            else:
                self.template_status_var.set(
                    "TEMPLATE MEMORY: NOT ACTIVE\n"
                    f"Family: {family}\n"
                    f"Reason: {meta.get('reason', 'No usable corrected example.')}"
                )

            self.redraw_detection()
            self.update_detection_stats()

            self.status_var.set(
                f"Detection complete: {len(base_proposals)} base → "
                f"{len(assisted)} assisted proposals."
            )
            self.snapshot_current_page()

        except Exception as exc:
            messagebox.showerror("Detection", f"{type(exc).__name__}: {exc}")

    def update_detection_stats(self):
        self.detect_stats_text.delete("1.0", tk.END)
        if not self.detection_result:
            return

        s = self.detection_result["stats"]
        meta = self.detection_result.get("template_meta", {})

        txt = (
            f"Components: {s['components']}\n"
            f"Text lines: {s['text_lines']}\n"
            f"Text blocks: {s['text_blocks']}\n"
            f"Table candidates: {s['tables']}\n\n"
            f"Base proposals: {s.get('base_proposals', s['proposals'])}\n"
            f"Memory proposals: {s.get('memory_regions', 0)}\n"
            f"Base proposals replaced by memory: "
            f"{s.get('memory_suppressed', 0)}\n"
            f"Final assisted proposals: {s['proposals']}\n\n"
            f"Horizontal rule kernel: {s['horizontal_kernel']} px\n"
            f"Vertical rule kernel: {s['vertical_kernel']} px\n\n"
        )

        if meta.get("operational"):
            txt += (
                "Family assistance: YES\n"
                f"Template: {meta.get('example')}\n"
                f"Alignment: {meta.get('alignment')}\n"
                f"Match evidence score: {meta.get('match_score')}\n\n"
            )
        else:
            txt += "Family assistance: NO\n\n"

        txt += (
            "Compare 'Base regions' with 'Assisted regions'.\n"
            "Purple MEMORY boxes came from prior corrected examples.\n\n"
            "Workflow:\n"
            "1. Tune base detection.\n"
            "2. Inspect family-assisted result.\n"
            "3. Send the assisted proposals to Human Edit."
        )

        self.detect_stats_text.insert("1.0", txt)

    def redraw_detection(self):
        self.detect_canvas.delete("all")

        if self.rgb is None:
            return

        if self.detection_result:
            arr = self.detection_result["stages"].get(
                self.detect_stage_var.get(), self.rgb
            )
        else:
            arr = self.rgb

        h, w = arr.shape[:2]

        if self.detect_fit:
            self.root.update_idletasks()
            cw = max(500, self.detect_canvas.winfo_width() - 30)
            ch = max(500, self.detect_canvas.winfo_height() - 30)
            scale = min(1.0, cw / w, ch / h)
            self.detect_zoom = scale
        else:
            scale = self.detect_zoom

        dw, dh = max(1, int(w * scale)), max(1, int(h * scale))
        pil = Image.fromarray(arr)
        if scale != 1.0:
            pil = pil.resize((dw, dh), Image.Resampling.LANCZOS)

        self.detect_photo = ImageTk.PhotoImage(pil)
        self.detect_canvas.create_image(0, 0, image=self.detect_photo, anchor="nw")
        self.detect_canvas.configure(scrollregion=(0, 0, dw, dh))

    def zoom_detection(self, factor):
        if self.rgb is None:
            return
        self.detect_fit = False
        self.detect_zoom = max(0.10, min(4.0, self.detect_zoom * factor))
        self.redraw_detection()

    def fit_detection(self):
        self.detect_fit = True
        self.redraw_detection()

    def send_to_edit(self):
        if not self.detection_result:
            self.run_detection()
            if not self.detection_result:
                return

        self.regions = []
        self.groups = {}
        self.layer_order = []
        self.selected_id = None

        g_text = self.create_group("Text")
        g_tables = self.create_group("Tables")
        g_other = self.create_group("Other")

        has_memory = any(
            p.get("source", "").startswith("template")
            for p in self.detection_result["proposals"]
        )
        g_memory = self.create_group("Memory") if has_memory else None

        for p in self.detection_result["proposals"]:
            source = p.get("source", "")

            if source.startswith("template") and g_memory is not None:
                gid = g_memory.id
            elif p["layout_type"] == "table":
                gid = g_tables.id
            elif p["layout_type"] == "text_block":
                gid = g_text.id
            else:
                gid = g_other.id

            self.add_region(
                p["layout_type"],
                p["bbox"],
                source=source,
                confidence=p.get("confidence", 0.0),
                role=p.get("role", ""),
                group_id=gid,
                angle=p.get("angle", 0.0),
            )

        self.refresh_layer_tree()
        self.redraw_edit()
        self.notebook.select(self.edit_tab)

        meta = self.detection_result.get("template_meta", {})
        if meta.get("operational"):
            self.status_var.set(
                f"Human Edit loaded assisted detection using {meta.get('example')}."
            )
        else:
            self.status_var.set("Human Edit loaded base detection; no template memory matched.")

        self.snapshot_current_page()

    # ------------------------------------------------------------------
    # Region / group management
    # ------------------------------------------------------------------

    def next_region_id(self):
        self.region_counter += 1
        return f"R{self.region_counter:04d}"

    def next_group_id(self):
        self.group_counter += 1
        return f"G{self.group_counter:04d}"

    def create_group(self, name):
        g = LayerGroup(id=self.next_group_id(), name=name)
        self.groups[g.id] = g
        return g

    def add_region(
        self,
        layout_type,
        bbox,
        source="user",
        confidence=0.0,
        role="",
        group_id="",
        modified=False,
        angle=0.0,
    ):
        if self.rgb is None:
            return None

        h, w = self.rgb.shape[:2]
        b = ensure_bbox(bbox, w, h)

        if b[2] - b[0] < 5 or b[3] - b[1] < 5:
            return None

        r = Region(
            id=self.next_region_id(),
            layout_type=layout_type,
            role=role,
            bbox=b,
            source=source,
            confidence=float(confidence),
            user_modified=modified,
            group_id=group_id,
            angle=float(angle),
        )
        self.regions.append(r)
        self.layer_order.append(r.id)
        return r

    def get_region(self, rid):
        for r in self.regions:
            if r.id == rid:
                return r
        return None

    def group_effective_visible(self, r):
        if not r.visible:
            return False
        if r.group_id and r.group_id in self.groups:
            return self.groups[r.group_id].visible
        return True

    def group_effective_locked(self, r):
        if r.locked:
            return True
        if r.group_id and r.group_id in self.groups:
            return self.groups[r.group_id].locked
        return False

    def ordered_regions(self):
        by_id = {r.id: r for r in self.regions}
        return [by_id[rid] for rid in self.layer_order if rid in by_id]

    # ------------------------------------------------------------------
    # Layer panel
    # ------------------------------------------------------------------

    def refresh_layer_tree(self):
        self._suppress_layer_event = True
        try:
            self.layer_tree.delete(*self.layer_tree.get_children())

            # Groups.
            for gid, g in self.groups.items():
                self.layer_tree.insert(
                    "",
                    "end",
                    iid=gid,
                    text=g.name,
                    values=("Y" if g.visible else "N", "Y" if g.locked else "N", "GROUP"),
                    open=True,
                )

                # Topmost layer shown first, Photoshop-like.
                members = [
                    r for r in reversed(self.ordered_regions())
                    if r.group_id == gid
                ]
                for r in members:
                    self.layer_tree.insert(
                        gid,
                        "end",
                        iid=r.id,
                        text=r.role or r.id,
                        values=(
                            "Y" if r.visible else "N",
                            "Y" if r.locked else "N",
                            r.layout_type,
                        ),
                    )

            # Ungrouped.
            ungrouped = [
                r for r in reversed(self.ordered_regions())
                if not r.group_id or r.group_id not in self.groups
            ]
            for r in ungrouped:
                self.layer_tree.insert(
                    "",
                    "end",
                    iid=r.id,
                    text=r.role or r.id,
                    values=(
                        "Y" if r.visible else "N",
                        "Y" if r.locked else "N",
                        r.layout_type,
                    ),
                )

            if self.selected_id and self.layer_tree.exists(self.selected_id):
                self.layer_tree.selection_set(self.selected_id)
                self.layer_tree.see(self.selected_id)

        finally:
            self._suppress_layer_event = False

    def on_layer_select(self, _event=None):
        if self._suppress_layer_event:
            return

        selected = self.layer_tree.selection()
        # Canvas selection follows the first selected actual region.
        rid = next((x for x in selected if self.get_region(x)), None)
        if rid:
            self.select_region(rid, sync_tree=False)

    def on_layer_double_click(self, event):
        item = self.layer_tree.identify_row(event.y)
        col = self.layer_tree.identify_column(event.x)
        if not item:
            return

        # Double click Vis / Lock columns for fast layer behavior.
        if col == "#1":
            self.toggle_items_visibility([item])
        elif col == "#2":
            self.toggle_items_lock([item])

    def selected_layer_items(self):
        return list(self.layer_tree.selection())

    def new_group(self):
        name = simpledialog.askstring("New group", "Group name:")
        if not name:
            return
        self.create_group(name.strip())
        self.refresh_layer_tree()
        self.snapshot_current_page()

    def group_selected(self):
        items = [x for x in self.selected_layer_items() if self.get_region(x)]
        if not items:
            messagebox.showinfo("Group", "Select one or more region layers first.")
            return

        name = simpledialog.askstring("Group selected", "New group name:")
        if not name:
            return

        g = self.create_group(name.strip())
        for rid in items:
            r = self.get_region(rid)
            if r:
                r.group_id = g.id
                r.user_modified = True

        self.refresh_layer_tree()
        self.redraw_edit()
        self.snapshot_current_page()

    def ungroup_selected(self):
        for item in self.selected_layer_items():
            r = self.get_region(item)
            if r:
                r.group_id = ""
                r.user_modified = True
        self.refresh_layer_tree()
        self.redraw_edit()
        self.snapshot_current_page()

    def toggle_items_visibility(self, items):
        for item in items:
            if item in self.groups:
                self.groups[item].visible = not self.groups[item].visible
            else:
                r = self.get_region(item)
                if r:
                    r.visible = not r.visible
        self.refresh_layer_tree()
        self.redraw_edit()
        self.snapshot_current_page()

    def toggle_layer_visibility(self):
        items = self.selected_layer_items()
        if items:
            self.toggle_items_visibility(items)

    def toggle_items_lock(self, items):
        for item in items:
            if item in self.groups:
                self.groups[item].locked = not self.groups[item].locked
            else:
                r = self.get_region(item)
                if r:
                    r.locked = not r.locked
        self.refresh_layer_tree()
        self.redraw_edit()
        self.snapshot_current_page()

    def toggle_layer_lock(self):
        items = self.selected_layer_items()
        if items:
            self.toggle_items_lock(items)

    def move_layer(self, direction):
        """
        direction +1 = move up / closer to viewer
        direction -1 = move down / farther from viewer
        """
        items = [x for x in self.selected_layer_items() if self.get_region(x)]
        if len(items) != 1:
            return

        rid = items[0]
        if rid not in self.layer_order:
            return

        i = self.layer_order.index(rid)
        j = i + direction
        if 0 <= j < len(self.layer_order):
            self.layer_order[i], self.layer_order[j] = (
                self.layer_order[j],
                self.layer_order[i],
            )
            self.refresh_layer_tree()
            self.redraw_edit()
            self.snapshot_current_page()

    # ------------------------------------------------------------------
    # Edit canvas / zoom
    # ------------------------------------------------------------------

    def redraw_edit(self):
        self.edit_canvas.delete("all")
        if self.rgb is None:
            return

        h, w = self.rgb.shape[:2]

        if self.edit_fit:
            self.root.update_idletasks()
            cw = max(500, self.edit_canvas.winfo_width() - 30)
            ch = max(500, self.edit_canvas.winfo_height() - 30)
            scale = min(1.0, cw / w, ch / h)
            self.edit_zoom = scale
        else:
            scale = self.edit_zoom

        dw, dh = max(1, int(w * scale)), max(1, int(h * scale))
        pil = Image.fromarray(self.rgb)
        if scale != 1.0:
            pil = pil.resize((dw, dh), Image.Resampling.LANCZOS)

        self.edit_photo = ImageTk.PhotoImage(pil)
        self.edit_canvas.create_image(0, 0, image=self.edit_photo, anchor="nw")
        self.edit_canvas.configure(scrollregion=(0, 0, dw, dh))

        # Draw bottom -> top.
        for r in self.ordered_regions():
            if self.group_effective_visible(r):
                self.draw_edit_region(r)

        self.edit_zoom_label.configure(text=f"{self.edit_zoom * 100:.0f}%")

    def redraw_edit_overlays(self):
        self.edit_canvas.delete("region")
        self.edit_canvas.delete("handle")
        for r in self.ordered_regions():
            if self.group_effective_visible(r):
                self.draw_edit_region(r)

    def draw_edit_region(self, r):
        s = self.edit_zoom
        color = TYPE_COLORS.get(r.layout_type, "#616161")
        selected = r.id == self.selected_id

        corners = rotated_region_corners(r.bbox, r.angle)
        pts = []
        for x, y in corners:
            pts.extend([x * s, y * s])

        self.edit_canvas.create_polygon(
            *pts,
            fill="",
            outline=color,
            width=4 if selected else 2,
            tags=("region", r.id),
        )

        # Label follows the first (top-left local) rotated corner.
        lx, ly = corners[0]
        lx *= s
        ly *= s

        label = r.role or r.layout_type
        label_w = max(70, min(220, len(label) * 7))

        self.edit_canvas.create_rectangle(
            lx,
            ly,
            lx + label_w,
            ly + 18,
            fill=color,
            outline=color,
            tags=("region", r.id),
        )
        self.edit_canvas.create_text(
            lx + 4,
            ly + 9,
            text=label,
            fill="white",
            anchor="w",
            font=("", 9, "bold"),
            tags=("region", r.id),
        )

        if selected and not self.group_effective_locked(r):
            size = 6
            for cx, cy in corners:
                cx *= s
                cy *= s
                self.edit_canvas.create_rectangle(
                    cx-size, cy-size, cx+size, cy+size,
                    fill="white",
                    outline=color,
                    width=2,
                    tags=("handle", r.id),
                )

    def zoom_edit(self, factor):
        if self.rgb is None:
            return
        self.edit_fit = False
        self.edit_zoom = max(0.10, min(5.0, self.edit_zoom * factor))
        self.redraw_edit()

    def fit_edit(self):
        self.edit_fit = True
        self.redraw_edit()

    def select_region(self, rid, sync_tree=True):
        r = self.get_region(rid)
        if not r:
            return

        self.selected_id = rid
        self.layout_var.set(r.layout_type)
        self.role_var.set(r.role)
        self.update_geometry_fields()

        if sync_tree and self.layer_tree.exists(rid):
            self._suppress_layer_event = True
            try:
                self.layer_tree.selection_set(rid)
                self.layer_tree.see(rid)
            finally:
                self._suppress_layer_event = False

        self.redraw_edit()

    def toggle_draw(self):
        if self.rgb is None:
            return
        self.edit_mode = "draw" if self.edit_mode != "draw" else "select"
        self.draw_btn.configure(
            text="Drawing..." if self.edit_mode == "draw" else "Draw region"
        )
        self.edit_canvas.configure(
            cursor="crosshair" if self.edit_mode == "draw" else "arrow"
        )

    def cancel_draw(self):
        self.edit_mode = "select"
        self.draw_btn.configure(text="Draw region")
        self.edit_canvas.configure(cursor="arrow")
        self.drag_kind = None
        self.drag_start = None
        if self.temp_rect:
            self.edit_canvas.delete(self.temp_rect)
            self.temp_rect = None

    def display_to_image(self, x, y):
        return x / self.edit_zoom, y / self.edit_zoom

    def edit_canvas_xy(self, event):
        return self.edit_canvas.canvasx(event.x), self.edit_canvas.canvasy(event.y)

    def corner_hit(self, r, dx, dy, radius=12):
        corners = rotated_region_corners(r.bbox, r.angle)
        names = ["tl", "tr", "br", "bl"]
        for name, (cx, cy) in zip(names, corners):
            cx *= self.edit_zoom
            cy *= self.edit_zoom
            if math.hypot(dx - cx, dy - cy) <= radius:
                return name
        return None

    def point_in_region(self, r, ix, iy):
        pts = np.asarray(
            rotated_region_corners(r.bbox, r.angle),
            dtype=np.float32,
        )
        return cv2.pointPolygonTest(pts, (float(ix), float(iy)), False) >= 0

    def edit_canvas_press(self, event):
        if self.rgb is None:
            return

        dx, dy = self.edit_canvas_xy(event)
        ix, iy = self.display_to_image(dx, dy)

        if self.edit_mode == "draw":
            self.drag_kind = "draw"
            self.drag_start = (dx, dy)
            self.temp_rect = self.edit_canvas.create_rectangle(
                dx, dy, dx, dy,
                outline="#ffeb3b",
                width=2,
                dash=(5, 3),
            )
            return

        selected = self.get_region(self.selected_id) if self.selected_id else None
        if selected and self.group_effective_visible(selected) and not self.group_effective_locked(selected):
            corner = self.corner_hit(selected, dx, dy)
            if corner:
                if abs(float(selected.angle)) > 0.001:
                    self.status_var.set(
                        "Rotated region: resize with W/H + Anchor in the left Geometry panel."
                    )
                    return
                self.drag_kind = "resize"
                self.resize_corner = corner
                self.drag_start = (ix, iy)
                self.drag_origin_bbox = list(selected.bbox)
                return

        # Topmost visible, unlocked region wins. Layer panel remains the
        # preferred way to select hidden/occluded regions.
        for r in reversed(self.ordered_regions()):
            if not self.group_effective_visible(r):
                continue
            if self.point_in_region(r, ix, iy):
                self.select_region(r.id)
                if not self.group_effective_locked(r):
                    self.drag_kind = "move"
                    self.drag_start = (ix, iy)
                    self.drag_origin_bbox = list(r.bbox)
                return

        self.selected_id = None
        self.redraw_edit()

    def edit_canvas_drag(self, event):
        if self.rgb is None or not self.drag_kind:
            return

        dx, dy = self.edit_canvas_xy(event)

        if self.drag_kind == "draw":
            x0, y0 = self.drag_start
            self.edit_canvas.coords(self.temp_rect, x0, y0, dx, dy)
            return

        r = self.get_region(self.selected_id) if self.selected_id else None
        if not r or self.group_effective_locked(r):
            return

        ix, iy = self.display_to_image(dx, dy)
        sx, sy = self.drag_start
        h, w = self.rgb.shape[:2]

        if self.drag_kind == "move":
            ox1, oy1, ox2, oy2 = self.drag_origin_bbox
            ddx, ddy = ix - sx, iy - sy
            bw, bh = ox2 - ox1, oy2 - oy1
            nx1 = min(max(0, ox1 + ddx), w - bw)
            ny1 = min(max(0, oy1 + ddy), h - bh)
            r.bbox = [nx1, ny1, nx1 + bw, ny1 + bh]

        elif self.drag_kind == "resize":
            x1, y1, x2, y2 = self.drag_origin_bbox
            c = self.resize_corner
            if "l" in c:
                x1 = ix
            if "r" in c:
                x2 = ix
            if "t" in c:
                y1 = iy
            if "b" in c:
                y2 = iy
            r.bbox = ensure_bbox([x1, y1, x2, y2], w, h)

        r.user_modified = True
        r.source = "user_corrected"
        self.redraw_edit_overlays()

    def edit_canvas_release(self, event):
        if not self.drag_kind:
            return

        dx, dy = self.edit_canvas_xy(event)

        if self.drag_kind == "draw":
            x0, y0 = self.drag_start

            if self.temp_rect:
                self.edit_canvas.delete(self.temp_rect)
                self.temp_rect = None

            ix1, iy1 = self.display_to_image(x0, y0)
            ix2, iy2 = self.display_to_image(dx, dy)

            # If one group is selected in layer tree, new region goes there.
            gid = ""
            selected_layers = self.selected_layer_items()
            if len(selected_layers) == 1 and selected_layers[0] in self.groups:
                gid = selected_layers[0]

            r = self.add_region(
                self.layout_var.get() or "unknown",
                [ix1, iy1, ix2, iy2],
                source="user_added",
                confidence=1.0,
                role=self.role_var.get().strip(),
                group_id=gid,
                modified=True,
            )
            if r:
                self.select_region(r.id)

        self.drag_kind = None
        self.drag_start = None
        self.drag_origin_bbox = None
        self.resize_corner = None
        self.refresh_layer_tree()
        self.update_geometry_fields()
        self.redraw_edit()
        self.snapshot_current_page()

    def update_geometry_fields(self):
        r = self.get_region(self.selected_id) if self.selected_id else None
        if not r:
            self.geom_x_var.set("")
            self.geom_y_var.set("")
            self.geom_w_var.set("")
            self.geom_h_var.set("")
            self.angle_var.set("0")
            return

        anchor = self.anchor_var.get() or "Center"
        ax, ay = region_anchor_point(r.bbox, r.angle, anchor)
        _, _, w, h = region_center_size(r.bbox)

        self.geom_x_var.set(f"{ax:.2f}")
        self.geom_y_var.set(f"{ay:.2f}")
        self.geom_w_var.set(f"{w:.2f}")
        self.geom_h_var.set(f"{h:.2f}")
        self.angle_var.set(f"{float(r.angle):.2f}")

    def apply_geometry(self):
        r = self.get_region(self.selected_id) if self.selected_id else None
        if not r or self.rgb is None:
            return
        if self.group_effective_locked(r):
            self.status_var.set("Selected region is locked.")
            return

        try:
            anchor = self.anchor_var.get() or "Center"
            ax = float(self.geom_x_var.get())
            ay = float(self.geom_y_var.get())
            width = max(2.0, float(self.geom_w_var.get()))
            height = max(2.0, float(self.geom_h_var.get()))
            angle = float(self.angle_var.get())

            # Normalize to a readable [-180, 180) range.
            angle = ((angle + 180.0) % 360.0) - 180.0

            ox, oy = anchor_local_offset(anchor, width, height)
            rox, roy = rotate_vector(ox, oy, angle)

            cx = ax - rox
            cy = ay - roy

            h_page, w_page = self.rgb.shape[:2]

            # bbox stores the unrotated local rectangle; rotation is separate.
            bbox = [
                cx - width / 2.0,
                cy - height / 2.0,
                cx + width / 2.0,
                cy + height / 2.0,
            ]

            # Keep the local box center/size sane. Rotated corners may extend
            # slightly beyond the page; that is allowed for editing.
            bbox = ensure_bbox(bbox, w_page, h_page)

            r.bbox = bbox
            r.angle = angle
            r.user_modified = True
            r.source = "user_corrected"

            self.update_geometry_fields()
            self.refresh_layer_tree()
            self.redraw_edit()
            self.status_var.set(
                f"Geometry applied from {anchor}; rotation {angle:.1f}°."
            )
            self.snapshot_current_page()

        except ValueError:
            messagebox.showerror(
                "Geometry",
                "X, Y, Width, Height and Angle must be numeric."
            )

    def rotate_selected(self, delta):
        r = self.get_region(self.selected_id) if self.selected_id else None
        if not r:
            return
        if self.group_effective_locked(r):
            return

        # Preserve the currently selected anchor in page coordinates.
        anchor = self.anchor_var.get() or "Center"
        ax, ay = region_anchor_point(r.bbox, r.angle, anchor)
        _, _, width, height = region_center_size(r.bbox)

        new_angle = ((float(r.angle) + float(delta) + 180.0) % 360.0) - 180.0

        ox, oy = anchor_local_offset(anchor, width, height)
        rox, roy = rotate_vector(ox, oy, new_angle)
        cx = ax - rox
        cy = ay - roy

        r.bbox = [
            cx - width / 2.0,
            cy - height / 2.0,
            cx + width / 2.0,
            cy + height / 2.0,
        ]
        r.angle = new_angle
        r.user_modified = True
        r.source = "user_corrected"

        self.update_geometry_fields()
        self.redraw_edit()
        self.snapshot_current_page()

    def apply_labels(self):
        r = self.get_region(self.selected_id) if self.selected_id else None
        if not r:
            return

        r.layout_type = self.layout_var.get() or "unknown"
        r.role = self.role_var.get().strip()
        r.user_modified = True
        r.source = "user_corrected"

        self.refresh_layer_tree()
        self.redraw_edit()
        self.snapshot_current_page()

    def delete_selected(self):
        items = [x for x in self.selected_layer_items() if self.get_region(x)]
        if not items and self.selected_id:
            items = [self.selected_id]

        if not items:
            return

        remove = set(items)
        self.regions = [r for r in self.regions if r.id not in remove]
        self.layer_order = [rid for rid in self.layer_order if rid not in remove]

        if self.selected_id in remove:
            self.selected_id = None

        self.refresh_layer_tree()
        self.redraw_edit()
        self.snapshot_current_page()

    # ------------------------------------------------------------------
    # Template memory
    # ------------------------------------------------------------------

    def load_template_regions(self, family):
        """Return (transferred_regions, match_metadata).

        Metadata is intentionally user-facing: it explains whether memory
        operated, which corrected example was selected, and how alignment ran.
        """
        examples = self.store.list_examples(family)[:8]

        meta = {
            "operational": False,
            "family": family,
            "example": None,
            "alignment": "none",
            "match_score": 0.0,
            "regions_transferred": 0,
            "reason": "",
        }

        if not examples:
            meta["reason"] = "No corrected examples exist for this family yet."
            return [], meta

        if self.rgb is None:
            meta["reason"] = "No current page image."
            return [], meta

        current_gray = cv2.cvtColor(self.rgb, cv2.COLOR_RGB2GRAY)
        orb = cv2.ORB_create(nfeatures=2500)
        kp2, des2 = orb.detectAndCompute(current_gray, None)

        best_ex = examples[0]
        best_H = None
        best_score = -1.0
        best_good = 0
        best_inliers = 0

        if des2 is not None and len(kp2) >= 8:
            matcher = cv2.BFMatcher(cv2.NORM_HAMMING)

            for ex in examples:
                img_path = ex / "page.png"
                if not img_path.exists():
                    continue

                tgray = cv2.imread(str(img_path), cv2.IMREAD_GRAYSCALE)
                if tgray is None:
                    continue

                kp1, des1 = orb.detectAndCompute(tgray, None)
                if des1 is None or len(kp1) < 8:
                    continue

                pairs = matcher.knnMatch(des1, des2, k=2)
                good = []

                for pair in pairs:
                    if len(pair) == 2:
                        m, n = pair
                        if m.distance < 0.75 * n.distance:
                            good.append(m)

                if len(good) < 8:
                    score = float(len(good))
                    if score > best_score:
                        best_ex = ex
                        best_H = None
                        best_score = score
                        best_good = len(good)
                        best_inliers = 0
                    continue

                src_pts = np.float32(
                    [kp1[m.queryIdx].pt for m in good]
                ).reshape(-1, 1, 2)
                dst_pts = np.float32(
                    [kp2[m.trainIdx].pt for m in good]
                ).reshape(-1, 1, 2)

                H, mask = cv2.findHomography(
                    src_pts, dst_pts, cv2.RANSAC, 5.0
                )
                inliers = int(mask.sum()) if mask is not None else 0
                score = inliers + 0.1 * len(good)

                if score > best_score:
                    best_ex = ex
                    best_H = H
                    best_score = score
                    best_good = len(good)
                    best_inliers = inliers

        reg_path = best_ex / "regions.json"
        if not reg_path.exists():
            meta["reason"] = f"{best_ex.name} has no regions.json."
            return [], meta

        payload = json.loads(reg_path.read_text(encoding="utf-8"))
        tw, th = payload.get("page_size_px", [1, 1])
        ch, cw = self.rgb.shape[:2]

        out = []
        aligned_count = 0

        for d in payload.get("regions", []):
            b = d.get("bbox")
            if not b:
                continue

            nb = None
            source = "template_scaled"

            if best_H is not None:
                try:
                    x1, y1, x2, y2 = b
                    pts = np.float32(
                        [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]
                    ).reshape(-1, 1, 2)
                    t = cv2.perspectiveTransform(pts, best_H).reshape(-1, 2)
                    nb = [
                        float(t[:, 0].min()),
                        float(t[:, 1].min()),
                        float(t[:, 0].max()),
                        float(t[:, 1].max()),
                    ]
                    source = "template_aligned"
                    aligned_count += 1
                except Exception:
                    nb = None

            if nb is None:
                x1, y1, x2, y2 = b
                nb = [
                    x1 / tw * cw,
                    y1 / th * ch,
                    x2 / tw * cw,
                    y2 / th * ch,
                ]

            nb = ensure_bbox(nb, cw, ch)

            out.append({
                "layout_type": d.get("layout_type", "unknown"),
                "role": d.get("role", ""),
                "bbox": nb,
                "confidence": min(
                    0.98,
                    0.75 + max(0, best_score) / 150,
                ),
                "source": source,
                "angle": float(d.get("angle", 0.0)),
            })

        meta.update({
            "operational": bool(out),
            "example": best_ex.name,
            "alignment": (
                "ORB + homography"
                if best_H is not None and aligned_count
                else "normalized-page fallback"
            ),
            "match_score": round(max(0.0, float(best_score)), 2),
            "good_matches": int(best_good),
            "inliers": int(best_inliers),
            "regions_transferred": len(out),
            "reason": (
                "Corrected family example transferred into detection."
                if out else
                "Matched example contained no usable regions."
            ),
        })

        return out, meta


    # ------------------------------------------------------------------
    # ML features / saving
    # ------------------------------------------------------------------

    def region_features(self, bbox):
        h, w = self.rgb.shape[:2]
        x1, y1, x2, y2 = [int(round(v)) for v in bbox]

        x1 = max(0, min(w - 1, x1))
        x2 = max(x1 + 1, min(w, x2))
        y1 = max(0, min(h - 1, y1))
        y2 = max(y1 + 1, min(h, y2))

        crop = self.rgb[y1:y2, x1:x2]
        gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)

        bw = x2 - x1
        bh = y2 - y1

        _, inv = cv2.threshold(
            gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
        )

        edges = cv2.Canny(gray, 80, 180)

        hk = cv2.getStructuringElement(cv2.MORPH_RECT, (max(5, bw // 8), 1))
        vk = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(5, bh // 8)))

        hh = cv2.morphologyEx(inv, cv2.MORPH_OPEN, hk)
        vv = cv2.morphologyEx(inv, cv2.MORPH_OPEN, vk)

        return [
            x1 / w,
            y1 / h,
            x2 / w,
            y2 / h,
            bw / w,
            bh / h,
            (bw * bh) / (w * h),
            bw / max(1, bh),
            float(np.count_nonzero(inv)) / max(1, inv.size),
            float(np.count_nonzero(edges)) / max(1, edges.size),
            float(np.count_nonzero(hh)) / max(1, hh.size),
            float(np.count_nonzero(vv)) / max(1, vv.size),
        ]

    def train_model(self, family):
        try:
            from sklearn.pipeline import Pipeline
            from sklearn.preprocessing import StandardScaler
            from sklearn.linear_model import SGDClassifier
        except ImportError:
            return False, ("ML is not active because scikit-learn is not installed. "
                       "Template memory was still updated successfully.")

        path = self.store.training_path(family)
        if not path.exists():
            return False, "No training data yet."

        X, y = [], []

        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(line)
                if d.get("features") and d.get("target"):
                    X.append(d["features"])
                    y.append(d["target"])
            except Exception:
                pass

        classes = sorted(set(y))
        if len(X) < 6 or len(classes) < 2:
            return False, (
                f"Need 6 corrected regions across 2 classes "
                f"(currently {len(X)} / {len(classes)})."
            )

        model = Pipeline([
            ("scale", StandardScaler()),
            ("clf", SGDClassifier(
                loss="log_loss",
                alpha=0.0005,
                max_iter=3000,
                tol=1e-4,
                random_state=42,
                class_weight="balanced",
            )),
        ])
        model.fit(np.asarray(X, dtype=float), np.asarray(y, dtype=object))

        with open(self.store.model_path(family), "wb") as f:
            pickle.dump(model, f)

        return True, f"ML trained on {len(X)} regions / {len(classes)} classes."

    def save_and_learn(self):
        if self.rgb is None or self.path is None or not self.regions:
            messagebox.showinfo("Save", "No edited regions to save.")
            return

        self.snapshot_current_page()

        family = self.family_var.get().strip() or "default"
        ex = self.store.next_example_dir(family)

        cv2.imwrite(
            str(ex / "page.png"),
            cv2.cvtColor(self.rgb, cv2.COLOR_RGB2BGR),
        )

        h, w = self.rgb.shape[:2]

        records = []
        for i, r in enumerate(self.ordered_regions(), start=1):
            records.append({
                "id": f"R{i:03d}",
                "layout_type": r.layout_type,
                "role": r.role,
                "bbox": [round(float(v), 2) for v in r.bbox],
                "bbox_normalized": [
                    round(v, 6) for v in r.normalized_bbox(w, h)
                ],
                "source_before_save": r.source,
                "user_modified": bool(r.user_modified),
                "group": self.groups[r.group_id].name
                    if r.group_id in self.groups else "",
                "visible": r.visible,
                "locked": r.locked,
                "angle": round(float(r.angle), 4),
            })

        payload = {
            "schema": "adaptive-document-example/v0.6",
            "family": family,
            "source_document": str(self.path),
            "page": self.page_index + 1 if self.is_pdf else 1,
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "page_size_px": [w, h],
            "regions": records,
        }

        (ex / "regions.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        train_path = self.store.training_path(family)
        with open(train_path, "a", encoding="utf-8") as f:
            for r in self.regions:
                f.write(json.dumps({
                    "saved_at": datetime.now().isoformat(timespec="seconds"),
                    "example": ex.name,
                    "target": r.layout_type,
                    "role": r.role,
                    "features": self.region_features(r.bbox),
                }, ensure_ascii=False) + "\n")

        trained, msg = self.train_model(family)
        self.refresh_learning_status()

        messagebox.showinfo(
            "Saved",
            f"Saved corrected example:\n{ex}\n\n"
            f"Regions: {len(self.regions)}\n"
            f"Template memory is available immediately.\n\n"
            f"{msg}",
        )

        self.record_job_correction(ex.name, len(self.regions))

        self.status_var.set(
            f"Saved {ex.name}. "
            + ("ML updated." if trained else "Template memory updated.")
        )

    def refresh_learning_status(self):
        family = self.family_var.get().strip() or "default"
        s = self.store.status(family)

        try:
            import sklearn
            sk_installed = True
            sk_text = f"installed ({sklearn.__version__})"
        except Exception:
            sk_installed = False
            sk_text = "NOT installed"

        if not sk_installed:
            mode = "TEMPLATE MEMORY ONLY"
            ml_line = "ML classifier: unavailable"
        elif s["model_exists"]:
            mode = "TEMPLATE + ML"
            ml_line = "ML classifier: ready"
        else:
            mode = "TEMPLATE MEMORY; ML WAITING FOR DATA"
            ml_line = "ML classifier: not trained yet"

        self.learning_status_var.set(
            f"Learning mode: {mode}\n"
            f"Family: {family}\n"
            f"Corrected examples: {s['examples']}\n"
            f"Training regions: {s['training_samples']}\n"
            f"Observed classes: {s['classes']}\n"
            f"{ml_line}\n"
            f"scikit-learn: {sk_text}"
        )


def main():
    root = tk.Tk()

    # Surface Tk callback errors instead of grey/frozen failure.
    def report_callback_exception(exc_type, exc_value, exc_tb):
        import traceback
        details = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        print(details)
        try:
            messagebox.showerror("Application error", details[-7000:])
        except Exception:
            pass

    root.report_callback_exception = report_callback_exception

    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
