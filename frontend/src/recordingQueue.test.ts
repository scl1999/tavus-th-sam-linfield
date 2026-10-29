import "fake-indexeddb/auto";
import { webcrypto } from "node:crypto";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import {
  createRecording,
  finalizeRecording,
  uploadRecordingChunk,
} from "./api";
import {
  drainRecordingQueue,
  enqueueRecording,
  pendingRecordingCount,
} from "./recordingQueue";

vi.mock("./api", () => ({
  createRecording: vi.fn(),
  finalizeRecording: vi.fn(),
  uploadRecordingChunk: vi.fn(),
}));
beforeEach(() => {
  vi.stubGlobal("crypto", webcrypto);
  vi.stubGlobal("window", {
    setTimeout: (callback: () => void) => {
      queueMicrotask(callback);
      return 0;
    },
  });
  vi.mocked(createRecording).mockResolvedValue(undefined);
  vi.mocked(uploadRecordingChunk).mockResolvedValue(undefined);
  vi.mocked(finalizeRecording).mockResolvedValue(undefined);
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

test("drain includes new chunks and finalization queued during an active upload", async () => {
  let release: () => void = () => undefined;
  vi.mocked(createRecording).mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        release = () => resolve(undefined);
      }),
  );
  await enqueueRecording({
    interview: "one",
    segment: "one",
    kind: "create",
    sequence: -1,
    mime: "video/webm",
  });
  const flight = drainRecordingQueue();
  await vi.waitFor(() => expect(createRecording).toHaveBeenCalledTimes(1));
  await enqueueRecording({
    interview: "one",
    segment: "one",
    kind: "chunk",
    sequence: 0,
    payload: new Blob(["abc"]),
  });
  await enqueueRecording({
    interview: "one",
    segment: "one",
    kind: "finalize",
    sequence: 1_000_000,
    count: 1,
  });
  release();
  await flight;
  expect(uploadRecordingChunk).toHaveBeenCalledWith(
    "one",
    "one",
    0,
    "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
    expect.any(Blob),
  );
  expect(finalizeRecording).toHaveBeenCalledWith("one", "one", 1);
  expect(await pendingRecordingCount()).toBe(0);
});

test("unacknowledged chunks remain durably queued after bounded retries", async () => {
  await enqueueRecording({
    interview: "two",
    segment: "two",
    kind: "create",
    sequence: -1,
    mime: "video/webm",
  });
  vi.mocked(createRecording).mockRejectedValue(new Error("offline"));
  await expect(drainRecordingQueue()).rejects.toThrow("offline");
  expect(createRecording).toHaveBeenCalledTimes(4);
  expect(await pendingRecordingCount()).toBe(1);
  vi.mocked(createRecording).mockResolvedValue(undefined);
  await drainRecordingQueue();
  expect(await pendingRecordingCount()).toBe(0);
});
