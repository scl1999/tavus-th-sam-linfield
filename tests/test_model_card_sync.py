"""YAML sync and Tavus provisioning with a mocked HTTP transport."""

import json
from pathlib import Path

import httpx
import pytest

from tavus_cvi.adapters.config import REPO_ROOT
from tavus_cvi.adapters.tavus_client import TavusClient
from tavus_cvi.domain.errors import ModelCardValidationError
from tavus_cvi.services.model_card_service import ModelCardService, load_card_file
from tests.support import InMemoryStore, sample_card


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/v2/voices":
        return httpx.Response(
            200,
            json={"data": [{"voice_name": "Charlie Studio", "voice_id": "vcharlie"}]},
        )
    if path == "/v2/guardrails":
        return httpx.Response(200, json={"uuid": "guard-1"})
    if path == "/v2/objectives":
        return httpx.Response(200, json={"objectives_id": "obj-1"})
    if path == "/v2/pals" and request.method == "POST":
        return httpx.Response(200, json={"pal_id": "pal-charlie"})
    if path == "/v2/tools" and request.method == "POST":
        return httpx.Response(200, json={"tool_id": "tool-1"})
    if path.endswith("/tools"):
        return httpx.Response(200, json={"data": []})
    return httpx.Response(404, json={"error": path})


def test_sync_provisions_charlie_and_skips_an_existing_checksum() -> None:
    store = InMemoryStore(card=sample_card(pal_id=None))
    pal_posts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2/pals" and request.method == "POST":
            pal_posts.append(request.url.path)
        return _handler(request)

    client = TavusClient("test-key", "https://tavusapi.com", transport=httpx.MockTransport(handler))
    service = ModelCardService(store, client, "https://callback.example.test", "test-secret")
    cards = service.sync_directory(REPO_ROOT / "config" / "agents")
    names = {card.agent_name for card in cards}
    assert names == {"charlie_interviewer", "context_compressor"}
    assert store.pal_ids[9] == "pal-charlie"
    again = service.sync_directory(REPO_ROOT / "config" / "agents")
    assert len(store.inserted_cards) == 2
    assert pal_posts == ["/v2/pals"]
    assert all(card.tavus_pal_id for card in again if card.agent_name == "charlie_interviewer")
    client.close()


def test_voice_id_is_used_when_it_already_looks_like_an_id(tmp_path: Path) -> None:
    path = tmp_path / "voice.yaml"
    card_path = REPO_ROOT / "config" / "agents" / "charlie_interviewer.yaml"
    source = card_path.read_text(encoding="utf-8")
    path.write_text(source.replace("voice_id: charlie", "voice_id: v12345"), encoding="utf-8")
    seen: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2/pals" and request.method == "POST":
            seen.append(json.loads(request.content))
        return _handler(request)

    store = InMemoryStore()
    client = TavusClient("test-key", "https://tavusapi.com", transport=httpx.MockTransport(handler))
    ModelCardService(store, client, "https://callback.example.test", "test-secret").sync_directory(
        tmp_path
    )
    assert seen[0]["layers"]["tts"]["voice_id"] == "v12345"
    client.close()


def test_boolean_temperature_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text(
        """
version: 3
agent_name: bad
model: x
pipeline_mode: chat
face_id: n/a
voice_id: n/a
perception_model: none
turn_detection_model: none
max_concurrent_tool_calls: 1
max_context_tokens: 5000
temperature: true
top_p: 1
context_template: hi
hardcoded_reminder_template: hi
system_instructions: hi
""",
        encoding="utf-8",
    )
    with pytest.raises(ModelCardValidationError):
        load_card_file(path)
