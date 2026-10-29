"""Candidate-observed transcript events; token counts are explicitly estimates."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from tavus_cvi.adapters.runtime_repository import RuntimeRepository
from tavus_cvi.api.routes_interviews import workspace_notice
from tavus_cvi.api.security import require_owner
from tavus_cvi.services.telemetry_service import TelemetryService

router = APIRouter()


class UtteranceRequest(BaseModel):
    event_id: UUID | None = None
    observed_at: datetime | None = None
    turn_idx: int = Field(ge=0)
    role: Literal["user", "pal"]
    text: str = Field(min_length=1, max_length=20000)
    inference_id: str | None = Field(default=None, max_length=200)
    code: str = Field(default="", max_length=100_000)
    terminal: str = Field(default="", max_length=65536)
    diagram_xml: str = Field(default="", max_length=1_000_000)


@router.post("/telemetry/{interview_id}/utterance", dependencies=[Depends(require_owner)])
def record_utterance(
    interview_id: UUID, body: UtteranceRequest, request: Request
) -> dict[str, object]:
    repository = request.app.state.repository
    if body.event_id and isinstance(repository, RuntimeRepository):
        if (
            not body.observed_at
            or body.observed_at.tzinfo is None
            or body.observed_at > datetime.now(UTC) + timedelta(minutes=5)
        ):
            raise HTTPException(400, "Invalid event time")
        fingerprint = hashlib.sha256(
            json.dumps(body.model_dump(mode="json"), sort_keys=True).encode()
        ).hexdigest()
        with repository._connect() as connection:
            row = connection.execute(
                "SELECT ended_at FROM interviews WHERE id=%s FOR UPDATE", (interview_id,)
            ).fetchone()
            if not row:
                raise HTTPException(404, "Interview not found")
            prior = connection.execute(
                "SELECT request_hash FROM transcript_event_receipts "
                "WHERE interview_id=%s AND event_id=%s",
                (interview_id, body.event_id),
            ).fetchone()
            if prior:
                if prior["request_hash"] != fingerprint:
                    raise HTTPException(409, "Transcript event identity conflict")
                return workspace_notice()
            if row["ended_at"] and body.observed_at > row["ended_at"]:
                raise HTTPException(409, "Event occurred after the interview ended")
            scoped = repository.borrow(connection)
            session = scoped.get_interview(interview_id)
            assert session
            card = scoped.card_for_version(session.agent_model_card_version)
            TelemetryService(scoped, request.app.state.compression).record_utterance(
                interview_id,
                body.turn_idx,
                body.role,
                body.text,
                system_instructions=card.system_instructions,
                rules="",
                workspace="",
                ceiling=card.max_context_tokens,
                inference_id=body.inference_id,
                observed_at=body.observed_at,
            )
            connection.execute(
                "INSERT INTO transcript_event_receipts VALUES (%s,%s,%s)",
                (interview_id, body.event_id, fingerprint),
            )
    else:
        session = repository.get_interview(interview_id)
        if session is None or session.ended_at:
            raise HTTPException(409, "Interview ended")
        card = repository.card_for_version(session.agent_model_card_version)
        request.app.state.telemetry.record_utterance(
            interview_id,
            body.turn_idx,
            body.role,
            body.text,
            system_instructions=card.system_instructions,
            rules="",
            workspace="",
            ceiling=card.max_context_tokens,
            inference_id=body.inference_id,
        )
    return workspace_notice()


@router.post("/telemetry/{interview_id}/tool")
@router.post("/telemetry/{interview_id}/tool/complete")
def deny_tool_logging(interview_id: UUID) -> None:
    raise HTTPException(403, "Tool invocation state is server-controlled")


@router.get("/telemetry/{interview_id}/turns", dependencies=[Depends(require_owner)])
def list_turns(interview_id: UUID, request: Request) -> dict[str, object]:
    return {
        "turns": request.app.state.repository.list_turns(interview_id),
        "token_counts": "estimates",
    }
