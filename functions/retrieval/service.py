from __future__ import annotations

from datetime import date, datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
from typing import Any, Iterable

from .contracts import RetrievalCandidate, RetrievalResult


class RetrievalConfigError(ValueError):
    pass


class RetrievalError(RuntimeError):
    pass


SUPPORTED_SOURCE_MODES = {"direct", "latest_regex"}
SUPPORTED_DUPLICATE_POLICIES = {"latest_date", "latest_modified", "error"}


def load_retrieval_config(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Retrieval configuration not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RetrievalConfigError("Retrieval configuration root must be a JSON object.")
    if not isinstance(data.get("families"), dict) or not data["families"]:
        raise RetrievalConfigError('Retrieval configuration requires a non-empty "families" object.')
    if not isinstance(data.get("projects"), dict) or not data["projects"]:
        raise RetrievalConfigError('Retrieval configuration requires a non-empty "projects" object.')
    return data


def _normalize_project(value: str) -> str:
    result = str(value or "").strip().upper()
    if not result:
        raise RetrievalConfigError("project_id cannot be empty.")
    return result


def _normalize_family(value: str) -> str:
    result = str(value or "").strip().upper()
    if not result:
        raise RetrievalConfigError("family cannot be empty.")
    return result


def _family_config(config: dict[str, Any], family: str) -> dict[str, Any]:
    family = _normalize_family(family)
    raw = config.get("families", {}).get(family)
    if not isinstance(raw, dict):
        raise RetrievalConfigError(f"Unknown retrieval family: {family}")
    if raw.get("enabled", True) is False:
        raise RetrievalConfigError(f"Retrieval family {family} is disabled in configuration.")
    return raw


def _project_config(config: dict[str, Any], project_id: str) -> dict[str, Any]:
    project_id = _normalize_project(project_id)
    raw = config.get("projects", {}).get(project_id)
    if not isinstance(raw, dict):
        raise RetrievalConfigError(f"Unknown project: {project_id}")
    if raw.get("enabled", True) is False:
        raise RetrievalConfigError(f"Project {project_id} is disabled in retrieval configuration.")
    return raw


def _source_config(config: dict[str, Any], project_id: str, family: str) -> dict[str, Any]:
    project = _project_config(config, project_id)
    family_cfg = _family_config(config, family)
    source = dict(family_cfg.get("source_defaults") or {})
    project_source = (project.get("sources") or {}).get(_normalize_family(family))
    if isinstance(project_source, dict):
        source.update(project_source)
    if not source:
        raise RetrievalConfigError(
            f"No source configuration exists for project {project_id}, family {family}."
        )
    mode = str(source.get("mode") or "latest_regex").strip().lower()
    if mode not in SUPPORTED_SOURCE_MODES:
        raise RetrievalConfigError(
            f"Unsupported retrieval source mode {mode!r}; expected one of {sorted(SUPPORTED_SOURCE_MODES)}."
        )
    source["mode"] = mode
    return source


def _valid_jalali_yyyymmdd(value: str | None) -> bool:
    if not value or re.fullmatch(r"\d{8}", str(value)) is None:
        return False
    year = int(value[:4])
    month = int(value[4:6])
    day = int(value[6:8])
    if not 1200 <= year <= 1599:
        return False
    if not 1 <= month <= 12:
        return False
    max_day = 31 if month <= 6 else 30
    if month == 12:
        max_day = 30  # broad structural check; leap-year precision is unnecessary for filename ranking
    return 1 <= day <= max_day


def gregorian_to_jalali(gy: int, gm: int, gd: int) -> tuple[int, int, int]:
    g_days_in_month = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    j_days_in_month = [31, 31, 31, 31, 31, 31, 30, 30, 30, 30, 30, 29]

    gy2 = gy - 1600
    gm2 = gm - 1
    gd2 = gd - 1

    g_day_no = 365 * gy2 + (gy2 + 3) // 4 - (gy2 + 99) // 100 + (gy2 + 399) // 400
    for i in range(gm2):
        g_day_no += g_days_in_month[i]
    leap = (gy % 4 == 0 and gy % 100 != 0) or (gy % 400 == 0)
    if gm2 > 1 and leap:
        g_day_no += 1
    g_day_no += gd2

    j_day_no = g_day_no - 79
    j_np = j_day_no // 12053
    j_day_no %= 12053
    jy = 979 + 33 * j_np + 4 * (j_day_no // 1461)
    j_day_no %= 1461
    if j_day_no >= 366:
        jy += (j_day_no - 1) // 365
        j_day_no = (j_day_no - 1) % 365

    jm = 0
    while jm < 11 and j_day_no >= j_days_in_month[jm]:
        j_day_no -= j_days_in_month[jm]
        jm += 1
    return jy, jm + 1, j_day_no + 1


def jalali_date_yyyymmdd(source_date: date | datetime | None = None) -> str:
    if source_date is None:
        source_date = date.today()
    if isinstance(source_date, datetime):
        source_date = source_date.date()
    jy, jm, jd = gregorian_to_jalali(source_date.year, source_date.month, source_date.day)
    return f"{jy:04d}{jm:02d}{jd:02d}"


def sha256_file(path: str | Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def discover_candidates(
    config: dict[str, Any], project_id: str, family: str
) -> list[RetrievalCandidate]:
    project_id = _normalize_project(project_id)
    family = _normalize_family(family)
    source = _source_config(config, project_id, family)
    mode = source["mode"]

    if mode == "direct":
        raw_path = str(source.get("path") or "").strip()
        if not raw_path:
            raise RetrievalConfigError(
                f"Direct source path is empty for project {project_id}, family {family}."
            )
        path = Path(raw_path)
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"Configured source file does not exist: {path}")
        return [
            RetrievalCandidate(
                path=path,
                project_id=project_id,
                family=family,
                modified_time=path.stat().st_mtime,
                metadata={"mode": "direct"},
            )
        ]

    root_raw = str(source.get("root") or "").strip()
    regex_raw = str(source.get("file_name_regex") or "").strip()
    if not root_raw:
        raise RetrievalConfigError(
            f"latest_regex source root is empty for project {project_id}, family {family}."
        )
    if not regex_raw:
        raise RetrievalConfigError(
            f"latest_regex file_name_regex is empty for project {project_id}, family {family}."
        )

    root = Path(root_raw)
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(f"Retrieval source folder does not exist: {root}")

    regex = re.compile(regex_raw, re.IGNORECASE)
    recursive = bool(source.get("recursive", False))
    extensions = {str(x).lower() for x in source.get("extensions", [".xlsx", ".xlsm"])}
    project_group = str(source.get("project_group") or "proj_id")
    date_group = source.get("date_group", "jalali_date")

    candidates: list[RetrievalCandidate] = []
    iterator: Iterable[Path] = root.rglob("*") if recursive else root.glob("*")
    for path in iterator:
        if not path.is_file() or path.name.startswith("~$"):
            continue
        if path.suffix.lower() not in extensions:
            continue
        match = regex.fullmatch(path.name)
        if match is None:
            continue
        try:
            found_project = str(match.group(project_group)).strip().upper()
        except (IndexError, KeyError) as exc:
            raise RetrievalConfigError(
                f'Filename regex has no project group {project_group!r}.'
            ) from exc
        if found_project != project_id:
            continue

        captured_date = None
        if date_group:
            try:
                captured_date = str(match.group(str(date_group))).strip()
            except (IndexError, KeyError) as exc:
                raise RetrievalConfigError(
                    f'Filename regex has no date group {date_group!r}.'
                ) from exc
            if captured_date and not _valid_jalali_yyyymmdd(captured_date):
                continue

        candidates.append(
            RetrievalCandidate(
                path=path,
                project_id=project_id,
                family=family,
                captured_date=captured_date,
                modified_time=path.stat().st_mtime,
                metadata={"mode": "latest_regex", "root": str(root)},
            )
        )
    return candidates


def select_candidate(
    candidates: list[RetrievalCandidate], duplicate_policy: str
) -> RetrievalCandidate:
    if not candidates:
        raise RetrievalError("No retrieval candidates matched the configured project/family.")
    if len(candidates) == 1:
        return candidates[0]

    policy = str(duplicate_policy or "latest_date").strip().lower()
    if policy not in SUPPORTED_DUPLICATE_POLICIES:
        raise RetrievalConfigError(
            f"Unsupported duplicate policy {policy!r}; expected one of {sorted(SUPPORTED_DUPLICATE_POLICIES)}."
        )
    if policy == "error":
        raise RetrievalError(
            "Multiple retrieval candidates matched: "
            + ", ".join(sorted(item.path.name for item in candidates))
        )
    if policy == "latest_modified":
        return max(candidates, key=lambda item: (item.modified_time or 0.0, item.path.name))

    dated = [item for item in candidates if item.captured_date]
    if not dated:
        raise RetrievalError(
            'Duplicate policy "latest_date" requires a captured Jalali date in matching filenames.'
        )
    return max(
        dated,
        key=lambda item: (item.captured_date or "", item.modified_time or 0.0, item.path.name),
    )


def build_retrieved_name(
    *,
    project_id: str,
    name_token: str,
    retrieval_date: str,
    extension: str,
    report_order: str | None = None,
) -> str:
    project_id = _normalize_project(project_id)
    token = str(name_token or "").strip()
    if not token:
        raise RetrievalConfigError("Retrieval family name_token cannot be empty.")
    if not _valid_jalali_yyyymmdd(retrieval_date):
        raise RetrievalConfigError(
            f"retrieval_date must be Jalali YYYYMMDD, got {retrieval_date!r}."
        )
    prefix = f"{str(report_order).strip()}_" if report_order not in (None, "") else ""
    suffix = str(extension or "").lower()
    if not suffix.startswith("."):
        suffix = f".{suffix}"
    return f"{prefix}{project_id}_{token}_{retrieval_date}{suffix}"


def retrieve_document(
    config: dict[str, Any],
    *,
    project_id: str,
    family: str,
    destination: str | Path | None = None,
    retrieval_date: str | None = None,
    overwrite: bool = False,
) -> RetrievalResult:
    project_id = _normalize_project(project_id)
    family = _normalize_family(family)
    family_cfg = _family_config(config, family)
    project_cfg = _project_config(config, project_id)
    source_cfg = _source_config(config, project_id, family)

    candidates = discover_candidates(config, project_id, family)
    duplicate_policy = str(source_cfg.get("duplicate_policy") or "latest_date")
    if source_cfg["mode"] == "direct":
        duplicate_policy = "error"
    selected = select_candidate(candidates, duplicate_policy)

    retrieval_date = retrieval_date or jalali_date_yyyymmdd()
    if destination is None:
        destination = config.get("retrieval_workspace") or "./input"
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)

    report_order = project_cfg.get("report_order")
    name_token = str(family_cfg.get("name_token") or family).strip()
    output_name = build_retrieved_name(
        project_id=project_id,
        name_token=name_token,
        retrieval_date=retrieval_date,
        extension=selected.path.suffix,
        report_order=str(report_order) if report_order not in (None, "") else None,
    )
    output_path = destination / output_name

    source_hash = sha256_file(selected.path)
    if output_path.exists():
        if output_path.resolve() == selected.path.resolve():
            return RetrievalResult(
                project_id=project_id,
                family=family,
                source_path=selected.path,
                retrieved_path=output_path,
                retrieval_date=retrieval_date,
                report_order=str(report_order) if report_order not in (None, "") else None,
                name_token=name_token,
                source_mode=source_cfg["mode"],
                candidate_count=len(candidates),
                selected_date=selected.captured_date,
                sha256=source_hash,
                metadata={"copy_action": "source_is_destination"},
            )
        if not overwrite:
            existing_hash = sha256_file(output_path)
            if existing_hash == source_hash:
                return RetrievalResult(
                    project_id=project_id,
                    family=family,
                    source_path=selected.path,
                    retrieved_path=output_path,
                    retrieval_date=retrieval_date,
                    report_order=str(report_order) if report_order not in (None, "") else None,
                    name_token=name_token,
                    source_mode=source_cfg["mode"],
                    candidate_count=len(candidates),
                    selected_date=selected.captured_date,
                    sha256=source_hash,
                    metadata={"copy_action": "already_retrieved_same_content"},
                )
            raise FileExistsError(
                f"Retrieved destination already exists with different content: {output_path}. "
                "Use overwrite=True to replace it."
            )

    shutil.copy2(selected.path, output_path)
    copied_hash = sha256_file(output_path)
    if copied_hash != source_hash:
        output_path.unlink(missing_ok=True)
        raise RetrievalError(
            f"Retrieved copy failed SHA-256 verification: {selected.path} -> {output_path}"
        )

    return RetrievalResult(
        project_id=project_id,
        family=family,
        source_path=selected.path,
        retrieved_path=output_path,
        retrieval_date=retrieval_date,
        report_order=str(report_order) if report_order not in (None, "") else None,
        name_token=name_token,
        source_mode=source_cfg["mode"],
        candidate_count=len(candidates),
        selected_date=selected.captured_date,
        sha256=copied_hash,
        metadata={"copy_action": "copied"},
    )


def retrieve_project_set(
    config: dict[str, Any],
    *,
    project_id: str,
    families: list[str] | None = None,
    destination: str | Path | None = None,
    retrieval_date: str | None = None,
    overwrite: bool = False,
) -> list[RetrievalResult]:
    if families is None:
        families = [
            key
            for key, value in config.get("families", {}).items()
            if not isinstance(value, dict) or value.get("enabled", True) is not False
        ]
    results: list[RetrievalResult] = []
    for family in families:
        results.append(
            retrieve_document(
                config,
                project_id=project_id,
                family=family,
                destination=destination,
                retrieval_date=retrieval_date,
                overwrite=overwrite,
            )
        )
    return results


def write_retrieval_manifest(
    results: list[RetrievalResult], path: str | Path
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "weekly_report.retrieval_manifest/0.1",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "results": [item.to_dict() for item in results],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
