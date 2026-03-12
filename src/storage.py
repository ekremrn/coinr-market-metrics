"""Storage helpers for Redis and MongoDB."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import redis
import redis.asyncio as aioredis
from pymongo import MongoClient

from src.config import MongoConfig, RedisConfig


class BroadcastHub:
    """
    Fan-out bridge: one Redis pubsub connection → N asyncio.Queue subscribers.

    No matter how many SSE clients are connected, only a single Redis pubsub
    connection is held per channel. The listener task starts on first subscribe
    and stops automatically when the last subscriber leaves.
    """

    def __init__(self, client: aioredis.Redis, channel: str) -> None:
        self._client = client
        self._channel = channel
        self._subscribers: set[asyncio.Queue[str]] = set()
        self._lock = asyncio.Lock()
        self._task: asyncio.Task | None = None

    async def _run(self) -> None:
        pubsub = self._client.pubsub()
        await pubsub.subscribe(self._channel)
        try:
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                data: str = message["data"]
                dead: set[asyncio.Queue[str]] = set()
                for q in list(self._subscribers):
                    try:
                        q.put_nowait(data)
                    except asyncio.QueueFull:
                        dead.add(q)
                for q in dead:
                    self._subscribers.discard(q)
        except asyncio.CancelledError:
            pass
        finally:
            await pubsub.unsubscribe(self._channel)
            await pubsub.aclose()

    async def subscribe(self) -> asyncio.Queue[str]:
        async with self._lock:
            q: asyncio.Queue[str] = asyncio.Queue(maxsize=64)
            self._subscribers.add(q)
            if self._task is None or self._task.done():
                self._task = asyncio.create_task(self._run())
        return q

    async def unsubscribe(self, q: asyncio.Queue[str]) -> None:
        async with self._lock:
            self._subscribers.discard(q)
            if not self._subscribers and self._task and not self._task.done():
                self._task.cancel()
                try:
                    await asyncio.wait_for(asyncio.shield(self._task), timeout=2.0)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    pass
                self._task = None


class RedisStore:
    """Synchronous Redis wrapper."""

    def __init__(self, config: Optional[RedisConfig] = None) -> None:
        cfg = config or RedisConfig()
        self._client = redis.Redis.from_url(cfg.url, decode_responses=True)

    def set_json(self, key: str, payload: Any) -> None:
        self._client.set(key, json.dumps(payload, separators=(",", ":")))

    def get_json(self, key: str) -> Optional[Any]:
        data = self._client.get(key)
        if not data:
            return None
        return json.loads(data)

    def publish(self, channel: str, payload: Any) -> int:
        return self._client.publish(channel, json.dumps(payload, separators=(",", ":")))


class AsyncRedisStore:
    """Async Redis wrapper."""

    def __init__(self, config: Optional[RedisConfig] = None) -> None:
        cfg = config or RedisConfig()
        self._client = aioredis.Redis.from_url(cfg.url, decode_responses=True)
        self._hubs: dict[str, BroadcastHub] = {}

    def _get_hub(self, channel: str) -> BroadcastHub:
        """Return (creating if needed) the shared broadcast hub for a channel."""
        if channel not in self._hubs:
            self._hubs[channel] = BroadcastHub(self._client, channel)
        return self._hubs[channel]

    async def subscribe(self, channel: str) -> asyncio.Queue[str]:
        """Subscribe to a channel. Returns a Queue that receives raw message data."""
        return await self._get_hub(channel).subscribe()

    async def unsubscribe(self, channel: str, q: asyncio.Queue[str]) -> None:
        """Unsubscribe a Queue from a channel."""
        if channel in self._hubs:
            await self._hubs[channel].unsubscribe(q)

    async def get_json(self, key: str) -> Optional[Any]:
        data = await self._client.get(key)
        if not data:
            return None
        return json.loads(data)

    async def get_recent_signals(
        self, key: str, max_age_seconds: int = 7200, max_items: int = 100
    ) -> List[Any]:
        """LRANGE key, filter by timestamp age, return oldest-first."""
        raw_items = await self._client.lrange(key, 0, max_items - 1)
        now = datetime.now(timezone.utc)
        result = []
        for item in raw_items:
            try:
                data = json.loads(item)
                ts_str = data.get("timestamp")
                if ts_str:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    if (now - ts).total_seconds() > max_age_seconds:
                        continue
                result.append(data)
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
        result.reverse()  # oldest first
        return result

    async def close(self) -> None:
        # Cancel all hub listener tasks first
        for hub in self._hubs.values():
            if hub._task and not hub._task.done():
                hub._task.cancel()
        await self._client.aclose()


class MongoStore:
    """MongoDB wrapper for market snapshots."""

    def __init__(self, config: Optional[MongoConfig] = None) -> None:
        cfg = config or MongoConfig()
        self._client = MongoClient(cfg.uri)
        self._db = self._client[cfg.database]

    def insert_snapshot(self, document: Dict[str, Any]) -> str:
        collection = self._db["market_state_snapshots"]
        result = collection.insert_one(document)
        return str(result.inserted_id)
