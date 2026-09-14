"""Tests for the HTTP client retry behaviour."""

import httpx
import pytest

from ston_liquidity_intelligence.client import StonApiClient, StonApiError


def _client_with_transport(handler) -> StonApiClient:
    client = StonApiClient(base_url="http://test", max_retries=2)
    client._client = httpx.AsyncClient(
        base_url="http://test", transport=httpx.MockTransport(handler)
    )
    return client


@pytest.mark.asyncio
async def test_retries_transient_status_codes():
    """503, 503, then 200: the client must retry and succeed."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] <= 2:
            return httpx.Response(503, text="unavailable")
        return httpx.Response(200, json={"ok": True})

    client = _client_with_transport(handler)
    data = await client._request("GET", "/v1/test")
    assert data == {"ok": True}
    assert calls["n"] == 3
    await client._client.aclose()


@pytest.mark.asyncio
async def test_retries_429_and_500_family():
    for status in (429, 500, 502, 504):
        calls = {"n": 0}

        def handler(request: httpx.Request, status=status, calls=calls) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(status, text="transient")
            return httpx.Response(200, json={"ok": True})

        client = _client_with_transport(handler)
        assert await client._request("GET", "/v1/test") == {"ok": True}
        assert calls["n"] == 2
        await client._client.aclose()


@pytest.mark.asyncio
async def test_does_not_retry_other_4xx():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(404, text="not found")

    client = _client_with_transport(handler)
    with pytest.raises(StonApiError):
        await client._request("GET", "/v1/test")
    assert calls["n"] == 1
    await client._client.aclose()


@pytest.mark.asyncio
async def test_exhausted_retries_raise_ston_api_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="down")

    client = _client_with_transport(handler)
    with pytest.raises(StonApiError):
        await client._request("GET", "/v1/test")
    await client._client.aclose()