from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Any, Iterable

from cleaner_core.status_library import load_status_library, normalize_status_token

from cleaner_core.correspondence_reconstruction import reconstruct_correspondence
from functions.board_to_log.contracts import LogRecord
from functions.cleaner.service import CleanerRun


_DATE_RE = re.compile(r"^(1[34]\d{2})/(0[1-9]|1[0-2])/(0[1-9]|[12]\d|3[01])$")


@dataclass(frozen=True)
class EngineeringExceptionRow:
    source_sheet: str
    document_index: int
    doc_name: Any
    doc_wbs: Any
    revision: str | None = None
    responsibility: str | None = None
    current_holder: str | None = None
    responsible_unit: str | None = None
    unit_basis: str | None = None
    responsibility_since: str | None = None
    responsibility_age_days: int | None = None
    state: str | None = None
    last_action_date: str | None = None
    last_action_text: Any = None
    status: Any = None
    status_meaning: str | None = None
    elapsed_days: int | None = None
    allowance_days: int | None = None
    delay_days: int | None = None
    calculation_status: str = "OK"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EngineeringThreeLists:
    status_date: str
    not_sent: list[EngineeringExceptionRow] = field(default_factory=list)
    company_delay: list[EngineeringExceptionRow] = field(default_factory=list)
    consultant_delay: list[EngineeringExceptionRow] = field(default_factory=list)
    diagnostics: list[dict[str, Any]] = field(default_factory=list)
    correspondence_audit: list[dict[str, Any]] = field(default_factory=list)

    def delay_register(self) -> list[EngineeringExceptionRow]:
        rows = [*self.company_delay, *self.consultant_delay]
        return sorted(
            rows,
            key=lambda row: (
                row.delay_days is None,
                -(row.delay_days or 0),
                str(row.responsibility_since or ""),
                str(row.doc_name or ""),
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        company_by_unit: dict[str, int] = {}
        for row in self.company_delay:
            unit = row.responsible_unit or "UNASSIGNED"
            company_by_unit[unit] = company_by_unit.get(unit, 0) + 1
        return {
            "schema": "engineering.three_lists/0.2",
            "status_date": self.status_date,
            "summary": {
                "not_sent": len(self.not_sent),
                "company_delay": len(self.company_delay),
                "consultant_delay": len(self.consultant_delay),
                "delay_register": len(self.company_delay) + len(self.consultant_delay),
                "company_delay_by_unit": company_by_unit,
                "diagnostic_count": len(self.diagnostics),
            },
            "lists": {
                "01_Not_Sent": [x.to_dict() for x in self.not_sent],
                "02_Company_Delay": [x.to_dict() for x in self.company_delay],
                "03_Consultant_Delay": [x.to_dict() for x in self.consultant_delay],
                "04_Delay_Register": [x.to_dict() for x in self.delay_register()],
            },
            "correspondence_audit": list(self.correspondence_audit),
            "diagnostics": list(self.diagnostics),
        }


def _jalali_parts(value: Any) -> tuple[int, int, int] | None:
    if value is None:
        return None
    match = _DATE_RE.fullmatch(str(value).strip())
    if not match:
        return None
    y, m, d = (int(x) for x in match.groups())
    max_day = 31 if m <= 6 else 30
    if m == 12:
        # The 33-year algorithm below handles the leap-day boundary by date
        # conversion; broad validation here only prevents impossible >30 days.
        max_day = 30
    if d > max_day:
        return None
    return y, m, d


def jalali_to_gregorian(jy: int, jm: int, jd: int) -> tuple[int, int, int]:
    """Convert Jalali to Gregorian using the reciprocal 33-year algorithm.

    This matches the conversion family already used by Retrieval for current
    Jalali dates and is sufficient for the 13xx/14xx Project Control dates.
    """
    jy2 = jy - 979
    jm2 = jm - 1
    jd2 = jd - 1
    j_days_in_month = [31, 31, 31, 31, 31, 31, 30, 30, 30, 30, 30, 29]
    j_day_no = 365 * jy2 + (jy2 // 33) * 8 + ((jy2 % 33) + 3) // 4
    for i in range(jm2):
        j_day_no += j_days_in_month[i]
    j_day_no += jd2

    g_day_no = j_day_no + 79
    gy = 1600 + 400 * (g_day_no // 146097)
    g_day_no %= 146097
    leap = True
    if g_day_no >= 36525:
        g_day_no -= 1
        gy += 100 * (g_day_no // 36524)
        g_day_no %= 36524
        if g_day_no >= 365:
            g_day_no += 1
        else:
            leap = False
    gy += 4 * (g_day_no // 1461)
    g_day_no %= 1461
    if g_day_no >= 366:
        leap = False
        g_day_no -= 1
        gy += g_day_no // 365
        g_day_no %= 365

    g_days_in_month = [31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    gm = 0
    while gm < 12 and g_day_no >= g_days_in_month[gm]:
        g_day_no -= g_days_in_month[gm]
        gm += 1
    return gy, gm + 1, g_day_no + 1


def jalali_day_difference(later: Any, earlier: Any) -> int | None:
    from datetime import date

    later_parts = _jalali_parts(later)
    earlier_parts = _jalali_parts(earlier)
    if not later_parts or not earlier_parts:
        return None
    lg = jalali_to_gregorian(*later_parts)
    eg = jalali_to_gregorian(*earlier_parts)
    return (date(*lg) - date(*eg)).days


def _doc_key(record: LogRecord) -> tuple[str, int]:
    return record.source_sheet, int(record.document_index)


def _sequence_key(record: LogRecord) -> tuple[int, int, int]:
    # block_index follows revision order. Within one transaction index, SEND
    # precedes RECEIVE, making the latest canonical state deterministic even if
    # the receive is narrative and has no calculable date.
    return (
        int(record.block_index if record.block_index is not None else -1),
        int(record.event_index or 0),
        0 if record.send_or_receive == "send" else 1,
    )


def _order_events_chronologically(
    doc_records: list[LogRecord], *, status_date: str
) -> tuple[list[LogRecord], list[dict[str, Any]]]:
    """Order *dated* transactions by Jalali day, not revision/slot position.

    Source sequence is only a tie-breaker for equal dates. An undated event
    cannot safely be assigned a calendar position: preserve it as potentially
    latest when its source sequence follows the latest dated event, and emit
    a diagnostic whenever an undated event makes chronology uncertain.

    Future-dated records are retained as evidence but excluded from the state
    as of status_date; the caller must not mistake that for no history.
    """
    dated: list[LogRecord] = []
    undated: list[LogRecord] = []
    future: list[LogRecord] = []
    diagnostics: list[dict[str, Any]] = []
    as_of = _jalali_parts(status_date)
    for event in doc_records:
        date = _jalali_parts(event.letter_date)
        if date is None:
            undated.append(event)
        elif as_of is not None and date > as_of:
            future.append(event)
        else:
            dated.append(event)

    # Lexicographic YYYY/MM/DD components are chronological Jalali dates.
    dated.sort(key=lambda x: (_jalali_parts(x.letter_date), _sequence_key(x)))
    undated.sort(key=_sequence_key)

    if future:
        diagnostics.append({
            "kind": "FUTURE_DATED_EVENT_EXCLUDED",
            "count": len(future),
            "events": [
                {"date": str(x.letter_date), "side": x.send_or_receive,
                 "revision": x.doc_rev, "block_index": x.block_index,
                 "event_index": x.event_index}
                for x in future
            ],
        })

    # Logbook source/revision order may disagree with dated event order.
    by_source = sorted(dated, key=_sequence_key)
    inverted_pairs = [
        (left, right)
        for left, right in zip(by_source, by_source[1:])
        if _jalali_parts(left.letter_date) > _jalali_parts(right.letter_date)
    ]
    if inverted_pairs:
        diagnostics.append({
            "kind": "SOURCE_SEQUENCE_DATE_INVERSION",
            "count": len(inverted_pairs),
            "examples": [
                {"earlier_source_date": str(left.letter_date),
                 "later_source_date": str(right.letter_date),
                 "earlier_source_side": left.send_or_receive,
                 "later_source_side": right.send_or_receive}
                for left, right in inverted_pairs[:5]
            ],
        })

    # A RECEIVE before its paired SEND is an evidence problem, not an
    # ordinary response-time interval. Preserve both events and flag it.
    transaction_pairs: dict[tuple[int, int], dict[str, list[LogRecord]]] = {}
    for event in dated:
        pair_key = (int(event.block_index if event.block_index is not None else -1),
                    int(event.event_index or 0))
        transaction_pairs.setdefault(pair_key, {}).setdefault(event.send_or_receive, []).append(event)
    contradictions = []
    for pair_key, parts in transaction_pairs.items():
        for send in parts.get("send", []):
            for receive in parts.get("receive", []):
                if _jalali_parts(receive.letter_date) < _jalali_parts(send.letter_date):
                    contradictions.append({
                        "block_index": pair_key[0], "event_index": pair_key[1],
                        "send_date": str(send.letter_date),
                        "receive_date": str(receive.letter_date),
                    })
    if contradictions:
        diagnostics.append({
            "kind": "RECEIVE_BEFORE_MATCHED_SEND",
            "count": len(contradictions),
            "examples": contradictions[:5],
        })

    if not dated:
        # With no usable dates, preserve original semantic source order and
        # let the existing NEEDS_DATE behavior handle the current state.
        if undated:
            diagnostics.append({"kind": "ALL_EVENTS_UNDATED", "count": len(undated)})
        return undated, diagnostics

    latest_dated = dated[-1]
    earlier_undated = [x for x in undated if _sequence_key(x) <= _sequence_key(latest_dated)]
    later_undated = [x for x in undated if _sequence_key(x) > _sequence_key(latest_dated)]
    if undated:
        diagnostics.append({
            "kind": "UNRESOLVED_UNDATED_EVENT_ORDER",
            "count": len(undated),
            "potentially_latest": len(later_undated),
            "latest_dated_event": str(latest_dated.letter_date),
        })

    return earlier_undated + dated + later_undated, diagnostics


def _identity(record: LogRecord) -> dict[str, Any]:
    return {
        "source_sheet": record.source_sheet,
        "document_index": int(record.document_index),
        "doc_name": record.doc_name,
        "doc_wbs": record.doc_wbs,
    }



def document_inventory_from_cleaner(run: CleanerRun) -> list[dict[str, Any]]:
    """Return every Cleaner document, including documents with zero transactions."""
    state = run.state()
    inventory: list[dict[str, Any]] = []
    for sheet, payload in (run.document_regions().get("sheets") or {}).items():
        for region in payload.get("regions", []):
            values: dict[str, Any] = {}
            for field_key, field in (region.get("fields") or {}).items():
                address = str(field.get("address") or "")
                value = field.get("value")
                if address:
                    override = (state.get("value_overrides") or {}).get(f"{sheet}!{address}".upper())
                    if override is not None:
                        value = override.get("value")
                values[str(field_key)] = value
            inventory.append({
                "source_sheet": sheet,
                "document_index": int(region.get("record_index")),
                "doc_name": values.get("name") or values.get("document_name") or values.get("doc_name"),
                "doc_wbs": values.get("wbs") or values.get("document_wbs") or values.get("doc_wbs"),
                "document_fields": values,
            })
    return inventory



def _responsible_unit(inventory_item: dict[str, Any]) -> tuple[str | None, str | None]:
    """Infer the internal engineering unit from Cleaner identifier metadata.

    Project profiles use slightly different identifier names. FSH exposes a
    Category field (LV/HV/CIVIL), while AZD/JND expose Document Type for the
    same discipline-level ownership. Keep the raw project vocabulary instead
    of inventing organisation names; a later unit map can translate these
    tokens into formal department names.
    """
    fields = inventory_item.get("document_fields") or {}
    for key in ("responsible_unit", "unit", "category", "discipline", "document_type"):
        value = fields.get(key)
        if value is None:
            value = inventory_item.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text, key
    return None, None

def build_three_engineering_lists(
    records: Iterable[LogRecord],
    *,
    status_date: str,
    document_inventory: Iterable[dict[str, Any]] | None = None,
    company_allowance_days: int = 0,
    consultant_allowance_days: int = 0,
    company_response_statuses: Iterable[str] | None = None,
    status_library_path: str | None = None,
) -> EngineeringThreeLists:
    """Build the three current engineering exception lists.

    The lists are current-state exception lists, not historical cycle KPIs:

    01 Not Sent
        No SEND event exists for the document.

    02 Company Delay
        Latest canonical event is a RECEIVE whose status requires our response,
        and no later SEND exists. Delay is measured from that receive date to
        the Status Date, less the configured company allowance.

    03 Consultant Delay
        Latest canonical event is a SEND with no later RECEIVE. Delay is
        measured from that send date to the Status Date, less the configured
        consultant allowance.

    Narrative RECEIVE events are retained. If they have no canonical date, the
    document is still placed in the appropriate responsibility list with
    calculation_status=NEEDS_DATE and delay_days=None.
    """
    if _jalali_parts(status_date) is None:
        raise ValueError(f"status_date must be canonical Jalali YYYY/MM/DD, got {status_date!r}")
    company_allowance_days = max(0, int(company_allowance_days))
    consultant_allowance_days = max(0, int(consultant_allowance_days))
    status_library = load_status_library(status_library_path)
    if company_response_statuses is None:
        # Preserve the historically configured CM/RJ behavior while allowing
        # the reusable library to contribute workflow semantics. As meanings
        # are defined in the library, hardcoded project knowledge can shrink.
        response_statuses = status_library.statuses_for_responsibility("COMPANY")
    else:
        response_statuses = {
            status_library.canonicalize(x) or normalize_status_token(x)
            for x in company_response_statuses
            if normalize_status_token(x)
        }

    result = EngineeringThreeLists(status_date=status_date)
    grouped: dict[tuple[str, int], list[LogRecord]] = {}
    for record in records:
        grouped.setdefault(_doc_key(record), []).append(record)

    inventory_map: dict[tuple[str, int], dict[str, Any]] = {}
    for item in document_inventory or []:
        key = (str(item.get("source_sheet")), int(item.get("document_index")))
        inventory_map[key] = dict(item)

    all_keys = sorted(set(grouped) | set(inventory_map))
    for key in all_keys:
        doc_records = grouped.get(key, [])
        reconstruction = reconstruct_correspondence(
            doc_records, status_library=status_library
        )
        ordered, chronology_issues = _order_events_chronologically(
            reconstruction.events, status_date=status_date
        )
        sends = [x for x in ordered if x.send_or_receive == "send"]
        inventory_item = inventory_map.get(key) or {}
        responsible_unit, unit_basis = _responsible_unit(inventory_item)
        if ordered:
            identity = _identity(ordered[0])
        else:
            identity = {
                "source_sheet": key[0],
                "document_index": key[1],
                "doc_name": inventory_item.get("doc_name"),
                "doc_wbs": inventory_item.get("doc_wbs"),
            }

        result.diagnostics.extend({**identity, **issue} for issue in chronology_issues)
        if doc_records:
            result.correspondence_audit.append({**identity, **reconstruction.to_dict()})
        result.diagnostics.extend({**identity, **issue} for issue in reconstruction.diagnostics)
        if not ordered and doc_records:
            # Interactions exist, but all are after the Status Date.
            continue

        if not ordered:
            latest = ordered[-1] if ordered else None
            result.not_sent.append(EngineeringExceptionRow(
                **identity,
                revision=(latest.doc_rev if latest else None),
                responsibility="COMPANY",
                current_holder=responsible_unit or "COMPANY",
                responsible_unit=responsible_unit,
                unit_basis=unit_basis,
                responsibility_since=None,
                responsibility_age_days=None,
                state="NOT_SENT",
                last_action_date=(str(latest.letter_date) if latest and _jalali_parts(latest.letter_date) else None),
                last_action_text=(latest.raw_source_value if latest else None),
                status=(latest.doc_status if latest else None),
                calculation_status="NO_INTERACTION_HISTORY",
            ))
            continue

        latest = ordered[-1]
        if latest.send_or_receive == "send":
            elapsed = jalali_day_difference(status_date, latest.letter_date)
            if elapsed is None:
                result.consultant_delay.append(EngineeringExceptionRow(
                    **identity,
                    revision=latest.doc_rev,
                    responsibility="CONSULTANT",
                    current_holder="CONSULTANT",
                    responsible_unit=None,
                    unit_basis=None,
                    responsibility_since=None,
                    responsibility_age_days=None,
                    state="WAITING_CONSULTANT_RESPONSE",
                    last_action_date=None,
                    last_action_text=latest.letter_date,
                    elapsed_days=None,
                    allowance_days=consultant_allowance_days,
                    delay_days=None,
                    calculation_status="NEEDS_DATE",
                ))
                result.diagnostics.append({
                    "kind": "UNDATED_CONSULTANT_WAIT_START",
                    **identity,
                    "revision": latest.doc_rev,
                    "value": latest.letter_date,
                })
            else:
                delay = max(0, elapsed - consultant_allowance_days)
                if delay > 0:
                    result.consultant_delay.append(EngineeringExceptionRow(
                        **identity,
                        revision=latest.doc_rev,
                        responsibility="CONSULTANT",
                        current_holder="CONSULTANT",
                        responsible_unit=None,
                        unit_basis=None,
                        responsibility_since=str(latest.letter_date),
                        responsibility_age_days=elapsed,
                        state="WAITING_CONSULTANT_RESPONSE",
                        last_action_date=str(latest.letter_date),
                        last_action_text=latest.raw_source_value,
                        elapsed_days=elapsed,
                        allowance_days=consultant_allowance_days,
                        delay_days=delay,
                    ))
            continue

        status_definition = status_library.definition(latest.doc_status)
        status = status_library.canonicalize(latest.doc_status) or normalize_status_token(latest.doc_status)
        status_meaning = None
        if status_definition is not None:
            status_meaning = status_definition.meaning or status_definition.meaning_fa
        # Closed engineering statuses A/AP/FC require no further
        # engineering work and are excluded from all three active
        # engineering lists. WBS finish approval is evaluated later.
        if (
            latest.send_or_receive == "receive"
            and status_definition is not None
            and status_definition.action_required is False
        ):
            continue

        if latest.send_or_receive == "receive" and status not in response_statuses:
            result.diagnostics.append({
                "kind": "UNKNOWN_RECEIVE_STATUS",
                **identity,
                "revision": latest.doc_rev,
                "status": latest.doc_status,
                "canonical_status": status or None,
                "status_meaning": status_meaning,
                "status_known": status_definition is not None,
                "transaction_mode": latest.transaction_mode,
                "responsible_unit": responsible_unit,
                "unit_basis": unit_basis,
                "value": latest.letter_reference or latest.letter_date,
            })
            continue
        if latest.send_or_receive == "receive" and status in response_statuses:
            elapsed = jalali_day_difference(status_date, latest.letter_date)
            if elapsed is None:
                result.company_delay.append(EngineeringExceptionRow(
                    **identity,
                    revision=latest.doc_rev,
                    responsibility="COMPANY",
                    current_holder=responsible_unit or "COMPANY",
                    responsible_unit=responsible_unit,
                    unit_basis=unit_basis,
                    responsibility_since=None,
                    responsibility_age_days=None,
                    state="WAITING_COMPANY_RESPONSE",
                    last_action_date=None,
                    last_action_text=latest.letter_reference or latest.letter_date,
                    status=latest.doc_status,
                    status_meaning=status_meaning,
                    elapsed_days=None,
                    allowance_days=company_allowance_days,
                    delay_days=None,
                    calculation_status="NEEDS_DATE",
                ))
                result.diagnostics.append({
                    "kind": "UNDATED_COMPANY_WAIT_START",
                    **identity,
                    "revision": latest.doc_rev,
                    "status": latest.doc_status,
                    "value": latest.letter_date,
                })
            else:
                delay = max(0, elapsed - company_allowance_days)
                if delay > 0:
                    result.company_delay.append(EngineeringExceptionRow(
                        **identity,
                        revision=latest.doc_rev,
                        responsibility="COMPANY",
                        current_holder=responsible_unit or "COMPANY",
                        responsible_unit=responsible_unit,
                        unit_basis=unit_basis,
                        responsibility_since=str(latest.letter_date),
                        responsibility_age_days=elapsed,
                        state="WAITING_COMPANY_RESPONSE",
                        last_action_date=str(latest.letter_date),
                        last_action_text=latest.letter_reference,
                        status=latest.doc_status,
                        status_meaning=status_meaning,
                        elapsed_days=elapsed,
                        allowance_days=company_allowance_days,
                        delay_days=delay,
                    ))

    return result
