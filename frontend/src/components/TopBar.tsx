import { isEnded } from "../interviewUi";
import type { Phase } from "../types";

interface TopBarProps {
  elapsedSeconds: number;
  phase: Phase | "lobby";
  frozen: boolean;
  recordingLabel: string;
  sharing: boolean;
  onShareScreen: () => void;
  onStopSharing: () => void;
  onLeave: () => void;
  remainingSeconds: number;
  listening: boolean;
}

function clock(elapsed: number): string {
  const safe = Math.max(0, Math.min(elapsed, 3600));
  const minutes = Math.floor(safe / 60);
  const seconds = safe % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

export function TopBar(props: TopBarProps) {
  const inSession = props.phase !== "lobby" && !isEnded(props.phase);
  return (
    <header className="topbar">
      <div className="topbar-main">
        <div className="brand">
          <img src="/brand/deloitte-logo-white.png" alt="Deloitte" />
        </div>
        <div className="topbar-actions">
          {inSession && (
            <div className="session-meta">
              <span className="clock">{clock(props.elapsedSeconds)} / 60:00</span>
              <span className="phase">{props.frozen ? "Candidate Q&A" : props.phase.replaceAll("_", " ")}</span>
              {props.recordingLabel && <span className="recording">{props.recordingLabel}</span>}
            </div>
          )}
          <p className="powered-by">
            <span>Powered by</span>
            <img src="/brand/tavus.svg" alt="Tavus" />
          </p>
          {inSession && (
            <>
              <button
                type="button"
                onClick={props.sharing ? props.onStopSharing : props.onShareScreen}
              >
                {props.sharing ? "Stop sharing" : "Share screen"}
              </button>
              <button type="button" className="leave" onClick={props.onLeave}>
                Leave call
              </button>
            </>
          )}
        </div>
      </div>
      {props.frozen && (
        <p className="freeze-banner">
          55:00 reached — Technical assessment locked. Final 5 minutes reserved for verbal wrap-up & Q&A
        </p>
      )}
      {inSession && !props.frozen && (
        <div className="session-strip">
          <span>{props.listening ? "Charlie is listening" : "Connecting audio…"}</span>
          <span className={props.remainingSeconds <= 120 ? "time-warning" : ""}>
            {clock(props.remainingSeconds)} remaining in this section
          </span>
        </div>
      )}
    </header>
  );
}
