"""Per-symbol scoring functions that operate on feature dicts."""

from __future__ import annotations

from typing import Any, Dict, Optional

from src.utils import clamp
from .normalizers import (
    liquidity_score_from_spread,
    normalize_range,
    normalize_symmetric,
    volatility_band_score,
    volume_score,
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


def market_feature_weight(feature: Dict[str, Any]) -> float:
    liquidity = liquidity_score_from_spread(feature.get("spread_bps"))
    volume_confirmation = clamp(feature.get("volume_confirmation_15m", 0.0), 0.0, 1.0)
    trend_score = normalize_range(feature.get("adx_15m"), 22.0, 35.0)
    return clamp(0.20 + 0.35 * liquidity + 0.30 * volume_confirmation + 0.15 * trend_score, 0.10, 1.0)


def extension_score_from_feature(feature: Dict[str, Any], direction: str = "neutral") -> float:
    # direction-aware range-edge: near the TOP penalises longs, near the BOTTOM
    # penalises shorts.  Passing direction="neutral" keeps the old symmetric
    # behaviour (used for regime/fakeout risk where side is unknown).
    ema_distance_atr = feature.get("ema_distance_atr_15m")
    range_position = feature.get("range_position_15m")
    volume_confirmation = feature.get("volume_confirmation_15m", 0.0)
    rsi_15m = feature.get("rsi_15m")

    distance_score = normalize_range(ema_distance_atr, 0.8, 2.5)
    edge_score = 0.0
    if range_position is not None:
        if direction == "bullish":
            # Only penalise being near the top of the range for longs
            edge_score = clamp(2 * max(range_position - 0.5, 0.0), 0.0, 1.0)
        elif direction == "bearish":
            # Only penalise being near the bottom of the range for shorts
            edge_score = clamp(2 * max(0.5 - range_position, 0.0), 0.0, 1.0)
        else:
            edge_score = clamp(2 * abs(range_position - 0.5), 0.0, 1.0)

    # RSI momentum extension: overbought hurts longs, oversold hurts shorts.
    # When RSI is absent (test fixtures, missing data) fall back to old 3-component
    # weights so existing behaviour is preserved.
    if rsi_15m is not None:
        if direction == "bullish":
            rsi_ext = clamp((rsi_15m - 60.0) / 25.0, 0.0, 1.0)   # 0 at RSI≤60, 1 at RSI≥85
        elif direction == "bearish":
            rsi_ext = clamp((40.0 - rsi_15m) / 25.0, 0.0, 1.0)   # 0 at RSI≥40, 1 at RSI≤15
        else:
            rsi_ext = clamp(abs(rsi_15m - 50.0) / 30.0, 0.0, 1.0) # 0 at RSI=50, 1 at RSI=80/20
        return clamp(
            0.55 * distance_score
            + 0.25 * edge_score
            + 0.10 * volume_confirmation
            + 0.10 * rsi_ext,
            0.0,
            1.0,
        )

    return clamp(0.6 * distance_score + 0.3 * edge_score + 0.1 * volume_confirmation, 0.0, 1.0)


def exhaustion_risk_from_feature(feature: Dict[str, Any], side: str) -> float:
    ema_distance_atr = feature.get("ema_distance_atr_15m")
    range_position = feature.get("range_position_15m")
    volume_confirmation = clamp(feature.get("volume_confirmation_15m", 0.0), 0.0, 1.0)
    direction_consensus = clamp(feature.get("direction_consensus", 0.5), 0.0, 1.0)
    rsi_15m = feature.get("rsi_15m")

    distance_score = normalize_range(ema_distance_atr, 1.0, 2.7)
    if range_position is None:
        edge_score = 0.0
    else:
        edge_value = range_position if side == "long" else 1.0 - range_position
        edge_score = normalize_range(edge_value, 0.65, 1.0)

    if rsi_15m is None:
        rsi_score = 0.0
    elif side == "long":
        # Penalise from RSI 68 (not 62): RSI 62-68 is normal in a healthy trend.
        rsi_score = normalize_range(rsi_15m, 68.0, 82.0)
    else:
        # Short: penalise from RSI 32 (not 38); range 14 (was 18).
        rsi_score = normalize_range(32.0 - rsi_15m, 0.0, 14.0)

    weak_volume = 1.0 - volume_confirmation
    taker_conflict = 1.0 if feature.get("taker_conflict_15m") else 0.0
    local_chop = 1.0 - normalize_range(feature.get("adx_15m"), 22.0, 35.0)
    consensus_weakness = 1.0 - direction_consensus

    return clamp(
        0.28 * distance_score
        + 0.22 * edge_score
        + 0.18 * rsi_score
        + 0.14 * weak_volume
        + 0.10 * taker_conflict
        + 0.05 * local_chop
        + 0.03 * consensus_weakness,
        0.0,
        1.0,
    )


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
        + 0.15 * taker_conflict
        + 0.28 * weak_volume
        + 0.15 * extension_score
        + 0.17 * (1.0 - execution_cost_score),
        0.0,
        1.0,
    )


def side_entry_risk_from_feature(feature: Dict[str, Any], side: str) -> float:
    """Estimate how likely CoinR analysis will reject a setup on entry-location grounds.

    Semantically distinct from extension_score (which measures how far a move has
    travelled): entry_risk answers "is the current price a bad entry point?"

    CoinR analysis hard-rejects:
    - Longs when range_position_5m_12 > 0.80 (entry_at_range_top)
    - Shorts when range_position_5m_12 < 0.20 (entry_at_range_bottom)
    - Longs when resistance_distance_pct_15m < 1.0% (entry_too_close_to_resistance)
    - Shorts when support_distance_pct_15m < 1.0%  (entry_too_close_to_support)
    - Longs when 5m RSI > 78 (rsi_chase_long)
    - Shorts when 5m RSI < 22 (rsi_chase_short)

    Returns [0, 1] where 1 = almost certain rejection.
    Falls back gracefully to 0 for any missing field so the cap is not
    triggered when data is absent.
    """
    range_5m = feature.get("range_position_5m_12")
    range_15m = feature.get("range_position_15m")
    rsi_5m = feature.get("rsi_5m")

    if side == "long":
        res_dist = feature.get("resistance_distance_pct_15m")
        if (
            (range_5m is not None and range_5m > 0.80)
            or (res_dist is not None and res_dist < 1.0)
            or (rsi_5m is not None and rsi_5m > 78.0)
        ):
            return 1.0

        # 5m range position: 0 below 0.60, ramps to 1 at/above 0.80
        range5m_risk = normalize_range(range_5m, 0.60, 0.80) if range_5m is not None else 0.0

        # 15m range position: 0 below 0.60, ramps to 1 at/above 0.90
        range15m_risk = normalize_range(range_15m, 0.60, 0.90) if range_15m is not None else 0.0

        # Resistance proximity: full risk when distance < 1.0%
        if res_dist is None:
            res_risk = 0.0
        elif res_dist < 1.0:
            res_risk = 1.0
        else:
            # 0 at 3%+, ramps up as price approaches resistance
            res_risk = normalize_range(3.0 - res_dist, 0.0, 2.0)

        # RSI chase: 0 at RSI=65, 1 at RSI=78+
        if rsi_5m is None:
            rsi_risk = 0.0
        elif rsi_5m >= 78.0:
            rsi_risk = 1.0
        else:
            rsi_risk = normalize_range(rsi_5m, 65.0, 78.0)

        return clamp(
            0.40 * range5m_risk
            + 0.25 * range15m_risk
            + 0.25 * res_risk
            + 0.10 * rsi_risk,
            0.0,
            1.0,
        )
    else:  # short
        sup_dist = feature.get("support_distance_pct_15m")
        if (
            (range_5m is not None and range_5m < 0.20)
            or (sup_dist is not None and sup_dist < 1.0)
            or (rsi_5m is not None and rsi_5m < 22.0)
        ):
            return 1.0

        # 5m range position: 0 above 0.40, ramps to 1 at/below 0.20
        if range_5m is not None:
            range5m_risk = normalize_range(0.40 - range_5m, 0.0, 0.20)
        else:
            range5m_risk = 0.0

        # 15m range position: 0 above 0.40, ramps to 1 at/below 0.10
        if range_15m is not None:
            range15m_risk = normalize_range(0.40 - range_15m, 0.0, 0.30)
        else:
            range15m_risk = 0.0

        # Support proximity: full risk when distance < 1.0%
        if sup_dist is None:
            sup_risk = 0.0
        elif sup_dist < 1.0:
            sup_risk = 1.0
        else:
            sup_risk = normalize_range(3.0 - sup_dist, 0.0, 2.0)

        # RSI chase: 0 at RSI=35, 1 at RSI=22 or below
        if rsi_5m is None:
            rsi_risk = 0.0
        elif rsi_5m <= 22.0:
            rsi_risk = 1.0
        else:
            rsi_risk = normalize_range(35.0 - rsi_5m, 0.0, 13.0)

        return clamp(
            0.40 * range5m_risk
            + 0.25 * range15m_risk
            + 0.25 * sup_risk
            + 0.10 * rsi_risk,
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
    exhaustion_risk: float,
) -> float:
    dir_alignment = side_alignment_score(feature.get("dir_15m", "neutral"), feature.get("dir_1h", "neutral"), side)
    dominance = dominance_score_for_side(feature.get("taker_dominance_15m", "neutral"), side)
    relative = 0.5 if relative_strength_score is None else relative_strength_score
    relative_side = relative if side == "long" else 1.0 - relative
    trend_score = normalize_range(feature.get("adx_15m"), 22.0, 35.0)
    consensus = clamp(feature.get("direction_consensus", 0.5), 0.0, 1.0)
    volume_confirmation = clamp(feature.get("volume_confirmation_15m", 0.0), 0.0, 1.0)

    score = clamp(
        0.18 * dir_alignment
        + 0.08 * dominance
        + 0.12 * relative_side
        + 0.10 * (1.0 - extension_score)
        + 0.12 * (1.0 - fakeout_risk)
        + 0.12 * (1.0 - exhaustion_risk)
        + 0.10 * execution_cost_score
        + 0.07 * volume_confirmation
        + 0.09 * trend_score
        + 0.02 * consensus,
        0.0,
        1.0,
    )

    if volume_confirmation < 0.20:
        score *= 0.78
    if trend_score < 0.40 and consensus < 0.70:
        score *= 0.82
    if exhaustion_risk >= 0.60:
        score *= 0.84

    return clamp(score, 0.0, 1.0)
