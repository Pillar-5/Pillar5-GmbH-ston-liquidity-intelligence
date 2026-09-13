"""Data pipeline: discover -> collect -> simulate -> analyse -> report.

High-level flow of a ``run``:

1. ``collect_market_data``  - pull assets, routers and pools from STON.fi
2. ``choose_markets``       - select a bounded, liquid universe of TON pairs
3. ``evaluate_markets``     - simulate swaps across trade sizes and score them
4. ``store_and_report``     - persist samples and produce a JSON/Markdown report
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from .analytics import ExecutionMetrics, execution_metrics, liquidity_metrics
from .client import StonApiClient, StonApiError
from .config import Settings, TON_ADDRESS
from .models import Asset, Pool, Router, SwapSimulation
from .repository import Repository

logger = logging.getLogger(__name__)

ISO = "%Y-%m-%dT%H:%M:%SZ"


def _now() -> str:
    return datetime.now(timezone.utc).strftime(ISO)


@dataclass
class Market:
    """A single monitored market: a pool between a base asset and TON."""

    pool: Pool
    base: Asset
    quote: Asset  # always TON

    @property
    def name(self) -> str:
        return f"{self.base.symbol}/{self.quote.symbol}"

    @property
    def base_address(self) -> str:
        return self.base.contract_address

    @property
    def quote_address(self) -> str:
        return self.quote.contract_address

    def base_reserve_human(self) -> float:
        """Human-readable size of the base-asset reserve in this pool."""
        from .analytics import scale_down

        if self.pool.token0_address == self.base_address:
            return scale_down(self.pool.reserve0, self.base.decimals)
        return scale_down(self.pool.reserve1, self.base.decimals)

    def tvl_usd(self) -> float:
        return self.pool.total_liquidity_usd()


###############################################################################
# Collection
###############################################################################


async def collect_market_data(
    client: StonApiClient,
    settings: Settings,
) -> tuple[list[Asset], list[Router], list[Pool]]:
    """Fetch assets, routers and pools from the STON.fi API concurrently."""
    assets, routers, pools = await asyncio.gather(
        client.get_assets(),
        client.get_routers(),
        client.get_pools(),
    )
    logger.info(
        "discovered %d assets, %d routers, %d pools",
        len(assets),
        len(routers),
        len(pools),
    )
    return assets, routers, pools


def store_market_data(
    db: Repository,
    observed_at: str,
    assets: Iterable[Asset],
    routers: Iterable[Router],
    pools: Iterable[Pool],
) -> None:
    db.store_snapshot(
        "assets",
        observed_at,
        [a.model_dump(mode="json") for a in assets],
    )
    db.store_snapshot(
        "routers",
        observed_at,
        [r.model_dump(mode="json") for r in routers],
    )
    db.store_snapshot(
        "pools",
        observed_at,
        [p.model_dump(mode="json") for p in pools],
    )


###############################################################################
# Market universe selection
###############################################################################


def choose_markets(
    pools: list[Pool],
    assets: list[Asset],
    settings: Settings,
) -> list[Market]:
    """Select the most liquid non-deprecated pools that pair a token with TON.

    The universe is capped at ``settings.max_pools`` and filtered by
    ``settings.min_pool_tvl_usd`` to keep the engine focused on liquid markets.
    """
    assets_by_addr = {a.contract_address: a for a in assets}
    ton = assets_by_addr.get(TON_ADDRESS)
    if ton is None:
        logger.warning("TON asset not found in the asset list; cannot build a market universe.")
        return []

    candidates: list[Market] = []
    for pool in pools:
        if pool.deprecated:
            continue
        tokens = (pool.token0_address, pool.token1_address)
        if TON_ADDRESS not in tokens:
            continue
        base_addr = pool.token1_address if pool.token0_address == TON_ADDRESS else pool.token0_address
        base = assets_by_addr.get(base_addr)
        if base is None or base.deprecated or base.blacklisted:
            continue
        market = Market(pool=pool, base=base, quote=ton)
        if market.tvl_usd() < settings.min_pool_tvl_usd:
            continue
        candidates.append(market)

    candidates.sort(key=lambda m: m.tvl_usd(), reverse=True)
    selected = candidates[: settings.max_pools]
    logger.info("selected %d liquid markets (of %d candidates)", len(selected), len(candidates))
    for m in selected:
        logger.info("  market %-28s tvl=%12.2f USD", m.name, m.tvl_usd())
    return selected
###############################################################################
# Execution simulations
###############################################################################


async def evaluate_market(
    client: StonApiClient,
    market: Market,
    settings: Settings,
) -> list[dict]:
    """Simulate selling increasing fractions of the base reserve for TON.

    The smallest simulated trade acts as the low-impact *reference* price;
    larger trades are then scored for execution quality relative to it.
    """
    from .analytics import scale_up

    base_reserve = market.base_reserve_human()
    if base_reserve <= 0:
        return []

    metrics: list[ExecutionMetrics] = []
    for fraction in settings.trade_sizes:
        amount = base_reserve * fraction
        units = scale_up(amount, market.base.decimals)
        if units <= 0:
            continue
        try:
            sim = await client.simulate_swap(
                offer_address=market.base_address,
                ask_address=market.quote_address,
                offer_units=units,
                slippage_tolerance=settings.slippage_tolerance,
                pool_address=market.pool.address,
            )
        except StonApiError as exc:
            logger.warning("simulation failed for %s at %g%%: %s", market.name, fraction * 100, exc)
            continue

        notional_usd = amount * market.base.price_usd
        metrics.append(
            execution_metrics(
                sim,
                market.base,
                market.quote,
                notional_usd=notional_usd,
            )
        )

    if not metrics:
        return []

    reference = min(m.effective_price for m in metrics if m.effective_price > 0)
    for m in metrics:
        m.reference_price = reference
        m.execution_quality = (m.effective_price / reference) if reference else None

    return [m.to_dict() for m in metrics]


async def evaluate_markets(
    client: StonApiClient,
    markets: list[Market],
    settings: Settings,
) -> dict[str, list[dict]]:
    results: dict[str, list[dict]] = {}
    for market in markets:
        samples = await evaluate_market(client, market, settings)
        if samples:
            results[market.name] = samples
            quality = sum(s["execution_quality"] or 1.0 for s in samples) / len(samples)
            logger.info(
                "evaluated %-28s %d trades, avg quality=%.4f",
                market.name,
                len(samples),
                quality,
            )
    return results
###############################################################################
# Reporting
###############################################################################


def _summarise_pool_liquidity(pools: list[Pool]) -> dict:
    liquid = [p for p in pools if not p.deprecated]
    total_tvl = sum(p.total_liquidity_usd() for p in liquid)
    total_volume = sum(p.volume_24h() for p in liquid)
    return {
        "num_pools": len(pools),
        "num_liquid_pools": len(liquid),
        "total_tvl_usd": round(total_tvl, 2),
        "total_volume_24h_usd": round(total_volume, 2),
        "largest_pools": [
            {
                "address": p.address,
                "tvl_usd": round(p.total_liquidity_usd(), 2),
                "volume_24h_usd": round(p.volume_24h(), 2),
                "lp_fee": p.lp_fee,
            }
            for p in sorted(liquid, key=lambda p: p.total_liquidity_usd(), reverse=True)[:10]
        ],
    }


async def run_pipeline(
    client: StonApiClient,
    db: Repository,
    settings: Settings,
    *,
    evaluate: bool = True,
) -> dict:
    """Run a full collection + evaluation cycle and store results in ``db``."""
    observed_at = _now()
    assets, routers, pools = await collect_market_data(client, settings)
    store_market_data(db, observed_at, assets, routers, pools)

    report = {
        "generated_at": observed_at,
        "settings": _settings_summary(settings),
        "discovery": {
            "assets": len(assets),
            "routers": len(routers),
            "pools": len(pools),
        },
        "liquidity": _summarise_pool_liquidity(pools),
        "markets": {},
        "execution_samples": 0,
        "markets_monitored": 0,
    }

    if not evaluate:
        return report

    markets = choose_markets(pools, assets, settings)
    results = await evaluate_markets(client, markets, settings)

    rows: list[dict] = []
    for market_name, samples in results.items():
        report["markets"][market_name] = samples
        for sample in samples:
            rows.append({**sample, "observed_at": observed_at})

    inserted = db.store_execution_samples(rows)
    report["execution_samples"] = inserted
    report["markets_monitored"] = len(markets)
    return report


def _settings_summary(settings: Settings) -> dict:
    return {
        "api_base_url": settings.api_base_url,
        "min_pool_tvl_usd": settings.min_pool_tvl_usd,
        "max_pools": settings.max_pools,
        "trade_sizes": list(settings.trade_sizes),
        "slippage_tolerance": settings.slippage_tolerance,
    }


def write_report(report: dict, settings: Settings, fmt: str = "json") -> Path:
    """Persist a report to ``report_dir`` and return the created file path."""
    out_dir = Path(settings.report_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = report["generated_at"].replace(":", "").replace("T", "_").rstrip("Z")
    if fmt == "json":
        path = out_dir / f"report_{stamp}.json"
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    else:
        path = out_dir / f"report_{stamp}.md"
        path.write_text(_report_to_markdown(report), encoding="utf-8")
    return path


def _report_to_markdown(report: dict) -> str:
    lines = ["# STON.fi Liquidity & Execution Intelligence - Market Report", ""]
    lines.append(f"- **Generated:** {report['generated_at']}")
    disc = report.get("discovery", {})
    lines.append(
        f"- **Discovered:** {disc.get('assets', 0)} assets / "
        f"{disc.get('pools', 0)} pools / {disc.get('routers', 0)} routers"
    )
    liq = report.get("liquidity", {})
    lines.append(
        f"- **Total tracked liquidity:** ${liq.get('total_tvl_usd', 0):,.2f} "
        f"(24h volume ${liq.get('total_volume_24h_usd', 0):,.2f})"
    )
    lines.append(f"- **Markets monitored:** {report.get('markets_monitored', 0)}")
    lines.append(f"- **Execution samples:** {report.get('execution_samples', 0)}")
    lines.append("")

    for market, samples in report.get("markets", {}).items():
        lines.append(f"## {market}")
        lines.append("")
        lines.append("| Trade size (base) | Notional USD | Effective price | Ref price | Quality | Impact | Fee bps |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|")
        for s in samples:
            lines.append(
                f"| {s['trade_size_base']:,.6g} | ${s['notional_usd']:,.2f} "
                f"| {s['effective_price']:.8g} | {s['reference_price'] or 0:.8g} "
                f"| {s['execution_quality'] or 0:.6f} | {s['price_impact'] * 100:.4f}% "
                f"| {s['fee_bps']:.2f} |"
            )
        lines.append("")
    return "\n".join(lines)