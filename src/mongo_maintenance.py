"""Dry-run-first Mongo index maintenance for market snapshot archives."""

from __future__ import annotations

import argparse
import json

from pymongo import MongoClient

from src.config import MongoConfig
from src.snapshot_archive import snapshot_index_specs

COLLECTION = "market_state_snapshots"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply-indexes", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()

    output = {"mode": "dry_run", "collection": COLLECTION, "indexes": snapshot_index_specs()}
    if not args.apply_indexes:
        print(json.dumps(output, indent=2, default=str))
        return
    if args.confirm != "APPLY_INDEXES":
        raise SystemExit("--apply-indexes requires --confirm APPLY_INDEXES")

    config = MongoConfig()
    collection = MongoClient(config.uri)[config.database][COLLECTION]
    output["mode"] = "apply_indexes"
    output["applied_indexes"] = [
        collection.create_index(spec["keys"], name=spec["name"])
        for spec in snapshot_index_specs()
    ]
    print(json.dumps(output, indent=2, default=str))


if __name__ == "__main__":
    main()
