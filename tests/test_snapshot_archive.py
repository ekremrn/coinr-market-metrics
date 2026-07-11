from src.mongo_maintenance import COLLECTION
from src.snapshot_archive import build_mongo_snapshot_document, snapshot_index_specs


def snapshot():
    return {
        "ts": "2026-07-11T10:00:00+00:00",
        "ts_ms": 1783764000000,
        "version": "v1.3",
        "status": "ok",
        "errors": [],
        "universe": {"symbols": ["BTCUSDT", "ETHUSDT"]},
        "market": {"market_regime": "TRENDING"},
    }


def symbols():
    return [
        {"symbol": "BTCUSDT", "long_score": 0.7},
        {"symbol": "ETHUSDT", "long_score": 0.6},
    ]


def test_full_archive_is_additive_and_marks_complete_universe():
    document = build_mongo_snapshot_document(
        snapshot(),
        symbols(),
        [{"symbol": "BTCUSDT"}],
        include_symbols=True,
    )

    assert document["symbols"] == symbols()
    assert document["candidates"] == [{"symbol": "BTCUSDT"}]
    assert document["replay_archive"]["full_symbols_included"] is True
    assert document["replay_archive"]["is_complete_universe"] is True


def test_compact_archive_keeps_legacy_shape_and_explicit_coverage_flag():
    document = build_mongo_snapshot_document(
        snapshot(),
        symbols(),
        [{"symbol": "BTCUSDT"}],
        include_symbols=False,
    )

    assert "symbols" not in document
    assert document["replay_archive"]["full_symbols_included"] is False
    assert document["replay_archive"]["symbol_count"] == 0


def test_index_plan_is_declarative_and_not_applied_during_import():
    specs = snapshot_index_specs()
    assert {spec["name"] for spec in specs} == {
        "market_snapshots_ts_ms_desc",
        "market_snapshots_status_ts",
        "market_snapshots_replay_coverage",
    }
    assert COLLECTION == "market_state_snapshots"
