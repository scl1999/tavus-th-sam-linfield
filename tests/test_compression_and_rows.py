"""Context compression, token counts, and PostgreSQL row mapping."""

from datetime import UTC, datetime
from uuid import uuid4

from tavus_cvi.adapters.postgres_rows import (
    design_row,
    interview_row,
    interview_values,
    model_card_row,
    problem_row,
)
from tavus_cvi.services.context_compression_service import ContextCompressionService
from tavus_cvi.services.token_counter import count_tokens


def test_empty_text_has_zero_tokens() -> None:
    assert count_tokens("") == 0
    assert count_tokens("hello") > 0


def test_workspace_delta_summarizes_code_and_diagram() -> None:
    service = ContextCompressionService()
    interview_id = uuid4()
    xml = (
        "<diagram>"
        '<mxCell id="1" value="Client"/>'
        '<mxCell id="2" value="API"/>'
        '<mxCell id="3" source="1" target="2"/>'
        "</diagram>"
    )
    summary = service.workspace_delta(interview_id, "print(1)", "ok", xml)
    assert "print(1)" in summary
    assert "[Client] -> [API]" in summary
    changed = service.workspace_delta(interview_id, "print(2)", "ok", "")
    assert "print(2)" in changed
    assert "No diagram yet." in changed


def test_ingest_folds_old_turns_through_the_summarizer() -> None:
    folded: list[str] = []

    def summarize(text: str) -> str:
        folded.append(text)
        return "digest"

    service = ContextCompressionService(summarizer=summarize)
    interview_id = uuid4()
    payload = ""
    for index in range(30):
        payload = service.ingest_turn(
            interview_id,
            "word " * 80 + str(index),
            system_instructions="system",
            rules="rules",
            workspace="code",
            ceiling=5000,
        )
    assert folded
    assert count_tokens(payload) <= 5000
    assert "digest" in payload


def test_model_card_row_reads_tools_stored_as_json_text() -> None:
    card = model_card_row(
        {
            "version": 1,
            "agent_name": "charlie_interviewer",
            "yaml_path": "card.yaml",
            "yaml_sha256": "abc",
            "model": "tavus-gpt-5.6-terra",
            "pipeline_mode": "full",
            "face_id": "rbb3ca3630f7",
            "voice_id": "charlie",
            "perception_model": "raven-2",
            "turn_detection_model": "sparrow-2",
            "system_instructions": "Be brief.",
            "context_template": "{phase}",
            "hardcoded_reminder_template": "{phase}",
            "guardrails_config": [],
            "tools_config": (
                '{"tools": [{"name": "start_technical_interview"}], '
                '"objectives": [{"name": "intro"}]}'
            ),
            "max_concurrent_tool_calls": 2,
            "max_context_tokens": 5000,
            "temperature": None,
            "top_p": "0.9",
            "tavus_pal_id": None,
        }
    )
    assert card.tools_config[0]["name"] == "start_technical_interview"
    assert card.objectives[0]["name"] == "intro"
    assert card.temperature is None
    assert card.top_p == 0.9


def test_problem_and_interview_rows_round_trip_ids() -> None:
    problem = problem_row(
        {
            "id": 4,
            "challenge_number": 1,
            "title_slug": "two-sum",
            "question_title": "Two Sum",
            "question": "Add",
            "difficulty_level": "Easy",
            "hints": ["Map"],
            "boilerplate_code": {"python3": "pass"},
        }
    )
    assert problem.id == 4
    design = design_row(
        {
            "id": 3,
            "question_number": 1,
            "question_title": "URL shortener",
            "problem_statement": "Shorten links.",
            "functional_requirements": ["Create"],
            "non_functional_requirements": ["Fast"],
            "evaluation_rubric": ["API"],
            "initial_drawio_xml": None,
        }
    )
    assert design.question_title == "URL shortener"
    interview_id = uuid4()
    candidate_id = uuid4()
    started = datetime.now(UTC)
    session = interview_row(
        {
            "id": str(interview_id),
            "candidate_id": str(candidate_id),
            "agent_model_card_version": 1,
            "current_phase": "intro",
            "started_at": started,
            "easy_leetcode_id": 1,
            "medium_leetcode_id": 2,
            "system_design_id": 1,
            "tavus_conversation_id": None,
            "tavus_conversation_url": None,
            "transcript": [],
            "video_recording_path": None,
            "final_code_submissions": {},
            "final_drawio_xml": None,
            "ended_at": None,
        }
    )
    values = interview_values(session)
    assert values[0] == interview_id
    assert values[1] == candidate_id
    assert session.current_phase == "intro"
