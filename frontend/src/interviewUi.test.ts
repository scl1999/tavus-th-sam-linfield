import { expect, test } from "vitest";
import { isEnded, showInterviewer, speakingState, statementSections } from "./interviewUi";

test("PAL speaking events show and hide the video while candidate speech has no effect", () => {
  expect(speakingState(false, "conversation.started_speaking", "pal")).toBe(true);
  expect(speakingState(true, "conversation.stopped_speaking", "pal")).toBe(false);
  expect(speakingState(false, "conversation.started_speaking", "replica")).toBe(true);
  expect(speakingState(true, "conversation.stopped_speaking", "user")).toBe(true);
  expect(showInterviewer(true, false, false, false)).toBe(false);
  expect(showInterviewer(true, true, false, false)).toBe(true);
  expect(showInterviewer(false, false, false, false)).toBe(true);
  expect(showInterviewer(true, false, false, true)).toBe(true);
});

test("old flattened statements regain examples and constraints without interpreting HTML", () => {
  expect(statementSections("Solve it. Example 1: Input: x Output: y Constraints: x > 0")).toEqual([
    { title: "", body: "Solve it." },
    { title: "Example 1", body: "Input: x Output: y" },
    { title: "Constraints", body: "x > 0" },
  ]);
  expect(statementSections("<script>alert(1)</script>")[0].body).toContain("<script>");
  expect(statementSections("First paragraph.\n\nSecond paragraph.")).toHaveLength(2);
});

test("all terminal phases release the session", () => {
  expect(isEnded("completed")).toBe(true);
  expect(isEnded("candidate_left")).toBe(true);
  expect(isEnded("terminated_rude")).toBe(true);
  expect(isEnded("coding_easy")).toBe(false);
});
