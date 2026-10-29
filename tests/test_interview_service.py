"""Interview lifecycle with an in-memory store and a fake Tavus transport."""

import random
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from tavus_cvi.adapters.tavus_client import TavusClient
from tavus_cvi.domain.errors import InvalidPhaseTransitionError, TavusIntegrationError
from tavus_cvi.services.interview_service import InterviewService
from tests.support import InMemoryStore, open_session, sample_card


def _client(calls: list[httpx.Request]) -> TavusClient:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path == "/v2/conversations" and request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "conversation_id": "conv-9",
                    "conversation_url": "https://tavus.daily.co/room",
                },
            )
        if request.url.path == "/v2/memory-stores":
            return httpx.Response(200, json={"memory_store_id": "mem-1"})
        if request.url.path.endswith("/pinned"):
            return httpx.Response(200, json={"memory_id": "pin-1"})
        if request.url.path.endswith("/end"):
            return httpx.Response(200, json={})
        return httpx.Response(404, json={"error": "missing"})

    return TavusClient("test-key", "https://tavusapi.com", transport=httpx.MockTransport(handler))


def test_start_opens_a_room_and_pins_the_cv(tmp_path: Path) -> None:
    store = InMemoryStore()
    calls: list[httpx.Request] = []
    client = _client(calls)
    service = InterviewService(store, client, tmp_path, rng=random.Random(1))
    session = service.start(system_design_id=2)
    stored = store.get_interview(session.id)
    assert stored is not None
    assert stored.tavus_conversation_url == "https://tavus.daily.co/room"
    assert stored.system_design_id == 2
    assert stored.current_phase == "intro"
    body = next(call for call in calls if call.url.path == "/v2/conversations").read().decode()
    assert f"interview_{session.id}" in body
    assert "AI interviewer" in body
    assert "Sam Linfield" in body
    assert "SCL CV.pdf" in body
    assert any(call.url.path.endswith("/pinned") for call in calls)
    client.close()


def test_start_requires_a_provisioned_pal(tmp_path: Path) -> None:
    store = InMemoryStore(card=sample_card(pal_id=None))
    service = InterviewService(store, None, tmp_path)
    with pytest.raises(TavusIntegrationError):
        service.start(None)


def test_transition_ends_the_remote_call(tmp_path: Path) -> None:
    store = InMemoryStore()
    session = open_session(store)
    calls: list[httpx.Request] = []
    client = _client(calls)
    service = InterviewService(store, client, tmp_path)
    finished = service.transition(session.id, "candidate_left")
    assert finished.current_phase == "candidate_left"
    assert finished.ended_at is not None
    assert any(call.url.path.endswith("/end") for call in calls)
    client.close()


def test_unknown_interview_cannot_change_phase(tmp_path: Path) -> None:
    service = InterviewService(InMemoryStore(), None, tmp_path)
    with pytest.raises(InvalidPhaseTransitionError):
        service.transition(uuid4(), "coding_easy")


def test_illegal_phase_and_missing_problems_are_rejected(tmp_path: Path) -> None:
    store = InMemoryStore()
    session = open_session(store)
    service = InterviewService(store, None, tmp_path)
    with pytest.raises(InvalidPhaseTransitionError):
        service.transition(session.id, "system_design")
    store.problems = []
    with pytest.raises(InvalidPhaseTransitionError):
        service.start(None)


def test_select_design_rejects_a_frozen_interview(tmp_path: Path) -> None:
    store = InMemoryStore()
    session = open_session(store)
    session.started_at = datetime.now(UTC) - timedelta(seconds=3400)
    service = InterviewService(store, None, tmp_path)
    with pytest.raises(InvalidPhaseTransitionError):
        service.select_design(session.id, 2)


def test_select_design_updates_the_prompt(tmp_path: Path) -> None:
    store = InMemoryStore()
    session = open_session(store)
    service = InterviewService(store, None, tmp_path)
    updated = service.select_design(session.id, 2)
    assert updated.system_design_id == 2


def test_status_reports_the_assigned_problems(tmp_path: Path) -> None:
    store = InMemoryStore()
    session = open_session(store)
    service = InterviewService(store, None, tmp_path)
    payload = service.status(session.id)
    assert payload["frozen"] is False
    assert payload["easy"]["question_title"] == "Problem 1"
    assert payload["system_design"]["question_title"] == "Design 1"


def test_optional_memory_failure_keeps_the_created_room_usable(tmp_path):
    store = InMemoryStore()
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.path == "/v2/memory-stores":
            return httpx.Response(500)
        assert len(store.interviews) == 1  # Setup was saved before room creation.
        return httpx.Response(
            200,
            json={
                "conversation_id": "usable",
                "conversation_url": "https://fixture.daily.co/usable",
            },
        )

    client = TavusClient("fixture", "https://example.test", transport=httpx.MockTransport(handler))
    session = InterviewService(store, client, tmp_path).start(None)
    assert session.tavus_conversation_id == "usable" and session.ended_at is None
    client.close()


def test_room_is_compensated_when_post_creation_save_fails(tmp_path):
    store = InMemoryStore()
    original = store.save_interview
    attempts = 0

    def failing_save(session):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("synthetic persistence failure")
        original(session)

    store.save_interview = failing_save
    calls = []
    client = _client(calls)
    with pytest.raises(RuntimeError, match="persistence failure"):
        InterviewService(store, client, tmp_path).start(None)
    assert any(call.url.path == "/v2/conversations/conv-9/end" for call in calls)
    assert next(iter(store.interviews.values())).ended_at is not None
    client.close()


def test_local_end_is_saved_even_when_remote_termination_fails(tmp_path):
    store = InMemoryStore()
    session = open_session(store)

    def handler(request):
        assert store.get_interview(session.id).ended_at is not None
        return httpx.Response(500)

    client = TavusClient("fixture", "https://example.test", transport=httpx.MockTransport(handler))
    result = InterviewService(store, client, tmp_path).transition(session.id, "candidate_left")
    assert result.ended_at is not None
    client.close()


def test_leave_at_the_server_deadline_preserves_completed_state(tmp_path):
    store = InMemoryStore()
    session = open_session(store)
    session.started_at = datetime.now(UTC) - timedelta(seconds=3601)
    finished = InterviewService(store, None, tmp_path).transition(session.id, "candidate_left")
    assert finished.current_phase == "completed" and finished.ended_at
