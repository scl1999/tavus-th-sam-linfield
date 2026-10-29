"""Tests for assembling copied Tavus docs pages into one file."""

from scrape_tavus_api_docs import (
    PAGE_SEPARATOR,
    filter_sidebar_hrefs,
    markdown_response_matches_page,
    join_page_markdown,
    unique_in_order,
)


def test_join_page_markdown_places_separator_between_pages() -> None:
    document = join_page_markdown(["# Overview\n\nHello", "# Authentication\n\nWorld"])

    assert document == (
        "# Overview\n\nHello"
        f"{PAGE_SEPARATOR}"
        "# Authentication\n\nWorld\n"
    )
    assert document.count(PAGE_SEPARATOR) == 1


def test_join_page_markdown_omits_separator_for_a_single_page() -> None:
    document = join_page_markdown(["  # Overview\n\nHello\n"])

    assert document == "# Overview\n\nHello\n"
    assert "====" not in document


def test_join_page_markdown_returns_empty_string_for_no_pages() -> None:
    assert join_page_markdown([]) == ""


def test_markdown_response_must_match_the_open_page() -> None:
    page_url = "https://docs.tavus.io/api-reference/overview"
    assert markdown_response_matches_page(
        page_url,
        "https://docs.tavus.io/api-reference/overview.md",
    )
    assert not markdown_response_matches_page(
        page_url,
        "https://docs.tavus.io/api-reference/authentication.md",
    )


def test_filter_sidebar_hrefs_keeps_only_the_requested_prefix() -> None:
    assert filter_sidebar_hrefs(
        [
            "/sections/introduction",
            "https://github.com/Tavus-Engineering/tavus-examples",
            "/api-reference/overview",
            "/sections/introduction",
            "/sections/models",
        ],
        "/sections/",
    ) == ["/sections/introduction", "/sections/models"]


def test_unique_in_order_keeps_first_occurrence() -> None:
    assert unique_in_order(
        [
            "/api-reference/overview",
            "/api-reference/authentication",
            "/api-reference/overview",
        ]
    ) == [
        "/api-reference/overview",
        "/api-reference/authentication",
    ]
