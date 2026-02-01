"""Worker entrypoint for run-once market scan."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Tuple

from src.binance_client import BinanceDataFetcher
from src.config import AppConfig, BinanceConfig, MongoConfig, RedisConfig
from src.logging import get_logger
from src.metrics import (
    build_market_metrics,
    build_symbol_features,
    build_symbol_metrics,
    select_candidates,
)
from src.storage import MongoStore, RedisStore
from src.utils import utc_now_iso, utc_now_ms


async def fetch_klines_for_symbols(
    fetcher: BinanceDataFetcher,
    symbols: List[str],
) -> Tuple[Dict[str, Any], Dict[str, Any], List[Dict[str, str]]]:
    errors: List[Dict[str, str]] = []
    klines_15m: Dict[str, Any] = {}
    klines_1h: Dict[str, Any] = {}

    async def fetch_one(symbol: str, interval: str, limit: int):
        data = await fetcher.get_klines(symbol, interval, limit)
        return symbol, interval, data

    tasks = []
    for symbol in symbols:
        tasks.append(fetch_one(symbol, "15m", 120))
        tasks.append(fetch_one(symbol, "1h", 48))

    for coro in asyncio.as_completed(tasks):
        symbol, interval, data = await coro
        if not data:
            errors.append({"type": "missing_klines", "symbol": symbol, "interval": interval})
            continue
        if interval == "15m":
            klines_15m[symbol] = data
        else:
            klines_1h[symbol] = data

    return klines_15m, klines_1h, errors


async def run_once() -> Dict[str, Any]:
    logger = get_logger("market-metrics-worker")
    app_cfg = AppConfig()
    binance_cfg = BinanceConfig()

    errors: List[Dict[str, str]] = []
    ts = utc_now_iso()
    ts_ms = utc_now_ms()

    fetcher = BinanceDataFetcher(binance_cfg, logger)

    universe_symbols: List[str] = []
    volume_ranked: List[Dict[str, Any]] = []
    blacklist: List[str] = []

    try:
        universe_symbols, volume_ranked, blacklist = await fetcher.select_universe(
            app_cfg.top_n,
            list(app_cfg.blacklist),
        )
    except Exception as exc:  # noqa: BLE001
        errors.append({"type": "universe_error", "detail": str(exc)})

    if not universe_symbols:
        errors.append({"type": "universe_empty"})

    calc_symbols = sorted({*universe_symbols, "BTCUSDT"})

    book_map: Dict[str, Any] = {}
    try:
        book_tickers = await fetcher.get_book_tickers() or []
        book_map = {item.get("symbol"): item for item in book_tickers if item.get("symbol")}
    except Exception as exc:  # noqa: BLE001
        errors.append({"type": "book_ticker_error", "detail": str(exc)})

    klines_15m, klines_1h, kline_errors = await fetch_klines_for_symbols(fetcher, calc_symbols)
    errors.extend(kline_errors)

    features: List[Dict[str, Any]] = []
    for symbol in calc_symbols:
        feature = build_symbol_features(
            symbol,
            klines_15m.get(symbol),
            klines_1h.get(symbol),
            book_map.get(symbol),
        )
        features.append(feature)

    market, btc_direction = build_market_metrics(features)

    symbol_metrics: List[Dict[str, Any]] = []
    for feature in features:
        if feature.get("symbol") not in universe_symbols:
            continue
        symbol_metrics.append(build_symbol_metrics(feature, btc_direction))

    candidates = select_candidates(symbol_metrics, app_cfg.candidates_k)

    status = "ok" if not errors else "partial"

    snapshot = {
        "ts": ts,
        "ts_ms": ts_ms,
        "version": app_cfg.metrics_version,
        "status": status,
        "errors": errors,
        "universe": {
            "top_n": app_cfg.top_n,
            "candidates_k": app_cfg.candidates_k,
            "blacklist": blacklist,
            "symbols": universe_symbols,
            "calc_symbols": calc_symbols,
            "volume_ranked": volume_ranked,
            "total_symbols": len(universe_symbols),
        },
        "market": market,
        "symbols": symbol_metrics,
        "candidates": candidates,
    }

    redis_store = RedisStore(RedisConfig())
    redis_store.set_json("market_state:latest", snapshot)
    redis_store.set_json("market_state:symbols:latest", symbol_metrics)
    redis_store.set_json("market_state:candidates:latest", candidates)
    redis_store.publish("market_state:events", {"ts": ts, "version": app_cfg.metrics_version})

    try:
        mongo_store = MongoStore(MongoConfig())
        mongo_doc = {
            "ts": ts,
            "ts_ms": ts_ms,
            "version": app_cfg.metrics_version,
            "status": status,
            "errors": errors,
            "universe": snapshot["universe"],
            "market": market,
            "candidates": candidates,
        }
        if app_cfg.include_symbols_in_mongo:
            mongo_doc["symbols"] = symbol_metrics
        mongo_store.insert_snapshot(mongo_doc)
    except Exception as exc:  # noqa: BLE001
        logger.error("Mongo insert failed", exc_info=True, context=None)
        snapshot["errors"].append({"type": "mongo_error", "detail": str(exc)})
        snapshot["status"] = "partial"

    logger.info("Snapshot complete")
    return snapshot


def main() -> None:
    asyncio.run(run_once())


if __name__ == "__main__":
    main()
