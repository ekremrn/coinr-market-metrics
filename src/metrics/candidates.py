"""Candidate selection: rank symbols by attractiveness and pick top-k."""

from __future__ import annotations

from typing import Any, Dict, List


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
                "long_extension_score": item.get("long_extension_score"),
                "short_extension_score": item.get("short_extension_score"),
                "long_exhaustion_risk": item.get("long_exhaustion_risk", 0.0),
                "short_exhaustion_risk": item.get("short_exhaustion_risk", 0.0),
                "fakeout_risk": item.get("fakeout_risk", 0.0),
                "execution_cost_score": item.get("execution_cost_score", 0.0),
                "long_score": item.get("long_score", 0.0),
                "short_score": item.get("short_score", 0.0),
                "long_entry_risk": item.get("long_entry_risk"),
                "short_entry_risk": item.get("short_entry_risk"),
                "range_position_15m": item.get("range_position_15m"),
                "range_position_5m_12": item.get("range_position_5m_12"),
                "support_distance_pct_15m": item.get("support_distance_pct_15m"),
                "resistance_distance_pct_15m": item.get("resistance_distance_pct_15m"),
                "support_touches_15m": item.get("support_touches_15m"),
                "resistance_touches_15m": item.get("resistance_touches_15m"),
                "rsi_5m": item.get("rsi_5m"),
                "taker_dominance_5m": item.get("taker_dominance_5m", "neutral"),
                "regime_label": item.get("regime_label"),
                "diagnostic_tags": item.get("diagnostic_tags", []),
            }
        )
    return candidates
