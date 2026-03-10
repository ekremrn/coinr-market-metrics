"""SSE route handlers."""

from __future__ import annotations

import asyncio
import json
from typing import AsyncGenerator, List, Optional

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from api.models import MarketSnapshot, SymbolMetrics
from api.store import redis_store

router = APIRouter(tags=["SSE"])


def format_sse(payload: Optional[object]) -> str:
    if payload is None:
        return ""
    data = json.dumps(payload, separators=(",", ":"))
    return f"data: {data}\n\n"


async def stream_key(key: str) -> AsyncGenerator[str, None]:
    pubsub = redis_store.pubsub()
    await pubsub.subscribe("market_state:events")

    try:
        latest = await redis_store.get_json(key)
        if latest is not None:
            yield format_sse(latest)

        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            latest = await redis_store.get_json(key)
            if latest is not None:
                yield format_sse(latest)
            await asyncio.sleep(0)
    except asyncio.CancelledError:
        raise
    finally:
        await pubsub.unsubscribe("market_state:events")
        await pubsub.close()


@router.get(
    "/sse/market",
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
    "/sse/candidates",
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
