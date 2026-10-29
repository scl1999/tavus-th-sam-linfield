/** Keep context writes ordered while coalescing intermediate editor snapshots. */
export class LatestWorkspaceQueue<T> {
  private pending: T | null = null;
  private running = false;
  constructor(private readonly send: (value: T, isLatest: () => boolean) => Promise<void>) {}

  async submit(value: T): Promise<void> {
    this.pending = value;
    if (this.running) return;
    this.running = true;
    try {
      while (this.pending !== null) {
        const next = this.pending;
        this.pending = null;
        await this.send(next, () => this.pending === null);
      }
    } finally { this.running = false; }
  }
}
