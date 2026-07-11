"""Mongo archive shape for reproducible full-universe scanner replay."""

from __future__ import annotations

from typing import Any, Dict, List

REPLAY_SCHEMA_VERSION = "full_universe_v1"


def build_mongo_snapshot_document(
    snapshot: Dict[str, Any],
    symbol_metrics: List[Dict[str, Any]],
    candidates: List[Dict[str, Any]],
    *,
    include_symbols: bool,
) -> Dict[str, Any]:
    """Build the additive historical archive document used by CoinR replay."""

    universe = dict(snapshot.get("universe") or {})
    universe_symbols = list(universe.get("symbols") or [])
    document: Dict[str, Any] = {
        "ts": snapshot["ts"],
        "ts_ms": snapshot["ts_ms"],
        "version": snapshot.get("version"),
        "status": snapshot["status"],
        "errors": list(snapshot.get("errors") or []),
        "universe": universe,
        "market": dict(snapshot.get("market") or {}),
        "candidates": list(candidates),
        "replay_archive": {
            "schema_version": REPLAY_SCHEMA_VERSION,
            "full_symbols_included": bool(include_symbols),
            "symbol_count": len(symbol_metrics) if include_symbols else 0,
            "universe_symbol_count": len(universe_symbols),
            "is_complete_universe": bool(include_symbols)
            and {str(row.get("symbol")) for row in symbol_metrics if row.get("symbol")}
            == {str(symbol) for symbol in universe_symbols},
        },
    }
    if include_symbols:
        document["symbols"] = list(symbol_metrics)
    return document


def snapshot_index_specs() -> list[dict[str, Any]]:
    """Return index declarations; applying them is an explicit ops action."""

    return [
        {"keys": [("ts_ms", -1)], "name": "market_snapshots_ts_ms_desc"},
        {"keys": [("status", 1), ("ts_ms", -1)], "name": "market_snapshots_status_ts"},
        {
            "keys": [("replay_archive.full_symbols_included", 1), ("ts_ms", -1)],
            "name": "market_snapshots_replay_coverage",
        },
    ]
