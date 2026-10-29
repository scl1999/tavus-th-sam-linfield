"""Persist per-turn token counts and enforce tool concurrency."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from tavus_cvi.adapters.postgres_repos import PostgresRepository
from tavus_cvi.domain.entities import ToolCallRecord, TurnTelemetry
from tavus_cvi.domain.errors import ConcurrencyLimitExceededError
from tavus_cvi.domain.rules import ToolCallConcurrencyLimiter
from tavus_cvi.services.context_compression_service import ContextCompressionService
from tavus_cvi.services.token_counter import count_tokens


class TelemetryService:
    """Record utterances and tool calls for one process."""

    def __init__(
        self,
        repository: PostgresRepository,
        compression: ContextCompressionService,
    ) -> None:
        self._repository = repository
        self._compression = compression
        self._limiters: dict[UUID, ToolCallConcurrencyLimiter] = {}

    def record_utterance(
        self,
        interview_id: UUID,
        turn_idx: int,
        role: str,
        text: str,
        *,
        system_instructions: str,
        rules: str,
        workspace: str,
        ceiling: int,
        inference_id: str | None = None,
        observed_at: datetime | None = None,
    ) -> str:
        """Store one turn and return the context payload that should replace history."""
        turn = TurnTelemetry(
            interview_id=interview_id,
            turn_idx=turn_idx,
            role=role,
            utterance_text=text,
            input_tokens=count_tokens(system_instructions) + count_tokens(workspace),
            output_tokens=count_tokens(text) if role == "pal" else 0,
            thinking_tokens=None,  # Tavus does not report this value in utterance events.
            event_timestamp=observed_at or datetime.now(UTC),
            inference_id=inference_id,
        )
        self._repository.insert_turn(turn)
        return self._compression.ingest_turn(
            interview_id,
            f"{role}: {text}",
            system_instructions=system_instructions,
            rules=rules,
            workspace=workspace,
            ceiling=ceiling,
        )

    def record_tool_call(
        self,
        interview_id: UUID,
        tool_name: str,
        arguments: dict[str, object],
        max_calls: int,
        turn_idx: int | None = None,
    ) -> str:
        """Accept a tool call or reject it when the concurrency cap is full."""
        limiter = self._limiters.setdefault(interview_id, ToolCallConcurrencyLimiter(max_calls))
        try:
            active = limiter.try_acquire()
            status = "executed"
        except ConcurrencyLimitExceededError:
            active = limiter.active
            status = "rejected_concurrency_limit"
        try:
            self._repository.insert_tool_call(
                ToolCallRecord(
                    interview_id=interview_id,
                    tool_name=tool_name,
                    tool_origin="system" if tool_name == "end_call" else "llm",
                    arguments=arguments,
                    status=status,
                    concurrency_at_call=active,
                    called_at=datetime.now(UTC),
                    turn_idx=turn_idx,
                )
            )
        except Exception:
            if status == "executed":
                limiter.release()
            raise
        return status

    def complete_tool_call(self, interview_id: UUID) -> None:
        """Release one in-flight tool slot after the workspace finishes the call."""
        limiter = self._limiters.get(interview_id)
        if limiter is not None:
            limiter.release()
