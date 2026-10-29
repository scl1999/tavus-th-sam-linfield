import { afterEach, expect, test, vi } from "vitest";
import { saveDiagram, saveDraft } from "./api";
import { storeWork } from "./localWork";
import { replayPendingWork } from "./workReplay";
import type { InterviewStatus } from "./types";
vi.mock("./api", () => ({
  saveDiagram: vi.fn(),
  saveDraft: vi.fn(),
  saveLanguage: vi.fn(),
}));
afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});
test("failed code and board saves remain available and replay after service recovery", async () => {
  const storage = new Map<string, string>();
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => storage.get(key),
    setItem: (key: string, value: string) => storage.set(key, value),
  });
  const state = {
    workspace: {
      drafts: {},
      whiteboards: {},
      revisions: {},
      language: "python3",
    },
    system_design: { id: 7 },
  } as InterviewStatus;
  storeWork("i", {
    "code:coding_easy:python3": { value: "print(1)", revision: 3 },
    "board:7": { value: "<board/>", revision: 4 },
  });
  vi.mocked(saveDraft).mockRejectedValueOnce(new Error("offline"));
  await expect(replayPendingWork("i", "coding_easy", state)).rejects.toThrow(
    "offline",
  );
  vi.mocked(saveDraft).mockResolvedValueOnce({ revision: 3 });
  await replayPendingWork("i", "coding_easy", state);
  expect(saveDraft).toHaveBeenLastCalledWith(
    "i",
    "coding_easy",
    "python3",
    "print(1)",
    3,
  );
  vi.mocked(saveDiagram).mockRejectedValueOnce(
    new Error("database unavailable"),
  );
  await expect(replayPendingWork("i", "system_design", state)).rejects.toThrow(
    "database unavailable",
  );
  vi.mocked(saveDiagram).mockResolvedValueOnce("saved");
  await replayPendingWork("i", "system_design", state);
  expect(saveDiagram).toHaveBeenLastCalledWith("i", "<board/>", 7, 4);
});
