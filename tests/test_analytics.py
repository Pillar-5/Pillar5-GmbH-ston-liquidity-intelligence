"""Tests for the analytics module."""

from ston_liquidity_intelligence.analytics import (
    execution_metrics,
    format_bps,
    liquidity_metrics,
    scale_down,
    scale_up,
)
from ston_liquidity_intelligence.models import Asset, Pool, SwapSimulation

TON = "EQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAM9c"


def _asset(symbol="TON", address=TON, decimals=9, price="2.5"):
    return Asset(contract_address=address, symbol=symbol, decimals=decimals, dex_price_usd=price)


def test_scale_down_and_up():
    assert scale_down("1000000000", 9) == 1.0
    assert scale_up(1.0, 9) == 1_000_000_000
    assert scale_down("0", 9) == 0.0
    assert scale_down("bad", 9) == 0.0


def test_format_bps():
    assert format_bps(0.003) == 30.0
    assert format_bps(1.0) == 10_000.0


def test_execution_metrics():
    offer = _asset("JETTON", "EQbase", 6, price="1.0")
    ask = _asset("TON", TON, 9, price="2.5")
    sim = SwapSimulation(
        offer_address=offer.contract_address,
        ask_address=ask.contract_address,
        offer_units="1000000",      # 1 JETTON
        ask_units="2500000000",     # 2.5 TON
        pool_address="EQpool",
        price_impact="0.0005",
        fee_percent="0.003",
        fee_units="7500000",        # 0.0075 TON
    )
    m = execution_metrics(sim, offer, ask, reference_price=2.5, notional_usd=1.0)
    assert m.trade_size_base == 1.0
    assert m.effective_price == 2.5
    assert m.reference_price == 2.5
    assert m.execution_quality == 1.0
    assert m.price_impact == 0.0005
    assert m.fee_bps == 30.0
    assert m.fee_amount_ask == 0.0075
    assert m.notional_usd == 1.0
    assert m.market == "JETTON/TON"


def test_execution_metrics_quality_below_one():
    offer = _asset("JETTON", "EQbase", 6)
    ask = _asset("TON", TON, 9)
    sim = SwapSimulation(
        offer_address=offer.contract_address,
        ask_address=ask.contract_address,
        offer_units="1000000",
        ask_units="2000000000",   # worse price
        pool_address="EQpool",
    )
    m = execution_metrics(sim, offer, ask, reference_price=2.5)
    assert m.effective_price == 2.0
    assert m.execution_quality == 0.8


def test_liquidity_metrics_for_pool():
    pool = Pool(
        address="EQpool",
        token0_address="EQa",
        token1_address=TON,
        reserve0="1234",
        reserve1="5678",
        lp_total_supply_usd="1000000",
        volume_24h_usd="250000",
        lp_fee="7",
        protocol_fee="3",
        ref_fee="2",
    )
    lm = liquidity_metrics(pool)
    assert lm.tvl_usd == 1_000_000
    assert lm.volume_24h_usd == 250_000
    assert lm.lp_fee_bps == 7.0
    assert lm.protocol_fee_bps == 3.0
    assert lm.ref_fee_bps == 2.0