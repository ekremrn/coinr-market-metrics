"""Symbol-level metric assembly: regime label, diagnostic tags, full metrics dict."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.utils import clamp
from .normalizers import (
    alignment_score,
    liquidity_score_from_spread,
    normalize_range,
    volatility_band_score,
    volume_score,
)
from .scores import (
    exhaustion_risk_from_feature,
    execution_cost_score_from_feature,
    extension_score_from_feature,
    fakeout_risk_from_feature,
    relative_strength_from_returns,
    side_entry_risk_from_feature,
    side_score_from_feature,
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
    long_exhaustion_risk: float,
    short_exhaustion_risk: float,
    long_entry_risk: float = 0.0,
    short_entry_risk: float = 0.0,
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
    if long_exhaustion_risk >= 0.60:
        tags.append("long_exhaustion_high")
    if short_exhaustion_risk >= 0.60:
        tags.append("short_exhaustion_high")
    if relative_strength_score is not None:
        if relative_strength_score >= 0.65:
            tags.append("relative_strength_leader")
        elif relative_strength_score <= 0.35:
            tags.append("relative_weakness_leader")
    if long_score - short_score >= 0.12:
        tags.append("long_edge")
    elif short_score - long_score >= 0.12:
        tags.append("short_edge")
    rsi_15m = feature.get("rsi_15m")
    if rsi_15m is not None:
        if rsi_15m >= 70:
            tags.append("rsi_overbought")
        elif rsi_15m <= 30:
            tags.append("rsi_oversold")

    # Entry-location diagnostic tags — mirror CoinR analysis rejection codes
    range_5m = feature.get("range_position_5m_12")
    if range_5m is not None:
        if range_5m > 0.80:
            tags.append("long_entry_near_range_top")
        if range_5m < 0.20:
            tags.append("short_entry_near_range_bottom")

    res_dist = feature.get("resistance_distance_pct_15m")
    if res_dist is not None and res_dist < 1.0:
        tags.append("long_near_resistance")

    sup_dist = feature.get("support_distance_pct_15m")
    if sup_dist is not None and sup_dist < 1.0:
        tags.append("short_near_support")

    if long_entry_risk >= 0.70:
        tags.append("long_entry_risk_high")
    if short_entry_risk >= 0.70:
        tags.append("short_entry_risk_high")

    rsi_5m = feature.get("rsi_5m")
    if rsi_5m is not None:
        if rsi_5m > 78.0:
            tags.append("rsi_chase_long")
        if rsi_5m < 22.0:
            tags.append("rsi_chase_short")

    adx_15m = feature.get("adx_15m")
    if adx_15m is not None and adx_15m < 25.0:
        tags.append("adx_cap_applied")

    dom_5m = feature.get("taker_dominance_5m", "neutral")
    if dom_5m == "buy_dominant":
        tags.append("taker_5m_conflict_short")
    elif dom_5m == "sell_dominant":
        tags.append("taker_5m_conflict_long")

    return tags


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

    # Compute extension early so it can penalise attractiveness.
    ext_for_attractiveness = extension_score_from_feature(feature)

    attractiveness = (
        0.25 * trend_score
        + 0.22 * liquidity_score
        + 0.18 * align_score
        + 0.13 * vol_score
        + 0.10 * volm_score
        + 0.12 * (1.0 - ext_for_attractiveness)
    )
    attractiveness = clamp(attractiveness, 0.0, 1.0)

    flags = []
    if adx_15m is not None and adx_15m < 22:
        flags.append("adx15_low")
    if spread_bps is not None and spread_bps > 2.5:
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
    # Symmetric extension used for regime label and fakeout risk (side unknown).
    extension_score = ext_for_attractiveness
    # Direction-aware extensions: long penalises near-resistance; short near-support.
    long_extension = extension_score_from_feature(feature, direction="bullish")
    short_extension = extension_score_from_feature(feature, direction="bearish")
    fakeout_risk = fakeout_risk_from_feature(feature, execution_cost_score, extension_score)
    long_exhaustion_risk = exhaustion_risk_from_feature(feature, "long")
    short_exhaustion_risk = exhaustion_risk_from_feature(feature, "short")
    long_score = side_score_from_feature(
        "long",
        feature,
        relative_strength_score,
        execution_cost_score,
        long_extension,
        fakeout_risk,
        long_exhaustion_risk,
    )
    short_score = side_score_from_feature(
        "short",
        feature,
        relative_strength_score,
        execution_cost_score,
        short_extension,
        fakeout_risk,
        short_exhaustion_risk,
    )

    # Compute entry risks for scoring and cap logic.
    long_entry_risk = side_entry_risk_from_feature(feature, "long")
    short_entry_risk = side_entry_risk_from_feature(feature, "short")

    # Hard caps: prevent scanner-grade scores when CoinR analysis will
    # deterministically reject the setup.  Cap = 0.60 keeps the score clearly
    # below CoinR's 0.65 pre-filter threshold.
    _CAP = 0.60

    # ADX < 25 → both sides capped.  CoinR analysis hard-rejects adx_too_low
    # at ADX 15m < 25; the existing adx15_low flag uses 22 as a softer signal.
    adx_15m_val = adx_15m if adx_15m is not None else 0.0
    if adx_15m_val < 25.0:
        long_score = min(long_score, _CAP)
        short_score = min(short_score, _CAP)

    # Opposite 5m taker → cap the conflicted side.
    # CoinR uses 5m taker (10-bar, ratio > 1.15 / < 0.85) for momentum_against_direction.
    dom_5m = feature.get("taker_dominance_5m", "neutral")
    if dom_5m == "buy_dominant":
        short_score = min(short_score, _CAP)
    elif dom_5m == "sell_dominant":
        long_score = min(long_score, _CAP)

    # Entry risk ≥ 0.70 → cap that side (range top/bottom, near S/R)
    if long_entry_risk >= 0.70:
        long_score = min(long_score, _CAP)
    if short_entry_risk >= 0.70:
        short_score = min(short_score, _CAP)

    # 5m RSI chase → CoinR hard-rejects rsi_chase_long / rsi_chase_short
    rsi_5m_val = feature.get("rsi_5m")
    if rsi_5m_val is not None:
        if rsi_5m_val > 78.0:
            long_score = min(long_score, _CAP)
        if rsi_5m_val < 22.0:
            short_score = min(short_score, _CAP)

    regime_label = determine_symbol_regime_label(feature, extension_score, fakeout_risk)
    diagnostic_tags = build_symbol_diagnostic_tags(
        feature,
        relative_strength_score,
        extension_score,
        fakeout_risk,
        execution_cost_score,
        long_score,
        short_score,
        long_exhaustion_risk,
        short_exhaustion_risk,
        long_entry_risk=long_entry_risk,
        short_entry_risk=short_entry_risk,
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
        # Backward-compatible symmetric extension score (side unknown)
        "extension_score": extension_score,
        # Side-aware extension scores
        "long_extension_score": long_extension,
        "short_extension_score": short_extension,
        "long_exhaustion_risk": long_exhaustion_risk,
        "short_exhaustion_risk": short_exhaustion_risk,
        "fakeout_risk": fakeout_risk,
        "execution_cost_score": execution_cost_score,
        "long_score": long_score,
        "short_score": short_score,
        # Entry-quality fields
        "long_entry_risk": long_entry_risk,
        "short_entry_risk": short_entry_risk,
        "range_position_15m": feature.get("range_position_15m"),
        "range_position_5m_12": feature.get("range_position_5m_12"),
        "support_distance_pct_15m": feature.get("support_distance_pct_15m"),
        "resistance_distance_pct_15m": feature.get("resistance_distance_pct_15m"),
        "support_touches_15m": feature.get("support_touches_15m"),
        "resistance_touches_15m": feature.get("resistance_touches_15m"),
        "rsi_5m": feature.get("rsi_5m"),
        "taker_dominance_5m": feature.get("taker_dominance_5m", "neutral"),
        "regime_label": regime_label,
        "diagnostic_tags": diagnostic_tags,
    }
