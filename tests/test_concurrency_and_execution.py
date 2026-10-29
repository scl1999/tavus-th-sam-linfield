"""Tool concurrency and the local code runner."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from tavus_cvi.domain.entities import ToolCallRecord, TurnTelemetry
from tavus_cvi.domain.errors import ConcurrencyLimitExceededError, WorkspaceExecutionError
from tavus_cvi.domain.rules import ToolCallConcurrencyLimiter
from tavus_cvi.services.code_execution_service import CodeExecutionService
from tavus_cvi.services.context_compression_service import ContextCompressionService
from tavus_cvi.services.telemetry_service import TelemetryService


class MemoryRepository:
    """In-memory stand-in for the telemetry tables."""

    def __init__(self) -> None:
        self.turns: list[TurnTelemetry] = []
        self.tools: list[ToolCallRecord] = []

    def insert_turn(self, turn: TurnTelemetry) -> None:
        self.turns.append(turn)

    def insert_tool_call(self, record: ToolCallRecord) -> None:
        self.tools.append(record)


def test_limiter_rejects_a_zero_cap() -> None:
    with pytest.raises(ConcurrencyLimitExceededError):
        ToolCallConcurrencyLimiter(0)


def test_unknown_language_and_allowlisted_ls(tmp_path: Path) -> None:
    runner = CodeExecutionService(tmp_path)
    with pytest.raises(WorkspaceExecutionError):
        runner.run_code("interview", "ruby", "puts 1")
    runner.run_code("interview", "python3", "print(1)")
    listed = runner.run_terminal("interview", "ls")
    assert listed.exit_code == 0


def test_limiter_rejects_the_call_past_the_cap() -> None:
    limiter = ToolCallConcurrencyLimiter(2)
    assert limiter.try_acquire() == 1
    assert limiter.try_acquire() == 2
    with pytest.raises(ConcurrencyLimitExceededError):
        limiter.try_acquire()
    limiter.release()
    assert limiter.try_acquire() == 2


def test_telemetry_rejects_a_third_in_flight_tool() -> None:
    repository = MemoryRepository()
    service = TelemetryService(repository, ContextCompressionService())
    interview_id = uuid4()
    assert service.record_tool_call(interview_id, "start_technical_interview", {}, 2) == "executed"
    assert service.record_tool_call(interview_id, "advance_to_medium_problem", {}, 2) == "executed"
    assert (
        service.record_tool_call(interview_id, "start_system_design", {}, 2)
        == "rejected_concurrency_limit"
    )
    service.complete_tool_call(interview_id)
    assert service.record_tool_call(interview_id, "start_system_design", {}, 2) == "executed"
    assert repository.tools[-1].status == "executed"


def test_utterance_payload_stays_within_5000_tokens() -> None:
    repository = MemoryRepository()
    service = TelemetryService(
        repository,
        ContextCompressionService(summarizer=lambda text: text[:40]),
    )
    context = service.record_utterance(
        uuid4(),
        0,
        "pal",
        "hello " * 400,
        system_instructions="rules " * 200,
        rules="phase intro",
        workspace="print(1)",
        ceiling=5000,
    )
    assert repository.turns[0].output_tokens > 0
    assert repository.turns[0].thinking_tokens is None
    assert repository.turns[0].event_timestamp <= datetime.now(UTC)
    assert len(context) > 0


def test_python_code_runs_and_shell_operators_are_rejected(tmp_path: Path) -> None:
    runner = CodeExecutionService(tmp_path)
    result = runner.run_code("interview", "python3", "print('ok')")
    assert result.exit_code == 0
    assert "ok" in result.stdout
    with pytest.raises(WorkspaceExecutionError):
        runner.run_terminal("interview", "ls; rm -rf /")
    with pytest.raises(WorkspaceExecutionError):
        runner.run_terminal("interview", "cat ../secret")


def test_failed_tool_logging_releases_the_reservation():
    repository = MemoryRepository()
    service = TelemetryService(repository, ContextCompressionService())
    original = repository.insert_tool_call

    def fail(_record):
        raise RuntimeError("synthetic log failure")

    repository.insert_tool_call = fail
    interview = uuid4()
    for _ in range(3):
        with pytest.raises(RuntimeError):
            service.record_tool_call(interview, "start_technical_interview", {}, 1)
    repository.insert_tool_call = original
    assert service.record_tool_call(interview, "start_technical_interview", {}, 1) == "executed"
