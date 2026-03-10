"""Shared Redis store instance for the API."""

from src.config import RedisConfig
from src.storage import AsyncRedisStore

redis_store = AsyncRedisStore(RedisConfig())
