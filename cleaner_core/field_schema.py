from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field, asdict
import re
from typing import Any, Iterable

from openpyxl.utils import get_column_letter

from .card_map import CardMapScan, scan_all_card_maps


_PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
_DASHES = str.maketrans({"–": "-", "—": "-", "−": "-", "ـ": "-"})
_JALALI_CANONICAL_RE = re.compile(r"^\d{4}/\d{2}/\d{2}$")
_JALALI_LOOSE_RE = re.compile(r"^\s*(?:\d{2}|\d{4})\s*[/\\.\-]\s*\d{1,2}\s*[/\\.\-]\s*\d{1,2}\s*$")
_EMBEDDED_JALALI_RE = re.compile(r"(?<!\d)(?:\d{2}|\d{4})\s*[/\.\-–—−]\s*\d{1,2}\s*[/\.\-–—−]\s*\d{1,2}(?!\d)")
_GLOBAL_JALALI_TOKEN_RE = re.compile(r"(?<!\d)(?:1[34]\d{2}|\d{3})\s*[/\.\-–—−]\s*\d{1,3}\s*[/\.\-–—−]\s*\d{1,3}(?!\d)")
_SHORT_JALALI_TOKEN_RE = re.compile(r"(?<!\d)\d{2}\s*[/\.\-–—−]\s*\d{1,2}\s*[/\.\-–—−]\s*\d{1,2}(?!\d)")
_DATE_CONTEXT_MARKERS = ("مورخ", "تاریخ", "تاريخ", "date", "dated")
_CODE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._/\-]{0,9}$")
_REFERENCEISH_RE = re.compile(r"^(?=.*\d)(?=.*[A-Za-z\u0600-\u06FF])[A-Za-z0-9\u0600-\u06FF._/\- ]{4,80}$")

_HEADER_KEYWORDS = {
    "status": ["status", "وضعیت", "وضعيت"],
    "send_date": ["send date", "sent date", "date sent", "ارسال", "تاریخ ارسال", "تاريخ ارسال", "صدور"],
    "receive_date": ["receive date", "received date", "date received", "دریافت", "دريافت", "تاریخ دریافت", "تاريخ دريافت", "وصول"],
    "reference": ["reference", "refrence", "ref", "مرجع", "شماره نامه", "شماره مکاتبه", "شماره مكاتبه", "مکاتبه", "مكاتبه"],
}


@dataclass(frozen=True)
class ColumnProfile:
    column: int
    letter: str
    headers: tuple[str, ...]
    non_empty: int
    dominant_kind: str
    dominant_kind_confidence: float
    unique_count: int
    samples: tuple[str, ...]
    semantic_type: str = "UNKNOWN"
    semantic_confidence: float = 0.0
    inferred_role: str | None = None
    role_confidence: float = 0.0
    role_source: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SlotProfile:
    column: int
    letter: str
    lane: str
    headers: tuple[str, ...]
    non_empty: int
    dominant_kind: str
    dominant_kind_confidence: float
    unique_count: int
    samples: tuple[str, ...]
    semantic_type: str = "UNKNOWN"
    semantic_confidence: float = 0.0
    inferred_role: str | None = None
    role_confidence: float = 0.0
    role_source: str | None = None

    @property
    def key(self) -> str:
        return f"{self.letter}:{self.lane}"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["key"] = self.key
        return payload


@dataclass(frozen=True)
class ReferenceRule:
    regex: str
    coverage: float
    sample_count: int
    matched_count: int
    example_values: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SlotSchema:
    sheet: str
    data_start_col: int
    data_end_col: int
    block_width: int | None
    block_confidence: float
    roles_by_offset: dict[int, str]
    role_confidence_by_offset: dict[int, float]
    columns: tuple[ColumnProfile, ...]
    slot_profiles: tuple[SlotProfile, ...] = ()
    roles_by_slot: dict[str, str] = field(default_factory=dict)
    jalali_regex: str = r"^\d{4}/\d{2}/\d{2}$"
    reference_rule: ReferenceRule | None = None
    status_values: tuple[str, ...] = ()
    status_coverage: float = 0.0
    # Reader-first exception handling: when a token is already part of the
    # high-confidence status vocabulary, its semantic meaning can override an
    # unusual physical position in a malformed/non-standard card. This keeps
    # the workbook untouched while teaching the reader how to interpret it.
    status_overrides_geometry: bool = True
    block_source: str = "SEMANTIC_PERIODICITY"
    block_evidence: dict[str, Any] = field(default_factory=dict)
    issues: tuple[dict[str, Any], ...] = ()

    def role_for_column(self, column: int) -> str | None:
        # Backward-compatible helper: return a role only when the column has one
        # unambiguous validated role across its vertical lanes.
        roles = {p.inferred_role for p in self.slot_profiles if p.column == column and p.inferred_role}
        if len(roles) == 1:
            return next(iter(roles))
        for profile in self.columns:
            if profile.column == column and profile.inferred_role:
                return profile.inferred_role
        return None

    def role_for_slot(self, card, slot) -> str | None:
        """Resolve the business role of one physical card sub-slot.

        The learned geometry says which roles are plausible at a horizontal
        transaction offset, but the actual value shape disambiguates stacked
        sub-slots. This is essential for multi-row cards where one column may
        contain DATE -> REFERENCE -> DATE -> REFERENCE.
        """
        lane = slot_lane(card, slot)

        if slot.value is not None and str(slot.value).strip():
            # A known status token is stronger semantic evidence than geometry.
            # Real project sheets sometimes place status inside a neighbouring
            # send/receive/reference cell when a card was built irregularly.
            # Treat that as a read exception, not as a workbook error.
            if (
                self.status_overrides_geometry
                and self.status_values
                and normalize_status(slot.value) in self.status_values
            ):
                return "status"

        if self.block_width and slot.value is not None and str(slot.value).strip():
            offset = (slot.col_start - self.data_start_col) % self.block_width
            offset_roles = {
                role
                for key, role in self.roles_by_slot.items()
                if key.startswith(f"{offset}:")
            }
            observed_kind = classify_value(slot.value)

            # A stable status offset remains status even when a rare code is new.
            if "status" in offset_roles and not any(
                role in offset_roles for role in {"send_date", "receive_date", "reference"}
            ):
                return "status"

            # Correspondence columns can stack multiple events vertically.
            # Dispatch each real sub-slot by its own value shape rather than by
            # TOP/BOTTOM alone.
            if observed_kind == "DATE":
                preferred = self.roles_by_offset.get(offset)
                if preferred in {"send_date", "receive_date"} or (preferred and preferred.startswith("date_")):
                    return preferred
                date_roles = [r for r in offset_roles if r in {"send_date", "receive_date"} or r.startswith("date_")]
                if date_roles:
                    return sorted(date_roles)[0]
                return "date"
            if observed_kind == "REFERENCE":
                return "reference"
            if observed_kind == "CODE" and "status" not in offset_roles:
                # Short alphanumeric codes in a correspondence column are more
                # likely document references than statuses.
                return "reference"
            if observed_kind == "TEXT" and (offset_roles or self.roles_by_offset.get(offset)):
                return "explanation"

        # Fallback to the learned card-relative lane role.
        for profile in self.slot_profiles:
            if profile.column == slot.col_start and profile.lane == lane:
                return profile.inferred_role
        return None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["roles_by_offset"] = {str(k): v for k, v in self.roles_by_offset.items()}
        payload["slot_profiles"] = [p.to_dict() for p in self.slot_profiles]
        payload["role_confidence_by_offset"] = {
            str(k): v for k, v in self.role_confidence_by_offset.items()
        }
        if self.reference_rule is not None:
            payload["reference_rule"] = self.reference_rule.to_dict()
        return payload


@dataclass
class SlotSchemaScan:
    sheets: dict[str, SlotSchema] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"sheets": {sheet: schema.to_dict() for sheet, schema in self.sheets.items()}}


def field_inference_config(profile: dict) -> dict[str, Any]:
    configured = profile.get("data_model", {}).get("field_inference", {})
    return {
        "header_rows": list(configured.get("header_rows", [1, 2])),
        "max_block_width": int(configured.get("max_block_width", 8)),
        "min_block_confidence": float(configured.get("min_block_confidence", 0.70)),
        "min_role_confidence": float(configured.get("min_role_confidence", 0.80)),
        "semantic_min_confidence": float(configured.get("semantic_min_confidence", 0.90)),
        "block_fundamental_tolerance": float(configured.get("block_fundamental_tolerance", 0.12)),
        "status_max_unique": int(configured.get("status_max_unique", 20)),
        "status_max_unique_ratio": float(configured.get("status_max_unique_ratio", 0.60)),
        "reference_min_samples": int(configured.get("reference_min_samples", 5)),
        "reference_min_coverage": float(configured.get("reference_min_coverage", 0.70)),
        "status_min_occurrences": int(configured.get("status_min_occurrences", 2)),
        "status_min_coverage": float(configured.get("status_min_coverage", 0.80)),
        # A document family can contain vertically mixed correspondence cells that
        # make whole-column periodicity noisy. Stable semantic anchor columns
        # (normally STATUS) can still reveal the horizontal transaction rhythm.
        "anchor_block_inference": bool(configured.get("anchor_block_inference", True)),
        "anchor_min_columns": int(configured.get("anchor_min_columns", 3)),
        "anchor_min_spacing_coverage": float(configured.get("anchor_min_spacing_coverage", 0.75)),
        # Once a block width is known, date-bearing offsets may still be MIXED
        # because a single physical column stacks dates, references and notes.
        # Infer send/receive roles from value-level evidence instead of requiring
        # one lane to be semantically pure.
        "mixed_offset_date_min_samples": int(configured.get("mixed_offset_date_min_samples", 3)),
        "mixed_offset_date_min_share": float(configured.get("mixed_offset_date_min_share", 0.20)),
        # Prefer semantic meaning over expected geometry for already learned
        # status tokens (e.g. A.N appearing in a receive/reference position).
        "known_status_overrides_geometry": bool(
            configured.get("known_status_overrides_geometry", True)
        ),
    }


def normalize_digits(value: Any) -> str:
    if value is None:
        return ""
    return str(value).translate(_PERSIAN_DIGITS).translate(_ARABIC_DIGITS)


def normalize_reference(value: Any) -> str:
    # Preserve the narrative exactly; normalize only date tokens that are found.
    text = str(value).strip()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s*([/\-.])\s*", r"\1", text)
    return text


def normalize_status(value: Any) -> str:
    return normalize_digits(value).strip().upper().replace(" ", "")


def normalize_jalali(value: Any) -> str | None:
    if value is None:
        return None
    text = normalize_digits(value).strip().translate(_DASHES)
    if not _JALALI_LOOSE_RE.fullmatch(text):
        return None
    parts = re.split(r"[/\\.\-]", text)
    if len(parts) != 3:
        return None
    year_token = parts[0].strip()
    try:
        year, month, day = (int(x.strip()) for x in parts)
    except ValueError:
        return None
    # AZD sometimes stores short Jalali years inside notes (e.g. 04/06/03).
    # Treat a two-digit year as 14YY; four-digit years remain unchanged.
    if len(year_token) == 2:
        year = 1400 + year
    elif len(year_token) != 4:
        return None
    return f"{year:04d}/{month:02d}/{day:02d}"


def normalize_embedded_jalali_text(value: Any) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    """Normalize Jalali-looking dates embedded inside explanatory text.

    Returns (normalized_text, normalized_dates, invalid_date_tokens). Invalid
    calendar dates are preserved verbatim so they can be reviewed rather than
    silently rewritten.
    """
    text = normalize_digits(value).strip().translate(_DASHES)
    normalized_dates: list[str] = []
    invalid_tokens: list[str] = []

    def repl(match: re.Match[str]) -> str:
        token = match.group(0)
        normalized = normalize_jalali(token)
        if normalized is None or not is_valid_jalali(normalized):
            invalid_tokens.append(token)
            return token
        normalized_dates.append(normalized)
        return normalized

    normalized_text = _EMBEDDED_JALALI_RE.sub(repl, text)
    return normalized_text, tuple(normalized_dates), tuple(invalid_tokens)




def discover_jalali_tokens(value: Any, *, allow_short: bool = False) -> tuple[dict[str, Any], ...]:
    """Discover Jalali-looking tokens anywhere inside a value.

    The global safety-net deliberately scans beyond fields already classified as
    dates. Four-digit 13xx/14xx tokens and malformed three-digit-year numeric
    triples are always considered date candidates. Month/day components are
    deliberately allowed up to three digits so malformed dates are discovered
    first and rejected by calendar validation rather than missed by regex.
    Two-digit years are considered only when explicitly allowed (normally for
    explanatory text with a date marker such as ``مورخ``).
    """
    if value is None:
        return ()
    text = normalize_digits(value).translate(_DASHES)
    matches: list[re.Match[str]] = list(_GLOBAL_JALALI_TOKEN_RE.finditer(text))
    if allow_short:
        occupied = [(m.start(), m.end()) for m in matches]
        for match in _SHORT_JALALI_TOKEN_RE.finditer(text):
            if any(not (match.end() <= a or match.start() >= b) for a, b in occupied):
                continue
            matches.append(match)
    matches.sort(key=lambda m: (m.start(), m.end()))

    found: list[dict[str, Any]] = []
    for match in matches:
        raw = match.group(0)
        normalized = normalize_jalali(raw)
        valid = normalized is not None and is_valid_jalali(normalized)
        canonical = bool(valid and raw == normalized)
        found.append({
            "token": raw,
            "normalized": normalized,
            "valid": valid,
            "canonical": canonical,
            "start": match.start(),
            "end": match.end(),
        })
    return tuple(found)


def has_date_context_marker(value: Any) -> bool:
    text = normalize_digits(value).strip().lower()
    return any(marker.lower() in text for marker in _DATE_CONTEXT_MARKERS)


def normalize_discovered_jalali_text(value: Any, *, allow_short: bool = False) -> tuple[str, tuple[dict[str, Any], ...]]:
    """Normalize valid discovered date tokens in-place and preserve all other text."""
    text = normalize_digits(value).strip().translate(_DASHES)
    audits = discover_jalali_tokens(text, allow_short=allow_short)
    if not audits:
        return text, audits
    parts: list[str] = []
    pos = 0
    for item in audits:
        start = int(item["start"]); end = int(item["end"])
        parts.append(text[pos:start])
        if item["valid"] and item["normalized"] is not None:
            parts.append(str(item["normalized"]))
        else:
            parts.append(text[start:end])
        pos = end
    parts.append(text[pos:])
    return "".join(parts), audits


def _jalali_cal(year: int) -> tuple[int, int]:
    """Return (leap_index, march_day) using the widely used Jalaali break algorithm."""
    breaks = [-61, 9, 38, 199, 426, 686, 756, 818, 1111, 1181, 1210, 1635,
              2060, 2097, 2192, 2262, 2324, 2394, 2456, 3178]
    if year < breaks[0] or year >= breaks[-1]:
        raise ValueError("Jalali year outside supported range")
    gy = year + 621
    leap_j = -14
    jp = breaks[0]
    jump = 0
    for jm in breaks[1:]:
        jump = jm - jp
        if year < jm:
            break
        leap_j += (jump // 33) * 8 + ((jump % 33) // 4)
        jp = jm
    n = year - jp
    leap_j += (n // 33) * 8 + (((n % 33) + 3) // 4)
    if jump % 33 == 4 and jump - n == 4:
        leap_j += 1
    leap_g = (gy // 4) - (((gy // 100) + 1) * 3 // 4) - 150
    march = 20 + leap_j - leap_g
    if jump - n < 6:
        n = n - jump + ((jump + 4) // 33) * 33
    leap = (((n + 1) % 33) - 1) % 4
    if leap == -1:
        leap = 4
    return leap, march


def is_valid_jalali(value: Any) -> bool:
    normalized = normalize_jalali(value)
    if normalized is None or _JALALI_CANONICAL_RE.fullmatch(normalized) is None:
        return False
    year, month, day = (int(x) for x in normalized.split("/"))
    if month < 1 or month > 12 or day < 1:
        return False
    if month <= 6:
        return day <= 31
    if month <= 11:
        return day <= 30
    try:
        leap_index, _ = _jalali_cal(year)
    except ValueError:
        return False
    return day <= (30 if leap_index == 0 else 29)


def classify_value(value: Any) -> str:
    text = normalize_digits(value).strip()
    if not text:
        return "EMPTY"
    if normalize_jalali(text) is not None:
        return "DATE"
    if _CODE_RE.fullmatch(text):
        return "CODE"

    # Narrative Persian/Arabic prose can contain dates and numbers but is not a
    # document reference. Keep common meeting-note/explanation language out of
    # the reference learner.
    narrative_markers = ("عطف", "صورتجلسه", "صورت جلسه", "مورخ", "مطابق", "مذاکرات", "توضیح", "جلسه")
    persian_chars = sum(1 for ch in text if "\u0600" <= ch <= "\u06ff")
    word_count = len(text.split())
    if any(marker in text for marker in narrative_markers) or (persian_chars >= 4 and word_count >= 4):
        return "TEXT"

    if _REFERENCEISH_RE.fullmatch(text):
        return "REFERENCE"
    if re.fullmatch(r"[-+]?\d+(?:[.,]\d+)?", text):
        return "NUMBER"
    return "TEXT"


def _header_texts(snapshot, sheet: str, column: int, header_rows: Iterable[int]) -> tuple[str, ...]:
    values: list[str] = []
    letter = get_column_letter(column)
    for row in header_rows:
        value = snapshot.effective_value(sheet, f"{letter}{row}")
        if value is None:
            continue
        text = str(value).strip()
        if text and text not in values:
            values.append(text)
    return tuple(values)


def _header_role(headers: Iterable[str]) -> tuple[str | None, float]:
    joined = " | ".join(headers).lower()
    if not joined:
        return None, 0.0
    scores: dict[str, int] = {}
    for role, keywords in _HEADER_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw.lower() in joined)
        if score:
            scores[role] = score
    if not scores:
        return None, 0.0
    ordered = sorted(scores.items(), key=lambda x: (-x[1], x[0]))
    role, score = ordered[0]
    total = sum(scores.values())
    confidence = score / total if total else 0.0
    return role, max(0.75, confidence)


def slot_lane(card, slot) -> str:
    """Normalize vertical slot geometry so 2-row and 4-row cards share semantics."""
    last = max(0, card.end_row - card.start_row)
    start = int(slot.row_offset_start)
    end = int(slot.row_offset_end)
    if last == 0 or (start == 0 and end >= last):
        return "FULL"
    midpoint = last / 2.0
    if end < midpoint or start == 0:
        return "TOP"
    if start > midpoint or end == last:
        return "BOTTOM"
    center = (start + end) / 2.0
    if center < midpoint:
        return "TOP"
    if center > midpoint:
        return "BOTTOM"
    return "MIDDLE"


def _collect_slot_values(scan: CardMapScan) -> dict[tuple[int, str], list[Any]]:
    values: dict[tuple[int, str], list[Any]] = defaultdict(list)
    for card in scan.cards:
        for slot in card.slots:
            if slot.value is None or str(slot.value).strip() == "":
                continue
            values[(slot.col_start, slot_lane(card, slot))].append(slot.value)
    return values


def _collect_column_values(scan: CardMapScan) -> dict[int, list[Any]]:
    values: dict[int, list[Any]] = defaultdict(list)
    for card in scan.cards:
        for slot in card.slots:
            if slot.value is None or str(slot.value).strip() == "":
                continue
            values[slot.col_start].append(slot.value)
    return values


def _dominant_kind(values: list[Any]) -> tuple[str, float, int, tuple[str, ...]]:
    if not values:
        return "EMPTY", 0.0, 0, ()
    kinds = Counter(classify_value(v) for v in values)
    kind, count = kinds.most_common(1)[0]
    samples: list[str] = []
    seen = set()
    for value in values:
        text = str(value)
        if text in seen:
            continue
        seen.add(text)
        samples.append(text)
        if len(samples) >= 6:
            break
    unique = len({str(v) for v in values})
    return kind, count / len(values), unique, tuple(samples)


def _block_width_scores(kinds: list[str], max_width: int) -> dict[int, tuple[float, int]]:
    scores: dict[int, tuple[float, int]] = {}
    upper = min(max_width, max(1, len(kinds) // 2))
    for width in range(2, upper + 1):
        matches = 0
        compared = 0
        for i in range(len(kinds) - width):
            left, right = kinds[i], kinds[i + width]
            if left in {"EMPTY", "UNKNOWN", "MIXED"} or right in {"EMPTY", "UNKNOWN", "MIXED"}:
                continue
            compared += 1
            if left == right:
                matches += 1
        if compared >= 3:
            scores[width] = (matches / compared, compared)
    return scores


def _detect_block_width(
    kinds: list[str],
    max_width: int,
    *,
    fundamental_tolerance: float = 0.12,
) -> tuple[int | None, float]:
    """Prefer the smallest plausible repeating period, not a harmonic multiple."""
    scores = _block_width_scores(kinds, max_width)
    if not scores:
        return None, 0.0

    best_width, (best_score, _) = max(
        scores.items(), key=lambda item: (item[1][0], -item[0], item[1][1])
    )

    # If a smaller divisor is almost as good, it is the more likely fundamental
    # transaction width (e.g. prefer 3 over a harmonic 6).
    candidates = []
    for width, (score, compared) in scores.items():
        if width >= best_width or best_width % width != 0:
            continue
        if best_score - score <= fundamental_tolerance:
            candidates.append((width, score, compared))
    if candidates:
        width, score, _ = min(candidates, key=lambda x: x[0])
        return width, score
    return best_width, best_score



def _infer_block_width_from_semantic_anchors(
    profiles: list[SlotProfile],
    *,
    max_width: int,
    min_semantic_confidence: float,
    min_columns: int = 3,
    min_spacing_coverage: float = 0.75,
) -> tuple[int | None, float, dict[str, Any]]:
    """Infer transaction width from stable repeated semantic anchor columns.

    Whole-column periodicity can be noisy when correspondence columns stack
    dates, references and narrative notes. Status columns are usually much more
    stable. If the same high-confidence semantic type recurs at a consistent
    horizontal spacing, that spacing is strong evidence for the block width.

    The helper is intentionally generic: STATUS is preferred, but DATE and
    REFERENCE anchors can also be used by other project families.
    """
    by_semantic: dict[str, dict[int, float]] = defaultdict(dict)
    preferred = ("STATUS", "DATE", "REFERENCE")
    for p in profiles:
        if p.semantic_type not in preferred or p.semantic_confidence < min_semantic_confidence:
            continue
        by_semantic[p.semantic_type][p.column] = max(
            by_semantic[p.semantic_type].get(p.column, 0.0), p.semantic_confidence
        )

    candidates: list[tuple[float, int, int, str, list[int], list[int]]] = []
    for semantic, conf_by_col in by_semantic.items():
        columns = sorted(conf_by_col)
        if len(columns) < min_columns:
            continue
        gaps = [b - a for a, b in zip(columns, columns[1:]) if 1 < (b - a) <= max_width]
        if len(gaps) < max(2, min_columns - 1):
            continue
        gap_counts = Counter(gaps)
        for width, exact_count in gap_counts.items():
            # Missing one anchor may produce a multiple of the real spacing;
            # count those gaps as support too.
            supported = sum(1 for gap in gaps if gap % width == 0)
            coverage = supported / len(gaps)
            if coverage < min_spacing_coverage:
                continue
            mean_conf = sum(conf_by_col[c] for c in columns) / len(columns)
            semantic_priority = {"STATUS": 3, "DATE": 2, "REFERENCE": 1}[semantic]
            confidence = coverage * mean_conf
            candidates.append(
                (confidence, semantic_priority, -width, semantic, columns, gaps)
            )

    if not candidates:
        return None, 0.0, {}
    confidence, _, neg_width, semantic, columns, gaps = max(candidates)
    width = -neg_width
    return width, confidence, {
        "semantic_anchor": semantic,
        "columns": columns,
        "gaps": gaps,
        "spacing_coverage": round(
            sum(1 for gap in gaps if gap % width == 0) / len(gaps), 4
        ),
    }


def _augment_mixed_offset_date_roles(
    scan: CardMapScan,
    *,
    data_start_col: int,
    block_width: int | None,
    roles_by_slot: dict[str, str],
    role_conf_by_slot: dict[str, float],
    roles_by_offset: dict[int, str],
    role_conf_by_offset: dict[int, float],
    min_samples: int,
    min_share: float,
) -> None:
    """Recover send/receive roles from value-level evidence in MIXED offsets.

    A stacked transaction column may contain dates, references and explanatory
    text, so its lane profile can legitimately be MIXED. Once the horizontal
    block rhythm is known, repeated valid date values at an offset are enough to
    establish that it is date-bearing. The first two date-bearing offsets are
    named send_date and receive_date, preserving the existing transaction model.
    """
    if not block_width:
        return

    kind_counts: dict[int, Counter[str]] = defaultdict(Counter)
    for card in scan.cards:
        for slot in card.slots:
            if slot.value is None or str(slot.value).strip() == "":
                continue
            offset = (slot.col_start - data_start_col) % block_width
            kind_counts[offset][classify_value(slot.value)] += 1

    date_candidates: list[tuple[int, float, int]] = []
    for offset in range(block_width):
        if roles_by_offset.get(offset) == "status":
            continue
        counts = kind_counts.get(offset, Counter())
        total = sum(counts.values())
        date_count = counts.get("DATE", 0)
        if total == 0 or date_count < min_samples:
            continue
        share = date_count / total
        if share >= min_share:
            date_candidates.append((offset, share, date_count))

    # Preserve already trusted date roles and fill only missing horizontal roles.
    existing_date_offsets = {
        offset for offset, role in roles_by_offset.items()
        if role in {"send_date", "receive_date"} or role.startswith("date_")
    }
    candidates = sorted(
        {offset: (share, count) for offset, share, count in date_candidates}.items()
    )
    ordered_offsets = sorted(existing_date_offsets | {offset for offset, _ in candidates})
    for idx, offset in enumerate(ordered_offsets):
        if offset in existing_date_offsets:
            continue
        role = "send_date" if idx == 0 else "receive_date" if idx == 1 else f"date_{idx + 1}"
        share, count = dict(candidates).get(offset, (0.0, 0))
        confidence = min(1.0, max(share, count / max(min_samples, count)))
        roles_by_offset[offset] = role
        role_conf_by_offset[offset] = confidence
        # VALUE is an intentionally synthetic lane: it says the horizontal
        # offset is date-bearing even though no single TOP/BOTTOM lane is pure.
        roles_by_slot[f"{offset}:VALUE"] = role
        role_conf_by_slot[f"{offset}:VALUE"] = confidence

def _semantic_type(
    values: list[Any],
    *,
    min_confidence: float,
    status_max_unique: int,
    status_max_unique_ratio: float,
) -> tuple[str, float]:
    if not values:
        return "UNKNOWN", 0.0
    kinds = Counter(classify_value(v) for v in values if str(v).strip())
    total = sum(kinds.values())
    if total == 0:
        return "UNKNOWN", 0.0
    kind, count = kinds.most_common(1)[0]
    confidence = count / total
    if confidence < min_confidence:
        return "MIXED", confidence
    if kind == "DATE":
        return "DATE", confidence
    if kind == "REFERENCE":
        return "REFERENCE", confidence
    if kind == "CODE":
        unique = len({normalize_status(v) for v in values if str(v).strip()})
        unique_ratio = unique / total
        if unique <= status_max_unique and unique_ratio <= status_max_unique_ratio:
            return "STATUS", confidence
        return "CODE", confidence
    if kind == "TEXT":
        return "TEXT", confidence
    if kind == "NUMBER":
        return "NUMBER", confidence
    return kind, confidence


def _role_compatible(semantic_type: str, role: str | None) -> bool:
    if role is None:
        return False
    if role == "status":
        return semantic_type == "STATUS"
    if role == "reference":
        return semantic_type == "REFERENCE"
    if role in {"send_date", "receive_date"} or role.startswith("date_"):
        return semantic_type == "DATE"
    return False

def _shape_tokens(text: str) -> list[tuple[str, str | int]]:
    tokens: list[tuple[str, str | int]] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch.isdigit():
            j = i + 1
            while j < len(text) and text[j].isdigit():
                j += 1
            tokens.append(("D", j - i))
            i = j
            continue
        if "A" <= ch.upper() <= "Z":
            j = i + 1
            while j < len(text) and ("A" <= text[j].upper() <= "Z"):
                j += 1
            tokens.append(("L", j - i))
            i = j
            continue
        if "\u0600" <= ch <= "\u06ff":
            j = i + 1
            while j < len(text) and "\u0600" <= text[j] <= "\u06ff":
                j += 1
            tokens.append(("P", j - i))
            i = j
            continue
        if ch.isspace():
            j = i + 1
            while j < len(text) and text[j].isspace():
                j += 1
            tokens.append(("S", j - i))
            i = j
            continue
        tokens.append(("X", ch))
        i += 1
    return tokens


def _shape_signature(tokens: list[tuple[str, str | int]]) -> tuple[tuple[str, str], ...]:
    out: list[tuple[str, str]] = []
    for kind, value in tokens:
        if kind == "X":
            out.append((kind, str(value)))
        else:
            out.append((kind, "*"))
    return tuple(out)


def _regex_for_token_group(group: list[tuple[str, str | int]]) -> str:
    kind = group[0][0]
    if kind == "X":
        return re.escape(str(group[0][1]))
    lengths = [int(x[1]) for x in group]
    lo, hi = min(lengths), max(lengths)
    if kind == "D":
        atom = r"\d"
    elif kind == "L":
        atom = r"[A-Za-z]"
    elif kind == "P":
        atom = r"[\u0600-\u06FF]"
    elif kind == "S":
        return r"\s+"
    else:
        return r"."
    quant = f"{{{lo}}}" if lo == hi else f"{{{lo},{hi}}}"
    return atom + quant


def infer_reference_regex(values: Iterable[Any], min_samples: int = 5) -> ReferenceRule | None:
    normalized = [normalize_reference(v) for v in values if normalize_reference(v)]
    if len(normalized) < min_samples:
        return None
    grouped: dict[tuple[tuple[str, str], ...], list[list[tuple[str, str | int]]]] = defaultdict(list)
    raw_grouped: dict[tuple[tuple[str, str], ...], list[str]] = defaultdict(list)
    for text in normalized:
        tokens = _shape_tokens(text)
        signature = _shape_signature(tokens)
        grouped[signature].append(tokens)
        raw_grouped[signature].append(text)
    signature, token_sets = max(grouped.items(), key=lambda x: (len(x[1]), str(x[0])))
    count = len(token_sets)
    if count == 0:
        return None
    pieces = ["^"]
    token_count = len(token_sets[0])
    for index in range(token_count):
        token_group = [tokens[index] for tokens in token_sets]
        pieces.append(_regex_for_token_group(token_group))
    pieces.append("$")
    examples = tuple(dict.fromkeys(raw_grouped[signature]))[:6]
    return ReferenceRule(
        regex="".join(pieces),
        coverage=count / len(normalized),
        sample_count=len(normalized),
        matched_count=count,
        example_values=examples,
    )


def _infer_roles_by_offset(
    columns: list[ColumnProfile],
    data_start_col: int,
    block_width: int | None,
) -> tuple[dict[int, str], dict[int, float]]:
    if not block_width:
        return {}, {}
    by_offset: dict[int, list[ColumnProfile]] = defaultdict(list)
    for col in columns:
        by_offset[(col.column - data_start_col) % block_width].append(col)

    raw_roles: dict[int, tuple[str, float]] = {}
    date_offsets: list[tuple[int, float]] = []

    for offset, profiles in by_offset.items():
        # Header roles are only trusted when the observed semantic type supports them.
        header_votes = Counter(
            p.inferred_role
            for p in profiles
            if p.inferred_role
            and p.role_source == "HEADER"
            and _role_compatible(p.semantic_type, p.inferred_role)
        )
        if header_votes:
            role, count = header_votes.most_common(1)[0]
            raw_roles[offset] = (str(role), count / sum(header_votes.values()))
            continue

        semantic_votes = Counter(
            p.semantic_type
            for p in profiles
            if p.semantic_type in {"DATE", "STATUS", "REFERENCE"}
        )
        total = sum(semantic_votes.values())
        if not total:
            continue
        semantic, count = semantic_votes.most_common(1)[0]
        conf = count / total
        if semantic == "STATUS":
            raw_roles[offset] = ("status", conf)
        elif semantic == "REFERENCE":
            raw_roles[offset] = ("reference", conf)
        elif semantic == "DATE":
            date_offsets.append((offset, conf))

    for idx, (offset, conf) in enumerate(sorted(date_offsets)):
        if idx == 0:
            role = "send_date"
        elif idx == 1:
            role = "receive_date"
        else:
            role = f"date_{idx + 1}"
        raw_roles[offset] = (role, conf)

    return (
        {offset: role for offset, (role, _) in raw_roles.items()},
        {offset: conf for offset, (_, conf) in raw_roles.items()},
    )

def _infer_slot_roles_by_offset(
    profiles: list[SlotProfile],
    data_start_col: int,
    block_width: int | None,
) -> tuple[dict[str, str], dict[str, float], dict[int, str], dict[int, float]]:
    if not block_width:
        return {}, {}, {}, {}
    grouped: dict[tuple[int, str], list[SlotProfile]] = defaultdict(list)
    for p in profiles:
        grouped[((p.column - data_start_col) % block_width, p.lane)].append(p)

    raw: dict[tuple[int, str], tuple[str, float]] = {}
    date_groups: list[tuple[int, str, float]] = []
    for (offset, lane), items in grouped.items():
        header_votes = Counter(
            p.inferred_role for p in items
            if p.inferred_role and p.role_source == "HEADER" and _role_compatible(p.semantic_type, p.inferred_role)
        )
        if header_votes:
            role, count = header_votes.most_common(1)[0]
            raw[(offset, lane)] = (str(role), count / sum(header_votes.values()))
            continue
        semantic_votes = Counter(
            p.semantic_type for p in items
            if p.semantic_type in {"DATE", "STATUS", "REFERENCE"}
        )
        total = sum(semantic_votes.values())
        if not total:
            continue
        semantic, count = semantic_votes.most_common(1)[0]
        conf = count / total
        if semantic == "STATUS":
            raw[(offset, lane)] = ("status", conf)
        elif semantic == "REFERENCE":
            raw[(offset, lane)] = ("reference", conf)
        elif semantic == "DATE":
            date_groups.append((offset, lane, conf))

    # Dates are named by horizontal position within the transaction block. This
    # keeps TOP dates as send/receive fields even when BOTTOM lanes hold references.
    for idx, (offset, lane, conf) in enumerate(sorted(date_groups, key=lambda x: (x[0], x[1]))):
        if idx == 0:
            role = "send_date"
        elif idx == 1:
            role = "receive_date"
        else:
            role = f"date_{idx + 1}"
        raw[(offset, lane)] = (role, conf)

    by_slot = {f"{offset}:{lane}": role for (offset, lane), (role, _) in raw.items()}
    conf_by_slot = {f"{offset}:{lane}": conf for (offset, lane), (_, conf) in raw.items()}

    # Backward-compatible one-role-per-offset summary. Prefer TOP date, then FULL status,
    # then any remaining role. Detailed consumers must use roles_by_slot/slot_profiles.
    offset_roles: dict[int, str] = {}
    offset_conf: dict[int, float] = {}
    lane_priority = {"TOP": 0, "FULL": 1, "BOTTOM": 2, "MIDDLE": 3}
    for offset in range(block_width):
        candidates = [
            (lane_priority.get(lane, 9), role, conf)
            for (off, lane), (role, conf) in raw.items() if off == offset
        ]
        if candidates:
            _, role, conf = sorted(candidates, key=lambda x: (x[0], -x[2], x[1]))[0]
            offset_roles[offset] = role
            offset_conf[offset] = conf
    return by_slot, conf_by_slot, offset_roles, offset_conf


def infer_slot_schema(snapshot, profile: dict, sheet: str, card_scan: CardMapScan | None = None) -> SlotSchema:
    config = field_inference_config(profile)
    if card_scan is None:
        card_scan = scan_all_card_maps(snapshot, profile).get(sheet)
    if card_scan is None or card_scan.data_start_col is None or card_scan.data_end_col is None:
        return SlotSchema(
            sheet=sheet,
            data_start_col=0,
            data_end_col=0,
            block_width=None,
            block_confidence=0.0,
            roles_by_offset={},
            role_confidence_by_offset={},
            columns=(),
            issues=({"kind": "NO_CARD_MAP", "message": f"{sheet}: no usable card map."},),
        )

    values_by_col = _collect_column_values(card_scan)
    values_by_slot = _collect_slot_values(card_scan)

    # Build card-relative slot profiles first. The same absolute column may contain
    # a TOP date and a BOTTOM reference/text value, so column-only semantics are lossy.
    slot_profiles: list[SlotProfile] = []
    lane_order = {"TOP": 0, "FULL": 1, "BOTTOM": 2, "MIDDLE": 3}
    for (col, lane), values in sorted(values_by_slot.items(), key=lambda x: (x[0][0], lane_order.get(x[0][1], 9))):
        kind, kind_conf, unique, samples = _dominant_kind(values)
        headers = _header_texts(snapshot, sheet, col, config["header_rows"])
        header_role, header_conf = _header_role(headers)
        semantic_type, semantic_confidence = _semantic_type(
            values,
            min_confidence=config["semantic_min_confidence"],
            status_max_unique=config["status_max_unique"],
            status_max_unique_ratio=config["status_max_unique_ratio"],
        )
        trusted_header_role = (
            header_role
            if semantic_confidence >= config["semantic_min_confidence"]
            and _role_compatible(semantic_type, header_role)
            else None
        )
        slot_profiles.append(SlotProfile(
            column=col,
            letter=get_column_letter(col),
            lane=lane,
            headers=headers,
            non_empty=len(values),
            dominant_kind=kind,
            dominant_kind_confidence=kind_conf,
            unique_count=unique,
            samples=samples,
            semantic_type=semantic_type,
            semantic_confidence=semantic_confidence,
            inferred_role=trusted_header_role,
            role_confidence=header_conf if trusted_header_role else 0.0,
            role_source="HEADER" if trusted_header_role else None,
        ))

    # Detect horizontal block rhythm from the *set of stable lane semantics* in each
    # column (e.g. TOP:DATE + BOTTOM:REFERENCE versus FULL:STATUS).
    signature_by_col: dict[int, str] = {}
    for col in range(card_scan.data_start_col, card_scan.data_end_col + 1):
        stable = [
            f"{p.lane}:{p.semantic_type}"
            for p in slot_profiles
            if p.column == col and p.semantic_type not in {"UNKNOWN", "MIXED", "EMPTY"}
        ]
        signature_by_col[col] = "|".join(sorted(stable)) if stable else "MIXED"
    signatures = [signature_by_col[col] for col in range(card_scan.data_start_col, card_scan.data_end_col + 1)]
    periodic_width, periodic_confidence = _detect_block_width(
        signatures,
        config["max_block_width"],
        fundamental_tolerance=config["block_fundamental_tolerance"],
    )
    block_width = periodic_width
    block_confidence = periodic_confidence
    block_source = "SEMANTIC_PERIODICITY"
    block_evidence: dict[str, Any] = {}

    if block_width is None or block_confidence < config["min_block_confidence"]:
        anchor_width = None
        anchor_confidence = 0.0
        anchor_evidence: dict[str, Any] = {}
        if config["anchor_block_inference"]:
            anchor_width, anchor_confidence, anchor_evidence = _infer_block_width_from_semantic_anchors(
                slot_profiles,
                max_width=config["max_block_width"],
                min_semantic_confidence=config["semantic_min_confidence"],
                min_columns=config["anchor_min_columns"],
                min_spacing_coverage=config["anchor_min_spacing_coverage"],
            )
        if anchor_width is not None and anchor_confidence >= config["min_block_confidence"]:
            block_width = anchor_width
            block_confidence = anchor_confidence
            block_source = "SEMANTIC_ANCHOR_SPACING"
            block_evidence = anchor_evidence
        else:
            block_width = None

    roles_by_slot, role_conf_by_slot, roles, role_confidences = _infer_slot_roles_by_offset(
        slot_profiles, card_scan.data_start_col, block_width
    )
    _augment_mixed_offset_date_roles(
        card_scan,
        data_start_col=card_scan.data_start_col,
        block_width=block_width,
        roles_by_slot=roles_by_slot,
        role_conf_by_slot=role_conf_by_slot,
        roles_by_offset=roles,
        role_conf_by_offset=role_confidences,
        min_samples=config["mixed_offset_date_min_samples"],
        min_share=config["mixed_offset_date_min_share"],
    )

    enriched_slots: list[SlotProfile] = []
    for p in slot_profiles:
        if p.inferred_role:
            enriched_slots.append(p)
            continue
        role = None
        conf = 0.0
        if block_width and p.semantic_confidence >= config["semantic_min_confidence"]:
            offset = (p.column - card_scan.data_start_col) % block_width
            key = f"{offset}:{p.lane}"
            candidate_role = roles_by_slot.get(key)
            candidate_conf = min(
                p.semantic_confidence,
                role_conf_by_slot.get(key, 0.0) * block_confidence,
            )
            if candidate_conf >= config["min_role_confidence"] and _role_compatible(p.semantic_type, candidate_role):
                role = candidate_role
                conf = candidate_conf
        enriched_slots.append(SlotProfile(
            column=p.column,
            letter=p.letter,
            lane=p.lane,
            headers=p.headers,
            non_empty=p.non_empty,
            dominant_kind=p.dominant_kind,
            dominant_kind_confidence=p.dominant_kind_confidence,
            unique_count=p.unique_count,
            samples=p.samples,
            semantic_type=p.semantic_type,
            semantic_confidence=p.semantic_confidence,
            inferred_role=role,
            role_confidence=conf,
            role_source="MAJORITY_PATTERN" if role else None,
        ))
    slot_profiles = enriched_slots

    # Retain a human-readable column summary for compatibility, but do not use it
    # to drive validation when a column contains multiple vertical semantics.
    columns: list[ColumnProfile] = []
    for col in range(card_scan.data_start_col, card_scan.data_end_col + 1):
        values = values_by_col.get(col, [])
        kind, kind_conf, unique, samples = _dominant_kind(values)
        headers = _header_texts(snapshot, sheet, col, config["header_rows"])
        lane_profiles = [p for p in slot_profiles if p.column == col]
        stable_semantics = {p.semantic_type for p in lane_profiles if p.semantic_type not in {"UNKNOWN", "MIXED", "EMPTY"}}
        if len(stable_semantics) == 1:
            semantic_type = next(iter(stable_semantics))
        elif stable_semantics:
            semantic_type = "COMPOSITE"
        elif any(p.semantic_type == "MIXED" for p in lane_profiles):
            semantic_type = "MIXED"
        else:
            semantic_type = "UNKNOWN"
        semantic_confidence = max((p.semantic_confidence for p in lane_profiles), default=0.0)
        roles_here = {p.inferred_role for p in lane_profiles if p.inferred_role}
        inferred_role = next(iter(roles_here)) if len(roles_here) == 1 else None
        role_confidence = max((p.role_confidence for p in lane_profiles if p.inferred_role == inferred_role), default=0.0) if inferred_role else 0.0
        columns.append(ColumnProfile(
            column=col,
            letter=get_column_letter(col),
            headers=headers,
            non_empty=len(values),
            dominant_kind=kind,
            dominant_kind_confidence=kind_conf,
            unique_count=unique,
            samples=samples,
            semantic_type=semantic_type,
            semantic_confidence=semantic_confidence,
            inferred_role=inferred_role,
            role_confidence=role_confidence,
            role_source="SLOT_LANES" if inferred_role else None,
        ))

    reference_values: list[Any] = []
    status_values_raw: list[str] = []
    provisional = SlotSchema(
        sheet=sheet, data_start_col=card_scan.data_start_col, data_end_col=card_scan.data_end_col,
        block_width=block_width, block_confidence=block_confidence, roles_by_offset=roles,
        role_confidence_by_offset=role_confidences, columns=tuple(columns),
        slot_profiles=tuple(slot_profiles), roles_by_slot=roles_by_slot,
        block_source=block_source, block_evidence=block_evidence,
    )
    for card in card_scan.cards:
        for slot in card.slots:
            role = provisional.role_for_slot(card, slot)
            if role == "reference" and slot.value is not None and str(slot.value).strip():
                reference_values.append(slot.value)
            elif role == "status" and slot.value is not None and str(slot.value).strip():
                status_values_raw.append(normalize_status(slot.value))

    reference_rule = infer_reference_regex(reference_values, config["reference_min_samples"])
    if reference_rule is not None and reference_rule.coverage < config["reference_min_coverage"]:
        reference_rule = None

    status_counts = Counter(x for x in status_values_raw if x)
    status_values: tuple[str, ...] = ()
    status_coverage = 0.0
    if status_counts:
        accepted = [value for value, count in status_counts.items() if count >= config["status_min_occurrences"]]
        if not accepted:
            accepted = list(status_counts)
        covered = sum(status_counts[x] for x in accepted)
        status_coverage = covered / sum(status_counts.values())
        if status_coverage >= config["status_min_coverage"]:
            status_values = tuple(sorted(accepted))

    issues: list[dict[str, Any]] = []
    if block_width is None:
        issues.append({
            "kind": "BLOCK_WIDTH_UNRESOLVED",
            "message": f"{sheet}: no repeating transaction block width reached the confidence threshold.",
            "block_confidence": block_confidence,
        })
    if not any(p.inferred_role in {"send_date", "receive_date", "status", "reference"} for p in slot_profiles):
        issues.append({
            "kind": "NO_SEMANTIC_ROLES",
            "message": f"{sheet}: no date/status/reference roles were inferred from headers or majority patterns.",
        })

    return SlotSchema(
        sheet=sheet,
        data_start_col=card_scan.data_start_col,
        data_end_col=card_scan.data_end_col,
        block_width=block_width,
        block_confidence=block_confidence,
        roles_by_offset=roles,
        role_confidence_by_offset=role_confidences,
        columns=tuple(columns),
        slot_profiles=tuple(slot_profiles),
        roles_by_slot=roles_by_slot,
        reference_rule=reference_rule,
        status_values=status_values,
        status_coverage=status_coverage,
        status_overrides_geometry=config["known_status_overrides_geometry"],
        block_source=block_source,
        block_evidence=block_evidence,
        issues=tuple(issues),
    )


def infer_all_slot_schemas(snapshot, profile: dict) -> dict[str, SlotSchema]:
    card_scans = scan_all_card_maps(snapshot, profile)
    return {
        sheet: infer_slot_schema(snapshot, profile, sheet, card_scan=scan)
        for sheet, scan in card_scans.items()
    }


def iter_role_slots(card_scan: CardMapScan, schema: SlotSchema):
    for card in card_scan.cards:
        for slot in card.slots:
            role = schema.role_for_slot(card, slot)
            if role:
                yield card, slot, role
