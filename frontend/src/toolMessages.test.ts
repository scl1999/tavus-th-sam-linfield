import { expect, test } from "vitest";

import {
  envelopeContext,
  parseConversationEvent,
  toolArguments,
  toolCallName,
  toolResultMessage,
} from "./toolMessages";

const toolCall = {
  message_type: "conversation",
  event_type: "conversation.tool_call",
  conversation_id: "conv-1",
  properties: {
    name: "start_technical_interview",
    arguments: "{}",
    tool_call_id: "call_abc",
  },
};

test("a Tavus tool call keeps its id and parses string arguments", () => {
  const event = parseConversationEvent(JSON.stringify(toolCall));
  expect(event?.eventType).toBe("conversation.tool_call");
  expect(event?.conversationId).toBe("conv-1");
  expect(toolCallName(event?.properties ?? {})).toBe("start_technical_interview");
  expect(toolArguments(event?.properties ?? {})).toEqual({});
});

test("object arguments and a nested message are accepted", () => {
  const event = parseConversationEvent({
    message: {
      event_type: "conversation.tool_call",
      properties: { tool_name: "advance_to_medium_problem", arguments: { note: "next" } },
    },
  });
  expect(toolCallName(event?.properties ?? {})).toBe("advance_to_medium_problem");
  expect(toolArguments(event?.properties ?? {})).toEqual({ note: "next" });
});

test("invalid argument text becomes an empty object", () => {
  expect(toolArguments({ arguments: "not-json" })).toEqual({});
});

test("the tool result pairs with the original call", () => {
  const event = parseConversationEvent(toolCall);
  expect(event).not.toBeNull();
  expect(toolResultMessage(event!, "", "Easy problem is open.", "success")).toEqual({
    message_type: "conversation",
    event_type: "conversation.tool_result",
    conversation_id: "conv-1",
    properties: {
      tool_call_id: "call_abc",
      output: "Easy problem is open.",
      status: "success",
    },
  });
});

test("context updates are sent as conversation app messages", () => {
  expect(
    envelopeContext(
      { event_type: "conversation.overwrite_llm_context", properties: { context: "phase" } },
      "conv-9",
    ),
  ).toEqual({
    message_type: "conversation",
    event_type: "conversation.overwrite_llm_context",
    conversation_id: "conv-9",
    properties: { context: "phase" },
  });
});
