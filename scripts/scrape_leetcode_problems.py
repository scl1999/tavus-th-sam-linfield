"""Scrape the first 100 complete LeetCode problems into Postgres."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tavus_cvi.adapters.config import REPO_ROOT, load_settings
from tavus_cvi.adapters.leetcode_scraper import LeetCodeScraper
from tavus_cvi.adapters.postgres_repos import PostgresRepository

logger = logging.getLogger("scrape_leetcode")


def main() -> int:
    """Fetch problems, write a JSON snapshot, and upsert leetcode_tests."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    problems = LeetCodeScraper().fetch(100)
    if len(problems) < 100:
        logger.error("Expected 100 problems, fetched %s", len(problems))
        return 1
    snapshot = REPO_ROOT / "data" / "leetcode_first_100.json"
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_text(
        json.dumps(
            [
                {
                    "challenge_number": item.challenge_number,
                    "title_slug": item.title_slug,
                    "question_title": item.question_title,
                    "question": item.question,
                    "difficulty_level": item.difficulty_level,
                    "hints": item.hints,
                    "boilerplate_code": item.boilerplate_code,
                }
                for item in problems
            ],
            indent=2,
        ),
        encoding="utf-8",
    )
    repository = PostgresRepository(load_settings().database_url)
    for problem in problems:
        repository.upsert_problem(problem)
    logger.info("Stored %s problems in leetcode_tests", len(problems))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
