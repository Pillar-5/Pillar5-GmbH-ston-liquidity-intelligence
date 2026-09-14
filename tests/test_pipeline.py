"""Tests for market selection and the pipeline helpers."""

from pathlib import Path

import pytest

from ston_liquidity_intelligence.config import Settings, TON_ADDRESS
from ston_liquidity_intelligence.client import StonApiError
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
            gas_params={"forward_gas": "100000", "estimated_gas_consumption": "50000"},
        )


class DegradingClient:
    """Prices degrade with size, so larger sells get a worse effective price."""

    def __init__(self, rate: float = 2.0, base_decimals: int = 6, impact: float = 0.05):
        self.rate = rate
        self.base_decimals = base_decimals
        self.impact = impact

    async def simulate_swap(self, offer_address, ask_address, offer_units, slippage_tolerance, pool_address=None):
        offer = int(offer_units)
        amount = offer / (10 ** self.base_decimals)
        factor = 1.0 - self.impact * amount
        ask_raw = int(amount * self.rate * factor * 1_000_000_000)
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


class FailSomeClient(FakeClient):
    """Fails simulations above a raw offer-unit threshold."""

    def __init__(self, fail_above: int, **kw):
        super().__init__(**kw)
        self.fail_above = fail_above

    async def simulate_swap(self, offer_address, ask_address, offer_units, slippage_tolerance, pool_address=None):
        if int(offer_units) >= self.fail_above:
            raise StonApiError("boom")
        return await super().simulate_swap(
            offer_address, ask_address, offer_units, slippage_tolerance, pool_address
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
    samples, attempted, succeeded = await evaluate_market(FakeClient(), market, settings)
    assert attempted == 3
    assert succeeded == 3
    assert len(samples) == 3
    assert all(s["execution_quality"] is not None for s in samples)
    assert samples[0]["trade_size_base"] == pytest.approx(1.0)  # 100 * 0.01
    assert samples[-1]["trade_size_base"] == pytest.approx(10.0)  # 100 * 0.1
    assert samples[0]["effective_price"] == pytest.approx(2.0, rel=0.01)
    assert samples[0]["notional_usd"] == pytest.approx(1.0)
    # Reproducible reference equals the smallest trade's effective price.
    assert samples[0]["reference_price"] == pytest.approx(2.0, rel=0.01)


@pytest.mark.asyncio
async def test_reference_is_smallest_trade_and_quality_decreases():
    base = _asset("USDT", "EQusdt", 6, price="1.0")
    quote = _asset("TON", TON, 9, price="2.0")
    pool = Pool(
        address="EQp",
        token0_address="EQusdt",
        token1_address=TON,
        reserve0="100000000",
        reserve1="0",
        lp_total_supply_usd="200",
    )
    market = Market(pool=pool, base=base, quote=quote)
    settings = Settings(trade_sizes=(0.01, 0.05, 0.5))
    samples, _, _ = await evaluate_market(DegradingClient(), market, settings)
    smallest = min(samples, key=lambda s: s["trade_size_base"])
    largest = max(samples, key=lambda s: s["trade_size_base"])
    # Reference is the (least impacted) smallest trade.
    assert smallest["execution_quality"] == pytest.approx(1.0)
    # Larger sell has a worse effective price, so quality is below 1.0.
    assert largest["effective_price"] < smallest["effective_price"]
    assert largest["execution_quality"] < 1.0


@pytest.mark.asyncio
async def test_failed_simulations_are_counted_and_excluded():
    base = _asset("USDT", "EQusdt", 6, price="1.0")
    quote = _asset("TON", TON, 9, price="2.0")
    pool = Pool(
        address="EQp",
        token0_address="EQusdt",
        token1_address=TON,
        reserve0="100000000",
        reserve1="0",
        lp_total_supply_usd="200",
    )
    market = Market(pool=pool, base=base, quote=quote)
    settings = Settings(trade_sizes=(0.01, 0.05, 0.5))
    # Raw offer units >= 10_000_000 fail. With 100 USDT reserve (6 decimals),
    # sizes 1 USDT and 5 USDT pass, 50 USDT fails.
    samples, attempted, succeeded = await evaluate_market(
        FailSomeClient(fail_above=10_000_000), market, settings
    )
    assert attempted == 3
    assert succeeded == 2
    assert len(samples) == 2
    assert all(s["trade_size_base"] < 6.0 for s in samples)


def test_report_markdown_contains_table():
    report = {
        "generated_at": "2026-01-01T00:00:00Z",
        "liquidity": {"total_liquidity_usd_est": 1234.5, "total_volume_24h_usd": 99.0},
        "markets_selected": 1,
        "markets_evaluated": 1,
        "simulations_attempted": 3,
        "simulations_successful": 3,
        "simulations_failed": 0,
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
    assert "3 successful" in md


def test_write_report(tmp_path):
    settings = Settings(report_dir=str(tmp_path))
    report = {
        "generated_at": "2026-01-01T00:00:00Z",
        "liquidity": {},
        "markets": {},
        "markets_selected": 0,
        "markets_evaluated": 0,
        "simulations_attempted": 0,
        "simulations_successful": 0,
        "simulations_failed": 0,
        "execution_samples": 0,
    }
    path = write_report(report, settings, fmt="json")
    assert path.exists()
    assert path.read_text().startswith("{")