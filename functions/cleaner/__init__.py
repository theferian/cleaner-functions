"""Cleaner function facade.

The implementation modules remain import-compatible while the public
architecture treats Cleaner as one function inside the higher-level pipeline.
"""

from .service import CleanerRun, finalize_run, load_cleaner_run
from .executor import WorkbookChange, apply_change_plan_com, build_change_plan, create_cleaned_copy_com, default_published_path

__all__ = [
    "CleanerRun", "finalize_run", "load_cleaner_run",
    "WorkbookChange", "build_change_plan", "apply_change_plan_com",
    "create_cleaned_copy_com", "default_published_path",
    "build_general_document_profile", "inspect_general_document_workbook",
    "export_structure_quality_schema",
]

from .bootstrap import build_general_document_profile, inspect_general_document_workbook

from .structure_quality_schema import export_structure_quality_schema
