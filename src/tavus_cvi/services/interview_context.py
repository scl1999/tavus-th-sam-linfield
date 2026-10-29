"""Server-only problem context; candidate views never include hint material."""

from tavus_cvi.adapters.postgres_repos import PostgresRepository


def active_problem_context(status: dict[str, object], repository: PostgresRepository) -> str:
    """Provide the active statement and private hints for request-only assistance."""
    interview = status.get("interview")
    phase = interview.get("current_phase") if isinstance(interview, dict) else ""
    if phase == "intro":
        return "No problem is open yet. Complete introductions briefly."
    key = (
        "system_design"
        if phase == "system_design"
        else ("medium" if phase == "coding_medium" else "easy")
    )
    problem = status.get(key)
    if not isinstance(problem, dict):
        return ""
    text = (
        str(problem.get("question_title") or "")
        + "\n"
        + str(problem.get("question") or problem.get("problem_statement") or "")
    )
    problem_id = problem.get("id")
    if key != "system_design" and isinstance(problem_id, int):
        stored = repository.get_problem(problem_id)
        if stored and stored.hints:
            text += "\nPrivate hint reference; only offer one minimal conceptual hint if asked. "
            text += "Never read out a solution from these notes:\n" + "\n".join(stored.hints)
    return text
