import { useEffect, useRef, useState } from "react";
import {
  acknowledgeCheckpoint,
  currentInterview,
  endInterview,
  fetchCandidate,
  fetchInterview,
  mediaReady,
  prepareInterview,
  runCode,
  saveDiagram,
  saveLanguage,
  startInterview,
} from "./api";
import { CodingWorkspace } from "./components/CodingWorkspace";
import { Lobby } from "./components/Lobby";
import { SystemDesignWorkspace } from "./components/SystemDesignWorkspace";
import { TopBar } from "./components/TopBar";
import { VideoStage } from "./components/VideoStage";
import { useDailyCall } from "./hooks/useDailyCall";
import { useScreenRecorder } from "./hooks/useScreenRecorder";
import { useWorkspaceSync } from "./hooks/useWorkspaceSync";
import { isEnded } from "./interviewUi";
import {
  loadWork,
  storeWork,
  mergeAcknowledged,
  isPending,
  type LocalWork,
} from "./localWork";
import { unlockPlayback } from "./mediaPlayback";
import { drainRecordingQueue, pendingRecordingCount } from "./recordingQueue";
import {
  drainTranscripts,
  enqueueTranscript,
  pendingTranscripts,
} from "./transcriptQueue";
import { replayPendingWork } from "./workReplay";
import { parseConversationEvent } from "./toolMessages";
import type { InterviewStatus, Phase } from "./types";

type Language = "python3" | "typescript";
export function App() {
  const [status, setStatus] = useState<InterviewStatus | null>(null);
  const [firstName, setFirstName] = useState("Sam");
  const [error, setError] = useState("");
  const [elapsed, setElapsed] = useState(0);
  const [language, setLanguage] = useState<Language>("python3");
  const [terminal, setTerminal] = useState("");
  const [work, setWork] = useState<LocalWork>({});
  const [starting, setStarting] = useState(false);
  const [loading, setLoading] = useState(true);
  const [connectingRequested, setConnectingRequested] = useState(false);
  const [running, setRunning] = useState(false);
  const callRef = useRef<ReturnType<typeof useDailyCall>["call"]>(null);
  const audio = useRef<HTMLAudioElement>(null);
  const clock = useRef({ at: performance.now(), elapsed: 0 });
  const startingRef = useRef(false);
  const readyFlight = useRef(false);
  const replayRef = useRef<() => Promise<void>>(async () => undefined);
  const seenEvents = useRef(new Set<string>());
  const turnIdx = useRef(0);
  const boardSaves = useRef<Promise<void>>(Promise.resolve());
  const syncRef = useRef<() => Promise<void>>(async () => undefined);
  const report = (reason: unknown) =>
    setError(reason instanceof Error ? reason.message : "Connection failed");
  const id = status?.interview.id ?? null;
  const phase: Phase | "lobby" = status?.interview.current_phase ?? "lobby";
  const ended = isEnded(phase);
  const frozen = ended || Boolean(status?.frozen) || elapsed >= 3300;
  const problem = phase === "coding_medium" ? status?.medium : status?.easy;
  const codeKey = `code:${phase}:${language}`;
  const boardKey = `board:${status?.system_design?.id ?? 0}`;
  const code =
    work[codeKey]?.value ??
    status?.workspace.drafts[`${phase}:${language}`] ??
    problem?.boilerplate_code?.[language] ??
    "";
  const diagram =
    work[boardKey]?.value ??
    status?.workspace.whiteboards[String(status?.system_design?.id)] ??
    "";
  const revision =
    work[codeKey]?.revision ?? status?.workspace.revisions[codeKey] ?? 0;
  const recorder = useScreenRecorder(id, Boolean(id) && !ended, callRef);
  const latest = useRef({
    code,
    terminal,
    diagram,
    phase,
    language,
    revision,
    frozen,
  });
  latest.current = {
    code,
    terminal,
    diagram,
    phase,
    language,
    revision,
    frozen,
  };
  const accept = (next: InterviewStatus) => {
    clock.current = { at: performance.now(), elapsed: next.elapsed_seconds };
    setElapsed(next.elapsed_seconds);
    setStatus(next);
  };
  const restore = (next: InterviewStatus) => {
    const local = loadWork(next.interview.id);
    setWork(local);
    const preferred = local.language?.value;
    setLanguage(
      preferred === "python3" || preferred === "typescript"
        ? preferred
        : next.workspace.language,
    );
    setTerminal(next.workspace.terminal);
    accept(next);
  };
  const {
    call,
    joined,
    readyForAssessment,
    speaking,
    audioBlocked,
    resumeAudio,
    stopReconnecting,
    videoElement,
  } = useDailyCall(
    connectingRequested && !ended
      ? (status?.interview.conversation_url ?? null)
      : null,
    {
      onError: report,
      onAppMessage: (data) => {
        const event = parseConversationEvent(data);
        if (
          !event ||
          !id ||
          ended ||
          event.eventType !== "conversation.utterance"
        )
          return;
        if (
          event.conversationId &&
          event.conversationId !== status?.interview.conversation_id
        )
          return;
        const role = event.properties.role;
        if (role !== "user" && role !== "pal") return;
        const text = String(
          event.properties.speech ?? event.properties.text ?? "",
        ).trim();
        if (!text) return;
        const inference =
          typeof event.properties.inference_id === "string"
            ? event.properties.inference_id
            : undefined;
        const key = JSON.stringify([
          role,
          inference,
          event.properties.timestamp,
          text,
        ]);
        if (seenEvents.current.has(key)) return;
        seenEvents.current.add(key);
        turnIdx.current++;
        const observed = {
          event_id: crypto.randomUUID(),
          observed_at: new Date().toISOString(),
          turn_idx: turnIdx.current,
          role,
          text,
          inference_id: inference,
          code: "",
          terminal: "",
          diagram_xml: "",
        };
        void enqueueTranscript(id, observed)
          .catch((reason: unknown) => {
            seenEvents.current.delete(key);
            throw new Error(
              "Unable to keep this transcript event in browser storage",
              { cause: reason },
            );
          })
          .then(() => drainTranscripts())
          .then(() => syncRef.current())
          .catch(report);
      },
    },
    recorder.localMedia,
    audio,
  );
  callRef.current = call;
  const sync = useWorkspaceSync(
    ended ? null : id,
    status?.interview.conversation_id ?? "",
    call,
    joined,
    { code, terminal, diagram, phase, language, frozen, revision },
    report,
  );
  syncRef.current = sync.requestSync;
  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    let attempts = 0;
    const load = async () => {
      try {
        const next = await currentInterview();
        if (cancelled) return;
        if (next) restore(next);
        setLoading(false);
        setError("");
        void fetchCandidate()
          .then((candidate) => {
            if (!cancelled) setFirstName(candidate.first_name);
          })
          .catch(report);
      } catch (reason) {
        if (cancelled) return;
        report(reason);
        timer = window.setTimeout(
          () => {
            timer = undefined;
            void load();
          },
          Math.min(30000, 1000 * 2 ** Math.min(attempts++, 5)),
        );
      }
    };
    const online = () => {
      if (timer !== undefined) {
        window.clearTimeout(timer);
        timer = undefined;
        void load();
      }
    };
    window.addEventListener("online", online);
    void load();
    return () => {
      cancelled = true;
      window.removeEventListener("online", online);
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, []);
  useEffect(() => {
    if (!id) return;
    const retry = () => {
      void drainTranscripts().catch(report);
    };
    retry();
    const timer = window.setInterval(retry, 5000);
    window.addEventListener("online", retry);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("online", retry);
    };
  }, [id]);
  useEffect(() => {
    if (!id || ended || frozen || !status?.ready) return;
    let flight: Promise<void> | null = null;
    const replay = () => {
      if (flight) return flight;
      flight = replayPendingWork(id, phase, status).finally(() => {
        flight = null;
      });
      return flight;
    };
    replayRef.current = replay;
    const timer = window.setInterval(() => {
      void replay().catch(report);
    }, 5000);
    const online = () => {
      void replay().catch(report);
    };
    window.addEventListener("online", online);
    void replay().catch(report);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("online", online);
    };
  }, [
    id,
    ended,
    frozen,
    status?.ready,
    phase,
    status?.system_design?.id,
    status?.workspace.revisions,
  ]);
  useEffect(() => {
    if (!id || ended) return;
    let disposed = false;
    let polling = false;
    const poll = async () => {
      if (polling) return;
      polling = true;
      try {
        const next = await fetchInterview(id);
        if (!disposed) accept(next);
      } catch (reason) {
        if (!disposed) report(reason);
      } finally {
        polling = false;
      }
    };
    const timer = window.setInterval(() => {
      void poll();
    }, 1500);
    window.addEventListener("focus", poll);
    return () => {
      disposed = true;
      window.clearInterval(timer);
      window.removeEventListener("focus", poll);
    };
  }, [id, ended]);
  useEffect(() => {
    if (!id || ended || !status?.ready) return;
    const timer = window.setInterval(
      () =>
        setElapsed(
          clock.current.elapsed +
            Math.floor((performance.now() - clock.current.at) / 1000),
        ),
      1000,
    );
    return () => window.clearInterval(timer);
  }, [id, ended, status?.ready]);
  useEffect(() => {
    if (
      !readyForAssessment ||
      !id ||
      status?.ready ||
      readyFlight.current ||
      !recorder.preview?.getAudioTracks().length
    )
      return;
    const acknowledge = () => {
      if (readyFlight.current) return;
      readyFlight.current = true;
      void mediaReady(id)
        .then(accept)
        .catch(report)
        .finally(() => {
          readyFlight.current = false;
        });
    };
    acknowledge();
    const retry = window.setInterval(acknowledge, 3000);
    return () => window.clearInterval(retry);
  }, [readyForAssessment, id, status?.ready, recorder.preview]);
  // Merge acknowledged snapshots after resume; never replace a newer pending local edit.
  useEffect(() => {
    if (!status) return;
    setWork((previous) => mergeAcknowledged(previous, status.workspace));
  }, [status?.workspace.revisions]);
  useEffect(() => {
    if (!id) return;
    try {
      storeWork(id, work);
    } catch {
      setError(
        "Local backup is full. Keep this tab open until changes are saved.",
      );
    }
  }, [id, work]);
  const edit = (key: string, value: string) => {
    if (!id || frozen) return;
    const next = {
      ...work,
      [key]: {
        value,
        revision:
          Math.max(
            work[key]?.revision ?? 0,
            status?.workspace.revisions[key] ?? 0,
          ) + 1,
      },
    };
    setWork(next);
    try {
      storeWork(id, next);
    } catch {
      setError(
        "Local backup is full. Keep this tab open until changes are saved.",
      );
    }
    return next[key].revision;
  };
  useEffect(() => {
    if (!id || !status?.checkpoint_request) return;
    const nonce = status.checkpoint_request;
    void Promise.all([
      sync.flushDraft(),
      boardSaves.current.catch(() => undefined),
      replayRef.current(),
    ])
      .then(() => acknowledgeCheckpoint(id, nonce))
      .catch(report);
  }, [id, status?.checkpoint_request]);
  const connect = () => {
    if (audio.current) unlockPlayback(audio.current);
    recorder.arm();
    setConnectingRequested(true);
  };
  useEffect(() => {
    if (!id || ended || !status?.ready || elapsed < 3600) return;
    // The server owns the deadline; also close local devices if the network is down.
    stopReconnecting();
    void recorder.release().catch(report);
    void call?.leave();
    setConnectingRequested(false);
    setStatus((current) =>
      current
        ? {
            ...current,
            frozen: true,
            interview: { ...current.interview, current_phase: "completed" },
          }
        : current,
    );
  }, [id, ended, status?.ready, elapsed, call]);
  const leave = async () => {
    if (!id) return;
    stopReconnecting();
    const media = recorder.release(); // Stops tracks immediately, before any upload awaits.
    void call?.leave();
    try {
      await Promise.all([sync.flushDraft(), boardSaves.current, media]);
    } catch (reason) {
      report(reason);
    }
    setConnectingRequested(false);
    setStatus((current) =>
      current
        ? {
            ...current,
            frozen: true,
            interview: {
              ...current.interview,
              current_phase: "candidate_left",
            },
          }
        : current,
    );
    try {
      await endInterview(id);
    } catch (reason) {
      report(reason);
    }
  };
  const start = async () => {
    if (startingRef.current) return;
    startingRef.current = true;
    setStarting(true);
    try {
      try {
        await recorder.release();
      } catch (reason) {
        report(reason);
      }
      if (await pendingRecordingCount()) await drainRecordingQueue();
      if (await pendingTranscripts()) await drainTranscripts();
      if (audio.current) unlockPlayback(audio.current);
      recorder.arm();
      await prepareInterview();
      let next: InterviewStatus;
      try {
        next = await startInterview();
      } catch (reason) {
        const recovered = await currentInterview().catch(() => null);
        if (!recovered) throw reason;
        next = recovered;
      }
      setWork({});
      seenEvents.current.clear();
      turnIdx.current = 0;
      restore(next);
      setConnectingRequested(true);
      setError("");
    } catch (reason) {
      void recorder.release().catch(report);
      report(reason);
    } finally {
      startingRef.current = false;
      setStarting(false);
    }
  };
  const pendingEdits = status
    ? Object.entries(work).filter(([key, draft]) =>
        isPending(key, draft, status.workspace),
      ).length
    : 0;
  const inactivePending = status
    ? Object.entries(work).some(
        ([key, draft]) =>
          key !== codeKey &&
          key !== boardKey &&
          isPending(key, draft, status.workspace),
      )
    : false;
  return (
    <div className="app">
      <audio ref={audio} autoPlay className="remote-audio" />
      <TopBar
        elapsedSeconds={elapsed}
        phase={phase}
        frozen={frozen && !ended}
        remainingSeconds={Math.max(
          0,
          (status?.phase_deadline_seconds ?? 300) - elapsed,
        )}
        listening={joined && Boolean(recorder.preview?.getAudioTracks().length)}
        recordingLabel={recorder.label}
        sharing={recorder.sharing}
        onShareScreen={recorder.shareScreen}
        onStopSharing={() => {
          void recorder.stopSharing().catch(report);
        }}
        onLeave={() => {
          void leave();
        }}
      />
      {error && (
        <p role="alert" className="error banner-error">
          {error}
          <button onClick={() => setError("")} aria-label="Dismiss error">
            ×
          </button>
        </p>
      )}
      {pendingEdits > 0 && (
        <p className="save-state" role="status">
          {frozen || inactivePending
            ? "Some changes remain on this device and have not been accepted by the server."
            : "Saving changes… Local copies are kept until acknowledged."}
          <button
            type="button"
            onClick={() => {
              const url = URL.createObjectURL(
                new Blob([JSON.stringify(work, null, 2)], {
                  type: "application/json",
                }),
              );
              const link = document.createElement("a");
              link.href = url;
              link.download = `interview-${id}-local-backup.json`;
              link.click();
              window.setTimeout(() => URL.revokeObjectURL(url), 1000);
            }}
          >
            Download local backup
          </button>
        </p>
      )}
      <main
        className={
          phase === "intro" ||
          phase === "lobby" ||
          ended ||
          !connectingRequested
            ? "stage hero-layout"
            : "stage dock-layout"
        }
      >
        {loading ? (
          <section className="session-ended">
            <p>Restoring interview state…</p>
          </section>
        ) : !status ? (
          <Lobby
            firstName={firstName}
            error=""
            busy={starting}
            onStart={() => {
              void start();
            }}
          />
        ) : ended ? (
          <section className="session-ended">
            <p className="eyebrow">Interview ended</p>
            <h1>Thank you, {firstName}.</h1>
            <p>Your camera and microphone are off.</p>
            <button className="primary" onClick={() => setStatus(null)}>
              Back to welcome
            </button>
          </section>
        ) : !connectingRequested ? (
          <section className="session-ended">
            <h1>Resume your interview</h1>
            <p>
              Your saved work is ready. Reconnect your camera and microphone to
              continue in the same call.
            </p>
            <button className="primary" onClick={connect}>
              Resume interview
            </button>
          </section>
        ) : (
          <>
            <VideoStage
              videoRef={videoElement}
              preview={recorder.preview}
              docked={phase !== "intro"}
              speaking={speaking}
              connecting={!joined}
              audioBlocked={audioBlocked}
              onResumeAudio={resumeAudio}
            />
            {joined && !recorder.preview && (
              <button
                className="primary"
                onClick={() => {
                  setConnectingRequested(false);
                  void recorder.release().catch(report);
                }}
              >
                Retry camera and microphone
              </button>
            )}
            {(phase === "coding_easy" || phase === "coding_medium") && (
              <CodingWorkspace
                problem={problem ?? null}
                language={language}
                code={code}
                terminal={terminal}
                frozen={frozen}
                running={running}
                onLanguage={(value) => {
                  setLanguage(value);
                  edit("language", value);
                  if (id) void saveLanguage(id, value).catch(report);
                }}
                onCode={(value) => {
                  edit(codeKey, value);
                }}
                onRun={() => {
                  if (running || frozen || !id) return;
                  setRunning(true);
                  const nextRevision = revision || edit(codeKey, code) || 1;
                  void sync
                    .flushDraft()
                    .then(() =>
                      runCode(id, language, code, phase, nextRevision),
                    )
                    .then((result) => {
                      setTerminal(
                        `${result.stdout}${result.stderr}\nProcess exited with code ${result.exit_code}.\n${result.warning || ""}`,
                      );
                    })
                    .catch((reason) =>
                      setTerminal(
                        reason instanceof Error ? reason.message : "Run failed",
                      ),
                    )
                    .finally(() => setRunning(false));
                }}
              />
            )}
            {phase === "system_design" && (
              <SystemDesignWorkspace
                key={status.system_design?.id}
                selected={status.system_design}
                frozen={frozen}
                initialXml={diagram}
                onXml={(xml) => {
                  const nextRevision = edit(boardKey, xml);
                  if (!nextRevision || !status.system_design?.id) return;
                  const question = status.system_design.id;
                  boardSaves.current = boardSaves.current
                    .catch(() => undefined)
                    .then(() =>
                      saveDiagram(
                        status.interview.id,
                        xml,
                        question,
                        nextRevision,
                      ),
                    )
                    .then(() => undefined);
                  void boardSaves.current
                    .then(() => sync.requestSync())
                    .catch(report);
                }}
              />
            )}
          </>
        )}
      </main>
    </div>
  );
}
