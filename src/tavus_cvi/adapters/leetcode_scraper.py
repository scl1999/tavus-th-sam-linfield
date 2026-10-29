"""Fetch public LeetCode problems through the GraphQL endpoint."""

from __future__ import annotations

import html
import re
from collections.abc import Callable

import httpx

from tavus_cvi.domain.entities import LeetCodeProblem

LIST_QUERY = """
query problemsetQuestionListV2($limit: Int, $skip: Int) {
  problemsetQuestionListV2(categorySlug: "", limit: $limit, skip: $skip) {
    questions {
      questionFrontendId
      title
      titleSlug
      difficulty
      paidOnly
    }
  }
}
"""

DETAIL_QUERY = """
query questionData($titleSlug: String!) {
  question(titleSlug: $titleSlug) {
    questionFrontendId
    title
    titleSlug
    content
    difficulty
    hints
    isPaidOnly
    codeSnippets { langSlug code }
  }
}
"""

Transport = Callable[[str, dict[str, object]], dict[str, object]]


def strip_html(value: str) -> str:
    """Convert a LeetCode HTML statement into plain text."""
    text = re.sub(r"<(script|style)\b[^>]*>[\s\S]*?</\1>", "", value, flags=re.I)
    text = re.sub(r"</(?:p|pre|ul|ol|h[1-6])>|<br\s*/?>", "\n\n", text, flags=re.I)
    text = re.sub(r"<li\b[^>]*>", "\n• ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text).replace("\xa0", " ")
    text = re.sub(r"[^\S\n]+", " ", text)
    return re.sub(r"\n[ \n]+", "\n\n", text).strip()


class LeetCodeScraper:
    """Collect complete free problems until the requested count is reached."""

    def __init__(self, transport: Transport | None = None) -> None:
        self._transport = transport or _http_transport

    def fetch(self, count: int = 100) -> list[LeetCodeProblem]:
        """Return `count` problems that include a statement and starter code."""
        collected: list[LeetCodeProblem] = []
        skip = 0
        while len(collected) < count:
            page = self._transport(LIST_QUERY, {"limit": 50, "skip": skip})
            questions = _questions(page)
            if not questions:
                break
            for item in questions:
                if item.get("paidOnly") or item.get("isPaidOnly"):
                    continue
                slug = str(item["titleSlug"])
                detail_payload = self._transport(DETAIL_QUERY, {"titleSlug": slug})
                question = _question(detail_payload)
                if not question or question.get("isPaidOnly") or not question.get("content"):
                    continue
                problem = _to_problem(question)
                if not problem.question or not problem.boilerplate_code:
                    continue
                collected.append(problem)
                if len(collected) == count:
                    break
            skip += 50
        return collected


def _http_transport(query: str, variables: dict[str, object]) -> dict[str, object]:
    response = httpx.post(
        "https://leetcode.com/graphql",
        json={"query": query, "variables": variables},
        headers={
            "Content-Type": "application/json",
            "Referer": "https://leetcode.com/problemset/",
            "User-Agent": "Mozilla/5.0",
        },
        timeout=30.0,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        return {}
    return payload


def _normalize_difficulty(value: object) -> str:
    text = str(value or "").strip().lower()
    return {"easy": "Easy", "medium": "Medium", "hard": "Hard"}.get(text, str(value))


def _questions(payload: dict[str, object]) -> list[dict[str, object]]:
    data = payload.get("data")
    if not isinstance(data, dict):
        return []
    listing = data.get("problemsetQuestionListV2") or data.get("problemsetQuestionList")
    if not isinstance(listing, dict):
        return []
    questions = listing.get("questions")
    if not isinstance(questions, list):
        return []
    return [item for item in questions if isinstance(item, dict)]


def _question(payload: dict[str, object]) -> dict[str, object] | None:
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    question = data.get("question")
    if not isinstance(question, dict):
        return None
    return question


def _to_problem(question: dict[str, object]) -> LeetCodeProblem:
    snippets = question.get("codeSnippets") or []
    boilerplate: dict[str, str] = {}
    if isinstance(snippets, list):
        for snippet in snippets:
            if not isinstance(snippet, dict):
                continue
            lang = str(snippet.get("langSlug") or "")
            code = str(snippet.get("code") or "")
            if lang in {"python3", "typescript"} and code:
                boilerplate[lang] = code
    hints_raw = question.get("hints") or []
    hints = [str(item) for item in hints_raw] if isinstance(hints_raw, list) else []
    return LeetCodeProblem(
        challenge_number=int(str(question.get("questionFrontendId"))),
        title_slug=str(question.get("titleSlug")),
        question_title=str(question.get("title")),
        question=strip_html(str(question.get("content") or "")),
        difficulty_level=_normalize_difficulty(question.get("difficulty")),
        hints=hints,
        boilerplate_code=boilerplate,
    )
