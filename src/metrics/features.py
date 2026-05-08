"""Raw feature extraction from kline data and order-book ticks."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from src.indicators import ema, sma, atr, adx, rsi
from src.utils import clamp, safe_float
from .klines import last_bar_elapsed_fraction, parse_klines
from .normalizers import (
    compute_returns,
    compute_window_return,
    direction_sign,
    liquidity_score_from_spread,
    return_sign,
    volume_score,
)


def last_value(values: List[float]) -> Optional[float]:
    return values[-1] if values else None


def compute_rsi(closes: List[float], period: int = 14) -> Optional[float]:
    values = rsi(closes, period)
    return last_value(values)


def compute_direction(closes: List[float], fast: int = 9, slow: int = 21) -> str:
    """Directional label from EMA crossover."""
    fast_ema = ema(closes, fast)
    slow_ema = ema(closes, slow)
    if not fast_ema or not slow_ema:
        return "neutral"
    if fast_ema[-1] > slow_ema[-1]:
        return "bullish"
    if fast_ema[-1] < slow_ema[-1]:
        return "bearish"
    return "neutral"


def compute_adx(highs: List[float], lows: List[float], closes: List[float]) -> Optional[float]:
    values = adx(highs, lows, closes, period=14)
    return last_value(values)


def compute_atr(highs: List[float], lows: List[float], closes: List[float]) -> Optional[float]:
    values = atr(highs, lows, closes, period=14)
    return last_value(values)


def compute_atr_percent(atr_value: Optional[float], price: Optional[float]) -> Optional[float]:
    if atr_value is None or not price or price <= 0:
        return None
    return (atr_value / price) * 100.0


def compute_vol_ratio(
    volumes: List[float],
    period: int = 20,
    elapsed_fraction: Optional[float] = None,
) -> Optional[float]:
    # Use only completed bars for the SMA baseline so the reference average
    # is not skewed by a half-formed bar.
    completed = volumes[:-1]
    if len(completed) < period:
        return None
    smas = sma(completed, period)
    if not smas or smas[-1] <= 0:
        return None
    # Project this bar's running volume to a full-bar equivalent.
    # elapsed_fraction comes from the bar's own open/close timestamps so it
    # works correctly even without a synchronised clock.
    if elapsed_fraction is not None and elapsed_fraction > 0:
        projected_vol = volumes[-1] / elapsed_fraction
    else:
        projected_vol = volumes[-1]
    return projected_vol / smas[-1]


def compute_taker_dominance(
    taker_buy: List[float],
    volumes: List[float],
    window: int = 4,
) -> Tuple[Optional[float], str]:
    if len(taker_buy) < window or len(volumes) < window:
        return None, "neutral"
    tb = sum(taker_buy[-window:])
    total = sum(volumes[-window:])
    if total <= 0:
        return None, "neutral"
    sell = total - tb
    if sell <= 0:
        ratio = 10.0
    else:
        ratio = tb / sell
    if ratio > 1.15:
        return ratio, "buy_dominant"
    if ratio < 0.85:
        return ratio, "sell_dominant"
    return ratio, "neutral"


def compute_spread_bps(bid: Optional[float], ask: Optional[float]) -> Optional[float]:
    if bid is None or ask is None:
        return None
    if bid <= 0 or ask <= 0:
        return None
    mid = (bid + ask) / 2.0
    if mid <= 0:
        return None
    return ((ask - bid) / mid) * 10000.0


def compute_range_position(
    highs: List[float],
    lows: List[float],
    price: Optional[float],
    window: int = 20,
) -> Optional[float]:
    if price is None or len(highs) < window or len(lows) < window:
        return None
    recent_high = max(highs[-window:])
    recent_low = min(lows[-window:])
    if recent_high <= recent_low:
        return 0.5
    return clamp((price - recent_low) / (recent_high - recent_low), 0.0, 1.0)


def compute_ema_distance_atr(
    price: Optional[float],
    ema_value: Optional[float],
    atr_value: Optional[float],
) -> Optional[float]:
    if price is None or ema_value is None or atr_value is None or atr_value <= 0:
        return None
    return abs(price - ema_value) / atr_value


def compute_direction_consensus(
    dir_15m: str,
    dir_1h: str,
    ret_15m: Optional[float],
    ret_1h: Optional[float],
) -> float:
    # Divide by len(signs)=4 always, not len(non_zero).
    # Previous code: 1 active signal out of 4 → 1/1=1.0 (false "strong").
    # Correct result: 1 active signal out of 4 → 1/4=0.25 (genuinely weak).
    signs = [direction_sign(dir_15m), direction_sign(dir_1h), return_sign(ret_15m), return_sign(ret_1h)]
    non_zero = [sign for sign in signs if sign != 0]
    if not non_zero:
        return 0.5
    positive = sum(1 for sign in non_zero if sign > 0)
    negative = len(non_zero) - positive
    return max(positive, negative) / len(signs)


def compute_taker_conflict(direction: str, dominance: str) -> bool:
    return (
        (dominance == "buy_dominant" and direction == "bearish")
        or (dominance == "sell_dominant" and direction == "bullish")
    )


def compute_swing_high(highs: List[float], window: int) -> Optional[float]:
    if len(highs) < window:
        return None
    return max(highs[-window:])


def compute_swing_low(lows: List[float], window: int) -> Optional[float]:
    if len(lows) < window:
        return None
    return min(lows[-window:])


def compute_level_touches(
    highs: List[float],
    lows: List[float],
    level: float,
    tolerance_frac: float,
    window: int,
    side: str,
) -> int:
    """Count bars where price touched a level within tolerance_frac of that level.

    side='support': checks lows <= level * (1 + tolerance_frac)
    side='resistance': checks highs >= level * (1 - tolerance_frac)
    """
    count = 0
    if side == "support":
        for low in lows[-window:]:
            if low <= level * (1.0 + tolerance_frac):
                count += 1
    else:
        for high in highs[-window:]:
            if high >= level * (1.0 - tolerance_frac):
                count += 1
    return count


def build_symbol_features(
    symbol: str,
    klines_15m: Optional[List[List[Any]]],
    klines_1h: Optional[List[List[Any]]],
    book: Optional[Dict[str, Any]],
    funding_rate: Optional[float] = None,
    klines_5m: Optional[List[List[Any]]] = None,
) -> Dict[str, Any]:
    parsed_15m = parse_klines(klines_15m)
    parsed_1h = parse_klines(klines_1h)

    closes_15m = parsed_15m["closes"]
    closes_1h = parsed_1h["closes"]
    highs_15m = parsed_15m["highs"]
    lows_15m = parsed_15m["lows"]
    volumes_15m = parsed_15m["volumes"]

    price = closes_15m[-1] if closes_15m else None

    adx_15m = compute_adx(highs_15m, lows_15m, closes_15m)
    adx_1h = compute_adx(parsed_1h["highs"], parsed_1h["lows"], closes_1h)

    atr_15m = compute_atr(highs_15m, lows_15m, closes_15m)
    atrp_15m = compute_atr_percent(atr_15m, price)

    elapsed_15m = last_bar_elapsed_fraction(klines_15m)
    vol_ratio_15m = compute_vol_ratio(volumes_15m, period=20, elapsed_fraction=elapsed_15m)

    taker_ratio, taker_dominance = compute_taker_dominance(
        parsed_15m["taker_buy_base"],
        volumes_15m,
        window=4,
    )

    dir_15m = compute_direction(closes_15m)
    dir_1h = compute_direction(closes_1h)
    # Suppress noisy EMA(9/21) crosses when ADX is below 18 (no real trend).
    # In choppy/low-ADX conditions, EMA crossovers are mostly noise; treating
    # the direction as neutral prevents false direction_consensus signals.
    if adx_15m is not None and adx_15m < 18.0:
        dir_15m = "neutral"
    if adx_1h is not None and adx_1h < 18.0:
        dir_1h = "neutral"

    bid = safe_float(book.get("bidPrice")) if book else None
    ask = safe_float(book.get("askPrice")) if book else None
    spread_bps = compute_spread_bps(bid, ask)

    returns_1h = compute_returns(closes_1h, periods=24)
    return_15m_4 = compute_window_return(closes_15m, periods=4)
    return_1h_6 = compute_window_return(closes_1h, periods=6)

    rsi_15m = compute_rsi(closes_15m)
    ema9_15m = last_value(ema(closes_15m, 9))
    ema21_15m = last_value(ema(closes_15m, 21))
    range_position_15m = compute_range_position(highs_15m, lows_15m, price, window=20)
    ema_distance_atr_15m = compute_ema_distance_atr(price, ema9_15m, atr_15m)
    volume_confirmation_15m = volume_score(vol_ratio_15m)
    taker_conflict_15m = compute_taker_conflict(dir_15m, taker_dominance)
    direction_consensus = compute_direction_consensus(dir_15m, dir_1h, return_15m_4, return_1h_6)

    # --- 5m-derived features (optional — absent when 5m klines not fetched) ---
    # range_position_5m_12 matches CoinR analysis agent's "position_in_range"
    # logic: 12-bar window, thresholds 0.80/0.20 for range-top/bottom rejection.
    # taker_dominance_5m uses the same 10-bar window and 1.15/0.85 ratio
    # thresholds as CoinR's pre-validation taker check.
    range_position_5m_12: Optional[float] = None
    rsi_5m: Optional[float] = None
    taker_ratio_5m: Optional[float] = None
    taker_dominance_5m: str = "neutral"

    if klines_5m is not None:
        parsed_5m = parse_klines(klines_5m)
        closes_5m = parsed_5m["closes"]
        highs_5m = parsed_5m["highs"]
        lows_5m = parsed_5m["lows"]
        volumes_5m = parsed_5m["volumes"]
        price_5m = closes_5m[-1] if closes_5m else price

        range_position_5m_12 = compute_range_position(highs_5m, lows_5m, price_5m, window=12)
        rsi_5m = compute_rsi(closes_5m, period=14)
        taker_ratio_5m, taker_dominance_5m = compute_taker_dominance(
            parsed_5m["taker_buy_base"],
            volumes_5m,
            window=10,
        )

    # --- Support / resistance levels ---
    # Near S/R: 8 × 15m = 2 hours (short-term ceiling/floor)
    # Key S/R:  12 × 1h = 3 days  (medium-term significant levels)
    # Distance uses the nearest level from both layers — most restrictive.
    # CoinR analysis rejects entries within 1.0% of support/resistance.
    support_near_15m = compute_swing_low(lows_15m, window=8)
    resistance_near_15m = compute_swing_high(highs_15m, window=8)

    highs_1h = parsed_1h["highs"]
    lows_1h = parsed_1h["lows"]
    support_key_1h = compute_swing_low(lows_1h, window=12)
    resistance_key_1h = compute_swing_high(highs_1h, window=12)

    support_distance_pct_15m: Optional[float] = None
    resistance_distance_pct_15m: Optional[float] = None
    support_touches_15m: Optional[int] = None
    resistance_touches_15m: Optional[int] = None

    if price is not None and price > 0:
        # nearest support = highest valid level below price
        support_candidates = [
            level
            for level in (support_near_15m, support_key_1h)
            if level is not None and level < price
        ]
        if support_candidates:
            nearest_support = max(support_candidates)
            support_distance_pct_15m = max((price - nearest_support) / price * 100.0, 0.0)

        # nearest resistance = lowest valid level above price
        resistance_candidates = [
            level
            for level in (resistance_near_15m, resistance_key_1h)
            if level is not None and level > price
        ]
        if resistance_candidates:
            nearest_resistance = min(resistance_candidates)
            resistance_distance_pct_15m = max((nearest_resistance - price) / price * 100.0, 0.0)

    # Adaptive touch tolerance: 0.15 × atrp_15m as fraction of level price.
    # Using ATR% makes the tolerance wider for volatile symbols and tighter
    # for stable ones, avoiding both false touches and missed touches.
    touch_tolerance = 0.0015 * (atrp_15m or 0.5)
    if support_near_15m is not None:
        support_touches_15m = compute_level_touches(
            highs_15m, lows_15m, support_near_15m, touch_tolerance, window=8, side="support"
        )
    if resistance_near_15m is not None:
        resistance_touches_15m = compute_level_touches(
            highs_15m, lows_15m, resistance_near_15m, touch_tolerance, window=8, side="resistance"
        )

    return {
        "symbol": symbol,
        "price": price,
        "dir_1h": dir_1h,
        "dir_15m": dir_15m,
        "adx_15m": adx_15m,
        "adx_1h": adx_1h,
        "atr_15m": atr_15m,
        "atrp_15m": atrp_15m,
        "vol_ratio_15m": vol_ratio_15m,
        "taker_ratio_15m": taker_ratio,
        "taker_dominance_15m": taker_dominance,
        "spread_bps": spread_bps,
        "returns_1h": returns_1h,
        "return_15m_4": return_15m_4,
        "return_1h_6": return_1h_6,
        "funding_rate": funding_rate,
        "range_position_15m": range_position_15m,
        "ema9_15m": ema9_15m,
        "ema21_15m": ema21_15m,
        "ema_distance_atr_15m": ema_distance_atr_15m,
        "volume_confirmation_15m": volume_confirmation_15m,
        "taker_conflict_15m": taker_conflict_15m,
        "direction_consensus": direction_consensus,
        "rsi_15m": rsi_15m,
        # 5m entry fields
        "range_position_5m_12": range_position_5m_12,
        "rsi_5m": rsi_5m,
        "taker_ratio_5m": taker_ratio_5m,
        "taker_dominance_5m": taker_dominance_5m,
        # Support / resistance
        "support_distance_pct_15m": support_distance_pct_15m,
        "resistance_distance_pct_15m": resistance_distance_pct_15m,
        "support_touches_15m": support_touches_15m,
        "resistance_touches_15m": resistance_touches_15m,
    }
