"""Regression checks from the interview usability red team."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from tavus_cvi.adapters.leetcode_scraper import strip_html
from tavus_cvi.domain.errors import InvalidPhaseTransitionError
from tavus_cvi.domain.rules import phase_deadline, timed_phase
from tavus_cvi.services.context_compression_service import ContextCompressionService
from tavus_cvi.services.interview_service import InterviewService
from tavus_cvi.services.model_card_service import load_card_file
from tavus_cvi.services.token_counter import count_tokens
from tests.support import InMemoryStore, open_session
from tests.test_api import _client


@pytest.mark.parametrize(
    ("elapsed", "phase"),
    [
        (299, "intro"),
        (300, "coding_easy"),
        (899, "coding_easy"),
        (900, "coding_medium"),
        (1499, "coding_medium"),
        (1500, "system_design"),
        (3300, "system_design"),
        (3600, "completed"),
    ],
)
def test_clock_boundaries(elapsed: int, phase: str) -> None:
    assert timed_phase("intro", elapsed) == phase


def test_early_transitions_do_not_go_backwards() -> None:
    assert timed_phase("coding_medium", 500) == "coding_medium"
    assert timed_phase("candidate_left", 4000) == "candidate_left"
    assert phase_deadline("system_design", 3299) == 3300
    assert phase_deadline("system_design", 3300) == 3600


def test_clock_catches_up_without_exposing_hints(tmp_path: Path) -> None:
    store = InMemoryStore()
    session = open_session(store)
    session.started_at = datetime.now(UTC) - timedelta(seconds=1501)
    service = InterviewService(store, None, tmp_path)
    status = service.status(session.id)
    assert status["interview"]["current_phase"] == "system_design"
    assert "hints" not in status["easy"]
    assert "evaluation_rubric" not in status["system_design"]


def test_terminal_interview_rejects_edits_and_stops_clock(tmp_path: Path) -> None:
    store = InMemoryStore()
    session = open_session(store)
    service = InterviewService(store, None, tmp_path)
    service.transition(session.id, "candidate_left")
    before = service.status(session.id)
    session.started_at -= timedelta(seconds=100)
    assert before["frozen"] is True
    with pytest.raises(InvalidPhaseTransitionError):
        service.select_design(session.id, 2)


def test_transition_is_idempotent_and_technical_tools_lock_at_55(tmp_path: Path) -> None:
    store = InMemoryStore()
    session = open_session(store)
    service = InterviewService(store, None, tmp_path)
    service.transition(session.id, "coding_easy")
    service.transition(session.id, "coding_easy")
    session.started_at = datetime.now(UTC) - timedelta(seconds=3301)
    with pytest.raises(InvalidPhaseTransitionError):
        service.transition(session.id, "coding_medium")


def test_workspace_refresh_keeps_spoken_approach_and_complete_short_code() -> None:
    compression = ContextCompressionService()
    interview = uuid4()
    args = dict(system_instructions="Assess fairly", rules="Wait", ceiling=5000)
    compression.ingest_turn(interview, "user: I will use two pointers", workspace="", **args)
    for _ in range(3):
        workspace = compression.workspace_delta(interview, "first = 1\nlast = 2", "", "")
        context = compression.build_context(interview, workspace=workspace, **args)
        assert "two pointers" in context
        assert "first = 1" in context
        assert "last = 2" in context
        assert count_tokens(context) <= 5000


def test_drafts_are_separate_and_never_executed() -> None:
    client, interviews, repository = _client()
    from types import SimpleNamespace

    repository.session = SimpleNamespace(final_code_submissions={})
    interview = uuid4()
    endpoint = f"/api/workspace/{interview}/draft"
    first = client.post(
        endpoint, json={"phase": "coding_easy", "language": "python3", "code": "x", "revision": 1}
    )
    second = client.post(
        endpoint, json={"phase": "coding_medium", "language": "python3", "code": "y", "revision": 1}
    )
    assert first.status_code == second.status_code == 200
    assert repository.session.final_code_submissions == {
        "coding_easy:python3": "x",
        "coding_medium:python3": "y",
    }
    interviews.elapsed = 3300
    assert (
        client.post(
            endpoint,
            json={"phase": "coding_easy", "language": "python3", "code": "z", "revision": 2},
        ).status_code
        == 409
    )


def test_scraper_preserves_paragraphs_and_preformatted_examples() -> None:
    statement = strip_html(
        "<p>A <code>sorted</code> array.</p><pre>Input: [1,1]\nOutput: 1</pre>"
        "<p>Constraints:</p><ul><li>n &gt; 0</li></ul>"
    )
    assert "A sorted array.\n\nInput:" in statement
    assert "\nOutput: 1" in statement
    assert "• n > 0" in statement


def test_agent_assessment_policy_and_flow_are_versioned() -> None:
    card = load_card_file(Path("config/agents/charlie_interviewer.yaml"))
    assert card.version == 9
    assert card.conversational_flow == {
        "turn_taking_patience": "high",
        "pal_interruptibility": "high",
        "idle_engagement": "off",
    }
    assert "explicitly asks for help" in card.system_instructions
    assert "Review code snapshots silently" in card.system_instructions
    assert "Do not edit their code or diagram" in card.system_instructions
    assert "update_shared_workspace" not in {tool["name"] for tool in card.tools_config}
    assert count_tokens(card.system_instructions) < 1500


def test_special_token_text_is_counted_as_candidate_data() -> None:
    assert count_tokens("# <|endoftext|> is just a code comment") > 0


def test_private_hint_context_is_not_exposed_to_candidate(tmp_path: Path) -> None:
    from tavus_cvi.services.interview_context import active_problem_context

    store = InMemoryStore()
    session = open_session(store)
    service = InterviewService(store, None, tmp_path)
    service.transition(session.id, "coding_easy")
    status = service.status(session.id)
    context = active_problem_context(status, store)
    assert "Private hint reference" in context
    assert "Think." in context
    assert "hints" not in status["easy"]
    assert "Private hint reference" not in str(status)


def test_workspace_route_refresh_does_not_erase_candidate_reasoning() -> None:
    client, _, _ = _client()
    interview = uuid4()
    utterance = client.post(
        f"/api/telemetry/{interview}/utterance",
        json={
            "turn_idx": 1,
            "role": "user",
            "text": "I will use two pointers.",
            "code": "first = 0",
            "terminal": "",
            "diagram_xml": "",
        },
    )
    refresh = client.post(f"/api/interviews/{interview}/reminder", json={"code": "first = 1"})
    assert utterance.status_code == refresh.status_code == 200
    assert "two pointers" not in refresh.json()["properties"]["context"]
    assert "first = 1" not in refresh.json()["properties"]["context"]


def test_revisit_survives_poll_and_preserves_clock_and_drafts(tmp_path: Path) -> None:
    store = InMemoryStore()
    session = open_session(store)
    session.started_at = datetime.now(UTC) - timedelta(seconds=1600)
    session.final_code_submissions = {"coding_easy:python3": "my solution"}
    service = InterviewService(store, None, tmp_path)
    assert service.status(session.id)["interview"]["current_phase"] == "system_design"
    started = session.started_at
    service.revisit(session.id, "coding_easy")
    status = service.status(session.id)
    assert status["interview"]["current_phase"] == "coding_easy"
    assert status["phase_deadline_seconds"] == 3300
    assert session.started_at == started
    assert session.final_code_submissions["coding_easy:python3"] == "my solution"
    service.transition(session.id, "coding_medium")
    assert service.status(session.id)["interview"]["current_phase"] == "coding_medium"


def test_revisit_rejects_forward_or_frozen_requests(tmp_path: Path) -> None:
    store = InMemoryStore()
    session = open_session(store)
    service = InterviewService(store, None, tmp_path)
    with pytest.raises(InvalidPhaseTransitionError):
        service.revisit(session.id, "coding_easy")
    session.current_phase = "coding_medium"
    with pytest.raises(InvalidPhaseTransitionError):
        service.revisit(session.id, "system_design")
    session.started_at = datetime.now(UTC) - timedelta(seconds=3301)
    with pytest.raises(InvalidPhaseTransitionError):
        service.revisit(session.id, "coding_easy")
