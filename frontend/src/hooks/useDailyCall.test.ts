// @vitest-environment jsdom
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { useDailyCall } from "./useDailyCall";
const mock = vi.hoisted(() => ({
  handlers: {} as Record<string, () => void>,
  join: vi.fn(),
  leave: vi.fn(),
  destroy: vi.fn(),
}));
vi.mock("@daily-co/daily-js", () => ({
  default: {
    getCallInstance: () => null,
    createCallObject: () => ({
      on: (event: string, fn: () => void) => {
        mock.handlers[event] = fn;
      },
      join: mock.join,
      leave: mock.leave,
      destroy: mock.destroy,
      participants: () => ({}),
      setInputDevicesAsync: vi.fn(),
    }),
  },
}));
afterEach(() => {
  vi.useRealTimers();
  vi.clearAllMocks();
  mock.handlers = {};
});
test("a dropped connection rejoins the same room, and leaving cancels retries", async () => {
  mock.join
    .mockRejectedValueOnce(new Error("network unavailable"))
    .mockImplementation(async () => {
      mock.handlers["joined-meeting"]();
    });
  mock.leave.mockResolvedValue(undefined);
  mock.destroy.mockResolvedValue(undefined);
  const audio = { current: null };
  const result = renderHook(() =>
    useDailyCall(
      "https://room.example/call",
      { onAppMessage: () => undefined },
      Promise.resolve(null),
      audio,
    ),
  );
  await waitFor(() => expect(mock.join).toHaveBeenCalledTimes(2), {
    timeout: 2500,
  });
  act(() => mock.handlers["left-meeting"]());
  await waitFor(() => expect(mock.join).toHaveBeenCalledTimes(3), {
    timeout: 2500,
  });
  expect(mock.join.mock.calls[2][0].url).toBe("https://room.example/call");
  act(() => {
    result.result.current.stopReconnecting();
    mock.handlers["left-meeting"]();
  });
  await new Promise((resolve) => setTimeout(resolve, 1200));
  expect(mock.join).toHaveBeenCalledTimes(3);
  result.unmount();
});
