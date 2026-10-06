from __future__ import annotations

import argparse
from pathlib import Path

from functions.cleaner import finalize_run
from . import extract_board_to_log, write_csv, write_excel_com, write_json


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a canonical Logbook from a reviewed Cleaner run.")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--project", default=None)
    parser.add_argument("--json-out", default=None)
    parser.add_argument("--csv-out", default=None)
    parser.add_argument("--excel-workbook", default=None)
    parser.add_argument("--sheet", default="Logbook")
    parser.add_argument("--no-save", action="store_true")
    args = parser.parse_args()

    run = finalize_run(args.run_dir)
    result = extract_board_to_log(run, project_id=args.project)
    out_json = Path(args.json_out) if args.json_out else run.run_dir / "board_to_log.json"
    write_json(result, out_json)
    print(f"[BOARD_TO_LOG] Records: {len(result.records)}")
    print(f"[BOARD_TO_LOG] Issues : {len(result.issues)}")
    print(f"[BOARD_TO_LOG] JSON   : {out_json}")

    if args.csv_out:
        csv_path = write_csv(result, args.csv_out)
        print(f"[BOARD_TO_LOG] CSV    : {csv_path}")
    if args.excel_workbook:
        summary = write_excel_com(
            result,
            workbook_path=args.excel_workbook,
            sheet_name=args.sheet,
            save=not args.no_save,
        )
        print(f"[BOARD_TO_LOG] Excel  : {summary}")


if __name__ == "__main__":
    main()
