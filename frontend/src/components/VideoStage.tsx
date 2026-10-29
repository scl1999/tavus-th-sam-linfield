import { showInterviewer } from "../interviewUi";
import { useEffect, useRef, type RefObject } from "react";

interface VideoStageProps {
  videoRef: RefObject<HTMLVideoElement>;
  preview: MediaStream | null;
  docked: boolean;
  speaking: boolean;
  connecting: boolean;
  audioBlocked: boolean;
  onResumeAudio: () => void;
}

function SelfView(props: { stream: MediaStream }) {
  const ref = useRef<HTMLVideoElement>(null);
  useEffect(() => {
    const video = ref.current;
    if (!video) {
      return;
    }
    video.srcObject = props.stream;
    void video.play().catch(() => undefined);
    return () => {
      video.srcObject = null;
    };
  }, [props.stream]);
  return (
    <div className="self-view">
      <video ref={ref} autoPlay muted playsInline aria-label="You" />
      <span>You</span>
    </div>
  );
}

export function VideoStage(props: VideoStageProps) {
  return (
    <section className={`${props.docked ? "video docked" : "video hero"}${showInterviewer(props.docked, props.speaking, props.connecting, props.audioBlocked) ? "" : " video-quiet"}`}
      aria-label="Charlie, AI interviewer" aria-hidden={!showInterviewer(props.docked, props.speaking, props.connecting, props.audioBlocked)}>
      <div className="video-frame">
        <video ref={props.videoRef} autoPlay muted playsInline />
        {props.preview && !props.docked && <SelfView stream={props.preview} />}
        {props.connecting && <p className="video-status">Connecting to Charlie…</p>}
        {props.audioBlocked && (
          <button type="button" className="hear-charlie" onClick={props.onResumeAudio}>
            Hear Charlie
          </button>
        )}
      </div>
      <p className="video-caption">
        <strong>Charlie</strong>
        <span>Interviewer</span>
      </p>
    </section>
  );
}
