"""Pydantic models mirroring the STON.fi HTTP API payloads.

Field names follow the snake_case form used by the raw API responses so that
``model_validate`` works directly on what the endpoints return.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

AssetKind = str  # "Ton" | "Wton" | "Jetton" | "NotAnAsset"


class Asset(BaseModel):
    contract_address: str
    symbol: str = ""
    decimals: int = 0
    display_name: Optional[str] = None
    kind: AssetKind = "Jetton"
    community: bool = False
    deprecated: bool = False
    blacklisted: bool = False
    default_symbol: bool = False
    priority: int = 0
    image_url: Optional[str] = None
    wallet_address: Optional[str] = None
    dex_price_usd: Optional[str] = None
    third_party_price_usd: Optional[str] = None
    popularity_index: Optional[float] = None
    tags: list[str] = Field(default_factory=list)

    @property
    def price_usd(self) -> float:
        """Best available USD reference price for the asset."""
        for raw in (self.dex_price_usd, self.third_party_price_usd):
            if raw not in (None, ""):
                try:
                    return float(raw)
                except (TypeError, ValueError):
                    continue
        return 0.0


class Router(BaseModel):
    address: str
    major_version: int = 1
    minor_version: int = 0
    router_type: Optional[str] = None
    pton_master_address: Optional[str] = None
    pton_wallet_address: Optional[str] = None
    pton_version: Optional[str] = None
    pool_creation_enabled: Optional[bool] = None


class Pool(BaseModel):
    address: str
    router_address: Optional[str] = None
    reserve0: str = "0"
    reserve1: str = "0"
    token0_address: Optional[str] = None
    token1_address: Optional[str] = None
    token0_balance: Optional[str] = None
    token1_balance: Optional[str] = None
    lp_total_supply: Optional[str] = None
    lp_total_supply_usd: Optional[str] = None
    lp_price_usd: Optional[str] = None
    lp_fee: Optional[str] = None
    protocol_fee: Optional[str] = None
    ref_fee: Optional[str] = None
    apy_1d: Optional[str] = None
    apy_7d: Optional[str] = None
    apy_30d: Optional[str] = None
    collected_token0_protocol_fee: Optional[str] = None
    collected_token1_protocol_fee: Optional[str] = None
    volume_24h_usd: Optional[str] = None
    deprecated: bool = False
    amp: Optional[str] = None
    rate: Optional[str] = None
    w0: Optional[str] = None

    def total_liquidity_usd(self) -> float:
        try:
            return float(self.lp_total_supply_usd or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def volume_24h(self) -> float:
        try:
            return float(self.volume_24h_usd or 0.0)
        except (TypeError, ValueError):
            return 0.0


class SwapSimulation(BaseModel):
    offer_address: str
    ask_address: str
    offer_units: str = "0"
    ask_units: str = "0"
    offer_jetton_wallet: Optional[str] = None
    ask_jetton_wallet: Optional[str] = None
    fee_address: Optional[str] = None
    fee_units: Optional[str] = None
    fee_percent: Optional[str] = None
    min_ask_units: Optional[str] = None
    pool_address: Optional[str] = None
    price_impact: Optional[str] = None
    router_address: Optional[str] = None
    router: Optional[Router] = None
    slippage_tolerance: Optional[str] = None
    swap_rate: Optional[str] = None
    recommended_slippage_tolerance: Optional[str] = None
    recommended_min_ask_units: Optional[str] = None
    gas_params: Optional[dict] = None

    def float_field(self, name: str) -> float:
        raw = getattr(self, name, None)
        if raw in (None, ""):
            return 0.0
        try:
            return float(raw)
        except (TypeError, ValueError):
            return 0.0

    @property
    def price_impact_value(self) -> float:
        return self.float_field("price_impact")

    @property
    def fee_percent_value(self) -> float:
        return self.float_field("fee_percent")