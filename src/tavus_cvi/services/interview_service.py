"""Create and advance a local interview, including the Tavus conversation."""

from __future__ import annotations

import logging
import random
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from tavus_cvi.adapters.postgres_repos import PostgresRepository
from tavus_cvi.adapters.runtime_repository import RuntimeRepository
from tavus_cvi.adapters.tavus_client import TavusClient
from tavus_cvi.domain.context_window import assemble_context
from tavus_cvi.domain.entities import (
    Candidate,
    InterviewSession,
    LeetCodeProblem,
    SystemDesignQuestion,
)
from tavus_cvi.domain.errors import InvalidPhaseTransitionError, TavusIntegrationError
from tavus_cvi.domain.rules import (
    CALL_LIMIT_SECONDS,
    assert_transition,
    is_frozen,
    phase_deadline,
    select_coding_pair,
    timed_phase,
)
from tavus_cvi.domain.starters import runnable_starter
from tavus_cvi.services.candidate_profile import (
    cv_sections,
    ensure_seeded_candidate,
    first_name,
    greeting,
    read_cv_text,
)
from tavus_cvi.services.serialized import serialized
from tavus_cvi.services.token_counter import count_tokens

logger = logging.getLogger(__name__)


class InterviewService:
    """Owns interview lifecycle and the opening conversational context."""

    def __init__(
        self,
        repository: PostgresRepository,
        tavus: TavusClient | None,
        recordings_dir: Path,
        rng: random.Random | None = None,
        call_limit: int = CALL_LIMIT_SECONDS,
    ) -> None:
        self._repository = repository
        self._tavus = tavus
        self._recordings_dir = recordings_dir
        self._rng = rng or random.Random()
        self._call_limit = call_limit

    def start(
        self, system_design_id: int | None, owner_hash: str | None = None
    ) -> InterviewSession:
        """Pick problems, open a CVI room, and persist the interview."""
        card = self._repository.latest_interviewer_card()
        if card is None or not card.tavus_pal_id:
            raise TavusIntegrationError("Charlie's model card is not provisioned")
        candidate = ensure_seeded_candidate(self._repository)
        cv_location = Path(candidate.cv_path) if candidate.cv_path else Path()
        cv_hot, cv_digest = cv_sections(read_cv_text(cv_location))
        problems = self._repository.list_problems()
        if isinstance(self._repository, RuntimeRepository):
            problems = [
                item for item in problems if item.challenge_number in {1, 20, 26, 3, 11, 49}
            ]
        easy, medium = select_coding_pair(problems, self._rng)
        designs = self._repository.list_designs()
        design = next((item for item in designs if item.id == system_design_id), None)
        if design is None:
            design = designs[0] if designs else None
        if easy.id is None or medium.id is None or design is None or design.id is None:
            raise InvalidPhaseTransitionError("Problems are not seeded")
        session = InterviewSession(
            id=uuid4(),
            candidate_id=candidate.id,
            agent_model_card_version=card.version,
            current_phase="intro",
            started_at=datetime.now(UTC),
            easy_leetcode_id=easy.id,
            medium_leetcode_id=medium.id,
            system_design_id=design.id,
        )
        context = assemble_context(
            system_instructions=card.system_instructions,
            rules=card.hardcoded_reminder_template.format(
                elapsed_clock="00:00",
                phase="intro",
                frozen=False,
                active_problem=easy.question_title,
                workspace_delta="Editor has not opened.",
            ),
            workspace="Editor has not opened.",
            digest=cv_digest,
            hot_window=(
                f"{candidate.full_name} is interviewing for {candidate.target_role}. "
                f"CV file: {candidate.cv_path}. "
                "You are an AI. Say that you are an AI before the interview begins.\n"
                f"{cv_hot}"
            ),
            count_tokens=count_tokens,
            ceiling=card.max_context_tokens,
        )
        if self._tavus is None:
            raise TavusIntegrationError("Tavus client is not configured")
        self._repository.insert_interview(session)
        runtime = self._repository if isinstance(self._repository, RuntimeRepository) else None
        if runtime:
            runtime.create_runtime(session.id, owner_hash)
        try:
            try:
                self._pin_memories(
                    card.tavus_pal_id,
                    candidate,
                    f"interview_{session.id}",
                    easy.question_title,
                    medium.question_title,
                    design.question_title,
                )
            except Exception:
                logger.warning(
                    "Optional memory initialization failed", extra={"interview_id": str(session.id)}
                )
            conversation = self._tavus.create_conversation(
                {
                    "pal_id": card.tavus_pal_id,
                    "face_id": card.face_id,
                    "conversation_name": f"Interview {session.id}",
                    "conversational_context": context,
                    "custom_greeting": greeting(first_name(candidate.full_name)),
                    "participant_tags": [f"interview_{session.id}"],
                    "properties": {
                        "max_call_duration": self._call_limit + 300
                        if self._call_limit == 3600
                        else self._call_limit,
                        "enable_closed_captions": True,
                    },
                }
            )
            session.tavus_conversation_id = str(conversation["conversation_id"])
            session.tavus_conversation_url = str(conversation["conversation_url"])
            if runtime:
                runtime.attach_room(
                    session.id, session.tavus_conversation_id, session.tavus_conversation_url
                )
            else:
                self._repository.save_interview(session)
        except Exception:
            # Compensate even when the local save failed after room creation.
            session.current_phase = "candidate_left"
            session.ended_at = datetime.now(UTC)
            try:
                self._repository.save_interview(session)
                if runtime:
                    runtime.set_runtime(session.id, setup_state="failed", remote_end_pending=True)
            except Exception:
                logger.exception(
                    "Could not persist failed setup", extra={"interview_id": str(session.id)}
                )
            self._end_remote(session)
            raise
        return session

    @serialized
    def select_design(self, interview_id: UUID, design_id: int) -> InterviewSession:
        """Point the interview at one of the three system design prompts."""
        session = self._synchronize(interview_id)
        elapsed = self._elapsed(session)
        if session.ended_at or is_frozen(elapsed):
            raise InvalidPhaseTransitionError("Technical assessment is locked at 55:00")
        design = self._repository.get_design(design_id)
        if design is None or design.id is None:
            raise InvalidPhaseTransitionError("System design question not found")
        if isinstance(self._repository, RuntimeRepository):
            runtime = self._repository.runtime(interview_id) or {}
            xml = runtime.get("whiteboards", {}).get(str(design.id), "")
            with self._repository._connect() as connection:
                connection.execute(
                    "UPDATE interviews SET system_design_id=%s,final_drawio_xml=%s WHERE id=%s",
                    (design.id, xml, interview_id),
                )
            return self._require(interview_id)
        session.system_design_id = design.id
        self._repository.save_interview(session)
        return session

    @serialized
    def transition(self, interview_id: UUID, target: str) -> InterviewSession:
        """Move the interview to the next allowed phase."""
        session = self._synchronize(interview_id)
        if session.current_phase == target:
            return session
        if session.ended_at and target in {"candidate_left", "completed", "terminated_rude"}:
            return session
        if is_frozen(self._elapsed(session)) and target not in {
            "completed",
            "terminated_rude",
            "candidate_left",
        }:
            raise InvalidPhaseTransitionError("Technical assessment is locked at 55:00")
        if isinstance(self._repository, RuntimeRepository) and target not in {
            "candidate_left",
            "completed",
            "terminated_rude",
        }:
            runtime = self._repository.runtime(interview_id)
            if not runtime or not runtime["connected_at"]:
                raise InvalidPhaseTransitionError("Waiting for candidate media readiness")
        requested_completion = (
            target == "completed"
            and isinstance(self._repository, RuntimeRepository)
            and bool((self._repository.runtime(interview_id) or {}).get("completion_requested"))
        )
        if not requested_completion:
            assert_transition(session.current_phase, target)
        session.current_phase = target
        if target in {"completed", "terminated_rude", "candidate_left"}:
            session.ended_at = datetime.now(UTC)
        self._repository.save_interview(session)
        if isinstance(self._repository, RuntimeRepository):
            self._repository.reveal(session.id, target)
        if session.ended_at:
            self._end_remote(session)
        return session

    @serialized
    def revisit(self, interview_id: UUID, target: str) -> InterviewSession:
        """Reopen an earlier technical stage without resetting the interview clock."""
        session = self._synchronize(interview_id)
        order = ["coding_easy", "coding_medium", "system_design"]
        if session.ended_at or is_frozen(self._elapsed(session)):
            raise InvalidPhaseTransitionError("Technical assessment is locked at 55:00")
        if session.current_phase not in order or target not in order:
            raise InvalidPhaseTransitionError("Only earlier technical stages can be revisited")
        if order.index(target) >= order.index(session.current_phase):
            raise InvalidPhaseTransitionError("Choose an earlier technical stage")
        session.current_phase = target
        session.revisiting = True
        self._repository.save_interview(session)
        if isinstance(self._repository, RuntimeRepository):
            self._repository.reveal(session.id, target)
        return session

    def status(self, interview_id: UUID) -> dict[str, object]:
        """Return the session plus the problems the UI should render."""
        session = self._synchronize(interview_id)
        elapsed = self._elapsed(session)
        runtime = (
            self._repository.runtime(session.id)
            if isinstance(self._repository, RuntimeRepository)
            else None
        )
        opened = (
            runtime["revealed_phases"]
            if runtime
            else ["coding_easy", "coding_medium", "system_design"]
        )
        easy = self._repository.get_problem(session.easy_leetcode_id or 0)
        medium = self._repository.get_problem(session.medium_leetcode_id or 0)
        design = self._repository.get_design(session.system_design_id or 0)
        return {
            "interview": _public_session(session),
            "elapsed_seconds": elapsed,
            "frozen": bool(session.ended_at) or is_frozen(elapsed),
            "phase_deadline_seconds": (
                3300
                if session.revisiting and not is_frozen(elapsed)
                else phase_deadline(session.current_phase, elapsed)
            ),
            "ready": bool(runtime is None or runtime["connected_at"]),
            "setup_state": runtime["setup_state"] if runtime else "ready",
            "checkpoint_request": runtime.get("checkpoint_request") if runtime else None,
            "easy": _public_problem(easy) if "coding_easy" in opened else None,
            "medium": _public_problem(medium) if "coding_medium" in opened else None,
            "system_design": _public_design(design) if "system_design" in opened else None,
            "workspace": {
                "drafts": session.final_code_submissions,
                "whiteboards": runtime["whiteboards"] if runtime else {},
                "revisions": runtime["revisions"] if runtime else {},
                "language": runtime["language"] if runtime else "python3",
                "terminal": runtime["terminal"] if runtime else "",
            },
        }

    def _elapsed(self, session: InterviewSession) -> int:
        base = session.started_at
        if isinstance(self._repository, RuntimeRepository):
            runtime = self._repository.runtime(session.id)
            if runtime and runtime["connected_at"] is None:
                return 0
            if runtime:
                base = runtime["connected_at"]
        end = session.ended_at or datetime.now(UTC)
        return max(0, int((end - base).total_seconds()))

    @serialized
    def _synchronize(self, interview_id: UUID) -> InterviewSession:
        session = self._require(interview_id)
        if isinstance(self._repository, RuntimeRepository):
            runtime = self._repository.runtime(session.id)
            if runtime and not runtime["connected_at"] and not session.ended_at:
                if (datetime.now(UTC) - runtime["created_at"]).total_seconds() >= 300:
                    session.current_phase = "candidate_left"
                    session.ended_at = datetime.now(UTC)
                    self._repository.save_interview(session)
                    self._end_remote(session)
                return session
        elapsed = self._elapsed(session)
        target = (
            session.current_phase
            if session.revisiting and elapsed < CALL_LIMIT_SECONDS
            else timed_phase(session.current_phase, elapsed)
        )
        if target != session.current_phase:
            session.current_phase = target
            if target == "completed":
                session.ended_at = datetime.now(UTC)
            self._repository.save_interview(session)
            if isinstance(self._repository, RuntimeRepository):
                self._repository.reveal(session.id, target)
            if session.ended_at:
                self._end_remote(session)
        return session

    def _require(self, interview_id: UUID) -> InterviewSession:
        session = self._repository.get_interview(interview_id)
        if session is None:
            raise InvalidPhaseTransitionError("Interview not found")
        return session

    def _end_remote(self, session: InterviewSession) -> None:
        runtime = self._repository if isinstance(self._repository, RuntimeRepository) else None
        if runtime:
            try:
                runtime.set_runtime(
                    session.id, remote_end_pending=bool(session.tavus_conversation_id)
                )
            except Exception:
                logger.exception("Could not persist remote cleanup intent")
            if runtime.borrowed:
                return
        if self._tavus and session.tavus_conversation_id:
            try:
                self._tavus.end_conversation(session.tavus_conversation_id)
                if runtime:
                    runtime.set_runtime(session.id, remote_end_pending=False)
            except Exception:
                logger.warning("Remote cleanup pending", extra={"interview_id": str(session.id)})

    def tick(self) -> None:
        """Recover deadlines and pending remote cleanup without a connected browser."""
        if not isinstance(self._repository, RuntimeRepository):
            return
        for interview_id in self._repository.active_ids():
            try:
                session = self._synchronize(interview_id)
                if not session.ended_at and self._tavus and session.tavus_conversation_id:
                    try:
                        remote = self._tavus.conversation_status(session.tavus_conversation_id)
                        if remote == "ended":
                            completion_state = self._repository.runtime(interview_id) or {}
                            target = (
                                "completed"
                                if completion_state.get("completion_requested")
                                else "candidate_left"
                            )
                            self.transition(interview_id, target)
                            session = self._require(interview_id)
                    except Exception:
                        logger.warning(
                            "Remote status unavailable", extra={"interview_id": str(interview_id)}
                        )
                runtime = self._repository.runtime(interview_id)
                if session.ended_at and runtime and runtime["remote_end_pending"]:
                    self._end_remote(session)
            except Exception:
                logger.exception(
                    "Interview reconciliation failed", extra={"interview_id": str(interview_id)}
                )

    def _pin_memories(
        self,
        pal_id: str,
        candidate: Candidate,
        participant_tag: str,
        easy_title: str,
        medium_title: str,
        design_title: str,
    ) -> None:
        if self._tavus is None:
            return
        store_id = self._tavus.create_memory_store(pal_id, participant_tag)
        if not store_id:
            return
        for fact in (
            f"Candidate name is {candidate.full_name}.",
            f"Target role is {candidate.target_role}.",
            f"CV file location is {candidate.cv_path}.",
            "Charlie is an AI and must say so at the start.",
            f"Easy problem is {easy_title}.",
            f"Medium problem is {medium_title}.",
            f"System design is {design_title}.",
        ):
            self._tavus.pin_memory(store_id, fact)


def _public_session(session: InterviewSession) -> dict[str, object]:
    return {
        "id": str(session.id),
        "current_phase": session.current_phase,
        "conversation_url": session.tavus_conversation_url,
        "conversation_id": session.tavus_conversation_id,
        "started_at": session.started_at.isoformat(),
        "ended_at": session.ended_at.isoformat() if session.ended_at else None,
    }


def _public_problem(problem: LeetCodeProblem | None) -> dict[str, object] | None:
    if problem is None:
        return None
    return {
        "id": problem.id,
        "challenge_number": problem.challenge_number,
        "question_title": problem.question_title,
        "question": problem.question,
        "difficulty_level": problem.difficulty_level,
        "boilerplate_code": {
            key: runnable_starter(key, value) for key, value in problem.boilerplate_code.items()
        },
    }


def _public_design(design: SystemDesignQuestion | None) -> dict[str, object] | None:
    if design is None:
        return None
    return {
        "id": design.id,
        "question_number": design.question_number,
        "question_title": design.question_title,
        "problem_statement": design.problem_statement,
        "functional_requirements": design.functional_requirements,
        "non_functional_requirements": design.non_functional_requirements,
    }
