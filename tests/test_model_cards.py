"""YAML model card validation."""

from pathlib import Path

import pytest

from tavus_cvi.domain.errors import ModelCardValidationError
from tavus_cvi.services.model_card_service import load_card_file

ROOT = Path(__file__).resolve().parents[1]


def test_charlie_card_loads_with_the_stock_face_and_ceiling() -> None:
    card = load_card_file(ROOT / "config" / "agents" / "charlie_interviewer.yaml")
    assert card.version == 9
    assert card.face_id == "rbb3ca3630f7"
    assert card.model == "tavus-gpt-5.6-terra"
    assert card.max_context_tokens == 5000
    assert card.max_concurrent_tool_calls == 2
    assert {item["name"] for item in card.guardrails_config} == {
        "safety_boundaries",
        "focus",
    }
    assert "end_call" in card.system_instructions


def test_compressor_card_uses_a_distinct_version() -> None:
    card = load_card_file(ROOT / "config" / "agents" / "context_compressor.yaml")
    assert card.version == 2
    assert card.model == "tavus-gemma-4"
    assert card.pipeline_mode == "chat"


def test_ceiling_above_5000_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text(
        """
version: 9
agent_name: bad
model: x
pipeline_mode: chat
face_id: n/a
voice_id: n/a
perception_model: none
turn_detection_model: none
max_concurrent_tool_calls: 1
max_context_tokens: 5001
temperature: 0.1
top_p: 1
context_template: hi
hardcoded_reminder_template: hi
system_instructions: hi
""",
        encoding="utf-8",
    )
    with pytest.raises(ModelCardValidationError):
        load_card_file(path)


def test_closing_and_retry_rules_use_the_system_end_call():
    card = load_card_file(ROOT / "config" / "agents" / "charlie_interviewer.yaml")
    prompt = card.system_instructions
    assert "up to five times" in prompt
    assert "how they thought the interview went" in prompt
    assert "what they might improve" in prompt
    assert "mark_interview_complete_v9" in prompt and "built-in end_call" in prompt
    assert any(tool["name"] == "mark_interview_complete_v9" for tool in card.tools_config)
    assert all(tool.get("delivery_timeout") == 45 for tool in card.tools_config)
