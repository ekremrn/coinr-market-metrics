"""
Configuration Management
========================

Centralized configuration for Coinr Market Metrics.
Uses environment variables with sensible defaults.
"""

import os
from dataclasses import dataclass, field
from typing import List, Set, Optional


def _csv_set(value: str) -> Set[str]:
    items = [item.strip().upper() for item in (value or "").split(",")]
    return {item for item in items if item}


@dataclass(frozen=True)
class LoggingConfig:
    """Application logging configuration."""
    level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))


@dataclass(frozen=True)
class BinanceConfig:
    """Binance API configuration."""
    api_key: str = field(default_factory=lambda: os.getenv("BINANCE_API_KEY", ""))
    api_secret: str = field(default_factory=lambda: os.getenv("BINANCE_API_SECRET", ""))
    use_testnet: bool = field(default_factory=lambda: os.getenv("BINANCE_TESTNET", "false").lower() == "true")


@dataclass(frozen=True)
class RedisConfig:
    """Redis connection configuration."""
    url: str = field(default_factory=lambda: os.getenv("REDIS_URL", "redis://localhost:6379/0"))


@dataclass(frozen=True)
class MongoConfig:
    """MongoDB connection configuration."""
    uri: str = field(default_factory=lambda: os.getenv("MONGO_URI", "mongodb://localhost:27017/coinr_market_metrics"))
    database: Optional[str] = field(default_factory=lambda: os.getenv("MONGO_DB"))


@dataclass(frozen=True)
class AppConfig:
    """Application-level configuration."""
    top_n: int = field(default_factory=lambda: int(os.getenv("TOP_N", "30")))
    candidates_k: int = field(default_factory=lambda: int(os.getenv("CANDIDATES_K", "10")))
    scan_interval_minutes: int = field(default_factory=lambda: int(os.getenv("SCAN_INTERVAL_MINUTES", "15")))
    blacklist: Set[str] = field(default_factory=lambda: _csv_set(os.getenv("BLACKLIST", "")))
    metrics_version: str = field(default_factory=lambda: os.getenv("METRICS_VERSION", "v1"))
    include_symbols_in_mongo: bool = field(
        default_factory=lambda: os.getenv("INCLUDE_SYMBOLS_IN_MONGO", "false").lower() == "true"
    )


def get_config() -> dict:
    """Return all configuration objects."""
    return {
        "logging": LoggingConfig(),
        "binance": BinanceConfig(),
        "redis": RedisConfig(),
        "mongo": MongoConfig(),
        "app": AppConfig(),
    }
