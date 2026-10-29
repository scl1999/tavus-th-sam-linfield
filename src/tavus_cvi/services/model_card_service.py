"""Load YAML agent cards and record each new checksum as a version."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import yaml

from tavus_cvi.adapters.postgres_repos import PostgresRepository
from tavus_cvi.adapters.runtime_repository import RuntimeRepository
from tavus_cvi.adapters.tavus_client import TavusClient
from tavus_cvi.domain.entities import AgentModelCard
from tavus_cvi.domain.errors import ModelCardValidationError

MAX_CONTEXT_TOKENS = 5000


def load_card_file(path: Path) -> AgentModelCard:
    """Parse one model card YAML file into an entity without a database id."""
    raw = path.read_text(encoding="utf-8")
    payload = yaml.safe_load(raw)
    if not isinstance(payload, dict):
        raise ModelCardValidationError(f"{path} is not a mapping")
    ceiling = int(payload["max_context_tokens"])
    if ceiling > MAX_CONTEXT_TOKENS:
        raise ModelCardValidationError("max_context_tokens cannot exceed 5000")
    version = int(payload["version"])
    if version < 1:
        raise ModelCardValidationError("version must be a positive integer")
    return AgentModelCard(
        version=version,
        agent_name=str(payload["agent_name"]),
        yaml_path=str(path),
        yaml_sha256=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        model=str(payload["model"]),
        pipeline_mode=str(payload["pipeline_mode"]),
        face_id=str(payload["face_id"]),
        voice_id=str(payload["voice_id"]),
        perception_model=str(payload["perception_model"]),
        turn_detection_model=str(payload["turn_detection_model"]),
        system_instructions=str(payload["system_instructions"]).strip(),
        context_template=str(payload["context_template"]).strip(),
        hardcoded_reminder_template=str(payload["hardcoded_reminder_template"]).strip(),
        guardrails_config=list(payload.get("guardrails") or []),
        tools_config=list(payload.get("tools") or []),
        objectives=list(payload.get("objectives") or []),
        conversational_flow=dict(payload.get("conversational_flow") or {}),
        max_concurrent_tool_calls=int(payload["max_concurrent_tool_calls"]),
        max_context_tokens=ceiling,
        temperature=_optional_float(payload.get("temperature")),
        top_p=_optional_float(payload.get("top_p")),
    )


class ModelCardService:
    """Sync YAML cards into agent_model_cards and provision Charlie on Tavus."""

    def __init__(
        self,
        repository: PostgresRepository,
        tavus: TavusClient | None,
        callback_base_url: str = "",
        callback_secret: str = "",
    ) -> None:
        self._repository = repository
        self._tavus = tavus
        self._callback_base_url = callback_base_url
        self._callback_secret = callback_secret

    def sync_directory(self, directory: Path) -> list[AgentModelCard]:
        """Insert a row for every YAML file whose checksum is new."""
        cards: list[AgentModelCard] = []
        for path in sorted(directory.glob("*.yaml")):
            card = load_card_file(path)
            existing = self._repository.find_card_by_sha(card.yaml_sha256)
            if existing is None:
                self._repository.insert_card(card)
            else:
                card = existing
            needs_pal = (
                card.agent_name == "charlie_interviewer"
                and self._tavus is not None
                and not card.tavus_pal_id
            )
            if needs_pal:
                pal_id = self._provision(card)
                self._repository.set_pal_id(card.version, pal_id)
                card = AgentModelCard(**{**card.__dict__, "tavus_pal_id": pal_id})
            if card.agent_name == "charlie_interviewer" and self._tavus and card.tavus_pal_id:
                self._bind_delivery(card)
            cards.append(card)
        return cards

    def binding_hash(self) -> str:
        return hashlib.sha256(
            (self._callback_base_url.rstrip("/") + "\n" + self._callback_secret).encode()
        ).hexdigest()

    def _bind_delivery(self, card: AgentModelCard) -> None:
        if not isinstance(self._repository, RuntimeRepository):
            return
        with self._repository._connect() as connection:
            binding = connection.execute(
                "SELECT binding_hash FROM model_card_delivery WHERE version=%s",
                (card.version,),
            ).fetchone()
        if binding and binding["binding_hash"] == self.binding_hash():
            return
        assert self._tavus and card.tavus_pal_id
        # Only version-namespaced tools belonging to this card are rebound.
        ids = [self._tavus.create_tool(self._delivery_tool(tool)) for tool in card.tools_config]
        self._tavus.attach_tools(card.tavus_pal_id, ids)
        with self._repository._connect() as connection:
            connection.execute(
                "INSERT INTO model_card_delivery(version,binding_hash) VALUES (%s,%s) "
                "ON CONFLICT(version) DO UPDATE "
                "SET binding_hash=excluded.binding_hash,bound_at=now()",
                (card.version, self.binding_hash()),
            )

    def _delivery_tool(self, tool: dict[str, Any]) -> dict[str, Any]:
        if not self._callback_base_url.startswith("https://") or not self._callback_secret:
            raise ModelCardValidationError("Signed callback delivery must be configured")
        return {
            **tool,
            "delivery": {
                "app_message": False,
                "api": {
                    "url": self._callback_base_url.rstrip("/") + "/tavus/tools",
                    "method": "POST",
                    "timeout": tool.get("delivery_timeout", 10),
                    "auth": {"type": "hmac", "secret": self._callback_secret},
                },
            },
            "on_call": "silent",
        }

    def _provision(self, card: AgentModelCard) -> str:
        if card.tools_config:
            self._delivery_tool(card.tools_config[0])
        voice_id = _resolve_voice(self._tavus, card.voice_id) if self._tavus else None
        guardrail_ids = [
            self._tavus.create_guardrail(f"{item['name']}_v{card.version}", item["prompt"])
            for item in card.guardrails_config
            if self._tavus is not None
        ]
        objectives_id = None
        if card.objectives and self._tavus is not None:
            objectives_id = self._tavus.create_objectives(card.objectives)
        body: dict[str, Any] = {
            "pal_name": "Charlie Interviewer",
            "system_prompt": card.system_instructions,
            "pipeline_mode": card.pipeline_mode,
            "default_face_id": card.face_id,
            "guardrail_ids": guardrail_ids,
            "layers": {
                "llm": {
                    "model": card.model,
                    "speculative_inference": True,
                    "extra_body": {
                        "temperature": card.temperature,
                        "top_p": card.top_p,
                    },
                },
                "perception": {
                    "perception_model": card.perception_model,
                },
                "conversational_flow": {
                    "turn_detection_model": card.turn_detection_model,
                    **card.conversational_flow,
                },
            },
        }
        if voice_id:
            body["layers"]["tts"] = {"tts_engine": "tavus-auto", "voice_id": voice_id}
        if objectives_id:
            body["objectives_id"] = objectives_id
        assert self._tavus is not None
        pal_id = self._tavus.create_pal(body)
        tool_ids = [
            self._tavus.create_tool(self._delivery_tool(tool)) for tool in card.tools_config
        ]
        self._tavus.attach_tools(pal_id, tool_ids)
        return pal_id


def _resolve_voice(client: TavusClient, requested: str) -> str | None:
    if requested.startswith("v") and len(requested) > 4:
        return requested
    for voice in client.list_voices():
        name = str(voice.get("voice_name") or voice.get("name") or "")
        if requested.lower() in name.lower():
            voice_id = voice.get("voice_id") or voice.get("id")
            if voice_id:
                return str(voice_id)
    return None


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        raise ModelCardValidationError("numeric model card fields must be numbers")
    return float(value)
