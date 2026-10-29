"""HTTP routes with in-memory collaborators."""

from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tavus_cvi.api.routes_interviews import router as interviews_router
from tavus_cvi.api.routes_telemetry import router as telemetry_router
from tavus_cvi.api.routes_workspace import router as workspace_router
from tavus_cvi.api.security import require_owner
from tavus_cvi.domain.entities import AgentModelCard, ExecutionResult
from tavus_cvi.domain.errors import InvalidPhaseTransitionError
from tavus_cvi.services.context_compression_service import ContextCompressionService
from tavus_cvi.services.telemetry_service import TelemetryService
from tests.test_concurrency_and_execution import MemoryRepository


class FakeInterviews:
    """Interview status the routes need."""

    def __init__(self) -> None:
        self.phases: list[str] = []
        self.elapsed = 12
        self.recordings: list[bytes] = []
        self.started_with: int | None = None
        self.designs: list[int] = []

    def status(self, interview_id: object) -> dict[str, object]:
        return {
            "interview": {
                "id": str(interview_id),
                "ended_at": None,
                "current_phase": "coding_easy",
                "conversation_url": "https://tavus.daily.co/room",
            },
            "ready": True,
            "elapsed_seconds": self.elapsed,
            "frozen": self.elapsed >= 3300,
            "easy": {"question_title": "Two Sum", "question": "Add indices."},
            "medium": {"question_title": "Add Two Numbers"},
            "system_design": {"question_title": "URL shortener"},
        }

    def transition(self, interview_id: object, phase: str) -> None:
        self.phases.append(phase)

    def start(self, system_design_id: int | None, owner_hash: str | None = None) -> SimpleNamespace:
        self.started_with = system_design_id
        return SimpleNamespace(id=uuid4())

    def select_design(self, interview_id: object, design_id: int) -> None:
        self.designs.append(design_id)

    def save_recording(self, interview_id: object, payload: bytes) -> str:
        self.recordings.append(payload)
        return "/tmp/interview.webm"


class FakeExecution:
    def run_code(self, interview_id: str, language: str, source: str) -> ExecutionResult:
        return ExecutionResult("ran", "", 0, 3)

    def run_terminal(self, interview_id: str, command: str) -> ExecutionResult:
        return ExecutionResult(command, "", 0, 1)


class FakeRepository(MemoryRepository):
    def __init__(self) -> None:
        super().__init__()
        self.saved: list[object] = []
        self.session = SimpleNamespace(
            ended_at=None,
            agent_model_card_version=1,
            current_phase="coding_easy",
            final_code_submissions={},
            final_drawio_xml="",
        )

    def latest_interviewer_card(self) -> AgentModelCard:
        return AgentModelCard(
            version=1,
            agent_name="charlie_interviewer",
            yaml_path="config/agents/charlie_interviewer.yaml",
            yaml_sha256="abc",
            model="tavus-gpt-5.6-terra",
            pipeline_mode="full",
            face_id="rbb3ca3630f7",
            voice_id="charlie",
            perception_model="raven-2",
            turn_detection_model="sparrow-2",
            system_instructions="Stay professional and use end_call after one warning.",
            context_template="{phase}",
            hardcoded_reminder_template=(
                "Elapsed {elapsed_clock}. Phase {phase}. Frozen {frozen}. "
                "{active_problem} {workspace_delta}"
            ),
            guardrails_config=[],
            tools_config=[],
            objectives=[],
            max_concurrent_tool_calls=2,
            max_context_tokens=5000,
            temperature=0.4,
            top_p=0.9,
        )

    def get_interview(self, interview_id: object) -> object | None:
        return getattr(self, "session", None)

    def save_interview(self, session: object) -> None:
        self.session = session

    def save_code_draft(self, interview_id: object, key: str, code: str) -> None:
        self.session.final_code_submissions[key] = code

    def save_whiteboard(self, interview_id: object, xml: str) -> None:
        self.session.final_drawio_xml = xml

    def owned_interview(self, token: str):
        return None

    def card_for_version(self, version: int):
        return self.latest_interviewer_card()

    def set_runtime(self, interview_id, **changes):
        return None

    def workspace_write(self, interview_id, key, value, revision):
        if not self.session or self.interviews.elapsed >= 3300:
            raise InvalidPhaseTransitionError("Technical assessment is locked at 55:00")
        if key.startswith("code:"):
            self.save_code_draft(interview_id, key[5:], value)
        else:
            self.save_whiteboard(interview_id, value)
        return revision

    def ensure_cv_column(self) -> None:
        return None

    def insert_candidate(self, candidate: object) -> None:
        self.candidate = candidate

    def candidate_by_email(self, email: str) -> object | None:
        candidate = getattr(self, "candidate", None)
        if candidate is not None and candidate.email == email:
            return candidate
        return None

    def list_designs(self) -> list[object]:
        return []

    def list_turns(self, interview_id: object) -> list[dict[str, object]]:
        return []


def _client() -> tuple[TestClient, FakeInterviews, FakeRepository]:
    app = FastAPI()
    app.include_router(interviews_router, prefix="/api")
    app.include_router(workspace_router, prefix="/api")
    app.include_router(telemetry_router, prefix="/api")
    interviews = FakeInterviews()
    repository = FakeRepository()
    repository.interviews = interviews
    app.dependency_overrides[require_owner] = lambda: (
        None
    )  # Unit tests; real auth covered separately.
    app.state.settings = SimpleNamespace(
        callback_base_url="https://test.example", callback_secret="secret", cookie_secure=False
    )
    app.state.interviews = interviews
    app.state.repository = repository
    app.state.compression = ContextCompressionService()
    app.state.telemetry = TelemetryService(repository, app.state.compression)
    app.state.execution = FakeExecution()
    return TestClient(app), interviews, repository


def test_reminder_returns_an_overwrite_event() -> None:
    client, _, _ = _client()
    interview_id = uuid4()
    response = client.post(f"/api/interviews/{interview_id}/reminder", json={"code": "print(1)"})
    assert response.status_code == 200
    body = response.json()
    assert body["event_type"] == "conversation.overwrite_llm_context"
    assert "Two Sum" not in body["properties"]["context"]
    assert "print(1)" not in body["properties"]["context"]


def test_run_code_returns_stdout() -> None:
    client, _, _ = _client()
    response = client.post(
        f"/api/workspace/{uuid4()}/run",
        json={"language": "python3", "code": "print(1)", "phase": "coding_easy", "revision": 1},
    )
    assert response.status_code == 200
    assert response.json()["stdout"] == "ran"


def test_tool_route_enforces_the_concurrency_cap() -> None:
    client, _, repository = _client()
    interview_id = uuid4()
    first = client.post(
        f"/api/telemetry/{interview_id}/tool",
        json={"tool_name": "start_technical_interview"},
    )
    second = client.post(
        f"/api/telemetry/{interview_id}/tool",
        json={"tool_name": "advance_to_medium_problem"},
    )
    third = client.post(
        f"/api/telemetry/{interview_id}/tool",
        json={"tool_name": "start_system_design"},
    )
    assert first.status_code == second.status_code == third.status_code == 403
    assert repository.tools == []


def test_candidate_route_returns_the_seeded_profile() -> None:
    client, _, _ = _client()
    response = client.get("/api/candidate")
    assert response.status_code == 200
    body = response.json()
    assert body["full_name"] == "Sam Linfield"
    assert body["first_name"] == "Sam"
    assert body["target_role"] == "Senior AI Engineer"
    assert "cv_path" not in body


def test_start_phase_end_and_recording_routes() -> None:
    client, interviews, _ = _client()
    started = client.post("/api/interviews", json={})
    assert started.status_code == 200
    assert interviews.started_with is None
    interview_id = uuid4()
    phase = client.post(f"/api/interviews/{interview_id}/phase", json={"phase": "coding_easy"})
    ended = client.post(f"/api/interviews/{interview_id}/end")
    recorded = client.post(
        f"/api/interviews/{interview_id}/recording",
        files={"chunk": ("chunk.webm", b"abc", "video/webm")},
    )
    assert phase.status_code == 403
    assert interviews.phases == ["candidate_left"]
    assert ended.json()["status"] == "ended"
    assert recorded.status_code == 404
    assert interviews.recordings == []


def test_frozen_workspace_and_missing_diagram() -> None:
    client, interviews, repository = _client()
    interview_id = uuid4()
    repository.session = None
    missing = client.post(
        f"/api/workspace/{interview_id}/diagram",
        json={"xml": "<mxfile/>", "question_id": 1, "revision": 1},
    )
    interviews.elapsed = 3300
    locked = client.post(
        f"/api/workspace/{interview_id}/run",
        json={"language": "python3", "code": "print(1)", "phase": "coding_easy", "revision": 1},
    )
    repository.session = SimpleNamespace(final_drawio_xml="", final_code_submissions={})
    interviews.elapsed = 12
    saved = client.post(
        f"/api/workspace/{interview_id}/diagram",
        json={"xml": '<mxCell value="Client"/>', "question_id": 1, "revision": 1},
    )
    assert missing.status_code == 409
    assert locked.status_code == 409
    assert saved.status_code == 200
    assert "Client" in saved.json()["summary"]


def test_terminal_utterance_and_tool_release() -> None:
    client, _, repository = _client()
    interview_id = uuid4()
    terminal = client.post(
        f"/api/workspace/{interview_id}/terminal",
        json={"command": "ls"},
    )
    utterance = client.post(
        f"/api/telemetry/{interview_id}/utterance",
        json={"turn_idx": 0, "role": "user", "text": "I will use a map."},
    )
    client.post(
        f"/api/telemetry/{interview_id}/tool",
        json={"tool_name": "start_technical_interview"},
    )
    client.post(
        f"/api/telemetry/{interview_id}/tool",
        json={"tool_name": "advance_to_medium_problem"},
    )
    released = client.post(f"/api/telemetry/{interview_id}/tool/complete")
    third = client.post(
        f"/api/telemetry/{interview_id}/tool",
        json={"tool_name": "start_system_design"},
    )
    turns = client.get(f"/api/telemetry/{interview_id}/turns")
    invalid = client.post(f"/api/telemetry/{interview_id}/tool", json={})
    assert terminal.status_code == 200
    assert utterance.json()["event_type"] == "conversation.overwrite_llm_context"
    assert released.status_code == third.status_code == 403
    assert turns.json()["turns"] == []
    assert invalid.status_code == 403
    assert repository.turns


def test_design_selection_and_append_reminder() -> None:
    client, interviews, _ = _client()
    interview_id = uuid4()
    selected = client.post(
        f"/api/interviews/{interview_id}/design",
        json={"system_design_id": 2},
    )
    reminder = client.post(
        f"/api/interviews/{interview_id}/reminder",
        json={"mode": "append", "code": "x = 1"},
    )
    designs = client.get("/api/problems/system-design")
    assert selected.status_code == 403
    assert interviews.designs == []
    assert reminder.json()["event_type"] == "conversation.overwrite_llm_context"
    assert designs.status_code == 403
