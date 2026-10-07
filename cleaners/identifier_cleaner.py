from __future__ import annotations

import re
from typing import Any


_PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def normalize_digits(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().translate(_PERSIAN_DIGITS).translate(_ARABIC_DIGITS)


def is_empty_name(value: Any) -> bool:
    return value is None or str(value).strip() == ""


def is_valid_wbs(value: Any, pattern: str) -> bool:
    text = normalize_digits(value)
    if not text:
        return False
    return re.fullmatch(pattern, text) is not None


def is_invalid_identifier_token(value: Any, tokens: list[Any] | tuple[Any, ...] | None = None) -> bool:
    text = normalize_digits(value)
    normalized_tokens = {normalize_digits(x) for x in (tokens or [None, "", "-", "–", "—"])}
    return text in normalized_tokens


def is_valid_sequence_identifier(value: Any, validation: dict | None = None) -> bool:
    validation = dict(validation or {})
    kind = str(validation.get("kind") or "NON_EMPTY").upper()
    text = normalize_digits(value)
    empty_tokens = validation.get("empty_or_invalid_tokens") or validation.get("empty_tokens")
    if is_invalid_identifier_token(value, empty_tokens):
        return False
    if kind == "REGEX":
        pattern = str(validation.get("pattern") or "")
        return bool(pattern and re.fullmatch(pattern, text))
    return bool(text)


def propose_empty_name(row: int, cleaning_cfg: dict) -> str:
    template = str(cleaning_cfg.get("template") or "ERR_EMPT_NAME_{NUMBER}")
    strategy = str(cleaning_cfg.get("number_strategy") or "ROW_NUMBER").upper()

    if strategy == "ROW_NUMBER":
        number = row
    else:
        # ROW_NUMBER is intentionally the default because it is deterministic.
        # An independent sequence can be introduced later without changing callers.
        number = row

    return template.replace("{NUMBER}", str(number))


class WbsProposalState:
    """
    Keeps placeholder numbering deterministic while scanning top-to-bottom.

    For nearest valid WBS 1.2.3:
        first invalid  -> 1.2.3.1000
        second invalid -> 1.2.3.1001

    When a new valid WBS is encountered, the placeholder suffix resets.
    """

    def __init__(self, sequence_start: int = 1000, separator: str = ".", fallback_root_start: int = 1000):
        self.sequence_start = int(sequence_start)
        self.separator = separator
        self.fallback_root_start = int(fallback_root_start)
        self.nearest_valid_above: str | None = None
        self._next_by_parent: dict[str | None, int] = {}

    def observe_valid(self, wbs: Any):
        normalized = normalize_digits(wbs)
        self.nearest_valid_above = normalized
        self._next_by_parent.setdefault(normalized, self.sequence_start)

    def propose(self) -> tuple[str, str | None]:
        parent = self.nearest_valid_above

        if parent is None:
            next_value = self._next_by_parent.get(None, self.fallback_root_start)
            self._next_by_parent[None] = next_value + 1
            return str(next_value), None

        next_value = self._next_by_parent.get(parent, self.sequence_start)
        self._next_by_parent[parent] = next_value + 1
        return f"{parent}{self.separator}{next_value}", parent


def proposed_set_value_fix(
    *,
    field_key: str,
    sheet: str,
    target: str,
    value: Any,
    reason: str,
    expected_old_value: Any = None,
) -> dict:
    return {
        "action": "SET_VALUE",
        "execution_kind": "WORKBOOK_CHANGE",
        "parameters": {
            "field_key": field_key,
            "sheet": sheet,
            "target": target,
            "value": value,
            "expected_old_value": expected_old_value,
        },
        "reason": reason,
    }
