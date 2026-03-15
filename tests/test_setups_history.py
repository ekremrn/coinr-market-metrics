from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from api.main import app
from api.routes import setups


client = TestClient(app)


def test_setups_history_ignores_still_valid_setups(monkeypatch):
    now = datetime.now(timezone.utc)

    async def fake_get_json(_key):
        return None

    async def fake_set_json(_key, payload, ex=None):
        assert ex == 300
        assert len(payload) == 1
        assert payload[0]["symbol"] == "ETHUSDT"

    def fake_load_setup_history():
        return [
            {
                "position": {
                    "symbol": "BTCUSDT",
                    "position_type": "long",
                    "entry_price": 65000.0,
                    "stop_loss_price": 64000.0,
                    "take_profit_prices": [66000.0],
                    "valid_for_minutes": 60,
                    "notes": ["still valid"],
                    "timestamp": (now - timedelta(minutes=10)).isoformat(),
                }
            },
            {
                "position": {
                    "symbol": "ETHUSDT",
                    "position_type": "short",
                    "entry_price": 3200.0,
                    "stop_loss_price": 3300.0,
                    "take_profit_prices": [3100.0],
                    "valid_for_minutes": 60,
                    "notes": ["expired"],
                    "timestamp": (now - timedelta(minutes=90)).isoformat(),
                }
            },
        ]

    monkeypatch.setattr(setups.redis_store, "get_json", fake_get_json)
    monkeypatch.setattr(setups.redis_store, "set_json", fake_set_json)
    monkeypatch.setattr(setups, "_load_setup_history", fake_load_setup_history)

    response = client.get("/setups/history")

    assert response.status_code == 200
    assert response.json() == [
        {
            "symbol": "ETHUSDT",
            "position_type": "short",
            "entry_price": 3200.0,
            "stop_loss_price": 3300.0,
            "take_profit_prices": [3100.0],
            "valid_for_minutes": 60,
            "notes": ["expired"],
            "timestamp": (now - timedelta(minutes=90)).isoformat(),
        }
    ]
