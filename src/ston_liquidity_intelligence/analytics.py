"""Analytics for liquidity and execution quality.

Metrics produced by this module:
- Human-readable token amounts and effective (virtual) execution price
- Price impact reported by a swap simulation (as a fraction)
- Fee / estimated execution cost (in bps and native/quote units)
- Execution quality, i.e. the effective price of a given trade relative to the
  low-impact reference price of the smallest simulated trade
- Liquidity indicators extracted from pool data
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional

from .models import Asset, Pool, SwapSimulation

###############################################################################
# Helpers
###############################################################################


def scale_down(units: int | str, decimals: int) -> float:
    """Convert raw token units to a human-readable amount."""
    try:
        amount = int(units)
    except (TypeError, ValueError):
        return 0.0
    if decimals <= 0:
        return float(amount)
    return amount / (10 ** decimals)


def scale_up(amount: float, decimals: int) -> int:
    """Convert a human-readable amount to raw token units."""
    return int(round(amount * (10 ** decimals)))


def format_bps(fraction: float) -> float:
    """Convert a fraction to basis points."""
    return fraction * 10_000


@dataclass
class ExecutionMetrics:
    """Refined execution metrics for a single simulated swap."""

    market: str
    pool_address: str
    direction: str
    offer_address: str
    ask_address: str
    offer_amount: float
    ask_amount: float
    trade_size_base: float
    effective_price: float
    reference_price: Optional[float]
    execution_quality: Optional[float]
    price_impact: float
    fee_percent: float
    fee_bps: float
    fee_amount_ask: float
    notional_usd: float

    def to_dict(self) -> dict:
        return asdict(self)


def execution_metrics(
    sim: SwapSimulation,
    offer_asset: Asset,
    ask_asset: Asset,
    *,
    reference_price: Optional[float] = None,
    notional_usd: float = 0.0,
) -> ExecutionMetrics:
    """Derive refined execution metrics from a raw swap simulation.

    ``effective_price`` is expressed in units of ask token per offer token.
    ``execution_quality`` (when a reference price is supplied) is the ratio of
    this trade's effective price to the reference price; values below 1.0 mean
    the trade executes worse than the low-impact reference.
    """
    offer_amount = scale_down(sim.offer_units, offer_asset.decimals)
    ask_amount = scale_down(sim.ask_units, ask_asset.decimals)
    effective_price = ask_amount / offer_amount if offer_amount else 0.0

    price_impact = sim.price_impact_value
    fee_percent = sim.fee_percent_value
    fee_amount_ask = scale_down(sim.fee_units, ask_asset.decimals) if sim.fee_units else 0.0

    return ExecutionMetrics(
        market=f"{offer_asset.symbol}/{ask_asset.symbol}",
        pool_address=sim.pool_address or "",
        direction="sell",
        offer_address=offer_asset.contract_address,
        ask_address=ask_asset.contract_address,
        offer_amount=offer_amount,
        ask_amount=ask_amount,
        trade_size_base=offer_amount,
        effective_price=effective_price,
        reference_price=reference_price,
        execution_quality=(effective_price / reference_price) if reference_price else None,
        price_impact=price_impact,
        fee_percent=fee_percent,
        fee_bps=format_bps(fee_percent),
        fee_amount_ask=fee_amount_ask,
        notional_usd=notional_usd,
    )


###############################################################################
# Liquidity analytics
###############################################################################


@dataclass
class LiquidityMetrics:
    """Normalised liquidity view for a pool."""

    pool_address: str
    token0_address: Optional[str]
    token1_address: Optional[str]
    reserve0: float
    reserve1: float
    tvl_usd: float
    volume_24h_usd: float
    lp_fee_bps: float
    protocol_fee_bps: float
    ref_fee_bps: float
    deprecated: bool


def liquidity_metrics(pool: Pool) -> LiquidityMetrics:
    """Build a liquidity view for a pool.

    Fee components (``lp_fee``, ``protocol_fee``, ``ref_fee``) are returned by
    the STON.fi API already in basis points and are reported as such.
    """
    return LiquidityMetrics(
        pool_address=pool.address,
        token0_address=pool.token0_address,
        token1_address=pool.token1_address,
        reserve0=float(pool.reserve0 or 0),
        reserve1=float(pool.reserve1 or 0),
        tvl_usd=pool.total_liquidity_usd(),
        volume_24h_usd=pool.volume_24h(),
        lp_fee_bps=_safe_float(pool.lp_fee),
        protocol_fee_bps=_safe_float(pool.protocol_fee),
        ref_fee_bps=_safe_float(pool.ref_fee),
        deprecated=pool.deprecated,
    )


def _safe_float(raw: Optional[str]) -> float:
    if raw in (None, ""):
        return 0.0
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0