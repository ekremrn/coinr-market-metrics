from __future__ import annotations

from typing import Any

from src.metrics import (
    build_market_metrics,
    build_symbol_features,
    build_symbol_metrics,
    select_candidates,
)


def _make_return_series(seed: float, drift: float, length: int = 24) -> list[float]:
    return [seed + drift * i for i in range(length)]


def make_feature(
    symbol: str,
    *,
    dir_1h: str,
    dir_15m: str,
    adx_15m: float,
    adx_1h: float = 32.0,
    atrp_15m: float = 0.8,
    vol_ratio_15m: float = 1.2,
    taker_dominance_15m: str = "neutral",
    spread_bps: float = 2.0,
    funding_rate: float = 0.0002,
    return_15m_4: float = 0.02,
    return_1h_6: float = 0.04,
    range_position_15m: float = 0.55,
    ema_distance_atr_15m: float = 0.6,
    direction_consensus: float = 0.8,
    volume_confirmation_15m: float = 0.7,
    taker_conflict_15m: bool | None = None,
    returns_1h: list[float] | None = None,
) -> dict[str, Any]:
    if taker_conflict_15m is None:
        taker_conflict_15m = (
            (taker_dominance_15m == "buy_dominant" and dir_15m == "bearish")
            or (taker_dominance_15m == "sell_dominant" and dir_15m == "bullish")
        )
    if returns_1h is None:
        returns_1h = _make_return_series(return_1h_6 / 6.0, 0.0001 if return_1h_6 >= 0 else -0.0001)
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
        "spread_bps": spread_bps,
        "returns_1h": returns_1h,
        "return_15m_4": return_15m_4,
        "return_1h_6": return_1h_6,
        "funding_rate": funding_rate,
        "range_position_15m": range_position_15m,
        "ema9_15m": 99.0,
        "ema21_15m": 98.0,
        "ema_distance_atr_15m": ema_distance_atr_15m,
        "volume_confirmation_15m": volume_confirmation_15m,
        "taker_conflict_15m": taker_conflict_15m,
        "direction_consensus": direction_consensus,
    }


def make_kline_series(prices: list[float], volume_base: float, taker_buy_ratio: float) -> list[list[float]]:
    rows = []
    prev = prices[0]
    for index, price in enumerate(prices):
        open_price = prev
        high = max(open_price, price) * 1.01
        low = min(open_price, price) * 0.99
        volume = volume_base + index * 20
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
                100 + index,
                volume * taker_buy_ratio,
                volume * taker_buy_ratio * price,
                0,
            ]
        )
        prev = price
    return rows


def test_build_symbol_features_adds_v11_feature_fields():
    prices_15m = [100 + i * 0.8 for i in range(40)]
    prices_1h = [100 + i * 1.4 for i in range(40)]
    feature = build_symbol_features(
        "ETHUSDT",
        make_kline_series(prices_15m, 1_000, 0.62),
        make_kline_series(prices_1h, 4_000, 0.61),
        {"bidPrice": 131.95, "askPrice": 132.05},
        0.0001,
    )

    assert feature["direction_consensus"] >= 0.75
    assert feature["range_position_15m"] is not None
    assert feature["ema_distance_atr_15m"] is not None
    assert feature["volume_confirmation_15m"] >= 0.0
    assert feature["return_15m_4"] is not None
    assert feature["return_1h_6"] is not None
    assert feature["taker_conflict_15m"] is False


def test_build_market_metrics_detects_bullish_trend_environment():
    btc = make_feature(
        "BTCUSDT",
        dir_1h="bullish",
        dir_15m="bullish",
        adx_15m=34.0,
        return_15m_4=0.015,
        return_1h_6=0.03,
        taker_dominance_15m="buy_dominant",
        direction_consensus=0.95,
        volume_confirmation_15m=0.85,
    )
    alts = [
        make_feature(
            f"ALT{i}USDT",
            dir_1h="bullish",
            dir_15m="bullish",
            adx_15m=30.0 + i,
            return_15m_4=0.02 + i * 0.002,
            return_1h_6=0.04 + i * 0.002,
            taker_dominance_15m="buy_dominant",
            direction_consensus=0.9,
            volume_confirmation_15m=0.8,
        )
        for i in range(4)
    ]

    market, _ = build_market_metrics([btc, *alts])

    assert market["market_regime"] == "TRENDING"
    assert market["recommended_mode"] == "LONG_ONLY"
    assert market["tradeability_score"] > 0.65
    assert market["long_environment_score"] > market["short_environment_score"]
    assert market["breakout_failure_risk"] < 0.55
    assert market["regime_detail"] in {"TREND", "TREND_PULLBACK", "TREND_EXTENSION"}


def test_build_market_metrics_detects_bearish_trend_environment():
    btc = make_feature(
        "BTCUSDT",
        dir_1h="bearish",
        dir_15m="bearish",
        adx_15m=35.0,
        return_15m_4=-0.018,
        return_1h_6=-0.05,
        taker_dominance_15m="sell_dominant",
        direction_consensus=0.93,
        volume_confirmation_15m=0.84,
        range_position_15m=0.15,
    )
    alts = [
        make_feature(
            f"ALT{i}USDT",
            dir_1h="bearish",
            dir_15m="bearish",
            adx_15m=29.0 + i,
            return_15m_4=-0.02 - i * 0.002,
            return_1h_6=-0.045 - i * 0.002,
            taker_dominance_15m="sell_dominant",
            direction_consensus=0.9,
            volume_confirmation_15m=0.78,
            range_position_15m=0.18,
        )
        for i in range(4)
    ]

    market, _ = build_market_metrics([btc, *alts])

    assert market["market_regime"] == "TRENDING"
    assert market["recommended_mode"] == "SHORT_ONLY"
    assert market["short_environment_score"] > market["long_environment_score"]
    assert market["tradeability_score"] > 0.65


def test_build_market_metrics_detects_chop_environment():
    btc = make_feature(
        "BTCUSDT",
        dir_1h="neutral",
        dir_15m="bullish",
        adx_15m=18.0,
        taker_dominance_15m="sell_dominant",
        direction_consensus=0.52,
        volume_confirmation_15m=0.3,
        taker_conflict_15m=True,
    )
    alts = [
        make_feature(
            f"ALT{i}USDT",
            dir_1h="bullish" if i % 2 == 0 else "bearish",
            dir_15m="bearish" if i % 2 == 0 else "bullish",
            adx_15m=17.0 + i,
            taker_dominance_15m="buy_dominant" if i % 2 else "sell_dominant",
            direction_consensus=0.5,
            volume_confirmation_15m=0.25,
            taker_conflict_15m=True,
            range_position_15m=0.5,
            ema_distance_atr_15m=0.2,
        )
        for i in range(4)
    ]

    market, _ = build_market_metrics([btc, *alts])

    assert market["market_regime"] == "OFF"
    assert market["recommended_mode"] == "OFF"
    assert market["chop_score"] > 0.65
    assert market["regime_detail"] == "CHOP"


def test_build_market_metrics_detects_exhaustion_environment():
    btc = make_feature(
        "BTCUSDT",
        dir_1h="bullish",
        dir_15m="bullish",
        adx_15m=31.0,
        taker_dominance_15m="buy_dominant",
        direction_consensus=0.88,
        volume_confirmation_15m=0.55,
        ema_distance_atr_15m=2.4,
        range_position_15m=0.98,
    )
    alts = [
        make_feature(
            f"ALT{i}USDT",
            dir_1h="bullish",
            dir_15m="bullish",
            adx_15m=29.0,
            taker_dominance_15m="sell_dominant",
            direction_consensus=0.8,
            volume_confirmation_15m=0.2,
            taker_conflict_15m=True,
            ema_distance_atr_15m=2.3,
            range_position_15m=0.99,
            spread_bps=7.5,
        )
        for i in range(4)
    ]

    market, _ = build_market_metrics([btc, *alts])

    assert market["breakout_failure_risk"] > 0.6
    assert market["regime_detail"] == "EXHAUSTION"
    assert "breakout_failure_elevated" in market["market_diagnostic_tags"]


def test_build_symbol_metrics_adds_relative_strength_and_side_scores():
    btc = make_feature(
        "BTCUSDT",
        dir_1h="bullish",
        dir_15m="bullish",
        adx_15m=30.0,
        return_15m_4=0.01,
        return_1h_6=0.02,
    )
    feature = make_feature(
        "XRPUSDT",
        dir_1h="bullish",
        dir_15m="bullish",
        adx_15m=31.0,
        taker_dominance_15m="buy_dominant",
        return_15m_4=0.03,
        return_1h_6=0.05,
        volume_confirmation_15m=0.9,
    )

    metrics = build_symbol_metrics(feature, "bullish", btc)

    assert metrics["relative_strength_score"] is not None
    assert metrics["relative_strength_score"] > 0.5
    assert metrics["long_score"] > metrics["short_score"]
    assert metrics["regime_label"] in {"TREND", "TREND_PULLBACK", "TREND_EXTENSION", "EXPANSION"}


def test_build_symbol_metrics_flags_extension_and_fakeout_without_new_compat_flags():
    btc = make_feature(
        "BTCUSDT",
        dir_1h="bullish",
        dir_15m="bullish",
        adx_15m=28.0,
        return_15m_4=0.015,
        return_1h_6=0.03,
    )
    feature = make_feature(
        "TAOUSDT",
        dir_1h="bullish",
        dir_15m="bullish",
        adx_15m=24.0,
        spread_bps=10.0,
        vol_ratio_15m=0.8,
        taker_dominance_15m="sell_dominant",
        taker_conflict_15m=True,
        volume_confirmation_15m=0.1,
        ema_distance_atr_15m=2.2,
        range_position_15m=0.98,
        direction_consensus=0.62,
    )

    metrics = build_symbol_metrics(feature, "bullish", btc)

    assert metrics["extension_score"] > 0.6
    assert metrics["fakeout_risk"] > 0.6
    assert "extended_move" in metrics["diagnostic_tags"]
    assert "fakeout_risk_high" in metrics["diagnostic_tags"]
    assert set(metrics["flags"]).issubset({"adx15_low", "high_spread", "volume_weak", "taker_conflict"})


def test_build_symbol_metrics_penalizes_execution_cost_from_spread():
    btc = make_feature(
        "BTCUSDT",
        dir_1h="bullish",
        dir_15m="bullish",
        adx_15m=32.0,
        return_15m_4=0.01,
        return_1h_6=0.02,
    )
    low_spread = build_symbol_metrics(
        make_feature(
            "SOLUSDT",
            dir_1h="bullish",
            dir_15m="bullish",
            adx_15m=30.0,
            spread_bps=1.5,
        ),
        "bullish",
        btc,
    )
    high_spread = build_symbol_metrics(
        make_feature(
            "SOLUSDT",
            dir_1h="bullish",
            dir_15m="bullish",
            adx_15m=30.0,
            spread_bps=11.0,
        ),
        "bullish",
        btc,
    )

    assert low_spread["execution_cost_score"] > high_spread["execution_cost_score"]


def test_build_symbol_metrics_can_prefer_short_without_changing_attractiveness_order():
    btc = make_feature(
        "BTCUSDT",
        dir_1h="bearish",
        dir_15m="bearish",
        adx_15m=31.0,
        return_15m_4=-0.015,
        return_1h_6=-0.03,
    )
    feature = make_feature(
        "ETHUSDT",
        dir_1h="bearish",
        dir_15m="bearish",
        adx_15m=29.0,
        taker_dominance_15m="sell_dominant",
        return_15m_4=-0.03,
        return_1h_6=-0.06,
        range_position_15m=0.12,
    )

    metrics = build_symbol_metrics(feature, "bearish", btc)

    assert metrics["short_score"] > metrics["long_score"]
    assert 0.0 <= metrics["attractiveness_score"] <= 1.0


def test_select_candidates_preserves_attractiveness_ranking():
    candidates = [
        {"symbol": "B", "attractiveness_score": 0.70, "flags": [], "dir_15m": "bullish", "dir_1h": "bullish"},
        {"symbol": "A", "attractiveness_score": 0.82, "flags": [], "dir_15m": "bearish", "dir_1h": "bearish"},
    ]

    ranked = select_candidates(candidates, k=2)

    assert [item["symbol"] for item in ranked] == ["A", "B"]
    assert all("diagnostic_tags" in item for item in ranked)
