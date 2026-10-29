export interface LocalDraft {
  value: string;
  revision: number;
  acknowledged?: boolean;
}
export type LocalWork = Record<string, LocalDraft>;
export function loadWork(id: string): LocalWork {
  try {
    const value: unknown = JSON.parse(
      localStorage.getItem(`tavus-work:${id}`) ?? "{}",
    );
    if (!value || typeof value !== "object" || Array.isArray(value)) return {};
    return Object.fromEntries(
      Object.entries(value).filter(
        ([, entry]) =>
          entry &&
          typeof entry === "object" &&
          typeof entry.value === "string" &&
          Number.isSafeInteger(entry.revision) &&
          entry.revision > 0,
      ),
    );
  } catch {
    return {};
  }
}
export function storeWork(id: string, work: LocalWork): void {
  localStorage.setItem(`tavus-work:${id}`, JSON.stringify(work));
}

interface ServerWork {
  drafts: Record<string, string>;
  whiteboards: Record<string, string>;
  revisions: Record<string, number>;
}
export function savedValue(
  key: string,
  server: ServerWork,
): string | undefined {
  return key.startsWith("code:")
    ? server.drafts[key.slice(5)]
    : server.whiteboards[key.slice(6)];
}
export function mergeAcknowledged(
  local: LocalWork,
  server: ServerWork,
): LocalWork {
  const next = { ...local };
  for (const [key, revision] of Object.entries(server.revisions)) {
    const value = savedValue(key, server);
    const entry = next[key];
    if (value === undefined) continue;
    if (
      !entry ||
      (revision >= entry.revision &&
        (entry.acknowledged || entry.value === value))
    ) {
      next[key] = { value, revision, acknowledged: true };
    }
  }
  return next;
}
export function isPending(
  key: string,
  draft: LocalDraft,
  server: ServerWork,
): boolean {
  return (
    key !== "language" &&
    (draft.revision > (server.revisions[key] ?? 0) ||
      draft.value !== savedValue(key, server))
  );
}
