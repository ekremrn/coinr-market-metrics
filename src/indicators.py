"""
Technical Indicators
====================

Lightweight indicator implementations using NumPy.
"""

from typing import List
import numpy as np


def ema(prices: List[float], period: int = 12) -> List[float]:
    """Calculate Exponential Moving Average."""
    if not prices or len(prices) < period:
        return []

    arr = np.array(prices, dtype=np.float64)
    multiplier = 2.0 / (period + 1)

    result = np.zeros(len(arr) - period + 1, dtype=np.float64)
    result[0] = np.mean(arr[:period])

    for i, price in enumerate(arr[period:], start=1):
        result[i] = (price - result[i - 1]) * multiplier + result[i - 1]

    return result.tolist()


def sma(prices: List[float], period: int = 20) -> List[float]:
    """Calculate Simple Moving Average."""
    if not prices or len(prices) < period:
        return []

    arr = np.array(prices, dtype=np.float64)
    weights = np.ones(period, dtype=np.float64) / period
    return np.convolve(arr, weights, mode="valid").tolist()


def atr(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    period: int = 14,
) -> List[float]:
    """Calculate Average True Range."""
    if not highs or len(highs) < period + 1:
        return []

    h = np.array(highs, dtype=np.float64)
    l = np.array(lows, dtype=np.float64)
    c = np.array(closes, dtype=np.float64)

    tr1 = h[1:] - l[1:]
    tr2 = np.abs(h[1:] - c[:-1])
    tr3 = np.abs(l[1:] - c[:-1])
    tr = np.maximum(np.maximum(tr1, tr2), tr3)

    result = np.zeros(len(tr) - period + 1, dtype=np.float64)
    result[0] = np.mean(tr[:period])

    for i in range(period, len(tr)):
        result[i - period + 1] = (result[i - period] * (period - 1) + tr[i]) / period

    return result.tolist()


def adx(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    period: int = 14,
) -> List[float]:
    """Calculate Average Directional Index."""
    if not highs or len(highs) < period * 2:
        return []

    h = np.array(highs, dtype=np.float64)
    l = np.array(lows, dtype=np.float64)
    c = np.array(closes, dtype=np.float64)

    plus_dm = np.zeros(len(h) - 1)
    minus_dm = np.zeros(len(h) - 1)

    for i in range(1, len(h)):
        up_move = h[i] - h[i - 1]
        down_move = l[i - 1] - l[i]

        if up_move > down_move and up_move > 0:
            plus_dm[i - 1] = up_move
        if down_move > up_move and down_move > 0:
            minus_dm[i - 1] = down_move

    tr = np.maximum(
        h[1:] - l[1:],
        np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])),
    )

    atr_vals = [np.mean(tr[:period])]
    plus_di_smooth = [np.mean(plus_dm[:period])]
    minus_di_smooth = [np.mean(minus_dm[:period])]

    for i in range(period, len(tr)):
        atr_vals.append((atr_vals[-1] * (period - 1) + tr[i]) / period)
        plus_di_smooth.append((plus_di_smooth[-1] * (period - 1) + plus_dm[i]) / period)
        minus_di_smooth.append((minus_di_smooth[-1] * (period - 1) + minus_dm[i]) / period)

    plus_di = []
    minus_di = []
    dx = []

    for i in range(len(atr_vals)):
        if atr_vals[i] > 0:
            plus_di.append(100 * plus_di_smooth[i] / atr_vals[i])
            minus_di.append(100 * minus_di_smooth[i] / atr_vals[i])
        else:
            plus_di.append(0)
            minus_di.append(0)

        di_sum = plus_di[-1] + minus_di[-1]
        if di_sum > 0:
            dx.append(100 * abs(plus_di[-1] - minus_di[-1]) / di_sum)
        else:
            dx.append(0)

    if len(dx) < period:
        return []

    adx_vals = [np.mean(dx[:period])]
    for i in range(period, len(dx)):
        adx_vals.append((adx_vals[-1] * (period - 1) + dx[i]) / period)

    return adx_vals
