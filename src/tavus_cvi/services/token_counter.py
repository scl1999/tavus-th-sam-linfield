"""Token counting used by the context ceiling."""

from __future__ import annotations

import tiktoken

_ENCODER = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    """Count tokens with the cl100k encoding."""
    if not text:
        return 0
    return len(_ENCODER.encode(text, disallowed_special=()))
