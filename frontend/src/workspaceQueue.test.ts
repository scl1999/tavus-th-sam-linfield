import { expect, test } from "vitest";
import { LatestWorkspaceQueue } from "./workspaceQueue";

test("an edit during an in-flight context request supersedes stale responses and coalesces intermediate edits", async () => {
  let release = () => {};
  const first = new Promise<void>((resolve) => { release = resolve; });
  const requested: string[] = [];
  const sent: string[] = [];
  const queue = new LatestWorkspaceQueue<string>(async (value, isLatest) => {
    requested.push(value);
    if (value === "old") await first;
    if (isLatest()) sent.push(value);
  });
  const flight = queue.submit("old");
  await queue.submit("middle");
  await queue.submit("latest");
  release();
  await flight;
  expect(requested).toEqual(["old", "latest"]);
  expect(sent).toEqual(["latest"]);
});

test("a rejected request does not lock all future context updates", async () => {
  const sent: number[] = [];
  const queue = new LatestWorkspaceQueue<number>(async (value) => {
    if (value === 1) throw new Error("offline");
    sent.push(value);
  });
  await expect(queue.submit(1)).rejects.toThrow("offline");
  await queue.submit(2);
  expect(sent).toEqual([2]);
});
