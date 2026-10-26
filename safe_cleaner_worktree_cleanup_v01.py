"""Safely reconcile accidental *untracked* Cleaner copies across Git worktrees.

Windows CMD (run in cleaner-wr-family):
  python safe_cleaner_worktree_cleanup_v01.py --check
  python safe_cleaner_worktree_cleanup_v01.py --copy-wr-candidates
  python safe_cleaner_worktree_cleanup_v01.py --quarantine-duplicates

Never removes source files without first retaining a byte-identical recoverable
copy. Only exact duplicates are quarantined; unique files are retained in main.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def git(root: Path, *argv: str) -> str:
    p = subprocess.run(["git", "-C", str(root), *argv], capture_output=True, check=False)
    if p.returncode:
        raise RuntimeError(f"git {' '.join(argv)} failed for {root}: {p.stderr.decode(errors='replace').strip()}")
    return p.stdout.decode("utf-8", errors="replace").strip()


def repo_info(root: Path) -> dict:
    actual = Path(git(root, "rev-parse", "--show-toplevel")).resolve()
    if actual != root:
        raise RuntimeError(f"Expected root {root}, Git root is {actual}")
    commondir = Path(git(root, "rev-parse", "--git-common-dir"))
    if not commondir.is_absolute():
        commondir = (root / commondir).resolve()
    return {"root": root, "branch": git(root, "branch", "--show-current"),
            "head": git(root, "rev-parse", "--short", "HEAD"),
            "common": commondir.resolve(),
            "tracked_changes": git(root, "diff", "--name-only")}


def untracked(root: Path) -> list[str]:
    p = subprocess.run(["git", "-C", str(root), "ls-files", "--others", "--exclude-standard", "-z"],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode:
        raise RuntimeError(p.stderr.decode(errors="replace"))
    return sorted((os.fsdecode(x) for x in p.stdout.split(b"\0") if x))


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for part in iter(lambda: f.read(1048576), b""):
            digest.update(part)
    return digest.hexdigest()


def ownership(rel: str) -> str:
    rel = rel.replace("\\", "/").lower()
    if rel.startswith(("tools/adaptive_document_reader/",)) or rel.startswith("tests/test_adaptive_") or rel.startswith(("adaptive_", "open_azd_")):
        return "ADAPTIVE_READER"
    if (rel.startswith(("tools/weekly_report/", "tools/weekly_report_family/", "docs/weekly_report/", "docs/wr_"))
            or rel.startswith(("tests/test_wr_", "tests/test_inventory_", "tests/test_triage_", "tests/test_weekly_report_"))
            or rel.startswith(("readme_weekly_report", "wr_inventory_"))
            or rel == "docs/git_worktree_guide.md"):
        return "WEEKLY_REPORT_CANDIDATE"
    return "UNASSIGNED_REVIEW"


def inventory(main: Path, wr: Path):
    entries = []
    for relative in untracked(main):
        left = (main / relative)
        right = (wr / relative)
        kind = ownership(relative)
        if left.is_symlink() or not left.is_file():
            state = "SKIP_LINK_OR_NONFILE"
        elif right.is_symlink():
            state = "DIFFERENT_OR_UNSAFE_TARGET"
        elif not right.exists():
            state = "MAIN_ONLY"
        elif not right.is_file():
            state = "DIFFERENT_OR_UNSAFE_TARGET"
        elif left.stat().st_size != right.stat().st_size:
            state = "DIFFERENT_IN_WR"
        elif sha(left) == sha(right):
            state = "EXACT_DUPLICATE"
        else:
            state = "DIFFERENT_IN_WR"
        entries.append({"relative_path": relative.replace("\\", "/"), "state": state, "group": kind,
                        "size_bytes": left.stat().st_size if left.is_file() else None})
    return entries


def quarantine(main: Path, wr: Path, entries: list[dict]) -> tuple[Path | None, int]:
    # Quarantine only files clearly associated with this WR worktree.
    # Other teams may intentionally maintain a main copy.
    selected = [item for item in entries if item["state"] == "EXACT_DUPLICATE"
                and item["group"] == "WEEKLY_REPORT_CANDIDATE"]
    if not selected:
        return None, 0
    backup = main.parent / ".cleaner_untracked_quarantine" / (dt.datetime.now().strftime("%Y%m%dT%H%M%S_%f"))
    manifest = []
    for item in selected:
        relative = Path(item["relative_path"])
        source = main / relative
        twin = wr / relative
        if source.is_symlink() or twin.is_symlink() or not source.is_file() or not twin.is_file():
            raise RuntimeError(f"File changed or became unsafe during operation: {relative}")
        if sha(source) != sha(twin):
            raise RuntimeError(f"File changed since inventory: {relative}")
        destination = backup / relative
        if destination.exists():
            raise RuntimeError(f"Backup collision: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        # COPY + verify before original untracked copy is removed from main.
        shutil.copy2(source, destination)
        original_hash = sha(source)
        if sha(destination) != original_hash:
            raise RuntimeError(f"Backup verification failed for {relative}; main left unchanged")
        source.unlink()
        manifest.append({"main_relative_path": item["relative_path"], "backup": str(destination),
                         "sha256": original_hash, "duplicate_in_wr": str(twin)})
    (backup / "quarantine_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return backup, len(manifest)


def copy_weekly_candidates(main: Path, wr: Path, entries: list[dict]) -> int:
    selected = [x for x in entries if x["state"] == "MAIN_ONLY" and x["group"] == "WEEKLY_REPORT_CANDIDATE"]
    for item in selected:
        relative = Path(item["relative_path"])
        source = main / relative
        target = wr / relative
        if not source.is_file() or source.is_symlink() or target.exists() or target.is_symlink():
            raise RuntimeError(f"Unsafe or changed file: {relative}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        if sha(source) != sha(target):
            raise RuntimeError(f"Copied bytes differ for {relative}; inspect WR copy")
    return len(selected)


def main_cli() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--main", type=Path, default=Path("../cleaner-functions"))
    p.add_argument("--wr", type=Path, default=Path("."))
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--copy-wr-candidates", action="store_true")
    mode.add_argument("--quarantine-duplicates", action="store_true")
    args = p.parse_args()
    main, wr = args.main.resolve(), args.wr.resolve()
    try:
        if main == wr:
            raise RuntimeError("Main and WR paths must be different Git worktrees")
        a, b = repo_info(main), repo_info(wr)
        if a["common"] != b["common"]:
            raise RuntimeError("These directories do not share the same Git repository")
        if b["branch"] != "feature/wr-family-cleaning":
            raise RuntimeError(f"WR worktree on unexpected branch {b['branch']!r}; operation refused")
        if a["branch"] == b["branch"]:
            raise RuntimeError("Both worktrees claim same branch; operation refused")
        print(f"[MAIN] {main} ({a['branch']} @ {a['head']})")
        print(f"[WR]   {wr} ({b['branch']} @ {b['head']})")
        if a["tracked_changes"]:
            print("[NOTE] Main also has tracked modifications; none will be touched")
        entries = inventory(main, wr)
        categories = {label: sum(x['state'] == label for x in entries) for label in
                      ("EXACT_DUPLICATE", "MAIN_ONLY", "DIFFERENT_IN_WR", "SKIP_LINK_OR_NONFILE", "DIFFERENT_OR_UNSAFE_TARGET")}
        print("[SUMMARY]", ", ".join(f"{k}={v}" for k,v in categories.items()))
        print("[OWNERSHIP]", ", ".join(f"{tag}={sum(x['group']==tag for x in entries)}" for tag in
                                    ("WEEKLY_REPORT_CANDIDATE", "ADAPTIVE_READER", "UNASSIGNED_REVIEW")))
        print("[QUARANTINE ELIGIBLE]", sum(x["state"] == "EXACT_DUPLICATE" and x["group"] == "WEEKLY_REPORT_CANDIDATE" for x in entries))
        for item in entries[:160]:
            print(f"[{item['state']}] {item['group']}: {item['relative_path']}")
        if len(entries) > 160:
            print(f"[TRUNCATED_DISPLAY] {len(entries)-160} more untracked files not displayed")
        if args.check:
            print("[DRY RUN] No files changed. Review MAIN_ONLY / DIFFERENT_IN_WR carefully.")
        elif args.copy_wr_candidates:
            n = copy_weekly_candidates(main, wr, entries)
            print(f"[COPIED TO WR] {n} unique probable WR files; originals remain in main")
            print("[NEXT] Inspect the WR files, run tests, and commit intentionally before cleanup")
        else:
            backup, n = quarantine(main, wr, entries)
            print(f"[QUARANTINED] {n} verified WR duplicate main copies")
            if backup:
                print(f"[RECOVERY DIRECTORY] {backup}")
            print("[RETAINED] All main-only and differing untracked files; no tracked files touched")
        return 0
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        print(f"[STOP] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main_cli())
