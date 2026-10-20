"""Read-only probe for one shared-folder engineering correspondence PDF.

Example (Windows CMD):
 python verify_shared_letter_v01.py --file "W:\\00-1403\\1403-02-05-230kV Azad\\Letter\\technical\\send\\1404-3003.pdf" --reference "1404/ES/S/3003" --expected-date "1404/07/19" --out "working\\source_registry\\AZD_1404-3003_probe.json"

The probe cannot establish that a date is the letter's *official* date merely by
finding it in text; field/visual review remains required. Does not modify PDFs.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import sys

DIGIT_MAP = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
DATE_RE = re.compile(r"(?<!\d)(1[34]\d{2})\s*[/\-.\\]\s*(\d{1,2})\s*[/\-.\\]\s*(\d{1,2})(?!\d)")


def ascii_digits(value: str) -> str:
    return value.translate(DIGIT_MAP)


def compact(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z]+", "", ascii_digits(value)).upper()


def dates_in_text(text: str) -> list[str]:
    values = set()
    for m in DATE_RE.finditer(ascii_digits(text)):
        year, month, day = map(int, m.groups())
        if 1 <= month <= 12 and 1 <= day <= 31:
            values.add(f"{year:04d}/{month:02d}/{day:02d}")
    return sorted(values)


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def read_pdf_text(path: Path) -> tuple[str | None, list[str], str | None]:
    errors = []
    try:
        import pymupdf  # type: ignore
        with pymupdf.open(str(path)) as pdf:
            return "pymupdf", [page.get_text("text") or "" for page in pdf], None
    except ImportError:
        try:
            import fitz  # type: ignore
            with fitz.open(str(path)) as pdf:
                return "pymupdf", [page.get_text("text") or "" for page in pdf], None
        except ImportError:
            pass
        except Exception as exc:
            errors.append(f"pymupdf: {type(exc).__name__}: {exc}")
    except Exception as exc:
        errors.append(f"pymupdf: {type(exc).__name__}: {exc}")
    try:
        from pypdf import PdfReader  # type: ignore
        reader = PdfReader(str(path), strict=False)
        return "pypdf", [page.extract_text() or "" for page in reader.pages], None
    except ImportError:
        return None, [], "; ".join(errors) if errors else "No PDF text reader installed (install pymupdf or pypdf)."
    except Exception as exc:
        errors.append(f"pypdf: {type(exc).__name__}: {exc}")
        return None, [], "; ".join(errors)


def probe(path: Path, reference: str, expected_date: str) -> dict:
    if not path.is_file():
        raise FileNotFoundError(f"PDF does not exist or is inaccessible: {path}")
    if path.suffix.lower() != ".pdf":
        raise ValueError("Only PDF input is supported")
    stat = path.stat()
    with path.open("rb") as f:
        signature = f.read(5)
    if signature != b"%PDF-":
        raise ValueError("Source file does not begin with PDF signature")
    backend, page_texts, error = read_pdf_text(path)
    full_key = compact(reference)
    serial = re.findall(r"\d+", ascii_digits(reference))[-1]
    normal_date = dates_in_text(expected_date)
    if len(normal_date) != 1:
        raise ValueError("--expected-date must be a Jalali date like 1404/07/19")
    expected = normal_date[0]
    findings = []
    all_dates = set()
    for i, content in enumerate(page_texts, start=1):
        normalized = ascii_digits(content)
        comp = compact(normalized)
        observed_dates = dates_in_text(normalized)
        all_dates.update(observed_dates)
        # The serial-number match is weak; a document can mention another letter.
        if full_key in comp or serial in comp or expected in observed_dates:
            findings.append({
                "page": i,
                "full_reference_present": full_key in comp,
                "serial_present": serial in comp,
                "expected_date_present": expected in observed_dates,
                "observed_date_candidates": observed_dates[:40],
            })
    if backend is None:
        status = "READER_UNAVAILABLE_OR_FAILED"
    elif not any(t.strip() for t in page_texts):
        status = "NO_SEARCHABLE_TEXT_OCR_REQUIRED"
    elif any(x["full_reference_present"] and x["expected_date_present"] for x in findings):
        status = "CONTENT_MATCH_CANDIDATE_FIELD_REVIEW_REQUIRED"
    elif any(x["full_reference_present"] for x in findings):
        status = "REFERENCE_CANDIDATE_DATE_NOT_LOCATED"
    else:
        status = "NO_FULL_REFERENCE_IN_SEARCHABLE_TEXT"
    return {
        "schema": "cleaner.source_letter_probe/0.1",
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source": {
            "path": str(path.resolve()),
            "size_bytes": stat.st_size,
            "modified_utc": dt.datetime.fromtimestamp(stat.st_mtime, dt.timezone.utc).isoformat(),
            "sha256": sha256_file(path),
        },
        "expected": {"reference": reference, "direction": "SEND", "date_jalali": expected},
        "reader": {"backend": backend, "pages": len(page_texts), "error": error},
        "findings": findings,
        "observed_date_candidates_all_pages": sorted(all_dates)[:100],
        "decision": status,
        "field_verified": False,
        "notes": "Filename or text occurrence alone does not verify header/reference/date fields. Inspect source page visually before approving a correction.",
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--file", required=True)
    p.add_argument("--reference", default="1404/ES/S/3003")
    p.add_argument("--expected-date", default="1404/07/19")
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)
    source = Path(args.file).expanduser().resolve()
    dest = Path(args.out).expanduser().resolve()
    if dest == source or source.parent == dest.parent or source.parent in dest.parents:
        p.error("--out must not write into the source PDF directory or its descendants")
    try:
        data = probe(source, args.reference, args.expected_date)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError) as exc:
        print(f"[STOP] {exc}", file=sys.stderr)
        return 2
    print(f"[SOURCE] {data['source']['path']}")
    print(f"[SHA256] {data['source']['sha256']}")
    print(f"[READER] {data['reader']['backend'] or 'NONE'}; pages={data['reader']['pages']}")
    if data['reader']['error']:
        print(f"[READER ISSUE] {data['reader']['error']}")
    print(f"[STATUS] {data['decision']}")
    print("[DATES] " + (", ".join(data['observed_date_candidates_all_pages'][:20]) or "none extracted"))
    for item in data['findings'][:20]:
        print(f"[PAGE {item['page']}] full_reference={item['full_reference_present']} serial={item['serial_present']} expected_date={item['expected_date_present']}")
    print(f"[LOCAL REPORT] {dest}")
    print("[CAUTION] No value is auto-corrected; inspect actual PDF header before verifying.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
