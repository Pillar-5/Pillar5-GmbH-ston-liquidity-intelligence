# STON.fi Liquidity & Execution Analytics

[![CI](https://github.com/Pillar-5/Pillar5-GmbH-ston-liquidity-intelligence/actions/workflows/ci.yml/badge.svg)](https://github.com/Pillar-5/Pillar5-GmbH-ston-liquidity-intelligence/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

## What it does

This project collects market data from the STON.fi public HTTP API and uses the
STON.fi swap simulation endpoint to measure execution conditions across selected
TON markets. For each simulated trade it calculates the expected output, the
effective execution price, the price impact and the estimated fee cost. Results
are stored in SQLite and exposed through a REST API, a small dashboard and JSON
or Markdown reports.

The project does not execute trades and does not claim to detect profitable
arbitrage. Where two quoted prices differ, it reports a potential price
difference after estimated execution costs, not a proven opportunity.

## Current status

This is an early MVP. The current version:

- connects to the STON.fi API and discovers assets, routers and pools
- selects a small set of liquid TON markets by estimated pool liquidity
- runs swap simulations at several trade sizes per market
- stores snapshots and execution samples in SQLite
- serves the results through a REST API and a dashboard

The MVP establishes the collection, simulation and analytics pipeline. The next
stage will add continuous historical collection, broader market coverage,
gas-cost analysis and execution comparisons across venues.

## How it works

```
STON.fi HTTP API
    |
    v
market selection (pool liquidity filter)
    |
    v
swap simulation (POST /v1/swap/simulate)
    |
    v
execution analytics
    |
    v
SQLite storage
    |
    v
REST API + dashboard + reports
```

- `client`: async, throttled, retrying client for the STON.fi endpoints used.
- `models`: pydantic models mirroring the raw STON.fi API payloads.
- `analytics`: effective execution price, price impact, fee cost and execution
  quality relative to a reference trade.
- `pipeline`: discovers data, selects markets, runs simulations and orchestrates
  a full run.
- `repository`: SQLite persistence for raw snapshots and execution samples.
- `cli`: command-line interface for `run`, `collect`, `evaluate` and `serve`.
- `api`: FastAPI REST layer plus the embedded dashboard.

## Metrics

- **Effective execution price**: ask amount / offer amount (ask units per offer unit).
- **Price impact**: reported by the STON.fi swap simulation (fraction). The
  project uses the API value directly and does not recompute it.
- **Reference price**: the effective execution price of the smallest simulated
  trade size (a fraction of the base reserve, configurable via
  `STONFI_TRADE_SIZES`). Because it is a small fraction of pool liquidity, its
  price impact is small. It is used only as a comparison point.
- **Execution quality**: effective price relative to the reference price. Below
  `1.0` means the trade executes worse than the reference trade.
- **Fee cost**: the simulation returns the fee percentage as a fraction. The
  project reports that value as both a percentage and basis points by
  multiplying the fraction by 10,000, and converts the fee amount to ask-token
  units. The fee is not subtracted from the effective price because the
  simulated ask amount already reflects the execution result, so there is no
  double-counting.
- **Estimated pool liquidity**: the pool's `lp_total_supply_usd` field from the
  STON.fi API, which is the LP supply value in USD. This is a liquidity proxy,
  not a canonical TVL. 24h volume comes from `volume_24h_usd`.

## Example

Real output from a run against the live STON.fi API (`ston-liq run
--write-report md`), market USD₮/GRAM, six simulated trade sizes:

| Trade size (GRAM) | Notional USD | Effective price | Ref price | Quality | Impact | Fee bps |
|---|---:|---:|---:|---:|---:|---:|
| 254.139 | $254.04 | 0.73917804 | 0.73917804 | 1.000000 | 0.0100% | 30.04 |
| 2,541.39 | $2,540.37 | 0.73851477 | 0.73917804 | 0.999103 | 0.0997% | 30.06 |
| 12,707 | $12,701.85 | 0.73558126 | 0.73917804 | 0.995134 | 0.4965% | 30.14 |
| 25,413.9 | $25,403.71 | 0.73194698 | 0.73917804 | 0.990217 | 0.9881% | 30.24 |
| 50,827.8 | $50,807.42 | 0.7247851 | 0.73917804 | 0.980528 | 1.9569% | 30.44 |
| 127,070 | $127,018.54 | 0.7041164 | 0.73917804 | 0.952567 | 4.7528% | 31.04 |

Larger trades execute at progressively worse effective prices relative to the
reference trade in this example.

## STON.fi integration

The project uses the official STON.fi HTTP API v1 (JavaScript client at
[`@ston-fi/api`](https://github.com/ston-fi/api)). Python consumes the HTTP
endpoints directly:

- `GET  /v1/assets`: DEX asset discovery and USD reference prices
- `GET  /v1/routers`: supported routers
- `GET  /v1/pools`: pool reserves and liquidity info
- `POST /v1/swap/simulate`: swap simulation used for execution analysis

The simulation is called with the `units` parameter (the changelog of
`@ston-fi/api` records the removal of `offer_units`). Router metadata is
collected from `/v1/routers` and stored with the market data. Simulations are
tied to the selected pool using its `pool_address`.

Because the official SDK is TypeScript, deeper contract-level interaction
(Router/Pool on-chain calls or live execution) is kept outside the Python core
and would be delegated to a small TypeScript service layer in a later phase.
The MVP operates purely in analysis and simulation mode and performs no live
trades. No v2 (`dexV2`) data is mixed into the v1 endpoints used here.

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
| `STONFI_MIN_POOL_TVL_USD`      | `50000`                              | Minimum pool liquidity (USD proxy)       |
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

## Limitations

- Analysis and simulation only. The system does not execute trades.
- Market coverage is a small liquidity-filtered set of pools per run. It is not a
  full snapshot of STON.fi markets.
- Execution metrics come from simulations at the configured trade sizes. They are
  estimates, not guaranteed execution outcomes.
- Historical tracking exists in SQLite, but there is no scheduled continuous
  collection yet.
- Price differences between quoted prices are reported as potential differences
  after estimated execution costs. Executable profitability is not established.

## Planned work

- Scheduled continuous collection and historical tracking over time
- Broader market coverage and configurable market universes
- Reference-price comparisons and execution-cost filtering for price differences
- A small TypeScript service layer for contract-level STON.fi interaction where
  the Python core is not sufficient
- More validation of simulation results against observed on-chain conditions

## License

[MIT](LICENSE) © 2026 Pillar5 GmbH.