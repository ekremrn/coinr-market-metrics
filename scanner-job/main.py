"""Worker entrypoint for run-once market scan."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

from src.binance_client import BinanceDataFetcher
from src.config import AppConfig, MongoConfig, RedisConfig
from src.logging import Logger, get_logger
from src.metrics import (
    build_market_metrics,
    build_symbol_features,
    build_symbol_metrics,
    select_candidates,
    stabilize_market_bias,
)
from src.storage import MongoStore, RedisStore
from src.utils import utc_now_iso, utc_now_ms


# Kline fetch intervals and limits
KLINE_INTERVAL_5M = "5m"
KLINE_INTERVAL_15M = "15m"
KLINE_INTERVAL_1H = "1h"
KLINE_LIMIT_5M = 15   # 12 closed + 3 buffer — matches CoinR analysis 12-bar range window
KLINE_LIMIT_15M = 120  # 30 hours of 15m candles
KLINE_LIMIT_1H = 48  # 48 hours of 1h candles


class ErrorRecord(NamedTuple):
    """Structure for tracking errors during execution."""

    type: str
    detail: Optional[str] = None
    symbol: Optional[str] = None
    interval: Optional[str] = None


class MarketData(NamedTuple):
    """Container for all fetched market data."""

    universe_symbols: List[str]
    volume_ranked: List[Dict[str, Any]]
    blacklist: List[str]
    book_map: Dict[str, Any]
    funding_map: Dict[str, float]
    klines_15m: Dict[str, Any]
    klines_1h: Dict[str, Any]
    klines_5m: Dict[str, Any]
    errors: List[Dict[str, str]]


def record_error(
    error_type: str,
    detail: Optional[str] = None,
    symbol: Optional[str] = None,
    interval: Optional[str] = None,
) -> Dict[str, str]:
    """Create a standardized error record."""
    error_dict = {"type": error_type}
    if detail:
        error_dict["detail"] = detail
    if symbol:
        error_dict["symbol"] = symbol
    if interval:
        error_dict["interval"] = interval
    return error_dict


async def fetch_klines_for_symbols(
    fetcher: BinanceDataFetcher,
    symbols: List[str],
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], List[Dict[str, str]]]:
    """Fetch klines for all symbols in parallel (5m, 15m, 1h)."""
    errors: List[Dict[str, str]] = []
    klines_5m: Dict[str, Any] = {}
    klines_15m: Dict[str, Any] = {}
    klines_1h: Dict[str, Any] = {}

    async def fetch_one(symbol: str, interval: str, limit: int):
        data = await fetcher.get_klines(symbol, interval, limit)
        return symbol, interval, data

    tasks = []
    for symbol in symbols:
        tasks.append(fetch_one(symbol, KLINE_INTERVAL_5M, KLINE_LIMIT_5M))
        tasks.append(fetch_one(symbol, KLINE_INTERVAL_15M, KLINE_LIMIT_15M))
        tasks.append(fetch_one(symbol, KLINE_INTERVAL_1H, KLINE_LIMIT_1H))

    for coro in asyncio.as_completed(tasks):
        symbol, interval, data = await coro
        if not data:
            errors.append(record_error("missing_klines", symbol=symbol, interval=interval))
            continue
        if interval == KLINE_INTERVAL_5M:
            klines_5m[symbol] = data
        elif interval == KLINE_INTERVAL_15M:
            klines_15m[symbol] = data
        else:
            klines_1h[symbol] = data

    return klines_5m, klines_15m, klines_1h, errors


async def fetch_universe(
    fetcher: BinanceDataFetcher,
    app_cfg: AppConfig,
) -> Tuple[List[str], List[Dict[str, Any]], List[str], List[Dict[str, str]]]:
    """Fetch and select tradeable universe of symbols."""
    errors: List[Dict[str, str]] = []
    try:
        universe_symbols, volume_ranked, blacklist = await fetcher.select_universe(
            app_cfg.top_n,
            list(app_cfg.blacklist),
            min_quote_volume=app_cfg.min_quote_volume,
            max_spread_bps=app_cfg.max_spread_bps,
        )
        if not universe_symbols:
            errors.append(record_error("universe_empty"))
        return universe_symbols, volume_ranked, blacklist, errors
    except Exception as exc:  # noqa: BLE001
        errors.append(record_error("universe_error", detail=str(exc)))
        return [], [], [], errors


async def fetch_book_tickers(
    fetcher: BinanceDataFetcher,
) -> Tuple[Dict[str, Any], List[Dict[str, str]]]:
    """Fetch orderbook ticker data for all symbols."""
    errors: List[Dict[str, str]] = []
    try:
        book_tickers = await fetcher.get_book_tickers() or []
        book_map = {item.get("symbol"): item for item in book_tickers if item.get("symbol")}
        return book_map, errors
    except Exception as exc:  # noqa: BLE001
        errors.append(record_error("book_ticker_error", detail=str(exc)))
        return {}, errors


async def fetch_funding_rates(
    fetcher: BinanceDataFetcher,
) -> Tuple[Dict[str, float], List[Dict[str, str]]]:
    """Fetch funding rate data for all symbols."""
    errors: List[Dict[str, str]] = []
    funding_map: Dict[str, float] = {}
    try:
        premium_index = await fetcher.get_premium_index() or []
        for item in premium_index:
            symbol = item.get("symbol")
            if not symbol:
                continue
            rate = item.get("lastFundingRate")
            if rate is None:
                continue
            try:
                funding_map[symbol] = float(rate)
            except (TypeError, ValueError):
                continue
        return funding_map, errors
    except Exception as exc:  # noqa: BLE001
        errors.append(record_error("funding_rate_error", detail=str(exc)))
        return {}, errors


async def fetch_all_market_data(
    fetcher: BinanceDataFetcher,
    app_cfg: AppConfig,
) -> MarketData:
    """Fetch all required market data from Binance."""
    universe_symbols, volume_ranked, blacklist, errors = await fetch_universe(fetcher, app_cfg)

    # Always include BTCUSDT for market metrics
    calc_symbols = sorted({*universe_symbols, "BTCUSDT"})

    # Fetch book tickers, funding rates, and klines in parallel
    book_result, funding_result, klines_result = await asyncio.gather(
        fetch_book_tickers(fetcher),
        fetch_funding_rates(fetcher),
        fetch_klines_for_symbols(fetcher, calc_symbols),
    )

    book_map, book_errors = book_result
    funding_map, funding_errors = funding_result
    klines_5m, klines_15m, klines_1h, kline_errors = klines_result

    all_errors = errors + book_errors + funding_errors + kline_errors

    return MarketData(
        universe_symbols=universe_symbols,
        volume_ranked=volume_ranked,
        blacklist=blacklist,
        book_map=book_map,
        funding_map=funding_map,
        klines_15m=klines_15m,
        klines_1h=klines_1h,
        klines_5m=klines_5m,
        errors=all_errors,
    )


def compute_features_and_metrics(
    market_data: MarketData,
    calc_symbols: List[str],
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Compute features and metrics from raw market data."""
    # Build features for all symbols
    features: List[Dict[str, Any]] = []
    for symbol in calc_symbols:
        feature = build_symbol_features(
            symbol,
            market_data.klines_15m.get(symbol),
            market_data.klines_1h.get(symbol),
            market_data.book_map.get(symbol),
            market_data.funding_map.get(symbol),
            klines_5m=market_data.klines_5m.get(symbol),
        )
        features.append(feature)

    # Build market-level metrics
    market, btc_direction = build_market_metrics(features)
    feature_map = {feature["symbol"]: feature for feature in features}
    btc_feature = feature_map.get("BTCUSDT")

    # Build symbol-level metrics for universe symbols only
    symbol_metrics: List[Dict[str, Any]] = []
    for feature in features:
        if feature.get("symbol") not in market_data.universe_symbols:
            continue
        symbol_metrics.append(build_symbol_metrics(feature, btc_direction, btc_feature))

    return market, symbol_metrics, features


def build_snapshot(
    market_data: MarketData,
    market: Dict[str, Any],
    symbol_metrics: List[Dict[str, Any]],
    candidates: List[Dict[str, Any]],
    app_cfg: AppConfig,
    ts: str,
    ts_ms: int,
) -> Dict[str, Any]:
    """Build the complete market state snapshot."""
    status = "ok" if not market_data.errors else "partial"

    return {
        "ts": ts,
        "ts_ms": ts_ms,
        "version": app_cfg.metrics_version,
        "status": status,
        "errors": market_data.errors,
        "universe": {
            "top_n": app_cfg.top_n,
            "candidates_k": app_cfg.candidates_k,
            "blacklist": market_data.blacklist,
            "symbols": market_data.universe_symbols,
            "calc_symbols": sorted({*market_data.universe_symbols, "BTCUSDT"}),
            "volume_ranked": market_data.volume_ranked,
            "total_symbols": len(market_data.universe_symbols),
        },
        "market": market,
        "symbols": symbol_metrics,
        "candidates": candidates,
    }


async def store_snapshot(
    snapshot: Dict[str, Any],
    symbol_metrics: List[Dict[str, Any]],
    candidates: List[Dict[str, Any]],
    app_cfg: AppConfig,
    logger: Logger,
) -> Dict[str, Any]:
    """Store snapshot to Redis and MongoDB."""
    # Store to Redis
    redis_store = RedisStore(RedisConfig())
    redis_store.set_json("market_state:latest", snapshot)
    redis_store.set_json("market_state:symbols:latest", symbol_metrics)
    redis_store.set_json("market_state:candidates:latest", candidates)
    redis_store.publish(
        "market_state:events",
        {"ts": snapshot["ts"], "version": app_cfg.metrics_version},
    )

    # Store to MongoDB
    try:
        mongo_store = MongoStore(MongoConfig())
        mongo_doc = {
            "ts": snapshot["ts"],
            "ts_ms": snapshot["ts_ms"],
            "version": app_cfg.metrics_version,
            "status": snapshot["status"],
            "errors": snapshot["errors"],
            "universe": snapshot["universe"],
            "market": snapshot["market"],
            "candidates": candidates,
        }
        if app_cfg.include_symbols_in_mongo:
            mongo_doc["symbols"] = symbol_metrics
        mongo_store.insert_snapshot(mongo_doc)
    except Exception as exc:  # noqa: BLE001
        logger.error("Mongo insert failed", exc_info=True, context=None)
        snapshot["errors"].append(record_error("mongo_error", detail=str(exc)))
        snapshot["status"] = "partial"

    return snapshot


def load_recent_market_history(limit: int = 5) -> List[Dict[str, Any]]:
    """Load recent successful market snapshots for bias smoothing."""
    mongo_store = MongoStore(MongoConfig())
    history = mongo_store.find(
        "market_state_snapshots",
        query={"status": "ok"},
        projection={"_id": 0, "market": 1, "ts_ms": 1},
        sort=[("ts_ms", -1)],
        limit=limit,
    )
    history.reverse()
    return [dict(item.get("market") or {}) for item in history]


async def run_once() -> Dict[str, Any]:
    """Main entry point for market scan."""
    logger = get_logger("market-metrics-worker")
    app_cfg = AppConfig()

    ts = utc_now_iso()
    ts_ms = utc_now_ms()

    # Initialize data fetcher
    fetcher = BinanceDataFetcher(logger)

    # Fetch all market data
    market_data = await fetch_all_market_data(fetcher, app_cfg)

    # Compute features and metrics
    calc_symbols = sorted({*market_data.universe_symbols, "BTCUSDT"})
    market, symbol_metrics, _ = compute_features_and_metrics(market_data, calc_symbols)
    try:
        history_markets = await asyncio.to_thread(load_recent_market_history, 5)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Recent market history unavailable, skipping smoothing: {exc}")
        history_markets = []
    market = stabilize_market_bias(market, history_markets)

    # Select top candidates
    candidates = select_candidates(symbol_metrics, app_cfg.candidates_k)

    # Build snapshot
    snapshot = build_snapshot(
        market_data,
        market,
        symbol_metrics,
        candidates,
        app_cfg,
        ts,
        ts_ms,
    )

    # Store to Redis and MongoDB
    snapshot = await store_snapshot(snapshot, symbol_metrics, candidates, app_cfg, logger)

    logger.info("Snapshot complete")
    return snapshot


def main() -> None:
    asyncio.run(run_once())


if __name__ == "__main__":
    main()
