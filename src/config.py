"""
Configuration Management
========================

Centralized configuration for Coinr Market Metrics.
Uses environment variables with sensible defaults.
"""

import os
from dataclasses import dataclass, field
from typing import Set

MARKET_METRICS_MONGO_DB = "coinr-market-metrics"
SETUPS_MONGO_DB = "coinr"


def _csv_set(value: str) -> Set[str]:
    items = [item.strip().upper() for item in (value or "").split(",")]
    return {item for item in items if item}


@dataclass(frozen=True)
class LoggingConfig:
    """Application logging configuration."""
    level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))


@dataclass(frozen=True)
class RedisConfig:
    """Redis connection configuration."""
    url: str = field(default_factory=lambda: os.getenv("REDIS_URL", "redis://localhost:6379/0"))


@dataclass(frozen=True)
class MongoConfig:
    """MongoDB connection configuration."""
    uri: str = field(default_factory=lambda: os.getenv("MONGO_URI", "mongodb://localhost:27017"))
    database: str = field(default=MARKET_METRICS_MONGO_DB)


@dataclass(frozen=True)
class ApiConfig:
    """API server configuration."""
    production: bool = field(
        default_factory=lambda: os.getenv("PRODUCTION", "false").lower() == "true"
    )
    cors_origins: list = field(
        default_factory=lambda: [
            o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()
        ]
    )


@dataclass(frozen=True)
class AppConfig:
    """Scanner / application-level configuration."""
    top_n: int = field(default_factory=lambda: int(os.getenv("TOP_N", "20")))
    candidates_k: int = field(default_factory=lambda: int(os.getenv("CANDIDATES_K", "5")))
    blacklist: Set[str] = field(default_factory=lambda: _csv_set(os.getenv("BLACKLIST", "")))
    metrics_version: str = field(default_factory=lambda: os.getenv("METRICS_VERSION", "v1.1"))
    include_symbols_in_mongo: bool = field(
        default_factory=lambda: os.getenv("INCLUDE_SYMBOLS_IN_MONGO", "false").lower() == "true"
    )
    # Universe quality gates — filter out wash-traded / illiquid tokens before
    # they distort market-level metrics (atrp_mean, volume_health, regime).
    # min_quote_volume: minimum 24h notional volume in USD (default $100M).
    # max_spread_bps: maximum bid/ask spread in basis points (default 3.5 bps).
    # Tokens exceeding max_spread_bps are excluded even if volume is high,
    # catching wash-traded meme tokens with inflated turnover.
    min_quote_volume: float = field(
        default_factory=lambda: float(os.getenv("MIN_QUOTE_VOLUME", "100000000"))
    )
    max_spread_bps: float = field(
        default_factory=lambda: float(os.getenv("MAX_SPREAD_BPS", "3.5"))
    )
