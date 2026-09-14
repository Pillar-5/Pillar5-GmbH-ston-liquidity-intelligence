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
            "offer_units_raw": "1000000",
            "ask_units_raw": "2000000000",
            "offer_decimals": 6,
            "ask_decimals": 9,
            "min_ask_units": "1900000000",
            "swap_rate": 2.0,
            "slippage_tolerance": 0.01,
            "fee_units_raw": "6000000",
            "fee_address": "EQa",
            "gas_forward": 100000,
            "gas_consumption": 50000,
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
    assert samples[0]["offer_decimals"] == 6
    assert samples[0]["gas_forward"] == 100000
    assert db.execution_samples(market="NOPE") == []
    db.close()


def test_schema_migration_adds_columns(tmp_path):
    """An older database without the newer columns is upgraded on open."""
    import sqlite3

    from ston_liquidity_intelligence.repository import Repository

    db_path = str(tmp_path / "old.db")
    # Simulate the original schema that lacked the decimal/gas columns.
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE execution_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            observed_at TEXT NOT NULL, market TEXT NOT NULL,
            pool_address TEXT NOT NULL, direction TEXT NOT NULL,
            offer_address TEXT NOT NULL, ask_address TEXT NOT NULL,
            trade_size_base REAL, notional_usd REAL, offer_amount REAL,
            ask_amount REAL, effective_price REAL, reference_price REAL,
            execution_quality REAL, price_impact REAL, fee_percent REAL,
            fee_bps REAL, fee_amount_ask REAL
        )
        """
    )
    conn.commit()
    conn.close()

    db = Repository(db_path)  # should run the migration
    cols = {row[1] for row in db._conn.execute("PRAGMA table_info(execution_samples)")}
    assert "offer_decimals" in cols
    assert "ask_decimals" in cols
    assert "gas_forward" in cols
    assert "gas_consumption" in cols
    db.store_execution_samples(
        [
            {
                "observed_at": "2026-01-01T00:00:00Z",
                "market": "A/B",
                "pool_address": "p",
                "direction": "sell",
                "offer_address": "a",
                "ask_address": "b",
                "offer_decimals": 6,
                "ask_decimals": 9,
            }
        ]
    )
    assert db.execution_samples(market="A/B")[0]["offer_decimals"] == 6
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