# STON.fi Liquidity & Execution Intelligence Engine

[![CI](https://github.com/Pillar-5/Pillar5-GmbH-ston-liquidity-intelligence/actions/workflows/ci.yml/badge.svg)](https://github.com/Pillar-5/Pillar5-GmbH-ston-liquidity-intelligence/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

A **Python-based liquidity and execution intelligence engine** that connects to
[STON.fi](https://ston.fi) market data and swap simulation to monitor liquidity,
evaluate execution quality and identify actionable market conditions across TON.

This is an MVP built natively against the **STON.fi public HTTP API**. Instead of
recreating STON.fi's own infrastructure, the project layers an **analytics and
execution-intelligence engine** on top of its assets, pools and swap-simulation
primitives.

## What it does

1. **Discovers** STON.fi assets, routers and pools
2. **Retrieves** market and liquidity information for selected markets
3. **Requests** simulated swap quotes across multiple trade sizes
4. **Calculates** execution quality, effective execution price and price impact
5. **Tracks** liquidity and market changes in a local database
6. **Identifies** potentially attractive execution conditions
7. **Exposes** the analytics through a REST API and lightweight dashboard
8. **Reports** structured liquidity and execution findings (JSON / Markdown)

A full run (`ston-liq run`) discovers assets/pools, selects the most liquid TON
markets, simulates trades across sizes, stores everything in SQLite, and writes a
report containing metrics such as total tracked liquidity (TVL) and 24h volume,
number of monitored markets and execution samples, and per-market effective price,
reference price, execution quality, price impact and fee cost (bps) for each
simulated trade size.

## Architecture

```
                 ┌──────────────────────── STON.fi HTTP API ────────────────────────┐
                 │  /v1/assets   /v1/routers   /v1/pools   /v1/swap/simulate        │
                 └───────────────────────────────┬──────────────────────────────────┘
                                                 │  async HTTP (httpx, throttled,
                                                 │  retried)
                 ┌───────────────────────────────▼──────────────────────────────────┐
                 │  client.StonApiClient                                             │
                 │  models (Asset, Pool, Router, SwapSimulation)                     │
                 └───────────────────────────────┬──────────────────────────────────┘
                                                 │
        ┌────────────────────────┬────────────────┴───────────────┬───────────────────────────┐
        │                        │                                │                           │
┌───────▼────────┐      ┌────────▼─────────┐            ┌─────────▼────────┐      ┌───────────▼────────┐
│ pipeline       │      │ analytics        │            │ repository       │      │ api (FastAPI)      │
│ choose_markets │      │ execution_metrics│            │ SQLite snapshots │      │ REST endpoints     │
│ evaluate_market│      │ liquidity_metrics│            │ + execution      │      │ + dashboard (HTML) │
│ run_pipeline   │      │ scale/format     │            │ samples          │      │ Chart.js           │
└───────┬────────┘      └──────────────────┘            └─────────┬────────┘      └────────────────────┘
        │                                                         │
        └─────────────────── CLI (ston-liq) ──────────────────────┘
```

- `client` – async, throttled, retrying client for the subset of STON.fi endpoints
  the engine uses.
- `models` – pydantic models mirroring the raw STON.fi API payloads.
- `analytics` – effective execution price, price impact, fee/execution cost (bps)
  and execution quality (price relative to a low-impact reference trade).
- `pipeline` – discovers data, selects a liquid market universe, runs simulations
  and orchestrates a full run.
- `repository` – SQLite persistence for raw snapshots and execution samples.
- `cli` – command-line interface for `run`, `collect`, `evaluate` and `serve`.
- `api` – FastAPI REST layer plus the embedded dashboard.

## Requirements

- Python 3.10+
- Internet access to reach `https://api.ston.fi` (the public STON.fi API needs no
  key for the endpoints used).

## Installation

```bash
git clone https://github.com/Pillar-5/Pillar5-GmbH-ston-liquidity-intelligence.git
cd ston-liquidity-intelligence
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

# Core (pipeline + CLI + report)
pip install -e .

# Optional REST API + dashboard
pip install -e ".[api]"

# Development (tests)
pip install -e ".[dev,api]"
```

## Quickstart

Run the full pipeline (discover + select markets + simulate + store + report):

```bash
ston-liq run --write-report md
```

This writes a report to `reports/` and stores data in `data/liquidity.db`.

Start the REST API + dashboard:

```bash
ston-liq serve --port 8000
# open http://127.0.0.1:8000/
```

## CLI reference

| Command                     | Description                                              |
|-----------------------------|----------------------------------------------------------|
| `ston-liq run`              | Full cycle: collect, select markets, simulate, store     |
| `ston-liq run --collect-only` | Discovery/collection only (no simulations)             |
| `ston-liq run --write-report md` | Also writes a Markdown report                       |
| `ston-liq collect`          | Discovery/collection only, store raw snapshots           |
| `ston-liq evaluate`         | Re-run simulations from the latest stored snapshot       |
| `ston-liq serve`            | Start REST API + dashboard                               |
| `python -m ston_liquidity_intelligence ...` | Same commands via `-m`            |

## Configuration

All settings are optional and read from environment variables (a `.env` file is
auto-loaded if present). See [.env.example](.env.example).

| Variable                       | Default                              | Description                              |
|--------------------------------|--------------------------------------|------------------------------------------|
| `STONFI_API_BASE_URL`          | `https://api.ston.fi`                | STON.fi API base URL                     |
| `STONFI_API_KEY`               | *(empty)*                            | Optional bearer key                      |
| `STONFI_DB_PATH`               | `data/liquidity.db`                  | SQLite database path                     |
| `STONFI_REPORT_DIR`            | `reports`                            | Report output directory                  |
| `STONFI_TIMEOUT_SECONDS`       | `30.0`                               | HTTP request timeout                     |
| `STONFI_MAX_CONCURRENCY`       | `8`                                  | Max parallel API requests                |
| `STONFI_MAX_RETRIES`           | `2`                                  | Retries for transient HTTP errors        |
| `STONFI_MIN_POOL_TVL_USD`      | `50000`                              | Keep pools with at least this TVL (USD)  |
| `STONFI_MAX_POOLS`             | `12`                                 | Cap on selected liquid markets           |
| `STONFI_TRADE_SIZES`           | `0.0001,0.001,0.005,0.01,0.02,0.05`  | Fractions of base reserve to simulate    |
| `STONFI_SLIPPAGE_TOLERANCE`    | `0.01`                               | Slippage tolerance for simulations       |

## REST API

| Method | Path                          | Description                              |
|--------|-------------------------------|------------------------------------------|
| `GET`  | `/health`                     | Liveness/status                          |
| `GET`  | `/api/summary`                | Discovery, liquidity and sample summary  |
| `GET`  | `/api/markets`                | Monitored markets + latest metrics       |
| `GET`  | `/api/execution?market=USDT/GRAM` | Execution samples for a market       |
| `GET`  | `/api/snapshots/{assets\|routers\|pools}` | Latest raw snapshot          |
| `GET`  | `/`                           | Interactive dashboard (HTML)             |

Example:

```bash
curl "http://127.0.0.1:8000/api/markets"
curl "http://127.0.0.1:8000/api/execution?market=USDT/GRAM"
```

## Metrics

- **Effective execution price** – ask amount / offer amount (ask units per offer unit).
- **Price impact** – reported by the STON.fi swap simulation (fraction).
- **Reference price** – effective price of the smallest simulated trade (low-impact).
- **Execution quality** – effective price relative to the reference price; below
  `1.0` means the trade executes worse than the low-impact reference.
- **Fee / execution cost** – total fee percent and basis points, plus fee amount in
  the ask token.
- **Liquidity** – pool TVL (`lp_total_supply_usd`) and 24h volume.

## STON.fi integration details

The engine integrates with the official STON.fi HTTP API (JavaScript client at
[`@ston-fi/api`](https://github.com/ston-fi/api)); Python consumes the underlying
HTTP endpoints directly:

- `GET  /v1/assets` – DEX asset discovery and USD reference prices
- `GET  /v1/routers` – supported routers
- `GET  /v1/pools` – pool reserves and liquidity info
- `POST /v1/swap/simulate` – swap simulation (used for execution analysis)

Because the official SDK is TypeScript, deeper contract-level interaction (e.g.
Router/Pool on-chain calls or live execution) is kept outside the Python core and
would be delegated to a small TypeScript service layer in a later phase. The MVP
operates purely in **analysis / simulation mode** and performs no live trades.

## Project structure

```
ston-liquidity-intelligence/
├── src/ston_liquidity_intelligence/
│   ├── client.py        # async STON.fi HTTP client
│   ├── models.py        # pydantic models
│   ├── analytics.py     # execution & liquidity metrics
│   ├── pipeline.py      # collection, simulation, orchestration
│   ├── repository.py    # SQLite persistence
│   ├── config.py        # environment configuration
│   ├── cli.py           # command-line interface
│   ├── api.py           # FastAPI REST + dashboard
│   └── __main__.py      # `python -m ston_liquidity_intelligence`
├── tests/               # pytest suite (mocked + live-ready)
├── .github/workflows/ci.yml
├── pyproject.toml
├── requirements.txt
└── .env.example
```

## Testing

```bash
pip install -e ".[dev,api]"
pytest
```

## Roadmap alignment

This repository currently ships **Phase 1 + part of Phase 2** of the proposal
("STON.fi Liquidity & Execution Intelligence Engine"): a working
`STON.fi API → Python → retrieve assets/pools → store data → produce a first
liquidity report` MVP, plus a REST API and dashboard. Later phases add continuous
scheduled collection, deeper analytics, opportunity detection and (eventually) an
execution interface.

## License

[MIT](LICENSE) © 2026 Pillar5 GmbH.