"""Snapshot route handlers."""

from __future__ import annotations

from fastapi import APIRouter

from api.models import SnapshotResponse
from api.store import redis_store

router = APIRouter(tags=["Snapshot"])


@router.get(
    "/snapshot/latest",
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
