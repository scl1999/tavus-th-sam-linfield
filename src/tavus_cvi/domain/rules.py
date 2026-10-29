"""Interview phase, problem selection, and tool concurrency rules."""

from __future__ import annotations

import random
import threading
from collections.abc import Sequence

from tavus_cvi.domain.entities import LeetCodeProblem
from tavus_cvi.domain.errors import ConcurrencyLimitExceededError, InvalidPhaseTransitionError

FREEZE_AFTER_SECONDS = 3300
CALL_LIMIT_SECONDS = 3600

_FORWARD: dict[str, str] = {
    "intro": "coding_easy",
    "coding_easy": "coding_medium",
    "coding_medium": "system_design",
    "system_design": "completed",
}
_TERMINAL = {"completed", "terminated_rude", "candidate_left"}


def assert_transition(current: str, target: str) -> None:
    """Allow the next phase, a rude ending, or the candidate leaving."""
    if current in _TERMINAL:
        raise InvalidPhaseTransitionError(f"Interview is already {current}")
    if target in {"terminated_rude", "candidate_left"}:
        return
    if _FORWARD.get(current) != target:
        raise InvalidPhaseTransitionError(f"Cannot move from {current} to {target}")


def is_frozen(elapsed_seconds: int) -> bool:
    """Lock the editor, terminal, and diagram at 55 minutes."""
    return elapsed_seconds >= FREEZE_AFTER_SECONDS


PHASE_DEADLINES = {"intro": 300, "coding_easy": 900, "coding_medium": 1500, "system_design": 3300}


def timed_phase(current: str, elapsed: int) -> str:
    """Enforce latest phase deadlines, preserving early forward transitions."""
    if current in _TERMINAL:
        return current
    if elapsed >= CALL_LIMIT_SECONDS:
        return "completed"
    order = ["intro", "coding_easy", "coding_medium", "system_design"]
    due = "intro"
    for index, phase in enumerate(order[:-1]):
        if elapsed >= PHASE_DEADLINES[phase]:
            due = order[index + 1]
    return order[max(order.index(current), order.index(due))]


def phase_deadline(phase: str, elapsed: int) -> int:
    """At the technical cutoff reserve the rest of the hour for Q&A."""
    return (
        CALL_LIMIT_SECONDS if is_frozen(elapsed) else PHASE_DEADLINES.get(phase, CALL_LIMIT_SECONDS)
    )


def select_coding_pair(
    problems: Sequence[LeetCodeProblem],
    rng: random.Random | None = None,
) -> tuple[LeetCodeProblem, LeetCodeProblem]:
    """Pick one easy problem and one different medium problem."""
    generator = rng or random.Random()
    easy = [item for item in problems if item.difficulty_level == "Easy"]
    medium = [item for item in problems if item.difficulty_level == "Medium"]
    if not easy or not medium:
        raise InvalidPhaseTransitionError("Need at least one Easy and one Medium problem")
    return generator.choice(easy), generator.choice(medium)


class ToolCallConcurrencyLimiter:
    """Caps how many tool calls may be in flight for one interview."""

    def __init__(self, max_calls: int) -> None:
        if max_calls < 1:
            raise ConcurrencyLimitExceededError("max_concurrent_tool_calls must be at least 1")
        self.max_calls = max_calls
        self.active = 0
        self._lock = threading.Lock()

    def try_acquire(self) -> int:
        """Reserve a slot and return the in-flight count including this call."""
        with self._lock:
            if self.active >= self.max_calls:
                raise ConcurrencyLimitExceededError(f"Concurrent tool limit is {self.max_calls}")
            self.active += 1
            return self.active

    def release(self) -> None:
        """Free one in-flight slot."""
        with self._lock:
            if self.active > 0:
                self.active -= 1
