from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from cleaner_core.exceptions import (
    load_exception_registry,
    save_exception_registry,
    sync_registry_from_decisions_file,
)
from cleaner_core.profile import load_profile
from cleaner_core.solutions import (
    load_project_solutions,
    save_project_solutions,
    sync_project_solutions_from_decisions_file,
)
from cleaner_core.state import (
    ingest_review_decisions_file,
    load_resolved_state,
    save_resolved_state,
)


CLEANER_STAGE_ORDER = (
    "M_LINE",
    "DOCUMENT_BOUNDARIES",
    "CARD_MAP",
    "SLOT_SCHEMA",
    "FIELD_VALIDATION",
    "IDENTIFIERS",
)


@dataclass(frozen=True)
class CleanerRun:
    run_dir: Path
    run_id: str
    profile_name: str
    workbook: dict[str, Any]
    state_path: Path
    manifest_path: Path
    document_regions_path: Path
    card_maps_path: Path
    slot_schema_path: Path
    profile_path: Path | None = None
    exception_registry_path: Path | None = None
    project_solutions_path: Path | None = None

    @property
    def ready_for_board_to_log(self) -> bool:
        return all(
            path.exists()
            for path in (
                self.state_path,
                self.document_regions_path,
                self.card_maps_path,
                self.slot_schema_path,
            )
        )

    def load_json(self, path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    def state(self) -> dict[str, Any]:
        return self.load_json(self.state_path)

    def document_regions(self) -> dict[str, Any]:
        return self.load_json(self.document_regions_path)

    def card_maps(self) -> dict[str, Any]:
        return self.load_json(self.card_maps_path)

    def slot_schema(self) -> dict[str, Any]:
        return self.load_json(self.slot_schema_path)


def _resolve_manifest_path(root: Path, value: str | None) -> Path | None:
    if not value:
        return None
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate
    return (root / candidate).resolve()


def load_cleaner_run(run_dir: str | Path, *, require_board_artifacts: bool = True) -> CleanerRun:
    run_dir = Path(run_dir).resolve()
    manifest_path = run_dir / "run_manifest.json"
    state_path = run_dir / "resolved_state.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Cleaner run manifest not found: {manifest_path}")
    if not state_path.exists():
        raise FileNotFoundError(f"Cleaner resolved state not found: {state_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    state = json.loads(state_path.read_text(encoding="utf-8"))
    root = run_dir.parents[1] if run_dir.parent.name == "runs" else run_dir.parent

    run = CleanerRun(
        run_dir=run_dir,
        run_id=str(state.get("run_id") or manifest.get("run_id") or run_dir.name),
        profile_name=str(state.get("profile_name") or manifest.get("profile_name") or ""),
        workbook=dict(state.get("workbook") or manifest.get("workbook") or {}),
        state_path=state_path,
        manifest_path=manifest_path,
        document_regions_path=run_dir / "document_regions.json",
        card_maps_path=run_dir / "card_maps.json",
        slot_schema_path=run_dir / "slot_schema.json",
        profile_path=_resolve_manifest_path(root, manifest.get("profile_path")),
        exception_registry_path=_resolve_manifest_path(root, manifest.get("exception_registry") or manifest.get("exception_registry_path")),
        project_solutions_path=_resolve_manifest_path(root, manifest.get("project_solutions") or manifest.get("project_solutions_path")),
    )

    if require_board_artifacts and not run.ready_for_board_to_log:
        missing = [
            str(path)
            for path in (
                run.document_regions_path,
                run.card_maps_path,
                run.slot_schema_path,
            )
            if not path.exists()
        ]
        raise RuntimeError(
            "Cleaner run is not ready for Board->Log; missing derived artifact(s): "
            + ", ".join(missing)
        )
    return run


def _queue_is_fully_reviewed(queue_path: Path) -> bool:
    if not queue_path.exists():
        return False
    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    return all(
        item.get("review_state") in {"RESOLVED", "DEFERRED"}
        and bool(item.get("decision"))
        for item in queue.get("items", [])
    )


def finalize_run(run_dir: str | Path) -> CleanerRun:
    """Ingest any fully-reviewed stage decision file not yet in resolved state.

    This mainly closes the final IDENTIFIERS review, because there is no later
    Cleaner stage whose startup would otherwise ingest that decision file.
    """
    run = load_cleaner_run(run_dir, require_board_artifacts=False)
    state = load_resolved_state(run.state_path)
    root = run.run_dir.parents[1] if run.run_dir.parent.name == "runs" else run.run_dir.parent

    profile_path = run.profile_path or (root / "profiles" / f"{run.profile_name}.profile.json")
    profile = load_profile(profile_path) if profile_path.exists() else {"profile_name": run.profile_name}

    exception_path = run.exception_registry_path or (root / "exceptions" / f"{run.profile_name}.exceptions.json")
    solutions_path = run.project_solutions_path or (root / "project_solutions" / f"{run.profile_name}.solutions.json")
    exceptions = load_exception_registry(exception_path, profile_name=run.profile_name, create=True)
    solutions = load_project_solutions(solutions_path, project_id=run.profile_name, create=True)

    for stage_id in CLEANER_STAGE_ORDER:
        stage = state.get("stages", {}).get(stage_id, {})
        stage_status = str(stage.get("status") or "")
        stem = stage_id.lower()
        queue_path = run.run_dir / f"{stem}_review_queue.json"
        decisions_path = run.run_dir / f"{stem}_review_decisions.json"

        # Finalization is intentionally idempotent. A reviewer may edit or add a
        # decision after a stage was previously marked REVIEWED, and downstream
        # functions must always see the latest logical workbook overlay. Re-ingest
        # every fully-reviewed decisions file on each finalization; state ingestion
        # is an upsert/audit-deduplicated operation and does not mutate Excel.
        if decisions_path.exists() and _queue_is_fully_reviewed(queue_path):
            ingest_review_decisions_file(state, decisions_path)

            # Review-time tooling already persists exception/project registries.
            # Keep the historical finalize behavior for a stage that is closing
            # now, but avoid re-syncing those registries on every downstream run.
            if stage_status == "AWAITING_REVIEW":
                sync_registry_from_decisions_file(exceptions, decisions_path)
                sync_project_solutions_from_decisions_file(solutions, decisions_path)
            continue

        if stage_status == "AWAITING_REVIEW":
            raise RuntimeError(
                f"Cleaner stage {stage_id} is still awaiting review. Finish its review before Board->Log."
            )

    save_resolved_state(state, run.state_path)
    save_exception_registry(exceptions, exception_path)
    save_project_solutions(solutions, solutions_path)
    return load_cleaner_run(run.run_dir, require_board_artifacts=True)
