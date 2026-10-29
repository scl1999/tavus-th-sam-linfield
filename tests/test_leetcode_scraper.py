"""LeetCode scraper parsing with a fake transport."""

from tavus_cvi.adapters.leetcode_scraper import LeetCodeScraper, strip_html


def test_strip_html_collapses_markup() -> None:
    assert strip_html("<p>Hello&nbsp;world</p>") == "Hello world"


def test_fetch_skips_paid_problems_and_keeps_complete_ones() -> None:
    def transport(query: str, variables: dict[str, object]) -> dict[str, object]:
        if "problemsetQuestionList" in query:
            return {
                "data": {
                    "problemsetQuestionList": {
                        "questions": [
                            {
                                "questionFrontendId": "1",
                                "title": "Paid",
                                "titleSlug": "paid",
                                "difficulty": "EASY",
                                "paidOnly": True,
                            },
                            {
                                "questionFrontendId": "2",
                                "title": "Add Two",
                                "titleSlug": "add-two",
                                "difficulty": "Easy",
                                "isPaidOnly": False,
                            },
                        ]
                    }
                }
            }
        return {
            "data": {
                "question": {
                    "questionFrontendId": "2",
                    "title": "Add Two",
                    "titleSlug": "add-two",
                    "content": "<p>Add numbers.</p>",
                    "difficulty": "Easy",
                    "hints": ["Start with the first digit."],
                    "isPaidOnly": False,
                    "codeSnippets": [
                        {"langSlug": "python3", "code": "class Solution:\n    pass"},
                        {"langSlug": "java", "code": "class Solution {}"},
                    ],
                }
            }
        }

    problems = LeetCodeScraper(transport).fetch(1)
    assert len(problems) == 1
    assert problems[0].challenge_number == 2
    assert problems[0].boilerplate_code["python3"].startswith("class Solution")
    assert "java" not in problems[0].boilerplate_code
    assert problems[0].question == "Add numbers."
    assert problems[0].difficulty_level == "Easy"


def test_fetch_stops_on_an_empty_page_and_normalizes_hard() -> None:
    def transport(query: str, variables: dict[str, object]) -> dict[str, object]:
        if "problemsetQuestionList" in query:
            if variables["skip"] == 50:
                return {"data": {"problemsetQuestionListV2": {"questions": []}}}
            return {
                "data": {
                    "problemsetQuestionListV2": {
                        "questions": [
                            {
                                "questionFrontendId": "9",
                                "title": "Hard One",
                                "titleSlug": "hard-one",
                                "difficulty": "HARD",
                            }
                        ]
                    }
                }
            }
        return {
            "data": {
                "question": {
                    "questionFrontendId": "9",
                    "title": "Hard One",
                    "titleSlug": "hard-one",
                    "content": "<p>Hard.</p>",
                    "difficulty": "HARD",
                    "hints": [],
                    "codeSnippets": [{"langSlug": "typescript", "code": "export {}"}],
                }
            }
        }

    problems = LeetCodeScraper(transport).fetch(5)
    assert len(problems) == 1
    assert problems[0].difficulty_level == "Hard"
    assert "typescript" in problems[0].boilerplate_code
