"""Expose only this handler through the temporary tunnel, never the candidate API."""

import asyncio
import logging

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import Response

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
MAX_RETRIES = 5
logger = logging.getLogger(__name__)


async def deliver(client: httpx.AsyncClient, raw: bytes, signature: str) -> Response:
    """Retry transient local delivery failures using the identical signed invocation."""
    for attempt in range(MAX_RETRIES + 1):
        try:
            result = await client.post(
                "http://127.0.0.1:8000/internal/tavus/tools",
                content=raw,
                headers={"x-tavus-signature": signature, "content-type": "application/json"},
            )
            if (result.status_code < 500 and result.status_code != 429) or attempt == MAX_RETRIES:
                return Response(
                    content=result.content,
                    status_code=result.status_code,
                    media_type="application/json",
                )
            logger.warning(
                "Callback attempt %s failed with HTTP %s", attempt + 1, result.status_code
            )
        except httpx.TransportError:
            if attempt == MAX_RETRIES:
                return Response(
                    content='{"detail":"Callback delivery unavailable"}',
                    status_code=502,
                    media_type="application/json",
                )
            logger.warning("Callback attempt %s failed to reach the API", attempt + 1)
        await asyncio.sleep(min(0.2 * 2**attempt, 2.0))
    raise AssertionError("Unreachable retry state")


@app.post("/tavus/tools")
async def forward_tool(request: Request) -> Response:
    raw = bytearray()
    async for part in request.stream():
        raw.extend(part)
        if len(raw) > 20000:
            return Response(status_code=413)
    async with httpx.AsyncClient(timeout=5) as client:
        return await deliver(client, bytes(raw), request.headers.get("x-tavus-signature", ""))
