"""Tests for market selection and the pipeline helpers."""

from pathlib import Path

import pytest

from ston_liquidity_intelligence.config import Settings, TON_ADDRESS
from ston_liquidity_intelligence.models import Asset, Pool, SwapSimulation
from ston_liquidity_intelligence.pipeline import (
    Market,
    _report_to_markdown,
    choose_markets,
    evaluate_market,
    write_report,
)

TON = TON_ADDRESS


def _asset(symbol, addr, decimals, price="1.0", **kw):
    return Asset(contract_address=addr, symbol=symbol, decimals=decimals, dex_price_usd=price, **kw)


def _pool(addr, t0, t1, tvl, **kw):
    return Pool(
        address=addr,
        token0_address=t0,
        token1_address=t1,
        reserve0="1000000000",
        reserve1="1000000000",
        lp_total_supply_usd=str(tvl),
        lp_fee="7",
        protocol_fee="3",
        deprecated=kw.pop("deprecated", False),
        **kw,
    )


def test_choose_markets_filters_and_caps():
    assets = [
        _asset("TON", TON, 9),
        _asset("USDT", "EQusdt", 6, price="1.0"),
        _asset("NOT", "EQnot", 9, price="0.01"),
        _asset("TSLA", "EQtsla", 9, price="9.0", deprecated=True, blacklisted=False),
    ]
    pools = [
        _pool("EQp1", "EQusdt", TON, 1_000_000),       # liquid
        _pool("EQp2", "EQnot", TON, 500_000),           # liquid
        _pool("EQp3", TON, "EQtsla", 2_000_000),        # base is deprecated -> skip
        _pool("EQp4", "EQother", "EQother2", 9_000),    # no TON -> skip
    ]
    settings = Settings(min_pool_tvl_usd=600_000, max_pools=2)
    markets = choose_markets(pools, assets, settings)
    assert len(markets) == 1
    assert markets[0].name in ("USDT/TON", "NOT/TON")
    # Only the USDT pool clears the 600k threshold.
    assert markets[0].pool.address == "EQp1"
    assert markets[0].base_address == "EQusdt"
    assert markets[0].quote_address == TON


def test_base_reserve_human_depends_on_token_side():
    base = _asset("USDT", "EQusdt", 6)
    quote = _asset("TON", TON, 9)
    # token0 is base here -> reserve0 used.
    pool = Pool(
        address="EQp",
        token0_address="EQusdt",
        token1_address=TON,
        reserve0="5000000",   # 5 USDT
        reserve1="12345",
        lp_total_supply_usd="100",
    )
    m = Market(pool=pool, base=base, quote=quote)
    assert m.base_reserve_human() == 5.0
    assert m.name == "USDT/TON"


class FakeClient:
    """Deterministic fake that prices trades at a constant rate plus impact."""

    def __init__(self, rate: float = 2.0, base_decimals: int = 6):
        self.rate = rate
        self.base_decimals = base_decimals

    async def simulate_swap(self, offer_address, ask_address, offer_units, slippage_tolerance, pool_address=None):
        offer = int(offer_units)
        # rate = ask TON per base token; ask raw units use 9 decimals.
        ask_raw = int((offer / (10 ** self.base_decimals)) * self.rate * 1_000_000_000)
        return SwapSimulation(
            offer_address=offer_address,
            ask_address=ask_address,
            offer_units=str(offer),
            ask_units=str(ask_raw),
            pool_address=pool_address,
            price_impact="0.0001",
            fee_percent="0.003",
            fee_units=str(int(ask_raw * 0.003)),
        )


@pytest.mark.asyncio
async def test_evaluate_market_produces_metrics():
    base = _asset("USDT", "EQusdt", 6, price="1.0")
    quote = _asset("TON", TON, 9, price="2.0")
    pool = Pool(
        address="EQp",
        token0_address="EQusdt",
        token1_address=TON,
        reserve0="100000000",   # 100 USDT raw at 6 dec
        reserve1="0",
        lp_total_supply_usd="200",
    )
    market = Market(pool=pool, base=base, quote=quote)
    settings = Settings(trade_sizes=(0.01, 0.05, 0.1))
    samples = await evaluate_market(FakeClient(), market, settings)
    assert len(samples) == 3
    # Quality ratios should be close to 1.0 (constant-rate model) and ordered by size.
    assert all(s["execution_quality"] is not None for s in samples)
    assert samples[0]["trade_size_base"] == pytest.approx(1.0)  # 100 * 0.01
    assert samples[-1]["trade_size_base"] == pytest.approx(10.0)  # 100 * 0.1
    # Effective price ~ 2.0 USDT-per-TON? No: selling USDT for TON, so ask TON per offer USDT.
    assert samples[0]["effective_price"] == pytest.approx(2.0, rel=0.01)
    assert samples[0]["notional_usd"] == pytest.approx(1.0)


def test_report_markdown_contains_table():
    report = {
        "generated_at": "2026-01-01T00:00:00Z",
        "discovery": {"assets": 5, "pools": 2, "routers": 1},
        "liquidity": {"total_tvl_usd": 1234.5, "total_volume_24h_usd": 99.0},
        "markets_monitored": 1,
        "execution_samples": 1,
        "markets": {
            "USDT/TON": [
                {
                    "trade_size_base": 1.0,
                    "notional_usd": 100.0,
                    "effective_price": 2.0,
                    "reference_price": 2.0,
                    "execution_quality": 1.0,
                    "price_impact": 0.0005,
                    "fee_bps": 30.0,
                }
            ]
        },
    }
    md = _report_to_markdown(report)
    assert "USDT/TON" in md
    assert "| Trade size" in md
    assert "$1,234.50" in md


def test_write_report(tmp_path):
    settings = Settings(report_dir=str(tmp_path))
    report = {
        "generated_at": "2026-01-01T00:00:00Z",
        "discovery": {"assets": 1, "pools": 1, "routers": 1},
        "liquidity": {},
        "markets": {},
        "execution_samples": 0,
        "markets_monitored": 0,
    }
    path = write_report(report, settings, fmt="json")
    assert path.exists()
    assert path.read_text().startswith("{")