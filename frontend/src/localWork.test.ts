import { afterEach, expect, test, vi } from "vitest";
import { loadWork, storeWork, mergeAcknowledged, isPending } from "./localWork";
afterEach(() => vi.unstubAllGlobals());
test("refresh preserves unacknowledged revisions and rejects corrupt entries", () => {
  const storage = new Map<string, string>();
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => storage.get(key),
    setItem: (key: string, value: string) => storage.set(key, value),
  });
  const draft = {
    "code:coding_easy:python3": { value: "print(2)", revision: 2 },
    "board:1": { value: "<board/>", revision: 1 },
  };
  storeWork("interview", draft);
  expect(loadWork("interview")).toEqual(draft);
  expect(loadWork("another-interview")).toEqual({});
  storage.set(
    "tavus-work:interview",
    JSON.stringify({ ...draft, corrupt: { value: 3, revision: -1 } }),
  );
  expect(loadWork("interview")).toEqual(draft);
});

test("a newer server snapshot cannot silently discard an unacknowledged local edit", () => {
  const local = {
    "code:coding_easy:python3": { value: "my pending edit", revision: 3 },
  };
  const server = {
    drafts: { "coding_easy:python3": "other tab" },
    whiteboards: {},
    revisions: { "code:coding_easy:python3": 4 },
  };
  expect(mergeAcknowledged(local, server)).toEqual(local);
  expect(
    isPending(
      "code:coding_easy:python3",
      local["code:coding_easy:python3"],
      server,
    ),
  ).toBe(true);
  const accepted = {
    ...server,
    drafts: { "coding_easy:python3": "my pending edit" },
  };
  expect(
    mergeAcknowledged(local, accepted)["code:coding_easy:python3"],
  ).toEqual({ value: "my pending edit", revision: 4, acknowledged: true });
});
