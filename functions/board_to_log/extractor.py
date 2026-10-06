from __future__ import annotations

from collections import defaultdict
import re
from typing import Any

from cleaner_core.field_schema import (
    classify_value,
    discover_jalali_tokens,
    is_valid_jalali,
    normalize_jalali,
    normalize_status,
)
from functions.cleaner.service import CleanerRun

from .contracts import BoardToLogResult, ExtractionIssue, LogRecord


_REV_RE = re.compile(r"\brev(?:ision)?\s*[-:() ]*([A-Za-z0-9.]+)", re.IGNORECASE)


_REFERENCE_CANDIDATE_RE = re.compile(r"^[A-Za-z0-9\u0600-\u06FF._/\- ]{2,80}$")
_NARRATIVE_MARKERS = ("عطف", "صورتجلسه", "صورت جلسه", "مورخ", "مطابق", "مذاکرات", "توضیح", "جلسه")


def _looks_like_reference_candidate(value: Any, *, status_values: set[str]) -> bool:
    """Return True for compact transaction-reference content.

    Cleaner intentionally classifies some compact numeric/hyphen letter IDs as
    TEXT because they do not match the learned alphanumeric reference regex.
    Board-to-Log may still pair those values when geometry places them directly
    below a date in the same Send/Receive column.  Long narrative prose remains
    narrative and is never promoted merely because it contains digits.
    """
    if value is None:
        return False
    text = str(value).strip()
    if not text:
        return False
    if normalize_status(value) in status_values:
        return False
    normalized = normalize_jalali(value)
    if normalized and is_valid_jalali(normalized):
        return False
    kind = classify_value(value)
    if kind in {"REFERENCE", "CODE"}:
        return True
    if kind not in {"TEXT", "NUMBER"}:
        return False
    if any(marker in text for marker in _NARRATIVE_MARKERS):
        return False
    if len(text.split()) > 3:
        return False
    if not _REFERENCE_CANDIDATE_RE.fullmatch(text):
        return False
    # A bare word is much more likely to be explanation/header residue than a
    # correspondence reference. Numeric-only and punctuated compact IDs are OK.
    return any(ch.isdigit() for ch in text)


def _reference_candidates(items: list[dict[str, Any]], status_values: set[str]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for item in items:
        if item.get("role") in {"send_date", "receive_date", "date", "status"}:
            continue
        if item.get("role") == "reference" or _looks_like_reference_candidate(
            item.get("value"), status_values=status_values
        ):
            candidates.append(item)
    return candidates


def _row_span(item: dict[str, Any]) -> tuple[int, int]:
    slot = item["slot"]
    start = int(slot.get("row_offset_start", 0))
    end = int(slot.get("row_offset_end", start))
    return start, end


def _rows_overlap(a: dict[str, Any], b: dict[str, Any]) -> bool:
    a0, a1 = _row_span(a)
    b0, b1 = _row_span(b)
    return not (a1 < b0 or b1 < a0)


def _choose_nearby_status(
    event: dict[str, Any],
    statuses: list[dict[str, Any]],
    *,
    require_next_column: bool = False,
) -> dict[str, Any] | None:
    if not statuses:
        return None
    event_col = int(event["slot"].get("col_start", 0))
    candidates = []
    for status in statuses:
        status_col = int(status["slot"].get("col_start", 0))
        if require_next_column and status_col != event_col + 1:
            continue
        if require_next_column and status.get("side_hint") != "receive":
            continue
        candidates.append(status)
    if not candidates:
        return None
    e0, e1 = _row_span(event)
    overlapping = [x for x in candidates if _rows_overlap(event, x)]
    pool = overlapping or candidates
    return min(
        pool,
        key=lambda x: min(
            abs(_row_span(x)[0] - e0),
            abs(_row_span(x)[1] - e1),
        ),
    )


def _narrative_date(value: Any) -> tuple[str | None, bool]:
    """Return (first valid Jalali date, has_invalid_date_like_token)."""
    audits = discover_jalali_tokens(value, allow_short=True)
    valid = [str(x["normalized"]) for x in audits if x.get("valid") and x.get("normalized")]
    invalid = any(not x.get("valid") for x in audits)
    return (valid[0] if valid else None), invalid


def _slot_lane(card: dict[str, Any], slot: dict[str, Any]) -> str:
    last = max(0, int(card["end_row"]) - int(card["start_row"]))
    start = int(slot.get("row_offset_start", 0))
    end = int(slot.get("row_offset_end", start))
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


def _effective_value(state: dict[str, Any], sheet: str, address: str, fallback: Any) -> Any:
    key = f"{sheet}!{address}".upper()
    override = (state.get("value_overrides") or {}).get(key)
    return fallback if override is None else override.get("value")


def _column_headers(schema: dict[str, Any]) -> dict[int, list[str]]:
    return {
        int(item.get("column")): [str(x) for x in (item.get("headers") or []) if str(x).strip()]
        for item in schema.get("columns", [])
    }


def _revision_for_block(schema: dict[str, Any], block_index: int) -> str:
    width = int(schema.get("block_width") or 0)
    start = int(schema.get("data_start_col") or 0) + block_index * width
    headers_by_col = _column_headers(schema)
    candidates: list[str] = []
    for col in range(start, start + max(width, 1)):
        candidates.extend(headers_by_col.get(col, []))
    for text in candidates:
        match = _REV_RE.search(text)
        if match:
            return match.group(1).upper()
    return f"BLOCK_{block_index + 1:02d}"


def _roles_at_offset(schema: dict[str, Any], offset: int) -> set[str]:
    roles = set()
    direct = (schema.get("roles_by_offset") or {}).get(str(offset))
    if direct:
        roles.add(str(direct))
    prefix = f"{offset}:"
    for key, role in (schema.get("roles_by_slot") or {}).items():
        if str(key).startswith(prefix) and role:
            roles.add(str(role))
    return roles


def _role_for_slot(schema: dict[str, Any], card: dict[str, Any], slot: dict[str, Any], value: Any) -> str | None:
    if value is None or str(value).strip() == "":
        return None

    status_values = {normalize_status(x) for x in (schema.get("status_values") or [])}
    if status_values and normalize_status(value) in status_values:
        return "status"

    width = int(schema.get("block_width") or 0)
    if width <= 0:
        return None
    start = int(schema.get("data_start_col") or 0)
    offset = (int(slot.get("col_start")) - start) % width
    offset_roles = _roles_at_offset(schema, offset)
    kind = classify_value(value)

    if kind == "DATE":
        direct = (schema.get("roles_by_offset") or {}).get(str(offset))
        if direct in {"send_date", "receive_date"} or (direct and str(direct).startswith("date_")):
            return str(direct)
        date_roles = sorted(
            role for role in offset_roles
            if role in {"send_date", "receive_date"} or role.startswith("date_")
        )
        return date_roles[0] if date_roles else "date"

    if kind == "REFERENCE":
        return "reference"

    if kind == "CODE":
        if "status" in offset_roles and not ({"send_date", "receive_date", "reference"} & offset_roles):
            return "status"
        return "reference"

    if kind == "TEXT" and offset_roles:
        return "explanation"

    lane = _slot_lane(card, slot)
    fallback = (schema.get("roles_by_slot") or {}).get(f"{offset}:{lane}")
    return str(fallback) if fallback else None


def _side_for_column(schema: dict[str, Any], col: int) -> str | None:
    width = int(schema.get("block_width") or 0)
    start = int(schema.get("data_start_col") or 0)
    if width <= 0:
        return None
    offset = (col - start) % width
    roles = _roles_at_offset(schema, offset)
    if "send_date" in roles:
        return "send"
    if "receive_date" in roles:
        return "receive"
    direct = (schema.get("roles_by_offset") or {}).get(str(offset))
    if direct == "send_date":
        return "send"
    if direct == "receive_date":
        return "receive"
    return None


def _slot_spans_role(schema: dict[str, Any], slot: dict[str, Any], role: str) -> bool:
    """Return True when a physical slot spans a semantic column for ``role``.

    This matters for merged receive narratives that physically cover both the
    Receive and Status columns.  Their top-left column identifies them as
    receive-side narrative, while ``col_end`` proves that the same merged cell
    also occupies the Status lane.
    """
    width = int(schema.get("block_width") or 0)
    start = int(schema.get("data_start_col") or 0)
    if width <= 0:
        return False
    c0 = int(slot.get("col_start", 0))
    c1 = int(slot.get("col_end", c0))
    for col in range(c0, c1 + 1):
        offset = (col - start) % width
        if role in _roles_at_offset(schema, offset):
            return True
        direct = (schema.get("roles_by_offset") or {}).get(str(offset))
        if direct == role:
            return True
    return False


def _field_value(region: dict[str, Any], state: dict[str, Any], key: str) -> Any:
    field = (region.get("fields") or {}).get(key) or {}
    address = str(field.get("address") or "")
    value = field.get("value")
    if address:
        value = _effective_value(state, str(region.get("sheet")), address, value)
    return value


def _document_identity(region: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for key in (region.get("fields") or {}):
        values[str(key)] = _field_value(region, state, str(key))
    return values


def _choose_reference(date_slot: dict[str, Any], refs: list[dict[str, Any]], next_date_start: int | None) -> dict[str, Any] | None:
    candidates = []
    date_col = int(date_slot["slot"].get("col_start"))
    date_end = int(date_slot["slot"].get("row_offset_end", date_slot["slot"].get("row_offset_start", 0)))
    for ref in refs:
        slot = ref["slot"]
        if int(slot.get("col_start")) != date_col:
            continue
        start = int(slot.get("row_offset_start", 0))
        if start < date_end:
            continue
        if next_date_start is not None and start >= next_date_start:
            continue
        candidates.append(ref)
    if not candidates:
        return None
    return min(candidates, key=lambda x: int(x["slot"].get("row_offset_start", 0)))


def _pair_statuses(receives: list[dict[str, Any]], statuses: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    if not receives or not statuses:
        return {}
    receives_sorted = sorted(receives, key=lambda x: int(x["slot"].get("row_offset_start", 0)))
    statuses_sorted = sorted(statuses, key=lambda x: int(x["slot"].get("row_offset_start", 0)))
    result: dict[int, dict[str, Any]] = {}
    unused = list(statuses_sorted)
    for idx, event in enumerate(receives_sorted):
        if not unused:
            break
        row = int(event["slot"].get("row_offset_start", 0))
        chosen = min(
            unused,
            key=lambda x: abs(int(x["slot"].get("row_offset_start", 0)) - row),
        )
        result[id(event)] = chosen
        unused.remove(chosen)
    return result


def extract_board_to_log(run: CleanerRun, *, project_id: str | None = None) -> BoardToLogResult:
    project_id = str(project_id or run.profile_name).upper()
    state = run.state()
    regions_payload = run.document_regions()
    cards_payload = run.card_maps()
    schemas_payload = run.slot_schema()
    workbook_name = (run.workbook or {}).get("name")

    result = BoardToLogResult(
        project_id=project_id,
        source_run_id=run.run_id,
        source_workbook=workbook_name,
        diagnostics={
            "preserved_narrative_count": 0,
            "unclassified_content_count": 0,
        },
    )

    for sheet, card_scan in (cards_payload.get("sheets") or {}).items():
        schema = (schemas_payload.get("sheets") or {}).get(sheet)
        region_scan = (regions_payload.get("sheets") or {}).get(sheet)
        if not schema or not region_scan:
            result.issues.append(ExtractionIssue(
                kind="MISSING_CLEANER_ARTIFACT",
                sheet=sheet,
                document_index=None,
                message=f"Missing slot schema or document-region data for {sheet}.",
            ))
            continue

        width = int(schema.get("block_width") or 0)
        if width <= 0:
            result.issues.append(ExtractionIssue(
                kind="NO_BLOCK_WIDTH",
                sheet=sheet,
                document_index=None,
                message=f"{sheet}: Cleaner did not resolve a transaction block width.",
            ))
            continue

        regions = {int(x["record_index"]): x for x in region_scan.get("regions", [])}
        data_start = int(schema.get("data_start_col") or card_scan.get("data_start_col") or 0)

        for card in card_scan.get("cards", []):
            doc_index = int(card.get("record_index"))
            region = regions.get(doc_index)
            if not region:
                result.issues.append(ExtractionIssue(
                    kind="MISSING_DOCUMENT_REGION",
                    sheet=sheet,
                    document_index=doc_index,
                    message=f"{sheet}: card {doc_index} has no matching DocumentRegion.",
                ))
                continue
            identity = _document_identity(region, state)

            classified: list[dict[str, Any]] = []
            for raw_slot in card.get("slots", []):
                slot = dict(raw_slot)
                address = str(slot.get("address"))
                value = _effective_value(state, sheet, address, slot.get("value"))
                role = _role_for_slot(schema, card, slot, value)
                col = int(slot.get("col_start"))
                block_index = max(0, (col - data_start) // width)
                classified.append({
                    "slot": slot,
                    "address": address,
                    "value": value,
                    "role": role,
                    "block_index": block_index,
                    "side_hint": _side_for_column(schema, col),
                })

            by_block: dict[int, list[dict[str, Any]]] = defaultdict(list)
            for item in classified:
                by_block[item["block_index"]].append(item)

            for block_index, items in sorted(by_block.items()):
                revision = _revision_for_block(schema, block_index)
                statuses = [x for x in items if x["role"] == "status"]
                status_values = {normalize_status(x) for x in (schema.get("status_values") or [])}
                refs = _reference_candidates(items, status_values)
                pure_receives = [x for x in items if x["role"] == "receive_date"]
                status_map = _pair_statuses(pure_receives, statuses)
                used_refs: set[int] = set()
                used_statuses: set[int] = {id(x) for x in status_map.values()}
                used_narratives: set[int] = set()

                send_events_all = sorted(
                    [x for x in items if x["role"] == "send_date"],
                    key=lambda x: (
                        int(x["slot"].get("row_offset_start", 0)),
                        int(x["slot"].get("col_start", 0)),
                    ),
                )

                # Some real boards compress an exceptional receive transaction into
                # two physical columns: DATE/REFERENCE in one column and STATUS in
                # the immediately adjacent column.  Cleaner already tells us that
                # adjacent column is semantically the receive lane because the
                # status token overrides the unusual geometry.  In that case the
                # date/reference pair is a RECEIVE event, not a SEND event.
                compressed_receive_status: dict[int, dict[str, Any]] = {}
                available_statuses = [x for x in statuses if id(x) not in used_statuses]
                for event in send_events_all:
                    status = _choose_nearby_status(
                        event,
                        available_statuses,
                        require_next_column=True,
                    )
                    if status is None:
                        continue
                    compressed_receive_status[id(event)] = status
                    used_statuses.add(id(status))
                    available_statuses.remove(status)

                def add_record(
                    *,
                    side: str,
                    event: dict[str, Any],
                    event_index: int,
                    ref: dict[str, Any] | None,
                    status: dict[str, Any] | None,
                    letter_date: Any,
                    letter_reference: Any,
                    mode: str,
                ) -> None:
                    result.records.append(LogRecord(
                        project_id=project_id,
                        source_run_id=run.run_id,
                        source_workbook=workbook_name,
                        source_sheet=sheet,
                        document_index=doc_index,
                        doc_type=identity.get("document_type") or identity.get("doc_type"),
                        doc_type_a=identity.get("document_type_a") or identity.get("doc_type_a"),
                        doc_type_b=identity.get("document_type_b") or identity.get("doc_type_b"),
                        doc_name=identity.get("name") or identity.get("document_name") or identity.get("doc_name"),
                        doc_code=identity.get("code") or identity.get("document_code") or identity.get("doc_code"),
                        doc_wbs=identity.get("wbs") or identity.get("document_wbs") or identity.get("doc_wbs"),
                        document_fields=dict(identity),
                        send_or_receive=side,
                        doc_rev=revision,
                        event_index=event_index,
                        letter_date=letter_date,
                        letter_reference=letter_reference,
                        doc_status=status["value"] if status else None,
                        transaction_mode=mode,
                        date_source=event["address"],
                        reference_source=(ref["address"] if ref else (event["address"] if mode.startswith("narrative_receive") else None)),
                        status_source=status["address"] if status else None,
                        source_row=int(card.get("start_row")) + int(event["slot"].get("row_offset_start", 0)),
                        source_col=int(event["slot"].get("col_start", 0)),
                        block_index=block_index,
                        raw_source_value=event["value"],
                        raw={
                            "date": event["value"],
                            "reference": letter_reference,
                            "status": status["value"] if status else None,
                            "mode": mode,
                        },
                    ))

                # --------------------------------------------------------------
                # SEND events (except compressed irregular receive lanes)
                # --------------------------------------------------------------
                send_events = [
                    x for x in send_events_all
                    if id(x) not in compressed_receive_status
                ]
                send_refs = [x for x in refs if x.get("side_hint") in {None, "send"}]
                for event_index, event in enumerate(send_events, start=1):
                    idx = send_events_all.index(event)
                    next_start = None
                    if idx + 1 < len(send_events_all):
                        next_start = int(send_events_all[idx + 1]["slot"].get("row_offset_start", 0))
                    ref = _choose_reference(event, send_refs, next_start)
                    if ref is not None:
                        used_refs.add(id(ref))
                    normalized_date = normalize_jalali(event["value"])
                    letter_date = (
                        normalized_date
                        if normalized_date and is_valid_jalali(normalized_date)
                        else event["value"]
                    )
                    add_record(
                        side="send",
                        event=event,
                        event_index=event_index,
                        ref=ref,
                        status=None,
                        letter_date=letter_date,
                        letter_reference=ref["value"] if ref else None,
                        mode="semantic_date",
                    )
                    if ref is None:
                        result.issues.append(ExtractionIssue(
                            kind="MISSING_REFERENCE",
                            sheet=sheet,
                            document_index=doc_index,
                            address=event["address"],
                            message=(
                                f"{sheet} document {doc_index} {revision}: "
                                "send date has no mapped letter reference."
                            ),
                            evidence={"side": "send", "revision": revision, "date": event["value"]},
                        ))

                # --------------------------------------------------------------
                # RECEIVE events: explicit receive dates first.
                # --------------------------------------------------------------
                receive_entries: list[dict[str, Any]] = []
                receive_refs = [x for x in refs if x.get("side_hint") in {None, "receive"}]
                pure_receives_sorted = sorted(
                    pure_receives,
                    key=lambda x: (
                        int(x["slot"].get("row_offset_start", 0)),
                        int(x["slot"].get("col_start", 0)),
                    ),
                )
                for pos, event in enumerate(pure_receives_sorted):
                    next_start = None
                    if pos + 1 < len(pure_receives_sorted):
                        next_start = int(pure_receives_sorted[pos + 1]["slot"].get("row_offset_start", 0))
                    ref = _choose_reference(event, receive_refs, next_start)
                    if ref is not None:
                        used_refs.add(id(ref))
                    normalized_date = normalize_jalali(event["value"])
                    letter_date = (
                        normalized_date
                        if normalized_date and is_valid_jalali(normalized_date)
                        else event["value"]
                    )
                    receive_entries.append({
                        "event": event,
                        "ref": ref,
                        "status": status_map.get(id(event)),
                        "letter_date": letter_date,
                        "letter_reference": ref["value"] if ref else None,
                        "mode": "semantic_date",
                    })

                # --------------------------------------------------------------
                # Compressed/irregular receive lane recovered from status
                # adjacency.  Reference stays in the same physical column.
                # --------------------------------------------------------------
                for pos, event in enumerate(send_events_all):
                    status = compressed_receive_status.get(id(event))
                    if status is None:
                        continue
                    next_start = None
                    if pos + 1 < len(send_events_all):
                        next_start = int(send_events_all[pos + 1]["slot"].get("row_offset_start", 0))
                    ref = _choose_reference(event, refs, next_start)
                    if ref is not None:
                        used_refs.add(id(ref))
                    normalized_date = normalize_jalali(event["value"])
                    letter_date = (
                        normalized_date
                        if normalized_date and is_valid_jalali(normalized_date)
                        else event["value"]
                    )
                    receive_entries.append({
                        "event": event,
                        "ref": ref,
                        "status": status,
                        "letter_date": letter_date,
                        "letter_reference": ref["value"] if ref else None,
                        "mode": "compressed_receive_lane",
                    })

                # --------------------------------------------------------------
                # Legacy lossless semantics for narrative RECEIVE cells.
                # A narrative with a valid embedded date is a response event.
                # A non-date narrative can also be a response when a status is
                # physically attached to it.  Invalid date-like text is NOT
                # promoted: Cleaner must repair it first.
                # --------------------------------------------------------------
                ref_ids = {id(x) for x in refs}
                narrative_candidates = sorted(
                    [
                        x for x in items
                        if x["role"] == "explanation"
                        and x.get("side_hint") == "receive"
                        and id(x) not in ref_ids
                    ],
                    key=lambda x: int(x["slot"].get("row_offset_start", 0)),
                )
                available_statuses = [x for x in statuses if id(x) not in used_statuses]
                for narrative in narrative_candidates:
                    spans_status_lane = _slot_spans_role(schema, narrative["slot"], "status")
                    status = _choose_nearby_status(narrative, available_statuses)
                    if status is None and not spans_status_lane:
                        continue
                    if status is not None:
                        n0, n1 = _row_span(narrative)
                        s0, s1 = _row_span(status)
                        row_distance = 0 if _rows_overlap(narrative, status) else min(abs(s0 - n1), abs(n0 - s1))
                        if row_distance > 1:
                            continue
                    embedded_date, has_invalid_date_like = _narrative_date(narrative["value"])
                    if has_invalid_date_like and embedded_date is None:
                        continue
                    if status is not None:
                        used_statuses.add(id(status))
                        available_statuses.remove(status)
                    used_narratives.add(id(narrative))
                    mode = (
                        "narrative_receive_merged_status"
                        if spans_status_lane and status is None
                        else "narrative_receive"
                    )
                    if mode == "narrative_receive_merged_status":
                        result.diagnostics["merged_receive_status_narrative_count"] = (
                            int(result.diagnostics.get("merged_receive_status_narrative_count", 0)) + 1
                        )
                    receive_entries.append({
                        "event": narrative,
                        "ref": None,
                        "status": status,
                        "letter_date": embedded_date if embedded_date is not None else narrative["value"],
                        "letter_reference": narrative["value"],
                        "mode": mode,
                    })

                receive_entries.sort(key=lambda x: (
                    int(x["event"]["slot"].get("row_offset_start", 0)),
                    int(x["event"]["slot"].get("col_start", 0)),
                ))
                for event_index, entry in enumerate(receive_entries, start=1):
                    event = entry["event"]
                    ref = entry["ref"]
                    status = entry["status"]
                    add_record(
                        side="receive",
                        event=event,
                        event_index=event_index,
                        ref=ref,
                        status=status,
                        letter_date=entry["letter_date"],
                        letter_reference=entry["letter_reference"],
                        mode=entry["mode"],
                    )
                    if entry["letter_reference"] is None:
                        result.issues.append(ExtractionIssue(
                            kind="MISSING_REFERENCE",
                            sheet=sheet,
                            document_index=doc_index,
                            address=event["address"],
                            message=(
                                f"{sheet} document {doc_index} {revision}: "
                                "receive date has no mapped letter reference."
                            ),
                            evidence={"side": "receive", "revision": revision, "date": event["value"]},
                        ))
                    if status is None and entry["mode"] != "narrative_receive_merged_status":
                        result.issues.append(ExtractionIssue(
                            kind="MISSING_RECEIVE_STATUS",
                            sheet=sheet,
                            document_index=doc_index,
                            address=event["address"],
                            message=(
                                f"{sheet} document {doc_index} {revision}: "
                                "receive date has no mapped response status."
                            ),
                            evidence={"revision": revision, "date": event["value"]},
                        ))

                # Narrative/explanation cells are intentionally preserved by
                # Cleaner. Those consumed as narrative receive events are no
                # longer counted as free-standing narrative diagnostics.
                narratives = [
                    x for x in items
                    if x["role"] == "explanation"
                    and id(x) not in used_refs
                    and id(x) not in used_narratives
                ]
                result.diagnostics["preserved_narrative_count"] += len(narratives)

                # A generic DATE means the Cleaner recognized a date value but could
                # not decide whether it is a Send or Receive date. That is a real
                # Board-to-Log ambiguity and deserves review.
                for item in [x for x in items if x["role"] == "date"]:
                    result.issues.append(ExtractionIssue(
                        kind="AMBIGUOUS_DATE_ROLE",
                        sheet=sheet,
                        document_index=doc_index,
                        address=item["address"],
                        message=(
                            f"{sheet} document {doc_index} {revision}: date-like content "
                            "could not be assigned to Send or Receive."
                        ),
                        evidence={"value": item["value"], "revision": revision},
                    ))

                for ref in refs:
                    if id(ref) in used_refs:
                        continue
                    result.issues.append(ExtractionIssue(
                        kind="ORPHAN_REFERENCE",
                        sheet=sheet,
                        document_index=doc_index,
                        address=ref["address"],
                        message=(
                            f"{sheet} document {doc_index} {revision}: letter reference "
                            "was not paired with a Send/Receive date."
                        ),
                        evidence={
                            "value": ref["value"],
                            "revision": revision,
                            "side_hint": ref.get("side_hint"),
                        },
                    ))

                for status in statuses:
                    if id(status) in used_statuses:
                        continue
                    result.issues.append(ExtractionIssue(
                        kind="ORPHAN_STATUS",
                        sheet=sheet,
                        document_index=doc_index,
                        address=status["address"],
                        message=(
                            f"{sheet} document {doc_index} {revision}: status was not "
                            "paired with a Receive event."
                        ),
                        evidence={"value": status["value"], "revision": revision},
                    ))

                result.diagnostics["unclassified_content_count"] += sum(
                    1
                    for x in items
                    if x["role"] is None and x["value"] is not None and str(x["value"]).strip()
                )

    result.records.sort(key=lambda x: (
        x.source_sheet,
        x.document_index,
        x.block_index if x.block_index is not None else 999,
        x.event_index,
        0 if x.side == "send" else 1,
    ))
    return result


def build_issue_contexts(run: CleanerRun, result: BoardToLogResult) -> list[dict[str, Any]]:
    """Build review context for Board-to-Log issues from Cleaner artifacts.

    Context is artifact-driven: document identity, the affected revision block,
    classified non-empty slots, and any canonical records already extracted for
    the same document/revision. It never re-opens Excel or re-discovers geometry.
    """
    state = run.state()
    regions_payload = run.document_regions()
    cards_payload = run.card_maps()
    schemas_payload = run.slot_schema()
    contexts: list[dict[str, Any]] = []

    for issue_no, issue in enumerate(result.issues, start=1):
        sheet = issue.sheet
        doc_index = issue.document_index
        schema = (schemas_payload.get("sheets") or {}).get(sheet) or {}
        card_scan = (cards_payload.get("sheets") or {}).get(sheet) or {}
        region_scan = (regions_payload.get("sheets") or {}).get(sheet) or {}
        card = next((x for x in card_scan.get("cards", []) if int(x.get("record_index", -1)) == int(doc_index or -1)), None)
        region = next((x for x in region_scan.get("regions", []) if int(x.get("record_index", -1)) == int(doc_index or -1)), None)
        identity = _document_identity(region, state) if region else {}
        revision = (issue.evidence or {}).get("revision")
        width = int(schema.get("block_width") or 0)
        data_start = int(schema.get("data_start_col") or card_scan.get("data_start_col") or 0)

        block_indexes: set[int] = set()
        if width > 0 and revision is not None:
            max_col = int(schema.get("data_end_col") or card_scan.get("data_end_col") or data_start)
            for block_index in range(max(1, ((max_col - data_start) // width) + 1)):
                if _revision_for_block(schema, block_index) == str(revision):
                    block_indexes.add(block_index)
        if card and issue.address and width > 0 and not block_indexes:
            target_slot = next((x for x in card.get("slots", []) if str(x.get("address")) == str(issue.address)), None)
            if target_slot:
                block_indexes.add(max(0, (int(target_slot.get("col_start")) - data_start) // width))

        slots: list[dict[str, Any]] = []
        if card:
            for raw_slot in card.get("slots", []):
                address = str(raw_slot.get("address"))
                value = _effective_value(state, sheet, address, raw_slot.get("value"))
                if value is None or str(value).strip() == "":
                    continue
                col = int(raw_slot.get("col_start"))
                block_index = max(0, (col - data_start) // width) if width > 0 else 0
                if block_indexes and block_index not in block_indexes:
                    continue
                role = _role_for_slot(schema, card, raw_slot, value) if schema else None
                slots.append({
                    "address": address,
                    "value": value,
                    "role": role,
                    "side_hint": _side_for_column(schema, col) if schema else None,
                    "block_index": block_index,
                    "row_offset_start": raw_slot.get("row_offset_start"),
                    "row_offset_end": raw_slot.get("row_offset_end"),
                })

        records = [
            record.to_dict()
            for record in result.records
            if record.source_sheet == sheet
            and record.document_index == doc_index
            and (revision is None or record.doc_rev == str(revision))
        ]
        contexts.append({
            "issue_no": issue_no,
            "issue": issue.to_dict(),
            "document_identity": identity,
            "revision": revision,
            "block_indexes": sorted(block_indexes),
            "slots": slots,
            "records": records,
        })
    return contexts
