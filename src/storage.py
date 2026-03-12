"""Storage helpers for Redis and MongoDB."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import redis
import redis.asyncio as aioredis
from pymongo import MongoClient

from src.config import MongoConfig, RedisConfig


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
        await self._client.close()

    def pubsub(self):
        return self._client.pubsub()


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
