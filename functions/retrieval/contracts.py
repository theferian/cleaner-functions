from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RetrievalCandidate:
    path: Path
    project_id: str
    family: str
    captured_date: str | None = None
    modified_time: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["path"] = str(self.path)
        return payload


@dataclass(frozen=True)
class RetrievalResult:
    project_id: str
    family: str
    source_path: Path
    retrieved_path: Path
    retrieval_date: str
    report_order: str | None
    name_token: str
    source_mode: str
    candidate_count: int
    selected_date: str | None = None
    sha256: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["source_path"] = str(self.source_path)
        payload["retrieved_path"] = str(self.retrieved_path)
        return payload
