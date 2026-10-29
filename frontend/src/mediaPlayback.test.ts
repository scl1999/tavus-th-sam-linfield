import { expect, test } from "vitest";

import { remotePlaybackSlot, unlockPlayback, type PlaybackElement } from "./mediaPlayback";

test("remote interviewer audio and video are played", () => {
  expect(remotePlaybackSlot(false, "audio", "audio")).toBe("audio");
  expect(remotePlaybackSlot(false, "video", "video")).toBe("video");
  expect(remotePlaybackSlot(false, "audio", "screenAudio")).toBe("audio");
});

test("local media and screen video are not played on Charlie's stage", () => {
  expect(remotePlaybackSlot(true, "audio", "audio")).toBeNull();
  expect(remotePlaybackSlot(true, "video", "video")).toBeNull();
  expect(remotePlaybackSlot(false, "video", "screenVideo")).toBeNull();
});

test("unlock keeps the shared audio element audible", () => {
  const plays: number[] = [];
  const audio: PlaybackElement = {
    muted: true,
    volume: 0,
    src: "",
    srcObject: null,
    play: () => {
      plays.push(1);
      return Promise.resolve();
    },
  };
  unlockPlayback(audio);
  expect(audio.muted).toBe(false);
  expect(audio.volume).toBe(1);
  expect(audio.src.startsWith("data:audio/wav")).toBe(true);
  expect(plays).toEqual([1]);
});

test("unlock leaves an existing stream in place", () => {
  const stream = { getTracks: () => [] } as unknown as MediaStream;
  const audio: PlaybackElement = {
    muted: true,
    volume: 0,
    src: "",
    srcObject: stream,
    play: () => Promise.resolve(),
  };
  unlockPlayback(audio);
  expect(audio.src).toBe("");
  expect(audio.srcObject).toBe(stream);
});
