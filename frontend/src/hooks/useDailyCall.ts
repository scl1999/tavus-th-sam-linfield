import DailyIframe, {
  type DailyCall,
  type DailyParticipant,
} from "@daily-co/daily-js";
import { useEffect, useRef, useState, type RefObject } from "react";

import { speakingState } from "../interviewUi";
import { parseConversationEvent } from "../toolMessages";
import { remotePlaybackSlot } from "../mediaPlayback";

interface DailyHandlers {
  onAppMessage: (data: unknown) => void;
  onError?: (error: unknown) => void;
}

function liveTrack(
  state:
    | { track?: MediaStreamTrack; persistentTrack?: MediaStreamTrack }
    | undefined,
) {
  return state?.track ?? state?.persistentTrack;
}

export function useDailyCall(
  url: string | null,
  handlers: DailyHandlers,
  localMedia: Promise<MediaStream | null> | null,
  audioElement: RefObject<HTMLAudioElement>,
): {
  call: DailyCall | null;
  joined: boolean;
  readyForAssessment: boolean;
  speaking: boolean;
  audioBlocked: boolean;
  resumeAudio: () => void;
  stopReconnecting: () => void;
  videoElement: RefObject<HTMLVideoElement>;
} {
  const videoElement = useRef<HTMLVideoElement>(null);
  const [call, setCall] = useState<DailyCall | null>(null);
  const [joined, setJoined] = useState(false);
  const [readyForAssessment, setReadyForAssessment] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [audioBlocked, setAudioBlocked] = useState(false);
  const stopped = useRef(false);
  const handlersRef = useRef(handlers);
  const localMediaRef = useRef(localMedia);
  handlersRef.current = handlers;
  localMediaRef.current = localMedia;

  const resumeAudio = () => {
    const audio = audioElement.current;
    if (!audio) {
      return;
    }
    audio.muted = false;
    audio.volume = 1;
    void audio
      .play()
      .then(() => setAudioBlocked(false))
      .catch(() => setAudioBlocked(true));
  };

  useEffect(() => {
    if (!url) {
      setJoined(false);
      setReadyForAssessment(false);
      setSpeaking(false);
      setAudioBlocked(false);
      return;
    }
    stopped.current = false;
    let cancelled = false;
    let reconnectTimer: number | undefined;
    let attempts = 0;
    let connected = false;
    let joining = false;
    const scheduleReconnect = () => {
      if (cancelled || stopped.current || reconnectTimer !== undefined) return;
      const delay = Math.min(30000, 1000 * 2 ** Math.min(attempts++, 5));
      reconnectTimer = window.setTimeout(() => {
        reconnectTimer = undefined;
        void joinAgain();
      }, delay);
    };
    const online = () => {
      if (!connected && reconnectTimer !== undefined) {
        window.clearTimeout(reconnectTimer);
        reconnectTimer = undefined;
        scheduleReconnect();
      }
    };
    window.addEventListener("online", online);
    const existing = DailyIframe.getCallInstance();
    if (existing) {
      void existing.destroy();
    }
    const room = DailyIframe.createCallObject();
    setCall(room);

    const attach = (
      track: MediaStreamTrack | undefined,
      local: boolean,
      trackType: string,
    ) => {
      if (!track || cancelled) {
        return;
      }
      const slot = remotePlaybackSlot(local, track.kind, trackType);
      const element =
        slot === "video" ? videoElement.current : audioElement.current;
      if (!slot || !element) {
        return;
      }
      if (slot === "audio") {
        element.pause();
        element.removeAttribute("src");
        element.srcObject = new MediaStream([track]);
        element.muted = false;
        element.volume = 1;
      } else {
        element.srcObject = new MediaStream([track]);
      }
      void element
        .play()
        .then(() => {
          if (!cancelled && slot === "audio") {
            setAudioBlocked(false);
          }
        })
        .catch(() => {
          if (!cancelled && slot === "audio") {
            setAudioBlocked(true);
          }
        });
    };

    const attachParticipant = (participant: DailyParticipant) => {
      attach(liveTrack(participant.tracks.audio), participant.local, "audio");
      attach(liveTrack(participant.tracks.video), participant.local, "video");
    };

    room.on("track-started", (event) => {
      attach(event.track, Boolean(event.participant?.local), event.type);
    });
    room.on("app-message", (event) => {
      const message = parseConversationEvent(event.data);
      if (message)
        setSpeaking((current) =>
          speakingState(current, message.eventType, message.properties.role),
        );
      handlersRef.current.onAppMessage(event.data);
    });
    room.on("left-meeting", () => {
      setJoined(false);
      setReadyForAssessment(false);
      setSpeaking(false);
      connected = false;
      scheduleReconnect();
    });
    room.on("error", (event) => {
      handlersRef.current.onError?.(event);
      if (!connected && !joining) scheduleReconnect();
    });
    room.on("joined-meeting", () => {
      if (cancelled) {
        return;
      }
      connected = true;
      attempts = 0;
      if (reconnectTimer !== undefined) window.clearTimeout(reconnectTimer);
      reconnectTimer = undefined;
      setJoined(true);
      Object.values(room.participants()).forEach(attachParticipant);
    });

    const joinAgain = async () => {
      if (joining || cancelled || stopped.current) return;
      joining = true;
      const pending = localMediaRef.current ?? Promise.resolve(null);
      let winner: "media" | "timeout" = "timeout";
      const local = await Promise.race([
        pending.then((stream) => {
          winner = "media";
          return stream;
        }),
        new Promise<null>((resolve) => {
          window.setTimeout(() => resolve(null), 2000);
        }),
      ]);
      if (cancelled || stopped.current) {
        return;
      }
      const missedMedia = winner === "timeout";
      try {
        await room.join({
          url,
          videoSource: local?.getVideoTracks()[0] ?? false,
          audioSource: local?.getAudioTracks()[0] ?? false,
        });
        if (
          !cancelled &&
          local?.getAudioTracks().some((track) => track.readyState === "live")
        ) {
          setReadyForAssessment(true);
        }
      } catch (error) {
        joining = false;
        handlersRef.current.onError?.(error);
        scheduleReconnect();
        return;
      }
      joining = false;
      if (cancelled || !missedMedia) {
        return;
      }
      const late = await pending;
      if (cancelled || !late) {
        return;
      }
      try {
        await room.setInputDevicesAsync({
          videoSource: late.getVideoTracks()[0] ?? false,
          audioSource: late.getAudioTracks()[0] ?? false,
        });
        if (
          !cancelled &&
          late.getAudioTracks().some((track) => track.readyState === "live")
        ) {
          setReadyForAssessment(true);
        }
      } catch (error) {
        handlersRef.current.onError?.(error);
      }
    };
    void joinAgain();

    return () => {
      cancelled = true;
      window.removeEventListener("online", online);
      if (reconnectTimer !== undefined) window.clearTimeout(reconnectTimer);
      const audio = audioElement.current;
      if (audio) {
        audio.pause();
        audio.srcObject = null;
      }
      setJoined(false);
      setReadyForAssessment(false);
      setSpeaking(false);
      setAudioBlocked(false);
      void room.leave();
      void room.destroy();
      setCall(null);
    };
  }, [audioElement, url]);

  return {
    call,
    joined,
    readyForAssessment,
    speaking,
    audioBlocked,
    resumeAudio,
    stopReconnecting: () => {
      stopped.current = true;
    },
    videoElement,
  };
}
