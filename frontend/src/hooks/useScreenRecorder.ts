import { useEffect, useRef, useState, type RefObject } from "react";
import type { DailyCall } from "@daily-co/daily-js";
import { drainRecordingQueue, enqueueRecording } from "../recordingQueue";

interface CaptureHandles {
  label: string;
  sharing: boolean;
  preview: MediaStream | null;
  localMedia: Promise<MediaStream | null> | null;
  arm: () => void;
  shareScreen: () => void;
  stopSharing: () => Promise<void>;
  release: () => Promise<void>;
}
export function useScreenRecorder(
  id: string | null,
  active: boolean,
  call?: RefObject<DailyCall | null>,
): CaptureHandles {
  const recorder = useRef<MediaRecorder | null>(null);
  const screen = useRef<MediaStream | null>(null);
  const camera = useRef<MediaStream | null>(null);
  const captureGeneration = useRef(0);
  const pendingStop = useRef<Promise<void> | null>(null);
  const [localMedia, setLocalMedia] =
    useState<Promise<MediaStream | null> | null>(null);
  const [preview, setPreview] = useState<MediaStream | null>(null);
  const [sharing, setSharing] = useState(false);
  const [label, setLabel] = useState("");
  const error = (reason: unknown) =>
    setLabel(
      reason instanceof Error
        ? reason.message
        : "Screen recording upload is incomplete",
    );
  const stopSharing = async () => {
    screen.current?.getTracks().forEach((track) => track.stop());
    screen.current = null;
    setSharing(false);
    try {
      call?.current?.stopScreenShare();
    } catch {
      setLabel("Call disconnected; local sharing stopped");
    }
    if (recorder.current && recorder.current.state !== "inactive")
      recorder.current.stop();
    try {
      await pendingStop.current;
    } finally {
      pendingStop.current = null;
    }
    await drainRecordingQueue();
    setLabel("");
  };
  const release = async () => {
    captureGeneration.current += 1;
    camera.current?.getTracks().forEach((track) => track.stop());
    camera.current = null;
    setPreview(null);
    setLocalMedia(null);
    await stopSharing();
  };
  const arm = () => {
    setLabel("");
    const generation = ++captureGeneration.current;
    const pending = navigator.mediaDevices
      .getUserMedia({ audio: true, video: true })
      .then((stream) => {
        if (generation !== captureGeneration.current) {
          stream.getTracks().forEach((track) => track.stop());
          return null;
        }
        camera.current = stream;
        setPreview(stream);
        return stream;
      })
      .catch(() => {
        setLabel(
          "Camera or microphone unavailable. Check browser permissions, then retry.",
        );
        return null;
      });
    setLocalMedia(pending);
  };
  const shareScreen = () => {
    if (
      !id ||
      !call?.current ||
      sharing ||
      recorder.current?.state === "recording"
    )
      return;
    const generation = captureGeneration.current;
    void navigator.mediaDevices
      .getDisplayMedia({ video: true })
      .then(async (stream) => {
        if (generation !== captureGeneration.current) {
          stream.getTracks().forEach((track) => track.stop());
          return;
        }
        screen.current = stream;
        const mime = ["video/webm;codecs=vp8", "video/webm", "video/mp4"].find(
          (value) => MediaRecorder.isTypeSupported(value),
        );
        if (!mime) {
          stream.getTracks().forEach((track) => track.stop());
          throw new Error("Screen recording is unavailable in this browser");
        }
        const segment = crypto.randomUUID();
        let sequence = 0;
        let interrupted = false;
        let queue = enqueueRecording({
          interview: id,
          segment,
          kind: "create",
          sequence: -1,
          mime,
        });
        void queue.catch(error);
        const media = new MediaRecorder(stream, {
          mimeType: mime,
          videoBitsPerSecond: 2_000_000,
        });
        recorder.current = media;
        await call.current!.startScreenShare({ mediaStream: stream });
        pendingStop.current = new Promise<void>((resolve, reject) => {
          media.ondataavailable = (event) => {
            if (!event.data.size) return;
            const index = sequence++;
            queue = queue.then(() =>
              enqueueRecording({
                interview: id,
                segment,
                kind: "chunk",
                sequence: index,
                payload: event.data,
              }),
            );
            void queue.then(() => drainRecordingQueue()).catch(error);
          };
          media.onstop = () => {
            if (interrupted || sequence === 0) {
              void queue
                .then(() => drainRecordingQueue())
                .then(
                  () =>
                    reject(
                      new Error(
                        "Screen recording is incomplete; no valid final segment was received.",
                      ),
                    ),
                  reject,
                );
              return;
            }
            queue = queue.then(() =>
              enqueueRecording({
                interview: id,
                segment,
                kind: "finalize",
                sequence: 1_000_000,
                count: sequence,
              }),
            );
            void queue.then(() => drainRecordingQueue()).then(resolve, reject);
          };
          media.onerror = () => {
            interrupted = true;
            screen.current?.getTracks().forEach((track) => track.stop());
            screen.current = null;
            setSharing(false);
            try {
              call.current?.stopScreenShare();
            } catch {
              /* local capture is already stopped */
            }
            if (media.state !== "inactive") media.stop();
            reject(
              new Error(
                "Screen recording stopped unexpectedly; segment is incomplete.",
              ),
            );
          };
        });
        // Observe rejection immediately even if the user has not pressed stop yet.
        void pendingStop.current.catch(error);
        stream.getVideoTracks()[0]?.addEventListener(
          "ended",
          () => {
            void stopSharing().catch(error);
          },
          { once: true },
        );
        media.start(4000);
        setSharing(true);
        setLabel("Recording screen video only");
      })
      .catch((reason) => {
        screen.current?.getTracks().forEach((track) => track.stop());
        screen.current = null;
        if (recorder.current?.state === "inactive") pendingStop.current = null;
        setSharing(false);
        error(reason);
      });
  };
  const releaseRef = useRef(release);
  releaseRef.current = release;
  useEffect(() => {
    if (!active) void releaseRef.current().catch(error);
  }, [active]);
  useEffect(() => {
    const retry = () => {
      void drainRecordingQueue().catch(error);
    };
    window.addEventListener("online", retry);
    retry();
    return () => {
      window.removeEventListener("online", retry);
      void releaseRef.current().catch(error);
    };
  }, []);
  return {
    label,
    sharing,
    preview,
    localMedia,
    arm,
    shareScreen,
    stopSharing,
    release,
  };
}
