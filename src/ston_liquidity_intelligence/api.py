"""FastAPI application exposing the analytics layer over HTTP.

Endpoints
---------
- ``GET  /health``                         - liveness/diagnostics
- ``GET  /api/summary``                    - overall liquidity & discovery summary
- ``GET  /api/markets``                    - list monitored markets + latest samples
- ``GET  /api/markets/{market}/execution`` - execution samples for one market
- ``GET  /api/snapshots/{type}``           - latest stored raw snapshot
- ``GET  /``                               - interactive dashboard (HTML)

The dashboard depends on the ``api`` extra (``pip install .[api]``).
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

from .config import Settings
from .repository import Repository

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>STON.fi Liquidity &amp; Execution Analytics</title>
<style>
  :root { --fg:#e6edf3; --muted:#9ba7b0; --bg:#0d1117; --card:#161b22; --acc:#238636; }
  * { box-sizing:border-box; }
  body { margin:0; font-family:-apple-system,Segoe UI,Roboto,sans-serif; background:var(--bg); color:var(--fg); }
  header { padding:1.2rem 2rem; border-bottom:1px solid #21262d; }
  header h1 { font-size:1.25rem; margin:0 0 .2rem; }
  header p { margin:0; color:var(--muted); font-size:.9rem; }
  main { padding:1.5rem 2rem; max-width:1200px; margin:0 auto; }
  .cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:1rem; }
  .card { background:var(--card); border:1px solid #21262d; border-radius:10px; padding:1rem; }
  .card h3 { margin:0 0 .4rem; font-size:.8rem; text-transform:uppercase; letter-spacing:.05em; color:var(--muted); }
  .card .value { font-size:1.5rem; font-weight:600; }
  table { width:100%; border-collapse:collapse; margin-top:1.5rem; font-size:.85rem; }
  th,td { text-align:right; padding:.5rem .75rem; border-bottom:1px solid #21262d; }
  th:first-child,td:first-child { text-align:left; }
  th { color:var(--muted); font-weight:600; text-transform:uppercase; font-size:.75rem; }
  tr:hover { background:#161b22; }
</style>
</head>
<body>
<header><h1>STON.fi Liquidity &amp; Execution Analytics</h1>
<p>Execution quality across monitored TON markets &middot; data: live STON.fi API</p></header>
<main>
  <section class="cards" id="summary"></section>
  <h2 style="margin-top:2rem">Market execution survey</h2>
  <table id="markets"><thead>
    <tr><th>Market</th><th>Pool</th><th>Largest trade (USD)</th>
    <th>Price impact (largest)</th><th>Avg execution quality</th><th>Samples</th></tr>
  </thead><tbody></tbody></table>
  <h2 style="margin-top:2rem">Execution quality curve</h2>
  <p style="color:var(--muted);font-size:.85rem">Select a market:</p>
  <select id="marketPicker"></select>
  <canvas id="chart" width="900" height="320" style="background:var(--card);border:1px solid #21262d;border-radius:10px;margin-top:.75rem"></canvas>
</main>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<script>
const fmt = new Intl.NumberFormat("en-US",{style:"currency",currency:"USD"});
async function load(){
  const m = await (await fetch("/api/markets")).json();
  const summary = await (await fetch("/api/summary")).json();
  document.getElementById("summary").innerHTML = [
    ["Markets selected", summary.markets_selected ?? 0],
    ["Markets evaluated", summary.markets_evaluated ?? 0],
    ["Simulations", (summary.simulations_successful ?? 0) + " ok / " + (summary.simulations_failed ?? 0) + " failed"],
    ["Estimated liquidity", fmt.format(summary.liquidity?.total_liquidity_usd_est ?? 0)],
    ["Execution samples", summary.execution_samples ?? 0],
  ].map(([k,v])=>`<div class="card"><h3>${k}</h3><div class="value">${v}</div></div>`).join("");
  const tb = document.querySelector("#markets tbody");
  tb.innerHTML = m.markets.map(x=>`<tr>
    <td>${x.market}</td><td>${x.pool_address}</td>
    <td>${fmt.format(x.largest_notional_usd)}</td>
    <td>${(x.impact_largest*100).toFixed(4)}%</td>
    <td>${x.avg_quality.toFixed(4)}</td><td>${x.samples}</td></tr>`).join("");
  const picker = document.getElementById("marketPicker");
  picker.innerHTML = m.markets.map(x=>`<option value="${x.market}">${x.market}</option>`).join("");
  await draw(m.markets[0]);
  picker.onchange = () => draw(m.markets.find(x=>x.market===picker.value));
}
let chart;
async function draw(sel){
  if(!sel) return;
  const data = await (await fetch(`/api/execution?market=${encodeURIComponent(sel.market)}`)).json();
  const labels = data.samples.map(s=>s.trade_size_base);
  const quality = data.samples.map(s=>s.execution_quality);
  if(chart) chart.destroy();
  chart = new Chart(document.getElementById("chart"),{type:"line",data:{labels,datasets:[{
      label:"Execution quality vs reference",data:quality,borderColor:"#238636",backgroundColor:"#23863633",fill:true,tension:.2,
      pointBackgroundColor:"#238636"}]},options:{responsive:false,scales:{y:{min:0.9,max:1.05,title:{display:true,text:"relative quality"}},x:{title:{display:true,text:"trade size (base units)"}}}}});
}
load();
</script>
</body>
</html>"""

def _markets_view(db: Repository) -> list[dict]:
    """Summarise the latest sample per market in a dashboard-friendly form."""
    samples = [dict(r) for r in db.execution_samples(limit=20000)]
    grouped: dict[str, list[dict]] = {}
    for r in samples:
        grouped.setdefault(r["market"], []).append(r)
    view = []
    for market, rows in grouped.items():
        largest = max(rows, key=lambda s: s["trade_size_base"] or 0)
        quality = [s["execution_quality"] for s in rows if s.get("execution_quality") is not None]
        view.append(
            {
                "market": market,
                "pool_address": rows[0]["pool_address"],
                "samples": len(rows),
                "largest_trade_base": largest["trade_size_base"],
                "largest_notional_usd": largest.get("notional_usd") or 0,
                "impact_largest": largest.get("price_impact") or 0,
                "avg_quality": round(sum(quality) / len(quality), 6) if quality else 0,
            }
        )
    return sorted(view, key=lambda x: x["largest_notional_usd"], reverse=True)


def create_app(settings: Settings) -> FastAPI:
    app = FastAPI(
        title="STON.fi Liquidity & Execution Analytics",
        version="0.1.0",
        description="REST API for STON.fi liquidity and execution analytics.",
    )
    db = Repository(settings.db_path)

    def _latest(type_: str) -> list:
        raw = db.latest_snapshot(type_)
        if raw is None:
            raise HTTPException(status_code=404, detail=f"no {type_} snapshot stored")
        return raw

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "db": settings.db_path}

    @app.get("/api/summary")
    def summary() -> dict:
        pools = _latest("pools")
        liq = [p for p in pools if not p.get("deprecated", False)]
        views = _markets_view(db)
        run: dict = db.latest_snapshot("run_summary") or {}
        markets_evaluated = run.get("markets_evaluated") or len(views)
        return {
            "discovery": {
                "assets": len(_latest("assets")),
                "routers": len(_latest("routers")),
                "pools": len(pools),
            },
            "liquidity": {
                "total_liquidity_usd_est": round(sum(float(p.get("lp_total_supply_usd") or 0) for p in liq), 2),
                "total_volume_24h_usd": round(sum(float(p.get("volume_24h_usd") or 0) for p in liq), 2),
                "liquid_pools": len(liq),
            },
            "markets": views,
            "markets_selected": run.get("markets_selected") or markets_evaluated,
            "markets_evaluated": markets_evaluated,
            "simulations_attempted": run.get("simulations_attempted", 0),
            "simulations_successful": run.get("simulations_successful", 0),
            "simulations_failed": run.get("simulations_failed", 0),
            "execution_samples": len(db.execution_samples(limit=100000)),
        }

    @app.get("/api/markets")
    def markets() -> dict:
        return {"markets": _markets_view(db)}

    @app.get("/api/execution")
    def market_execution(
        market: str = Query(..., description="Market name, e.g. USDT/GRAM"),
        limit: int = Query(50, ge=1, le=500),
    ) -> dict:
        rows = db.execution_samples(market=market, limit=limit)
        return {"market": market, "samples": [dict(r) for r in rows]}

    @app.get("/api/snapshots/{type_}")
    def snapshot(type_: str) -> list:
        return _latest(type_)

    @app.get("/", response_class=HTMLResponse)
    def dashboard() -> str:
        return DASHBOARD_HTML

    return app