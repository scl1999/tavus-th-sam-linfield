"""Serialize lifecycle changes against the same PostgreSQL row used by autosave."""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import TYPE_CHECKING, Concatenate, ParamSpec, TypeVar
from uuid import UUID

from tavus_cvi.adapters.runtime_repository import RuntimeRepository

if TYPE_CHECKING:
    from tavus_cvi.services.interview_service import InterviewService
P = ParamSpec("P")
R = TypeVar("R")


def serialized(
    method: Callable[Concatenate[InterviewService, UUID, P], R],
) -> Callable[Concatenate[InterviewService, UUID, P], R]:
    @wraps(method)
    def locked(
        self: InterviewService, interview_id: UUID, /, *args: P.args, **kwargs: P.kwargs
    ) -> R:
        from tavus_cvi.services.interview_service import InterviewService

        repository = self._repository
        if not isinstance(repository, RuntimeRepository) or repository.borrowed:
            return method(self, interview_id, *args, **kwargs)
        with repository._connect() as connection:
            connection.execute("SELECT id FROM interviews WHERE id=%s FOR UPDATE", (interview_id,))
            scoped = InterviewService(
                repository.borrow(connection),
                self._tavus,
                self._recordings_dir,
                self._rng,
                self._call_limit,
            )
            result = method(scoped, interview_id, *args, **kwargs)
        # Commit the local end and cleanup intent before contacting Tavus.
        runtime = repository.runtime(interview_id)
        if runtime and runtime["remote_end_pending"]:
            session = repository.get_interview(interview_id)
            if session and session.ended_at:
                self._end_remote(session)
        return result

    return locked
