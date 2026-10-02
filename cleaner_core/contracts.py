from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class Finding:
    test_id: str
    status: str
    message: str
    sheet: str | None = None
    target: str | None = None
    severity: str = "INFO"
    expected: Any = None
    observed: Any = None
    evidence: dict[str, Any] = field(default_factory=dict)
    suggested_exception: dict[str, Any] | None = None

    def to_dict(self):
        return asdict(self)


@dataclass
class DiscoveryCandidate:
    discovery_id: str
    sheet: str
    target: str
    message: str
    evidence: dict[str, Any] = field(default_factory=dict)
    suggested_profile_patch: dict[str, Any] | None = None

    def to_dict(self):
        return asdict(self)


@dataclass
class RunReport:
    kind: str
    script_id: str
    logs: list[dict[str, str]] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    candidates: list[DiscoveryCandidate] = field(default_factory=list)
    snapshot_path: str | None = None

    def to_dict(self):
        return {
            "kind": self.kind,
            "script_id": self.script_id,
            "logs": list(self.logs),
            "findings": [x.to_dict() for x in self.findings],
            "candidates": [x.to_dict() for x in self.candidates],
            "snapshot_path": self.snapshot_path,
        }
