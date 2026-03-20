"""Scanner job route handlers (market snapshots and candidates)."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator, Optional

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from api.models import HistoricalMarketSnapshot, MarketSnapshot, SnapshotResponse, SymbolMetrics
from api.store import redis_store
from src.config import MongoConfig
from src.storage import MongoStore

router = APIRouter(tags=["Scanner"])

_HISTORY_WINDOW_HOURS = 48
_HISTORY_CACHE_KEY = "history:market:48h:v1.1"
_HISTORY_CACHE_TTL_SECONDS = 300


def _load_market_history() -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=_HISTORY_WINDOW_HOURS)
    cutoff_ms = int(cutoff.timestamp() * 1000)
    store = MongoStore(MongoConfig())
    return store.find(
        "market_state_snapshots",
        query={"ts_ms": {"$gte": cutoff_ms}, "status": "ok"},
        projection={"_id": 0, "ts": 1, "ts_ms": 1, "market": 1},
        sort=[("ts_ms", -1)],
    )


@router.get(
    "/market",
    summary="Get latest market snapshot",
    description="""
Returns the most recent market snapshot and candidate list in a single HTTP
response. Use this for initial page load or non-streaming clients.

Returns `null` for fields if the scanner has not run yet.
""",
    response_model=SnapshotResponse,
    response_description="Latest market state and candidates",
)
async def snapshot_latest() -> SnapshotResponse:
    market_state = await redis_store.get_json("market_state:latest")
    candidates = await redis_store.get_json("market_state:candidates:latest")
    return SnapshotResponse(market_state=market_state, candidates=candidates)


@router.get(
    "/market/history",
    summary="Get market history for the last 48 hours",
    description="""
Returns compact market snapshots from the last 48 hours, newest first.

Only successful snapshots (`status = "ok"`) are included. Each item contains
only `ts`, `ts_ms`, and `market`.
""",
    response_model=list[HistoricalMarketSnapshot],
    response_description="Compact market snapshots from the last 48 hours",
)
async def market_history() -> list[HistoricalMarketSnapshot]:
    cached = await redis_store.get_json(_HISTORY_CACHE_KEY)
    if cached is not None:
        return [HistoricalMarketSnapshot.model_validate(item) for item in cached]

    history = await asyncio.to_thread(_load_market_history)
    await redis_store.set_json(_HISTORY_CACHE_KEY, history, ex=_HISTORY_CACHE_TTL_SECONDS)
    return [HistoricalMarketSnapshot.model_validate(item) for item in history]


def format_sse(payload: Optional[object]) -> str:
    if payload is None:
        return ""
    data = json.dumps(payload, separators=(",", ":"))
    return f"data: {data}\n\n"


_KEEPALIVE_INTERVAL = 30  # seconds between SSE keepalive pings


async def stream_key(key: str) -> AsyncGenerator[str, None]:
    q = await redis_store.subscribe("market_state:events")
    try:
        latest = await redis_store.get_json(key)
        if latest is not None:
            yield format_sse(latest)

        while True:
            try:
                await asyncio.wait_for(q.get(), timeout=_KEEPALIVE_INTERVAL)
            except asyncio.TimeoutError:
                yield 'data: {"type":"keepalive"}\n\n'  # refreshes client stale clock
                continue
            # Got a notification — re-fetch value from Redis
            latest = await redis_store.get_json(key)
            if latest is not None:
                yield format_sse(latest)
            await asyncio.sleep(0)
    except asyncio.CancelledError:
        raise
    finally:
        await redis_store.unsubscribe("market_state:events", q)


@router.get(
    "/market/stream",
    summary="Stream full market snapshots",
    description="""
Server-Sent Events stream that emits a new **MarketSnapshot** JSON payload
every time the scanner job completes a cycle.

The first event is the latest cached snapshot (if available), so clients
receive data immediately on connect without waiting for the next scan.

Each SSE frame is a single `data: <json>\\n\\n` line.
""",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": "Continuous SSE stream. Each frame: `data: <MarketSnapshot JSON>\\n\\n`.",
            "content": {
                "text/event-stream": {
                    "schema": MarketSnapshot.model_json_schema(),
                }
            },
        }
    },
)
async def sse_market() -> StreamingResponse:
    return StreamingResponse(
        stream_key("market_state:latest"),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.get(
    "/candidates/stream",
    summary="Stream top candidate symbols",
    description="""
Server-Sent Events stream that emits the updated **top-K candidate list**
every time the scanner job completes.

Candidates are ranked by `attractiveness_score` (composite of trend, liquidity,
alignment with BTC, volatility band, and volume).

Each SSE frame is a single `data: <json>\\n\\n` line where the payload is a
`List[SymbolMetrics]`.
""",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": "Continuous SSE stream. Each frame: `data: <List[SymbolMetrics] JSON>\\n\\n`.",
            "content": {
                "text/event-stream": {
                    "schema": {
                        "type": "array",
                        "items": SymbolMetrics.model_json_schema(),
                    },
                }
            },
        }
    },
)
async def sse_candidates() -> StreamingResponse:
    return StreamingResponse(
        stream_key("market_state:candidates:latest"),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
