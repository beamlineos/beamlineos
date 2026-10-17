// SPDX-License-Identifier: MIT
import { createMessage, readKey, readSignature, verify } from 'openpgp';
import publicKey from '../../files/keys/dev/update/import-pubring.pgp';

export class HttpError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}
export const sha256 = async bytes => Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)),
  byte => byte.toString(16).padStart(2, '0')).join('');



class Cache {
  constructor(limit) { this.limit = limit; this.bytes = 0; this.entries = new Map(); this.pending = new Map(); }
  async get(key, load) {
    if (this.entries.has(key)) {
      const entry = this.entries.get(key);
      this.entries.delete(key); this.entries.set(key, entry);
      return entry.value;
    }
    if (this.pending.has(key)) return this.pending.get(key);
    if (this.pending.size >= 16) throw new HttpError(503, 'Metadata reader busy');
    const promise = (async () => {
      const entry = await load();
      while (this.bytes + entry.size > this.limit && this.entries.size) {
        const oldest = this.entries.keys().next().value;
        this.bytes -= this.entries.get(oldest).size; this.entries.delete(oldest);
      }
      if (entry.size <= this.limit) { this.entries.set(key, entry); this.bytes += entry.size; }
      return entry.value;
    })();
    this.pending.set(key, promise);
    try { return await promise; } finally { this.pending.delete(key); }
  }
}
const manifests = new Cache(2 << 20);
const indexes = new Cache(8 << 20);
let verificationKey;

function storeUrl(env, key) {
  const origin = new URL(env.STORE_ORIGIN);
  if ((origin.protocol !== 'https:' && !(origin.protocol === 'http:' && origin.hostname === '127.0.0.1'))
      || origin.username || origin.password || origin.search || origin.hash || origin.pathname !== '/') {
    throw new Error('STORE_ORIGIN must be an HTTPS origin');
  }
  return new URL(key, origin).href;
}

export async function getBytes(env, key, limit, { missing = 502, signal, cacheTtl = 31536000 } = {}) {
  const deadline = new AbortController();
  
  
  const timer = setTimeout(() => deadline.abort(), 30000);
  try {
    const response = await fetch(storeUrl(env, key), { redirect: 'manual',
      cf: { cacheEverything: true, cacheTtlByStatus: { '200': cacheTtl, '400-599': -1 } },
      signal: signal ? AbortSignal.any([signal, deadline.signal]) : deadline.signal });
    if (response.status !== 200) {
      await response.body?.cancel();
      throw new HttpError(response.status === 404 ? missing : 502, 'Store object unavailable');
    }
    if (Number(response.headers.get('Content-Length')) > limit) {
      await response.body?.cancel(); throw new HttpError(502, 'Store object too large');
    }
    const reader = response.body.getReader();
    const pieces = []; let length = 0;
    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        length += value.length;
        if (length > limit) { await reader.cancel(); throw new HttpError(502, 'Store object too large'); }
        pieces.push(value);
      }
    } finally { reader.releaseLock(); }
    const bytes = new Uint8Array(length); let at = 0;
    for (const piece of pieces) { bytes.set(piece, at); at += piece.length; }
    return bytes;
  } finally { clearTimeout(timer); }
}

const digest = value => typeof value === 'string' && /^[0-9a-f]{64}$/.test(value);
const record = value => value !== null && typeof value === 'object' && !Array.isArray(value);
export function validateManifest(value, snapshot, arch) {
  const chunking = value?.chunking;
  if (!record(value) || value.schema !== 1 || value.snapshot !== snapshot || value.arch !== arch
      || chunking?.desync_version !== '1.1.4' || chunking.digest !== 'sha512-256'
      || JSON.stringify(chunking.sizes_kib) !== '[16,64,256]' || chunking.store !== 'store/'
      || !digest(value.installer_uncompressed_sha256)) throw new HttpError(502, 'Invalid publication');
  if (!record(value.metadata) || Object.keys(value.metadata).sort().join(',') !== 'update/SHA256SUMS,update/SHA256SUMS.gpg'
      || !Object.values(value.metadata).every(digest) || !record(value.artifacts)
      || !Object.hasOwn(value.artifacts, `virt-${arch}.install.raw.zst`)
      || Object.keys(value.artifacts).length > 128) throw new HttpError(502, 'Invalid publication files');
  for (const [name, file] of Object.entries(value.artifacts)) {
    if ((name !== `virt-${arch}.install.raw.zst` && !/^update\/[A-Za-z0-9][A-Za-z0-9._-]*$/.test(name))
        || !record(file) || !digest(file.sha256) || !digest(file.index_sha256)
        || file.index !== `indexes/${file.sha256}.caibx` || !Number.isSafeInteger(file.size) || file.size <= 0) {
      throw new HttpError(502, 'Invalid publication artifact');
    }
  }
  return value;
}

export async function publication(env, snapshot, arch) {
  const prefix = `snapshots/${snapshot}/${arch}/`;
  return manifests.get(storeUrl(env, prefix), async () => {
    const bytes = await getBytes(env, prefix + 'publication.json', 256 << 10, { missing: 404 });
    const signature = await getBytes(env, prefix + 'publication.json.gpg', 16 << 10);
    verificationKey ??= readKey({ binaryKey: publicKey });
    const result = await verify({ message: await createMessage({ binary: bytes }),
      signature: await readSignature({ binarySignature: signature }), verificationKeys: await verificationKey,
      format: 'binary' });
    if (result.signatures.length !== 1) throw new HttpError(502, 'Invalid publication signature');
    await result.signatures[0].verified;
    const manifest = validateManifest(JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes)), snapshot, arch);
    return { value: { manifest, bytes, signature, prefix }, size: bytes.length * 4 + signature.length };
  });
}

export async function indexBytes(env, release, file) {
  return indexes.get(storeUrl(env, release.prefix + file.index), async () => {
    const bytes = await getBytes(env, release.prefix + file.index, 4 << 20);
    if (await sha256(bytes) !== file.index_sha256) throw new HttpError(502, 'Index digest mismatch');
    return { value: bytes, size: bytes.length };
  });
}
