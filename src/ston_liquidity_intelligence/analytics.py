"""Analytics for liquidity and execution conditions.

Metrics produced by this module:

- Token amounts converted to human-readable units using token decimals
- Effective execution price, that is the simulated output ratio ask / offer
- Price impact reported by the swap simulation (as a fraction)
- Fee percent, fee in basis points, and fee amount in the ask token
- Execution quality, that is a trade's effective price relative to the
  reference price of the smallest simulated trade
- Gas estimates reported by the simulation
- Liquidity indicators extracted from pool data

The metrics come from the STON.fi simulation outputs wherever possible. Values
such as the pool fee and price impact are reported separately and are not added
to the effective execution price, which the simulation already incorporates.
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
    """Refined execution metrics for a single simulated swap.

    ``effective_price`` is the quoted execution price, that is the actual output
    ratio ``ask_amount / offer_amount`` returned by the simulation. It already
    reflects the pool fee and the price impact for that trade size.

    The fee and price impact are reported separately as derived metrics. They
    are not added to ``effective_price`` because the simulation output already
    incorporates them. Fees are therefore not double counted, and
    ``effective_price`` is not a synthetic figure built from assumptions.
    """

    market: str
    pool_address: str
    direction: str
    offer_address: str
    ask_address: str
    # raw inputs for reproducibility
    offer_units_raw: str
    ask_units_raw: str
    offer_decimals: int
    ask_decimals: int
    min_ask_units: Optional[str]
    swap_rate: Optional[float]
    slippage_tolerance: Optional[float]
    fee_units_raw: Optional[str]
    fee_address: Optional[str]
    gas_forward: Optional[float]
    gas_consumption: Optional[float]
    # derived metrics
    offer_amount: float
    ask_amount: float
    trade_size_base: float
    effective_price: float
    reference_price: Optional[float]
    execution_quality: Optional[float]
    price_impact: float
    fee_percent: float
    """Fee as a fraction of the trade, as returned by the simulation response
    field ``fee_percent``. Despite the field name it is a fraction, for example
    0.003004 for roughly 30 bps."""
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
    """Derive execution metrics from a raw swap simulation.

    ``effective_price`` is quoted as ask token units per offer token unit. It is
    computed from the simulated output amounts only.

    ``execution_quality`` is only meaningful when a ``reference_price`` is
    supplied. It is the ratio of this trade's effective price to that
    reference. For a sell direction, a value below 1.0 means the trade is worse
    than the reference (higher price impact for the larger trade).
    """
    offer_decimals = offer_asset.decimals
    ask_decimals = ask_asset.decimals
    offer_amount = scale_down(sim.offer_units, offer_decimals)
    ask_amount = scale_down(sim.ask_units, ask_decimals)
    effective_price = ask_amount / offer_amount if offer_amount else 0.0

    price_impact = sim.price_impact_value
    fee_percent = sim.fee_percent_value
    fee_amount_ask = scale_down(sim.fee_units, ask_decimals) if sim.fee_units else 0.0

    gas = sim.gas_params or {}
    gas_forward = _safe_float(gas.get("forward_gas"))
    gas_consumption = _safe_float(gas.get("estimated_gas_consumption"))

    return ExecutionMetrics(
        market=f"{offer_asset.symbol}/{ask_asset.symbol}",
        pool_address=sim.pool_address or "",
        direction="sell",
        offer_address=offer_asset.contract_address,
        ask_address=ask_asset.contract_address,
        offer_units_raw=sim.offer_units,
        ask_units_raw=sim.ask_units,
        offer_decimals=offer_decimals,
        ask_decimals=ask_decimals,
        min_ask_units=sim.min_ask_units,
        swap_rate=sim.float_field("swap_rate") or None,
        slippage_tolerance=_safe_float(sim.slippage_tolerance),
        fee_units_raw=sim.fee_units,
        fee_address=sim.fee_address,
        gas_forward=gas_forward or None,
        gas_consumption=gas_consumption or None,
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
    """LP supply value in USD as reported by the STON.fi API
    (``lp_total_supply_usd``). This is a liquidity proxy, not a canonical TVL."""
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