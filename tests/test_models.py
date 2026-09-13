"""Tests that raw STON.fi API payloads parse into the pydantic models."""

from ston_liquidity_intelligence.models import (
    Asset,
    Pool,
    Router,
    SwapSimulation,
)

TON = "EQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAM9c"


def test_asset_parsing():
    raw = {
        "contract_address": TON,
        "symbol": "GRAM",
        "display_name": "Gram",
        "decimals": 9,
        "kind": "Ton",
        "deprecated": False,
        "community": False,
        "blacklisted": False,
        "default_symbol": True,
        "priority": 95,
        "tags": ["asset:default_symbol"],
        "dex_price_usd": "5.5",
        "third_party_price_usd": "5.4",
    }
    asset = Asset.model_validate(raw)
    assert asset.symbol == "GRAM"
    assert asset.decimals == 9
    assert asset.kind == "Ton"
    assert asset.price_usd == 5.5


def test_asset_price_usd_falls_back():
    asset = Asset(
        contract_address=TON,
        symbol="GRAM",
        decimals=9,
        dex_price_usd=None,
        third_party_price_usd="12.3",
    )
    assert asset.price_usd == 12.3
    bare = Asset(contract_address=TON, symbol="X", decimals=9)
    assert bare.price_usd == 0.0


def test_pool_parsing():
    raw = {
        "address": "EQpool",
        "router_address": "EQrouter",
        "reserve0": "1000000000",
        "reserve1": "2000000000",
        "token0_address": "EQa",
        "token1_address": TON,
        "lp_total_supply": "999",
        "lp_total_supply_usd": "123456.789",
        "lp_fee": "7",
        "protocol_fee": "3",
        "ref_fee": "2",
        "volume_24h_usd": "50000",
        "deprecated": False,
    }
    pool = Pool.model_validate(raw)
    assert pool.total_liquidity_usd() == 123456.789
    assert pool.volume_24h() == 50000
    assert not pool.deprecated


def test_router_parsing():
    raw = {
        "address": "EQrouter",
        "major_version": 1,
        "minor_version": 0,
        "router_type": "ConstantProduct",
        "pool_creation_enabled": False,
    }
    router = Router.model_validate(raw)
    assert router.router_type == "ConstantProduct"


def test_swap_simulation_parsing():
    raw = {
        "offer_address": TON,
        "ask_address": "EQjetton",
        "offer_units": "1000000000",
        "ask_units": "1351003",
        "pool_address": "EQpool",
        "price_impact": "0.000000580",
        "fee_percent": "0.003004263",
        "fee_units": "4071",
        "slippage_tolerance": "0.01",
        "min_ask_units": "1337492",
        "swap_rate": "1.351003000",
    }
    sim = SwapSimulation.model_validate(raw)
    assert sim.price_impact_value == 0.000000580
    assert sim.fee_percent_value == 0.003004263
    assert sim.float_field("missing_key") == 0.0