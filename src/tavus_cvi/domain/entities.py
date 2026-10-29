"""Pure interview entities."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class AgentModelCard:
    """One immutable version of an agent configuration."""

    version: int
    agent_name: str
    yaml_path: str
    yaml_sha256: str
    model: str
    pipeline_mode: str
    face_id: str
    voice_id: str
    perception_model: str
    turn_detection_model: str
    system_instructions: str
    context_template: str
    hardcoded_reminder_template: str
    guardrails_config: list[dict[str, Any]]
    tools_config: list[dict[str, Any]]
    objectives: list[dict[str, Any]]
    max_concurrent_tool_calls: int
    max_context_tokens: int
    temperature: float | None
    top_p: float | None
    conversational_flow: dict[str, Any] = field(default_factory=dict)
    tavus_pal_id: str | None = None


@dataclass(frozen=True)
class LeetCodeProblem:
    """A scraped coding problem stored in leetcode_tests."""

    challenge_number: int
    title_slug: str
    question_title: str
    question: str
    difficulty_level: str
    hints: list[str]
    boilerplate_code: dict[str, str]
    id: int | None = None


@dataclass(frozen=True)
class SystemDesignQuestion:
    """A manually selected architecture prompt."""

    question_number: int
    question_title: str
    problem_statement: str
    functional_requirements: list[str]
    non_functional_requirements: list[str]
    evaluation_rubric: list[str]
    initial_drawio_xml: str | None = None
    id: int | None = None


@dataclass(frozen=True)
class Candidate:
    """A person sitting the interview."""

    id: UUID
    full_name: str
    email: str
    target_role: str
    cv_path: str | None = None


@dataclass
class InterviewSession:
    """One live or finished interview."""

    id: UUID
    candidate_id: UUID
    agent_model_card_version: int
    current_phase: str
    started_at: datetime
    easy_leetcode_id: int | None = None
    medium_leetcode_id: int | None = None
    system_design_id: int | None = None
    tavus_conversation_id: str | None = None
    tavus_conversation_url: str | None = None
    transcript: list[dict[str, Any]] = field(default_factory=list)
    video_recording_path: str | None = None
    final_code_submissions: dict[str, str] = field(default_factory=dict)
    final_drawio_xml: str | None = None
    ended_at: datetime | None = None
    revisiting: bool = False


@dataclass(frozen=True)
class TurnTelemetry:
    """Token and tool record for one conversational turn."""

    interview_id: UUID
    turn_idx: int
    role: str
    utterance_text: str
    input_tokens: int
    output_tokens: int
    thinking_tokens: int | None
    event_timestamp: datetime
    inference_id: str | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    active_concurrent_tools: int = 0


@dataclass(frozen=True)
class ToolCallRecord:
    """One accepted or rejected tool invocation."""

    interview_id: UUID
    tool_name: str
    tool_origin: str
    arguments: dict[str, Any]
    status: str
    concurrency_at_call: int
    called_at: datetime
    turn_idx: int | None = None


@dataclass(frozen=True)
class ExecutionResult:
    """Output of a sandboxed code or terminal run."""

    stdout: str
    stderr: str
    exit_code: int
    duration_ms: int
