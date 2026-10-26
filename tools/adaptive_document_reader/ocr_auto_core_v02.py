"""Offline read-only regional OCR and persistent auto-run audit for card teaching.

No Cleaner state/solution updates. Results are provisional evidence only.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import time
from typing import Any

from card_teaching_core import compare_field

FIELDS = ("letter_date", "letter_reference")


def event_key(card: dict, event: dict, path: str | Path) -> str:
    parts = [str(card.get("sheet", "")), str(card.get("index", "")),
             event.get("direction", ""), event.get("reference", ""),
             event.get("date", ""), str(Path(path).resolve()).casefold()]
    file_path = Path(path)
    try:
        st = file_path.stat()
        parts.extend([str(st.st_size), str(st.st_mtime_ns)])
    except OSError:
        parts.append("missing")
    return hashlib.sha256("\u241f".join(parts).encode("utf-8")).hexdigest()[:24]


def load_completed(journal: Path) -> set[str]:
    keys = set()
    if not journal.exists():
        return keys
    with journal.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if item.get("processing_status") == "COMPLETED" and item.get("event_key"):
                keys.add(item["event_key"])
    return keys


def append_journal(journal: Path, record: dict) -> None:
    journal.parent.mkdir(parents=True, exist_ok=True)
    with journal.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
        f.flush()


def readiness(boxes: dict, meta: dict, require_alignment: bool = True, min_inliers: int = 8) -> tuple[bool, str]:
    if any(len(boxes.get(f, [])) != 1 for f in FIELDS):
        return False, "NEEDS_TEACHING: one date box and one reference box required"
    if not meta.get("operational"):
        return False, "NEEDS_TEACHING: no approved family example transferred"
    if require_alignment and (meta.get("alignment") != "ORB + homography" or int(meta.get("inliers") or 0) < min_inliers):
        return False, "NEEDS_REVIEW: insufficient verified alignment"
    return True, "READY"


def _valid_bbox(page, coords: list[float]):
    import pymupdf
    if len(coords) != 4:
        raise ValueError("bbox must have four coordinates")
    r = pymupdf.Rect(*map(float, coords)) & page.rect
    if r.is_empty or r.width < 3 or r.height < 3:
        raise ValueError("invalid field bbox")
    return r


def _ocr(image_path: Path, tesseract: str, langs: str, psm: int, stop: threading.Event,
         timeout: int = 45) -> tuple[str, str]:
    argv = [tesseract, str(image_path), "stdout", "-l", langs, "--psm", str(psm)]
    try:
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except (FileNotFoundError, OSError):
        return "", "OCR_UNAVAILABLE"
    since = time.monotonic()
    try:
        while proc.poll() is None:
            if stop.is_set():
                proc.kill(); proc.communicate()
                return "", "STOPPED"
            if time.monotonic() - since >= timeout:
                proc.kill(); proc.communicate()
                return "", "OCR_TIMEOUT"
            time.sleep(0.15)
        stdout, stderr = proc.communicate()
        if proc.returncode != 0:
            return "", "OCR_FAILED: " + stderr.decode("utf-8", errors="replace")[:160]
        return stdout.decode("utf-8", errors="replace"), "OCR_OK"
    finally:
        if proc.poll() is None:
            proc.kill(); proc.communicate()


def extract_regional_fields(pdf_path: Path, field_boxes: dict[str, list[float]],
                            expected: dict[str, str], tesseract: str = "tesseract",
                            langs: str = "fas+eng", psm: int = 6, dpi: int = 300,
                            stop: threading.Event | None = None) -> dict[str, Any]:
    """Open PDF locally in worker; OCR only field rectangles on first page."""
    import pymupdf
    stop = stop or threading.Event()
    out = {"fields": [], "pdf_sha256": None, "reader": "pymupdf+tesseract", "complete": False}
    if stop.is_set():
        out["reason"] = "STOPPED"
        return out
    # Fingerprint for evidence; always read-only. Large PDFs remain supported.
    hasher = hashlib.sha256()
    with Path(pdf_path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(2 * 1024 * 1024), b""):
            if stop.is_set():
                out["reason"] = "STOPPED"; return out
            hasher.update(chunk)
    out["pdf_sha256"] = hasher.hexdigest()
    with pymupdf.open(str(pdf_path)) as doc:
        if doc.page_count < 1:
            out["reason"] = "EMPTY_PDF"; return out
        page = doc[0]
        for field in FIELDS:
            if stop.is_set():
                out["reason"] = "STOPPED"; return out
            rect = _valid_bbox(page, field_boxes[field])
            # Small padding improves OCR of tight manual boxes while staying within target.
            rect = (rect + (-1.5, -1.5, 1.5, 1.5)) & page.rect
            native_text = page.get_text("text", clip=rect, sort=True).strip()
            scale = dpi / 72
            pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), clip=rect, alpha=False)
            with tempfile.TemporaryDirectory(prefix="cleaner_ocr_") as tmp:
                crop = Path(tmp) / "crop.png"
                pix.save(str(crop))
                ocr_text, ocr_status = _ocr(crop, tesseract, langs, psm, stop)
            if ocr_status == "STOPPED":
                out["reason"] = "STOPPED"; return out
            entry = compare_field(field, native_text, ocr_text, expected.get(field, ""))
            native_candidates = entry.get("native_candidates") or []
            ocr_candidates = entry.get("ocr_candidates") or []
            entry["reading_basis"] = (
                "NATIVE_AND_OCR_AGREE" if native_candidates and ocr_candidates and
                set(native_candidates).intersection(ocr_candidates) else
                "OCR_ONLY" if ocr_candidates else
                "NATIVE_ONLY" if native_candidates else "NONE"
            )
            entry["needs_review"] = (entry["result"] != "VALUE_MATCH_CANDIDATE" or
                                      ocr_status != "OCR_OK" or
                                      entry["reading_basis"] != "NATIVE_AND_OCR_AGREE")
            entry.update({"bbox_pdf": [round(x, 2) for x in rect], "page": 1,
                          "native_text": native_text[:500], "ocr_text": ocr_text[:500],
                          "ocr_status": ocr_status, "pdf_text_layer_present": bool(native_text),
                          "candidate_not_verified": True})
            out["fields"].append(entry)
    out["complete"] = True
    return out


def make_queue(cards, index):
    """Deterministic card order, all unique events; ambiguous file matches not auto-opened."""
    from card_teaching_core import locate_candidates
    queue = []
    seen = set()
    for card in cards:
        for ev in card.get("events", []):
            match = locate_candidates(ev, index)
            path = Path(match["paths"][0]) if len(match["paths"]) == 1 else None
            key = event_key(card, ev, path) if path else hashlib.sha256(
                (str(card.get("sheet")) + str(card.get("index")) + str(ev)).encode("utf-8")
            ).hexdigest()[:24]
            if key in seen: continue
            seen.add(key)
            queue.append({"card": card, "event": ev, "path": path,
                          "locator": match["status"], "event_key": key})
    return queue
