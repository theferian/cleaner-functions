"""Read-only shared-folder discovery for Cleaner 4A.12a.

Collect a bounded, reproducible metadata inventory. Does not open/read file contents,
change source folders, perform OCR, or upload anything.

Example (Windows CMD):
  python discover_shared_letters_v01.py --root "W:\\00-1403\\1403-02-05-230kV Azad\\Letter" --out "working\\shared_folder_discovery\\AZD_letters_v01.json" --find "1404/ES/S/3003"
"""
from __future__ import annotations
import argparse
import collections
import datetime as dt
import json
import os
from pathlib import Path
import re
import sys

MAX_EXAMPLES = 8

def normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def inventory(root: Path, *, max_depth: int, max_files: int, sample_size: int, find: str) -> dict:
    if not root.exists() or not root.is_dir():
        raise ValueError(f"Source directory does not exist or cannot be accessed: {root}")
    if not (0 <= max_depth <= 25):
        raise ValueError("--max-depth must be between 0 and 25")
    if not (1 <= max_files <= 500_000):
        raise ValueError("--max-files must be between 1 and 500000")
    find_key = normalize(find)
    by_ext: collections.Counter[str] = collections.Counter()
    folder_summaries: dict[str, dict] = {}
    sample_names: dict[str, list[str]] = {}
    candidates: list[dict] = []
    entries: list[dict] = []
    errors: list[dict] = []
    scanned_directories = 0
    cutoff = False
    # Depth means number of directory levels below root (root is 0).
    queue = collections.deque([(root, 0)])
    while queue:
        folder, depth = queue.popleft()
        scanned_directories += 1
        relative_folder = "." if folder == root else folder.relative_to(root).as_posix()
        top_branch = "." if relative_folder == "." else relative_folder.split("/")[0]
        bucket = folder_summaries.setdefault(top_branch, {"files": 0, "folders": 0, "extensions": {}})
        try:
            # Stable results allow meaningful diffing of consecutive inventories.
            with os.scandir(folder) as scan:
                items = sorted(list(scan), key=lambda x: x.name.casefold())
        except (OSError, PermissionError) as exc:
            errors.append({"folder": relative_folder, "error": type(exc).__name__, "message": str(exc)})
            continue
        for item in items:
            try:
                if item.is_symlink():  # Avoid crossing junctions, cycles or linked trees.
                    continue
                if item.is_dir(follow_symlinks=False):
                    bucket["folders"] += 1
                    if depth < max_depth:
                        queue.append((Path(item.path), depth + 1))
                    continue
                if not item.is_file(follow_symlinks=False):
                    continue
                if len(entries) >= max_files:
                    cutoff = True
                    queue.clear()
                    break
                stat = item.stat(follow_symlinks=False)
                relpath = Path(item.path).relative_to(root).as_posix()
                ext = Path(item.name).suffix.casefold() or "[no extension]"
                entry = {
                    "relative_path": relpath,
                    "extension": ext,
                    "size_bytes": stat.st_size,
                    "modified_utc": dt.datetime.fromtimestamp(stat.st_mtime, dt.timezone.utc).isoformat(),
                }
                entries.append(entry)
                by_ext[ext] += 1
                bucket["files"] += 1
                bucket["extensions"][ext] = bucket["extensions"].get(ext, 0) + 1
                samples = sample_names.setdefault(top_branch, [])
                if len(samples) < sample_size:
                    samples.append(relpath)
                if find_key and find_key in normalize(relpath):
                    candidates.append(entry)
            except (OSError, PermissionError) as exc:
                errors.append({"folder": relative_folder, "item": item.name, "error": type(exc).__name__})
    return {
        "schema": "cleaner.shared_folder_discovery/0.1",
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source_root": str(root),
        "source_mode": "read_only_metadata",
        "scope": {"max_depth": max_depth, "max_files": max_files, "truncated": cutoff,
                  "note": "Links/junctions are not followed; files are not opened or hashed."},
        "summary": {"directories_scanned": scanned_directories, "files_indexed": len(entries),
                    "extensions": dict(by_ext.most_common()), "errors": len(errors)},
        "branches": dict(sorted(folder_summaries.items())),
        "sample_paths_by_branch": dict(sorted(sample_names.items())),
        "filename_candidates": {"query": find, "count": len(candidates), "records": candidates[:50],
                                "note": "Only filename/path matching. No source contents verified."},
        "errors": errors[:100],
        "files": entries,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", required=True, help="Shared-folder Letter root, mapped or UNC")
    ap.add_argument("--out", required=True, help="LOCAL JSON output path (never network folder)")
    ap.add_argument("--max-depth", type=int, default=4)
    ap.add_argument("--max-files", type=int, default=20000)
    ap.add_argument("--samples", type=int, default=5)
    ap.add_argument("--find", default="1404/ES/S/3003")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()
    out = Path(args.out).resolve()
    # Fail closed if user points report output into source or descendants.
    if out == root or root in out.parents:
        ap.error("--out must be outside the scanned shared folder")
    try:
        result = inventory(root, max_depth=args.max_depth, max_files=args.max_files,
                           sample_size=args.samples, find=args.find)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError) as exc:
        print(f"[STOP] {exc}", file=sys.stderr)
        return 2
    summary = result["summary"]
    print(f"[ROOT] {root}")
    print(f"[SCAN] dirs={summary['directories_scanned']} files={summary['files_indexed']} errors={summary['errors']} truncated={result['scope']['truncated']}")
    print("[EXT] " + ", ".join(f"{k}={v}" for k,v in list(summary["extensions"].items())[:12]))
    for branch, rec in result["branches"].items():
        print(f"[BRANCH] {branch}: files={rec['files']} folders={rec['folders']}")
        for s in result['sample_paths_by_branch'].get(branch, [])[:3]:
            print(f"  sample: {s}")
    print(f"[FILENAME CANDIDATES] {result['filename_candidates']['count']} (not content verified)")
    for r in result['filename_candidates']['records'][:5]:
        print(f"  {r['relative_path']}")
    print(f"[LOCAL REPORT] {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
