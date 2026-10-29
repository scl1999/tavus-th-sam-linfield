"""HTTP client for the Tavus CVI API."""

from __future__ import annotations

from typing import Any

import httpx

from tavus_cvi.domain.errors import TavusIntegrationError


class TavusClient:
    """Calls Tavus with the server-side API key."""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"x-api-key": api_key},
            timeout=30.0,
            transport=transport,
        )

    def close(self) -> None:
        """Close the underlying connection pool."""
        self._client.close()

    def request(self, method: str, path: str, json_body: Any | None = None) -> Any:
        """Send one JSON request and return the decoded body."""
        response = self._client.request(method, path, json=json_body)
        if response.status_code >= 400:
            detail = f"{method} {path} failed: {response.status_code} {response.text}"
            raise TavusIntegrationError(detail)
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    def list_voices(self) -> list[dict[str, Any]]:
        """Return voice records from the first list page."""
        payload = self.request("GET", "/v2/voices")
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            data = payload.get("data") or payload.get("voices") or []
            if isinstance(data, list):
                return data
        return []

    def list_guardrails(self) -> list[dict[str, Any]]:
        """Return guardrail records from the first list page."""
        return _records(self.request("GET", "/v2/guardrails"), "guardrails")

    def create_guardrail(self, name: str, prompt: str) -> str:
        """Create one guardrail and return its id."""
        body = {"guardrail_name": name, "guardrail_prompt": prompt, "modality": "verbal"}
        try:
            payload = self.request("POST", "/v2/guardrails", body)
        except TavusIntegrationError:
            payload = _match_named(self.list_guardrails(), "guardrail_name", name)
        return _resource_id(payload, "uuid", "guardrail_id")

    def create_objectives(self, objectives: list[dict[str, Any]]) -> str:
        """Create an objective chain and return its id."""
        data = [
            {
                "objective_name": item["name"],
                "objective_prompt": item["prompt"],
                "confirmation_mode": "auto",
                "modality": "verbal",
                **({"next_required_objective": item["next"]} if item.get("next") else {}),
            }
            for item in objectives
        ]
        payload = self.request("POST", "/v2/objectives", {"data": data})
        return _resource_id(payload, "objectives_id", "uuid", "id")

    def list_tools(self) -> list[dict[str, Any]]:
        """Return every tool page, including older and versioned tools."""
        records: list[dict[str, Any]] = []
        page = 1
        while True:
            payload = self.request("GET", f"/v2/tools?page={page}")
            batch = _records(payload, "tools")
            records.extend(batch)
            total = payload.get("total_count") if isinstance(payload, dict) else None
            if not batch or not isinstance(total, int) or len(records) >= total:
                return records
            page += 1

    def create_tool(self, tool: dict[str, Any]) -> str:
        """Register an app-message tool and return its id."""
        body = {
            "name": tool["name"],
            "description": tool["description"],
            "parameters": tool.get("parameters") or {"type": "object", "properties": {}},
            "origin": "llm",
            "delivery": tool.get("delivery") or {"app_message": True},
            "on_call": tool.get("on_call") or "silent",
            "on_resolve": tool.get("on_resolve") or "generate_response",
        }
        try:
            payload = self.request("POST", "/v2/tools", body)
        except TavusIntegrationError:
            payload = _match_named(self.list_tools(), "name", str(tool["name"]))
            tool_id = _resource_id(payload, "tool_id", "uuid")
            self.request(
                "PATCH",
                f"/v2/tools/{tool_id}",
                {
                    "description": body["description"],
                    "parameters": body["parameters"],
                    "on_resolve": body["on_resolve"],
                    "delivery": body["delivery"],
                    "on_call": body["on_call"],
                },
            )
            return tool_id
        return _resource_id(payload, "tool_id", "uuid")

    def create_pal(self, body: dict[str, Any]) -> str:
        """Create a PAL and return its id."""
        payload = self.request("POST", "/v2/pals", body)
        return _resource_id(payload, "pal_id", "uuid")

    def attach_tools(self, pal_id: str, tool_ids: list[str]) -> None:
        """Attach registry tools to a PAL."""
        if tool_ids:
            self.request("POST", f"/v2/pals/{pal_id}/tools", {"tool_ids": tool_ids})

    def create_conversation(self, body: dict[str, Any]) -> dict[str, Any]:
        """Start a CVI conversation."""
        payload = self.request("POST", "/v2/conversations", body)
        if not isinstance(payload, dict) or "conversation_url" not in payload:
            raise TavusIntegrationError("Create conversation did not return conversation_url")
        return payload

    def end_conversation(self, conversation_id: str) -> None:
        """End a live conversation."""
        try:
            self.request("POST", f"/v2/conversations/{conversation_id}/end")
        except TavusIntegrationError:
            status = self._client.get(f"/v2/conversations/{conversation_id}", timeout=3)
            if status.status_code == 404 or (
                status.is_success and status.json().get("status") == "ended"
            ):
                return
            raise

    def conversation_status(self, conversation_id: str) -> str:
        response = self._client.get(f"/v2/conversations/{conversation_id}", timeout=3)
        response.raise_for_status()
        return str(response.json().get("status", ""))

    def create_memory_store(self, pal_id: str, participant_tag: str) -> str | None:
        """Create a memory store. A 409 means the store already exists."""
        try:
            payload = self.request(
                "POST",
                "/v2/memory-stores",
                {"pal_id": pal_id, "participant_tag": participant_tag},
            )
        except TavusIntegrationError as exc:
            if "409" in str(exc):
                return None
            raise
        if isinstance(payload, dict):
            return _resource_id(payload, "memory_store_id", "uuid")
        return None

    def pin_memory(self, memory_store_id: str, text: str) -> None:
        """Add one pinned fact to a memory store."""
        self.request(
            "POST",
            f"/v2/memory-stores/{memory_store_id}/pinned",
            {"memory": text[:500]},
        )

    def chat_start(self, pal_id: str) -> str:
        """Open a text-only chat conversation and return its id."""
        payload = self.request(
            "POST",
            "/v2/conversations",
            {"pal_id": pal_id, "audio_only": False, "properties": {"chat_mode": True}},
        )
        return _resource_id(payload, "conversation_id", "uuid")


def _records(payload: Any, key: str) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        data = payload.get("data") or payload.get(key) or []
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
    return []


def _match_named(records: list[dict[str, Any]], field: str, name: str) -> dict[str, Any]:
    for record in records:
        if record.get(field) == name:
            return record
    raise TavusIntegrationError(f"No {field} named {name}")


def _resource_id(payload: Any, *keys: str) -> str:
    if not isinstance(payload, dict):
        raise TavusIntegrationError("Tavus response was not an object")
    for key in keys:
        value = payload.get(key)
        if value:
            return str(value)
    raise TavusIntegrationError("Tavus response did not include an id")
