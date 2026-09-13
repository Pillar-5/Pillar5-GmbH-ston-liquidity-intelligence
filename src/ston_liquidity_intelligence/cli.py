"""Command-line interface for the STON.fi intelligence engine.

Usage examples
--------------
python -m ston_liquidity_intelligence run            # collect + evaluate + report
python -m ston_liquidity_intelligence collect        # discovery only (store snapshots)
python -m ston_liquidity_intelligence evaluate       # simulation only (from disk DB)
python -m ston_liquidity_intelligence serve [--port] # REST API + dashboard
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from .config import Settings, _load_dotenv
from .client import StonApiClient
from .pipeline import run_pipeline, write_report
from .repository import Repository

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
)
logger = logging.getLogger("ston-liq")


def _client_and_db(settings: Settings):
    client = StonApiClient(
        base_url=settings.api_base_url,
        timeout=settings.timeout_seconds,
        max_retries=settings.max_retries,
        max_concurrency=settings.max_concurrency,
        api_key=settings.api_key,
    )
    db = Repository(settings.db_path)
    return client, db


async def _cmd_run(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    client, db = _client_and_db(settings)
    try:
        report = await run_pipeline(client, db, settings, evaluate=not args.collect_only)
        if args.write_report != "none":
            fmt = args.write_report
            path = write_report(report, settings, fmt=fmt)
            logger.info("report written to %s", path)
        logger.info(
            "run complete: %d markets, %d execution samples",
            report.get("markets_monitored", 0),
            report.get("execution_samples", 0),
        )
    finally:
        await client.aclose()
        db.close()
    return 0


async def _cmd_evaluate(args: argparse.Namespace) -> int:
    """Re-run simulations using the latest stored snapshot (no new collection)."""
    from .pipeline import choose_markets, evaluate_markets, _summarise_pool_liquidity
    from .models import Asset, Pool

    settings = Settings.from_env()
    with Repository(settings.db_path) as db:
        assets_raw = db.latest_snapshot("assets") or []
        pools_raw = db.latest_snapshot("pools") or []
        assets = [Asset.model_validate(a) for a in assets_raw]
        pools = [Pool.model_validate(p) for p in pools_raw]
        markets = choose_markets(pools, assets, settings)
        client = StonApiClient(
            base_url=settings.api_base_url,
            timeout=settings.timeout_seconds,
            max_retries=settings.max_retries,
            max_concurrency=settings.max_concurrency,
        )
        try:
            results = await evaluate_markets(client, markets, settings)
        finally:
            await client.aclose()
        rows = []
        import datetime as _dt

        observed_at = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        for market, samples in results.items():
            for s in samples:
                rows.append({**s, "observed_at": observed_at})
        n = db.store_execution_samples(rows)
        logger.info("stored %d new execution samples across %d markets", n, len(results))
    return 0


async def _cmd_collect(args: argparse.Namespace) -> int:
    """Run discovery/collection only and store raw snapshots (no simulations)."""
    settings = Settings.from_env()
    client, db = _client_and_db(settings)
    try:
        report = await run_pipeline(client, db, settings, evaluate=False)
        logger.info(
            "collection complete: %d assets, %d pools discovered",
            report["discovery"]["assets"],
            report["discovery"]["pools"],
        )
    finally:
        await client.aclose()
        db.close()
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    """Serve the REST API + dashboard (FastAPI needs to be installed)."""
    import uvicorn

    from .api import create_app

    settings = Settings.from_env()
    app = create_app(settings)
    logger.info("serving on http://127.0.0.1:%d (dashboard at /)", args.port)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ston-liq",
        description=(
            "STON.fi Liquidity & Execution Intelligence Engine - monitor "
            "liquidity, evaluate execution quality and identify market conditions."
        ),
    )
    parser.add_argument("--version", action="version", version="ston-liq 0.1.0")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="collect + evaluate + write report")
    run.add_argument(
        "--collect-only",
        action="store_true",
        help="only run discovery/collection (skip swap simulations)",
    )
    run.add_argument(
        "--write-report",
        choices=["json", "md", "none"],
        default="json",
        help="output format for the generated report (default: json)",
    )
    run.set_defaults(func=_cmd_run)

    sub.add_parser("collect", help="run discovery only and store raw snapshots").set_defaults(
        func=lambda a: asyncio.run(_cmd_collect(a))
    )

    sub.add_parser(
        "evaluate", help="re-run simulations from the latest stored snapshot"
    ).set_defaults(func=lambda a: asyncio.run(_cmd_evaluate(a)))

    serve = sub.add_parser("serve", help="start the REST API + dashboard")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.set_defaults(func=_cmd_serve)

    return parser


def main(argv: list[str] | None = None) -> int:
    _load_dotenv()
    args = build_parser().parse_args(argv)
    if args.command == "run":
        return asyncio.run(_cmd_run(args))
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())