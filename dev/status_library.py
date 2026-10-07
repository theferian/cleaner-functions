from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cleaner_core.status_library import (  # noqa: E402
    default_status_library_path,
    load_status_library,
    save_status_library,
    upsert_status,
)


def _yn(value: str | None) -> bool | None:
    if value is None:
        return None
    token = value.strip().lower()
    if token in {"yes", "y", "true", "1"}:
        return True
    if token in {"no", "n", "false", "0"}:
        return False
    raise argparse.ArgumentTypeError("expected yes/no")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Inspect and maintain the reusable engineering status library.")
    parser.add_argument("--library", default=str(default_status_library_path()))
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="List known canonical status codes and meanings.")

    show = sub.add_parser("show", help="Show one status definition (aliases accepted).")
    show.add_argument("code")

    add = sub.add_parser("add", help="Add or update one canonical status definition.")
    add.add_argument("code")
    add.add_argument("--alias", action="append", default=[])
    add.add_argument("--meaning")
    add.add_argument("--meaning-fa")
    add.add_argument("--responsibility", choices=["COMPANY", "CONSULTANT", "NONE"])
    add.add_argument("--action-required", type=_yn)
    add.add_argument("--notes")
    add.add_argument("--source", default="user-maintained")

    args = parser.parse_args(argv)
    library = load_status_library(args.library)

    if args.command == "list":
        print(f"Library: {Path(args.library)}")
        if not library.statuses:
            print("(empty)")
            return 0
        for code in library.known_codes:
            item = library.statuses[code]
            meaning = item.meaning or item.meaning_fa or "<meaning not defined>"
            resp = item.responsibility_after_receive or "<workflow not defined>"
            aliases = f" aliases={list(item.aliases)}" if item.aliases else ""
            print(f"{code:<10} {meaning} | after receive: {resp}{aliases}")
        return 0

    if args.command == "show":
        item = library.definition(args.code)
        if item is None:
            print(f"Unknown status: {args.code}")
            return 2
        for key, value in item.to_dict().items():
            print(f"{key:<30}: {value}")
        return 0

    upsert_status(
        library,
        code=args.code,
        aliases=args.alias,
        meaning=args.meaning,
        meaning_fa=args.meaning_fa,
        responsibility_after_receive=args.responsibility,
        action_required=args.action_required,
        notes=args.notes,
        source=args.source,
    )
    target = save_status_library(library, args.library)
    print(f"Saved: {target}")
    item = library.definition(args.code)
    print(f"Status: {item.code} | meaning={item.meaning!r} | responsibility={item.responsibility_after_receive!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
