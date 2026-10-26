"""Card-guided source locator and field comparison (read-only, offline).

This module deliberately does not import the GUI, modify source PDFs, or write
Cleaner solutions. A filename match is *candidate* evidence only.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, asdict
from pathlib import Path
import json
import re

DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
DATE_RE = re.compile(r"(?<!\d)(?:13|14)\d{2}\s*[/._\-]\s*\d{1,2}\s*[/._\-]\s*\d{1,2}(?!\d)")
REF_RE = re.compile(r"\b(?:13|14)\d{2}\s*[/\-]\s*[A-Z]{1,4}\s*[/\-]\s*[A-Z]{1,4}\s*[/\-]\s*\d{1,6}\b|\b\d{3,4}\s*[-]\s*\d{1,6}\b(?!\s*[-]\s*\d)", re.I)


def normalize_digits(s):
    return str(s or "").translate(DIGITS).replace("‌", "")


def canonical_date(s):
    m = DATE_RE.search(normalize_digits(s))
    if not m:
        return None
    parts = [int(x) for x in re.split(r"[/._\-]", m.group())]
    if not (1 <= parts[1] <= 12 and 1 <= parts[2] <= (31 if parts[1] <= 6 else 30)):
        return None
    return "%04d/%02d/%02d" % tuple(parts)


def date_candidates(text):
    return list(dict.fromkeys(filter(None, (canonical_date(m.group()) for m in DATE_RE.finditer(normalize_digits(text))))))


def canonical_reference(s):
    return re.sub(r"[^A-Z0-9]", "", normalize_digits(s).upper())


def references_in_text(s):
    return list(dict.fromkeys(m.group() for m in REF_RE.finditer(normalize_digits(s))))


def document_key(r):
    return (str(r.get("source_sheet", "")).strip(), str(r.get("document_index", "")).strip())


def load_records(logbook_path: Path):
    data = json.loads(logbook_path.read_text(encoding="utf-8-sig"))
    records = data if isinstance(data, list) else next(
        (data[k] for k in ("records", "logbook", "transactions", "events") if isinstance(data.get(k), list)), None
    )
    if records is None:
        raise ValueError("Could not find transaction records in board_to_log.json")
    return records


def load_card_queue(logbook_path: Path):
    grouped = {}
    for event in load_records(logbook_path):
        k = document_key(event)
        if not k[0] or not k[1]:
            continue
        if k not in grouped:
            grouped[k] = {"sheet": k[0], "index": k[1], "name": str(event.get("doc_name") or ""),
                          "wbs": str(event.get("doc_wbs") or ""), "events": []}
        ev = {
            "direction": str(event.get("send_or_receive") or "").lower(),
            "reference": str(event.get("letter_reference") or "").strip(),
            "date": str(event.get("letter_date") or "").strip(),
            "revision": str(event.get("doc_rev") or "").strip(),
            "status": str(event.get("doc_status") or "").strip(),
            "source_sheet": k[0], "document_index": k[1],
            "date_source": str(event.get("date_source") or ""),
            "reference_source": str(event.get("reference_source") or ""),
        }
        if ev["reference"]:
            grouped[k]["events"].append(ev)
    return list(grouped.values())


def pdf_index(source_root: Path):
    """Index technical/send and technical/recive, without opening PDF contents."""
    out = defaultdict(list)
    for dirname, direction in (("send", "send"), ("recive", "receive"), ("receive", "receive")):
        folder = source_root / dirname
        if not folder.is_dir():
            continue
        for p in folder.rglob("*.pdf"):
            out[direction].append(p)
    return out


def filename_variants(reference):
    """Only candidates: 1404/ES/S/3003 -> 1404-3003, not verification."""
    ref = normalize_digits(reference).upper()
    parts = [p for p in re.split(r"[/\\ _.-]+", ref) if p]
    candidates = set()
    if len(parts) >= 2:
        year, serial = parts[0], parts[-1]
        if year.isdigit() and serial.isdigit():
            candidates.add(f"{year}-{int(serial)}")
            candidates.add(f"{year}-{serial}")
    candidates.add(re.sub(r"\W+", "-", ref).strip("-"))
    return {v.casefold() for v in candidates if v}


def locate_candidates(ev, index):
    direction = ev.get("direction")
    files = index.get(direction, [])
    variants = filename_variants(ev.get("reference", ""))
    candidates = [str(p) for p in files if p.stem.casefold() in variants]
    return {"status": "SINGLE_CANDIDATE" if len(candidates) == 1 else
            "MULTIPLE_CANDIDATES" if candidates else "NOT_FOUND",
            "paths": candidates, "direction": direction, "reference": ev.get("reference")}


def compare_field(field, native_text, ocr_text, expected):
    """Separate extraction from approval. No mismatch silently becomes a repair."""
    extract = date_candidates if field == "letter_date" else references_in_text
    norm = (lambda x: canonical_date(x)) if field == "letter_date" else canonical_reference
    native = [norm(x) for x in extract(native_text)]
    ocr = [norm(x) for x in extract(ocr_text)]
    expected_normal = norm(expected)
    native = list(dict.fromkeys(v for v in native if v))
    ocr = list(dict.fromkeys(v for v in ocr if v))
    union = list(dict.fromkeys(native + ocr))
    if native and ocr and not set(native).intersection(ocr):
        result = "READER_DISAGREEMENT"
    elif not union:
        result = "UNREADABLE"
    elif len(union) != 1:
        result = "AMBIGUOUS"
    elif union[0] == expected_normal:
        result = "VALUE_MATCH_CANDIDATE"  # not a confirmed document identity
    else:
        result = "VALUE_MISMATCH"
    return {"field": field, "expected": expected, "normalized_expected": expected_normal,
            "native_candidates": native, "ocr_candidates": ocr,
            "result": result, "source_confirmed": False}
