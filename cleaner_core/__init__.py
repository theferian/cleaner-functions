from .contracts import Finding, DiscoveryCandidate, RunReport
from .live_excel import attach_excel_workbook, snapshot_live_workbook
from .snapshot import WorkbookSnapshot, load_snapshot
from .profile import load_profile

__all__ = [
    "Finding",
    "DiscoveryCandidate",
    "RunReport",
    "attach_excel_workbook",
    "snapshot_live_workbook",
    "WorkbookSnapshot",
    "load_snapshot",
    "load_profile",
    "FieldAnchor",
    "DocumentRegion",
    "BoundaryScan",
    "boundary_config",
    "scan_document_regions",
    "scan_all_document_regions",
    "StructurePattern",
    "RegionStructure",
    "StructureScan",
    "document_structure_config",
    "structure_pattern_for_region",
    "scan_document_structure",
    "scan_all_document_structures",
    "scan_all_card_maps",
    "scan_card_map",
    "card_map_config",
    "CardMapScan",
    "CardMap",
    "CardSlot",
    "ColumnProfile",
    "ReferenceRule",
    "SlotSchema",
    "SlotSchemaScan",
    "field_inference_config",
    "normalize_jalali",
    "is_valid_jalali",
    "normalize_reference",
    "normalize_status",
    "discover_jalali_tokens",
    "has_date_context_marker",
    "normalize_discovered_jalali_text",
    "infer_reference_regex",
    "infer_slot_schema",
    "infer_all_slot_schemas",
    "iter_role_slots",
]


from .state import (
    STATE_SCHEMA,
    new_resolved_state,
    load_resolved_state,
    save_resolved_state,
    mark_stage_run,
    ingest_review_decisions,
    ingest_review_decisions_file,
)
from .overlay import (
    ResolvedWorkbookView,
    apply_state_to_profile,
    build_resolved_context,
)

from .knowledge import (
    promote_decisions_to_profile,
    save_profile,
    match_known_fix,
    decision_from_known_policy,
)
from .document_regions import (
    FieldAnchor,
    DocumentRegion,
    BoundaryScan,
    boundary_config,
    scan_document_regions,
    scan_all_document_regions,
)

from .document_structure import (
    StructurePattern,
    RegionStructure,
    StructureScan,
    document_structure_config,
    structure_pattern_for_region,
    scan_document_structure,
    scan_all_document_structures,
)

from .card_map import (
    CardSlot,
    CardMap,
    CardMapScan,
    card_map_config,
    scan_card_map,
    scan_all_card_maps,
)


from .field_schema import (
    ColumnProfile,
    ReferenceRule,
    SlotSchema,
    SlotSchemaScan,
    field_inference_config,
    normalize_jalali,
    is_valid_jalali,
    normalize_reference,
    normalize_status,
    discover_jalali_tokens,
    has_date_context_marker,
    normalize_discovered_jalali_text,
    infer_reference_regex,
    infer_slot_schema,
    infer_all_slot_schemas,
    iter_role_slots,
)

from .exceptions import (
    REGISTRY_SCHEMA,
    new_exception_registry,
    load_exception_registry,
    save_exception_registry,
    sync_registry_from_decisions_payload,
    sync_registry_from_decisions_file,
    reconcile_stage_findings,
    retire_profile_covered_cases,
    case_for_review_item,
    case_for_finding,
)

from .context import (
    document_identity,
    document_relative_target,
    build_document_context_index,
    attach_document_context,
)
from .solutions import (
    load_project_solutions,
    save_project_solutions,
    sync_project_solutions_from_decisions_payload,
    sync_project_solutions_from_decisions_file,
    match_project_solution,
    decision_from_project_solution,
    repair_project_solutions_registry,
    make_manual_project_solution,
)
