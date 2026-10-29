"""Signed, durable Tavus tool execution. No browser tool authority."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from jsonschema import Draft202012Validator
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from tavus_cvi.adapters.runtime_repository import RuntimeRepository
from tavus_cvi.api.security import verify_signature
from tavus_cvi.domain.errors import DomainError
from tavus_cvi.services.interview_service import InterviewService
from tavus_cvi.services.private_context import private_context

router = APIRouter()
CHECKPOINT_WAIT_SECONDS = 2.5


class Invocation(BaseModel):
    name: str = Field(max_length=150)
    arguments: str = Field(max_length=10000)
    conversation_id: str = Field(max_length=150)
    tool_call_id: str = Field(min_length=1, max_length=150)
    inference_id: str | None = None
    turn_idx: int | None = None


@router.post("/internal/tavus/tools")
async def tool_callback(request: Request) -> dict[str, object]:
    raw = await request.body()
    if len(raw) > 20000:
        raise HTTPException(413, "Tool request is too large")
    if not verify_signature(
        raw,
        request.headers.get("x-tavus-signature", ""),
        request.app.state.settings.callback_secret,
    ):
        raise HTTPException(401, "Invalid Tavus signature")
    try:
        invocation = Invocation.model_validate_json(raw)
        arguments = json.loads(invocation.arguments)
    except ValueError as exc:
        raise HTTPException(400, "Invalid tool envelope") from exc
    repository: RuntimeRepository = request.app.state.repository
    if not invocation.name.startswith("get_interview_context_"):
        # Give the connected editor a bounded opportunity to checkpoint before opening
        # another task. An absent browser never prevents an explicitly requested skip.
        with repository._connect() as connection:
            connection.execute(
                "UPDATE interview_runtime r SET checkpoint_request=%s FROM interviews i "
                "WHERE r.interview_id=i.id AND i.tavus_conversation_id=%s AND i.ended_at IS NULL",
                (invocation.tool_call_id, invocation.conversation_id),
            )
        deadline = time.monotonic() + CHECKPOINT_WAIT_SECONDS
        while time.monotonic() < deadline:
            with repository._connect() as connection:
                ready = connection.execute(
                    "SELECT r.checkpoint_ack FROM interview_runtime r JOIN interviews i "
                    "ON i.id=r.interview_id WHERE i.tavus_conversation_id=%s",
                    (invocation.conversation_id,),
                ).fetchone()
            if ready and ready["checkpoint_ack"] == invocation.tool_call_id:
                break
            await asyncio.sleep(0.1)
    # Row lock makes action + recorded result atomic; a crash rolls back both.
    with repository._connect() as connection:
        row = connection.execute(
            "SELECT * FROM interviews WHERE tavus_conversation_id=%s FOR UPDATE",
            (invocation.conversation_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Unknown conversation")
        interview_id: UUID = row["id"]
        existing = connection.execute(
            "SELECT * FROM tool_invocations WHERE conversation_id=%s AND tool_call_id=%s",
            (invocation.conversation_id, invocation.tool_call_id),
        ).fetchone()
        fingerprint = hashlib.sha256(
            json.dumps({"name": invocation.name, "arguments": arguments}, sort_keys=True).encode()
        ).hexdigest()
        if existing:
            if existing["request_hash"] != fingerprint:
                raise HTTPException(409, "Tool-call ID was reused with different arguments")
            return dict(existing["result"])
        scoped = repository.borrow(connection)
        card = scoped.card_for_version(row["agent_model_card_version"])
        tool = next((item for item in card.tools_config if item["name"] == invocation.name), None)
        if not tool or not isinstance(arguments, dict):
            raise HTTPException(403, "Tool is not permitted for this interview")
        if list(Draft202012Validator(tool["parameters"]).iter_errors(arguments)):
            raise HTTPException(400, "Arguments do not match the registered tool")
        service = InterviewService(
            scoped, request.app.state.tavus, request.app.state.settings.recordings_dir
        )
        action = invocation.name.removesuffix(f"_v{card.version}")
        result: dict[str, object]
        try:
            if action == "mark_interview_complete":
                if row["ended_at"]:
                    raise HTTPException(409, "Interview ended")
                scoped.set_runtime(interview_id, completion_requested=True)
                result = {"status": "completion recorded; use end_call now"}
            elif action == "get_interview_context":
                result = private_context(
                    scoped,
                    service,
                    interview_id,
                    arguments.get("cursor"),
                    arguments.get("resource", "transcript"),
                )
            else:
                if row["ended_at"]:
                    raise HTTPException(409, "Interview ended")
                target = {
                    "start_technical_interview": "coding_easy",
                    "advance_to_medium_problem": "coding_medium",
                    "start_system_design": "system_design",
                }.get(action)
                if action == "return_to_technical_stage":
                    if row["current_phase"] != arguments["phase"]:
                        service.revisit(interview_id, arguments["phase"])
                elif target:
                    if action == "start_system_design" and arguments.get("question_number"):
                        design = next(
                            (
                                item
                                for item in scoped.list_designs()
                                if item.question_number == arguments["question_number"]
                            ),
                            None,
                        )
                        if design is None or design.id is None:
                            raise HTTPException(400, "Unknown design question")
                        service.select_design(interview_id, design.id)
                    service.transition(interview_id, target)
                else:
                    raise HTTPException(403, "Unknown tool")
                result = private_context(scoped, service, interview_id)
        except DomainError as exc:
            raise HTTPException(409, str(exc)) from exc
        connection.execute(
            "INSERT INTO tool_invocations(conversation_id,tool_call_id,interview_id,"
            "request_hash,result) "
            "VALUES (%s,%s,%s,%s,%s)",
            (
                invocation.conversation_id,
                invocation.tool_call_id,
                interview_id,
                fingerprint,
                Jsonb(result),
            ),
        )
        connection.execute(
            "INSERT INTO tool_call_logs(interview_id,turn_idx,tool_name,tool_origin,"
            "arguments,status,"
            "concurrency_at_call,called_at) "
            "VALUES (%s,%s,%s,'llm',%s,'executed',1,now())",
            (interview_id, invocation.turn_idx, invocation.name, Jsonb(arguments)),
        )
    return result
