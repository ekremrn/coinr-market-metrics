"""Tests for v1.3 entry-quality features, side_entry_risk, and side score caps.

Coverage:
- build_symbol_features returns 5m fields when klines_5m provided
- build_symbol_features returns None for 5m fields when klines_5m absent
- support/resistance distance and touch fields computed correctly
- side_entry_risk_from_feature returns high risk for bad entry locations
- build_symbol_metrics exposes all new v1.3 fields
- Hard caps: ADX < 25, opposite 5m taker, entry risk >= 0.70, RSI chase
- Clean trend: caps NOT triggered, scores remain above 0.65
- Candidate projection includes new v1.3 fields
- API SymbolMetrics model parses new fields correctly
- Scanner kline fetch: missing 5m is non-fatal
"""

from __future__ import annotations

from typing import Any

from src.metrics import build_symbol_features, build_symbol_metrics, select_candidates
from src.metrics.market import build_market_metrics
from src.metrics.scores import side_entry_risk_from_feature
from src.config import AppConfig
from api.models import SymbolMetrics


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def make_kline_series(
    prices: list[float],
    volume_base: float,
    taker_buy_ratio: float,
) -> list[list[float]]:
    rows = []
    prev = prices[0]
    for index, price in enumerate(prices):
        open_price = prev
        high = max(open_price, price) * 1.001
        low = min(open_price, price) * 0.999
        volume = volume_base + index * 10
        rows.append(
            [
                index * 60_000,
                open_price,
                high,
                low,
                price,
                volume,
                index * 60_000 + 59_000,
                volume * price,
                50 + index,
                volume * taker_buy_ratio,
                volume * taker_buy_ratio * price,
                0,
            ]
        )
        prev = price
    return rows


def make_feature(
    symbol: str = "TESTUSDT",
    *,
    dir_1h: str = "bullish",
    dir_15m: str = "bullish",
    adx_15m: float = 30.0,
    adx_1h: float = 32.0,
    atrp_15m: float = 0.8,
    vol_ratio_15m: float = 1.2,
    taker_dominance_15m: str = "neutral",
    taker_dominance_5m: str = "neutral",
    spread_bps: float = 2.0,
    funding_rate: float = 0.0002,
    return_15m_4: float = 0.02,
    return_1h_6: float = 0.04,
    range_position_15m: float = 0.55,
    range_position_5m_12: float | None = None,
    ema_distance_atr_15m: float = 0.6,
    direction_consensus: float = 0.8,
    volume_confirmation_15m: float = 0.7,
    rsi_15m: float = 58.0,
    rsi_5m: float | None = None,
    taker_conflict_15m: bool = False,
    support_distance_pct_15m: float | None = None,
    resistance_distance_pct_15m: float | None = None,
    support_touches_15m: int | None = None,
    resistance_touches_15m: int | None = None,
) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "price": 100.0,
        "dir_1h": dir_1h,
        "dir_15m": dir_15m,
        "adx_15m": adx_15m,
        "adx_1h": adx_1h,
        "atr_15m": 1.0,
        "atrp_15m": atrp_15m,
        "vol_ratio_15m": vol_ratio_15m,
        "taker_ratio_15m": 1.2,
        "taker_dominance_15m": taker_dominance_15m,
        "taker_dominance_5m": taker_dominance_5m,
        "spread_bps": spread_bps,
        "returns_1h": [return_1h_6 / 6.0] * 24,
        "return_15m_4": return_15m_4,
        "return_1h_6": return_1h_6,
        "funding_rate": funding_rate,
        "range_position_15m": range_position_15m,
        "range_position_5m_12": range_position_5m_12,
        "ema9_15m": 99.0,
        "ema21_15m": 98.0,
        "ema_distance_atr_15m": ema_distance_atr_15m,
        "volume_confirmation_15m": volume_confirmation_15m,
        "rsi_15m": rsi_15m,
        "rsi_5m": rsi_5m,
        "taker_conflict_15m": taker_conflict_15m,
        "direction_consensus": direction_consensus,
        "support_distance_pct_15m": support_distance_pct_15m,
        "resistance_distance_pct_15m": resistance_distance_pct_15m,
        "support_touches_15m": support_touches_15m,
        "resistance_touches_15m": resistance_touches_15m,
    }


BTC = make_feature("BTCUSDT", dir_1h="bullish", dir_15m="bullish", adx_15m=30.0)


# ---------------------------------------------------------------------------
# Phase B: build_symbol_features with 5m klines
# ---------------------------------------------------------------------------

def test_build_symbol_features_5m_fields_present_when_klines_provided():
    prices_15m = [100 + i * 0.5 for i in range(40)]
    prices_1h = [100 + i * 1.0 for i in range(40)]
    prices_5m = [100 + i * 0.2 for i in range(20)]

    feature = build_symbol_features(
        "ETHUSDT",
        make_kline_series(prices_15m, 1_000, 0.55),
        make_kline_series(prices_1h, 4_000, 0.55),
        {"bidPrice": "131.95", "askPrice": "132.05"},
        0.0001,
        klines_5m=make_kline_series(prices_5m, 500, 0.55),
    )

    assert feature["range_position_5m_12"] is not None
    assert 0.0 <= feature["range_position_5m_12"] <= 1.0
    assert feature["rsi_5m"] is not None
    assert feature["taker_dominance_5m"] in {"buy_dominant", "sell_dominant", "neutral"}


def test_build_symbol_features_5m_fields_absent_when_no_klines_5m():
    """Backward compatibility: no klines_5m → all 5m fields None / neutral."""
    prices_15m = [100 + i * 0.5 for i in range(40)]
    prices_1h = [100 + i * 1.0 for i in range(40)]

    feature = build_symbol_features(
        "ETHUSDT",
        make_kline_series(prices_15m, 1_000, 0.55),
        make_kline_series(prices_1h, 4_000, 0.55),
        {"bidPrice": "131.95", "askPrice": "132.05"},
        0.0001,
    )

    assert feature["range_position_5m_12"] is None
    assert feature["rsi_5m"] is None
    assert feature["taker_dominance_5m"] == "neutral"


def test_build_symbol_features_sr_distances_computed():
    """support/resistance distance fields are non-None in a typical series."""
    prices_15m = [100.0] * 120  # flat series — clear high/low exists
    prices_1h = [100.0] * 48
    prices_15m[60] = 102.0   # set a clear resistance
    prices_15m[61] = 98.0    # set a clear support

    feature = build_symbol_features(
        "BTCUSDT",
        make_kline_series(prices_15m, 1_000, 0.55),
        make_kline_series(prices_1h, 4_000, 0.55),
        {"bidPrice": "99.95", "askPrice": "100.05"},
    )

    # At minimum the 15m near window should yield values
    assert feature["support_distance_pct_15m"] is not None or feature["resistance_distance_pct_15m"] is not None
    if feature["support_distance_pct_15m"] is not None:
        assert feature["support_distance_pct_15m"] >= 0.0
    if feature["resistance_distance_pct_15m"] is not None:
        assert feature["resistance_distance_pct_15m"] >= 0.0


def test_build_symbol_features_touch_counts_are_non_negative_ints():
    prices_15m = [100 + (i % 3) * 0.5 for i in range(40)]
    prices_1h = [100 + i * 0.1 for i in range(40)]

    feature = build_symbol_features(
        "SOLUSDT",
        make_kline_series(prices_15m, 1_000, 0.55),
        make_kline_series(prices_1h, 4_000, 0.55),
        {"bidPrice": "99.95", "askPrice": "100.05"},
    )

    for key in ("support_touches_15m", "resistance_touches_15m"):
        if feature[key] is not None:
            assert isinstance(feature[key], int)
            assert feature[key] >= 0


def test_support_distance_ignores_support_levels_above_price():
    """A 1h 'support' above current price must not mask a valid 15m support."""
    feature = build_symbol_features(
        "BTCUSDT",
        make_kline_series([100.0] * 40, 1_000, 0.55),
        make_kline_series([106.0] * 40, 4_000, 0.55),
        {"bidPrice": "99.95", "askPrice": "100.05"},
    )

    assert feature["support_distance_pct_15m"] is not None
    assert feature["support_distance_pct_15m"] > 0.0


def test_resistance_distance_ignores_resistance_levels_below_price():
    """A 1h 'resistance' below current price must not mask a valid 15m resistance."""
    feature = build_symbol_features(
        "BTCUSDT",
        make_kline_series([100.0] * 40, 1_000, 0.55),
        make_kline_series([94.0] * 40, 4_000, 0.55),
        {"bidPrice": "99.95", "askPrice": "100.05"},
    )

    assert feature["resistance_distance_pct_15m"] is not None
    assert feature["resistance_distance_pct_15m"] > 0.0


# ---------------------------------------------------------------------------
# Phase C: side_entry_risk_from_feature
# ---------------------------------------------------------------------------

def test_side_entry_risk_long_high_when_at_range_top():
    feature = make_feature(range_position_5m_12=0.85, resistance_distance_pct_15m=3.0)
    risk = side_entry_risk_from_feature(feature, "long")
    assert risk == 1.0, f"Expected hard-block long entry risk, got {risk}"


def test_side_entry_risk_short_high_when_at_range_bottom():
    feature = make_feature(range_position_5m_12=0.15, support_distance_pct_15m=3.0)
    risk = side_entry_risk_from_feature(feature, "short")
    assert risk == 1.0, f"Expected hard-block short entry risk, got {risk}"


def test_side_entry_risk_range_boundaries_match_coinr_hard_rejects():
    long_boundary = make_feature(range_position_5m_12=0.80, resistance_distance_pct_15m=3.0, rsi_5m=55.0)
    long_blocked = make_feature(range_position_5m_12=0.8001, resistance_distance_pct_15m=3.0, rsi_5m=55.0)
    short_boundary = make_feature(range_position_5m_12=0.20, support_distance_pct_15m=3.0, rsi_5m=55.0)
    short_blocked = make_feature(range_position_5m_12=0.1999, support_distance_pct_15m=3.0, rsi_5m=55.0)

    assert side_entry_risk_from_feature(long_boundary, "long") < 1.0
    assert side_entry_risk_from_feature(long_blocked, "long") == 1.0
    assert side_entry_risk_from_feature(short_boundary, "short") < 1.0
    assert side_entry_risk_from_feature(short_blocked, "short") == 1.0


def test_side_entry_risk_long_high_when_near_resistance():
    feature = make_feature(resistance_distance_pct_15m=0.5, range_position_5m_12=0.5)
    risk = side_entry_risk_from_feature(feature, "long")
    assert risk == 1.0, f"Near resistance should hard-block long risk, got {risk}"


def test_side_entry_risk_short_high_when_near_support():
    feature = make_feature(support_distance_pct_15m=0.5, range_position_5m_12=0.5)
    risk = side_entry_risk_from_feature(feature, "short")
    assert risk == 1.0, f"Near support should hard-block short risk, got {risk}"


def test_side_entry_risk_low_when_mid_range_and_clear_distance():
    feature = make_feature(
        range_position_5m_12=0.50,
        range_position_15m=0.50,
        support_distance_pct_15m=3.0,
        resistance_distance_pct_15m=3.0,
        rsi_5m=55.0,
    )
    long_risk = side_entry_risk_from_feature(feature, "long")
    short_risk = side_entry_risk_from_feature(feature, "short")
    assert long_risk < 0.30, f"Mid-range long risk should be low, got {long_risk}"
    assert short_risk < 0.30, f"Mid-range short risk should be low, got {short_risk}"


def test_side_entry_risk_graceful_with_none_fields():
    feature = make_feature(range_position_5m_12=None, rsi_5m=None)
    long_risk = side_entry_risk_from_feature(feature, "long")
    short_risk = side_entry_risk_from_feature(feature, "short")
    assert 0.0 <= long_risk <= 1.0
    assert 0.0 <= short_risk <= 1.0


# ---------------------------------------------------------------------------
# Phase D: build_symbol_metrics exposes new fields
# ---------------------------------------------------------------------------

def test_build_symbol_metrics_exposes_all_v13_fields():
    metrics = build_symbol_metrics(make_feature(), "bullish", BTC)

    expected_fields = [
        "long_extension_score",
        "short_extension_score",
        "long_entry_risk",
        "short_entry_risk",
        "range_position_15m",
        "range_position_5m_12",
        "support_distance_pct_15m",
        "resistance_distance_pct_15m",
        "support_touches_15m",
        "resistance_touches_15m",
        "rsi_5m",
        "taker_dominance_5m",
    ]
    for field in expected_fields:
        assert field in metrics, f"Field '{field}' missing from build_symbol_metrics output"


def test_build_symbol_metrics_long_extension_and_short_extension_are_floats():
    metrics = build_symbol_metrics(make_feature(), "bullish", BTC)
    assert 0.0 <= metrics["long_extension_score"] <= 1.0
    assert 0.0 <= metrics["short_extension_score"] <= 1.0


# ---------------------------------------------------------------------------
# Phase D: Hard cap — ADX < 25
# ---------------------------------------------------------------------------

def test_adx_below_25_caps_both_side_scores():
    """ADX 15m < 25 → both long_score and short_score capped at 0.60.
    CoinR analysis hard-rejects adx_too_low at ADX 15m < 25.
    """
    feature = make_feature(
        dir_1h="bullish",
        dir_15m="bullish",
        adx_15m=22.0,  # below 25 cap threshold
        taker_dominance_15m="buy_dominant",
        direction_consensus=0.9,
        volume_confirmation_15m=0.85,
        return_15m_4=0.03,
        return_1h_6=0.05,
    )
    metrics = build_symbol_metrics(feature, "bullish", BTC)
    assert metrics["long_score"] <= 0.60, f"long_score {metrics['long_score']} should be capped at 0.60 (ADX=22)"
    assert metrics["short_score"] <= 0.60, f"short_score {metrics['short_score']} should be capped at 0.60 (ADX=22)"


def test_adx_above_25_does_not_trigger_adx_cap():
    """ADX = 28 → cap NOT applied from ADX alone."""
    feature = make_feature(
        dir_1h="bullish",
        dir_15m="bullish",
        adx_15m=28.0,
        taker_dominance_15m="buy_dominant",
        taker_dominance_5m="buy_dominant",
        direction_consensus=0.9,
        volume_confirmation_15m=0.85,
        range_position_5m_12=0.50,
        range_position_15m=0.50,
        rsi_5m=55.0,
        return_15m_4=0.03,
        return_1h_6=0.05,
        resistance_distance_pct_15m=3.0,
        support_distance_pct_15m=3.0,
    )
    metrics = build_symbol_metrics(feature, "bullish", BTC)
    # ADX is 28 (>= 25), taker aligned for long, mid range, no RSI chase
    # The long_score should be allowed above 0.60 in a clean setup
    assert metrics["long_score"] > 0.60, (
        f"ADX=28 with clean long setup should not be ADX-capped; long_score={metrics['long_score']}"
    )


# ---------------------------------------------------------------------------
# Phase D: Hard cap — opposite 5m taker dominance
# ---------------------------------------------------------------------------

def test_buy_dominant_5m_taker_caps_short_score():
    """5m taker buy_dominant → short_score capped at 0.60.
    CoinR rejects momentum_against_direction when taker opposes side.
    """
    feature = make_feature(
        dir_1h="bearish",
        dir_15m="bearish",
        adx_15m=30.0,
        taker_dominance_5m="buy_dominant",   # buy pressure → bad for shorts
        direction_consensus=0.85,
        volume_confirmation_15m=0.80,
        range_position_5m_12=0.50,
    )
    metrics = build_symbol_metrics(feature, "bearish", BTC)
    assert metrics["short_score"] <= 0.60, (
        f"buy_dominant 5m taker should cap short_score; got {metrics['short_score']}"
    )


def test_sell_dominant_5m_taker_caps_long_score():
    """5m taker sell_dominant → long_score capped at 0.60."""
    feature = make_feature(
        dir_1h="bullish",
        dir_15m="bullish",
        adx_15m=30.0,
        taker_dominance_5m="sell_dominant",  # sell pressure → bad for longs
        direction_consensus=0.85,
        volume_confirmation_15m=0.80,
        range_position_5m_12=0.50,
    )
    metrics = build_symbol_metrics(feature, "bullish", BTC)
    assert metrics["long_score"] <= 0.60, (
        f"sell_dominant 5m taker should cap long_score; got {metrics['long_score']}"
    )


def test_neutral_5m_taker_does_not_cap_from_taker():
    """5m taker neutral → no taker cap applied."""
    feature = make_feature(
        dir_1h="bullish",
        dir_15m="bullish",
        adx_15m=30.0,
        taker_dominance_5m="neutral",
        direction_consensus=0.85,
        volume_confirmation_15m=0.80,
        range_position_5m_12=0.50,
        resistance_distance_pct_15m=3.0,
        rsi_5m=55.0,
    )
    metrics = build_symbol_metrics(feature, "bullish", BTC)
    # Neutral taker + good setup → no taker cap; other caps must not fire either
    # (range mid, no RSI chase, ADX=30)
    assert metrics["long_score"] > 0.60, (
        f"Neutral 5m taker should not apply taker cap; long_score={metrics['long_score']}"
    )


# ---------------------------------------------------------------------------
# Phase D: Hard cap — entry risk >= 0.70
# ---------------------------------------------------------------------------

def test_range_top_5m_caps_long_score():
    """range_top 5m + near resistance → long_entry_risk >= 0.70 → long_score capped."""
    feature = make_feature(
        dir_1h="bullish",
        dir_15m="bullish",
        adx_15m=30.0,
        range_position_5m_12=0.90,
        range_position_15m=0.80,
        resistance_distance_pct_15m=0.5,
    )
    metrics = build_symbol_metrics(feature, "bullish", BTC)
    assert metrics["long_entry_risk"] >= 0.70, f"long_entry_risk={metrics['long_entry_risk']}"
    assert metrics["long_score"] <= 0.60, f"long_score {metrics['long_score']} should be capped"


def test_range_bottom_5m_caps_short_score():
    """range_bottom 5m + near support → short_entry_risk >= 0.70 → short_score capped."""
    feature = make_feature(
        dir_1h="bearish",
        dir_15m="bearish",
        adx_15m=30.0,
        range_position_5m_12=0.15,
        range_position_15m=0.12,
        support_distance_pct_15m=0.5,
    )
    metrics = build_symbol_metrics(feature, "bearish", BTC)
    assert metrics["short_entry_risk"] >= 0.70, f"short_entry_risk={metrics['short_entry_risk']}"
    assert metrics["short_score"] <= 0.60, f"short_score {metrics['short_score']} should be capped"


def test_near_resistance_caps_long_score():
    """near resistance + elevated range position → long_entry_risk >= 0.70 → capped."""
    feature = make_feature(
        dir_1h="bullish",
        dir_15m="bullish",
        adx_15m=30.0,
        range_position_5m_12=0.90,   # at extreme range top
        range_position_15m=0.80,     # 15m also elevated
        resistance_distance_pct_15m=0.5,  # < 1.0% → CoinR entry_too_close_to_resistance
    )
    metrics = build_symbol_metrics(feature, "bullish", BTC)
    assert metrics["long_entry_risk"] >= 0.70, f"long_entry_risk={metrics['long_entry_risk']}"
    assert metrics["long_score"] <= 0.60, f"long_score {metrics['long_score']} should be capped"


def test_near_support_caps_short_score():
    """near support + depressed range position → short_entry_risk >= 0.70 → capped."""
    feature = make_feature(
        dir_1h="bearish",
        dir_15m="bearish",
        adx_15m=30.0,
        range_position_5m_12=0.10,   # at extreme range bottom
        range_position_15m=0.12,     # 15m also low
        support_distance_pct_15m=0.5,  # < 1.0% → CoinR entry_too_close_to_support
    )
    metrics = build_symbol_metrics(feature, "bearish", BTC)
    assert metrics["short_entry_risk"] >= 0.70, f"short_entry_risk={metrics['short_entry_risk']}"
    assert metrics["short_score"] <= 0.60, f"short_score {metrics['short_score']} should be capped"


# ---------------------------------------------------------------------------
# Phase D: Hard cap — RSI chase (5m)
# ---------------------------------------------------------------------------

def test_rsi_chase_long_caps_long_score():
    """rsi_5m > 78 → long_score capped. CoinR hard-rejects rsi_chase_long."""
    feature = make_feature(
        dir_1h="bullish",
        dir_15m="bullish",
        adx_15m=30.0,
        rsi_5m=82.0,
        range_position_5m_12=0.50,
    )
    metrics = build_symbol_metrics(feature, "bullish", BTC)
    assert metrics["long_score"] <= 0.60, f"rsi_5m=82 should cap long_score; got {metrics['long_score']}"


def test_rsi_chase_short_caps_short_score():
    """rsi_5m < 22 → short_score capped. CoinR hard-rejects rsi_chase_short."""
    feature = make_feature(
        dir_1h="bearish",
        dir_15m="bearish",
        adx_15m=30.0,
        rsi_5m=18.0,
        range_position_5m_12=0.50,
    )
    metrics = build_symbol_metrics(feature, "bearish", BTC)
    assert metrics["short_score"] <= 0.60, f"rsi_5m=18 should cap short_score; got {metrics['short_score']}"


# ---------------------------------------------------------------------------
# Clean trend: no cap fires, strong side scores allowed above threshold
# ---------------------------------------------------------------------------

def test_clean_long_setup_scores_above_threshold():
    """ADX=30, aligned 5m taker, mid range, no RSI chase, clear S/R distance.
    None of the hard caps should fire; long_score should stay above 0.65.
    """
    feature = make_feature(
        dir_1h="bullish",
        dir_15m="bullish",
        adx_15m=30.0,
        taker_dominance_15m="buy_dominant",
        taker_dominance_5m="buy_dominant",
        direction_consensus=0.90,
        volume_confirmation_15m=0.85,
        range_position_5m_12=0.50,
        range_position_15m=0.52,
        rsi_15m=58.0,
        rsi_5m=56.0,
        return_15m_4=0.03,
        return_1h_6=0.05,
        support_distance_pct_15m=3.5,
        resistance_distance_pct_15m=3.5,
        ema_distance_atr_15m=0.5,
    )
    metrics = build_symbol_metrics(feature, "bullish", BTC)
    assert metrics["long_score"] > 0.65, (
        f"Clean long setup should score above 0.65; got {metrics['long_score']}"
    )


def test_clean_short_setup_scores_above_threshold():
    """ADX=30, aligned 5m sell_dominant taker, mid-low range, no RSI chase."""
    feature = make_feature(
        dir_1h="bearish",
        dir_15m="bearish",
        adx_15m=30.0,
        taker_dominance_15m="sell_dominant",
        taker_dominance_5m="sell_dominant",
        direction_consensus=0.90,
        volume_confirmation_15m=0.85,
        range_position_5m_12=0.50,
        range_position_15m=0.45,
        rsi_15m=42.0,
        rsi_5m=44.0,
        return_15m_4=-0.03,
        return_1h_6=-0.05,
        support_distance_pct_15m=3.5,
        resistance_distance_pct_15m=3.5,
        ema_distance_atr_15m=0.5,
    )
    btc_bearish = make_feature("BTCUSDT", dir_1h="bearish", dir_15m="bearish", adx_15m=30.0)
    metrics = build_symbol_metrics(feature, "bearish", btc_bearish)
    assert metrics["short_score"] > 0.65, (
        f"Clean short setup should score above 0.65; got {metrics['short_score']}"
    )


# ---------------------------------------------------------------------------
# Diagnostic tags
# ---------------------------------------------------------------------------

def test_diagnostic_tags_include_range_top_tag():
    feature = make_feature(range_position_5m_12=0.85)
    metrics = build_symbol_metrics(feature, "bullish", BTC)
    assert "long_entry_near_range_top" in metrics["diagnostic_tags"]


def test_diagnostic_tags_include_range_bottom_tag():
    feature = make_feature(range_position_5m_12=0.15)
    metrics = build_symbol_metrics(feature, "bearish", BTC)
    assert "short_entry_near_range_bottom" in metrics["diagnostic_tags"]


def test_diagnostic_tags_include_rsi_chase_long():
    feature = make_feature(rsi_5m=80.0)
    metrics = build_symbol_metrics(feature, "bullish", BTC)
    assert "rsi_chase_long" in metrics["diagnostic_tags"]


def test_diagnostic_tags_include_rsi_chase_short():
    feature = make_feature(rsi_5m=20.0)
    metrics = build_symbol_metrics(feature, "bearish", BTC)
    assert "rsi_chase_short" in metrics["diagnostic_tags"]


def test_diagnostic_tags_adx_cap_applied_when_adx_below_25():
    feature = make_feature(adx_15m=23.0)
    metrics = build_symbol_metrics(feature, "bullish", BTC)
    assert "adx_cap_applied" in metrics["diagnostic_tags"]


def test_diagnostic_tags_taker_5m_conflict():
    feature = make_feature(taker_dominance_5m="buy_dominant")
    metrics = build_symbol_metrics(feature, "bearish", BTC)
    assert "taker_5m_conflict_short" in metrics["diagnostic_tags"]


# ---------------------------------------------------------------------------
# Phase E: Candidate projection includes v1.3 fields
# ---------------------------------------------------------------------------

def test_select_candidates_includes_v13_fields():
    feature = make_feature(
        "ETHUSDT",
        adx_15m=30.0,
        range_position_5m_12=0.50,
        rsi_5m=55.0,
        support_distance_pct_15m=3.0,
        resistance_distance_pct_15m=3.0,
    )
    metrics = build_symbol_metrics(feature, "bullish", BTC)
    candidates = select_candidates([metrics], k=1)
    assert len(candidates) == 1
    c = candidates[0]

    new_fields = [
        "long_extension_score",
        "short_extension_score",
        "long_entry_risk",
        "short_entry_risk",
        "range_position_15m",
        "range_position_5m_12",
        "support_distance_pct_15m",
        "resistance_distance_pct_15m",
        "support_touches_15m",
        "resistance_touches_15m",
        "rsi_5m",
        "taker_dominance_5m",
    ]
    for field in new_fields:
        assert field in c, f"Candidate projection missing field '{field}'"


# ---------------------------------------------------------------------------
# Phase F: API SymbolMetrics model parses new fields
# ---------------------------------------------------------------------------

def _make_full_symbol_dict(**overrides) -> dict:
    base = {
        "symbol": "TESTUSDT",
        "dir_1h": "bullish",
        "dir_15m": "bullish",
        "adx_15m": 30.0,
        "spread_bps": 2.0,
        "atrp_15m": 0.8,
        "vol_ratio_15m": 1.2,
        "taker_dominance_15m": "neutral",
        "liquidity_score": 0.8,
        "trend_score": 0.7,
        "attractiveness_score": 0.7,
        "flags": [],
        "relative_strength_score": 0.55,
        "extension_score": 0.3,
        "long_extension_score": 0.28,
        "short_extension_score": 0.32,
        "long_exhaustion_risk": 0.2,
        "short_exhaustion_risk": 0.2,
        "fakeout_risk": 0.25,
        "execution_cost_score": 0.75,
        "long_score": 0.68,
        "short_score": 0.62,
        "long_entry_risk": 0.15,
        "short_entry_risk": 0.20,
        "range_position_15m": 0.55,
        "range_position_5m_12": 0.50,
        "support_distance_pct_15m": 3.0,
        "resistance_distance_pct_15m": 3.5,
        "support_touches_15m": 2,
        "resistance_touches_15m": 1,
        "rsi_5m": 56.0,
        "taker_dominance_5m": "neutral",
        "regime_label": "TREND",
        "diagnostic_tags": [],
    }
    base.update(overrides)
    return base


def test_symbol_metrics_model_parses_all_v13_fields():
    m = SymbolMetrics(**_make_full_symbol_dict())
    assert m.long_entry_risk == 0.15
    assert m.short_entry_risk == 0.20
    assert m.range_position_5m_12 == 0.50
    assert m.support_distance_pct_15m == 3.0
    assert m.resistance_distance_pct_15m == 3.5
    assert m.support_touches_15m == 2
    assert m.resistance_touches_15m == 1
    assert m.rsi_5m == 56.0
    assert m.taker_dominance_5m == "neutral"
    assert m.long_extension_score == 0.28
    assert m.short_extension_score == 0.32


def test_symbol_metrics_model_still_valid_without_new_fields():
    """Backward compat: new Optional fields can be absent (None)."""
    minimal = {
        "symbol": "TESTUSDT",
        "dir_1h": "bullish",
        "dir_15m": "bullish",
        "taker_dominance_15m": "neutral",
        "liquidity_score": 0.8,
        "trend_score": 0.7,
        "attractiveness_score": 0.7,
        "flags": [],
        "diagnostic_tags": [],
    }
    m = SymbolMetrics(**minimal)
    assert m.long_entry_risk is None
    assert m.range_position_5m_12 is None
    assert m.rsi_5m is None
    assert m.taker_dominance_5m is None


# ---------------------------------------------------------------------------
# Config defaults
# ---------------------------------------------------------------------------

def test_app_config_defaults_align_with_env_example(monkeypatch):
    monkeypatch.delenv("TOP_N", raising=False)
    monkeypatch.delenv("CANDIDATES_K", raising=False)

    cfg = AppConfig()
    assert cfg.top_n == 30
    assert cfg.candidates_k == 20


# ---------------------------------------------------------------------------
# Scanner partial error: missing 5m klines is non-fatal
# ---------------------------------------------------------------------------

def test_fetch_klines_missing_5m_creates_error_record_not_crash():
    """Missing 5m klines for a symbol should produce a record_error entry,
    not crash the entire scan.  We verify this by checking that
    build_symbol_features still works when klines_5m=None.
    """
    prices_15m = [100 + i * 0.5 for i in range(40)]
    prices_1h = [100 + i * 1.0 for i in range(40)]

    # klines_5m=None simulates the 5m data being missing for this symbol
    feature = build_symbol_features(
        "BTCUSDT",
        make_kline_series(prices_15m, 1_000, 0.55),
        make_kline_series(prices_1h, 4_000, 0.55),
        {"bidPrice": "131.95", "askPrice": "132.05"},
        klines_5m=None,
    )

    # Must not raise; 5m fields fall back to None / "neutral"
    assert feature["range_position_5m_12"] is None
    assert feature["rsi_5m"] is None
    assert feature["taker_dominance_5m"] == "neutral"

    # Must still be usable in build_symbol_metrics without crashing
    btc = make_feature("BTCUSDT")
    metrics = build_symbol_metrics(feature, "bullish", btc)
    assert "long_score" in metrics
    assert "short_score" in metrics


# ---------------------------------------------------------------------------
# Market-level environment score cap alignment
# ---------------------------------------------------------------------------

def _make_capped_feature(
    symbol: str,
    *,
    adx_15m: float = 20.0,
    taker_dominance_5m: str = "neutral",
    rsi_5m: float | None = None,
    range_position_5m_12: float | None = None,
    resistance_distance_pct_15m: float | None = None,
    support_distance_pct_15m: float | None = None,
) -> dict[str, Any]:
    """Build a feature dict that should trigger one or more hard caps."""
    return make_feature(
        symbol,
        adx_15m=adx_15m,
        dir_15m="bullish",
        dir_1h="bullish",
        taker_dominance_5m=taker_dominance_5m,
        rsi_5m=rsi_5m,
        range_position_5m_12=range_position_5m_12,
        resistance_distance_pct_15m=resistance_distance_pct_15m,
        support_distance_pct_15m=support_distance_pct_15m,
        volume_confirmation_15m=0.7,
        direction_consensus=0.8,
    )


def test_market_env_caps_adx_below_25():
    """When all symbols have ADX < 25, the cap logic must reduce long/short
    environment scores compared to a matched cohort with healthy ADX."""
    features_capped = [
        _make_capped_feature(f"COIN{i}USDT", adx_15m=19.0)
        for i in range(20)
    ]
    features_capped.append(make_feature("BTCUSDT", adx_15m=19.0))

    features_uncapped = [
        make_feature(
            f"COIN{i}USDT",
            adx_15m=32.0,
            dir_15m="bullish",
            dir_1h="bullish",
            taker_dominance_5m="neutral",
            volume_confirmation_15m=0.7,
            direction_consensus=0.8,
        )
        for i in range(20)
    ]
    features_uncapped.append(make_feature("BTCUSDT", adx_15m=32.0))

    market_capped, _ = build_market_metrics(features_capped)
    market_uncapped, _ = build_market_metrics(features_uncapped)

    # ADX < 25 cap must reduce long environment score vs healthy ADX universe
    assert market_capped["long_environment_score"] < market_uncapped["long_environment_score"], (
        f"Expected ADX<25 cap to reduce long_env but got "
        f"capped={market_capped['long_environment_score']:.4f}, "
        f"uncapped={market_uncapped['long_environment_score']:.4f}"
    )
    assert market_capped["short_environment_score"] < market_uncapped["short_environment_score"], (
        f"Expected ADX<25 cap to reduce short_env but got "
        f"capped={market_capped['short_environment_score']:.4f}, "
        f"uncapped={market_uncapped['short_environment_score']:.4f}"
    )


def test_market_env_capped_mean_blocks_directional_mode_even_when_env_is_high():
    """A capped universe must not emit LONG_ONLY just because aggregate env
    additives lift long_environment_score above the directional threshold."""
    features = [
        make_feature(
            f"COIN{i}USDT",
            adx_15m=24.0,  # caps both symbol side scores at 0.60
            adx_1h=35.0,
            dir_15m="bullish",
            dir_1h="bullish",
            taker_dominance_15m="buy_dominant",
            taker_dominance_5m="neutral",
            volume_confirmation_15m=0.5,
            vol_ratio_15m=0.5,
            spread_bps=0.5,
            direction_consensus=1.0,
            return_15m_4=0.04,
            return_1h_6=0.08,
        )
        for i in range(20)
    ]
    features.append(
        make_feature(
            "BTCUSDT",
            adx_15m=24.0,
            adx_1h=35.0,
            dir_15m="bullish",
            dir_1h="bullish",
            taker_dominance_15m="buy_dominant",
            volume_confirmation_15m=0.5,
            vol_ratio_15m=0.5,
            spread_bps=0.5,
            direction_consensus=1.0,
        )
    )

    market, _ = build_market_metrics(features)

    assert market["long_environment_score"] >= 0.62
    assert market["recommended_mode"] == "SELECTIVE"


def test_market_env_caps_sell_dominant_5m_taker():
    """Sell-dominant 5m taker should cap long scores per symbol, reducing
    long_environment_score relative to a neutral-taker control group."""
    features_sell_dom = [
        _make_capped_feature(f"COIN{i}USDT", adx_15m=30.0, taker_dominance_5m="sell_dominant")
        for i in range(20)
    ]
    features_sell_dom.append(make_feature("BTCUSDT", adx_15m=30.0))

    features_neutral = [
        _make_capped_feature(f"COIN{i}USDT", adx_15m=30.0, taker_dominance_5m="neutral")
        for i in range(20)
    ]
    features_neutral.append(make_feature("BTCUSDT", adx_15m=30.0))

    market_sell_dom, _ = build_market_metrics(features_sell_dom)
    market_neutral, _ = build_market_metrics(features_neutral)

    # Sell-dominant cap must reduce long_environment_score vs neutral baseline
    assert market_sell_dom["long_environment_score"] < market_neutral["long_environment_score"], (
        f"Expected sell_dominant taker cap to reduce long_env but got "
        f"sell_dom={market_sell_dom['long_environment_score']:.4f}, "
        f"neutral={market_neutral['long_environment_score']:.4f}"
    )


def test_market_env_caps_rsi_chase_long():
    """RSI > 78 on all symbols should cap long scores per symbol, reducing
    long_environment_score relative to a non-overbought control group."""
    features_chase = [
        _make_capped_feature(f"COIN{i}USDT", adx_15m=30.0, rsi_5m=82.0)
        for i in range(20)
    ]
    features_chase.append(make_feature("BTCUSDT", adx_15m=30.0))

    features_normal = [
        _make_capped_feature(f"COIN{i}USDT", adx_15m=30.0, rsi_5m=60.0)
        for i in range(20)
    ]
    features_normal.append(make_feature("BTCUSDT", adx_15m=30.0))

    market_chase, _ = build_market_metrics(features_chase)
    market_normal, _ = build_market_metrics(features_normal)

    # RSI chase cap must reduce long_environment_score vs non-overbought baseline
    assert market_chase["long_environment_score"] < market_normal["long_environment_score"], (
        f"Expected RSI chase cap to reduce long_env but got "
        f"chase={market_chase['long_environment_score']:.4f}, "
        f"normal={market_normal['long_environment_score']:.4f}"
    )


def test_market_env_no_caps_on_clean_trend():
    """A clean trending market must NOT be suppressed by the cap logic.
    Scores should be able to reach above 0.62."""
    features = [
        make_feature(
            f"COIN{i}USDT",
            adx_15m=33.0,
            dir_15m="bullish",
            dir_1h="bullish",
            taker_dominance_5m="buy_dominant",
            rsi_5m=62.0,
            volume_confirmation_15m=0.8,
            direction_consensus=0.9,
            range_position_5m_12=0.55,
            resistance_distance_pct_15m=3.0,
        )
        for i in range(20)
    ]
    features.append(make_feature("BTCUSDT", adx_15m=34.0, dir_15m="bullish", dir_1h="bullish"))

    market, _btc_dir = build_market_metrics(features)

    # In a genuine strong trend, long scores should be meaningfully above the
    # suppression cap — otherwise the cap itself is too aggressive.
    assert market["long_environment_score"] > 0.60, (
        f"long_environment_score={market['long_environment_score']:.4f} was unexpectedly capped "
        "in a clean trending market"
    )
    assert market["recommended_mode"] == "LONG_ONLY"
