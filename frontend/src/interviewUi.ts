import type { Phase } from "./types";

export function isEnded(phase: Phase | "lobby"): boolean {
  return ["completed", "candidate_left", "terminated_rude"].includes(phase);
}

export function speakingState(current: boolean, event: string, role: unknown): boolean {
  if (role !== "pal" && role !== "replica") return current;
  if (event === "conversation.started_speaking") return true;
  if (event === "conversation.stopped_speaking") return false;
  return current;
}

export function showInterviewer(docked: boolean, speaking: boolean, connecting: boolean, blocked: boolean): boolean {
  return !docked || speaking || connecting || blocked;
}

// Older stored questions lost their HTML paragraph boundaries. Restore explicit
// section labels as a fallback; new scrapes preserve block structure.
export function statementSections(text: string): { title: string; body: string }[] {
  const normalized = text.replace(/\r/g, "").replace(/\u00a0/g, " ")
    .replace(/\s*(Example\s+\d+\s*:|Constraints\s*:|Follow[- ]up\s*:|Custom Judge\s*:|Custom judge\s*:)/g, "\n\n$1");
  return normalized.split(/\n\s*\n/).map((part) => {
    const match = part.trim().match(/^(Example\s+\d+|Constraints|Follow[- ]up|Custom [Jj]udge)\s*:\s*([\s\S]*)$/);
    return match ? { title: match[1], body: match[2] } : { title: "", body: part.trim() };
  }).filter((part) => part.body);
}
