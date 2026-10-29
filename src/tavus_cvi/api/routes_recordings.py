"""Ownership-protected recording segment transport."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from tavus_cvi.api.security import require_owner

router = APIRouter(dependencies=[Depends(require_owner)])


class SegmentRequest(BaseModel):
    mime_type: str = Field(max_length=100)


class FinalizeRequest(BaseModel):
    count: int = Field(ge=1, le=2000)


@router.post("/interviews/{interview_id}/recordings/{segment_id}")
def create_segment(
    interview_id: UUID, segment_id: UUID, body: SegmentRequest, request: Request
) -> dict[str, str]:
    request.app.state.recordings.create(interview_id, segment_id, body.mime_type)
    return {"status": "open"}


@router.put("/interviews/{interview_id}/recordings/{segment_id}/chunks/{sequence}")
async def upload_chunk(
    interview_id: UUID, segment_id: UUID, sequence: int, request: Request
) -> dict[str, object]:
    payload = bytearray()
    async for part in request.stream():
        payload.extend(part)
        if len(payload) > 10 * 1024 * 1024:
            raise HTTPException(413, "Recording chunk exceeds 10 MiB")
    request.app.state.recordings.chunk(
        interview_id,
        segment_id,
        sequence,
        bytes(payload),
        request.headers.get("x-chunk-sha256", ""),
    )
    return {"status": "saved", "sequence": sequence}


@router.post("/interviews/{interview_id}/recordings/{segment_id}/finalize")
def finalize(
    interview_id: UUID, segment_id: UUID, body: FinalizeRequest, request: Request
) -> dict[str, str]:
    request.app.state.recordings.finalize(interview_id, segment_id, body.count)
    return {"status": "complete"}


@router.get("/interviews/{interview_id}/recordings")
def recordings(interview_id: UUID, request: Request) -> dict[str, object]:
    with request.app.state.repository._connect() as connection:
        rows = connection.execute(
            "SELECT id,mime_type,next_sequence,status FROM recording_segments "
            "WHERE interview_id=%s ORDER BY updated_at",
            (interview_id,),
        ).fetchall()
    return {"segments": rows, "capture": "screen video only"}
