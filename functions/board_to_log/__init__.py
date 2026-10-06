"""Board->Log function.

Consumes Cleaner semantic artifacts; it does not rediscover workbook geometry.
"""

from .contracts import BoardToLogResult, ExtractionIssue, LogRecord
from .extractor import build_issue_contexts, extract_board_to_log
from .writers import (
    canonical_record_digest, validate_logbook_workbook_com, write_csv,
    write_excel_com, write_issues_csv, write_json, write_logbook_to_workbook_com,
)

__all__ = [
    "BoardToLogResult",
    "ExtractionIssue",
    "LogRecord",
    "extract_board_to_log",
    "build_issue_contexts",
    "write_csv",
    "write_excel_com",
    "write_json",
    "write_issues_csv",
    "write_logbook_to_workbook_com",
    "validate_logbook_workbook_com",
    "canonical_record_digest",
    "build_coverage_audit",
    "apply_coverage_highlights_com",
]

from .coverage import build_coverage_audit, apply_coverage_highlights_com
