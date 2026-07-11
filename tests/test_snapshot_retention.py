from dataclasses import dataclass

import pytest

from src.snapshot_retention import cutoff_ts_ms, delete_expired_snapshots


@dataclass
class DeleteResult:
    deleted_count: int


class Cursor:
    def __init__(self, rows):
        self.rows = rows

    def sort(self, *_args):
        return self

    def limit(self, limit):
        return self.rows[:limit]


class Collection:
    def __init__(self, ids):
        self.ids = list(ids)

    def find(self, *_args):
        return Cursor([{"_id": value} for value in self.ids])

    def delete_many(self, query):
        selected = query["_id"]["$in"]
        self.ids = [value for value in self.ids if value not in selected]
        return DeleteResult(len(selected))


def test_cutoff_requires_positive_retention() -> None:
    with pytest.raises(ValueError):
        cutoff_ts_ms(now_ts=1_000, retention_days=0)


def test_cutoff_uses_whole_days() -> None:
    assert cutoff_ts_ms(now_ts=10 * 86_400, retention_days=7) == 3 * 86_400 * 1_000


def test_delete_expired_snapshots_uses_bounded_batches() -> None:
    collection = Collection(range(12))

    deleted, batches = delete_expired_snapshots(
        collection,
        cutoff_ms=123,
        batch_size=5,
    )

    assert deleted == 12
    assert batches == 3
    assert collection.ids == []
