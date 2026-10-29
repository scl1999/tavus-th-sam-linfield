import { useEffect, useRef } from "react";
import type { DailyCall } from "@daily-co/daily-js";
import { reminder, saveDraft } from "../api";
import { envelopeContext } from "../toolMessages";

export interface WorkspaceSnapshot {
  code: string;
  terminal: string;
  diagram: string;
  phase: string;
  language: string;
  frozen: boolean;
  revision: number;
}
export function useWorkspaceSync(
  id: string | null,
  conversationId: string,
  call: DailyCall | null,
  joined: boolean,
  snapshot: WorkspaceSnapshot,
  onError: (reason: unknown) => void,
) {
  const current = useRef({
    id,
    conversationId,
    call,
    joined,
    snapshot,
    onError,
  });
  current.current = { id, conversationId, call, joined, snapshot, onError };
  const queue = useRef<Promise<void>>(Promise.resolve());
  const saved = useRef(new Map<string, number>());
  const flushDraft = async () => {
    const state = current.current;
    if (
      !state.id ||
      state.snapshot.frozen ||
      !state.snapshot.phase.startsWith("coding_") ||
      state.snapshot.revision < 1
    )
      return;
    const { snapshot: work } = state;
    const key = `${state.id}:${work.phase}:${work.language}`;
    if ((saved.current.get(key) ?? 0) >= work.revision) return;
    const flight = queue.current
      .catch(() => undefined)
      .then(async () => {
        if ((saved.current.get(key) ?? 0) >= work.revision) return;
        await saveDraft(
          state.id!,
          work.phase,
          work.language,
          work.code,
          work.revision,
        );
        saved.current.set(key, work.revision);
      });
    queue.current = flight;
    await flight;
  };
  const requestSync = async () => {
    const state = current.current;
    if (!state.id || !state.call || !state.joined) return;
    // Only a small public notification crosses the candidate data channel.
    const notice = await reminder(state.id, {
      code: "",
      terminal: "",
      diagram_xml: "",
      mode: "overwrite",
    });
    const message = envelopeContext(notice, state.conversationId);
    if (new TextEncoder().encode(JSON.stringify(message)).length > 4096)
      throw new Error("Context notification exceeds the transport limit");
    if (current.current.id === state.id && current.current.joined)
      state.call.sendAppMessage(message, "*");
  };
  const actions = useRef({ flushDraft, requestSync });
  actions.current = { flushDraft, requestSync };
  useEffect(() => {
    if (!id) return;
    const timer = window.setTimeout(() => {
      void actions.current.flushDraft().catch(current.current.onError);
    }, 500);
    return () => window.clearTimeout(timer);
  }, [id, snapshot.code, snapshot.revision, snapshot.phase, snapshot.language]);
  useEffect(() => {
    if (!id || !joined) return;
    const timer = window.setTimeout(() => {
      void actions.current
        .flushDraft()
        .then(() => actions.current.requestSync())
        .catch(current.current.onError);
    }, 1500);
    return () => window.clearTimeout(timer);
  }, [
    id,
    joined,
    snapshot.code,
    snapshot.diagram,
    snapshot.terminal,
    snapshot.phase,
  ]);
  useEffect(() => {
    if (!id) return;
    const timer = window.setInterval(() => {
      void actions.current.flushDraft().catch(current.current.onError);
    }, 5000);
    return () => window.clearInterval(timer);
  }, [id]);
  return { flushDraft, requestSync };
}
