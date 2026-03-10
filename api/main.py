"""FastAPI application entry point."""

from __future__ import annotations

from fastapi import FastAPI

from api.routes import snapshot, sse
from api.store import redis_store
from src.logging import get_logger

logger = get_logger("market-metrics-api")

app = FastAPI(
    title="Coinr Market Metrics",
    version="v1",
    description="""
Real-time USDT-perpetual futures market metrics streamed via SSE.

### How it works
The **scanner job** runs on a fixed schedule and writes a full market snapshot
to Redis. The **API** serves that snapshot via:

- **SSE endpoints** — push updates to connected clients whenever a new snapshot lands.
- **Snapshot endpoint** — single HTTP pull of the latest state.

### Data freshness
Snapshots are produced every `SCAN_INTERVAL_MINUTES` (default 15 min).
""",
)

app.include_router(sse.router)
app.include_router(snapshot.router)


@app.on_event("shutdown")
async def shutdown() -> None:
    await redis_store.close()
