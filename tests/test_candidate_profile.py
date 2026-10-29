"""Seeded candidate greeting and CV context splitting."""

from pathlib import Path

from tavus_cvi.services.candidate_profile import (
    SEEDED_ID,
    candidate_id,
    cv_file,
    cv_sections,
    ensure_seeded_candidate,
    first_name,
    greeting,
    read_cv_text,
)
from tests.support import InMemoryStore


def test_greeting_identifies_charlie_as_an_ai() -> None:
    spoken = greeting("Sam")
    assert spoken.startswith("Hi Sam,")
    assert "AI" in spoken
    assert "ready" in spoken


def test_first_name_uses_the_given_name() -> None:
    assert first_name("Sam Linfield") == "Sam"
    assert first_name("  ") == "there"


def test_missing_or_unreadable_cv_yields_empty_text(tmp_path: Path) -> None:
    assert read_cv_text(tmp_path / "missing.pdf") == ""
    broken = tmp_path / "notes.pdf"
    broken.write_text("not a pdf", encoding="utf-8")
    assert read_cv_text(broken) == ""
    assert candidate_id() == SEEDED_ID


def test_seeded_candidate_stores_the_cv_location() -> None:
    store = InMemoryStore()
    candidate = ensure_seeded_candidate(store)
    assert store.cv_column is True
    assert candidate.full_name == "Sam Linfield"
    assert candidate.target_role == "Senior AI Engineer"
    assert candidate.cv_path == str(cv_file())


def test_cv_sections_keep_the_start_and_do_not_repeat_it() -> None:
    cv = "alpha " * 4000
    hot, digest = cv_sections(cv)
    assert cv.startswith(hot)
    assert cv[len(hot) :].startswith(digest[:20])
    assert len(hot) + len(digest) < len(cv)
