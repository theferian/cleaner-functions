from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Iterable


def normalize_status_token(value: Any) -> str:
    """Normalize a status token for catalog lookup without changing punctuation.

    Punctuation is deliberately preserved because codes such as ``A.N`` and
    ``F.C`` may be meaningful project codes. Formatting variants should be
    modeled explicitly through ``aliases`` in the library instead of guessed.
    """
    if value is None:
        return ""
    text = str(value).translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))
    text = text.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))
    return text.strip().upper().replace(" ", "")


@dataclass(frozen=True)
class StatusDefinition:
    code: str
    aliases: tuple[str, ...] = ()
    meaning: str | None = None
    meaning_fa: str | None = None
    responsibility_after_receive: str | None = None
    action_required: bool | None = None
    notes: str | None = None
    source: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "aliases": list(self.aliases),
            "meaning": self.meaning,
            "meaning_fa": self.meaning_fa,
            "responsibility_after_receive": self.responsibility_after_receive,
            "action_required": self.action_required,
            "notes": self.notes,
            "source": self.source,
        }


@dataclass
class StatusLibrary:
    statuses: dict[str, StatusDefinition] = field(default_factory=dict)
    schema: str = "cleaner.status_library/0.1"
    path: Path | None = None

    def __post_init__(self) -> None:
        # Canonical keys are always normalized status tokens.
        self.statuses = {
            normalize_status_token(code): definition
            for code, definition in self.statuses.items()
            if normalize_status_token(code)
        }
        alias_map: dict[str, str] = {}
        for code, definition in self.statuses.items():
            alias_map[code] = code
            for alias in definition.aliases:
                token = normalize_status_token(alias)
                if token:
                    existing = alias_map.get(token)
                    if existing is not None and existing != code:
                        raise ValueError(
                            f"Status alias {alias!r} maps to both {existing!r} and {code!r}."
                        )
                    alias_map[token] = code
        self._alias_map = alias_map

    @property
    def known_codes(self) -> tuple[str, ...]:
        return tuple(sorted(self.statuses))

    def canonicalize(self, value: Any) -> str | None:
        token = normalize_status_token(value)
        if not token:
            return None
        return self._alias_map.get(token)

    def is_known(self, value: Any) -> bool:
        return self.canonicalize(value) is not None

    def definition(self, value: Any) -> StatusDefinition | None:
        code = self.canonicalize(value)
        return self.statuses.get(code) if code else None

    def statuses_for_responsibility(self, responsibility: str) -> set[str]:
        wanted = str(responsibility or "").strip().upper()
        return {
            code
            for code, definition in self.statuses.items()
            if str(definition.responsibility_after_receive or "").strip().upper() == wanted
            and definition.action_required is not False
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "statuses": {code: definition.to_dict() for code, definition in sorted(self.statuses.items())},
        }


_DEFAULT_LIBRARY = Path(__file__).resolve().parents[1] / "configs" / "status_library.json"


def default_status_library_path() -> Path:
    return _DEFAULT_LIBRARY


def _definition_from_payload(code: str, payload: Any) -> StatusDefinition:
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ValueError(f"Status definition for {code!r} must be a JSON object.")
    canonical = normalize_status_token(payload.get("code") or code)
    if not canonical:
        raise ValueError("Status code cannot be blank.")
    aliases = tuple(str(x) for x in (payload.get("aliases") or []) if str(x).strip())
    action_required = payload.get("action_required")
    if action_required is not None:
        action_required = bool(action_required)
    responsibility = payload.get("responsibility_after_receive")
    if responsibility is not None:
        responsibility = str(responsibility).strip().upper() or None
    return StatusDefinition(
        code=canonical,
        aliases=aliases,
        meaning=payload.get("meaning"),
        meaning_fa=payload.get("meaning_fa"),
        responsibility_after_receive=responsibility,
        action_required=action_required,
        notes=payload.get("notes"),
        source=payload.get("source"),
    )


def load_status_library(path: str | Path | None = None) -> StatusLibrary:
    explicit = path is not None
    path_obj = Path(path) if path is not None else default_status_library_path()
    if not path_obj.exists():
        if explicit:
            raise FileNotFoundError(f"Status library not found: {path_obj}")
        return StatusLibrary(path=path_obj)

    payload = json.loads(path_obj.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Status library root must be a JSON object.")
    statuses_payload = payload.get("statuses") or {}
    if not isinstance(statuses_payload, dict):
        raise ValueError("Status library 'statuses' must be a JSON object.")
    statuses: dict[str, StatusDefinition] = {}
    for code, definition_payload in statuses_payload.items():
        definition = _definition_from_payload(str(code), definition_payload)
        if definition.code in statuses:
            raise ValueError(f"Duplicate canonical status code {definition.code!r}.")
        statuses[definition.code] = definition
    return StatusLibrary(
        statuses=statuses,
        schema=str(payload.get("schema") or "cleaner.status_library/0.1"),
        path=path_obj,
    )


def save_status_library(library: StatusLibrary, path: str | Path | None = None) -> Path:
    target = Path(path) if path is not None else (library.path or default_status_library_path())
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(library.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    library.path = target
    return target


def upsert_status(
    library: StatusLibrary,
    *,
    code: str,
    aliases: Iterable[str] = (),
    meaning: str | None = None,
    meaning_fa: str | None = None,
    responsibility_after_receive: str | None = None,
    action_required: bool | None = None,
    notes: str | None = None,
    source: str | None = None,
) -> StatusDefinition:
    canonical = normalize_status_token(code)
    if not canonical:
        raise ValueError("Status code cannot be blank.")
    old = library.statuses.get(canonical)
    definition = StatusDefinition(
        code=canonical,
        aliases=tuple(aliases) if aliases else (old.aliases if old else ()),
        meaning=meaning if meaning is not None else (old.meaning if old else None),
        meaning_fa=meaning_fa if meaning_fa is not None else (old.meaning_fa if old else None),
        responsibility_after_receive=(
            str(responsibility_after_receive).strip().upper()
            if responsibility_after_receive is not None
            else (old.responsibility_after_receive if old else None)
        ),
        action_required=action_required if action_required is not None else (old.action_required if old else None),
        notes=notes if notes is not None else (old.notes if old else None),
        source=source if source is not None else (old.source if old else None),
    )
    library.statuses[canonical] = definition
    library.__post_init__()
    return definition
