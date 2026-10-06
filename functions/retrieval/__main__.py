from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from functions.retrieval import (
    load_retrieval_config,
    retrieve_project_set,
    write_retrieval_manifest,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Retrieve configured Project Control source documents.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--family", action="append", default=[])
    parser.add_argument("--destination", default=None)
    parser.add_argument("--retrieval-date", default=None)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--manifest", default=None)
    args = parser.parse_args()

    config = load_retrieval_config(args.config)
    results = retrieve_project_set(
        config,
        project_id=args.project,
        families=args.family or None,
        destination=args.destination,
        retrieval_date=args.retrieval_date,
        overwrite=args.overwrite,
    )
    manifest = Path(args.manifest) if args.manifest else Path(args.destination or config.get("retrieval_workspace") or "./input") / "retrieval_manifest.json"
    write_retrieval_manifest(results, manifest)
    for item in results:
        print(
            f"[RETRIEVAL] {item.project_id} {item.family}: "
            f"{item.source_path} -> {item.retrieved_path} "
            f"({item.metadata.get('copy_action')})"
        )
    print(f"[RETRIEVAL] Manifest: {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
