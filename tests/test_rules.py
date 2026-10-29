"""Phase rules, freeze clock, and problem selection."""

import random

import pytest

from tavus_cvi.domain.entities import LeetCodeProblem
from tavus_cvi.domain.errors import InvalidPhaseTransitionError
from tavus_cvi.domain.rules import assert_transition, is_frozen, select_coding_pair


def _problem(number: int, difficulty: str) -> LeetCodeProblem:
    return LeetCodeProblem(
        challenge_number=number,
        title_slug=f"p{number}",
        question_title=f"Problem {number}",
        question="statement",
        difficulty_level=difficulty,
        hints=[],
        boilerplate_code={"python3": "pass"},
        id=number,
    )


def test_forward_phase_transitions_are_accepted() -> None:
    assert_transition("intro", "coding_easy")
    assert_transition("coding_easy", "coding_medium")
    assert_transition("coding_medium", "system_design")
    assert_transition("system_design", "completed")


def test_skipping_a_phase_is_rejected() -> None:
    with pytest.raises(InvalidPhaseTransitionError):
        assert_transition("intro", "system_design")


def test_rude_ending_is_allowed_from_any_open_phase() -> None:
    assert_transition("coding_easy", "terminated_rude")
    assert_transition("intro", "candidate_left")


def test_terminal_phase_cannot_move() -> None:
    with pytest.raises(InvalidPhaseTransitionError):
        assert_transition("completed", "coding_easy")


def test_workspace_freezes_at_55_minutes() -> None:
    assert is_frozen(3299) is False
    assert is_frozen(3300) is True


def test_select_coding_pair_returns_one_easy_and_one_medium() -> None:
    problems = [
        _problem(1, "Easy"),
        _problem(2, "Easy"),
        _problem(3, "Medium"),
        _problem(4, "Hard"),
    ]
    easy, medium = select_coding_pair(problems, random.Random(7))
    assert easy.difficulty_level == "Easy"
    assert medium.difficulty_level == "Medium"


def test_select_coding_pair_requires_both_difficulties() -> None:
    with pytest.raises(InvalidPhaseTransitionError):
        select_coding_pair([_problem(1, "Easy")], random.Random(1))
