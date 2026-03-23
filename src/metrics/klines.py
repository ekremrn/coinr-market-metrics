"""Binance kline array parsing."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from src.utils import clamp, safe_float

KLINE_OPEN_TIME = 0
KLINE_OPEN = 1
KLINE_HIGH = 2
KLINE_LOW = 3
KLINE_CLOSE = 4
KLINE_VOLUME = 5
KLINE_CLOSE_TIME = 6
KLINE_TAKER_BUY_BASE = 9


def parse_klines(raw: Optional[List[List[Any]]]) -> Dict[str, List[float]]:
    """Parse Binance kline arrays into numeric lists."""
    parsed: Dict[str, List[float]] = {
        "opens": [],
        "highs": [],
        "lows": [],
        "closes": [],
        "volumes": [],
        "taker_buy_base": [],
    }
    if not raw:
        return parsed

    for item in raw:
        if len(item) <= KLINE_TAKER_BUY_BASE:
            continue
        parsed["opens"].append(safe_float(item[KLINE_OPEN]))
        parsed["highs"].append(safe_float(item[KLINE_HIGH]))
        parsed["lows"].append(safe_float(item[KLINE_LOW]))
        parsed["closes"].append(safe_float(item[KLINE_CLOSE]))
        parsed["volumes"].append(safe_float(item[KLINE_VOLUME]))
        parsed["taker_buy_base"].append(safe_float(item[KLINE_TAKER_BUY_BASE]))
    return parsed


def last_bar_elapsed_fraction(raw: Optional[List[List[Any]]]) -> Optional[float]:
    """Fraction of the last (currently-forming) bar that has elapsed.

    Uses the bar's own open_time / close_time timestamps so the result is
    independent of clock-sync issues.  Clamped to [0.05, 1.0] to prevent
    absurd extrapolations when a bar has just opened.
    """
    if not raw:
        return None
    last = raw[-1]
    if len(last) <= KLINE_CLOSE_TIME:
        return None
    open_time_ms = safe_float(last[KLINE_OPEN_TIME])
    close_time_ms = safe_float(last[KLINE_CLOSE_TIME])
    bar_duration_ms = close_time_ms - open_time_ms + 1
    if bar_duration_ms <= 0:
        return None
    now_ms = time.time() * 1000
    return clamp((now_ms - open_time_ms) / bar_duration_ms, 0.05, 1.0)
