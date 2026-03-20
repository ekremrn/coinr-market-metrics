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

REGIME_DETAILS = {
    "TREND",
    "TREND_PULLBACK",
    "TREND_EXTENSION",
    "CHOP",
    "EXPANSION",
    "EXHAUSTION",
    "MIXED",
}


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


def liquidity_score_from_spread(spread_bps: Optional[float]) -> float:
    if spread_bps is None:
        return 0.0
    return clamp((8.0 - spread_bps) / 8.0, 0.0, 1.0)


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
    signs = [direction_sign(dir_15m), direction_sign(dir_1h), return_sign(ret_15m), return_sign(ret_1h)]
    non_zero = [sign for sign in signs if sign != 0]
    if not non_zero:
        return 0.5
    positive = sum(1 for sign in non_zero if sign > 0)
    negative = len(non_zero) - positive
    return max(positive, negative) / len(non_zero)


def compute_taker_conflict(direction: str, dominance: str) -> bool:
    return (
        (dominance == "buy_dominant" and direction == "bearish")
        or (dominance == "sell_dominant" and direction == "bullish")
    )


def relative_strength_from_returns(
    feature: Dict[str, Any],
    btc_feature: Optional[Dict[str, Any]],
) -> Optional[float]:
    if btc_feature is None:
        return None
    rel_components = []
    ret_15m = feature.get("return_15m_4")
    btc_ret_15m = btc_feature.get("return_15m_4")
    if ret_15m is not None and btc_ret_15m is not None:
        rel_components.append(0.4 * (ret_15m - btc_ret_15m))

    ret_1h = feature.get("return_1h_6")
    btc_ret_1h = btc_feature.get("return_1h_6")
    if ret_1h is not None and btc_ret_1h is not None:
        rel_components.append(0.6 * (ret_1h - btc_ret_1h))

    if not rel_components:
        return None
    return normalize_symmetric(sum(rel_components), 0.06)


def execution_cost_score_from_feature(feature: Dict[str, Any]) -> float:
    liquidity = liquidity_score_from_spread(feature.get("spread_bps"))
    volatility_usable = volatility_band_score(feature.get("atrp_15m"))
    return clamp(0.7 * liquidity + 0.3 * volatility_usable, 0.0, 1.0)


def extension_score_from_feature(feature: Dict[str, Any]) -> float:
    ema_distance_atr = feature.get("ema_distance_atr_15m")
    range_position = feature.get("range_position_15m")
    volume_confirmation = feature.get("volume_confirmation_15m", 0.0)

    distance_score = normalize_range(ema_distance_atr, 0.8, 2.5)
    edge_score = 0.0
    if range_position is not None:
        edge_score = clamp(2 * abs(range_position - 0.5), 0.0, 1.0)

    return clamp(0.6 * distance_score + 0.3 * edge_score + 0.1 * volume_confirmation, 0.0, 1.0)


def fakeout_risk_from_feature(
    feature: Dict[str, Any],
    execution_cost_score: float,
    extension_score: float,
) -> float:
    local_chop = 1.0 - normalize_range(feature.get("adx_15m"), 22.0, 35.0)
    taker_conflict = 1.0 if feature.get("taker_conflict_15m") else 0.0
    weak_volume = 1.0 - clamp(feature.get("volume_confirmation_15m", 0.0), 0.0, 1.0)
    return clamp(
        0.25 * local_chop
        + 0.25 * taker_conflict
        + 0.20 * weak_volume
        + 0.20 * extension_score
        + 0.10 * (1.0 - execution_cost_score),
        0.0,
        1.0,
    )


def side_alignment_score(dir_15m: str, dir_1h: str, side: str) -> float:
    target = "bullish" if side == "long" else "bearish"
    support = 0.0
    if dir_15m == target:
        support += 0.5
    elif dir_15m == "neutral":
        support += 0.25

    if dir_1h == target:
        support += 0.5
    elif dir_1h == "neutral":
        support += 0.25

    return clamp(support, 0.0, 1.0)


def dominance_score_for_side(dominance: str, side: str) -> float:
    if dominance == "neutral":
        return 0.5
    if side == "long":
        return 1.0 if dominance == "buy_dominant" else 0.0
    return 1.0 if dominance == "sell_dominant" else 0.0


def side_score_from_feature(
    side: str,
    feature: Dict[str, Any],
    relative_strength_score: Optional[float],
    execution_cost_score: float,
    extension_score: float,
    fakeout_risk: float,
) -> float:
    dir_alignment = side_alignment_score(feature.get("dir_15m", "neutral"), feature.get("dir_1h", "neutral"), side)
    dominance = dominance_score_for_side(feature.get("taker_dominance_15m", "neutral"), side)
    relative = 0.5 if relative_strength_score is None else relative_strength_score
    relative_side = relative if side == "long" else 1.0 - relative

    return clamp(
        0.25 * dir_alignment
        + 0.15 * dominance
        + 0.20 * relative_side
        + 0.15 * (1.0 - extension_score)
        + 0.15 * (1.0 - fakeout_risk)
        + 0.10 * execution_cost_score,
        0.0,
        1.0,
    )


def determine_symbol_regime_label(
    feature: Dict[str, Any],
    extension_score: float,
    fakeout_risk: float,
) -> str:
    trend_score = normalize_range(feature.get("adx_15m"), 22.0, 35.0)
    consensus = clamp(feature.get("direction_consensus", 0.5), 0.0, 1.0)
    volume_confirmation = clamp(feature.get("volume_confirmation_15m", 0.0), 0.0, 1.0)
    volatility_usable = volatility_band_score(feature.get("atrp_15m"))

    if fakeout_risk >= 0.72 and extension_score >= 0.68:
        return "EXHAUSTION"
    if trend_score < 0.35 and consensus < 0.6:
        return "CHOP"
    if trend_score >= 0.7 and extension_score >= 0.62:
        return "TREND_EXTENSION"
    if trend_score >= 0.65 and extension_score <= 0.42 and fakeout_risk <= 0.45:
        return "TREND"
    if trend_score >= 0.5 and extension_score < 0.6 and fakeout_risk < 0.55:
        return "TREND_PULLBACK"
    if volume_confirmation >= 0.7 and volatility_usable >= 0.65:
        return "EXPANSION"
    return "MIXED"


def build_symbol_diagnostic_tags(
    feature: Dict[str, Any],
    relative_strength_score: Optional[float],
    extension_score: float,
    fakeout_risk: float,
    execution_cost_score: float,
    long_score: float,
    short_score: float,
) -> List[str]:
    tags: List[str] = []
    if feature.get("direction_consensus", 0.5) >= 0.75:
        tags.append("direction_consensus_strong")
    if feature.get("volume_confirmation_15m", 0.0) >= 0.6:
        tags.append("volume_confirmed")
    if feature.get("taker_conflict_15m"):
        tags.append("taker_conflict")
    if execution_cost_score < 0.4:
        tags.append("execution_friction_high")
    if extension_score >= 0.65:
        tags.append("extended_move")
    if fakeout_risk >= 0.65:
        tags.append("fakeout_risk_high")
    if relative_strength_score is not None:
        if relative_strength_score >= 0.65:
            tags.append("relative_strength_leader")
        elif relative_strength_score <= 0.35:
            tags.append("relative_weakness_leader")
    if long_score - short_score >= 0.12:
        tags.append("long_edge")
    elif short_score - long_score >= 0.12:
        tags.append("short_edge")
    return tags


def determine_market_regime_detail(
    tradeability_score: float,
    chop_score: float,
    breakout_failure_risk: float,
    extension_mean: float,
    volume_health: float,
    volatility_level: float,
) -> str:
    if chop_score >= 0.64:
        return "CHOP"
    if breakout_failure_risk >= 0.7 and extension_mean >= 0.62:
        return "EXHAUSTION"
    if tradeability_score >= 0.68 and extension_mean >= 0.62:
        return "TREND_EXTENSION"
    if tradeability_score >= 0.7 and breakout_failure_risk <= 0.45 and extension_mean <= 0.42:
        return "TREND"
    if tradeability_score >= 0.58 and extension_mean < 0.6 and breakout_failure_risk < 0.56:
        return "TREND_PULLBACK"
    if volatility_level >= 0.7 and volume_health >= 0.6:
        return "EXPANSION"
    return "MIXED"


def build_market_diagnostic_tags(
    trend_breadth: float,
    low_adx_share: float,
    taker_conflict_share: float,
    breakout_failure_risk: float,
    extension_mean: float,
    long_environment_score: float,
    short_environment_score: float,
) -> List[str]:
    tags: List[str] = []
    if trend_breadth >= 0.6:
        tags.append("trend_breadth_strong")
    if low_adx_share >= 0.45:
        tags.append("low_adx_share_elevated")
    if taker_conflict_share >= 0.3:
        tags.append("taker_conflict_elevated")
    if breakout_failure_risk >= 0.6:
        tags.append("breakout_failure_elevated")
    if extension_mean >= 0.58:
        tags.append("market_extension_elevated")
    if long_environment_score - short_environment_score >= 0.12:
        tags.append("long_environment_dominant")
    elif short_environment_score - long_environment_score >= 0.12:
        tags.append("short_environment_dominant")
    return tags


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
    highs_15m = parsed_15m["highs"]
    lows_15m = parsed_15m["lows"]
    volumes_15m = parsed_15m["volumes"]

    price = closes_15m[-1] if closes_15m else None

    adx_15m = compute_adx(highs_15m, lows_15m, closes_15m)
    adx_1h = compute_adx(parsed_1h["highs"], parsed_1h["lows"], closes_1h)

    atr_15m = compute_atr(highs_15m, lows_15m, closes_15m)
    atrp_15m = compute_atr_percent(atr_15m, price)

    vol_ratio_15m = compute_vol_ratio(volumes_15m, period=20)

    taker_ratio, taker_dominance = compute_taker_dominance(
        parsed_15m["taker_buy_base"],
        volumes_15m,
        window=4,
    )

    dir_15m = compute_direction(closes_15m)
    dir_1h = compute_direction(closes_1h)

    bid = safe_float(book.get("bidPrice")) if book else None
    ask = safe_float(book.get("askPrice")) if book else None
    spread_bps = compute_spread_bps(bid, ask)

    returns_1h = compute_returns(closes_1h, periods=24)
    return_15m_4 = compute_window_return(closes_15m, periods=4)
    return_1h_6 = compute_window_return(closes_1h, periods=6)

    ema9_15m = last_value(ema(closes_15m, 9))
    ema21_15m = last_value(ema(closes_15m, 21))
    range_position_15m = compute_range_position(highs_15m, lows_15m, price, window=20)
    ema_distance_atr_15m = compute_ema_distance_atr(price, ema9_15m, atr_15m)
    volume_confirmation_15m = volume_score(vol_ratio_15m)
    taker_conflict_15m = compute_taker_conflict(dir_15m, taker_dominance)
    direction_consensus = compute_direction_consensus(dir_15m, dir_1h, return_15m_4, return_1h_6)

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
    }


def build_symbol_metrics(
    feature: Dict[str, Any],
    btc_direction: str,
    btc_feature: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    adx_15m = feature.get("adx_15m")
    spread_bps = feature.get("spread_bps")
    vol_ratio_15m = feature.get("vol_ratio_15m")
    atrp_15m = feature.get("atrp_15m")

    liquidity_score = liquidity_score_from_spread(spread_bps)
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
    taker_conflict = feature.get("taker_conflict_15m", False)
    if taker_conflict:
        flags.append("taker_conflict")

    relative_strength_score = relative_strength_from_returns(feature, btc_feature)
    execution_cost_score = execution_cost_score_from_feature(feature)
    extension_score = extension_score_from_feature(feature)
    fakeout_risk = fakeout_risk_from_feature(feature, execution_cost_score, extension_score)
    long_score = side_score_from_feature(
        "long",
        feature,
        relative_strength_score,
        execution_cost_score,
        extension_score,
        fakeout_risk,
    )
    short_score = side_score_from_feature(
        "short",
        feature,
        relative_strength_score,
        execution_cost_score,
        extension_score,
        fakeout_risk,
    )
    regime_label = determine_symbol_regime_label(feature, extension_score, fakeout_risk)
    diagnostic_tags = build_symbol_diagnostic_tags(
        feature,
        relative_strength_score,
        extension_score,
        fakeout_risk,
        execution_cost_score,
        long_score,
        short_score,
    )

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
        "relative_strength_score": relative_strength_score,
        "extension_score": extension_score,
        "fakeout_risk": fakeout_risk,
        "execution_cost_score": execution_cost_score,
        "long_score": long_score,
        "short_score": short_score,
        "regime_label": regime_label,
        "diagnostic_tags": diagnostic_tags,
    }


def build_market_metrics(
    features: List[Dict[str, Any]],
    btc_symbol: str = "BTCUSDT",
) -> Tuple[Dict[str, Any], str]:
    feature_map = {item["symbol"]: item for item in features}
    btc = feature_map.get(btc_symbol)

    adx_values = [item.get("adx_15m") for item in features if item.get("adx_15m") is not None]
    adx_mean = float(np.mean(adx_values)) if adx_values else 0.0
    low_adx_share = sum(1 for value in adx_values if value < 22) / len(adx_values) if adx_values else 0.0

    btc_direction = btc.get("dir_1h") if btc else "neutral"
    btc_trend_strength = normalize_range(btc.get("adx_1h") if btc else None, 20.0, 35.0)

    alt_features = [item for item in features if item.get("symbol") != btc_symbol]
    if not alt_features:
        alt_features = features

    alt_dirs = [item.get("dir_15m", "neutral") for item in alt_features]
    total_alts = len(alt_dirs)
    bull_ratio = alt_dirs.count("bullish") / total_alts if total_alts else 0.0
    bear_ratio = alt_dirs.count("bearish") / total_alts if total_alts else 0.0
    alt_bias = clamp(0.5 + 0.5 * (bull_ratio - bear_ratio), 0.0, 1.0)

    btc_returns = btc.get("returns_1h") if btc else None
    correlations = []
    if btc_returns:
        for item in alt_features:
            alt_returns = item.get("returns_1h")
            corr = pearson_corr(btc_returns, alt_returns) if alt_returns else None
            if corr is not None:
                correlations.append(corr)

    mean_corr = float(np.mean(correlations)) if correlations else 0.0
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

    trend_breadth = sum(
        1
        for item in features
        if (item.get("adx_15m") or 0) >= 22 and item.get("dir_15m") != "neutral"
    ) / len(features) if features else 0.0
    direction_consensus_mean = float(
        np.mean([item.get("direction_consensus", 0.5) for item in features])
    ) if features else 0.0
    liquidity_health = float(
        np.mean([liquidity_score_from_spread(item.get("spread_bps")) for item in features])
    ) if features else 0.0
    volatility_usability = float(
        np.mean([volatility_band_score(item.get("atrp_15m")) for item in features])
    ) if features else 0.0
    taker_conflict_share = float(
        np.mean([1.0 if item.get("taker_conflict_15m") else 0.0 for item in features])
    ) if features else 0.0
    taker_alignment = 1.0 - taker_conflict_share

    tradeability_score = clamp(
        0.30 * trend_breadth
        + 0.20 * direction_consensus_mean
        + 0.20 * liquidity_health
        + 0.15 * volatility_usability
        + 0.15 * taker_alignment,
        0.0,
        1.0,
    )

    directional_share = bull_ratio + bear_ratio
    if directional_share > 0:
        direction_dispersion = 1.0 - abs(bull_ratio - bear_ratio) / directional_share
    else:
        direction_dispersion = 1.0

    chop_score = clamp(
        0.45 * low_adx_share
        + 0.30 * direction_dispersion
        + 0.25 * taker_conflict_share,
        0.0,
        1.0,
    )

    extension_values = []
    fakeout_values = []
    long_scores = []
    short_scores = []
    for item in alt_features:
        relative_strength_score = relative_strength_from_returns(item, btc)
        execution_cost_score = execution_cost_score_from_feature(item)
        extension_score = extension_score_from_feature(item)
        fakeout_risk = fakeout_risk_from_feature(item, execution_cost_score, extension_score)
        extension_values.append(extension_score)
        fakeout_values.append(fakeout_risk)
        long_scores.append(
            side_score_from_feature(
                "long",
                item,
                relative_strength_score,
                execution_cost_score,
                extension_score,
                fakeout_risk,
            )
        )
        short_scores.append(
            side_score_from_feature(
                "short",
                item,
                relative_strength_score,
                execution_cost_score,
                extension_score,
                fakeout_risk,
            )
        )

    extension_mean = float(np.mean(extension_values)) if extension_values else 0.0
    fakeout_mean = float(np.mean(fakeout_values)) if fakeout_values else 0.0
    breakout_failure_risk = clamp(
        0.35 * fakeout_mean
        + 0.25 * extension_mean
        + 0.20 * taker_conflict_share
        + 0.20 * (1.0 - volume_health),
        0.0,
        1.0,
    )

    btc_bullish_support = 1.0 if btc_direction == "bullish" else 0.5 if btc_direction == "neutral" else 0.0
    btc_bearish_support = 1.0 if btc_direction == "bearish" else 0.5 if btc_direction == "neutral" else 0.0
    mean_long_score = float(np.mean(long_scores)) if long_scores else 0.0
    mean_short_score = float(np.mean(short_scores)) if short_scores else 0.0
    long_environment_score = clamp(
        0.55 * mean_long_score
        + 0.20 * btc_bullish_support
        + 0.15 * alt_bias
        + 0.10 * (1.0 - breakout_failure_risk),
        0.0,
        1.0,
    )
    short_environment_score = clamp(
        0.55 * mean_short_score
        + 0.20 * btc_bearish_support
        + 0.15 * (1.0 - alt_bias)
        + 0.10 * (1.0 - breakout_failure_risk),
        0.0,
        1.0,
    )

    market_regime = "SELECTIVE"
    if tradeability_score < 0.42 or chop_score > 0.68 or max(long_environment_score, short_environment_score) < 0.48:
        market_regime = "OFF"
    elif tradeability_score > 0.64 and breakout_failure_risk < 0.52 and max(long_environment_score, short_environment_score) > 0.58:
        market_regime = "TRENDING"

    recommended_mode = "SELECTIVE"
    if market_regime == "OFF":
        recommended_mode = "OFF"
    elif long_environment_score - short_environment_score >= 0.12 and long_environment_score >= 0.58:
        recommended_mode = "LONG_ONLY"
    elif short_environment_score - long_environment_score >= 0.12 and short_environment_score >= 0.58:
        recommended_mode = "SHORT_ONLY"

    regime_detail = determine_market_regime_detail(
        tradeability_score,
        chop_score,
        breakout_failure_risk,
        extension_mean,
        volume_health,
        volatility_level,
    )
    if regime_detail not in REGIME_DETAILS:
        regime_detail = "MIXED"

    market_diagnostic_tags = build_market_diagnostic_tags(
        trend_breadth,
        low_adx_share,
        taker_conflict_share,
        breakout_failure_risk,
        extension_mean,
        long_environment_score,
        short_environment_score,
    )

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
        "chop_ratio": low_adx_share,
        "atrp_mean_15m": atrp_mean,
        "btc_alt_corr_raw": mean_corr,
        "regime_detail": regime_detail,
        "long_environment_score": long_environment_score,
        "short_environment_score": short_environment_score,
        "breakout_failure_risk": breakout_failure_risk,
        "market_diagnostic_tags": market_diagnostic_tags,
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
                "relative_strength_score": item.get("relative_strength_score"),
                "extension_score": item.get("extension_score", 0.0),
                "fakeout_risk": item.get("fakeout_risk", 0.0),
                "execution_cost_score": item.get("execution_cost_score", 0.0),
                "long_score": item.get("long_score", 0.0),
                "short_score": item.get("short_score", 0.0),
                "regime_label": item.get("regime_label"),
                "diagnostic_tags": item.get("diagnostic_tags", []),
            }
        )
    return candidates
