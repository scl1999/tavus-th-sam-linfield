"""Application wiring, settings, schema, and the LeetCode seed script."""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

import scrape_leetcode_problems
from tavus_cvi.adapters.config import REPO_ROOT, Settings
from tavus_cvi.api.app import create_app
from tavus_cvi.domain.entities import LeetCodeProblem
from tests.support import sample_problem


def test_health_responds_without_opening_the_database() -> None:
    app = create_app(Settings(TAVUS_API_KEY="", DATABASE_URL="postgresql://unused/db"))

    @asynccontextmanager
    async def _skip_startup(_app: object) -> AsyncIterator[None]:
        yield

    app.router.lifespan_context = _skip_startup
    with TestClient(app) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["x-request-id"]


def test_settings_keep_the_local_database_default(monkeypatch) -> None:
    monkeypatch.setenv("NOT_A_SETTING", "ignored")
    settings = Settings(TAVUS_API_KEY="", DATABASE_URL="postgresql://unit/db")
    assert settings.database_url == "postgresql://unit/db"
    assert settings.tavus_base_url == "https://tavusapi.com"
    assert settings.agent_config_dir == REPO_ROOT / "config" / "agents"


def test_schema_declares_every_interview_table() -> None:
    sql = (REPO_ROOT / "src" / "tavus_cvi" / "adapters" / "db" / "schema.sql").read_text()
    for table in (
        "agent_model_cards",
        "leetcode_tests",
        "system_design_questions",
        "candidates",
        "interviews",
        "interview_turns",
        "tool_call_logs",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql
    assert "cv_path" in sql


def test_seed_script_rejects_a_short_fetch(monkeypatch) -> None:
    monkeypatch.setattr(
        scrape_leetcode_problems.LeetCodeScraper,
        "fetch",
        lambda self, count=100: [],
    )
    assert scrape_leetcode_problems.main() == 1


def test_seed_script_writes_a_snapshot_without_postgres(monkeypatch, tmp_path: Path) -> None:
    problems = [sample_problem(number, "Easy") for number in range(1, 101)]
    saved: list[LeetCodeProblem] = []

    class Repository:
        def __init__(self, database_url: str) -> None:
            self.database_url = database_url

        def upsert_problem(self, problem: LeetCodeProblem) -> None:
            saved.append(problem)

    monkeypatch.setattr(scrape_leetcode_problems, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        scrape_leetcode_problems.LeetCodeScraper,
        "fetch",
        lambda self, count=100: problems,
    )
    monkeypatch.setattr(scrape_leetcode_problems, "PostgresRepository", Repository)
    monkeypatch.setattr(
        scrape_leetcode_problems,
        "load_settings",
        lambda: SimpleNamespace(database_url="postgresql://unit/db"),
    )
    assert scrape_leetcode_problems.main() == 0
    snapshot = json.loads((tmp_path / "data" / "leetcode_first_100.json").read_text())
    assert len(snapshot) == 100
    assert len(saved) == 100
    assert snapshot[0]["title_slug"] == "problem-1"
