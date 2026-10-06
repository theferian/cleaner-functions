from __future__ import annotations

from datetime import date
import json
from pathlib import Path

import pytest

from functions.retrieval import (
    RetrievalError,
    build_retrieved_name,
    discover_candidates,
    jalali_date_yyyymmdd,
    retrieve_document,
    select_candidate,
)


def _config(root: Path, destination: Path) -> dict:
    return {
        "retrieval_workspace": str(destination),
        "families": {
            "GENERAL_DOCUMENT": {
                "enabled": True,
                "name_token": "LATEST_GENERAL_DOC",
                "source_defaults": {
                    "mode": "latest_regex",
                    "root": str(root),
                    "recursive": False,
                    "extensions": [".xlsx"],
                    "file_name_regex": r"^(?:\d+(?:\.\d+)?)_(?P<proj_id>[A-Z0-9]+)_LATEST_GENERAL_DOC_(?P<jalali_date>\d{8})\.xlsx$",
                    "project_group": "proj_id",
                    "date_group": "jalali_date",
                    "duplicate_policy": "latest_date",
                },
            },
            "PROCUREMENT": {"enabled": False, "name_token": "LATEST_PROCUREMENT"},
        },
        "projects": {
            "AZD": {"enabled": True, "report_order": "7", "sources": {}},
            "BFG": {"enabled": True, "report_order": "4.1", "sources": {}},
        },
    }


def test_jalali_converter_known_date():
    assert jalali_date_yyyymmdd(date(2026, 10, 7)) == "14050715"


def test_build_name_preserves_decimal_report_order():
    assert (
        build_retrieved_name(
            project_id="BFG",
            name_token="LATEST_GENERAL_DOC",
            retrieval_date="14050715",
            extension=".xlsx",
            report_order="4.1",
        )
        == "4.1_BFG_LATEST_GENERAL_DOC_14050715.xlsx"
    )


def test_latest_regex_selects_latest_jalali_date(tmp_path: Path):
    source = tmp_path / "src"
    destination = tmp_path / "out"
    source.mkdir()
    (source / "7_AZD_LATEST_GENERAL_DOC_14050707.xlsx").write_bytes(b"old")
    (source / "7_AZD_LATEST_GENERAL_DOC_14050708.xlsx").write_bytes(b"new")
    (source / "~$7_AZD_LATEST_GENERAL_DOC_14050709.xlsx").write_bytes(b"temp")
    config = _config(source, destination)

    candidates = discover_candidates(config, "AZD", "GENERAL_DOCUMENT")
    assert len(candidates) == 2
    chosen = select_candidate(candidates, "latest_date")
    assert chosen.path.name.endswith("14050708.xlsx")


def test_retrieve_copies_and_standardizes_name(tmp_path: Path):
    source = tmp_path / "src"
    destination = tmp_path / "out"
    source.mkdir()
    original = source / "7_AZD_LATEST_GENERAL_DOC_14050707.xlsx"
    original.write_bytes(b"excel-like-content")
    config = _config(source, destination)

    result = retrieve_document(
        config,
        project_id="AZD",
        family="GENERAL_DOCUMENT",
        retrieval_date="14050715",
    )

    assert result.retrieved_path.name == "7_AZD_LATEST_GENERAL_DOC_14050715.xlsx"
    assert result.retrieved_path.read_bytes() == original.read_bytes()
    assert result.sha256
    assert result.metadata["copy_action"] == "copied"


def test_retrieve_is_idempotent_when_same_content_already_exists(tmp_path: Path):
    source = tmp_path / "src"
    destination = tmp_path / "out"
    source.mkdir()
    original = source / "7_AZD_LATEST_GENERAL_DOC_14050707.xlsx"
    original.write_bytes(b"same")
    config = _config(source, destination)

    first = retrieve_document(
        config,
        project_id="AZD",
        family="GENERAL_DOCUMENT",
        retrieval_date="14050715",
    )
    second = retrieve_document(
        config,
        project_id="AZD",
        family="GENERAL_DOCUMENT",
        retrieval_date="14050715",
    )
    assert first.retrieved_path == second.retrieved_path
    assert second.metadata["copy_action"] == "already_retrieved_same_content"


def test_retrieve_refuses_different_existing_destination_without_overwrite(tmp_path: Path):
    source = tmp_path / "src"
    destination = tmp_path / "out"
    source.mkdir()
    destination.mkdir()
    original = source / "7_AZD_LATEST_GENERAL_DOC_14050707.xlsx"
    original.write_bytes(b"new")
    (destination / "7_AZD_LATEST_GENERAL_DOC_14050715.xlsx").write_bytes(b"different")
    config = _config(source, destination)

    with pytest.raises(FileExistsError):
        retrieve_document(
            config,
            project_id="AZD",
            family="GENERAL_DOCUMENT",
            retrieval_date="14050715",
        )


def test_direct_source_mode(tmp_path: Path):
    source_file = tmp_path / "master.xlsx"
    source_file.write_bytes(b"direct")
    destination = tmp_path / "out"
    config = {
        "retrieval_workspace": str(destination),
        "families": {"GENERAL_DOCUMENT": {"enabled": True, "name_token": "LATEST_GENERAL_DOC"}},
        "projects": {
            "AZD": {
                "enabled": True,
                "report_order": "7",
                "sources": {"GENERAL_DOCUMENT": {"mode": "direct", "path": str(source_file)}},
            }
        },
    }
    result = retrieve_document(
        config,
        project_id="AZD",
        family="GENERAL_DOCUMENT",
        retrieval_date="14050715",
    )
    assert result.source_mode == "direct"
    assert result.retrieved_path.exists()


def test_latest_date_requires_dated_candidates():
    from functions.retrieval.contracts import RetrievalCandidate

    candidates = [
        RetrievalCandidate(Path("a.xlsx"), "AZD", "GENERAL_DOCUMENT", modified_time=1),
        RetrievalCandidate(Path("b.xlsx"), "AZD", "GENERAL_DOCUMENT", modified_time=2),
    ]
    with pytest.raises(RetrievalError):
        select_candidate(candidates, "latest_date")
