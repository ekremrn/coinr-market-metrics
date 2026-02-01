"""FastAPI app exposing SSE and snapshot endpoints."""

from __future__ import annotations

import asyncio
import json
from typing import AsyncGenerator, Optional

from fastapi import FastAPI
from fastapi.responses import JSONResponse, StreamingResponse

from src.config import RedisConfig
from src.logging import get_logger
from src.storage import AsyncRedisStore


logger = get_logger("market-metrics-api")
app = FastAPI(title="coinr-market-metrics", version="v1")
redis_store = AsyncRedisStore(RedisConfig())


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


@app.get("/sse/market")
async def sse_market() -> StreamingResponse:
    return StreamingResponse(
        stream_key("market_state:latest"),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@app.get("/sse/candidates")
async def sse_candidates() -> StreamingResponse:
    return StreamingResponse(
        stream_key("market_state:candidates:latest"),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@app.get("/snapshot/latest")
async def snapshot_latest() -> JSONResponse:
    market_state = await redis_store.get_json("market_state:latest")
    candidates = await redis_store.get_json("market_state:candidates:latest")
    return JSONResponse({"market_state": market_state, "candidates": candidates})


@app.on_event("shutdown")
async def shutdown() -> None:
    await redis_store.close()
