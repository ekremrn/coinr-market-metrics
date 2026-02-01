"""Utility helpers."""

from datetime import datetime, timezone
from typing import Any


def clamp(value: float, min_value: float = 0.0, max_value: float = 1.0) -> float:
    """Clamp a value to [min_value, max_value]."""
    return max(min_value, min(max_value, value))


def utc_now_iso() -> str:
    """UTC ISO-8601 timestamp."""
    return datetime.now(timezone.utc).isoformat()


def utc_now_ms() -> int:
    """UTC epoch milliseconds."""
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def safe_float(value: Any, default: float = 0.0) -> float:
    """Convert to float safely."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
