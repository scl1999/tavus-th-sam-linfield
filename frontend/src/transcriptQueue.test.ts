import "fake-indexeddb/auto";
import { afterEach, expect, test, vi } from "vitest";
import { recordUtterance } from "./api";
import {
  enqueueTranscript,
  drainTranscripts,
  pendingTranscripts,
} from "./transcriptQueue";
vi.mock("./api", () => ({ recordUtterance: vi.fn() }));
afterEach(() => vi.clearAllMocks());
test("an API outage retains speech and retries the same event after recovery", async () => {
  const event = {
    event_id: "event-1",
    observed_at: "2026-10-29T10:00:00Z",
    turn_idx: 1,
    role: "user",
    text: "thinking",
    code: "",
    terminal: "",
    diagram_xml: "",
  };
  vi.mocked(recordUtterance).mockRejectedValueOnce(new Error("offline"));
  await enqueueTranscript("interview", event);
  await expect(drainTranscripts()).rejects.toThrow("offline");
  expect(await pendingTranscripts()).toBe(1);
  vi.mocked(recordUtterance).mockResolvedValueOnce({
    event_type: "notice",
    properties: {},
  });
  await drainTranscripts();
  expect(recordUtterance).toHaveBeenCalledTimes(2);
  expect(vi.mocked(recordUtterance).mock.calls[1][1].event_id).toBe("event-1");
  expect(await pendingTranscripts()).toBe(0);
});
