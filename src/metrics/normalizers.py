"""Pure numeric helpers: normalization curves, scoring, return math."""

from __future__ import annotations

from typing import List, Optional

import numpy as np

from src.utils import clamp


def normalize_range(value: Optional[float], low: float, high: float) -> float:
    if value is None:
        return 0.0
    if high == low:
        return 0.0
    return clamp((value - low) / (high - low), 0.0, 1.0)


def normalize_symmetric(value: Optional[float], max_abs: float) -> float:
    if value is None or max_abs <= 0:
        return 0.5
    return clamp((value + max_abs) / (2 * max_abs), 0.0, 1.0)


def weighted_mean(values: List[Optional[float]], weights: List[float], default: float = 0.0) -> float:
    numerator = 0.0
    denominator = 0.0
    for value, weight in zip(values, weights):
        if value is None:
            continue
        safe_weight = max(float(weight), 0.0)
        if safe_weight <= 0:
            continue
        numerator += float(value) * safe_weight
        denominator += safe_weight
    if denominator <= 0:
        return default
    return numerator / denominator


def volatility_band_score(atrp: Optional[float]) -> float:
    if atrp is None:
        return 0.0
    if atrp <= 0.4:
        return clamp(atrp / 0.4, 0.0, 1.0)
    if atrp <= 1.2:
        return 1.0
    return clamp(1.0 - (atrp - 1.2) / 0.8, 0.0, 1.0)


def volume_score(vol_ratio: Optional[float]) -> float:
    # Graduated curve: 0 at zero volume, 0.5 at average, 1.0 at 2x average.
    # Previous formula (vol_ratio-1)/0.5 gave 0 for anything below average,
    # causing volume_health=0 during off-peak sessions and false OFF regimes.
    if vol_ratio is None:
        return 0.0
    return clamp(vol_ratio / 2.0, 0.0, 1.0)


def alignment_score(direction: str, btc_direction: str) -> float:
    if direction == "neutral" or btc_direction == "neutral":
        return 0.5
    if direction == btc_direction:
        return 1.0
    return 0.0


def liquidity_score_from_spread(spread_bps: Optional[float]) -> float:
    # Cap at 4 bps (was 8 bps): top-20 USDT perps typically trade 0.01-2 bps,
    # so the old 8-bps cap compressed BTC/ETH/SOL into 0.85-1.0 with no
    # meaningful differentiation. 4 bps gives proper separation.
    if spread_bps is None:
        return 0.0
    return clamp((4.0 - spread_bps) / 4.0, 0.0, 1.0)


def direction_sign(direction: str) -> int:
    if direction == "bullish":
        return 1
    if direction == "bearish":
        return -1
    return 0


def return_sign(value: Optional[float], threshold: float = 0.001) -> int:
    if value is None:
        return 0
    if value > threshold:
        return 1
    if value < -threshold:
        return -1
    return 0


def compute_returns(closes: List[float], periods: int = 24) -> Optional[List[float]]:
    if len(closes) < periods + 1:
        return None
    window = closes[-(periods + 1):]
    returns = []
    for i in range(1, len(window)):
        prev = window[i - 1]
        curr = window[i]
        if prev == 0:
            returns.append(0.0)
        else:
            returns.append(curr / prev - 1.0)
    return returns


def compute_window_return(closes: List[float], periods: int) -> Optional[float]:
    if len(closes) < periods + 1:
        return None
    prev = closes[-(periods + 1)]
    curr = closes[-1]
    if prev == 0:
        return None
    return curr / prev - 1.0


def pearson_corr(a: List[float], b: List[float]) -> Optional[float]:
    if not a or not b:
        return None
    if len(a) != len(b):
        return None
    arr_a = np.array(a, dtype=np.float64)
    arr_b = np.array(b, dtype=np.float64)
    if arr_a.std() == 0 or arr_b.std() == 0:
        return None
    corr = np.corrcoef(arr_a, arr_b)[0, 1]
    if np.isnan(corr):
        return None
    return float(corr)
