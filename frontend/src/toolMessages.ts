import type { AppMessage } from "./types";

export interface ConversationEvent {
  messageType: string;
  eventType: string;
  conversationId: string;
  properties: Record<string, unknown>;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

export function parseConversationEvent(data: unknown): ConversationEvent | null {
  let record = asRecord(data);
  if (!record && typeof data === "string") {
    try {
      record = asRecord(JSON.parse(data));
    } catch {
      return null;
    }
  }
  if (!record) {
    return null;
  }
  if (typeof record.event_type !== "string") {
    const nested = asRecord(record.message) ?? asRecord(record.data);
    if (nested) {
      return parseConversationEvent(nested);
    }
    return null;
  }
  const properties = asRecord(record.properties) ?? {};
  return {
    messageType: typeof record.message_type === "string" ? record.message_type : "conversation",
    eventType: record.event_type,
    conversationId: typeof record.conversation_id === "string" ? record.conversation_id : "",
    properties,
  };
}

export function toolCallName(properties: Record<string, unknown>): string {
  const name = properties.name ?? properties.tool_name;
  return typeof name === "string" ? name : "";
}

export function toolArguments(properties: Record<string, unknown>): Record<string, unknown> {
  const raw = properties.arguments ?? properties.args ?? {};
  if (typeof raw === "string") {
    try {
      return asRecord(JSON.parse(raw)) ?? {};
    } catch {
      return {};
    }
  }
  return asRecord(raw) ?? {};
}

export function toolResultMessage(
  event: ConversationEvent,
  conversationId: string,
  output: string,
  status: "success" | "error",
): Record<string, unknown> {
  const toolCallId = event.properties.tool_call_id;
  return {
    message_type: "conversation",
    event_type: "conversation.tool_result",
    conversation_id: event.conversationId || conversationId,
    properties: {
      tool_call_id: typeof toolCallId === "string" ? toolCallId : "",
      output,
      status,
    },
  };
}

export function envelopeContext(message: AppMessage, conversationId: string): Record<string, unknown> {
  return {
    message_type: "conversation",
    event_type: message.event_type,
    conversation_id: conversationId,
    properties: message.properties,
  };
}
