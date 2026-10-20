from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from zipfile import ZipFile, BadZipFile
import xml.etree.ElementTree as ET
import re

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = {"m": MAIN, "r": REL, "pr": PKG_REL}


def col_to_num(col: str) -> int:
    n = 0
    for ch in col.upper():
        if ch.isalpha():
            n = n * 26 + ord(ch) - 64
    return n


def num_to_col(n: int) -> str:
    out = ""
    while n:
        n, rem = divmod(n - 1, 26)
        out = chr(65 + rem) + out
    return out


def split_ref(ref: str) -> tuple[str, int]:
    m = re.fullmatch(r"([A-Z]+)(\d+)", ref.upper())
    if not m:
        raise ValueError(ref)
    return m.group(1), int(m.group(2))


def parse_range(rng: str) -> tuple[int, int, int, int]:
    a, b = (rng.split(":", 1) + [rng])[:2] if ":" in rng else (rng, rng)
    c1, r1 = split_ref(a)
    c2, r2 = split_ref(b)
    return col_to_num(c1), r1, col_to_num(c2), r2


@dataclass
class Cell:
    ref: str
    value: object = None
    formula: str | None = None
    style: int = 0
    cell_type: str | None = None


class XlsxWorkbook:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.sheets: dict[str, dict[str, Cell]] = {}
        self.merges: dict[str, list[str]] = {}
        self.dimensions: dict[str, str | None] = {}
        self.defined_names: list[dict] = []
        self._load()

    def _load(self) -> None:
        try:
            with ZipFile(self.path) as z:
                if "xl/workbook.xml" not in z.namelist():
                    raise ValueError("Not an OOXML workbook")
                shared = self._shared_strings(z)
                workbook = ET.fromstring(z.read("xl/workbook.xml"))
                rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
                relmap = {r.attrib["Id"]: r.attrib["Target"] for r in rels}
                dn = workbook.find("m:definedNames", NS)
                if dn is not None:
                    for item in dn:
                        self.defined_names.append({"attrs": dict(item.attrib), "text": item.text or ""})
                for sh in workbook.find("m:sheets", NS):
                    name = sh.attrib["name"]
                    rid = sh.attrib[f"{{{REL}}}id"]
                    target = relmap[rid].lstrip("/")
                    if not target.startswith("xl/"):
                        target = "xl/" + target
                    self._load_sheet(z, name, target, shared)
        except BadZipFile as exc:
            raise ValueError(f"Invalid XLSX ZIP container: {self.path}") from exc

    def _shared_strings(self, z: ZipFile) -> list[str]:
        if "xl/sharedStrings.xml" not in z.namelist():
            return []
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
        return ["".join((t.text or "") for t in si.iter(f"{{{MAIN}}}t")) for si in root.findall("m:si", NS)]

    def _load_sheet(self, z: ZipFile, name: str, target: str, shared: list[str]) -> None:
        root = ET.fromstring(z.read(target))
        cells: dict[str, Cell] = {}
        for c in root.findall(".//m:sheetData/m:row/m:c", NS):
            ref = c.attrib["r"]
            typ = c.attrib.get("t")
            value_node = c.find("m:v", NS)
            formula_node = c.find("m:f", NS)
            inline = c.find("m:is", NS)
            raw = value_node.text if value_node is not None else None
            if typ == "s" and raw is not None:
                value = shared[int(raw)]
            elif typ == "inlineStr" and inline is not None:
                value = "".join((x.text or "") for x in inline.iter(f"{{{MAIN}}}t"))
            elif typ == "b" and raw is not None:
                value = raw == "1"
            elif typ == "str":
                value = raw
            elif raw is not None:
                try:
                    value = float(raw) if ("." in raw or "E" in raw.upper()) else int(raw)
                except Exception:
                    value = raw
            else:
                value = None
            cells[ref] = Cell(
                ref=ref,
                value=value,
                formula=formula_node.text if formula_node is not None else None,
                style=int(c.attrib.get("s", "0")),
                cell_type=typ,
            )
        self.sheets[name] = cells
        self.merges[name] = [m.attrib["ref"] for m in root.findall("m:mergeCells/m:mergeCell", NS)]
        dim = root.find("m:dimension", NS)
        self.dimensions[name] = dim.attrib.get("ref") if dim is not None else None

    def sheet_names(self) -> list[str]:
        return list(self.sheets)

    def cell(self, sheet: str, ref: str) -> Cell:
        return self.sheets.get(sheet, {}).get(ref, Cell(ref=ref))

    def iter_cells(self, sheet: str):
        return self.sheets.get(sheet, {}).values()

    def cells_in_range(self, sheet: str, rng: str):
        c1, r1, c2, r2 = parse_range(rng)
        for cell in self.iter_cells(sheet):
            col, row = split_ref(cell.ref)
            ci = col_to_num(col)
            if c1 <= ci <= c2 and r1 <= row <= r2:
                yield cell

    def find_text(self, sheet: str, needle: str) -> list[str]:
        key = normalize_text(needle)
        found = []
        for cell in self.iter_cells(sheet):
            if isinstance(cell.value, str) and key in normalize_text(cell.value):
                found.append(cell.ref)
        return sorted(found, key=lambda x: (split_ref(x)[1], col_to_num(split_ref(x)[0])))

    def formula_error_refs(self) -> list[dict]:
        out = []
        for sheet in self.sheet_names():
            for c in self.iter_cells(sheet):
                if c.formula and "#REF!" in c.formula:
                    out.append({"sheet": sheet, "cell": c.ref, "formula": c.formula})
        for dn in self.defined_names:
            if "#REF!" in dn.get("text", ""):
                out.append({"defined_name": dn.get("attrs", {}).get("name"), "text": dn.get("text")})
        return out


def normalize_text(value: object) -> str:
    if value is None:
        return ""
    text = str(value).replace("ي", "ی").replace("ك", "ک")
    text = re.sub(r"\s+", " ", text).strip().casefold()
    return text
