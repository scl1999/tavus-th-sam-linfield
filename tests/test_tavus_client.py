"""Tavus response id parsing."""

import json

import httpx
import pytest

from tavus_cvi.adapters.tavus_client import TavusClient
from tavus_cvi.domain.errors import TavusIntegrationError


def test_guardrail_id_comes_from_uuid() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v2/guardrails"
        return httpx.Response(200, json={"uuid": "g-1", "guardrail_name": "focus"})

    client = TavusClient("test-key", "https://tavusapi.com", transport=httpx.MockTransport(handler))
    assert client.create_guardrail("focus", "Stay on the interview.") == "g-1"
    client.close()


def test_duplicate_guardrail_reuses_the_existing_uuid() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(400, json={"error": "exists"})
        return httpx.Response(200, json={"data": [{"uuid": "g-2", "guardrail_name": "focus"}]})

    client = TavusClient("test-key", "https://tavusapi.com", transport=httpx.MockTransport(handler))
    assert client.create_guardrail("focus", "Stay on the interview.") == "g-2"
    client.close()


def test_create_conversation_requires_a_room_url() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"conversation_id": "c1"})

    client = TavusClient("test-key", "https://tavusapi.com", transport=httpx.MockTransport(handler))
    with pytest.raises(TavusIntegrationError):
        client.create_conversation({"pal_id": "p1"})
    client.close()


def test_existing_memory_store_is_not_an_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"error": "exists"})

    client = TavusClient("test-key", "https://tavusapi.com", transport=httpx.MockTransport(handler))
    assert client.create_memory_store("pal-1", "candidate_1") is None
    client.close()


def test_pin_memory_sends_the_memory_field() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"memory_id": "pm-1"})

    client = TavusClient("test-key", "https://tavusapi.com", transport=httpx.MockTransport(handler))
    client.pin_memory("mem-1", "x" * 600)
    assert seen["path"] == "/v2/memory-stores/mem-1/pinned"
    assert len(str(seen["body"]["memory"])) == 500
    client.close()


def test_chat_start_and_empty_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/end"):
            return httpx.Response(204)
        return httpx.Response(
            200, json={"conversation_id": "chat-1", "conversation_url": "https://x"}
        )

    client = TavusClient("test-key", "https://tavusapi.com", transport=httpx.MockTransport(handler))
    assert client.chat_start("pal-1") == "chat-1"
    client.end_conversation("chat-1")
    client.close()


def test_existing_tool_is_updated_to_speak_after_it_returns() -> None:
    seen: list[tuple[str, str, dict[str, object] | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        seen.append((request.method, request.url.path, body))
        if request.method == "POST":
            return httpx.Response(409, json={"message": "exists"})
        if request.method == "GET":
            return httpx.Response(
                200,
                json={"data": [{"name": "start_technical_interview", "tool_id": "tool-9"}]},
            )
        return httpx.Response(200, json={"tool_id": "tool-9"})

    client = TavusClient("test-key", "https://tavusapi.com", transport=httpx.MockTransport(handler))
    assert (
        client.create_tool(
            {
                "name": "start_technical_interview",
                "description": "Open it",
                "on_resolve": "generate_response",
            }
        )
        == "tool-9"
    )
    patch = next(item for item in seen if item[0] == "PATCH")
    assert patch[1] == "/v2/tools/tool-9"
    assert patch[2] is not None
    assert patch[2]["on_resolve"] == "generate_response"
    client.close()


def test_tool_and_objectives_ids_are_read() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "objectives" in request.url.path:
            return httpx.Response(200, json={"objectives_id": "obj-1"})
        return httpx.Response(200, json={"tool_id": "tool-9"})

    client = TavusClient("test-key", "https://tavusapi.com", transport=httpx.MockTransport(handler))
    assert client.create_objectives([{"name": "intro", "prompt": "Greet"}]) == "obj-1"
    tool_id = client.create_tool({"name": "start_technical_interview", "description": "Open it"})
    assert tool_id == "tool-9"
    client.close()


def test_http_error_includes_the_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "nope"})

    client = TavusClient("test-key", "https://tavusapi.com", transport=httpx.MockTransport(handler))
    with pytest.raises(TavusIntegrationError, match="401"):
        client.list_voices()
    client.close()


def test_remote_cleanup_is_idempotent_for_an_already_ended_room():
    def handler(request):
        return (
            httpx.Response(409)
            if request.method == "POST"
            else httpx.Response(200, json={"status": "ended"})
        )

    client = TavusClient("fixture", "https://example.test", transport=httpx.MockTransport(handler))
    client.end_conversation("already-ended")
    client.close()


def test_existing_versioned_tool_is_found_on_later_registry_page():
    requests = []

    def handle(request):
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(409, json={"message": "already exists"})
        if request.method == "GET":
            if request.url.params.get("page") == "2":
                return httpx.Response(
                    200,
                    json={
                        "total_count": 2,
                        "data": [{"name": "start_technical_interview_v9", "tool_id": "new-tool"}],
                    },
                )
            return httpx.Response(
                200, json={"total_count": 2, "data": [{"name": "old_tool", "tool_id": "old-tool"}]}
            )
        return httpx.Response(200, json={"tool_id": "new-tool"})

    client = TavusClient("fixture", "https://example.test", transport=httpx.MockTransport(handle))
    assert (
        client.create_tool({"name": "start_technical_interview_v9", "description": "open"})
        == "new-tool"
    )
    assert any(req.method == "PATCH" and req.url.path.endswith("/new-tool") for req in requests)
    client.close()
