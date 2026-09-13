"""Tests for the SQLite repository."""


def test_store_and_query_snapshots(tmp_path):
    from ston_liquidity_intelligence.repository import Repository

    db = Repository(str(tmp_path / "test.db"))
    db.store_snapshot("pools", "2026-01-01T00:00:00Z", [{"a": 1}])
    assert db.latest_snapshot("pools") == [{"a": 1}]
    assert db.latest_snapshot("assets") is None
    db.close()


def test_store_and_query_execution_samples(tmp_path):
    from ston_liquidity_intelligence.repository import Repository

    db = Repository(str(tmp_path / "test.db"))
    rows = [
        {
            "observed_at": "2026-01-01T00:00:00Z",
            "market": "USDT/TON",
            "pool_address": "EQp",
            "direction": "sell",
            "offer_address": "EQusdt",
            "ask_address": "EQa",
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
    inserted = db.store_execution_samples(rows)
    assert inserted == 1
    samples = db.execution_samples(market="USDT/TON")
    assert len(samples) == 1
    assert samples[0]["market"] == "USDT/TON"
    assert samples[0]["effective_price"] == 2.0
    assert db.execution_samples(market="NOPE") == []
    db.close()


def test_double_insert_counts(tmp_path):
    from ston_liquidity_intelligence.repository import Repository

    db = Repository(str(tmp_path / "test.db"))
    row = {
        "observed_at": "2026-01-01T00:00:00Z",
        "market": "A/B",
        "pool_address": "EQp",
        "direction": "sell",
        "offer_address": "a",
        "ask_address": "b",
        "trade_size_base": 1.0,
        "notional_usd": 1.0,
        "offer_amount": 1.0,
        "ask_amount": 1.0,
        "effective_price": 1.0,
        "reference_price": 1.0,
        "execution_quality": 1.0,
        "price_impact": 0.0,
        "fee_percent": 0.0,
        "fee_bps": 0.0,
        "fee_amount_ask": 0.0,
    }
    db.store_execution_samples([row])
    assert db.store_execution_samples([row]) == 1
    assert len(db.execution_samples(limit=100)) == 2
    db.close()