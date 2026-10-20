from __future__ import annotations

import argparse
import json
from pathlib import Path

from .service import inspect_file, validate_file, extract_file, run_profile


def dump(obj, output=None):
    text = json.dumps(obj, ensure_ascii=False, indent=2)
    if output:
        Path(output).write_text(text + "\n", encoding="utf-8")
        print(output)
    else:
        print(text)


def main(argv=None):
    p = argparse.ArgumentParser(description="Weekly Report Cleaner read-only service")
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("inspect", "validate", "extract", "run"):
        s = sub.add_parser(name)
        s.add_argument("--workbook", required=True)
        s.add_argument("--profile", required=True)
        s.add_argument("--output")
    c = sub.add_parser("corpus-test")
    c.add_argument("--root", required=True)
    c.add_argument("--pattern", default="**/*.xlsx")
    c.add_argument("--profile", required=True)
    c.add_argument("--output")
    args = p.parse_args(argv)
    if args.command == "inspect":
        obj = inspect_file(args.workbook, args.profile)
    elif args.command == "validate":
        obj = validate_file(args.workbook, args.profile)
    elif args.command == "extract":
        obj = extract_file(args.workbook, args.profile)
    elif args.command == "run":
        obj = run_profile(args.workbook, args.profile)
    else:
        root = Path(args.root)
        rows = []
        for file in sorted(root.glob(args.pattern)):
            try:
                result = validate_file(file, args.profile)
                rows.append({"file": str(file), "status": result["status"], "counts": result["counts"], "issues": result["issues"]})
            except Exception as exc:
                rows.append({"file": str(file), "status": "failed_to_read", "error": str(exc)})
        obj = {"schema": "cleaner.weekly_report.corpus_test/0.1", "root": str(root), "files": rows,
               "summary": {"total": len(rows), "passed": sum(1 for x in rows if x.get("status") == "passed"), "needs_review": sum(1 for x in rows if x.get("status") == "needs_review"), "failed_to_read": sum(1 for x in rows if x.get("status") == "failed_to_read")}}
    dump(obj, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
