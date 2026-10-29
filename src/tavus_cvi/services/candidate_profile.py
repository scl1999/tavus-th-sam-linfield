"""The single local candidate and the CV text Charlie should know."""

from __future__ import annotations

import subprocess
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from tavus_cvi.adapters.config import REPO_ROOT
from tavus_cvi.adapters.postgres_repos import PostgresRepository
from tavus_cvi.domain.context_window import DIGEST_TOKEN_BUDGET, HOT_TOKEN_BUDGET, trim_to_tokens
from tavus_cvi.domain.entities import Candidate
from tavus_cvi.services.token_counter import count_tokens

SEEDED_EMAIL = "sam.linfield@ecoze.app"
SEEDED_NAME = "Sam Linfield"
SEEDED_ROLE = "Senior AI Engineer"
SEEDED_ID = uuid5(NAMESPACE_URL, SEEDED_EMAIL)


def cv_file() -> Path:
    """Absolute path of the CV stored with this project."""
    return REPO_ROOT / "documentation" / "SCL CV.pdf"


def greeting(first_name: str) -> str:
    """Spoken opening. Charlie must identify as an AI."""
    return f"Hi {first_name}, I'm Charlie, an AI interviewer. Are you ready to start the interview?"


def ensure_seeded_candidate(repository: PostgresRepository) -> Candidate:
    """Insert Sam Linfield, including the local CV path, if the row is missing."""
    repository.ensure_cv_column()
    candidate = Candidate(
        id=SEEDED_ID,
        full_name=SEEDED_NAME,
        email=SEEDED_EMAIL,
        target_role=SEEDED_ROLE,
        cv_path=str(cv_file()),
    )
    repository.insert_candidate(candidate)
    stored = repository.candidate_by_email(SEEDED_EMAIL)
    return stored or candidate


def read_cv_text(path: Path) -> str:
    """Extract plain text from the CV. An unreadable file yields an empty string."""
    if not path.is_file():
        return ""
    try:
        completed = subprocess.run(
            ["pdftotext", "-layout", str(path), "-"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def cv_sections(cv_text: str) -> tuple[str, str]:
    """Split CV text across the hot window and the rolling digest budgets."""
    hot = trim_to_tokens(cv_text, HOT_TOKEN_BUDGET, count_tokens)
    digest = trim_to_tokens(cv_text[len(hot) :], DIGEST_TOKEN_BUDGET, count_tokens)
    return hot, digest


def first_name(full_name: str) -> str:
    """Return the given name used in the welcome line."""
    return full_name.split()[0] if full_name.strip() else "there"


def candidate_id() -> UUID:
    """Stable id for the seeded candidate."""
    return SEEDED_ID
