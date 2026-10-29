import type { AppMessage, InterviewStatus, TurnRow } from "./types";

function nestedMessage(text: string, depth = 0): string {
  if (!text || depth > 4) return text;
  try {
    const payload = JSON.parse(text) as { detail?: unknown; message?: unknown };
    if (typeof payload.message === "string") return payload.message;
    if (typeof payload.detail === "string")
      return nestedMessage(payload.detail, depth + 1);
  } catch {
    const start = text.indexOf("{");
    const end = text.lastIndexOf("}");
    if (start >= 0 && end > start)
      return nestedMessage(text.slice(start, end + 1), depth + 1);
  }
  return text;
}

export async function requestJson<T>(
  url: string,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(url, {
    ...init,
    signal: init?.signal
      ? AbortSignal.any([
          init.signal,
          AbortSignal.timeout(
            url === "/api/interviews" && init?.method === "POST"
              ? 120000
              : 10000,
          ),
        ])
      : AbortSignal.timeout(
          url === "/api/interviews" && init?.method === "POST" ? 120000 : 10000,
        ),
    credentials: "same-origin",
    headers: {
      "X-Requested-With": "tavus-interview",
      ...init?.headers,
    },
  });
  if (!response.ok) {
    let message = nestedMessage(await response.text());
    if (message.includes("maximum concurrent conversations"))
      message =
        "Another interview is still open. Leave that call, then try again.";
    throw new Error(message || response.statusText);
  }
  return response.json() as Promise<T>;
}

function post<T>(url: string, body: object = {}): Promise<T> {
  return requestJson(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}
export const fetchCandidate = () =>
  requestJson<{ first_name: string; full_name: string; target_role: string }>(
    "/api/candidate",
  );
export const prepareInterview = () => post<void>("/api/interviews/prepare");
export const startInterview = () => post<InterviewStatus>("/api/interviews");
export const currentInterview = () =>
  requestJson<InterviewStatus | null>("/api/interviews/current");
export const fetchInterview = (id: string) =>
  requestJson<InterviewStatus>(`/api/interviews/${id}`);
export const mediaReady = (id: string) =>
  post<InterviewStatus>(`/api/interviews/${id}/ready`);
export const endInterview = (id: string) =>
  post<void>(`/api/interviews/${id}/end`);
export const saveDraft = (
  id: string,
  phase: string,
  language: string,
  code: string,
  revision = 1,
) =>
  post<{ revision: number }>(`/api/workspace/${id}/draft`, {
    phase,
    language,
    code,
    revision,
  });
export async function saveDiagram(
  id: string,
  xml: string,
  question_id = 0,
  revision = 1,
): Promise<string> {
  const result = await post<{ summary: string }>(
    `/api/workspace/${id}/diagram`,
    { xml, question_id, revision },
  );
  return result.summary;
}
export const runCode = (
  id: string,
  language: string,
  code: string,
  phase = "coding_easy",
  revision = 1,
) =>
  post<{ stdout: string; stderr: string; exit_code: number; warning?: string }>(
    `/api/workspace/${id}/run`,
    { language, code, phase, revision },
  );
export const runTerminal = (id: string, command: string) =>
  post<{ stdout: string; stderr: string; exit_code: number; warning?: string }>(
    `/api/workspace/${id}/terminal`,
    { command },
  );
export const reminder = (
  id: string,
  snapshot: {
    code: string;
    terminal: string;
    diagram_xml: string;
    mode: "append" | "overwrite";
  },
) => post<AppMessage>(`/api/interviews/${id}/reminder`, snapshot);
export const recordUtterance = (
  id: string,
  body: {
    turn_idx: number;
    event_id?: string;
    observed_at?: string;
    inference_id?: string;
    role: string;
    text: string;
    code: string;
    terminal: string;
    diagram_xml: string;
  },
) => post<AppMessage>(`/api/telemetry/${id}/utterance`, body);
export const listTurns = async (id: string): Promise<TurnRow[]> =>
  (await requestJson<{ turns: TurnRow[] }>(`/api/telemetry/${id}/turns`)).turns;
export const createRecording = (
  id: string,
  segment: string,
  mime_type: string,
) => post<void>(`/api/interviews/${id}/recordings/${segment}`, { mime_type });
export const finalizeRecording = (id: string, segment: string, count: number) =>
  post<void>(`/api/interviews/${id}/recordings/${segment}/finalize`, { count });
export const uploadRecordingChunk = (
  id: string,
  segment: string,
  sequence: number,
  checksum: string,
  payload: Blob,
) =>
  requestJson<void>(
    `/api/interviews/${id}/recordings/${segment}/chunks/${sequence}`,
    { method: "PUT", headers: { "X-Chunk-SHA256": checksum }, body: payload },
  );

export const acknowledgeCheckpoint = (id: string, nonce: string) =>
  post<void>(`/api/interviews/${id}/checkpoint`, { nonce });

export const saveLanguage = (id: string, language: string) =>
  post<void>(`/api/workspace/${id}/language`, { language });
