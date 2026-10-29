"""Revisioned, candidate-owned code and whiteboard persistence."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from threading import Event
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from tavus_cvi.adapters.runtime_repository import RuntimeRepository
from tavus_cvi.api.security import require_owner
from tavus_cvi.domain.context_window import summarize_drawio
from tavus_cvi.domain.entities import ExecutionResult
from tavus_cvi.domain.errors import DomainError, WorkspaceExecutionError
from tavus_cvi.services.code_execution_service import CodeExecutionService

router = APIRouter(dependencies=[Depends(require_owner)])


class DraftRequest(BaseModel):
    phase: Literal["coding_easy", "coding_medium"]
    language: Literal["python3", "typescript"]
    code: str = Field(max_length=100_000)
    revision: int = Field(ge=1)


class RunCodeRequest(DraftRequest):
    pass


class TerminalRequest(BaseModel):
    command: str = Field(min_length=1, max_length=200)


class LanguageRequest(BaseModel):
    language: Literal["python3", "typescript"]


@router.post("/workspace/{interview_id}/language")
def language(interview_id: UUID, body: LanguageRequest, request: Request) -> dict[str, str]:
    request.app.state.repository.set_runtime(interview_id, language=body.language)
    return {"status": "saved"}


class DiagramRequest(BaseModel):
    xml: str = Field(max_length=1_000_000)
    question_id: int
    revision: int = Field(ge=1)


def _write(request: Request, interview_id: UUID, key: str, value: str, revision: int) -> int:
    try:
        return int(request.app.state.repository.workspace_write(interview_id, key, value, revision))
    except DomainError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/workspace/{interview_id}/draft")
def save_draft(interview_id: UUID, body: DraftRequest, request: Request) -> dict[str, object]:
    revision = _write(
        request, interview_id, f"code:{body.phase}:{body.language}", body.code, body.revision
    )
    return {"status": "saved", "revision": revision}


@router.post("/workspace/{interview_id}/run")
async def run_code(interview_id: UUID, body: RunCodeRequest, request: Request) -> dict[str, object]:
    _write(request, interview_id, f"code:{body.phase}:{body.language}", body.code, body.revision)
    try:
        execution = request.app.state.execution
        result = await _execute(
            request,
            lambda stopped: execution.run_code(
                str(interview_id),
                body.language,
                body.code,
                **({"cancelled": stopped} if isinstance(execution, CodeExecutionService) else {}),
            ),
        )
    except WorkspaceExecutionError as exc:
        raise HTTPException(400, str(exc)) from exc
    repository = request.app.state.repository
    accepted = True
    if isinstance(repository, RuntimeRepository):
        accepted = repository.save_output(
            interview_id,
            f"code:{body.phase}:{body.language}",
            body.revision,
            result.stdout + result.stderr,
        )
    return {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "exit_code": result.exit_code,
        "duration_ms": result.duration_ms,
        "warning": ""
        if accepted
        else "Output was not saved: the task, revision or deadline changed.",
    }


@router.post("/workspace/{interview_id}/terminal")
async def run_terminal(
    interview_id: UUID, body: TerminalRequest, request: Request
) -> dict[str, object]:
    status = request.app.state.interviews.status(interview_id)
    if status["frozen"] or not status["ready"]:
        raise HTTPException(409, "Workspace is closed")
    try:
        execution = request.app.state.execution
        result = await _execute(
            request,
            lambda stopped: execution.run_terminal(
                str(interview_id),
                body.command,
                **({"cancelled": stopped} if isinstance(execution, CodeExecutionService) else {}),
            ),
        )
    except WorkspaceExecutionError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "exit_code": result.exit_code,
        "duration_ms": result.duration_ms,
    }


async def _execute(
    request: Request, operation: Callable[[Event], ExecutionResult]
) -> ExecutionResult:
    stopped = Event()
    task = asyncio.create_task(asyncio.to_thread(operation, stopped))
    try:
        while not task.done():
            if await request.is_disconnected():
                stopped.set()
            await asyncio.sleep(0.05)
        return await task
    finally:
        stopped.set()
        if not task.done():
            await asyncio.shield(task)


@router.post("/workspace/{interview_id}/diagram")
def save_diagram(interview_id: UUID, body: DiagramRequest, request: Request) -> dict[str, object]:
    revision = _write(request, interview_id, f"board:{body.question_id}", body.xml, body.revision)
    return {"summary": summarize_drawio(body.xml), "revision": revision}
