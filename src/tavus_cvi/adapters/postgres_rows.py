"""Map PostgreSQL rows to domain entities."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from tavus_cvi.domain.entities import (
    AgentModelCard,
    InterviewSession,
    LeetCodeProblem,
    SystemDesignQuestion,
)


def model_card_row(row: dict[str, Any]) -> AgentModelCard:
    """Build a model card from an agent_model_cards row."""
    tools_blob = row["tools_config"] or {}
    if isinstance(tools_blob, str):
        tools_blob = json.loads(tools_blob)
    tools = tools_blob.get("tools", tools_blob if isinstance(tools_blob, list) else [])
    objectives = tools_blob.get("objectives", [])
    return AgentModelCard(
        version=row["version"],
        agent_name=row["agent_name"],
        yaml_path=row["yaml_path"],
        yaml_sha256=row["yaml_sha256"],
        model=row["model"],
        pipeline_mode=row["pipeline_mode"],
        face_id=row["face_id"],
        voice_id=row["voice_id"],
        perception_model=row["perception_model"],
        turn_detection_model=row["turn_detection_model"],
        system_instructions=row["system_instructions"],
        context_template=row["context_template"],
        hardcoded_reminder_template=row["hardcoded_reminder_template"],
        guardrails_config=list(row["guardrails_config"]),
        tools_config=list(tools),
        objectives=list(objectives),
        conversational_flow=dict(tools_blob.get("conversational_flow", {})),
        max_concurrent_tool_calls=row["max_concurrent_tool_calls"],
        max_context_tokens=row["max_context_tokens"],
        temperature=float(row["temperature"]) if row["temperature"] is not None else None,
        top_p=float(row["top_p"]) if row["top_p"] is not None else None,
        tavus_pal_id=row["tavus_pal_id"],
    )


def problem_row(row: dict[str, Any]) -> LeetCodeProblem:
    """Build a coding problem from a leetcode_tests row."""
    return LeetCodeProblem(
        id=row["id"],
        challenge_number=row["challenge_number"],
        title_slug=row["title_slug"],
        question_title=row["question_title"],
        question=row["question"],
        difficulty_level=row["difficulty_level"],
        hints=list(row["hints"]),
        boilerplate_code=dict(row["boilerplate_code"]),
    )


def design_row(row: dict[str, Any]) -> SystemDesignQuestion:
    """Build a system design question from its row."""
    return SystemDesignQuestion(
        id=row["id"],
        question_number=row["question_number"],
        question_title=row["question_title"],
        problem_statement=row["problem_statement"],
        functional_requirements=list(row["functional_requirements"]),
        non_functional_requirements=list(row["non_functional_requirements"]),
        evaluation_rubric=list(row["evaluation_rubric"]),
        initial_drawio_xml=row["initial_drawio_xml"],
    )


def interview_row(row: dict[str, Any]) -> InterviewSession:
    """Build an interview session from its row."""
    return InterviewSession(
        id=UUID(str(row["id"])),
        candidate_id=UUID(str(row["candidate_id"])),
        agent_model_card_version=row["agent_model_card_version"],
        current_phase=row["current_phase"],
        started_at=row["started_at"],
        easy_leetcode_id=row["easy_leetcode_id"],
        medium_leetcode_id=row["medium_leetcode_id"],
        system_design_id=row["system_design_id"],
        tavus_conversation_id=row["tavus_conversation_id"],
        tavus_conversation_url=row["tavus_conversation_url"],
        transcript=list(row["transcript"] or []),
        video_recording_path=row["video_recording_path"],
        final_code_submissions=dict(row["final_code_submissions"] or {}),
        final_drawio_xml=row["final_drawio_xml"],
        ended_at=row["ended_at"],
        revisiting=row.get("revisiting", False),
    )


def interview_values(session: InterviewSession) -> tuple[Any, ...]:
    """Return the insert column values for an interview."""
    return (
        session.id,
        session.candidate_id,
        session.agent_model_card_version,
        session.tavus_conversation_id,
        session.tavus_conversation_url,
        session.easy_leetcode_id,
        session.medium_leetcode_id,
        session.system_design_id,
        session.current_phase,
        Jsonb(session.transcript),
        session.video_recording_path,
        Jsonb(session.final_code_submissions),
        session.final_drawio_xml,
        session.started_at,
        session.ended_at,
    )
