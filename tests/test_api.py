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


def _sample(market="USDT/GRAM", observed_at="2026-01-01T00:00:00Z", trade=1.0, price=2.0):
    return {
        "observed_at": observed_at,
        "market": market,
        "pool_address": "p",
        "direction": "sell",
        "offer_address": "usdt",
        "ask_address": "ton",
        "trade_size_base": trade,
        "notional_usd": trade * 100.0,
        "offer_amount": trade,
        "ask_amount": trade * price,
        "effective_price": price,
        "reference_price": price,
        "execution_quality": 1.0,
        "price_impact": 0.0001,
        "fee_percent": 0.003,
        "fee_bps": 30.0,
        "fee_amount_ask": 0.006,
    }


def test_markets_view_shows_only_latest_run(tmp_path):
    """The API must not mix samples from different collection runs."""
    db = Repository(str(tmp_path / "runs.db"))
    db.store_execution_samples(
        [_sample(observed_at="2026-01-01T00:00:00Z", trade=1.0, price=2.0)]
    )
    db.store_execution_samples(
        [
            _sample(observed_at="2026-01-02T00:00:00Z", trade=1.0, price=3.0),
            _sample(observed_at="2026-01-02T00:00:00Z", trade=5.0, price=3.0),
        ]
    )
    app = create_app(Settings(db_path=str(tmp_path / "runs.db")))
    client = TestClient(app)

    markets = client.get("/api/markets").json()["markets"]
    assert len(markets) == 1
    assert markets[0]["observed_at"] == "2026-01-02T00:00:00Z"
    assert markets[0]["samples"] == 2

    ex = client.get("/api/execution", params={"market": "USDT/GRAM"}).json()
    assert len(ex["samples"]) == 2
    assert all(s["observed_at"] == "2026-01-02T00:00:00Z" for s in ex["samples"])

    # Historical samples stay available on request.
    hist = client.get(
        "/api/execution", params={"market": "USDT/GRAM", "latest": "false"}
    ).json()
    assert len(hist["samples"]) == 3
    assert db.close() is None


def test_empty_db_raises_404(tmp_path):
    Repository(str(tmp_path / "empty.db"))
    app = create_app(Settings(db_path=str(tmp_path / "empty.db")))
    client = TestClient(app)
    assert client.get("/api/summary").status_code == 404