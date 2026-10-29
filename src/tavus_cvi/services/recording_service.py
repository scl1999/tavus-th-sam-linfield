"""Sequenced, checksummed screen-video segments with explicit finalization."""

from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import UUID

from fastapi import HTTPException

from tavus_cvi.adapters.runtime_repository import RuntimeRepository


class RecordingService:
    def __init__(self, repository: RuntimeRepository, root: Path) -> None:
        self.repository = repository
        self.root = root

    def create(self, interview_id: UUID, segment_id: UUID, mime: str) -> None:
        if mime.split(";")[0] not in {"video/webm", "video/mp4"}:
            raise HTTPException(400, "Unsupported screen recording format")
        with self.repository._connect() as connection:
            row = connection.execute(
                "SELECT * FROM recording_segments WHERE id=%s FOR UPDATE", (segment_id,)
            ).fetchone()
            if row:
                if row["interview_id"] != interview_id or row["mime_type"] != mime:
                    raise HTTPException(409, "Recording identity conflict")
                return
            session = connection.execute(
                "SELECT ended_at FROM interviews WHERE id=%s FOR UPDATE", (interview_id,)
            ).fetchone()
            if not session:
                raise HTTPException(404, "Interview not found")
            # A persisted local upload queue may first reach us after the call ended.
            count = connection.execute(
                "SELECT count(*) AS n FROM recording_segments WHERE interview_id=%s",
                (interview_id,),
            ).fetchone()
            if count and count["n"] >= 32:
                raise HTTPException(409, "Recording segment limit reached")
            connection.execute(
                "INSERT INTO recording_segments(id,interview_id,mime_type) VALUES (%s,%s,%s)",
                (segment_id, interview_id, mime),
            )

    def chunk(
        self, interview_id: UUID, segment_id: UUID, sequence: int, payload: bytes, checksum: str
    ) -> None:
        if not payload or len(payload) > 10 * 1024 * 1024 or sequence < 0 or sequence >= 2000:
            raise HTTPException(413, "Chunk exceeds recording limits")
        if hashlib.sha256(payload).hexdigest() != checksum:
            raise HTTPException(400, "Chunk checksum mismatch")
        with self.repository._connect() as connection:
            row = connection.execute(
                "SELECT * FROM recording_segments WHERE id=%s AND interview_id=%s FOR UPDATE",
                (segment_id, interview_id),
            ).fetchone()
            if not row:
                raise HTTPException(404, "Recording not found")
            prior = connection.execute(
                "SELECT checksum FROM recording_chunks WHERE segment_id=%s AND sequence=%s",
                (segment_id, sequence),
            ).fetchone()
            if prior:
                if prior["checksum"] != checksum:
                    raise HTTPException(409, "Conflicting duplicate recording chunk")
                return
            if row["status"] == "complete" or sequence != row["next_sequence"]:
                raise HTTPException(409, "Chunk is out of sequence or segment is complete")
            size = connection.execute(
                "SELECT coalesce(sum(octet_length(payload)),0) AS size "
                "FROM recording_chunks WHERE segment_id=%s",
                (segment_id,),
            ).fetchone()
            if size and size["size"] + len(payload) > 1024**3:
                raise HTTPException(413, "Recording segment exceeds 1 GiB")
            connection.execute(
                "INSERT INTO recording_chunks VALUES (%s,%s,%s,%s)",
                (segment_id, sequence, checksum, payload),
            )
            connection.execute(
                "UPDATE recording_segments SET next_sequence=next_sequence+1, "
                "updated_at=now(),status='open' WHERE id=%s",
                (segment_id,),
            )

    def finalize(self, interview_id: UUID, segment_id: UUID, count: int) -> None:
        with self.repository._connect() as connection:
            row = connection.execute(
                "SELECT * FROM recording_segments WHERE id=%s AND interview_id=%s FOR UPDATE",
                (segment_id, interview_id),
            ).fetchone()
            if not row:
                raise HTTPException(404, "Recording not found")
            if count != row["next_sequence"] or count < 1:
                raise HTTPException(409, "Recording still has unacknowledged chunks")
            if row["status"] == "complete":
                return
            self.root.mkdir(parents=True, exist_ok=True)
            extension = "webm" if row["mime_type"].startswith("video/webm") else "mp4"
            path = self.root / f"{interview_id}-{segment_id}.{extension}"
            temporary = path.with_suffix(".part")
            with (
                temporary.open("wb") as output,
                connection.cursor(name=f"recording_{segment_id.hex}") as cursor,
            ):
                cursor.execute(
                    "SELECT payload FROM recording_chunks WHERE segment_id=%s ORDER BY sequence",
                    (segment_id,),
                )
                for chunk in cursor:
                    output.write(chunk["payload"])
            temporary.replace(path)
            connection.execute(
                "UPDATE recording_segments SET status='complete',path=%s,updated_at=now() "
                "WHERE id=%s",
                (str(path), segment_id),
            )
            connection.execute(
                "UPDATE interviews SET video_recording_path=%s WHERE id=%s",
                (str(path), interview_id),
            )
