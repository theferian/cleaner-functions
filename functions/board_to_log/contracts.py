from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class LogRecord:
    """Canonical record with backward-compatible Board->Log field names."""

    project_id: str
    source_run_id: str
    source_workbook: str | None
    source_sheet: str
    document_index: int

    doc_type: Any = None
    doc_type_a: Any = None
    doc_type_b: Any = None
    doc_name: Any = None
    doc_code: Any = None
    doc_wbs: Any = None
    document_fields: dict[str, Any] = field(default_factory=dict)

    send_or_receive: str = ""
    doc_rev: str = ""
    event_index: int = 1
    letter_date: Any = None
    letter_reference: Any = None
    doc_status: Any = None
    transaction_mode: str | None = None

    source_row: int | None = None
    source_col: int | None = None
    date_source: str | None = None
    reference_source: str | None = None
    status_source: str | None = None
    block_index: int | None = None
    raw_source_value: Any = None
    raw: dict[str, Any] = field(default_factory=dict)

    # Convenience aliases for the new internal vocabulary while downstream
    # reports can keep using send_or_receive/doc_rev/doc_name/doc_wbs.
    @property
    def side(self) -> str:
        return self.send_or_receive

    @property
    def revision(self) -> str:
        return self.doc_rev

    @property
    def document_name(self) -> Any:
        return self.doc_name

    @property
    def document_wbs(self) -> Any:
        return self.doc_wbs

    @property
    def document_type(self) -> Any:
        return self.doc_type

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ExtractionIssue:
    kind: str
    sheet: str
    document_index: int | None
    message: str
    address: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BoardToLogResult:
    project_id: str
    source_run_id: str
    source_workbook: str | None
    records: list[LogRecord] = field(default_factory=list)
    issues: list[ExtractionIssue] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        issue_by_kind = Counter(x.kind for x in self.issues)
        issue_by_sheet = Counter(x.sheet for x in self.issues)
        records_by_sheet = Counter(x.source_sheet for x in self.records)
        return {
            "schema": "board_to_log.logbook/0.1",
            "project_id": self.project_id,
            "source_run_id": self.source_run_id,
            "source_workbook": self.source_workbook,
            "summary": {
                "record_count": len(self.records),
                "issue_count": len(self.issues),
                "send_count": sum(1 for x in self.records if x.send_or_receive == "send"),
                "receive_count": sum(1 for x in self.records if x.send_or_receive == "receive"),
                "records_by_sheet": dict(sorted(records_by_sheet.items())),
                "issues_by_kind": dict(sorted(issue_by_kind.items())),
                "issues_by_sheet": dict(sorted(issue_by_sheet.items())),
                "preserved_narrative_count": int(self.diagnostics.get("preserved_narrative_count", 0)),
            },
            "diagnostics": dict(self.diagnostics),
            "records": [x.to_dict() for x in self.records],
            "issues": [x.to_dict() for x in self.issues],
        }
