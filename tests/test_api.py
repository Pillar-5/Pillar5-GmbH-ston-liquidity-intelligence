"""Tests for the FastAPI REST layer.

These are skipped automatically when the ``api`` extra (fastapi/uvicorn) is not
installed, e.g. in a minimal CI run.
"""

import pytest

fastapi = pytest.importorskip("fastapi")
TestClient = pytest.importorskip("fastapi.testclient").TestClient

from ston_liquidity_intelligence.api import create_app
from ston_liquidity_intelligence.config import Settings
from ston_liquidity_intelligence.repository import Repository


def _seed_db(tmp_path):
    db = Repository(str(tmp_path / "api.db"))
    db.store_snapshot("assets", "2026-01-01T00:00:00Z", [{"contract_address": "a", "symbol": "A"}])
    db.store_snapshot("routers", "2026-01-01T00:00:00Z", [{"address": "r"}])
    db.store_snapshot(
        "pools",
        "2026-01-01T00:00:00Z",
        [{"address": "p", "lp_total_supply_usd": "100000", "volume_24h_usd": "5000", "deprecated": False}],
    )
    db.store_execution_samples(
        [
            {
                "observed_at": "2026-01-01T00:00:00Z",
                "market": "USDT/GRAM",
                "pool_address": "p",
                "direction": "sell",
                "offer_address": "usdt",
                "ask_address": "ton",
                "trade_size_base": 1.0,
                "notional_usd": 100.0,
                "offer_amount": 1.0,
                "ask_amount": 2.0,
                "effective_price": 2.0,
                "reference_price": 2.0,
                "execution_quality": 1.0,
                "price_impact": 0.0001,
                "fee_percent": 0.003,
                "fee_bps": 30.0,
                "fee_amount_ask": 0.006,
            }
        ]
    )
    return db


def test_health_and_summary(tmp_path):
    _seed_db(tmp_path)
    app = create_app(Settings(db_path=str(tmp_path / "api.db")))
    client = TestClient(app)
    assert client.get("/health").json()["status"] == "ok"
    summary = client.get("/api/summary").json()
    assert summary["discovery"]["pools"] == 1
    assert summary["liquidity"]["total_liquidity_usd_est"] == 100000.0
    assert summary["markets_evaluated"] == 1
    assert summary["markets_selected"] == 1
    assert summary["execution_samples"] == 1


def test_markets_and_execution(tmp_path):
    _seed_db(tmp_path)
    app = create_app(Settings(db_path=str(tmp_path / "api.db")))
    client = TestClient(app)
    markets = client.get("/api/markets").json()["markets"]
    assert markets[0]["market"] == "USDT/GRAM"
    ex = client.get("/api/execution", params={"market": "USDT/GRAM"}).json()
    assert len(ex["samples"]) == 1
    assert ex["samples"][0]["execution_quality"] == 1.0


def test_dashboard_html(tmp_path):
    _seed_db(tmp_path)
    app = create_app(Settings(db_path=str(tmp_path / "api.db")))
    resp = TestClient(app).get("/")
    assert resp.status_code == 200
    assert "STON.fi" in resp.text


def test_empty_db_raises_404(tmp_path):
    Repository(str(tmp_path / "empty.db"))
    app = create_app(Settings(db_path=str(tmp_path / "empty.db")))
    client = TestClient(app)
    assert client.get("/api/summary").status_code == 404