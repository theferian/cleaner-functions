#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""Read-only layout evidence for NGN's atypical General Document workbook.

From the cleaner-functions root:
  py .\INSPECT_NGN_LAYOUT.py

The script never edits workbooks, profiles, decisions or runs. It deliberately
refuses to infer an official WBS when source evidence does not contain one.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
from pathlib import Path
import re
import sys

DEFAULT_BOOK = Path(r"input\GENERAL_DOCUMENT\NGN\retrieval_20261017\NGN\General - Negin.xlsx")
WBS_RE = re.compile(r"^\d+(?:\.\d+)+$")
DATE_RE = re.compile(r"^(?:13|14)\d{2}[/.-]\d{1,2}[/.-]\d{1,2}$")
STATUS_CODES = {"A", "A.N", "A.F.C", "CM", "C.M", "F.C", "FC", "N.A", "NA", "R.M", "HOLD"}


def view(value, maximum=62):
    if value is None:
        return "·"
    s = str(value).replace("\r", " ").replace("\n", " / ").strip()
    return (s[: maximum - 1] + "…") if len(s) > maximum else (s or "·")


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(part)
    return h.hexdigest()


def column_letter(i):
    from openpyxl.utils.cell import get_column_letter
    return get_column_letter(i)


def inspect(book: Path, limit: int):
    from openpyxl import load_workbook
    if not book.is_file():
        raise FileNotFoundError(f"Staged NGN source not found: {book}")
    wb = load_workbook(book, read_only=False, data_only=False)
    try:
        print(f"[SOURCE] {book.resolve()} ({book.stat().st_size:,} bytes)")
        print(f"[SHA256] {sha256(book)}")
        print(f"[SHEETS] {wb.sheetnames}")
        for ws in wb.worksheets:
            print(f"\n=== SHEET {ws.title!r} | rows={ws.max_row} columns={ws.max_column} ===")
            maxcol = min(ws.max_column, 10)
            for c in range(1, maxcol+1):
                values = [str(ws.cell(r, c).value).strip() for r in range(3, ws.max_row+1)
                          if ws.cell(r, c).value is not None and str(ws.cell(r, c).value).strip()]
                wbs = [v for v in values if WBS_RE.fullmatch(v)]
                dates = sum(bool(DATE_RE.fullmatch(v)) for v in values)
                statuses = sum(v.strip().upper() in STATUS_CODES for v in values)
                descriptive = sum(len(v)>=9 and any(ch.isalpha() for ch in v) and not DATE_RE.fullmatch(v) for v in values)
                preview = "; ".join(view(v, 31) for v in values[:3])
                print(f"[COLUMN {column_letter(c)}] nonempty={len(values)} WBS={len(wbs)} dates={dates} statuses={statuses} descriptive={descriptive} first=[{preview}]")
            print("\n[HEADER CELLS] Rows 1–6 (nonempty, A:N):")
            for r in range(1, min(ws.max_row, 6)+1):
                bits = [f"{column_letter(c)}={view(ws.cell(r,c).value,46)!r}" for c in range(1,min(ws.max_column,14)+1)
                        if ws.cell(r,c).value is not None and str(ws.cell(r,c).value).strip()]
                if bits:
                    print(f"  {r}: " + " | ".join(bits))
            print("\n[IDENTIFIER ROW SAMPLES] Source values A:H (first unique candidate rows):")
            printed = 0
            for r in range(3, ws.max_row+1):
                values = [ws.cell(r, c).value for c in range(1, min(ws.max_column,8)+1)]
                if not any(v is not None and str(v).strip() for v in values[:min(4,len(values))]):
                    continue
                # Avoid rendering many repeated template/static labels.
                cells = [f"{column_letter(c)}:{view(values[c-1],57)}" for c in range(1,len(values)+1)]
                print(f"  r{r}: " + " | ".join(cells))
                printed += 1
                if printed >= limit:
                    break
            merged = [str(m) for m in ws.merged_cells.ranges
                      if m.min_col<=8 and m.max_row>=3]
            print(f"\n[MERGES] identifier-area A:H: {len(merged)} ranges; first 18: {', '.join(merged[:18])}")
            wbs_count = sum(bool(WBS_RE.fullmatch(str(ws.cell(r,c).value or '').strip())) for c in range(1,min(8,ws.max_column)+1) for r in range(3,ws.max_row+1))
            if wbs_count == 0:
                print("[REVIEW GATE] No source numeric WBS in A:H. Do not claim an official WBS. Inspect Name/Document No. columns; any surrogate key must be labeled generated and traceable.")
            else:
                print(f"[WBS EVIDENCE] {wbs_count} numeric WBS tokens found in A:H.")
    finally:
        wb.close()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--workbook', type=Path, default=DEFAULT_BOOK)
    p.add_argument('--rows', type=int, default=22)
    a = p.parse_args()
    if not (1 <= a.rows <= 100):
        p.error('--rows must be 1..100')
    try:
        inspect(a.workbook, a.rows)
        return 0
    except (OSError, ValueError, ImportError) as e:
        print(f'[STOP] {e}', file=sys.stderr)
        return 2

if __name__ == '__main__':
    raise SystemExit(main())
