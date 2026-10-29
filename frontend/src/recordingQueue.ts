import {
  createRecording,
  finalizeRecording,
  uploadRecordingChunk,
} from "./api";

interface PendingRecording {
  key: string;
  interview: string;
  segment: string;
  sequence: number;
  kind: "create" | "chunk" | "finalize";
  mime?: string;
  payload?: Blob;
  count?: number;
}
const database = () =>
  new Promise<IDBDatabase>((resolve, reject) => {
    const request = indexedDB.open("tavus-screen-uploads", 1);
    request.onupgradeneeded = () =>
      request.result.createObjectStore("pending", { keyPath: "key" });
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
async function all(): Promise<PendingRecording[]> {
  const db = await database();
  try {
    return await new Promise((resolve, reject) => {
      const request = db.transaction("pending").objectStore("pending").getAll();
      request.onsuccess = () => resolve(request.result as PendingRecording[]);
      request.onerror = () => reject(request.error);
    });
  } finally {
    db.close();
  }
}
async function write(value: PendingRecording | string): Promise<void> {
  const db = await database();
  try {
    await new Promise<void>((resolve, reject) => {
      const transaction = db.transaction("pending", "readwrite");
      const store = transaction.objectStore("pending");
      if (typeof value === "string") store.delete(value);
      else store.put(value);
      transaction.oncomplete = () => resolve();
      transaction.onerror = () => reject(transaction.error);
    });
  } finally {
    db.close();
  }
}
export async function enqueueRecording(
  item: Omit<PendingRecording, "key">,
): Promise<void> {
  const size = (await all()).reduce(
    (sum, row) => sum + (row.payload?.size ?? 0),
    0,
  );
  if (size + (item.payload?.size ?? 0) > 100 * 1024 * 1024)
    throw new Error(
      "Screen recording upload queue is full. Stop sharing and restore the connection.",
    );
  await write({
    ...item,
    key: `${item.segment}:${String(item.sequence + 1).padStart(10, "0")}`,
  });
}
let flight: Promise<void> | null = null;
export async function drainRecordingQueue(): Promise<void> {
  if (flight) return flight;
  flight = (async () => {
    while (true) {
      const item = (await all()).sort((a, b) => a.key.localeCompare(b.key))[0];
      if (!item) return;
      let complete = false;
      for (let attempt = 0; attempt < 4; attempt++) {
        try {
          if (item.kind === "create")
            await createRecording(item.interview, item.segment, item.mime!);
          else if (item.kind === "finalize")
            await finalizeRecording(item.interview, item.segment, item.count!);
          else {
            const digest = await crypto.subtle.digest(
              "SHA-256",
              await item.payload!.arrayBuffer(),
            );
            const checksum = Array.from(new Uint8Array(digest), (value) =>
              value.toString(16).padStart(2, "0"),
            ).join("");
            await uploadRecordingChunk(
              item.interview,
              item.segment,
              item.sequence,
              checksum,
              item.payload!,
            );
          }
          complete = true;
          break;
        } catch (reason) {
          if (attempt === 3) throw reason;
          await new Promise((resolve) =>
            window.setTimeout(resolve, 1000 * 2 ** attempt),
          );
        }
      }
      if (complete) await write(item.key);
    }
  })();
  try {
    await flight;
  } finally {
    flight = null;
  }
}
export async function pendingRecordingCount(): Promise<number> {
  return (await all()).length;
}
