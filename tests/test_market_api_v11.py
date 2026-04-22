from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from api.main import app
from api.routes import scanner


client = TestClient(app)


def make_market_state() -> dict:
    return {
        "tradeability_score": 0.71,
        "chop_score": 0.28,
        "market_regime": "TRENDING",
        "recommended_mode": "LONG_ONLY",
        "btc_direction_1h": "bullish",
        "btc_trend_strength": 0.76,
        "alt_directional_bias_15m": 0.72,
        "btc_alt_corr_mean_1h": 0.81,
        "btc_alt_corr_raw": 0.62,
        "correlation_regime": "COUPLED",
        "volatility_level_15m": 0.55,
        "volatility_regime": "NORMAL",
        "atrp_mean_15m": 0.74,
        "volume_health_15m": 0.68,
        "funding_rate_avg_8h": 0.56,
        "funding_rate_direction": "positive",
        "adx15_mean": 28.4,
        "chop_ratio": 0.18,
        "regime_detail": "TREND",
        "long_environment_score": 0.74,
        "short_environment_score": 0.41,
        "raw_long_environment_score": 0.77,
        "raw_short_environment_score": 0.38,
        "raw_recommended_mode": "LONG_ONLY",
        "bias_score": 0.33,
        "breakout_failure_risk": 0.32,
        "market_diagnostic_tags": ["trend_breadth_strong", "long_environment_dominant"],
    }


def make_symbol(symbol: str) -> dict:
    return {
        "symbol": symbol,
        "dir_1h": "bullish",
        "dir_15m": "bullish",
        "adx_15m": 31.0,
        "spread_bps": 2.1,
        "atrp_15m": 0.82,
        "vol_ratio_15m": 1.3,
        "taker_dominance_15m": "buy_dominant",
        "liquidity_score": 0.74,
        "trend_score": 0.69,
        "attractiveness_score": 0.77,
        "flags": [],
        "relative_strength_score": 0.63,
        "extension_score": 0.38,
        "long_exhaustion_risk": 0.24,
        "short_exhaustion_risk": 0.12,
        "fakeout_risk": 0.24,
        "execution_cost_score": 0.79,
        "long_score": 0.76,
        "short_score": 0.32,
        "regime_label": "TREND",
        "diagnostic_tags": ["direction_consensus_strong", "long_edge"],
    }


def make_snapshot(now: datetime) -> dict:
    market = make_market_state()
    symbols = [make_symbol("ETHUSDT")]
    return {
        "ts": now.isoformat(),
        "ts_ms": int(now.timestamp() * 1000),
        "version": "v1.1",
        "status": "ok",
        "errors": [],
        "universe": {
            "top_n": 20,
            "candidates_k": 5,
            "blacklist": [],
            "symbols": ["ETHUSDT"],
            "calc_symbols": ["BTCUSDT", "ETHUSDT"],
            "volume_ranked": [{"symbol": "ETHUSDT", "quote_volume": 1_000_000.0}],
            "total_symbols": 1,
        },
        "market": market,
        "symbols": symbols,
        "candidates": symbols,
    }


def test_market_route_returns_v11_snapshot(monkeypatch):
    now = datetime.now(timezone.utc)
    snapshot = make_snapshot(now)

    async def fake_get_json(key):
        if key == "market_state:latest":
            return snapshot
        if key == "market_state:candidates:latest":
            return snapshot["candidates"]
        return None

    monkeypatch.setattr(scanner.redis_store, "get_json", fake_get_json)

    response = client.get("/market")

    assert response.status_code == 200
    payload = response.json()
    assert payload["market_state"]["version"] == "v1.1"
    assert payload["market_state"]["market"]["regime_detail"] == "TREND"
    assert payload["market_state"]["market"]["raw_recommended_mode"] == "LONG_ONLY"
    assert payload["market_state"]["market"]["bias_score"] == 0.33
    assert "market_diagnostic_tags" in payload["market_state"]["market"]
    assert "diagnostic_tags" in payload["candidates"][0]


def test_market_history_parses_v11_fields(monkeypatch):
    now = datetime.now(timezone.utc)
    history_doc = {
        "ts": (now - timedelta(hours=1)).isoformat(),
        "ts_ms": int((now - timedelta(hours=1)).timestamp() * 1000),
        "market": make_market_state(),
    }

    async def fake_get_json(_key):
        return None

    async def fake_set_json(_key, payload, ex=None):
        assert ex == 300
        assert payload[0]["market"]["regime_detail"] == "TREND"

    def fake_load_market_history():
        return [history_doc]

    monkeypatch.setattr(scanner.redis_store, "get_json", fake_get_json)
    monkeypatch.setattr(scanner.redis_store, "set_json", fake_set_json)
    monkeypatch.setattr(scanner, "_load_market_history", fake_load_market_history)

    response = client.get("/market/history")

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["market"]["regime_detail"] == "TREND"
    assert payload[0]["market"]["long_environment_score"] == history_doc["market"]["long_environment_score"]
    assert payload[0]["market"]["raw_long_environment_score"] == history_doc["market"]["raw_long_environment_score"]
