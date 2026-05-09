"""Market-level metric aggregation: regime, environment scores, BTC correlation."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

import numpy as np

from src.utils import clamp
from .normalizers import (
    liquidity_score_from_spread,
    normalize_range,
    normalize_symmetric,
    pearson_corr,
    volatility_band_score,
    volume_score,
    weighted_mean,
)
from .scores import (
    exhaustion_risk_from_feature,
    execution_cost_score_from_feature,
    extension_score_from_feature,
    fakeout_risk_from_feature,
    market_feature_weight,
    relative_strength_from_returns,
    side_entry_risk_from_feature,
    side_score_from_feature,
)

REGIME_DETAILS = {
    "TREND",
    "TREND_PULLBACK",
    "TREND_EXTENSION",
    "CHOP",
    "EXPANSION",
    "EXHAUSTION",
    "MIXED",
}

_DIRECTIONAL_MODES = {"LONG_ONLY", "SHORT_ONLY"}
_BIAS_SMOOTHING_ALPHA = 0.45
_RAW_DIRECTIONAL_BIAS_THRESHOLD = 0.16
_RAW_DIRECTIONAL_ENV_FLOOR = 0.60


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


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _derive_raw_recommended_mode(
    *,
    market_regime: str,
    long_environment_score: float,
    short_environment_score: float,
) -> str:
    if str(market_regime).upper() == "OFF":
        return "OFF"
    if (
        long_environment_score - short_environment_score >= _RAW_DIRECTIONAL_BIAS_THRESHOLD
        and long_environment_score >= _RAW_DIRECTIONAL_ENV_FLOOR
    ):
        return "LONG_ONLY"
    if (
        short_environment_score - long_environment_score >= _RAW_DIRECTIONAL_BIAS_THRESHOLD
        and short_environment_score >= _RAW_DIRECTIONAL_ENV_FLOOR
    ):
        return "SHORT_ONLY"
    return "SELECTIVE"


def _ema(values: List[float], alpha: float) -> float:
    if not values:
        return 0.0
    ema_value = values[0]
    for value in values[1:]:
        ema_value = alpha * value + (1.0 - alpha) * ema_value
    return ema_value


def _historical_raw_env(market: Dict[str, Any], side: str) -> float | None:
    raw_key = "raw_long_environment_score" if side == "long" else "raw_short_environment_score"
    env_key = "long_environment_score" if side == "long" else "short_environment_score"
    raw_value = _safe_float(market.get(raw_key))
    if raw_value is not None:
        return clamp(raw_value, 0.0, 1.0)
    env_value = _safe_float(market.get(env_key))
    if env_value is None:
        return None
    return clamp(env_value, 0.0, 1.0)


def _historical_raw_mode(market: Dict[str, Any]) -> str:
    raw_mode = str(market.get("raw_recommended_mode") or "").upper()
    if raw_mode:
        return raw_mode

    resolved_mode = str(market.get("recommended_mode") or "").upper()
    if resolved_mode:
        return resolved_mode

    market_regime = str(market.get("market_regime") or "SELECTIVE").upper()
    long_env = _historical_raw_env(market, "long")
    short_env = _historical_raw_env(market, "short")
    if long_env is None or short_env is None:
        return "OFF" if market_regime == "OFF" else "SELECTIVE"
    return _derive_raw_recommended_mode(
        market_regime=market_regime,
        long_environment_score=long_env,
        short_environment_score=short_env,
    )


def _apply_mode_hysteresis(prev_state: str, prev_raw_mode: str, raw_mode: str) -> str:
    prev_state = str(prev_state or "SELECTIVE").upper()
    prev_raw_mode = str(prev_raw_mode or "SELECTIVE").upper()
    raw_mode = str(raw_mode or "SELECTIVE").upper()

    if raw_mode == "OFF":
        return "OFF"

    if prev_state == "OFF":
        if raw_mode == "SELECTIVE":
            return "SELECTIVE"
        return raw_mode if prev_raw_mode == raw_mode else "SELECTIVE"

    if prev_state == "SELECTIVE":
        if raw_mode in _DIRECTIONAL_MODES and prev_raw_mode == raw_mode:
            return raw_mode
        return raw_mode if raw_mode == "OFF" else "SELECTIVE"

    if raw_mode == prev_state:
        return prev_state

    if raw_mode in _DIRECTIONAL_MODES and raw_mode != prev_state:
        return "SELECTIVE" if prev_raw_mode != prev_state else prev_state

    return "SELECTIVE" if prev_raw_mode != prev_state else prev_state


def stabilize_market_bias(
    current_market: Dict[str, Any],
    history_markets: List[Dict[str, Any]] | None = None,
    *,
    alpha: float = _BIAS_SMOOTHING_ALPHA,
) -> Dict[str, Any]:
    """Smooth env scores with recent history and resolve mode with hysteresis."""
    history_markets = list(history_markets or [])
    market = dict(current_market)

    raw_long = clamp(_safe_float(current_market.get("long_environment_score")) or 0.0, 0.0, 1.0)
    raw_short = clamp(_safe_float(current_market.get("short_environment_score")) or 0.0, 0.0, 1.0)
    market_regime = str(current_market.get("market_regime") or "SELECTIVE").upper()

    historical_longs = [
        value
        for value in (_historical_raw_env(item, "long") for item in history_markets[-5:])
        if value is not None
    ]
    historical_shorts = [
        value
        for value in (_historical_raw_env(item, "short") for item in history_markets[-5:])
        if value is not None
    ]

    long_values = historical_longs + [raw_long]
    short_values = historical_shorts + [raw_short]
    smoothed_long = clamp(_ema(long_values, alpha), 0.0, 1.0) if len(long_values) >= 2 else raw_long
    smoothed_short = clamp(_ema(short_values, alpha), 0.0, 1.0) if len(short_values) >= 2 else raw_short
    bias_score = clamp(smoothed_long - smoothed_short, -1.0, 1.0)
    raw_mode = _derive_raw_recommended_mode(
        market_regime=market_regime,
        long_environment_score=smoothed_long,
        short_environment_score=smoothed_short,
    )

    resolved_mode = raw_mode
    if market_regime != "OFF":
        if len(history_markets) >= 1:
            history_slice = history_markets[-5:]
            state = str(
                history_slice[0].get("recommended_mode")
                or history_slice[0].get("raw_recommended_mode")
                or _historical_raw_mode(history_slice[0])
            ).upper()
            previous_raw_mode = _historical_raw_mode(history_slice[0])
            for item in history_slice[1:]:
                item_raw_mode = _historical_raw_mode(item)
                state = _apply_mode_hysteresis(state, previous_raw_mode, item_raw_mode)
                previous_raw_mode = item_raw_mode
            resolved_mode = _apply_mode_hysteresis(state, previous_raw_mode, raw_mode)
    else:
        resolved_mode = "OFF"

    market["raw_long_environment_score"] = raw_long
    market["raw_short_environment_score"] = raw_short
    market["long_environment_score"] = smoothed_long
    market["short_environment_score"] = smoothed_short
    market["bias_score"] = bias_score
    market["raw_recommended_mode"] = raw_mode
    market["recommended_mode"] = resolved_mode
    return market


def build_market_metrics(
    features: List[Dict[str, Any]],
    btc_symbol: str = "BTCUSDT",
) -> Tuple[Dict[str, Any], str]:
    feature_map = {item["symbol"]: item for item in features}
    btc = feature_map.get(btc_symbol)
    feature_weights = [market_feature_weight(item) for item in features]

    adx_values = [item.get("adx_15m") for item in features if item.get("adx_15m") is not None]
    adx_mean = float(np.mean(adx_values)) if adx_values else 0.0
    low_adx_share = weighted_mean(
        [1.0 if item.get("adx_15m") is not None and item.get("adx_15m") < 22 else 0.0 for item in features],
        feature_weights,
        0.0,
    )

    btc_direction = btc.get("dir_1h") if btc else "neutral"
    btc_trend_strength = normalize_range(btc.get("adx_1h") if btc else None, 20.0, 35.0)

    alt_features = [item for item in features if item.get("symbol") != btc_symbol]
    if not alt_features:
        alt_features = features
    alt_weights = [market_feature_weight(item) for item in alt_features]

    total_alt_weight = sum(alt_weights)
    bull_ratio = (
        sum(weight for item, weight in zip(alt_features, alt_weights) if item.get("dir_15m", "neutral") == "bullish")
        / total_alt_weight
        if total_alt_weight
        else 0.0
    )
    bear_ratio = (
        sum(weight for item, weight in zip(alt_features, alt_weights) if item.get("dir_15m", "neutral") == "bearish")
        / total_alt_weight
        if total_alt_weight
        else 0.0
    )
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

    # Weighted mean dampens illiquid tokens with extreme ATR% (e.g. a token at
    # 9% ATR gets low weight because its spread/volume score is near zero).
    atrp_mean = weighted_mean(
        [item.get("atrp_15m") for item in features],
        feature_weights,
        0.0,
    )
    volatility_level = normalize_range(atrp_mean, 0.3, 1.2)
    if atrp_mean <= 0.4:
        volatility_regime = "LOW"
    elif atrp_mean >= 1.0:
        volatility_regime = "HIGH"
    else:
        volatility_regime = "NORMAL"

    vol_scores = [volume_score(item.get("vol_ratio_15m")) for item in features]
    volume_health = weighted_mean(vol_scores, feature_weights, 0.0)

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

    trend_breadth = weighted_mean(
        [1.0 if (item.get("adx_15m") or 0) >= 22 and item.get("dir_15m") != "neutral" else 0.0 for item in features],
        feature_weights,
        0.0,
    )
    direction_consensus_mean = weighted_mean(
        [item.get("direction_consensus", 0.5) for item in features],
        feature_weights,
        0.0,
    )
    liquidity_health = weighted_mean(
        [liquidity_score_from_spread(item.get("spread_bps")) for item in features],
        feature_weights,
        0.0,
    )
    volatility_usability = weighted_mean(
        [volatility_band_score(item.get("atrp_15m")) for item in features],
        feature_weights,
        0.0,
    )
    taker_conflict_share = weighted_mean(
        [1.0 if item.get("taker_conflict_15m") else 0.0 for item in features],
        feature_weights,
        0.0,
    )
    taker_alignment = 1.0 - taker_conflict_share

    # volume_health has additive weight 0.28 — no multiplicative penalty on top,
    # which previously caused quadratic over-weighting and made the OFF regime
    # overly sticky during low-activity sessions.
    tradeability_score = clamp(
        0.22 * trend_breadth
        + 0.14 * direction_consensus_mean
        + 0.16 * liquidity_health
        + 0.10 * volatility_usability
        + 0.10 * taker_alignment
        + 0.28 * volume_health,
        0.0,
        1.0,
    )

    directional_share = bull_ratio + bear_ratio
    if directional_share > 0:
        direction_dispersion = 1.0 - abs(bull_ratio - bear_ratio) / directional_share
    else:
        direction_dispersion = 1.0

    chop_score = clamp(
        0.28 * low_adx_share
        + 0.22 * direction_dispersion
        + 0.18 * taker_conflict_share
        + 0.32 * (1.0 - volume_health),
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
        long_extension = extension_score_from_feature(item, direction="bullish")
        short_extension = extension_score_from_feature(item, direction="bearish")
        fakeout_risk = fakeout_risk_from_feature(item, execution_cost_score, extension_score)
        long_exhaustion_risk = exhaustion_risk_from_feature(item, "long")
        short_exhaustion_risk = exhaustion_risk_from_feature(item, "short")
        extension_values.append(extension_score)
        fakeout_values.append(fakeout_risk)
        long_s = side_score_from_feature(
            "long",
            item,
            relative_strength_score,
            execution_cost_score,
            long_extension,
            fakeout_risk,
            long_exhaustion_risk,
        )
        short_s = side_score_from_feature(
            "short",
            item,
            relative_strength_score,
            execution_cost_score,
            short_extension,
            fakeout_risk,
            short_exhaustion_risk,
        )
        # Apply the same hard caps used in build_symbol_metrics so that
        # market-level environment scores reflect the true tradeable quality
        # of the universe and do not trigger directional modes when most
        # symbols would be deterministically rejected by the analysis agent.
        _ENV_CAP = 0.60
        adx_val = item.get("adx_15m") or 0.0
        if adx_val < 25.0:
            long_s = min(long_s, _ENV_CAP)
            short_s = min(short_s, _ENV_CAP)
        dom_5m = item.get("taker_dominance_5m", "neutral")
        if dom_5m == "buy_dominant":
            short_s = min(short_s, _ENV_CAP)
        elif dom_5m == "sell_dominant":
            long_s = min(long_s, _ENV_CAP)
        if side_entry_risk_from_feature(item, "long") >= 0.70:
            long_s = min(long_s, _ENV_CAP)
        if side_entry_risk_from_feature(item, "short") >= 0.70:
            short_s = min(short_s, _ENV_CAP)
        rsi_5m_val = item.get("rsi_5m")
        if rsi_5m_val is not None:
            if rsi_5m_val > 78.0:
                long_s = min(long_s, _ENV_CAP)
            if rsi_5m_val < 22.0:
                short_s = min(short_s, _ENV_CAP)
        long_scores.append(long_s)
        short_scores.append(short_s)

    extension_mean = weighted_mean(extension_values, alt_weights, 0.0)
    fakeout_mean = weighted_mean(fakeout_values, alt_weights, 0.0)
    breakout_failure_risk = clamp(
        0.28 * fakeout_mean
        + 0.17 * extension_mean
        + 0.20 * taker_conflict_share
        + 0.35 * (1.0 - volume_health),
        0.0,
        1.0,
    )

    # Weight directional BTC signal by trend strength to prevent whipsaw flips
    # when EMA9/EMA21 crosses in a weak/choppy BTC market. btc_trend_strength is
    # normalize_range(adx_1h, 20, 35): 0 at ADX<20, 1.0 at ADX>35.
    # At minimum we apply 30% of the raw directional signal so some bias is kept.
    _btc_strength = max(btc_trend_strength if btc_trend_strength is not None else 0.3, 0.3)
    _btc_base_bull = 1.0 if btc_direction == "bullish" else 0.5 if btc_direction == "neutral" else 0.0
    _btc_base_bear = 1.0 if btc_direction == "bearish" else 0.5 if btc_direction == "neutral" else 0.0
    btc_bullish_support = 0.5 + (_btc_base_bull - 0.5) * _btc_strength
    btc_bearish_support = 0.5 + (_btc_base_bear - 0.5) * _btc_strength
    mean_long_score = weighted_mean(long_scores, alt_weights, 0.0)
    mean_short_score = weighted_mean(short_scores, alt_weights, 0.0)
    long_environment_score = clamp(
        0.42 * mean_long_score
        + 0.14 * btc_bullish_support
        + 0.08 * alt_bias
        + 0.18 * volume_health
        + 0.18 * (1.0 - breakout_failure_risk),
        0.0,
        1.0,
    )
    short_environment_score = clamp(
        0.42 * mean_short_score
        + 0.14 * btc_bearish_support
        + 0.08 * (1.0 - alt_bias)
        + 0.18 * volume_health
        + 0.18 * (1.0 - breakout_failure_risk),
        0.0,
        1.0,
    )
    market_regime = "SELECTIVE"
    if (
        tradeability_score < 0.50
        or chop_score > 0.62
        or volume_health < 0.12
        or breakout_failure_risk > 0.58
        or max(long_environment_score, short_environment_score) < 0.50
    ):
        market_regime = "OFF"
    elif (
        tradeability_score > 0.62
        and chop_score < 0.55
        and volume_health > 0.18
        and breakout_failure_risk < 0.45
        and max(long_environment_score, short_environment_score) > 0.60
    ):
        market_regime = "TRENDING"

    recommended_mode = "SELECTIVE"
    if market_regime == "OFF":
        recommended_mode = "OFF"
    else:
        directional_only_blocked = (
            volume_health < 0.18
            or breakout_failure_risk > 0.42
            or chop_score > 0.58
            or tradeability_score < 0.60
        )
        if not directional_only_blocked:
            if (
                mean_long_score > _ENV_CAP
                and long_environment_score - short_environment_score >= 0.18
                and long_environment_score >= 0.62
            ):
                recommended_mode = "LONG_ONLY"
            elif (
                mean_short_score > _ENV_CAP
                and short_environment_score - long_environment_score >= 0.18
                and short_environment_score >= 0.62
            ):
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
