"""Verify transient delivery retries preserve the signed request and stop on permanent errors."""

import asyncio

import httpx
import pytest

from tavus_cvi.api import callback_gateway


async def _no_delay(_seconds: float) -> None:
    return None


def test_gateway_retries_five_times_with_same_signed_body(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(callback_gateway.asyncio, "sleep", _no_delay)
    calls: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ReadTimeout("response lost", request=request)
        return httpx.Response(503 if len(calls) < 6 else 200, json={"status": "ok"})

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle), timeout=5) as client:
            response = await callback_gateway.deliver(client, b'{"tool_call_id":"stable"}', "sig")
            assert response.status_code == 200

    asyncio.run(run())
    assert len(calls) == 6
    assert all(call.content == b'{"tool_call_id":"stable"}' for call in calls)
    assert all(call.headers["x-tavus-signature"] == "sig" for call in calls)


@pytest.mark.parametrize("status", [400, 401, 403, 404, 409])
def test_permanent_callback_errors_are_not_retried(status: int) -> None:
    calls: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(status, json={"detail": "invalid"})

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            assert (await callback_gateway.deliver(client, b"{}", "sig")).status_code == status

    asyncio.run(run())
    assert len(calls) == 1


def test_retry_limit_reports_final_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(callback_gateway.asyncio, "sleep", _no_delay)
    calls: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(503)

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            assert (await callback_gateway.deliver(client, b"{}", "sig")).status_code == 503

    asyncio.run(run())
    assert len(calls) == 6


def test_rate_limit_is_retryable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(callback_gateway.asyncio, "sleep", _no_delay)
    calls: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(429 if len(calls) == 1 else 200)

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            assert (await callback_gateway.deliver(client, b"{}", "sig")).status_code == 200

    asyncio.run(run())
    assert len(calls) == 2
