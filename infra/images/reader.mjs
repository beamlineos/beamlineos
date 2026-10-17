// SPDX-License-Identifier: BSD-3-Clause
import module from './reader.wasm';



export class Reader {
  constructor(bytes, size) {
    this.w = new WebAssembly.Instance(module, {}).exports;
    const ptr = this.w.alloc(bytes.length);
    try {
      this.view(ptr, bytes.length).set(bytes);
      this.handle = this.w.load_index(ptr, bytes.length);
      if (!this.handle || this.w.image_size(this.handle) !== BigInt(size)) {
        if (this.handle) this.w.drop_index(this.handle);
        this.handle = 0;
        throw new Error('Invalid index size or format');
      }
    } finally { this.w.free(ptr, bytes.length); }
  }
  view(ptr, length) { return new Uint8Array(this.w.memory.buffer, ptr, length); }
  plan(start, length) {
    const capacity = this.w.chunk_count(this.handle);
    const ptr = this.w.alloc(capacity * 12);
    try {
      const count = this.w.read_plan(this.handle, BigInt(start), BigInt(length), ptr, capacity);
      if (count < 0) throw new Error('Invalid read range');
      return new Uint32Array(this.w.memory.buffer, ptr, count * 3).slice();
    } finally { this.w.free(ptr, capacity * 12); }
  }
  id(number) {
    return Array.from(this.view(this.w.chunk_id(this.handle, number), 32), byte => byte.toString(16).padStart(2, '0')).join('');
  }
  size(number) {
    return Number(this.w.chunk_end(this.handle, number) - this.w.chunk_start(this.handle, number));
  }
  decode(number, encoded) {
    const expected = this.size(number);
    const ptr = this.w.alloc(encoded.length); let output = 0;
    try {
      this.view(ptr, encoded.length).set(encoded);
      output = this.w.decode_chunk(ptr, encoded.length, expected);
      if (!output || !this.w.verify_chunk(this.handle, number, output, expected)) throw new Error('Chunk decoding or digest verification failed');
      return this.view(output, expected).slice();
    } finally {
      this.w.free(ptr, encoded.length);
      if (output) this.w.free(output, expected);
    }
  }
  close() {
    if (this.handle) this.w.drop_index(this.handle);
    this.handle = 0; this.w = null;
  }
}
