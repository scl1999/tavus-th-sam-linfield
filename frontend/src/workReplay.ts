import { saveDiagram, saveDraft, saveLanguage } from "./api";
import { isPending, loadWork } from "./localWork";
import type { InterviewStatus } from "./types";
export async function replayPendingWork(
  id: string,
  phase: string,
  status: InterviewStatus,
): Promise<void> {
  for (const [key, draft] of Object.entries(loadWork(id))) {
    if (key === "language") {
      if (draft.value !== status.workspace.language)
        await saveLanguage(id, draft.value);
      continue;
    }
    if (!isPending(key, draft, status.workspace)) continue;
    const parts = key.split(":");
    if (parts[0] === "code" && parts[1] === phase)
      await saveDraft(id, parts[1], parts[2], draft.value, draft.revision);
    if (
      parts[0] === "board" &&
      phase === "system_design" &&
      parts[1] === String(status.system_design?.id)
    )
      await saveDiagram(id, draft.value, Number(parts[1]), draft.revision);
  }
}
