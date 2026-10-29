import { afterEach, expect, test, vi } from "vitest";

import {
  endInterview,
  currentInterview,
  mediaReady,
  uploadRecordingChunk,
  fetchCandidate,
  listTurns,
  recordUtterance,
  reminder,
  runCode,
  runTerminal,
  saveDiagram,
  startInterview,
} from "./api";
import type { InterviewStatus } from "./types";

const status: InterviewStatus = {
  interview: {
    id: "interview-1",
    current_phase: "intro",
    conversation_url: "https://tavus.daily.co/room",
    conversation_id: "conv-1",
    started_at: "2026-10-27T00:00:00Z",
  },
  ready: true,
  setup_state: "ready",
  workspace: {
    drafts: {},
    whiteboards: {},
    revisions: {},
    language: "python3",
    terminal: "",
  },
  phase_deadline_seconds: 300,
  elapsed_seconds: 0,
  frozen: false,
  easy: null,
  medium: null,
  system_design: null,
};

function jsonResponse(body: unknown, ok = true): Response {
  return new Response(JSON.stringify(body), {
    status: ok ? 200 : 400,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

test("interview client calls the seeded start, phase, design, and end routes", async () => {
  const calls: Array<{ url: string; method: string; body: string }> = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({
        url: String(input),
        method: init?.method ?? "GET",
        body: typeof init?.body === "string" ? init.body : "",
      });
      if (String(input).endsWith("/problems/system-design")) {
        return jsonResponse({
          questions: [
            {
              id: 1,
              question_number: 1,
              question_title: "URL shortener",
              problem_statement: "Shorten links.",
            },
          ],
        });
      }
      if (String(input).endsWith("/candidate")) {
        return jsonResponse({
          first_name: "Sam",
          full_name: "Sam Linfield",
          target_role: "Senior AI Engineer",
        });
      }
      return jsonResponse(status);
    }),
  );

  const candidate = await fetchCandidate();
  const started = await startInterview();
  await currentInterview();
  await mediaReady("interview-1");
  await endInterview("interview-1");

  expect(candidate.full_name).toBe("Sam Linfield");
  expect(started.interview.conversation_url).toContain("daily.co");
  expect(calls.map((call) => [call.method, call.url])).toEqual([
    ["GET", "/api/candidate"],
    ["POST", "/api/interviews"],
    ["GET", "/api/interviews/current"],
    ["POST", "/api/interviews/interview-1/ready"],
    ["POST", "/api/interviews/interview-1/end"],
  ]);
  expect(calls[1]?.body).toBe("{}");
});

test("workspace and telemetry helpers send the editor snapshot", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/run") || url.endsWith("/terminal")) {
        return jsonResponse({ stdout: "ok", stderr: "", exit_code: 0 });
      }
      if (url.endsWith("/diagram")) {
        return jsonResponse({ summary: "[Client] -> [API]" });
      }
      if (url.endsWith("/reminder") || url.endsWith("/utterance")) {
        return jsonResponse({
          event_type: "conversation.overwrite_llm_context",
          properties: { context: "phase" },
        });
      }
      if (url.endsWith("/tool")) {
        return jsonResponse({ status: "executed" });
      }
      if (url.endsWith("/turns")) {
        return jsonResponse({
          turns: [
            {
              turn_idx: 0,
              role: "candidate",
              input_tokens: 10,
              output_tokens: 0,
              utterance_text: "map",
            },
          ],
        });
      }
      return jsonResponse({ status: "released" });
    }),
  );

  const ran = await runCode("interview-1", "python3", "print(1)");
  const terminal = await runTerminal("interview-1", "ls");
  const summary = await saveDiagram("interview-1", "<diagram/>");
  const message = await reminder("interview-1", {
    code: "print(1)",
    terminal: "ok",
    diagram_xml: "",
    mode: "overwrite",
  });
  const utterance = await recordUtterance("interview-1", {
    turn_idx: 0,
    role: "candidate",
    text: "I will use a map.",
    code: "",
    terminal: "",
    diagram_xml: "",
  });

  const turns = await listTurns("interview-1");

  expect(ran.stdout).toBe("ok");
  expect(terminal.exit_code).toBe(0);
  expect(summary).toBe("[Client] -> [API]");
  expect(message.event_type).toBe("conversation.overwrite_llm_context");
  expect(utterance.properties.context).toBe("phase");
  expect(turns).toHaveLength(1);
});

test("json error details are shown as sentences", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            detail:
              'POST /v2/conversations failed: 400 {"message":"User has reached maximum concurrent conversations"}',
          }),
          { status: 400 },
        ),
    ),
  );
  await expect(startInterview()).rejects.toThrow(
    "Another interview is still open",
  );
});

test("failed responses raise the server detail", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response("Technical assessment is locked at 55:00", {
          status: 409,
        }),
    ),
  );
  await expect(fetchCandidate()).rejects.toThrow("locked at 55:00");
});

test("recording chunks carry sequence, checksum and CSRF headers", async () => {
  const fetchMock = vi.fn(async () => jsonResponse({ status: "acknowledged" }));
  vi.stubGlobal("fetch", fetchMock);
  const chunk = new Blob(["abc"], { type: "video/webm" });
  await uploadRecordingChunk("interview-1", "segment-1", 2, "checksum", chunk);
  const [url, init] = fetchMock.mock.calls[0] as unknown as [
    string,
    RequestInit,
  ];
  expect(url).toBe("/api/interviews/interview-1/recordings/segment-1/chunks/2");
  expect(init.body).toBe(chunk);
  expect(init.credentials).toBe("same-origin");
  expect(init.headers).toMatchObject({
    "X-Chunk-SHA256": "checksum",
    "X-Requested-With": "tavus-interview",
  });
});

test("an API timeout aborts an unresponsive request", async () => {
  const controller = new AbortController();
  const timeout = vi
    .spyOn(AbortSignal, "timeout")
    .mockReturnValue(controller.signal);
  vi.stubGlobal(
    "fetch",
    vi.fn(
      (_input: RequestInfo | URL, init?: RequestInit) =>
        new Promise((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () =>
            reject(new DOMException("timed out", "AbortError")),
          );
        }),
    ),
  );
  const request = fetchCandidate();
  controller.abort();
  await expect(request).rejects.toMatchObject({ name: "AbortError" });
  expect(timeout).toHaveBeenCalledWith(10000);
  timeout.mockRestore();
});
