import { recordUtterance } from "./api";

export interface TranscriptEvent {
  event_id: string;
  observed_at: string;
  turn_idx: number;
  role: string;
  text: string;
  inference_id?: string;
  code: string;
  terminal: string;
  diagram_xml: string;
}
type Entry = { event: TranscriptEvent; interview: string; key: string };
const open = () =>
  new Promise<IDBDatabase>((resolve, reject) => {
    const request = indexedDB.open("tavus-transcript-queue", 1);
    request.onupgradeneeded = () =>
      request.result.createObjectStore("events", { keyPath: "key" });
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
async function list(): Promise<Entry[]> {
  const db = await open();
  try {
    return await new Promise((resolve, reject) => {
      const request = db.transaction("events").objectStore("events").getAll();
      request.onsuccess = () => resolve(request.result as Entry[]);
      request.onerror = () => reject(request.error);
    });
  } finally {
    db.close();
  }
}
async function write(item: Entry | string): Promise<void> {
  const db = await open();
  try {
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction("events", "readwrite"),
        store = tx.objectStore("events");
      if (typeof item === "string") store.delete(item);
      else store.put(item);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
      tx.onabort = () => reject(tx.error);
    });
  } finally {
    db.close();
  }
}
let pendingWrite: Promise<void> = Promise.resolve();
export async function enqueueTranscript(
  interview: string,
  event: TranscriptEvent,
): Promise<void> {
  const writeEvent = pendingWrite
    .catch(() => undefined)
    .then(async () => {
      if ((await list()).length >= 5000)
        throw new Error(
          "Transcript queue is full; reconnect to save observed speech.",
        );
      await write({
        interview,
        event,
        key: `${event.observed_at}:${event.event_id}`,
      });
    });
  // A failed enqueue must not prevent previously queued events from draining.
  pendingWrite = writeEvent.catch(() => undefined);
  await writeEvent;
}
let flight: Promise<void> | null = null;
export async function drainTranscripts(): Promise<void> {
  await pendingWrite;
  if (flight) return flight;
  flight = (async () => {
    while (true) {
      const item = (await list()).sort((a, b) => a.key.localeCompare(b.key))[0];
      if (!item) return;
      await recordUtterance(item.interview, item.event);
      await write(item.key);
    }
  })();
  try {
    await flight;
  } finally {
    flight = null;
  }
}
export async function pendingTranscripts(): Promise<number> {
  await pendingWrite;
  return (await list()).length;
}
