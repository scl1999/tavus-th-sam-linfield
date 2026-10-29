"""Deterministic workspace summaries and the 5,000-token context ceiling."""

from __future__ import annotations

import difflib
import xml.etree.ElementTree as ElementTree
from collections.abc import Callable

MAX_CONTEXT_TOKENS = 5000
SYSTEM_TOKEN_BUDGET = 1500
RULES_TOKEN_BUDGET = 1000
WORKSPACE_TOKEN_BUDGET = 1000
DIGEST_TOKEN_BUDGET = 800
HOT_TOKEN_BUDGET = 1000

TokenCounter = Callable[[str], int]


def trim_to_tokens(text: str, limit: int, count_tokens: TokenCounter) -> str:
    """Shorten text until it fits the token limit."""
    if limit < 1:
        return ""
    if count_tokens(text) <= limit:
        return text
    low = 0
    high = len(text)
    best = ""
    while low <= high:
        mid = (low + high) // 2
        candidate = text[:mid]
        if count_tokens(candidate) <= limit:
            best = candidate
            low = mid + 1
        else:
            high = mid - 1
    return best


def summarize_drawio(xml_text: str) -> str:
    """Turn draw.io XML into a short node-and-edge description."""
    if not xml_text.strip():
        return "Empty diagram."
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return "Unreadable diagram."
    labels: dict[str, str] = {}
    edges: list[tuple[str, str]] = []
    for cell in root.iter("mxCell"):
        cell_id = cell.attrib.get("id", "")
        value = cell.attrib.get("value", "").strip()
        source = cell.attrib.get("source")
        target = cell.attrib.get("target")
        if source and target:
            edges.append((source, target))
        elif value:
            labels[cell_id] = value
    if edges:
        rendered = [
            f"[{labels.get(source, source)}] -> [{labels.get(target, target)}]"
            for source, target in edges
        ]
        return "\n".join(rendered)
    if labels:
        return "Nodes: " + ", ".join(labels.values())
    return "Empty diagram."


def code_delta(previous: str, current: str) -> str:
    """Return a unified diff, or the current buffer when there is no baseline."""
    if previous == current:
        return current[-2000:]
    diff = difflib.unified_diff(
        previous.splitlines(),
        current.splitlines(),
        fromfile="previous",
        tofile="current",
        lineterm="",
    )
    rendered = "\n".join(diff)
    return rendered or current[-2000:]


def assemble_context(
    *,
    system_instructions: str,
    rules: str,
    workspace: str,
    digest: str,
    hot_window: str,
    count_tokens: TokenCounter,
    ceiling: int = MAX_CONTEXT_TOKENS,
) -> str:
    """Fit every context section into its budget and the hard ceiling."""
    if ceiling > MAX_CONTEXT_TOKENS:
        ceiling = MAX_CONTEXT_TOKENS
    system = trim_to_tokens(system_instructions, min(SYSTEM_TOKEN_BUDGET, ceiling), count_tokens)
    remaining = ceiling - count_tokens(system)
    sections = [
        ("Rules", rules, RULES_TOKEN_BUDGET),
        ("Workspace", workspace, WORKSPACE_TOKEN_BUDGET),
        ("Digest", digest, DIGEST_TOKEN_BUDGET),
        ("Recent", hot_window, HOT_TOKEN_BUDGET),
    ]
    parts = [system]
    for label, text, budget in sections:
        allowance = min(budget, remaining)
        piece = trim_to_tokens(f"{label}:\n{text}", allowance, count_tokens)
        if not piece:
            continue
        parts.append(piece)
        remaining -= count_tokens(piece)
        if remaining <= 0:
            break
    combined = "\n\n".join(parts)
    return trim_to_tokens(combined, ceiling, count_tokens)
