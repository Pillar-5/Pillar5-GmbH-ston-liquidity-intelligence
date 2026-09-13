"""Application configuration.

Settings are read from environment variables (optionally from a ``.env`` file),
so the pipeline can be tuned without touching code.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Canonical TON (GRAM) jetton master / native asset address on the STON.fi API.
TON_ADDRESS = "EQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAM9c"


def _load_dotenv(path: str = ".env") -> None:
    """Minimal ``.env`` loader that does not clobber existing environment vars."""
    p = Path(path)
    if not p.exists():
        return
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


@dataclass
class Settings:
    api_base_url: str = "https://api.ston.fi"
    api_key: str | None = None
    db_path: str = "data/liquidity.db"
    report_dir: str = "reports"

    timeout_seconds: float = 30.0
    max_concurrency: int = 8
    max_retries: int = 2

    min_pool_tvl_usd: float = 50_000.0
    max_pools: int = 12
    trade_sizes: tuple[float, ...] = (0.0001, 0.001, 0.005, 0.01, 0.02, 0.05)
    slippage_tolerance: float = 0.01

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Settings":
        env = env or os.environ

        def _num(name: str, default: float) -> float:
            raw = env.get(name)
            return float(raw) if raw not in (None, "") else default

        def _str(name: str, default: str) -> str:
            return env.get(name) or default

        def _sizes(name: str, default: tuple[float, ...]) -> tuple[float, ...]:
            raw = env.get(name)
            if not raw:
                return default
            try:
                return tuple(float(x) for x in raw.split(",") if x.strip() != "")
            except ValueError:
                return default

        return cls(
            api_base_url=_str("STONFI_API_BASE_URL", cls.api_base_url),
            api_key=_str("STONFI_API_KEY", "") or None,
            db_path=_str("STONFI_DB_PATH", cls.db_path),
            report_dir=_str("STONFI_REPORT_DIR", cls.report_dir),
            timeout_seconds=_num("STONFI_TIMEOUT_SECONDS", cls.timeout_seconds),
            max_concurrency=int(_num("STONFI_MAX_CONCURRENCY", cls.max_concurrency)),
            max_retries=int(_num("STONFI_MAX_RETRIES", cls.max_retries)),
            min_pool_tvl_usd=_num("STONFI_MIN_POOL_TVL_USD", cls.min_pool_tvl_usd),
            max_pools=int(_num("STONFI_MAX_POOLS", cls.max_pools)),
            trade_sizes=_sizes("STONFI_TRADE_SIZES", cls.trade_sizes),
            slippage_tolerance=_num("STONFI_SLIPPAGE_TOLERANCE", cls.slippage_tolerance),
        )


def _default_settings() -> Settings:
    """Return settings loaded from the environment for interactive/CLI use."""
    _load_dotenv()
    return Settings.from_env()