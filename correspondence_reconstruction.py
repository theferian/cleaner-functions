"""Non-destructive reconstruction of correspondence events for Cleaner.

Canonicalize repeated physical representations of one letter while retaining
all its source locations. Does not infer hard send/receive relationships from
revision order, source position, or coincident dates.

Input/output use the existing immutable LogRecord contract. The original
Board->Log remains the exhaustive transaction audit.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable
import re
import unicodedata

from functions.board_to_log.contracts import LogRecord
from cleaner_core.status_library import normalize_status_token


_DATE = re.compile(r"^(\d{4})/(\d{2})/(\d{2})$")


def _text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(unicodedata.normalize("NFKC", str(value)).split()).casefold()


def _date(value: Any) -> str | None:
    token = str(value or "").strip()
    match = _DATE.fullmatch(token)
    if not match:
        return None
    _, m, d = (int(x) for x in match.groups())
    if not 1 <= m <= 12 or not 1 <= d <= (31 if m <= 6 else 30):
        return None
    return token


def _order(record: LogRecord) -> tuple[int, int, int, int, int]:
    return (
        int(record.block_index if record.block_index is not None else -1),
        int(record.event_index or 0),
        0 if record.send_or_receive == "send" else 1,
        int(record.source_row or -1),
        int(record.source_col or -1),
    )


def _source(record: LogRecord) -> dict[str, Any]:
    return {
        "date_source": record.date_source,
        "reference_source": record.reference_source,
        "status_source": record.status_source,
        "source_row": record.source_row,
        "source_col": record.source_col,
        "block_index": record.block_index,
        "event_index": record.event_index,
        "revision": record.doc_rev,
    }


def _status(record: LogRecord, library: Any) -> str:
    canonical = library.canonicalize(record.doc_status) if library else None
    return canonical or normalize_status_token(record.doc_status)


@dataclass
class Reconstruction:
    events: list[LogRecord] = field(default_factory=list)
    representations: list[dict[str, Any]] = field(default_factory=list)
    overlaps: list[dict[str, Any]] = field(default_factory=list)
    possible_links: list[dict[str, Any]] = field(default_factory=list)
    diagnostics: list[dict[str, Any]] = field(default_factory=list)
    raw_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_events": self.raw_count,
            "canonical_events": len(self.events),
            "duplicate_representation_count": self.raw_count - len(self.events),
            "representations": self.representations,
            "overlapping_submission_groups": self.overlaps,
            "possible_source_slot_links": self.possible_links,
        }


def reconstruct_correspondence(
    records: Iterable[LogRecord], *, status_library: Any = None
) -> Reconstruction:
    """Collapse exact same-letter representations, preserving their provenance.

    Identity is (sheet, document index, direction, letter reference, date,
    canonical status). A date and reference must BOTH be usable before any
    deduplication. Ambiguous references never get silently merged.
    """
    raw = list(records)
    result = Reconstruction(raw_count=len(raw))
    by_id: dict[tuple[str, int, str, str, str, str], list[LogRecord]] = {}
    ambiguous: list[LogRecord] = []
    by_reference: dict[tuple[str, int, str, str], list[LogRecord]] = {}

    for event in raw:
        reference = _text(event.letter_reference)
        date = _date(event.letter_date)
        side = str(event.send_or_receive or "").lower()
        if reference:
            by_reference.setdefault(
                (event.source_sheet, int(event.document_index), side, reference), []
            ).append(event)
        if not reference or not date or side not in ("send", "receive"):
            ambiguous.append(event)
            continue
        key = (
            event.source_sheet, int(event.document_index), side, reference,
            date, _status(event, status_library),
        )
        by_id.setdefault(key, []).append(event)

    # Distinct dates or response statuses for the same reference are *not*
    # deduplicated; require source review instead of deciding which is true.
    for (sheet, index, side, reference), instances in sorted(by_reference.items()):
        variants = sorted({(_date(x.letter_date) or str(x.letter_date or ""),
                            _status(x, status_library)) for x in instances})
        if len(variants) > 1:
            result.diagnostics.append({
                "kind": "CORRESPONDENCE_REFERENCE_CONFLICT",
                "source_sheet": sheet,
                "document_index": index,
                "side": side,
                "letter_reference": reference,
                "variants": [{"date": date, "status": status} for date, status in variants],
                "source_locations": [_source(x) for x in sorted(instances, key=_order)],
            })

    result.events.extend(ambiguous)
    for key, items in by_id.items():
        items.sort(key=_order)
        result.events.append(items[0])
        if len(items) > 1:
            result.representations.append({
                "direction": key[2],
                "letter_reference": items[0].letter_reference,
                "letter_date": key[4],
                "status": key[5] or None,
                "source_locations": [_source(x) for x in items],
            })

    result.events.sort(key=_order)

    # Source rows cannot prove which event happened first when only the same
    # Jalali calendar day is known for opposite-direction correspondence.
    by_day: dict[str, list[LogRecord]] = {}
    for event in result.events:
        date = _date(event.letter_date)
        if date:
            by_day.setdefault(date, []).append(event)
    for date, same_day in sorted(by_day.items()):
        if {x.send_or_receive for x in same_day} >= {"send", "receive"}:
            result.diagnostics.append({
                "kind": "SAME_DAY_DIRECTION_ORDER_UNVERIFIED",
                "letter_date": date,
                "events": [
                    {"direction": x.send_or_receive,
                     "letter_reference": x.letter_reference,
                     "source": _source(x)}
                    for x in same_day
                ],
            })

    # Observed overlap is not an error and does not imply that one receive
    # answers a specific send. Separate source-slot links are *candidates*.
    dated = [x for x in result.events if _date(x.letter_date)]
    dated.sort(key=lambda x: (_date(x.letter_date), _order(x)))
    pending_sends: list[LogRecord] = []
    for event in dated:
        if event.send_or_receive == "send":
            pending_sends.append(event)
        elif event.send_or_receive == "receive":
            if len(pending_sends) > 1:
                result.overlaps.append({
                    "before_receive": _source(event),
                    "send_dates": [str(x.letter_date) for x in pending_sends],
                    "send_references": [x.letter_reference for x in pending_sends],
                    "link_status": "NOT_INFERRED",
                })
            pending_sends.clear()

    slots: dict[tuple[int, int], dict[str, list[LogRecord]]] = {}
    for event in result.events:
        if event.block_index is None or event.event_index is None:
            continue
        slot = (int(event.block_index), int(event.event_index))
        slots.setdefault(slot, {}).setdefault(event.send_or_receive, []).append(event)
    for (block, event_index), sides in sorted(slots.items()):
        sends = sides.get("send", [])
        receives = sides.get("receive", [])
        if len(sends) != 1 or len(receives) != 1:
            continue
        send, receive = sends[0], receives[0]
        start, end = _date(send.letter_date), _date(receive.letter_date)
        if start and end and end >= start:
            result.possible_links.append({
                "block_index": block,
                "event_index": event_index,
                "send_reference": send.letter_reference,
                "receive_reference": receive.letter_reference,
                "link_basis": "SOURCE_SLOT_ONLY",
                "confirmed": False,
            })

    return result
