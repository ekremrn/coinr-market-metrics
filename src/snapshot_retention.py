"""Dry-run-first retention cleanup for compact market snapshots."""

from __future__ import annotations

import argparse
import json
import time
from typing import Any

from pymongo import MongoClient

from src.config import MongoConfig

COLLECTION = "market_state_snapshots"
CONFIRM_TOKEN = "APPLY_RETENTION"


def cutoff_ts_ms(*, now_ts: float, retention_days: int) -> int:
    if retention_days < 1:
        raise ValueError("retention_days must be at least 1")
    return int((now_ts - retention_days * 86_400) * 1_000)


def delete_expired_snapshots(
    collection: Any,
    *,
    cutoff_ms: int,
    batch_size: int,
) -> tuple[int, int]:
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")

    deleted = 0
    batches = 0
    while True:
        ids = [
            row["_id"]
            for row in collection.find(
                {"ts_ms": {"$lt": cutoff_ms}},
                {"_id": 1},
            )
            .sort("ts_ms", 1)
            .limit(batch_size)
        ]
        if not ids:
            break
        result = collection.delete_many(
            {"_id": {"$in": ids}, "ts_ms": {"$lt": cutoff_ms}}
        )
        deleted += result.deleted_count
        batches += 1
    return deleted, batches


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()

    cutoff_ms = cutoff_ts_ms(now_ts=time.time(), retention_days=args.days)
    config = MongoConfig()
    collection = MongoClient(config.uri)[config.database][COLLECTION]
    output = {
        "mode": "dry_run",
        "collection": COLLECTION,
        "retention_days": args.days,
        "batch_size": args.batch_size,
        "cutoff_ts_ms": cutoff_ms,
        "expired_count": collection.count_documents({"ts_ms": {"$lt": cutoff_ms}}),
    }

    if args.apply:
        if args.confirm != CONFIRM_TOKEN:
            raise SystemExit(f"--apply requires --confirm {CONFIRM_TOKEN}")
        deleted, batches = delete_expired_snapshots(
            collection,
            cutoff_ms=cutoff_ms,
            batch_size=args.batch_size,
        )
        output.update(mode="apply", deleted_count=deleted, batches=batches)

    print(json.dumps(output, indent=2, default=str))


if __name__ == "__main__":
    main()
