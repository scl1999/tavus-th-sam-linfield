"""Click through a Tavus docs sidebar and save each copied page.

The script opens the docs in a desktop browser, expands collapsed sidebar groups,
clicks every page link under a path prefix, clicks Copy page, and appends that
markdown to the output file. Copy page fetches the page markdown and writes it
to the clipboard; the script reads the clipboard and falls back to the markdown
response from that click when the clipboard API is unavailable.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import (
    Browser,
    Error as PlaywrightError,
    Page,
    Playwright,
    sync_playwright,
)

START_URL = "https://docs.tavus.io/api-reference/overview"
API_PATH_PREFIX = "/api-reference/"
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "documentation" / "tavus_api_docs.txt"
PAGE_SEPARATOR = (
    "\n\n"
    "============================================\n"
    "============================================\n"
    "============================================\n"
    "\n"
)
DESKTOP_VIEWPORT = {"width": 1440, "height": 900}
logger = logging.getLogger("scrape_tavus_api_docs")


class DocsScrapeError(Exception):
    """Raised when a sidebar page cannot be opened or copied."""


def unique_in_order(values: list[str]) -> list[str]:
    """Return values with duplicates removed, preserving first-seen order."""
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def join_page_markdown(pages: list[str]) -> str:
    """Join copied page markdown with the required separator between pages."""
    if not pages:
        return ""
    blocks = [page.strip() for page in pages]
    return f"{PAGE_SEPARATOR.join(blocks)}\n"


def _expand_sidebar(page: Page) -> None:
    for _ in range(8):
        collapsed = page.locator("#sidebar button[aria-expanded='false']")
        count = collapsed.count()
        if count == 0:
            return
        for _index in range(count):
            collapsed.nth(0).click()
            page.wait_for_timeout(150)
    remaining = page.locator("#sidebar button[aria-expanded='false']").count()
    if remaining:
        raise DocsScrapeError(f"{remaining} sidebar groups stayed collapsed")


def filter_sidebar_hrefs(hrefs: list[str], path_prefix: str) -> list[str]:
    """Keep sidebar paths under path_prefix, in first-seen order."""
    matching = [href for href in hrefs if href.startswith(path_prefix)]
    return unique_in_order(matching)


def _sidebar_hrefs(page: Page, path_prefix: str) -> list[str]:
    hrefs = page.locator("#sidebar a[href]").evaluate_all(
        """(anchors) => anchors.map((anchor) => anchor.getAttribute('href'))"""
    )
    cleaned = [href for href in hrefs if isinstance(href, str) and href]
    return filter_sidebar_hrefs(cleaned, path_prefix)


def collect_sidebar_pages(
    page: Page,
    start_url: str = START_URL,
    path_prefix: str = API_PATH_PREFIX,
) -> list[str]:
    """Expand the docs sidebar and return page paths in menu order."""
    page.goto(start_url, wait_until="domcontentloaded")
    page.locator("#sidebar").wait_for(state="visible", timeout=30_000)
    _expand_sidebar(page)
    hrefs = _sidebar_hrefs(page, path_prefix)
    if not hrefs:
        raise DocsScrapeError(f"The sidebar did not contain any pages under {path_prefix}")
    return hrefs


def _open_sidebar_page(page: Page, href: str) -> None:
    _expand_sidebar(page)
    link = page.locator(f"#sidebar a[href='{href}']").first
    link.wait_for(state="visible", timeout=15_000)
    link.scroll_into_view_if_needed()
    link.click()
    page.wait_for_url(f"**{href}", timeout=20_000)
    page.locator("#page-context-menu-button").first.wait_for(state="visible", timeout=20_000)
    page.wait_for_function(
        """() => {
            const button = [...document.querySelectorAll('#page-context-menu-button')]
                .find((node) => node.getClientRects().length > 0);
            return Boolean(button && !button.disabled);
        }""",
        timeout=15_000,
    )


def _read_clipboard(page: Page) -> str:
    clipboard = page.evaluate(
        """() => navigator.clipboard.readText().catch(() => '')"""
    )
    if not isinstance(clipboard, str):
        return ""
    return clipboard.strip()


def markdown_response_matches_page(page_url: str, response_url: str) -> bool:
    page_path = urlparse(page_url).path.rstrip("/")
    response_path = urlparse(response_url).path.removesuffix(".md").rstrip("/")
    return response_url.endswith(".md") and response_path == page_path


def copy_current_page(page: Page) -> str:
    """Click Copy page and return the markdown that click copied."""
    button = page.locator("#page-context-menu-button:visible").first
    current_url = page.url
    with page.expect_response(
        lambda response: response.ok
        and markdown_response_matches_page(current_url, response.url),
        timeout=20_000,
    ) as response_info:
        button.click()
    fetched = response_info.value.text().strip()
    if not fetched:
        raise DocsScrapeError(f"Copy page returned empty markdown for {page.url}")

    deadline = time.monotonic() + 5
    clipboard = ""
    while time.monotonic() < deadline:
        clipboard = _read_clipboard(page)
        if clipboard == fetched:
            return clipboard
        page.wait_for_timeout(200)

    if clipboard:
        logger.warning(
            "Clipboard did not match the Copy page response for %s; saving the response body",
            page.url,
        )
    else:
        logger.info(
            "Clipboard was empty for %s; saving the markdown Copy page fetched",
            page.url,
        )
    return fetched


def scrape_api_reference(
    page: Page,
    limit: int | None = None,
    start_url: str = START_URL,
    path_prefix: str = API_PATH_PREFIX,
) -> list[str]:
    """Click each sidebar page and Copy page, returning markdown in menu order."""
    hrefs = collect_sidebar_pages(page, start_url=start_url, path_prefix=path_prefix)
    if limit is not None:
        hrefs = hrefs[:limit]
    pages: list[str] = []
    for index, href in enumerate(hrefs, start=1):
        logger.info("Copying %s/%s %s", index, len(hrefs), href)
        last_error: Exception | None = None
        for attempt in range(1, 3):
            try:
                _open_sidebar_page(page, href)
                pages.append(copy_current_page(page))
                last_error = None
                break
            except (DocsScrapeError, PlaywrightError) as exc:
                last_error = exc
                logger.warning("Attempt %s failed for %s: %s", attempt, href, exc)
                page.goto(start_url, wait_until="domcontentloaded")
                page.locator("#sidebar").wait_for(state="visible", timeout=30_000)
        if last_error is not None:
            raise DocsScrapeError(f"Failed to copy {href}") from last_error
    return pages


def write_docs(pages: list[str], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(join_page_markdown(pages), encoding="utf-8")


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Destination file (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--start-url",
        default=START_URL,
        help=f"Docs page to open before walking the sidebar (default: {START_URL})",
    )
    parser.add_argument(
        "--path-prefix",
        default=API_PATH_PREFIX,
        help=f"Sidebar path prefix to copy (default: {API_PATH_PREFIX})",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Copy only the first N sidebar pages. Useful for a smoke test.",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Show the browser window instead of running headless.",
    )
    return parser.parse_args(argv)


def _launch(playwright: Playwright, headed: bool) -> Browser:
    return playwright.chromium.launch(headless=not headed)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    if args.limit is not None and args.limit < 1:
        logger.error("--limit must be at least 1")
        return 2
    if not args.path_prefix.startswith("/") or not args.path_prefix.endswith("/"):
        logger.error("--path-prefix must start and end with /")
        return 2

    with sync_playwright() as playwright:
        browser = _launch(playwright, headed=args.headed)
        context = browser.new_context(
            viewport=DESKTOP_VIEWPORT,
            permissions=["clipboard-read", "clipboard-write"],
        )
        page = context.new_page()
        try:
            pages = scrape_api_reference(
                page,
                limit=args.limit,
                start_url=args.start_url,
                path_prefix=args.path_prefix,
            )
        finally:
            context.close()
            browser.close()

    write_docs(pages, args.output)
    logger.info("Wrote %s pages to %s", len(pages), args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
