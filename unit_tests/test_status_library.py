from pathlib import Path

from cleaner_core.status_library import (
    confirm_status_alias,
    register_canonical_status,
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

def test_default_library_contains_confirmed_fsh_status_knowledge():
    library = load_status_library()
    assert library.canonicalize("C.M") == "CM"
    assert library.canonicalize("CM") == "CM"
    assert library.canonicalize("N.A") == "N.A"
    assert library.definition("N.A").meaning == "Not Approved"
    assert library.definition("N.A").responsibility_after_receive == "COMPANY"


def test_confirm_status_alias_is_idempotent_and_preserves_metadata():
    library = StatusLibrary()
    upsert_status(library, code="CM", aliases=["COMMENT"], meaning="Existing meaning")
    first = confirm_status_alias(library, alias="C.M", canonical="CM")
    second = confirm_status_alias(library, alias="c.m", canonical="cm")
    assert first.meaning == "Existing meaning"
    assert second.meaning == "Existing meaning"
    assert library.canonicalize("COMMENT") == "CM"
    assert library.canonicalize("C.M") == "CM"
    assert len(library.statuses["CM"].aliases) == 2


def test_confirm_status_alias_rejects_conflicting_remap():
    library = StatusLibrary()
    upsert_status(library, code="CM", aliases=["C.M"])
    upsert_status(library, code="OTHER")
    try:
        confirm_status_alias(library, alias="C.M", canonical="OTHER")
    except ValueError as exc:
        assert "refusing to remap" in str(exc)
    else:
        raise AssertionError("Expected conflicting alias remap to fail")


def test_register_canonical_status_without_semantic_guessing():
    library = StatusLibrary()
    item = register_canonical_status(
        library,
        "N.A",
        notes="Confirmed valid; meaning pending.",
        source="user-confirmed",
    )
    assert item.code == "N.A"
    assert item.meaning is None
    assert item.action_required is None
    assert library.is_known("N.A")
