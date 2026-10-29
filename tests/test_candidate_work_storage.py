"""Opt-in PostgreSQL test; all fixture data is rolled back."""

import os
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from tavus_cvi.adapters.postgres_repos import PostgresRepository
from tavus_cvi.domain.entities import TurnTelemetry


@pytest.mark.skipif(not os.getenv("TAVUS_TEST_DATABASE_URL"), reason="PostgreSQL test URL not set")
def test_candidate_work_is_linked_to_interview_and_not_lost_by_stale_session() -> None:
    database_url = os.environ["TAVUS_TEST_DATABASE_URL"]
    connection = psycopg.connect(database_url, row_factory=dict_row)
    candidate_id, interview_id = uuid4(), uuid4()
    repository = PostgresRepository(database_url)

    class TransactionConnection:
        def execute(self, *args, **kwargs):
            return connection.execute(*args, **kwargs)

        def commit(self):
            pass  # The entire test rolls back, including the candidate and interview.

    @contextmanager
    def transaction_connection():
        yield TransactionConnection()

    repository._connect = transaction_connection  # type: ignore[method-assign]
    try:
        card = connection.execute("SELECT version FROM agent_model_cards LIMIT 1").fetchone()
        assert card is not None
        connection.execute(
            "INSERT INTO candidates(id, full_name, email, target_role) VALUES (%s, %s, %s, %s)",
            (candidate_id, "Test", f"{candidate_id}@example.test", "Engineer"),
        )
        connection.execute(
            "INSERT INTO interviews(id, candidate_id, agent_model_card_version, current_phase) "
            "VALUES (%s, %s, %s, 'coding_easy')",
            (interview_id, candidate_id, card["version"]),
        )
        repository.insert_turn(
            TurnTelemetry(
                interview_id=interview_id,
                turn_idx=1,
                role="pal",
                utterance_text="Hello",
                input_tokens=10,
                output_tokens=2,
                thinking_tokens=None,
                event_timestamp=datetime.now(UTC),
                inference_id="test-inference",
            )
        )
        turn = connection.execute(
            "SELECT thinking_tokens, inference_id FROM interview_turns WHERE interview_id = %s",
            (interview_id,),
        ).fetchone()
        assert turn is not None and turn["thinking_tokens"] is None
        assert turn["inference_id"] == "test-inference"
        stale = repository.get_interview(interview_id)
        assert stale is not None
        repository.save_code_draft(interview_id, "coding_easy:python3", "first solution")
        repository.save_code_draft(interview_id, "coding_medium:typescript", "second solution")
        repository.save_whiteboard(interview_id, "<mxfile>diagram</mxfile>")
        repository.save_interview(stale)
        saved = repository.get_interview(interview_id)
        assert saved is not None
        assert saved.final_code_submissions == {
            "coding_easy:python3": "first solution",
            "coding_medium:typescript": "second solution",
        }
        assert saved.final_drawio_xml == "<mxfile>diagram</mxfile>"
        row = connection.execute(
            "SELECT code_submissions, whiteboards FROM candidates WHERE id = %s", (candidate_id,)
        ).fetchone()
        assert row is not None
        assert row["code_submissions"][str(interview_id)] == saved.final_code_submissions
        assert row["whiteboards"][str(interview_id)]["unassigned"] == saved.final_drawio_xml
    finally:
        connection.rollback()
        connection.close()
