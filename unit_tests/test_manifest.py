import json
from pathlib import Path


def test_manifest():
    root = Path(__file__).resolve().parents[1]
    data = json.loads((root / "cleaner.package.json").read_text(encoding="utf-8"))
    assert data["package_id"] == "cleaner_functions"
    assert data["core_module"] == "cleaner_core"
    assert data["entrypoints"]["tests"] == "tests"
