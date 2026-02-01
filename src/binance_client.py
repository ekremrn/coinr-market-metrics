"""Binance Futures data fetcher with basic rate limiting and retries."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional, Tuple

from binance_futures_python import BinanceFuturesClient, BinanceFuturesAPIError

from src.config import BinanceConfig
from src.logging import Logger, LogContext


class RateLimiter:
    """Simple async rate limiter enforcing a minimum interval between calls."""

    def __init__(self, min_interval: float = 0.12) -> None:
        self._min_interval = min_interval
        self._lock = asyncio.Lock()
        self._last_call = 0.0

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            wait_time = self._min_interval - (now - self._last_call)
            if wait_time > 0:
                await asyncio.sleep(wait_time)
            self._last_call = time.monotonic()


class BinanceDataFetcher:
    """Async wrapper for Binance Futures REST calls."""

    def __init__(
        self,
        config: BinanceConfig,
        logger: Logger,
        max_concurrency: int = 6,
        min_interval: float = 0.12,
        max_retries: int = 3,
    ) -> None:
        self._client = BinanceFuturesClient(
            api_key=config.api_key,
            api_secret=config.api_secret,
            use_testnet=config.use_testnet,
        )
        self._logger = logger
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._rate_limiter = RateLimiter(min_interval=min_interval)
        self._max_retries = max_retries

    async def _call(self, fn, *args, **kwargs) -> Any:
        backoff = 0.6
        for attempt in range(1, self._max_retries + 1):
            try:
                await self._rate_limiter.wait()
                async with self._semaphore:
                    return await asyncio.to_thread(fn, *args, **kwargs)
            except BinanceFuturesAPIError as exc:
                status = getattr(exc, "status_code", None)
                if status in (418, 429, 500, 502, 503, 504):
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 6)
                    continue
                self._logger.error(
                    "Binance API error",
                    context=LogContext(extra={"status": status, "attempt": attempt}),
                )
                return None
            except Exception as exc:  # noqa: BLE001
                self._logger.error(
                    "Binance request failed",
                    context=LogContext(extra={"attempt": attempt, "error": str(exc)}),
                    exc_info=True,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 6)
        return None

    async def get_exchange_info(self) -> Optional[Dict[str, Any]]:
        return await self._call(self._client.get_exchange_info)

    async def get_24h_tickers(self) -> Optional[List[Dict[str, Any]]]:
        data = await self._call(self._client.get_24h_ticker)
        if isinstance(data, dict):
            return [data]
        return data

    async def get_book_tickers(self) -> Optional[List[Dict[str, Any]]]:
        data = await self._call(self._client.get_book_ticker)
        if isinstance(data, dict):
            return [data]
        return data

    async def get_klines(
        self,
        symbol: str,
        interval: str,
        limit: int,
    ) -> Optional[List[List[Any]]]:
        return await self._call(
            self._client.get_klines,
            symbol=symbol,
            interval=interval,
            limit=limit,
        )

    async def select_universe(
        self,
        top_n: int,
        blacklist: List[str],
    ) -> Tuple[List[str], List[Dict[str, Any]], List[str]]:
        exchange_info = await self.get_exchange_info()
        if not exchange_info:
            return [], [], []

        symbols_info = exchange_info.get("symbols", [])
        eligible = {
            item.get("symbol")
            for item in symbols_info
            if item.get("quoteAsset") == "USDT"
            and item.get("contractType") == "PERPETUAL"
            and item.get("status") == "TRADING"
        }

        tickers = await self.get_24h_tickers()
        if not tickers:
            return [], [], []

        ranked: List[Tuple[str, float]] = []
        for ticker in tickers:
            symbol = ticker.get("symbol")
            if symbol not in eligible:
                continue
            try:
                quote_volume = float(ticker.get("quoteVolume", 0.0))
            except (TypeError, ValueError):
                quote_volume = 0.0
            ranked.append((symbol, quote_volume))

        ranked.sort(key=lambda item: item[1], reverse=True)
        blacklist_set = {item.upper() for item in blacklist}
        filtered = [(sym, qv) for sym, qv in ranked if sym not in blacklist_set]
        universe = [sym for sym, _ in filtered][:top_n]
        volume_ranked = [
            {"symbol": sym, "quote_volume": qv}
            for sym, qv in filtered[: max(top_n, len(universe))]
        ]

        return universe, volume_ranked, list(blacklist_set)
