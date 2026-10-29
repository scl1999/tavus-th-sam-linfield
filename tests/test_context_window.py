"""Context ceiling, diagram summary, and code diff."""

from tavus_cvi.domain.context_window import (
    MAX_CONTEXT_TOKENS,
    assemble_context,
    code_delta,
    summarize_drawio,
    trim_to_tokens,
)


def _count(text: str) -> int:
    return len(text.split())


def test_trim_returns_empty_when_limit_is_zero() -> None:
    assert trim_to_tokens("hello world", 0, _count) == ""


def test_assemble_context_never_exceeds_the_hard_ceiling() -> None:
    context = assemble_context(
        system_instructions="system " * 5000,
        rules="rules " * 5000,
        workspace="workspace " * 5000,
        digest="digest " * 5000,
        hot_window="hot " * 5000,
        count_tokens=_count,
        ceiling=5000,
    )
    assert _count(context) <= MAX_CONTEXT_TOKENS


def test_requested_ceiling_above_5000_is_clamped() -> None:
    context = assemble_context(
        system_instructions="one two three",
        rules="four",
        workspace="five",
        digest="six",
        hot_window="seven",
        count_tokens=_count,
        ceiling=9000,
    )
    assert _count(context) <= 5000
    assert "one" in context


def test_summarize_drawio_renders_edges() -> None:
    xml = """
    <mxGraphModel>
      <root>
        <mxCell id="1" value="Client"/>
        <mxCell id="2" value="API"/>
        <mxCell id="3" value="" source="1" target="2"/>
      </root>
    </mxGraphModel>
    """
    assert summarize_drawio(xml) == "[Client] -> [API]"


def test_summarize_drawio_rejects_broken_xml() -> None:
    assert summarize_drawio("<not-xml") == "Unreadable diagram."


def test_code_delta_is_a_unified_diff() -> None:
    rendered = code_delta("a = 1", "a = 2")
    assert "a = 1" in rendered
    assert "a = 2" in rendered
