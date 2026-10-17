// SPDX-License-Identifier: MIT


export class ChunkWindow {
  constructor(count, load, size, { countLimit = 16, byteLimit = 4 << 20, concurrency = 6 } = {}) {
    this.count = count; this.load = load; this.size = size;
    this.countLimit = countLimit; this.byteLimit = byteLimit; this.concurrency = concurrency;
    this.pending = new Map(); this.scheduled = 0; this.consumed = 0;
    this.reserved = 0; this.inFlight = 0; this.closed = false;
    this.stats = { maxPending: 0, maxReservedBytes: 0, maxInFlight: 0, chunks: 0, orderedWaitMs: 0 };
    this.pump();
  }
  pump() {
    while (!this.closed && this.scheduled < this.count && this.pending.size < this.countLimit
        && this.inFlight < this.concurrency) {
      const position = this.scheduled;
      const decoded = this.size(position);
      const reservation = decoded + 300000;
      if (this.reserved + reservation > this.byteLimit) break;
      this.scheduled++; this.inFlight++; this.reserved += reservation;
      const entry = { reservation };
      this.pending.set(position, entry);
      this.stats.maxPending = Math.max(this.stats.maxPending, this.pending.size);
      this.stats.maxReservedBytes = Math.max(this.stats.maxReservedBytes, this.reserved);
      this.stats.maxInFlight = Math.max(this.stats.maxInFlight, this.inFlight);
      entry.promise = Promise.resolve().then(() => {
        if (this.closed) throw new Error('Download cancelled');
        return this.load(position);
      }).then(
        data => ({ data }), error => ({ error }),
      ).then(result => {
        if (!this.closed) {
          this.inFlight--; this.reserved -= 300000; entry.reservation = decoded;
          this.stats.chunks++; this.pump();
        }
        return result;
      });
    }
  }
  async next() {
    if (this.closed || this.consumed >= this.count) throw new Error('Chunk window is closed');
    const entry = this.pending.get(this.consumed);
    if (!entry) throw new Error('Chunk window cannot make progress');
    const started = performance.now();
    const result = await entry.promise;
    this.stats.orderedWaitMs += performance.now() - started;
    if (this.closed) throw new Error('Download cancelled');
    this.pending.delete(this.consumed++); this.reserved -= entry.reservation;
    this.pump();
    if (result.error) throw result.error;
    return result.data;
  }
  close() { this.closed = true; this.pending.clear(); this.reserved = 0; }
}
