"""PostgreSQL repositories for the interview platform."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from tavus_cvi.adapters.postgres_rows import (
    design_row,
    interview_row,
    interview_values,
    model_card_row,
    problem_row,
)
from tavus_cvi.domain.entities import (
    AgentModelCard,
    Candidate,
    InterviewSession,
    LeetCodeProblem,
    SystemDesignQuestion,
    ToolCallRecord,
    TurnTelemetry,
)


class PostgresRepository:
    """Reads and writes the interview tables."""

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def _connect(self) -> psycopg.Connection[dict[str, Any]]:
        return psycopg.connect(self._database_url, row_factory=dict_row)

    def apply_schema(self, schema_sql: str) -> None:
        """Create tables from the schema script."""
        with self._connect() as connection:
            connection.execute(schema_sql)
            connection.commit()

    def find_card_by_sha(self, digest: str) -> AgentModelCard | None:
        """Return the model card row for a YAML checksum."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM agent_model_cards WHERE yaml_sha256 = %s",
                (digest,),
            ).fetchone()
        return model_card_row(row) if row else None

    def insert_card(self, card: AgentModelCard) -> None:
        """Insert a new model-card version. Existing versions stay unchanged."""
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO agent_model_cards (
                    version, agent_name, yaml_path, yaml_sha256, model, pipeline_mode,
                    face_id, voice_id, perception_model, turn_detection_model,
                    system_instructions, context_template, hardcoded_reminder_template,
                    guardrails_config, tools_config, max_concurrent_tool_calls,
                    max_context_tokens, temperature, top_p, tavus_pal_id
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    card.version,
                    card.agent_name,
                    card.yaml_path,
                    card.yaml_sha256,
                    card.model,
                    card.pipeline_mode,
                    card.face_id,
                    card.voice_id,
                    card.perception_model,
                    card.turn_detection_model,
                    card.system_instructions,
                    card.context_template,
                    card.hardcoded_reminder_template,
                    Jsonb(card.guardrails_config),
                    Jsonb(
                        {
                            "tools": card.tools_config,
                            "objectives": card.objectives,
                            "conversational_flow": card.conversational_flow,
                        }
                    ),
                    card.max_concurrent_tool_calls,
                    card.max_context_tokens,
                    card.temperature,
                    card.top_p,
                    card.tavus_pal_id,
                ),
            )
            connection.commit()

    def set_pal_id(self, version: int, pal_id: str) -> None:
        """Store the Tavus PAL id created for this version."""
        with self._connect() as connection:
            connection.execute(
                "UPDATE agent_model_cards SET tavus_pal_id = %s WHERE version = %s",
                (pal_id, version),
            )
            connection.commit()

    def latest_interviewer_card(self) -> AgentModelCard | None:
        """Return the newest Charlie interviewer card."""
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM agent_model_cards
                WHERE agent_name = 'charlie_interviewer'
                ORDER BY version DESC LIMIT 1
                """
            ).fetchone()
        return model_card_row(row) if row else None

    def upsert_problem(self, problem: LeetCodeProblem) -> int:
        """Insert or update a LeetCode problem and return its id."""
        with self._connect() as connection:
            row = connection.execute(
                """
                INSERT INTO leetcode_tests (
                    challenge_number, title_slug, question_title, question,
                    difficulty_level, hints, boilerplate_code
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (challenge_number) DO UPDATE SET
                    title_slug = EXCLUDED.title_slug,
                    question_title = EXCLUDED.question_title,
                    question = EXCLUDED.question,
                    difficulty_level = EXCLUDED.difficulty_level,
                    hints = EXCLUDED.hints,
                    boilerplate_code = EXCLUDED.boilerplate_code
                RETURNING id
                """,
                (
                    problem.challenge_number,
                    problem.title_slug,
                    problem.question_title,
                    problem.question,
                    problem.difficulty_level,
                    Jsonb(problem.hints),
                    Jsonb(problem.boilerplate_code),
                ),
            ).fetchone()
            connection.commit()
        if row is None:
            raise RuntimeError("leetcode upsert did not return an id")
        return int(row["id"])

    def list_problems(self) -> list[LeetCodeProblem]:
        """Return every stored coding problem."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM leetcode_tests ORDER BY challenge_number"
            ).fetchall()
        return [problem_row(row) for row in rows]

    def get_problem(self, problem_id: int) -> LeetCodeProblem | None:
        """Return one coding problem by primary key."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM leetcode_tests WHERE id = %s",
                (problem_id,),
            ).fetchone()
        return problem_row(row) if row else None

    def list_designs(self) -> list[SystemDesignQuestion]:
        """Return the seeded system design questions."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM system_design_questions ORDER BY question_number"
            ).fetchall()
        return [design_row(row) for row in rows]

    def get_design(self, design_id: int) -> SystemDesignQuestion | None:
        """Return one system design question."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM system_design_questions WHERE id = %s",
                (design_id,),
            ).fetchone()
        return design_row(row) if row else None

    def allow_unknown_thinking_tokens(self) -> None:
        """Represent unreported reasoning usage as NULL in new telemetry rows."""
        with self._connect() as connection:
            connection.execute(
                "ALTER TABLE interview_turns ALTER COLUMN thinking_tokens DROP NOT NULL"
            )
            connection.commit()

    def ensure_candidate_work_columns(self) -> None:
        """Add candidate-level work and backfill existing interview snapshots."""
        with self._connect() as connection:
            connection.execute(
                "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS "
                "code_submissions JSONB NOT NULL DEFAULT '{}'::jsonb"
            )
            connection.execute(
                "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS "
                "whiteboards JSONB NOT NULL DEFAULT '{}'::jsonb"
            )
            connection.execute("""
                UPDATE candidates c SET code_submissions = d.work || c.code_submissions
                FROM (SELECT candidate_id,
                             jsonb_object_agg(id::text, final_code_submissions) AS work
                      FROM interviews WHERE final_code_submissions <> '{}'::jsonb
                      GROUP BY candidate_id) d WHERE c.id = d.candidate_id
            """)
            connection.execute("""
                UPDATE candidates c SET whiteboards = d.work || c.whiteboards
                FROM (SELECT candidate_id, jsonb_object_agg(
                          id::text, jsonb_build_object(
                              COALESCE(system_design_id::text, 'unassigned'),
                                                       final_drawio_xml)) AS work
                      FROM interviews WHERE final_drawio_xml IS NOT NULL
                      GROUP BY candidate_id) d WHERE c.id = d.candidate_id
            """)
            connection.commit()

    def ensure_revisit_column(self) -> None:
        """Migrate older local databases without changing existing sessions."""
        with self._connect() as connection:
            connection.execute(
                "ALTER TABLE interviews ADD COLUMN IF NOT EXISTS revisiting "
                "BOOLEAN NOT NULL DEFAULT FALSE"
            )
            connection.commit()

    def ensure_cv_column(self) -> None:
        """Add the CV location column on databases created before it existed."""
        with self._connect() as connection:
            connection.execute("ALTER TABLE candidates ADD COLUMN IF NOT EXISTS cv_path TEXT")
            connection.commit()

    def insert_candidate(self, candidate: Candidate) -> None:
        """Store a candidate."""
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO candidates (id, full_name, email, target_role, cv_path)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (email) DO UPDATE SET
                    full_name = EXCLUDED.full_name,
                    target_role = EXCLUDED.target_role,
                    cv_path = EXCLUDED.cv_path
                """,
                (
                    candidate.id,
                    candidate.full_name,
                    candidate.email,
                    candidate.target_role,
                    candidate.cv_path,
                ),
            )
            connection.commit()

    def candidate_by_email(self, email: str) -> Candidate | None:
        """Find a candidate by email."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM candidates WHERE email = %s",
                (email,),
            ).fetchone()
        if not row:
            return None
        return Candidate(
            UUID(str(row["id"])),
            row["full_name"],
            row["email"],
            row["target_role"],
            row.get("cv_path"),
        )

    def insert_interview(self, session: InterviewSession) -> None:
        """Store a new interview."""
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO interviews (
                    id, candidate_id, agent_model_card_version, tavus_conversation_id,
                    tavus_conversation_url, easy_leetcode_id, medium_leetcode_id,
                    system_design_id, current_phase, transcript, video_recording_path,
                    final_code_submissions, final_drawio_xml, started_at, ended_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                interview_values(session),
            )
            connection.commit()

    def save_interview(self, session: InterviewSession) -> None:
        """Update mutable interview fields."""
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE interviews SET
                    current_phase = %s,
                    revisiting = %s,
                    tavus_conversation_id = %s,
                    tavus_conversation_url = %s,
                    transcript = %s,
                    video_recording_path = %s,
                    ended_at = %s,
                    easy_leetcode_id = %s,
                    medium_leetcode_id = %s,
                    system_design_id = %s
                WHERE id = %s
                """,
                (
                    session.current_phase,
                    session.revisiting,
                    session.tavus_conversation_id,
                    session.tavus_conversation_url,
                    Jsonb(session.transcript),
                    session.video_recording_path,
                    session.ended_at,
                    session.easy_leetcode_id,
                    session.medium_leetcode_id,
                    session.system_design_id,
                    session.id,
                ),
            )
            connection.commit()

    def save_code_draft(self, interview_id: UUID, key: str, code: str) -> None:
        """Update interview and candidate snapshots in one transaction."""
        with self._connect() as connection:
            row = connection.execute(
                "UPDATE interviews SET final_code_submissions = "
                "final_code_submissions || %s WHERE id = %s "
                "RETURNING candidate_id, final_code_submissions",
                (Jsonb({key: code}), interview_id),
            ).fetchone()
            if row is None:
                raise ValueError("Interview not found")
            connection.execute(
                "UPDATE candidates SET code_submissions = jsonb_set(code_submissions, "
                "ARRAY[%s], %s, true) WHERE id = %s",
                (str(interview_id), Jsonb(row["final_code_submissions"]), row["candidate_id"]),
            )
            connection.commit()

    def save_whiteboard(self, interview_id: UUID, xml: str) -> None:
        """Update the interview's current board and candidate's per-question board."""
        with self._connect() as connection:
            row = connection.execute(
                "UPDATE interviews SET final_drawio_xml = %s WHERE id = %s "
                "RETURNING candidate_id, system_design_id",
                (xml, interview_id),
            ).fetchone()
            if row is None:
                raise ValueError("Interview not found")
            key = str(interview_id)
            question = str(row["system_design_id"] or "unassigned")
            connection.execute(
                "UPDATE candidates SET whiteboards = jsonb_set(whiteboards, ARRAY[%s], "
                "COALESCE(whiteboards -> %s, '{}'::jsonb) || %s, true) WHERE id = %s",
                (key, key, Jsonb({question: xml}), row["candidate_id"]),
            )
            connection.commit()

    def get_interview(self, interview_id: UUID) -> InterviewSession | None:
        """Load one interview."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM interviews WHERE id = %s",
                (interview_id,),
            ).fetchone()
        return interview_row(row) if row else None

    def insert_turn(self, turn: TurnTelemetry) -> None:
        """Append turn telemetry."""
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO interview_turns (
                    interview_id, turn_idx, inference_id, role, utterance_text,
                    input_tokens, output_tokens, thinking_tokens, tool_calls,
                    active_concurrent_tools, event_timestamp
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    turn.interview_id,
                    turn.turn_idx,
                    turn.inference_id,
                    turn.role,
                    turn.utterance_text,
                    turn.input_tokens,
                    turn.output_tokens,
                    turn.thinking_tokens,
                    Jsonb(turn.tool_calls),
                    turn.active_concurrent_tools,
                    turn.event_timestamp,
                ),
            )
            connection.commit()

    def insert_tool_call(self, record: ToolCallRecord) -> None:
        """Append a tool call log."""
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO tool_call_logs (
                    interview_id, turn_idx, tool_name, tool_origin, arguments,
                    status, concurrency_at_call, called_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    record.interview_id,
                    record.turn_idx,
                    record.tool_name,
                    record.tool_origin,
                    Jsonb(record.arguments),
                    record.status,
                    record.concurrency_at_call,
                    record.called_at,
                ),
            )
            connection.commit()

    def list_turns(self, interview_id: UUID) -> list[dict[str, Any]]:
        """Return stored turns for an interview."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM interview_turns
                WHERE interview_id = %s ORDER BY event_timestamp, id
                """,
                (interview_id,),
            ).fetchall()
        return list(rows)
