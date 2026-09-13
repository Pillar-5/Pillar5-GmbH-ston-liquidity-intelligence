"""Async client for the STON.fi public HTTP API.

Implements the subset of endpoints used by the intelligence engine:

- ``GET /v1/assets``            - discover DEX assets
- ``GET /v1/routers``           - discover supported routers
- ``GET /v1/pools``             - retrieve pool / liquidity information
- ``POST /v1/swap/simulate``    - simulate a swap to measure execution quality

The full endpoint catalogue is documented in the official ``@ston-fi/api``
TypeScript client (https://github.com/ston-fi/api), which this module mirrors.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

import httpx

from .models import Asset, Pool, Router, SwapSimulation

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.ston.fi"
DEFAULT_USER_AGENT = "ston-liquidity-intelligence/0.1 (+https://github.com/Pillar-5/Pillar5-GmbH-ston-liquidity-intelligence)"


class StonApiError(RuntimeError):
    """Raised when the STON.fi API returns a non-2xx response or is unreachable."""


class StonApiClient:
    """Thin, retrying, throttled async client over the STON.fi HTTP API."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30.0,
        max_retries: int = 2,
        max_concurrency: int = 8,
        api_key: Optional[str] = None,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._max_retries = max_retries
        self._api_key = api_key
        self._client: Optional[httpx.AsyncClient] = None
        self._semaphore = asyncio.Semaphore(max(1, max_concurrency))
        self._user_agent = user_agent

    async def __aenter__(self) -> "StonApiClient":
        await self.start()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    async def start(self) -> None:
        if self._client is None:
            headers = {"User-Agent": self._user_agent}
            if self._api_key:
                headers["Authorization"] = f"Bearer {self._api_key}"
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout,
                headers=headers,
            )

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict] = None,
    ) -> dict[str, Any]:
        """Issue a throttled request, retrying transient HTTP errors."""
        await self.start()
        assert self._client is not None

        last_exc: Optional[Exception] = None
        for attempt in range(self._max_retries + 1):
            try:
                async with self._semaphore:
                    resp = await self._client.request(method, path, params=params)
                if resp.status_code >= 400:
                    raise StonApiError(
                        f"{method} {path} -> HTTP {resp.status_code}: {resp.text[:300]}"
                    )
                return resp.json()
            except httpx.HTTPError as exc:  # network / timeout / connection errors
                last_exc = exc
                if attempt < self._max_retries:
                    logger.warning(
                        "request %s %s attempt %d/%d failed: %s",
                        method,
                        path,
                        attempt + 1,
                        self._max_retries + 1,
                        exc,
                    )
                    await asyncio.sleep(0.5 * (attempt + 1))

        raise StonApiError(f"request {method} {path} failed after retries: {last_exc}")

    # ------------------------------------------------------------------ assets
    async def get_assets(self) -> list[Asset]:
        data = await self._request("GET", "/v1/assets")
        return [Asset.model_validate(a) for a in data.get("asset_list", [])]

    async def get_asset(self, asset_address: str) -> Asset:
        data = await self._request("GET", f"/v1/assets/{asset_address}")
        return Asset.model_validate(data["asset"])

    # ---------------------------------------------------------------- routers
    async def get_routers(self) -> list[Router]:
        data = await self._request("GET", "/v1/routers")
        return [Router.model_validate(r) for r in data.get("router_list", [])]

    # ------------------------------------------------------------------- pools
    async def get_pools(self) -> list[Pool]:
        data = await self._request("GET", "/v1/pools")
        return [Pool.model_validate(p) for p in data.get("pool_list", [])]

    async def get_pool(self, pool_address: str) -> Pool:
        data = await self._request("GET", f"/v1/pools/{pool_address}")
        return Pool.model_validate(data["pool"])

    # ------------------------------------------------------------------ swaps
    async def simulate_swap(
        self,
        offer_address: str,
        ask_address: str,
        offer_units: int | str,
        slippage_tolerance: float = 0.01,
        pool_address: Optional[str] = None,
    ) -> SwapSimulation:
        """Simulate a direct swap, selling ``offer_address`` for ``ask_address``.

        ``offer_units`` is the amount sold, expressed in the offer token's raw
        units (i.e. token amount * 10**decimals).
        """
        params: dict[str, str] = {
            "offer_address": offer_address,
            "ask_address": ask_address,
            "units": str(offer_units),
            "slippage_tolerance": str(slippage_tolerance),
        }
        if pool_address:
            params["pool_address"] = pool_address
        data = await self._request("POST", "/v1/swap/simulate", params=params)
        return SwapSimulation.model_validate(data)