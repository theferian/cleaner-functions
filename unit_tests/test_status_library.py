from pathlib import Path

from cleaner_core.status_library import (
    StatusLibrary,
    load_status_library,
    save_status_library,
    upsert_status,
)


def test_default_library_knows_rj_as_rejected():
    library = load_status_library()
    item = library.definition("RJ")
    assert item is not None
    assert item.meaning == "Rejected"
    assert item.meaning_fa == "رد شده"
    assert item.responsibility_after_receive == "COMPANY"
    assert item.action_required is True


def test_aliases_are_explicit_not_guessed(tmp_path: Path):
    library = StatusLibrary()
    upsert_status(
        library,
        code="CM",
        aliases=["C.M"],
        meaning="Comment",
        responsibility_after_receive="COMPANY",
        action_required=True,
    )
    path = save_status_library(library, tmp_path / "statuses.json")
    loaded = load_status_library(path)
    assert loaded.canonicalize("cm") == "CM"
    assert loaded.canonicalize("C.M") == "CM"
    assert loaded.canonicalize("C-M") is None


def test_company_responsibility_can_be_derived_from_semantics():
    library = load_status_library()
    assert "RJ" in library.statuses_for_responsibility("COMPANY")
