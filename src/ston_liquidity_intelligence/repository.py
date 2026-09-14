"""SQLite-backed persistence for snapshots and execution samples.

Two kinds of rows are stored:

- ``snapshots``  - raw collections of assets/routers/pools at a point in time
- ``execution_samples`` - per-swap execution metrics used for analytics

All data is parameterised as JSON/float/text so the schema stays stable while
the underlying STON.fi API evolves.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable, Optional


class Repository:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        # The FastAPI layer serves read requests from a worker thread pool, so
        # allow cross-thread use and serialise access with a lock.
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._init_schema()

    # ------------------------------------------------------------------ schema
    def _init_schema(self) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS snapshots (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_type TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                payload     TEXT NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_snapshots_type_time
            ON snapshots (snapshot_type, observed_at)
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS execution_samples (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                observed_at    TEXT NOT NULL,
                market         TEXT NOT NULL,
                pool_address   TEXT NOT NULL,
                direction      TEXT NOT NULL,
                offer_address  TEXT NOT NULL,
                ask_address    TEXT NOT NULL,
                offer_units_raw TEXT,
                ask_units_raw  TEXT,
                offer_decimals INTEGER,
                ask_decimals   INTEGER,
                min_ask_units  TEXT,
                swap_rate      REAL,
                slippage_tolerance REAL,
                fee_units_raw  TEXT,
                fee_address    TEXT,
                gas_forward    REAL,
                gas_consumption REAL,
                trade_size_base REAL,
                notional_usd   REAL,
                offer_amount   REAL,
                ask_amount     REAL,
                effective_price REAL,
                reference_price REAL,
                execution_quality REAL,
                price_impact   REAL,
                fee_percent    REAL,
                fee_bps        REAL,
                fee_amount_ask REAL
            )
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_samples_time
            ON execution_samples (observed_at)
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_samples_market
            ON execution_samples (market, observed_at)
            """
        )
        self._conn.commit()
        self._migrate_samples()

    def _migrate_samples(self) -> None:
        """Add any columns introduced after the initial schema creation.

        This keeps older databases usable when the schema evolves, so a fresh
        clone does not need to start over.
        """
        cols = {
            "offer_units_raw": "TEXT",
            "ask_units_raw": "TEXT",
            "offer_decimals": "INTEGER",
            "ask_decimals": "INTEGER",
            "min_ask_units": "TEXT",
            "swap_rate": "REAL",
            "slippage_tolerance": "REAL",
            "fee_units_raw": "TEXT",
            "fee_address": "TEXT",
            "gas_forward": "REAL",
            "gas_consumption": "REAL",
        }
        existing = {row[1] for row in self._conn.execute("PRAGMA table_info(execution_samples)")}
        for name, decl in cols.items():
            if name not in existing:
                self._conn.execute(f"ALTER TABLE execution_samples ADD COLUMN {name} {decl}")
        self._conn.commit()

    # --------------------------------------------------------------- snapshots
    def store_snapshot(self, snapshot_type: str, observed_at: str, payload: Any) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO snapshots (snapshot_type, observed_at, payload) VALUES (?, ?, ?)",
                (snapshot_type, observed_at, json.dumps(payload)),
            )
            self._conn.commit()

    def latest_snapshot(self, snapshot_type: str) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT payload FROM snapshots WHERE snapshot_type = ? ORDER BY observed_at DESC LIMIT 1",
                (snapshot_type,),
            ).fetchone()
        if row is None:
            return None
        return json.loads(row["payload"])

    # ------------------------------------------------------- execution samples
    def store_execution_samples(self, rows: Iterable[dict]) -> int:
        values: list[tuple] = []
        for s in rows:
            values.append(
                (
                    s.get("observed_at"),
                    s.get("market"),
                    s.get("pool_address"),
                    s.get("direction"),
                    s.get("offer_address"),
                    s.get("ask_address"),
                    s.get("offer_units_raw"),
                    s.get("ask_units_raw"),
                    s.get("offer_decimals"),
                    s.get("ask_decimals"),
                    s.get("min_ask_units"),
                    s.get("swap_rate"),
                    s.get("slippage_tolerance"),
                    s.get("fee_units_raw"),
                    s.get("fee_address"),
                    s.get("gas_forward"),
                    s.get("gas_consumption"),
                    s.get("trade_size_base"),
                    s.get("notional_usd"),
                    s.get("offer_amount"),
                    s.get("ask_amount"),
                    s.get("effective_price"),
                    s.get("reference_price"),
                    s.get("execution_quality"),
                    s.get("price_impact"),
                    s.get("fee_percent"),
                    s.get("fee_bps"),
                    s.get("fee_amount_ask"),
                )
            )
        if not values:
            return 0
        with self._lock:
            self._conn.executemany(
                """
                INSERT INTO execution_samples (
                    observed_at, market, pool_address, direction, offer_address,
                    ask_address, offer_units_raw, ask_units_raw, offer_decimals,
                    ask_decimals, min_ask_units, swap_rate, slippage_tolerance,
                    fee_units_raw, fee_address, gas_forward, gas_consumption,
                    trade_size_base, notional_usd, offer_amount, ask_amount,
                    effective_price, reference_price, execution_quality,
                    price_impact, fee_percent, fee_bps, fee_amount_ask
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
            self._conn.commit()
        return len(values)

    def execution_samples(
        self,
        market: Optional[str] = None,
        limit: int = 1000,
    ) -> list[sqlite3.Row]:
        if market:
            with self._lock:
                rows = self._conn.execute(
                    """
                    SELECT * FROM execution_samples
                    WHERE market = ? ORDER BY observed_at DESC LIMIT ?
                    """,
                    (market, limit),
                ).fetchall()
        else:
            with self._lock:
                rows = self._conn.execute(
                    "SELECT * FROM execution_samples ORDER BY observed_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return rows

    def latest_run_samples(
        self,
        market: Optional[str] = None,
        limit: int = 20000,
    ) -> list[sqlite3.Row]:
        """Execution samples from the most recent collection run only."""
        with self._lock:
            row = self._conn.execute(
                "SELECT MAX(observed_at) AS latest FROM execution_samples"
            ).fetchone()
            if row is None or row["latest"] is None:
                return []
            if market:
                rows = self._conn.execute(
                    """
                    SELECT * FROM execution_samples
                    WHERE observed_at = ? AND market = ? ORDER BY trade_size_base ASC
                    """,
                    (row["latest"], market),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    """
                    SELECT * FROM execution_samples
                    WHERE observed_at = ? ORDER BY market, trade_size_base ASC
                    """,
                    (row["latest"],),
                ).fetchall()
        return rows[:limit]

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Repository":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()