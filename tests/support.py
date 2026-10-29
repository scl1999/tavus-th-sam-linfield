"""In-memory stand-ins shared by service tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from tavus_cvi.domain.entities import (
    AgentModelCard,
    Candidate,
    InterviewSession,
    LeetCodeProblem,
    SystemDesignQuestion,
)


def sample_card(*, pal_id: str | None = "pal-1") -> AgentModelCard:
    return AgentModelCard(
        version=1,
        agent_name="charlie_interviewer",
        yaml_path="config/agents/charlie_interviewer.yaml",
        yaml_sha256="abc",
        model="tavus-gpt-5.6-terra",
        pipeline_mode="full",
        face_id="rbb3ca3630f7",
        voice_id="charlie",
        perception_model="raven-2",
        turn_detection_model="sparrow-2",
        system_instructions="Stay professional. Use end_call after one warning.",
        context_template="{phase}",
        hardcoded_reminder_template=(
            "Elapsed {elapsed_clock}. Phase {phase}. Frozen {frozen}. "
            "{active_problem} {workspace_delta}"
        ),
        guardrails_config=[],
        tools_config=[],
        objectives=[],
        max_concurrent_tool_calls=2,
        max_context_tokens=5000,
        temperature=0.4,
        top_p=0.9,
        tavus_pal_id=pal_id,
    )


def sample_problem(number: int, difficulty: str) -> LeetCodeProblem:
    return LeetCodeProblem(
        challenge_number=number,
        title_slug=f"problem-{number}",
        question_title=f"Problem {number}",
        question="Solve it.",
        difficulty_level=difficulty,
        hints=["Think."],
        boilerplate_code={"python3": "pass", "typescript": "export {}"},
        id=number,
    )


def sample_design(number: int) -> SystemDesignQuestion:
    return SystemDesignQuestion(
        question_number=number,
        question_title=f"Design {number}",
        problem_statement="Design it.",
        functional_requirements=["Create"],
        non_functional_requirements=["Low latency"],
        evaluation_rubric=["API"],
        id=number,
    )


class InMemoryStore:
    """Repository methods the services call, without PostgreSQL."""

    def __init__(self, card: AgentModelCard | None = None) -> None:
        self.card = sample_card() if card is None else card
        self.candidates: dict[str, Candidate] = {}
        self.interviews: dict[UUID, InterviewSession] = {}
        self.problems = [sample_problem(1, "Easy"), sample_problem(2, "Medium")]
        self.designs = [sample_design(1), sample_design(2)]
        self.cards_by_sha: dict[str, AgentModelCard] = {}
        self.inserted_cards: list[AgentModelCard] = []
        self.pal_ids: dict[int, str] = {}
        self.cv_column = False

    def ensure_cv_column(self) -> None:
        self.cv_column = True

    def insert_candidate(self, candidate: Candidate) -> None:
        self.candidates[candidate.email] = candidate

    def candidate_by_email(self, email: str) -> Candidate | None:
        return self.candidates.get(email)

    def latest_interviewer_card(self) -> AgentModelCard | None:
        return self.card

    def list_problems(self) -> list[LeetCodeProblem]:
        return list(self.problems)

    def list_designs(self) -> list[SystemDesignQuestion]:
        return list(self.designs)

    def get_problem(self, problem_id: int) -> LeetCodeProblem | None:
        return next((item for item in self.problems if item.id == problem_id), None)

    def get_design(self, design_id: int) -> SystemDesignQuestion | None:
        return next((item for item in self.designs if item.id == design_id), None)

    def insert_interview(self, session: InterviewSession) -> None:
        self.interviews[session.id] = session

    def save_interview(self, session: InterviewSession) -> None:
        self.interviews[session.id] = session

    def get_interview(self, interview_id: UUID) -> InterviewSession | None:
        return self.interviews.get(interview_id)

    def find_card_by_sha(self, digest: str) -> AgentModelCard | None:
        return self.cards_by_sha.get(digest)

    def insert_card(self, card: AgentModelCard) -> None:
        self.inserted_cards.append(card)
        self.cards_by_sha[card.yaml_sha256] = card

    def set_pal_id(self, version: int, pal_id: str) -> None:
        self.pal_ids[version] = pal_id
        for digest, card in list(self.cards_by_sha.items()):
            if card.version == version:
                updated = AgentModelCard(**{**card.__dict__, "tavus_pal_id": pal_id})
                self.cards_by_sha[digest] = updated


def open_session(store: InMemoryStore) -> InterviewSession:
    """Persist one intro interview for transition tests."""
    session = InterviewSession(
        id=uuid4(),
        candidate_id=uuid4(),
        agent_model_card_version=1,
        current_phase="intro",
        started_at=datetime.now(UTC),
        easy_leetcode_id=1,
        medium_leetcode_id=2,
        system_design_id=1,
        tavus_conversation_id="conv-1",
    )
    store.insert_interview(session)
    return session
