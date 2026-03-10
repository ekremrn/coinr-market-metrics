"""Storage helpers for Redis and MongoDB."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

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
