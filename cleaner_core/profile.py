from __future__ import annotations
import json
from pathlib import Path


def load_profile(path: str | Path) -> dict:
    path = Path(path)
    with path.open("r", encoding="utf-8") as f:
        profile = json.load(f)

    if not isinstance(profile, dict):
        raise ValueError("Profile root must be a JSON object.")

    if "schema_version" not in profile:
        raise ValueError("Profile is missing schema_version.")

    return profile
