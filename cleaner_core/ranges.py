from __future__ import annotations

import re
from dataclasses import dataclass
from openpyxl.utils import column_index_from_string, get_column_letter


@dataclass(frozen=True)
class Rect:
    address: str
    r1: int
    r2: int
    c1: int
    c2: int

    @property
    def row_span(self):
        return self.r2 - self.r1 + 1

    @property
    def col_span(self):
        return self.c2 - self.c1 + 1

    def rows(self):
        return range(self.r1, self.r2 + 1)


def parse_range(address: str) -> Rect:
    s = address.replace("$", "").upper()
    m = re.fullmatch(r"([A-Z]+)(\d+):([A-Z]+)(\d+)", s)
    if m:
        c1, r1, c2, r2 = m.groups()
        return Rect(
            s,
            int(r1),
            int(r2),
            column_index_from_string(c1),
            column_index_from_string(c2),
        )

    m = re.fullmatch(r"([A-Z]+)(\d+)", s)
    if not m:
        raise ValueError(f"Invalid Excel address: {address}")
    c, r = m.groups()
    ci = column_index_from_string(c)
    ri = int(r)
    return Rect(s, ri, ri, ci, ci)


def crosses_vertical_boundary(rect: Rect, boundary_after_col: int) -> bool:
    return rect.c1 <= boundary_after_col < rect.c2


def intersects_window(rect: Rect, r1: int, r2: int, c1: int, c2: int) -> bool:
    return not (rect.r2 < r1 or rect.r1 > r2 or rect.c2 < c1 or rect.c1 > c2)


def contiguous_groups(rows: set[int]) -> list[tuple[int, int]]:
    if not rows:
        return []
    vals = sorted(rows)
    groups = []
    start = prev = vals[0]
    for x in vals[1:]:
        if x == prev + 1:
            prev = x
            continue
        groups.append((start, prev))
        start = prev = x
    groups.append((start, prev))
    return groups


def col_letter(n: int) -> str:
    return get_column_letter(n)
