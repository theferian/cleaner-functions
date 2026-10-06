from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from functions.cleaner.azd_pipeline import STAGES, main as cleaner_main


def _retrieved_workbook(project: str, manifest: str | Path | None) -> Path:
    project = str(project).strip().upper()
    path = Path(manifest) if manifest else PROJECT_ROOT / "input" / f"{project}_retrieval_manifest.json"
    if not path.exists():
        raise FileNotFoundError(
            f"Retrieval manifest not found: {path}. Run weekly_report_pipeline.py prepare-general-doc first."
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    matches = [
        item for item in payload.get("results", [])
        if str(item.get("project_id") or "").upper() == project
        and str(item.get("family") or "").upper() == "GENERAL_DOCUMENT"
    ]
    if not matches:
        raise RuntimeError(f"Manifest {path} has no GENERAL_DOCUMENT result for {project}.")
    workbook = Path(str(matches[-1].get("retrieved_path") or ""))
    if not workbook.exists():
        raise FileNotFoundError(f"Retrieved workbook from manifest does not exist: {workbook}")
    return workbook


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Generic project Cleaner launcher for retrieved General-Document workbooks."
    )
    p.add_argument("--project", required=True)
    p.add_argument("--stage", choices=STAGES, required=True)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--new-run", action="store_true")
    mode.add_argument("--run-id")
    p.add_argument("--workbook", default=None)
    p.add_argument("--manifest", default=None)
    p.add_argument("--profile", default=None)
    p.add_argument("--decisions", action="append", default=[])
    p.add_argument("--exception-registry", default=None)
    p.add_argument("--project-solutions", default=None)
    p.add_argument("--keep-snapshot", action="store_true")
    p.add_argument(
        "--no-open-excel",
        action="store_true",
        help="Do not auto-open the retrieved working copy; require it to already be open in Excel.",
    )
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    project = str(args.project).strip().upper()
    profile = Path(args.profile) if args.profile else PROJECT_ROOT / "profiles" / f"{project}.profile.json"
    if not profile.exists():
        raise FileNotFoundError(
            f"Project profile not found: {profile}. Run prepare-general-doc for {project} first."
        )
    workbook = Path(args.workbook) if args.workbook else _retrieved_workbook(project, args.manifest)
    workbook = workbook.resolve()

    forwarded = [
        "--stage", args.stage,
        "--profile", str(profile),
        "--workbook", str(workbook),
    ]
    if not args.no_open_excel:
        forwarded.append("--open-workbook")
    if args.new_run:
        forwarded.append("--new-run")
    else:
        forwarded.extend(["--run-id", str(args.run_id)])
    for decision in args.decisions:
        forwarded.extend(["--decisions", decision])
    if args.exception_registry:
        forwarded.extend(["--exception-registry", args.exception_registry])
    if args.project_solutions:
        forwarded.extend(["--project-solutions", args.project_solutions])
    if args.keep_snapshot:
        forwarded.append("--keep-snapshot")
    return int(cleaner_main(forwarded) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
