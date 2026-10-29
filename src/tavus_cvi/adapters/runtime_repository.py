"""Durable ownership, runtime state and serialized workspace writes."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb

from tavus_cvi.adapters.postgres_repos import PostgresRepository
from tavus_cvi.adapters.postgres_rows import model_card_row
from tavus_cvi.domain.entities import AgentModelCard
from tavus_cvi.domain.errors import InvalidPhaseTransitionError


class RuntimeRepository(PostgresRepository):
    """Extend the existing repository without duplicating historical records."""

    borrowed = False

    def runtime(self, interview_id: UUID) -> dict[str, Any] | None:
        with self._connect() as connection:
            return connection.execute(
                "SELECT * FROM interview_runtime WHERE interview_id=%s", (interview_id,)
            ).fetchone()

    def create_runtime(self, interview_id: UUID, owner_hash: str | None) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO interview_runtime(interview_id,owner_hash,setup_state) "
                "VALUES (%s,%s,'creating')",
                (interview_id, owner_hash),
            )
            connection.execute(
                "INSERT INTO interview_phase_openings(interview_id,phase) VALUES (%s,'intro')",
                (interview_id,),
            )

    def owned_interview(self, token: str) -> UUID | None:
        hashed = hashlib.sha256(token.encode()).hexdigest()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT interview_id FROM interview_runtime WHERE owner_hash=%s", (hashed,)
            ).fetchone()
        return row["interview_id"] if row else None

    def card_for_version(self, version: int) -> AgentModelCard:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM agent_model_cards WHERE version=%s", (version,)
            ).fetchone()
        if row is None:
            raise InvalidPhaseTransitionError("Interview configuration is missing")
        return model_card_row(row)

    def set_runtime(self, interview_id: UUID, **changes: Any) -> None:
        allowed = {
            "setup_state",
            "connected_at",
            "remote_end_pending",
            "completion_requested",
            "terminal",
            "language",
        }
        if not changes or not set(changes) <= allowed:
            raise ValueError("Unsupported runtime update")
        columns = ",".join(f"{key}=%s" for key in changes)
        with self._connect() as connection:
            connection.execute(
                f"UPDATE interview_runtime SET {columns} WHERE interview_id=%s",
                (*changes.values(), interview_id),
            )

    def reveal(self, interview_id: UUID, phase: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO interview_phase_openings(interview_id,phase) VALUES (%s,%s) "
                "ON CONFLICT DO NOTHING",
                (interview_id, phase),
            )
            connection.execute(
                "UPDATE interview_runtime SET revealed_phases = CASE "
                "WHEN revealed_phases ? %s THEN revealed_phases "
                "ELSE revealed_phases || %s END WHERE interview_id=%s",
                (phase, Jsonb([phase]), interview_id),
            )

    def ready(self, interview_id: UUID) -> None:
        with self._connect() as connection:
            connection.execute("SELECT id FROM interviews WHERE id=%s FOR UPDATE", (interview_id,))
            connection.execute(
                "UPDATE interview_runtime SET connected_at=clock_timestamp() "
                "WHERE interview_id=%s AND connected_at IS NULL AND setup_state='ready' "
                "AND created_at > clock_timestamp() - interval '5 minutes'",
                (interview_id,),
            )

    def active_ids(self) -> list[UUID]:
        with self._connect() as connection:
            return [
                row["id"]
                for row in connection.execute(
                    "SELECT i.id FROM interviews i JOIN interview_runtime r ON r.interview_id=i.id "
                    "WHERE i.ended_at IS NULL OR r.remote_end_pending"
                ).fetchall()
            ]

    def stream_turns(self, interview_id: UUID) -> Iterator[dict[str, Any]]:
        """Bound database fetch batches instead of materializing the full transcript."""
        with (
            self._connect() as connection,
            connection.cursor(name=f"history_{uuid4().hex}") as cursor,
        ):
            cursor.itersize = 32
            cursor.execute(
                "SELECT role,utterance_text,event_timestamp FROM interview_turns "
                "WHERE interview_id=%s ORDER BY event_timestamp,id",
                (interview_id,),
            )
            yield from cursor

    def history_stats(self, interview_id: UUID) -> dict[str, int]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT count(*) AS turns,coalesce(sum(char_length(role)+3+"
                "char_length(utterance_text)),0) AS characters FROM interview_turns "
                "WHERE interview_id=%s",
                (interview_id,),
            ).fetchone()
        assert row is not None
        return {"turns": int(row["turns"]), "characters": int(row["characters"])}

    def attach_room(self, interview_id: UUID, conversation_id: str, url: str) -> None:
        """Persist the returned identity without reviving an expired setup."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT i.ended_at,r.created_at FROM interviews i JOIN interview_runtime r "
                "ON r.interview_id=i.id WHERE i.id=%s FOR UPDATE OF i,r",
                (interview_id,),
            ).fetchone()
            expired = (
                not row
                or row["ended_at"]
                or (datetime.now(UTC) - row["created_at"]).total_seconds() >= 300
            )
            connection.execute(
                "UPDATE interviews SET tavus_conversation_id=%s,tavus_conversation_url=%s "
                "WHERE id=%s",
                (conversation_id, url, interview_id),
            )
            connection.execute(
                "UPDATE interview_runtime SET setup_state=%s,remote_end_pending=%s "
                "WHERE interview_id=%s",
                ("failed" if expired else "ready", bool(expired), interview_id),
            )
        if expired:
            raise InvalidPhaseTransitionError("Media setup deadline expired")

    def save_output(self, interview_id: UUID, key: str, revision: int, output: str) -> bool:
        with self._connect() as connection:
            connection.execute(
                "SELECT i.id FROM interviews i JOIN interview_runtime r ON r.interview_id=i.id "
                "WHERE i.id=%s FOR UPDATE OF i,r",
                (interview_id,),
            )
            updated = connection.execute(
                "UPDATE interview_runtime r SET terminal=%s FROM interviews i "
                "WHERE r.interview_id=i.id AND i.id=%s AND i.ended_at IS NULL "
                "AND r.connected_at > clock_timestamp()-interval '55 minutes' "
                "AND r.revisions->>%s=%s AND i.current_phase=%s RETURNING i.id",
                (output[-65536:], interview_id, key, str(revision), key.split(":")[1]),
            ).fetchone()
        return bool(updated)

    def workspace_write(self, interview_id: UUID, key: str, value: str, revision: int) -> int:
        """Reject stale writes and lock the accepted snapshot at the server deadline."""
        with self._connect() as connection:
            session = connection.execute(
                "SELECT i.*,r.connected_at,r.revisions FROM interviews i "
                "JOIN interview_runtime r ON r.interview_id=i.id WHERE i.id=%s FOR UPDATE OF i,r",
                (interview_id,),
            ).fetchone()
            if session is None or session["ended_at"] or session["connected_at"] is None:
                raise InvalidPhaseTransitionError("Workspace is not open")
            if (datetime.now(UTC) - session["connected_at"]).total_seconds() >= 3300:
                raise InvalidPhaseTransitionError("Technical assessment is locked at 55:00")
            prior = int(session["revisions"].get(key, 0))
            if key.startswith("code:"):
                _, phase, language = key.split(":")
                if session["current_phase"] != phase:
                    raise InvalidPhaseTransitionError(
                        "The active task changed; keep the local draft"
                    )
                existing = session["final_code_submissions"].get(f"{phase}:{language}", "")
            else:
                if session["current_phase"] != "system_design":
                    raise InvalidPhaseTransitionError("The design board is not active")
                if key != f"board:{session['system_design_id']}":
                    raise InvalidPhaseTransitionError("The design question changed")
                existing = session["final_drawio_xml"] or ""
            if revision <= prior:
                if revision == prior and existing == value:
                    return prior
                raise InvalidPhaseTransitionError("A newer revision is already saved")
            borrowed = self.borrow(connection)
            if key.startswith("code:"):
                borrowed.save_code_draft(interview_id, f"{phase}:{language}", value)
                connection.execute(
                    "UPDATE interview_runtime SET language=%s WHERE interview_id=%s",
                    (language, interview_id),
                )
            else:
                borrowed.save_whiteboard(interview_id, value)
                connection.execute(
                    "UPDATE interview_runtime SET whiteboards=whiteboards || %s "
                    "WHERE interview_id=%s",
                    (Jsonb({str(session["system_design_id"]): value}), interview_id),
                )
            connection.execute(
                "UPDATE interview_runtime SET revisions=revisions || %s WHERE interview_id=%s",
                (Jsonb({key: revision}), interview_id),
            )
        return revision

    def borrow(self, connection: psycopg.Connection[dict[str, Any]]) -> RuntimeRepository:
        """Use an outer transaction; nested repository methods cannot commit it."""
        child = RuntimeRepository(self._database_url)
        child.borrowed = True

        class Borrowed:
            def execute(self, *args: Any, **kwargs: Any) -> Any:
                return connection.execute(*args, **kwargs)

            def cursor(self, *args: Any, **kwargs: Any) -> Any:
                return connection.cursor(*args, **kwargs)

            def transaction(self, *args: Any, **kwargs: Any) -> Any:
                return connection.transaction(*args, **kwargs)

            def commit(self) -> None:
                return None

        @contextmanager
        def connect() -> Any:
            with connection.transaction():
                yield Borrowed()

        child._connect = connect  # type: ignore[method-assign,assignment]
        return child
