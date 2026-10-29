"""Adversarial regression tests against PostgreSQL; fixture data is rolled back."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from tavus_cvi.adapters.config import REPO_ROOT, Settings
from tavus_cvi.adapters.runtime_repository import RuntimeRepository
from tavus_cvi.adapters.tavus_client import TavusClient
from tavus_cvi.api.app import create_app
from tavus_cvi.api.security import COOKIE, token_hash
from tavus_cvi.domain.entities import Candidate, InterviewSession
from tavus_cvi.services.context_compression_service import ContextCompressionService
from tavus_cvi.services.interview_service import InterviewService
from tavus_cvi.services.model_card_service import load_card_file
from tavus_cvi.services.private_context import private_context
from tavus_cvi.services.recording_service import RecordingService
from tavus_cvi.services.telemetry_service import TelemetryService
from tests.support import sample_problem

pytestmark = pytest.mark.skipif(
    not os.getenv("TAVUS_TEST_DATABASE_URL"), reason="PostgreSQL URL not set"
)


@pytest.fixture
def runtime(tmp_path):
    url = os.environ["TAVUS_TEST_DATABASE_URL"]
    parent = RuntimeRepository(url)
    parent.apply_schema((REPO_ROOT / "src/tavus_cvi/adapters/db/repair.sql").read_text())
    connection = psycopg.connect(url, row_factory=dict_row)
    connection.execute("BEGIN")
    repository = parent.borrow(connection)
    card = load_card_file(REPO_ROOT / "config/agents/charlie_interviewer.yaml")
    if not repository.find_card_by_sha(card.yaml_sha256):
        repository.insert_card(card)
    candidate = Candidate(uuid4(), "Fixture candidate", f"{uuid4()}@example.test", "Engineer")
    repository.insert_candidate(candidate)
    easy = repository.upsert_problem(
        replace(sample_problem(100001, "Easy"), hints=["PRIVATE_FIXTURE_HINT"])
    )
    medium = repository.upsert_problem(sample_problem(100003, "Medium"))
    design = repository.list_designs()[0].id
    session = InterviewSession(
        uuid4(),
        candidate.id,
        card.version,
        "intro",
        datetime.now(UTC),
        easy_leetcode_id=easy,
        medium_leetcode_id=medium,
        system_design_id=design,
        tavus_conversation_id=f"test-{uuid4()}",
        tavus_conversation_url="https://fixture.daily.co/test",
    )
    repository.insert_interview(session)
    capability = str(uuid4())
    repository.create_runtime(session.id, token_hash(capability))
    repository.set_runtime(session.id, setup_state="ready")
    tavus = TavusClient(
        "fixture",
        "https://example.test",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"status": "active"})
        ),
    )
    settings = Settings(
        TAVUS_API_KEY="",
        DATABASE_URL=url,
        recordings_dir=tmp_path,
        callback_base_url="https://callback.example.test",
        callback_secret="fixture-secret",
    )
    app = create_app(settings)

    @asynccontextmanager
    async def no_startup(_app):
        yield

    app.router.lifespan_context = no_startup
    service = InterviewService(repository, tavus, tmp_path)
    app.state.repository = repository
    app.state.tavus = tavus
    app.state.interviews = service
    app.state.compression = ContextCompressionService()
    app.state.telemetry = TelemetryService(repository, app.state.compression)
    app.state.recordings = RecordingService(repository, tmp_path)
    with TestClient(
        app, headers={"Origin": "http://127.0.0.1:5173", "X-Requested-With": "tavus-interview"}
    ) as client:
        client.cookies.set(COOKIE, capability, path="/api")
        yield SimpleNamespace(
            client=client,
            repository=repository,
            connection=connection,
            session=session,
            service=service,
            settings=settings,
            card=card,
            app=app,
        )
    tavus.close()
    connection.rollback()
    connection.close()


def invoke(r, action, args=None, call_id=None):
    body = {
        "name": f"{action}_v{r.card.version}",
        "arguments": json.dumps(args or {}),
        "conversation_id": r.session.tavus_conversation_id,
        "tool_call_id": call_id or str(uuid4()),
    }
    raw = json.dumps(body).encode()
    signature = hmac.new(r.settings.callback_secret.encode(), raw, hashlib.sha256).hexdigest()
    return r.client.post(
        "/internal/tavus/tools", content=raw, headers={"X-Tavus-Signature": signature}
    )


def open_easy(r):
    r.repository.ready(r.session.id)
    assert invoke(r, "start_technical_interview").status_code == 200


def test_owner_csrf_and_agent_capabilities_are_separate(runtime):
    r = runtime
    endpoint = f"/api/interviews/{r.session.id}"
    assert r.client.get(endpoint).status_code == 200
    assert r.client.get(f"/api/interviews/{uuid4()}").status_code == 403
    assert r.client.post(endpoint + "/phase", json={"phase": "coding_easy"}).status_code == 403
    assert (
        r.client.post(
            endpoint + "/ready", headers={"Origin": "https://attacker.example"}
        ).status_code
        == 403
    )
    r.client.cookies.clear()
    assert r.client.get(endpoint).status_code == 403
    assert r.client.post(endpoint + "/end").status_code == 403


def test_hints_and_future_tasks_never_cross_candidate_responses(runtime):
    r = runtime
    status = r.client.get(f"/api/interviews/{r.session.id}").json()
    assert status["easy"] is status["medium"] is status["system_design"] is None
    r.repository.ready(r.session.id)
    response = invoke(r, "start_technical_interview")
    assert "PRIVATE_FIXTURE_HINT" in response.text  # Private Tavus response only.
    for endpoint in (f"/api/interviews/{r.session.id}", f"/api/interviews/{r.session.id}/reminder"):
        response = (
            r.client.post(endpoint, json={})
            if endpoint.endswith("reminder")
            else r.client.get(endpoint)
        )
        assert response.status_code == 200
        assert "PRIVATE_FIXTURE_HINT" not in response.text
        assert "System instructions" not in response.text
    assert r.client.get(f"/api/interviews/{r.session.id}").json()["medium"] is None
    notice = r.client.post(f"/api/interviews/{r.session.id}/reminder", json={}).json()
    assert len(json.dumps(notice).encode()) < 4096


def test_signed_calls_are_bound_validated_and_idempotent(runtime):
    r = runtime
    r.repository.ready(r.session.id)
    assert r.client.post("/internal/tavus/tools", json={}).status_code == 401
    raw = json.dumps({"name": "fake"}).encode()
    sig = hmac.new(r.settings.callback_secret.encode(), raw, hashlib.sha256).hexdigest()
    assert (
        r.client.post(
            "/internal/tavus/tools", content=raw + b" ", headers={"X-Tavus-Signature": sig}
        ).status_code
        == 401
    )
    first = invoke(r, "start_technical_interview", call_id="once")
    assert first.status_code == 200
    assert invoke(r, "start_technical_interview", call_id="once").json() == first.json()
    assert invoke(r, "start_technical_interview", {"unexpected": 1}).status_code == 400
    assert invoke(r, "advance_to_medium_problem", call_id="once").status_code == 409
    assert invoke(r, "not_a_tool").status_code == 403
    assert invoke(r, "start_technical_interview_v6").status_code == 403
    assert (
        r.connection.execute(
            "SELECT count(*) AS n FROM tool_invocations WHERE interview_id=%s", (r.session.id,)
        ).fetchone()["n"]
        == 1
    )


def test_revisions_restore_after_new_service_and_reject_old_writes(runtime):
    r = runtime
    open_easy(r)
    endpoint = f"/api/workspace/{r.session.id}/draft"
    payload = {"phase": "coding_easy", "language": "python3", "code": "print(2)", "revision": 2}
    assert r.client.post(endpoint, json=payload).status_code == 200
    assert r.client.post(endpoint, json=payload).status_code == 200
    assert (
        r.client.post(endpoint, json={**payload, "code": "old", "revision": 1}).status_code == 409
    )
    r.app.state.interviews = InterviewService(
        r.repository, r.app.state.tavus, r.settings.recordings_dir
    )
    restored = r.client.get("/api/interviews/current").json()
    assert restored["workspace"]["drafts"]["coding_easy:python3"] == "print(2)"
    assert restored["workspace"]["revisions"]["code:coding_easy:python3"] == 2
    r.repository.set_runtime(r.session.id, connected_at=datetime.now(UTC) - timedelta(seconds=3301))
    assert r.client.post(endpoint, json={**payload, "revision": 3}).status_code == 409
    assert (
        r.repository.get_interview(r.session.id).final_code_submissions["coding_easy:python3"]
        == "print(2)"
    )


def test_readiness_and_deadlines_survive_without_browser(runtime):
    r = runtime
    assert r.service.status(r.session.id)["elapsed_seconds"] == 0
    r.repository.ready(r.session.id)
    original = r.repository.runtime(r.session.id)["connected_at"]
    r.repository.ready(r.session.id)
    assert r.repository.runtime(r.session.id)["connected_at"] == original
    r.repository.set_runtime(r.session.id, connected_at=datetime.now(UTC) - timedelta(seconds=1501))
    r.service.tick()
    assert r.repository.get_interview(r.session.id).current_phase == "system_design"
    assert invoke(r, "return_to_technical_stage", {"phase": "coding_easy"}).status_code == 200
    r.service.tick()
    assert r.repository.get_interview(r.session.id).current_phase == "coding_easy"
    r.repository.set_runtime(r.session.id, connected_at=datetime.now(UTC) - timedelta(seconds=3601))
    r.service.tick()
    assert r.repository.get_interview(r.session.id).ended_at is not None


def test_private_transcript_rebuild_and_paging(runtime):
    r = runtime
    open_easy(r)
    for index in range(30):
        r.app.state.telemetry.record_utterance(
            r.session.id,
            index,
            "user",
            f"reasoning-{index} " * 90,
            system_instructions="",
            rules="",
            workspace="",
            ceiling=5000,
        )
    result = private_context(r.repository, r.service, r.session.id)
    assert "reasoning-0" in result["context"] and "reasoning-29" in result["context"]
    cursor = 0
    transcript = ""
    while True:
        page = private_context(r.repository, r.service, r.session.id, cursor)
        transcript += page["transcript"]
        if page["next_cursor"] == cursor:
            break
        cursor = page["next_cursor"]
    assert "reasoning-15" in transcript


def test_recording_segments_deduplicate_and_finalize(runtime):
    r = runtime
    segment = uuid4()
    url = f"/api/interviews/{r.session.id}/recordings/{segment}"
    assert r.client.post(url, json={"mime_type": "video/webm"}).status_code == 200

    def chunk(sequence, payload):
        return r.client.put(
            url + f"/chunks/{sequence}",
            content=payload,
            headers={"X-Chunk-SHA256": hashlib.sha256(payload).hexdigest()},
        )

    assert chunk(0, b"first").status_code == 200
    assert chunk(0, b"first").status_code == 200
    assert chunk(0, b"conflict").status_code == 409
    assert chunk(2, b"gap").status_code == 409
    assert r.client.post(url + "/finalize", json={"count": 2}).status_code == 409
    assert chunk(1, b"second").status_code == 200
    assert r.client.post(url + "/finalize", json={"count": 2}).status_code == 200
    assert r.client.post(url + "/finalize", json={"count": 2}).status_code == 200
    row = r.connection.execute(
        "SELECT * FROM recording_segments WHERE id=%s", (segment,)
    ).fetchone()
    from pathlib import Path

    assert Path(row["path"]).read_bytes() == b"firstsecond"
    assert row["status"] == "complete"


def test_logging_failure_rolls_back_action_and_retry_recovers(runtime):
    r = runtime
    r.repository.ready(r.session.id)
    r.connection.execute(
        "CREATE FUNCTION pg_temp.reject_tool_log() RETURNS trigger LANGUAGE plpgsql AS $$ "
        "BEGIN RAISE EXCEPTION 'synthetic log failure'; END $$"
    )
    r.connection.execute(
        "CREATE TRIGGER fixture_reject_log BEFORE INSERT ON tool_call_logs "
        "FOR EACH ROW EXECUTE FUNCTION pg_temp.reject_tool_log()"
    )
    with pytest.raises(psycopg.Error, match="synthetic log failure"):
        invoke(r, "start_technical_interview", call_id="retry-after-log-failure")
    assert r.repository.get_interview(r.session.id).current_phase == "intro"
    r.connection.execute("DROP TRIGGER fixture_reject_log ON tool_call_logs")
    assert (
        invoke(r, "start_technical_interview", call_id="retry-after-log-failure").status_code == 200
    )
    assert r.repository.get_interview(r.session.id).current_phase == "coding_easy"


def test_board_restoration_and_durable_remote_cleanup(runtime):
    r = runtime
    open_easy(r)
    assert invoke(r, "advance_to_medium_problem").status_code == 200
    assert invoke(r, "start_system_design", {"question_number": 1}).status_code == 200
    first = r.repository.get_interview(r.session.id).system_design_id
    endpoint = f"/api/workspace/{r.session.id}/diagram"
    assert (
        r.client.post(
            endpoint,
            json={"xml": "<mxGraphModel>first</mxGraphModel>", "question_id": first, "revision": 1},
        ).status_code
        == 200
    )
    second = next(item.id for item in r.repository.list_designs() if item.id != first)
    r.service.select_design(r.session.id, second)
    assert r.repository.get_interview(r.session.id).final_drawio_xml == ""
    r.service.select_design(r.session.id, first)
    assert "first" in r.repository.get_interview(r.session.id).final_drawio_xml
    bad = TavusClient(
        "fixture",
        "https://example.test",
        transport=httpx.MockTransport(lambda request: httpx.Response(500)),
    )
    r.service._tavus = bad
    r.service.transition(r.session.id, "candidate_left")
    assert r.repository.get_interview(r.session.id).ended_at
    assert r.repository.runtime(r.session.id)["remote_end_pending"]
    # A fresh service retries persisted intent, without any candidate browser polling.
    fresh = InterviewService(r.repository, r.app.state.tavus, r.settings.recordings_dir)
    # The rollback fixture borrows a transaction; exercise cleanup outside its lock wrapper.
    r.repository.borrowed = False
    fresh.tick()
    assert not r.repository.runtime(r.session.id)["remote_end_pending"]
    bad.close()


@pytest.mark.parametrize(
    "path,method,body",
    [
        (
            "/api/workspace/{id}/draft",
            "post",
            {"phase": "coding_easy", "language": "python3", "code": "x", "revision": 1},
        ),
        ("/api/workspace/{id}/diagram", "post", {"question_id": 1, "xml": "x", "revision": 1}),
        ("/api/workspace/{id}/terminal", "post", {"command": "ls"}),
        ("/api/telemetry/{id}/utterance", "post", {"turn_idx": 1, "role": "user", "text": "x"}),
        ("/api/telemetry/{id}/turns", "get", None),
        ("/api/interviews/{id}/recordings", "get", None),
    ],
)
def test_foreign_interview_routes_reject_the_ownership_cookie(runtime, path, method, body):
    endpoint = path.format(id=uuid4())
    response = getattr(runtime.client, method)(endpoint, **({"json": body} if body else {}))
    assert response.status_code == 403


def test_setup_timeout_and_interrupted_recording_survive_restart(runtime):
    r = runtime
    r.connection.execute(
        "UPDATE interview_runtime SET created_at=now()-interval '301 seconds' "
        "WHERE interview_id=%s",
        (r.session.id,),
    )
    fresh = InterviewService(r.repository, r.app.state.tavus, r.settings.recordings_dir)
    fresh.tick()
    assert r.repository.get_interview(r.session.id).ended_at
    segment = uuid4()
    r.app.state.recordings.create(r.session.id, segment, "video/webm")
    r.connection.execute(
        "UPDATE recording_segments SET status='incomplete' WHERE id=%s", (segment,)
    )
    response = r.client.get(f"/api/interviews/{r.session.id}/recordings")
    assert response.json()["segments"][0]["status"] == "incomplete"
    assert not r.repository.get_interview(r.session.id).video_recording_path


def test_expired_setup_cannot_be_revived_by_a_late_room_response(runtime):
    r = runtime
    r.service.transition(r.session.id, "candidate_left")
    from tavus_cvi.domain.errors import InvalidPhaseTransitionError

    with pytest.raises(InvalidPhaseTransitionError, match="deadline expired"):
        r.repository.attach_room(r.session.id, "late-room", "https://fixture.daily.co/late")
    assert r.repository.get_interview(r.session.id).ended_at
    assert r.repository.runtime(r.session.id)["remote_end_pending"]


def test_output_is_bound_to_accepted_revision_and_deadline(runtime):
    r = runtime
    open_easy(r)
    key = "code:coding_easy:python3"
    r.repository.workspace_write(r.session.id, key, "print(1)", 1)
    assert r.repository.save_output(r.session.id, key, 1, "first")
    r.repository.workspace_write(r.session.id, key, "print(2)", 2)
    assert not r.repository.save_output(r.session.id, key, 1, "stale")
    r.repository.set_runtime(r.session.id, connected_at=datetime.now(UTC) - timedelta(seconds=3301))
    assert not r.repository.save_output(r.session.id, key, 2, "late")
    assert r.repository.runtime(r.session.id)["terminal"] == "first"


def test_rejoined_browser_turn_counter_does_not_reorder_persisted_history(runtime):
    r = runtime
    for index, text in ((9, "before-refresh"), (1, "after-refresh")):
        r.app.state.telemetry.record_utterance(
            r.session.id,
            index,
            "user",
            text,
            system_instructions="",
            rules="",
            workspace="",
            ceiling=5000,
        )
    assert [row["utterance_text"] for row in r.repository.list_turns(r.session.id)] == [
        "before-refresh",
        "after-refresh",
    ]


def test_queued_transcript_retries_are_idempotent_after_response_loss_and_end(runtime):
    r = runtime
    endpoint = f"/api/telemetry/{r.session.id}/utterance"
    body = {
        "event_id": str(uuid4()),
        "observed_at": datetime.now(UTC).isoformat(),
        "turn_idx": 1,
        "role": "user",
        "text": "saved once",
    }
    assert r.client.post(endpoint, json=body).status_code == 200
    r.service.transition(r.session.id, "candidate_left")
    assert r.client.post(endpoint, json=body).status_code == 200
    assert r.client.post(endpoint, json={**body, "text": "conflict"}).status_code == 409
    assert (
        len(
            [
                row
                for row in r.repository.list_turns(r.session.id)
                if row["utterance_text"] == "saved once"
            ]
        )
        == 1
    )
    later = {
        **body,
        "event_id": str(uuid4()),
        "observed_at": (datetime.now(UTC) + timedelta(seconds=2)).isoformat(),
    }
    assert r.client.post(endpoint, json=later).status_code == 409


def test_database_connection_outage_does_not_overwrite_work(runtime):
    r = runtime
    open_easy(r)
    key = "code:coding_easy:python3"
    r.repository.workspace_write(r.session.id, key, "before outage", 1)
    unavailable = RuntimeRepository("postgresql://127.0.0.1:1/unavailable?connect_timeout=1")
    with pytest.raises(psycopg.OperationalError):
        unavailable.workspace_write(r.session.id, key, "after outage", 2)
    assert (
        r.repository.get_interview(r.session.id).final_code_submissions["coding_easy:python3"]
        == "before outage"
    )
    r.repository.workspace_write(r.session.id, key, "after outage", 2)
    assert (
        r.repository.get_interview(r.session.id).final_code_submissions["coding_easy:python3"]
        == "after outage"
    )


def test_start_capability_is_available_before_room_creation(runtime):
    r = runtime
    existing_cookie = r.client.cookies.get(COOKIE)
    response = r.client.post("/api/interviews/prepare")
    assert response.status_code == 200
    assert r.client.cookies.get(COOKIE) == existing_cookie
    r.client.cookies.clear()
    response = r.client.post("/api/interviews/prepare")
    assert response.status_code == 200
    assert "HttpOnly" in response.headers["set-cookie"]
    capability = r.client.cookies.get(COOKIE)
    assert len(capability) >= 32
    assert r.repository.owned_interview(capability) is None
    assert r.client.get(f"/api/interviews/{r.session.id}").status_code == 403


def test_unreachable_callback_blocks_new_calls(runtime, monkeypatch):
    from tavus_cvi.api import routes_interviews
    from tavus_cvi.services.model_card_service import ModelCardService

    r = runtime
    card = r.repository.latest_interviewer_card()
    binding = ModelCardService(
        r.repository, None, r.settings.callback_base_url, r.settings.callback_secret
    ).binding_hash()
    r.connection.execute(
        "INSERT INTO model_card_delivery(version,binding_hash) VALUES (%s,%s) "
        "ON CONFLICT(version) DO UPDATE SET binding_hash=excluded.binding_hash",
        (card.version, binding),
    )
    monkeypatch.setattr(routes_interviews, "callback_reachable", lambda _url: False)
    response = r.client.post("/api/interviews", json={})
    assert response.status_code == 503
    assert "tunnel" in response.text


def test_agent_completion_is_recorded_then_finalized_when_remote_ends(runtime):
    r = runtime
    r.repository.ready(r.session.id)
    assert invoke(r, "mark_interview_complete").status_code == 200
    assert r.repository.runtime(r.session.id)["completion_requested"] is True
    assert r.repository.get_interview(r.session.id).ended_at is None
    ended = TavusClient(
        "fixture",
        "https://example.test",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"status": "ended"})
        ),
    )
    fresh = InterviewService(r.repository, ended, r.settings.recordings_dir)
    fresh.tick()
    result = r.repository.get_interview(r.session.id)
    assert result.current_phase == "completed"
    assert result.ended_at is not None
    ended.close()


def test_revisited_stage_retry_with_new_call_id_is_idempotent(runtime):
    r = runtime
    open_easy(r)
    assert invoke(r, "advance_to_medium_problem").status_code == 200
    assert invoke(r, "return_to_technical_stage", {"phase": "coding_easy"}).status_code == 200
    assert invoke(r, "return_to_technical_stage", {"phase": "coding_easy"}).status_code == 200
    assert r.repository.get_interview(r.session.id).current_phase == "coding_easy"
