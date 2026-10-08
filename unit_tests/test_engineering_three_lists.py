from functions.board_to_log.contracts import LogRecord
from functions.engineering_control import build_three_engineering_lists, jalali_day_difference


def rec(*, idx=1, side="send", rev="A", date="1405/01/01", status=None, block=0, event=1, name="DOC", sheet="230KV SS"):
    return LogRecord(
        project_id="AZD",
        source_run_id="run",
        source_workbook="AZD.xlsx",
        source_sheet=sheet,
        document_index=idx,
        doc_name=name,
        doc_wbs=f"1.{idx}",
        send_or_receive=side,
        doc_rev=rev,
        event_index=event,
        letter_date=date,
        letter_reference="REF" if side == "send" else "RESP",
        doc_status=status,
        block_index=block,
        raw_source_value=date,
        raw={"mode": "semantic_date"},
    )


def inventory(idx, name="DOC", unit="LV"):
    return {
        "source_sheet": "230KV SS",
        "document_index": idx,
        "doc_name": name,
        "doc_wbs": f"1.{idx}",
        "document_fields": {"document_type": unit},
    }


def test_jalali_day_difference_across_month_boundary():
    assert jalali_day_difference("1405/02/02", "1405/01/31") == 2


def test_not_sent_uses_cleaner_inventory_even_when_logbook_has_zero_rows():
    result = build_three_engineering_lists(
        [], status_date="1405/02/01", document_inventory=[inventory(1, "NEVER SENT")]
    )
    assert len(result.not_sent) == 1
    assert result.not_sent[0].doc_name == "NEVER SENT"
    assert result.not_sent[0].calculation_status == "NO_SEND_EVENT"


def test_latest_send_puts_responsibility_on_consultant():
    result = build_three_engineering_lists(
        [rec(date="1405/01/01")],
        status_date="1405/01/11",
        document_inventory=[inventory(1)],
        consultant_allowance_days=5,
    )
    assert len(result.consultant_delay) == 1
    row = result.consultant_delay[0]
    assert row.elapsed_days == 10
    assert row.delay_days == 5
    assert row.responsibility == "CONSULTANT"
    assert row.current_holder == "CONSULTANT"
    assert row.responsible_unit is None
    assert row.responsibility_since == "1405/01/01"
    assert row.responsibility_age_days == 10


def test_latest_comment_receive_puts_responsibility_on_company():
    records = [
        rec(side="send", rev="A", date="1405/01/01", block=0),
        rec(side="receive", rev="A", date="1405/01/05", status="CM", block=0),
    ]
    result = build_three_engineering_lists(
        records,
        status_date="1405/01/15",
        document_inventory=[inventory(1)],
        company_allowance_days=3,
    )
    assert len(result.company_delay) == 1
    row = result.company_delay[0]
    assert row.elapsed_days == 10
    assert row.delay_days == 7
    assert row.responsibility == "COMPANY"
    assert row.current_holder == "LV"
    assert row.responsible_unit == "LV"
    assert row.unit_basis == "document_type"
    assert row.responsibility_since == "1405/01/05"
    assert row.responsibility_age_days == 10


def test_approved_receive_closes_current_exception_state():
    records = [
        rec(side="send", rev="A", date="1405/01/01", block=0),
        rec(side="receive", rev="A", date="1405/01/05", status="A", block=0),
    ]
    result = build_three_engineering_lists(
        records,
        status_date="1405/02/01",
        document_inventory=[inventory(1)],
    )
    assert not result.company_delay
    assert not result.consultant_delay
    assert not result.not_sent


def test_narrative_receive_with_cm_is_company_state_but_delay_needs_date():
    records = [
        rec(side="send", rev="A", date="1405/01/01", block=0, sheet="LINE", name="ROUTE PLAN AND PROFILE"),
        LogRecord(
            project_id="AZD", source_run_id="run", source_workbook="AZD.xlsx",
            source_sheet="LINE", document_index=1, doc_name="ROUTE PLAN AND PROFILE",
            doc_wbs="1.6.1.1.1", send_or_receive="receive", doc_rev="A",
            event_index=1, letter_date="پیرو مذاکرات صورت گرفته",
            letter_reference="پیرو مذاکرات صورت گرفته", doc_status="CM",
            transaction_mode="narrative_receive", block_index=1,
            raw_source_value="پیرو مذاکرات صورت گرفته",
            raw={"mode": "narrative_receive"},
        ),
    ]
    inv = [{"source_sheet": "LINE", "document_index": 1, "doc_name": "ROUTE PLAN AND PROFILE", "doc_wbs": "1.6.1.1.1"}]
    result = build_three_engineering_lists(records, status_date="1405/02/01", document_inventory=inv)
    assert len(result.company_delay) == 1
    row = result.company_delay[0]
    assert row.calculation_status == "NEEDS_DATE"
    assert row.delay_days is None
    assert row.last_action_text == "پیرو مذاکرات صورت گرفته"


def test_later_send_moves_responsibility_back_to_consultant():
    records = [
        rec(side="send", rev="A", date="1405/01/01", block=0),
        rec(side="receive", rev="A", date="1405/01/05", status="CM", block=0),
        rec(side="send", rev="B", date="1405/01/10", block=1),
    ]
    result = build_three_engineering_lists(
        records, status_date="1405/01/20", document_inventory=[inventory(1)]
    )
    assert not result.company_delay
    assert len(result.consultant_delay) == 1
    assert result.consultant_delay[0].last_action_date == "1405/01/10"


def test_latest_receive_with_unknown_status_is_diagnostic_not_silently_dropped():
    records = [
        rec(side="send", rev="A", date="1405/01/01", block=0),
        LogRecord(
            project_id="AZD", source_run_id="run", source_workbook="AZD.xlsx",
            source_sheet="230KV SS", document_index=1, doc_name="DOC", doc_wbs="1.1",
            send_or_receive="receive", doc_rev="A", event_index=1,
            letter_date="1405/01/05", letter_reference="پیرو مذاکرات",
            doc_status=None, transaction_mode="narrative_receive_merged_status",
            block_index=0, raw_source_value="پیرو مذاکرات",
            raw={"mode": "narrative_receive_merged_status"},
        ),
    ]
    result = build_three_engineering_lists(
        records, status_date="1405/01/20", document_inventory=[inventory(1)]
    )
    assert not result.company_delay
    assert not result.consultant_delay
    assert len(result.diagnostics) == 1
    assert result.diagnostics[0]["kind"] == "UNKNOWN_RECEIVE_STATUS"
    assert result.diagnostics[0]["transaction_mode"] == "narrative_receive_merged_status"


def test_status_library_meaning_flows_into_company_delay():
    records = [
        rec(side="send", rev="A", date="1405/01/01", block=0),
        rec(side="receive", rev="A", date="1405/01/05", status="RJ", block=0),
    ]
    result = build_three_engineering_lists(
        records,
        status_date="1405/01/15",
        document_inventory=[inventory(1)],
    )
    assert len(result.company_delay) == 1
    assert result.company_delay[0].status == "RJ"
    assert result.company_delay[0].status_meaning == "Rejected"


def test_fsh_category_is_used_as_internal_responsible_unit():
    records = [
        rec(side="send", date="1405/01/01"),
        rec(side="receive", date="1405/01/05", status="CM"),
    ]
    inv = [{
        "source_sheet": "230KV SS", "document_index": 1, "doc_name": "DOC", "doc_wbs": "1.1",
        "document_fields": {"category": "CIVIL", "type": "DRAWINGS"},
    }]
    result = build_three_engineering_lists(records, status_date="1405/01/10", document_inventory=inv)
    row = result.company_delay[0]
    assert row.responsible_unit == "CIVIL"
    assert row.unit_basis == "category"
    assert row.current_holder == "CIVIL"
    assert row.responsibility_since == "1405/01/05"


def test_delay_register_combines_company_and_consultant_and_sorts_by_delay():
    records = [
        rec(idx=1, side="send", date="1405/01/01"),
        rec(idx=2, side="send", date="1405/01/01"),
        rec(idx=2, side="receive", date="1405/01/05", status="CM"),
    ]
    result = build_three_engineering_lists(
        records, status_date="1405/01/20",
        document_inventory=[inventory(1, unit="HV"), inventory(2, unit="CIVIL")],
    )
    delay = result.delay_register()
    assert len(delay) == 2
    assert delay[0].responsibility == "CONSULTANT"
    assert delay[0].delay_days == 19
    assert delay[1].responsibility == "COMPANY"
    assert delay[1].responsible_unit == "CIVIL"
    assert result.to_dict()["summary"]["company_delay_by_unit"] == {"CIVIL": 1}
