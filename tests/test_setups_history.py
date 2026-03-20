from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient

from api.main import app
from api.routes import setups


client = TestClient(app)


def test_load_setup_history_filters_to_accepted_and_legacy_records(monkeypatch):
    captured = {}

    class FakeStore:
        def __init__(self, _cfg):
            pass

        def find(self, collection, query, projection, sort):
            captured["collection"] = collection
            captured["query"] = query
            captured["projection"] = projection
            captured["sort"] = sort
            return []

    def fake_mongo_config(uri="mongodb://localhost:27017", database="coinr"):
        return SimpleNamespace(uri=uri, database=database)

    monkeypatch.setattr(setups, "MongoStore", FakeStore)
    monkeypatch.setattr(setups, "MongoConfig", fake_mongo_config)

    assert setups._load_setup_history() == []
    assert captured["collection"] == "analyses"
    assert captured["projection"] == {"_id": 0, "position": 1}
    assert captured["sort"] == [("timestamp", -1)]
    assert captured["query"]["position"] == {"$ne": None}
    assert "$gte" in captured["query"]["timestamp"]
    assert captured["query"]["$or"] == [
        {"decision_stage": {"$in": ["HARD_ACCEPT", "REVIEWED_ACCEPT"]}},
        {"decision_stage": {"$exists": False}},
    ]


def test_setups_history_ignores_still_valid_setups(monkeypatch):
    now = datetime.now(timezone.utc)

    async def fake_get_json(_key):
        return None

    async def fake_set_json(_key, payload, ex=None):
        assert ex == 300
        assert len(payload) == 1
        assert payload[0]["symbol"] == "ETHUSDT"
        assert payload[0]["decision_context"]["decision_stage"] == "REVIEWED_ACCEPT"
        assert payload[0]["review"]["grade"] == "B"

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
                    "decision_context": {"decision_stage": "HARD_ACCEPT"},
                    "review": {"grade": "A"},
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
                    "decision_context": {
                        "decision_stage": "REVIEWED_ACCEPT",
                        "market_metrics": {
                            "snapshot_ts": (now - timedelta(minutes=91)).isoformat(),
                        },
                    },
                    "review": {
                        "grade": "B",
                        "confidence": 0.63,
                    },
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
            "decision_context": {
                "decision_stage": "REVIEWED_ACCEPT",
                "market_metrics": {
                    "snapshot_ts": (now - timedelta(minutes=91)).isoformat(),
                },
            },
            "review": {
                "grade": "B",
                "confidence": 0.63,
            },
            "timestamp": (now - timedelta(minutes=90)).isoformat(),
        }
    ]
