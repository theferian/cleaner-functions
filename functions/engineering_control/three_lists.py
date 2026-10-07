from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Any, Iterable

from cleaner_core.status_library import load_status_library, normalize_status_token

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

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "engineering.three_lists/0.1",
            "status_date": self.status_date,
            "summary": {
                "not_sent": len(self.not_sent),
                "company_delay": len(self.company_delay),
                "consultant_delay": len(self.consultant_delay),
                "diagnostic_count": len(self.diagnostics),
            },
            "lists": {
                "01_Not_Sent": [x.to_dict() for x in self.not_sent],
                "02_Company_Delay": [x.to_dict() for x in self.company_delay],
                "03_Consultant_Delay": [x.to_dict() for x in self.consultant_delay],
            },
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
        response_statuses = {"CM", "RJ"} | status_library.statuses_for_responsibility("COMPANY")
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
        ordered = sorted(doc_records, key=_sequence_key)
        sends = [x for x in ordered if x.send_or_receive == "send"]
        inventory_item = inventory_map.get(key) or {}
        if ordered:
            identity = _identity(ordered[0])
        else:
            identity = {
                "source_sheet": key[0],
                "document_index": key[1],
                "doc_name": inventory_item.get("doc_name"),
                "doc_wbs": inventory_item.get("doc_wbs"),
            }

        if not sends:
            latest = ordered[-1] if ordered else None
            result.not_sent.append(EngineeringExceptionRow(
                **identity,
                revision=(latest.doc_rev if latest else None),
                responsibility="COMPANY",
                state="NOT_SENT",
                last_action_date=(str(latest.letter_date) if latest and _jalali_parts(latest.letter_date) else None),
                last_action_text=(latest.raw_source_value if latest else None),
                status=(latest.doc_status if latest else None),
                calculation_status="NO_SEND_EVENT",
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
