"""Candidate-owned lifecycle routes; interviewer actions are signed callbacks."""

from __future__ import annotations

from typing import cast
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from tavus_cvi.adapters.runtime_repository import RuntimeRepository
from tavus_cvi.api.security import COOKIE, new_token, require_owner, token_hash
from tavus_cvi.domain.errors import DomainError
from tavus_cvi.services.candidate_profile import ensure_seeded_candidate, first_name
from tavus_cvi.services.model_card_service import ModelCardService

router = APIRouter()


def callback_reachable(base_url: str) -> bool:
    try:
        response = httpx.post(base_url.rstrip("/") + "/tavus/tools", content=b"{}", timeout=4)
        return response.status_code == 401
    except httpx.HTTPError:
        return False


class StartInterviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReminderRequest(BaseModel):
    code: str = Field(default="", max_length=100_000)
    terminal: str = Field(default="", max_length=65536)
    diagram_xml: str = Field(default="", max_length=1_000_000)
    mode: str = "overwrite"


class CheckpointRequest(BaseModel):
    nonce: str = Field(min_length=1, max_length=150)


def set_capability(response: Response, token: str, secure: bool) -> None:
    response.set_cookie(
        COOKIE, token, httponly=True, samesite="strict", secure=secure, path="/api", max_age=86400
    )


def workspace_notice() -> dict[str, object]:
    # Contains no prompt, task, stored hint, candidate data, or call authority.
    return {
        "event_type": "conversation.overwrite_llm_context",
        "properties": {
            "context": (
                "Workspace may have changed. Consult the registered context tool before "
                "discussing the candidate's work. Context updates do not request speech."
            )
        },
    }


@router.get("/candidate")
def get_candidate(request: Request) -> dict[str, str]:
    candidate = ensure_seeded_candidate(request.app.state.repository)
    return {
        "full_name": candidate.full_name,
        "first_name": first_name(candidate.full_name),
        "target_role": candidate.target_role,
    }


@router.get("/interviews/current")
def current_interview(request: Request) -> dict[str, object] | None:
    token = request.cookies.get(COOKIE, "")
    interview_id = request.app.state.repository.owned_interview(token) if token else None
    if not interview_id:
        return None
    status = request.app.state.interviews.status(interview_id)
    if status["interview"]["ended_at"]:
        return None
    return cast(dict[str, object], status)


@router.post("/interviews")
def start_interview(
    body: StartInterviewRequest, request: Request, response: Response
) -> dict[str, object]:
    settings = request.app.state.settings
    if not settings.callback_base_url.startswith("https://") or not settings.callback_secret:
        raise HTTPException(503, "Trusted Tavus callback is not configured")
    repository = request.app.state.repository
    if isinstance(repository, RuntimeRepository):
        card = repository.latest_interviewer_card()
        binding_hash = ModelCardService(
            repository, None, settings.callback_base_url, settings.callback_secret
        ).binding_hash()
        with repository._connect() as connection:
            binding = connection.execute(
                "SELECT binding_hash FROM model_card_delivery WHERE version=%s",
                (card.version if card else -1,),
            ).fetchone()
        if not binding or binding["binding_hash"] != binding_hash:
            raise HTTPException(503, "Tavus callback delivery must be rebound before starting")
        if not callback_reachable(settings.callback_base_url):
            raise HTTPException(
                503, "Tavus callback tunnel is unavailable; restore it before starting"
            )
    token = request.cookies.get(COOKIE, "")
    existing = request.app.state.repository.owned_interview(token) if token else None
    if existing:
        prior = request.app.state.interviews.status(existing)
        if not prior["interview"]["ended_at"]:
            raise HTTPException(409, "Resume the interview already open in this session")
    token = token if len(token) >= 32 else new_token()
    try:
        session = request.app.state.interviews.start(None, owner_hash=token_hash(token))
    except DomainError as exc:
        raise HTTPException(503, "Interview setup failed; please try again") from exc
    set_capability(response, token, settings.cookie_secure)
    return cast(dict[str, object], request.app.state.interviews.status(session.id))


@router.post("/interviews/prepare")
def prepare_interview(request: Request, response: Response) -> dict[str, str]:
    """Establish ownership before the potentially slow remote room creation."""
    token = request.cookies.get(COOKIE, "")
    existing = request.app.state.repository.owned_interview(token) if token else None
    if existing:
        prior = request.app.state.interviews.status(existing)
        if not prior["interview"]["ended_at"]:
            return {"status": "ready"}
    set_capability(response, new_token(), request.app.state.settings.cookie_secure)
    return {"status": "ready"}


@router.get("/interviews/{interview_id}", dependencies=[Depends(require_owner)])
def get_interview(interview_id: UUID, request: Request) -> dict[str, object]:
    return cast(dict[str, object], request.app.state.interviews.status(interview_id))


@router.post("/interviews/{interview_id}/ready", dependencies=[Depends(require_owner)])
def ready(interview_id: UUID, request: Request) -> dict[str, object]:
    request.app.state.repository.ready(interview_id)
    return cast(dict[str, object], request.app.state.interviews.status(interview_id))


@router.post("/interviews/{interview_id}/checkpoint", dependencies=[Depends(require_owner)])
def checkpoint(interview_id: UUID, body: CheckpointRequest, request: Request) -> dict[str, str]:
    # This acknowledges saved work only. It cannot choose or execute a tool or phase.
    with request.app.state.repository._connect() as connection:
        connection.execute(
            "UPDATE interview_runtime SET checkpoint_ack=%s "
            "WHERE interview_id=%s AND checkpoint_request=%s",
            (body.nonce, interview_id, body.nonce),
        )
    return {"status": "acknowledged"}


@router.post("/interviews/{interview_id}/phase")
@router.post("/interviews/{interview_id}/revisit")
@router.post("/interviews/{interview_id}/design")
def denied_action(interview_id: UUID) -> None:
    raise HTTPException(403, "Only signed interviewer callbacks may change assessment stages")


@router.post("/interviews/{interview_id}/end", dependencies=[Depends(require_owner)])
def end_interview(interview_id: UUID, request: Request) -> dict[str, object]:
    try:
        session = request.app.state.repository.get_interview(interview_id)
        if session and not session.ended_at:
            request.app.state.interviews.transition(interview_id, "candidate_left")
    except DomainError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"status": "ended"}


@router.post("/interviews/{interview_id}/reminder", dependencies=[Depends(require_owner)])
def reminder(interview_id: UUID, body: ReminderRequest, request: Request) -> dict[str, object]:
    # Work is saved through revisioned workspace routes, not trusted from this notification.
    return workspace_notice()


@router.get("/problems/system-design")
def list_designs() -> None:
    raise HTTPException(403, "Question assignment is controlled by the interviewer")
