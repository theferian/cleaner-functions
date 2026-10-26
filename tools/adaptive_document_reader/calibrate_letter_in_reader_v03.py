"""Visual calibration mode for the EXISTING Adaptive Document Annotator v0.6.

Loads screenshot-derived region suggestions into native editable Human Edit layers;
uses the existing detection pipeline and Save & Learn. Never marks field values
verified and never writes to the source PDF or Cleaner project solutions.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tkinter as tk
from tkinter import ttk, messagebox

from open_letter_in_reader import (
    DirectLetterApp,
    DEFAULT_PDF,
    DEFAULT_REFERENCE,
    DEFAULT_DATE,
    DEFAULT_FAMILY,
)

DEFAULT_PROFILE = Path(__file__).with_name("azd_outgoing_letter_calibration_v01.json")


def load_profile(profile_path: Path) -> dict:
    payload = json.loads(profile_path.read_text(encoding="utf-8"))
    if payload.get("schema") != "adaptive-reader.visual-calibration/0.1":
        raise ValueError("Unsupported calibration schema")
    crop = payload["page_crop_in_screenshot"]
    if len(crop) != 4 or crop[2] <= crop[0] or crop[3] <= crop[1]:
        raise ValueError("Invalid screenshot crop")
    valid_types = {"form_field", "image", "text_block", "title", "signature", "footer", "header", "table", "stamp"}
    all_ids = []
    for page in payload["target_pages"]:
        for entry in page["elements"]:
            if entry["type"] not in valid_types:
                raise ValueError(f"Invalid native layout type: {entry['type']}")
            if len(entry["screenshot_bbox"]) != 4:
                raise ValueError("Calibration bbox must contain four numbers")
            if not entry["role"] or not entry["field_id"]:
                raise ValueError("Every region must have role and field_id")
            all_ids.append((page["page"], entry["field_id"]))
    if len(all_ids) != len(set(all_ids)):
        raise ValueError("Duplicate region field_id in same page")
    return payload


def normalized_box(box, screenshot_crop):
    x1, y1, x2, y2 = screenshot_crop
    result = [
        (box[0] - x1) / (x2 - x1),
        (box[1] - y1) / (y2 - y1),
        (box[2] - x1) / (x2 - x1),
        (box[3] - y1) / (y2 - y1),
    ]
    if not (0 <= result[0] < result[2] <= 1 and 0 <= result[1] < result[3] <= 1):
        raise ValueError(f"BBox outside screenshot page: {box}")
    return result


def target_regions(profile, page_num, page_width, page_height):
    """Return proposed pixel regions, not verified detections."""
    crop = profile["page_crop_in_screenshot"]
    matching_pages = [p for p in profile["target_pages"] if p["page"] == page_num]
    if not matching_pages:
        return [], None
    page = matching_pages[0]
    observed_ratio = page_width / page_height
    target_ratio = float(page["aspect_ratio"])
    if abs(observed_ratio - target_ratio) > 0.06:
        return [], f"PAGE_ASPECT_MISMATCH {observed_ratio:.3f} vs {target_ratio:.3f}"
    regions = []
    for entry in page["elements"]:
        box = normalized_box(entry["screenshot_bbox"], crop)
        regions.append({
            "field_id": entry["field_id"],
            "role": entry["role"],
            "layout_type": entry["type"],
            "optional": bool(entry.get("optional", False)),
            "bbox_normalized": box,
            "bbox": [box[0] * page_width, box[1] * page_height,
                     box[2] * page_width, box[3] * page_height],
            "confidence": None,
            "verification": "UNVERIFIED_SCREENSHOT_CALIBRATION",
        })
    return regions, None


def iou(box_a, box_b):
    x1 = max(box_a[0], box_b[0])
    y1 = max(box_a[1], box_b[1])
    x2 = min(box_a[2], box_b[2])
    y2 = min(box_a[3], box_b[3])
    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    def area(b):
        return max(0, b[2] - b[0]) * max(0, b[3] - b[1])
    return intersection / max(1e-9, area(box_a) + area(box_b) - intersection)


def calibration_audit(profile, page_num, w, h, native_proposals, applied_regions):
    targets, error = target_regions(profile, page_num, w, h)
    audit_rows = []
    for target in targets:
        candidates = [(iou(target["bbox"], p["bbox"]), p) for p in native_proposals]
        value, chosen = max(candidates, key=lambda x: x[0]) if candidates else (0.0, None)
        edited = next((r for r in applied_regions if r.role == target["role"] and r.source.startswith("screenshot_calibration")), None)
        audit_rows.append({
            "field_id": target["field_id"],
            "expected_role": target["role"],
            "target_bbox_normalized": [round(x, 5) for x in target["bbox_normalized"]],
            "best_native_geometry_iou": round(value, 4),
            "detector_geometry_hit_030": value >= .30,
            "best_native_type": chosen.get("layout_type") if chosen else None,
            "editable_region_present": edited is not None,
            "current_edit_bbox_normalized": [round(x/dim, 5) for x, dim in zip(edited.bbox, (w,h,w,h))] if edited else None,
            "optional": target["optional"],
            "verification": "NOT_VERIFIED",
        })
    required = [x for x in audit_rows if not x["optional"]]
    return {
        "schema": "adaptive-reader.calibration-audit/0.1",
        "profile_id": profile["profile_id"],
        "page": page_num,
        "page_size_px": [w, h],
        "warnings": [error] if error else [],
        "summary": {
            "target_regions": len(audit_rows),
            "required_regions": len(required),
            "native_geometry_hits_iou030": sum(x["detector_geometry_hit_030"] for x in required),
            "editable_target_regions": sum(x["editable_region_present"] for x in audit_rows),
            "source_fields_verified": 0,
        },
        "elements": audit_rows,
    }


class CalibrationApp(DirectLetterApp):
    def __init__(self, root, path, reference, expected_date, family, profile, audit_dir, mask_preview=False):
        self.mask_preview = bool(mask_preview)
        self.calibration_profile = profile
        self.calibration_dir = audit_dir
        self.calibration_pages: set[int] = set()
        self.calibration_groups: dict[int, str] = {}
        self.approved_calibration_pages: set[int] = set()
        self.calibration_label = tk.StringVar(value="Screenshot layout — unverified")
        super().__init__(root, path, reference, expected_date, family)
        bar = ttk.Frame(root, padding=(10, 2))
        ttk.Label(bar, textvariable=self.calibration_label).pack(side=tk.LEFT, padx=(0, 12))
        ttk.Button(bar, text="Evaluate detector", command=self.export_calibration_audit).pack(side=tk.LEFT, padx=3)
        ttk.Button(bar, text="Show / hide target", command=self.toggle_target).pack(side=tk.LEFT, padx=3)
        ttk.Button(bar, text="Mask / outline preview", command=self.toggle_mask_preview).pack(side=tk.LEFT, padx=3)
        ttk.Button(bar, text="Accept corrected layout", command=self.accept_target_layout).pack(side=tk.LEFT, padx=3)
        bar.pack(fill=tk.X, before=self.notebook)

    def _prepare_current_page(self):
        super()._prepare_current_page()
        idx = self.page_index
        if idx in self.calibration_pages or self.rgb is None or not self.detection_result:
            return
        h, w = self.rgb.shape[:2]
        targets, warning = target_regions(self.calibration_profile, idx + 1, w, h)
        if warning:
            self.calibration_label.set(f"NO TARGET: {warning}")
            return
        if not targets:
            self.calibration_label.set(f"No calibrated template for page {idx + 1}; native detector only")
            return
        group = self.create_group("Calibration targets — REVIEW BEFORE LEARNING")
        self.calibration_groups[idx] = group.id
        for entry in targets:
            self.add_region(
                entry["layout_type"], entry["bbox"],
                source="screenshot_calibration_unverified",
                confidence=0.0,
                role=entry["role"],
                group_id=group.id,
            )
        self.calibration_pages.add(idx)
        self.calibration_label.set(f"Page {idx + 1}: {len(targets)} screenshot-derived region targets (unverified)")
        self.refresh_layer_tree()
        self.redraw_edit()
        self.snapshot_current_page()

    def toggle_mask_preview(self):
        self.mask_preview = not self.mask_preview
        self.redraw_edit()

    def draw_edit_region(self, region):
        """Optional screenshot-like masked preview; native outline remains default."""
        if not (self.mask_preview and region.source.startswith("screenshot_calibration")):
            return super().draw_edit_region(region)
        from adaptive_document_annotator_v0_6 import rotated_region_corners
        s = self.edit_zoom
        corners = rotated_region_corners(region.bbox, region.angle)
        pts = [v * s for point in corners for v in point]
        selected = region.id == self.selected_id
        self.edit_canvas.create_polygon(
            *pts, fill="#111111", outline="#fb3b35" if selected else "#151515",
            width=2 if selected else 1, tags=("region", region.id),
        )
        center_x = sum(point[0] for point in corners) * s / 4
        center_y = sum(point[1] for point in corners) * s / 4
        self.edit_canvas.create_text(
            center_x, center_y, text=region.role,
            font=("", 10, "bold"), fill="#ff4b43",
            tags=("region", region.id),
        )
        if selected and not self.group_effective_locked(region):
            for x,y in corners:
                x,y=x*s,y*s
                self.edit_canvas.create_rectangle(
                    x-5,y-5,x+5,y+5, fill="white", outline="#ff4b43",
                    tags=("handle", region.id),
                )

    def toggle_target(self):
        gid = self.calibration_groups.get(self.page_index)
        group = self.groups.get(gid) if gid else None
        if group:
            group.visible = not group.visible
            self.refresh_layer_tree()
            self.redraw_edit()
            self.snapshot_current_page()

    def accept_target_layout(self):
        """Require an explicit operator decision before any learning is allowed."""
        gid = self.calibration_groups.get(self.page_index)
        group = self.groups.get(gid) if gid else None
        if group is None:
            messagebox.showwarning("Calibration", "No screenshot target on this page")
            return
        if not messagebox.askyesno(
            "Approve reviewed regions?",
            "Have you inspected and adjusted every region in the calibration group?\n\n"
            "Accept the CURRENT layout for this page? No source facts will be verified."
        ):
            return
        self.approved_calibration_pages.add(self.page_index)
        for r in self.regions:
            if r.group_id == gid:
                r.user_modified = True
                r.source = "screenshot_calibration_reviewed_by_user"
        self.calibration_label.set("Calibration layout reviewed. Save correction + learn to train template.")
        self.snapshot_current_page()

    def save_and_learn(self):
        """Save reviewed calibration boxes only, not unsupervised detector suggestions.

        Avoid contaminating the template-memory training set with unreviewed
        machine regions or screenshot coordinates that were not accepted.
        """
        gid = self.calibration_groups.get(self.page_index)
        if gid is None:
            messagebox.showwarning(
                "Calibration", "This page has no target calibration. "
                "Review it with native Human Edit and save using the original reader if needed."
            )
            return
        if self.page_index not in self.approved_calibration_pages:
            messagebox.showwarning(
                "Calibration not approved",
                "Review/adjust regions, then choose 'Accept corrected layout' before learning."
            )
            return
        reviewed = [r for r in self.ordered_regions() if r.group_id == gid]
        if not reviewed:
            messagebox.showwarning("Calibration", "No corrected target regions to save")
            return
        all_regions = self.regions
        all_order = self.layer_order
        try:
            self.regions = reviewed
            self.layer_order = [r.id for r in reviewed]
            super().save_and_learn()
        finally:
            self.regions = all_regions
            self.layer_order = all_order
            self.refresh_layer_tree()
            self.redraw_edit()
            self.snapshot_current_page()

    def export_calibration_audit(self):
        if self.rgb is None or not self.detection_result:
            messagebox.showwarning("Calibration", "Open and detect a page first")
            return
        h, w = self.rgb.shape[:2]
        audit = calibration_audit(
            self.calibration_profile,
            self.page_index + 1,
            w, h,
            self.detection_result.get("proposals", []),
            self.regions,
        )
        audit["source_pdf"] = str(self.path)
        audit["source_evidence"] = self.evidence_by_page.get(self.page_index, {})
        self.calibration_dir.mkdir(parents=True, exist_ok=True)
        out = self.calibration_dir / f"page_{self.page_index + 1:02d}_calibration_audit.json"
        out.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
        s = audit["summary"]
        self.calibration_label.set(
            f"Native geometric hits: {s['native_geometry_hits_iou030']}/{s['required_regions']}; "
            f"editable targets: {s['editable_target_regions']}/{s['target_regions']} (NOT verified)"
        )
        messagebox.showinfo("Calibration audit saved", str(out))
        return audit


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Open PDF in existing Adaptive Reader with screenshot layout calibration")
    p.add_argument("--pdf", type=Path, default=DEFAULT_PDF)
    p.add_argument("--reference", default=DEFAULT_REFERENCE)
    p.add_argument("--expected-date", default=DEFAULT_DATE)
    p.add_argument("--family", default=DEFAULT_FAMILY)
    p.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    p.add_argument("--audit-dir", type=Path, default=Path("working/source_registry/AZD_1404-3003_calibration"))
    p.add_argument("--mask-preview", action="store_true", help="Show red labels on black masks like screenshot (toggle in UI)")
    p.add_argument("--smoke-test", action="store_true", help=argparse.SUPPRESS)
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    profile = load_profile(args.profile)
    if not args.pdf.is_file():
        print(f"[ERROR] File missing: {args.pdf}", file=sys.stderr)
        return 2
    root = tk.Tk()
    app = CalibrationApp(root, args.pdf, args.reference, args.expected_date, args.family, profile, args.audit_dir, mask_preview=args.mask_preview)
    root.after(100, app.open_target)
    if args.smoke_test:
        def smoke():
            if not app.prepared_pages:
                print("[SMOKE] FAILED — document was not opened", file=sys.stderr, flush=True)
            else:
                h, w = app.rgb.shape[:2]
                report = calibration_audit(profile, app.page_index + 1, w, h,
                    app.detection_result.get('proposals', []), app.regions)
                print(f"[SMOKE] PASS pages={len(app.doc)} calibrated={len(app.calibration_pages)} "
                      f"labels={report['summary']['editable_target_regions']} required={report['summary']['required_regions']}", flush=True)
                if len(app.doc) > 1:
                    app.next_page()
                    app.prev_page()
                    print(f"[SMOKE] BACK_TO_FIRST labels={len([r for r in app.regions if r.source.startswith('screenshot_calibration')])}",flush=True)
            root.destroy()
        root.after(3500, smoke)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
