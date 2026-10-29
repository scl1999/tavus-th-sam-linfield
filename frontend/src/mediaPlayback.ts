export type RemoteSlot = "video" | "audio";

const SILENT_WAV =
  "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAgD4AAAB9AAACABAAZGF0YQAAAAA=";

export interface PlaybackElement {
  muted: boolean;
  volume: number;
  src: string;
  srcObject: MediaProvider | null;
  play: () => Promise<void>;
}

export function remotePlaybackSlot(
  local: boolean,
  kind: string,
  trackType: string,
): RemoteSlot | null {
  if (local || trackType === "screenVideo") {
    return null;
  }
  if (trackType === "audio" || trackType === "screenAudio" || kind === "audio") {
    return "audio";
  }
  if (trackType === "video" || kind === "video") {
    return "video";
  }
  return null;
}

export function unlockPlayback(audio: PlaybackElement): void {
  audio.muted = false;
  audio.volume = 1;
  if (!audio.srcObject) {
    audio.src = SILENT_WAV;
  }
  void audio.play().catch(() => undefined);
}
