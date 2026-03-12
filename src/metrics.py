"""Metric computation for market state snapshots."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
import numpy as np

from src.indicators import ema, sma, atr, adx
from src.utils import clamp, safe_float


KLINE_OPEN = 1
KLINE_HIGH = 2
KLINE_LOW = 3
KLINE_CLOSE = 4
KLINE_VOLUME = 5
KLINE_TAKER_BUY_BASE = 9


def parse_klines(raw: Optional[List[List[Any]]]) -> Dict[str, List[float]]:
    """Parse Binance kline arrays into numeric lists."""
    parsed = {
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


def last_value(values: List[float]) -> Optional[float]:
    return values[-1] if values else None


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


def compute_vol_ratio(volumes: List[float], period: int = 20) -> Optional[float]:
    if not volumes:
        return None
    smas = sma(volumes, period)
    if not smas:
        return None
    last_vol = volumes[-1]
    return last_vol / smas[-1] if smas[-1] > 0 else None


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


def volatility_band_score(atrp: Optional[float]) -> float:
    if atrp is None:
        return 0.0
    if atrp <= 0.4:
        return clamp(atrp / 0.4, 0.0, 1.0)
    if atrp <= 1.2:
        return 1.0
    return clamp(1.0 - (atrp - 1.2) / 0.8, 0.0, 1.0)


def volume_score(vol_ratio: Optional[float]) -> float:
    if vol_ratio is None:
        return 0.0
    return clamp((vol_ratio - 1.0) / 0.5, 0.0, 1.0)


def alignment_score(direction: str, btc_direction: str) -> float:
    if direction == "neutral" or btc_direction == "neutral":
        return 0.5
    if direction == btc_direction:
        return 1.0
    return 0.0


def compute_returns(closes: List[float], periods: int = 24) -> Optional[List[float]]:
    if len(closes) < periods + 1:
        return None
    window = closes[-(periods + 1) :]
    returns = []
    for i in range(1, len(window)):
        prev = window[i - 1]
        curr = window[i]
        if prev == 0:
            returns.append(0.0)
        else:
            returns.append(curr / prev - 1.0)
    return returns


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


def build_symbol_features(
    symbol: str,
    klines_15m: Optional[List[List[Any]]],
    klines_1h: Optional[List[List[Any]]],
    book: Optional[Dict[str, Any]],
    funding_rate: Optional[float] = None,
) -> Dict[str, Any]:
    parsed_15m = parse_klines(klines_15m)
    parsed_1h = parse_klines(klines_1h)

    closes_15m = parsed_15m["closes"]
    closes_1h = parsed_1h["closes"]

    price = closes_15m[-1] if closes_15m else None

    adx_15m = compute_adx(parsed_15m["highs"], parsed_15m["lows"], closes_15m)
    adx_1h = compute_adx(parsed_1h["highs"], parsed_1h["lows"], closes_1h)

    atr_15m = compute_atr(parsed_15m["highs"], parsed_15m["lows"], closes_15m)
    atrp_15m = compute_atr_percent(atr_15m, price)

    vol_ratio_15m = compute_vol_ratio(parsed_15m["volumes"], period=20)

    taker_ratio, taker_dominance = compute_taker_dominance(
        parsed_15m["taker_buy_base"],
        parsed_15m["volumes"],
        window=4,
    )

    dir_15m = compute_direction(closes_15m)
    dir_1h = compute_direction(closes_1h)

    bid = safe_float(book.get("bidPrice")) if book else None
    ask = safe_float(book.get("askPrice")) if book else None
    spread_bps = compute_spread_bps(bid, ask)

    returns_1h = compute_returns(closes_1h, periods=24)

    return {
        "symbol": symbol,
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
        "funding_rate": funding_rate,
    }


def build_symbol_metrics(feature: Dict[str, Any], btc_direction: str) -> Dict[str, Any]:
    adx_15m = feature.get("adx_15m")
    spread_bps = feature.get("spread_bps")
    vol_ratio_15m = feature.get("vol_ratio_15m")
    atrp_15m = feature.get("atrp_15m")

    liquidity_score = 0.0
    if spread_bps is not None:
        liquidity_score = clamp((8.0 - spread_bps) / 8.0, 0.0, 1.0)

    trend_score = normalize_range(adx_15m, 22.0, 35.0)
    align_score = alignment_score(feature.get("dir_15m", "neutral"), btc_direction)
    vol_score = volatility_band_score(atrp_15m)
    volm_score = volume_score(vol_ratio_15m)

    attractiveness = (
        0.30 * trend_score
        + 0.25 * liquidity_score
        + 0.20 * align_score
        + 0.15 * vol_score
        + 0.10 * volm_score
    )
    attractiveness = clamp(attractiveness, 0.0, 1.0)

    flags = []
    if adx_15m is not None and adx_15m < 22:
        flags.append("adx15_low")
    if spread_bps is not None and spread_bps > 8:
        flags.append("high_spread")
    if vol_ratio_15m is not None and vol_ratio_15m < 1.0:
        flags.append("volume_weak")

    dominance = feature.get("taker_dominance_15m", "neutral")
    dir_15m = feature.get("dir_15m", "neutral")
    if dominance == "buy_dominant" and dir_15m == "bearish":
        flags.append("taker_conflict")
    if dominance == "sell_dominant" and dir_15m == "bullish":
        flags.append("taker_conflict")

    return {
        "symbol": feature.get("symbol"),
        "dir_1h": feature.get("dir_1h"),
        "dir_15m": dir_15m,
        "adx_15m": adx_15m,
        "spread_bps": spread_bps,
        "taker_dominance_15m": dominance,
        "atrp_15m": atrp_15m,
        "vol_ratio_15m": vol_ratio_15m,
        "liquidity_score": liquidity_score,
        "trend_score": trend_score,
        "attractiveness_score": attractiveness,
        "flags": flags,
    }


def build_market_metrics(
    features: List[Dict[str, Any]],
    btc_symbol: str = "BTCUSDT",
) -> Tuple[Dict[str, Any], str]:
    feature_map = {item["symbol"]: item for item in features}
    btc = feature_map.get(btc_symbol)

    adx_values = [item.get("adx_15m") for item in features if item.get("adx_15m") is not None]
    adx_mean = float(np.mean(adx_values)) if adx_values else 0.0
    chop_ratio = 0.0
    if adx_values:
        chop_ratio = sum(1 for v in adx_values if v < 22) / len(adx_values)

    tradeability_score = normalize_range(adx_mean, 22.0, 30.0)
    chop_score = clamp(chop_ratio / 0.5, 0.0, 1.0)

    market_regime = "SELECTIVE"
    if adx_mean < 22 or chop_ratio > 0.4:
        market_regime = "OFF"
    elif adx_mean >= 30 and chop_ratio <= 0.2:
        market_regime = "TRENDING"

    btc_direction = btc.get("dir_1h") if btc else "neutral"
    btc_trend_strength = normalize_range(btc.get("adx_1h") if btc else None, 20.0, 35.0)

    alt_dirs = [
        item.get("dir_15m", "neutral")
        for item in features
        if item.get("symbol") != btc_symbol
    ]
    total_alts = len(alt_dirs)
    bull_ratio = alt_dirs.count("bullish") / total_alts if total_alts else 0.0
    bear_ratio = alt_dirs.count("bearish") / total_alts if total_alts else 0.0
    alt_bias = clamp(0.5 + 0.5 * (bull_ratio - bear_ratio), 0.0, 1.0)

    btc_returns = btc.get("returns_1h") if btc else None
    correlations = []
    if btc_returns:
        for item in features:
            if item.get("symbol") == btc_symbol:
                continue
            alt_returns = item.get("returns_1h")
            corr = pearson_corr(btc_returns, alt_returns) if alt_returns else None
            if corr is not None:
                correlations.append(corr)

    if correlations:
        mean_corr = float(np.mean(correlations))
    else:
        mean_corr = 0.0

    btc_alt_corr_mean_1h = (mean_corr + 1.0) / 2.0

    if mean_corr > 0.6:
        correlation_regime = "COUPLED"
    elif mean_corr < 0.3:
        correlation_regime = "DECOUPLED"
    else:
        correlation_regime = "MIXED"

    atrp_values = [item.get("atrp_15m") for item in features if item.get("atrp_15m") is not None]
    atrp_mean = float(np.mean(atrp_values)) if atrp_values else 0.0
    volatility_level = normalize_range(atrp_mean, 0.3, 1.2)

    if atrp_mean <= 0.4:
        volatility_regime = "LOW"
    elif atrp_mean >= 1.0:
        volatility_regime = "HIGH"
    else:
        volatility_regime = "NORMAL"

    vol_scores = [volume_score(item.get("vol_ratio_15m")) for item in features]
    volume_health = float(np.mean(vol_scores)) if vol_scores else 0.0

    funding_rates = [
        item.get("funding_rate") for item in features if item.get("funding_rate") is not None
    ]
    funding_rate_avg = float(np.mean(funding_rates)) if funding_rates else None
    funding_rate_avg_8h = normalize_symmetric(funding_rate_avg, 0.003)
    if funding_rate_avg is None or abs(funding_rate_avg) < 0.0001:
        funding_rate_direction = "neutral"
    elif funding_rate_avg > 0:
        funding_rate_direction = "positive"
    else:
        funding_rate_direction = "negative"

    recommended_mode = "SELECTIVE"
    if market_regime == "OFF":
        recommended_mode = "OFF"
    elif btc_direction == "bearish" and alt_bias < 0.4:
        recommended_mode = "SHORT_ONLY"
    elif btc_direction == "bullish" and alt_bias > 0.6:
        recommended_mode = "LONG_ONLY"

    market = {
        "tradeability_score": tradeability_score,
        "chop_score": chop_score,
        "market_regime": market_regime,
        "btc_direction_1h": btc_direction,
        "btc_trend_strength": btc_trend_strength,
        "alt_directional_bias_15m": alt_bias,
        "btc_alt_corr_mean_1h": clamp(btc_alt_corr_mean_1h, 0.0, 1.0),
        "correlation_regime": correlation_regime,
        "volatility_level_15m": volatility_level,
        "volatility_regime": volatility_regime,
        "volume_health_15m": volume_health,
        "recommended_mode": recommended_mode,
        "funding_rate_avg_8h": funding_rate_avg_8h,
        "funding_rate_direction": funding_rate_direction,
        "adx15_mean": adx_mean,
        "chop_ratio": chop_ratio,
        "atrp_mean_15m": atrp_mean,
        "btc_alt_corr_raw": mean_corr,
    }
    return market, btc_direction


def select_candidates(symbols: List[Dict[str, Any]], k: int = 10) -> List[Dict[str, Any]]:
    ranked = sorted(symbols, key=lambda item: item.get("attractiveness_score", 0.0), reverse=True)
    candidates = []
    for item in ranked[:k]:
        candidates.append(
            {
                "symbol": item.get("symbol"),
                "flags": item.get("flags", []),
                "dir_15m": item.get("dir_15m"),
                "dir_1h": item.get("dir_1h"),
                "adx_15m": item.get("adx_15m"),
                "spread_bps": item.get("spread_bps"),
                "atrp_15m": item.get("atrp_15m"),
                "vol_ratio_15m": item.get("vol_ratio_15m"),
                "taker_dominance_15m": item.get("taker_dominance_15m"),
                "liquidity_score": item.get("liquidity_score", 0.0),
                "trend_score": item.get("trend_score", 0.0),
                "attractiveness_score": item.get("attractiveness_score", 0.0),
            }
        )
    return candidates
