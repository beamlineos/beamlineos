// SPDX-License-Identifier: MIT
import { HttpError, getBytes, publication, indexBytes, sha256 } from './publication.mjs';
import { Reader } from './reader.mjs';
import { ChunkWindow } from './prefetch.mjs';

const immutable = 'public, max-age=31536000, immutable, no-transform';
let activeDownloads = 0;

function selection(request, size, hash, type, filename) {
  const etag = `"sha256-${hash}"`;
  const headers = new Headers({ 'Content-Type': type, 'Accept-Ranges': 'bytes', ETag: etag,
    'Cache-Control': immutable, 'X-Content-Type-Options': 'nosniff' });
  if (filename) headers.set('Content-Disposition', `attachment; filename="${filename}"`);
  const matches = request.headers.get('If-None-Match')?.split(',').map(tag => tag.trim().replace(/^W\//, ''));
  if (matches?.some(tag => tag === '*' || tag === etag)) return { headers, status: 304 };
  let start = 0, length = size, status = 200;
  const range = request.headers.get('Range');
  if (request.method === 'GET' && range && (!request.headers.has('If-Range') || request.headers.get('If-Range') === etag)) {
    
    const match = /^bytes=(\d*)-(\d*)$/.exec(range);
    if (match) {
      let end;
      if (!match[1]) {
        const suffix = Number(match[2]);
        start = Math.max(0, size - suffix); end = size - 1;
        if (!match[2] || !Number.isSafeInteger(suffix) || suffix <= 0) start = size;
      } else { start = Number(match[1]); end = match[2] ? Number(match[2]) : size - 1; }
      if (!Number.isSafeInteger(start) || !Number.isSafeInteger(end) || start >= size || end < start) {
        headers.set('Content-Range', `bytes */${size}`);
        headers.set('Cache-Control', 'no-store');
        return { headers, status: 416 };
      }
      end = Math.min(end, size - 1); length = end - start + 1; status = 206;
      headers.set('Content-Range', `bytes ${start}-${end}/${size}`);
    }
  }
  headers.set('Content-Length', String(length));
  return { headers, status, start, length };
}

function smallFile(request, bytes, hash, type) {
  const selected = selection(request, bytes.length, hash, type);
  const empty = request.method === 'HEAD' || selected.status === 304 || selected.status === 416;
  return new Response(empty ? null : bytes.subarray(selected.start, selected.start + selected.length), selected);
}

async function artifact(request, env, release, file, filename) {
  const selected = selection(request, file.size, file.sha256, 'application/octet-stream', filename);
  if (request.method === 'HEAD' || selected.status === 304 || selected.status === 416) return new Response(null, selected);
  if (activeDownloads >= 4) throw new HttpError(503, 'Image reader busy; retry shortly');
  activeDownloads++;
  let reader, window, finished = false;
  const started = performance.now();
  const metrics = { requests: 0, cacheHits: 0, headerWaitMs: 0, encodedBytes: 0 };
  const benchmark = env.BENCHMARK_MODE === 'true';
  const countLimit = benchmark ? Number(request.headers.get('X-Beamline-Prefetch') || 16) : 16;
  const legacy = benchmark && request.headers.get('X-Beamline-Scheduling') === 'legacy';
  if (![4, 16, 32].includes(countLimit)) { activeDownloads--; throw new HttpError(400, 'Invalid prefetch window'); }
  const active = new Set(), pending = new Map();
  const finish = (outcome = 'complete') => {
    if (finished) return;
    finished = true;
    for (const controller of active) controller.abort();
    pending.clear(); window?.close();
    if (benchmark) console.log(JSON.stringify({ event: 'image-download', filename, outcome,
      bytes: selected.length, prefetch: countLimit, scheduling: legacy ? 'legacy' : 'rolling',
      transport: env.IMAGE_TRANSPORT || 'public', wallMs: performance.now() - started,
      ...metrics, window: window?.stats, wasmBytes: reader?.w?.memory.buffer.byteLength }));
    reader?.close(); activeDownloads--;
  };
  try {
    reader = new Reader(await indexBytes(env, release, file), file.size);
    const parts = reader.plan(selected.start, selected.length);
    let scheduled = 0, consumed = 0;
    const count = parts.length / 3;
    const chunk = async position => {
      const number = parts[position * 3];
      const id = reader.id(number);
      const controller = new AbortController(); active.add(controller);
      try {
        const encoded = await getBytes(env, `store/${id.slice(0, 4)}/${id}.cacnk`, 300000, { signal: controller.signal, metrics });
        if (finished) throw new Error('Download cancelled');
        const plain = reader.decode(number, encoded);
        return plain.subarray(parts[position * 3 + 1], parts[position * 3 + 1] + parts[position * 3 + 2]);
      } finally { active.delete(controller); }
    };
    
    
    if (!legacy) window = new ChunkWindow(count, chunk, position => reader.size(parts[position * 3]), { countLimit });
    let first = legacy ? await chunk(0) : await window.next();
    if (legacy) { pending.set(0, Promise.resolve({ data: first })); scheduled = 1; }
    let firstPending = true;
    const body = new ReadableStream({
      async pull(controller) {
        try {
          while (legacy && scheduled < count && pending.size < countLimit) {
            const position = scheduled++;
            pending.set(position, chunk(position).then(data => ({ data }), error => ({ error })));
          }
          let data;
          if (legacy) {
            const result = await pending.get(consumed);
            pending.delete(consumed);
            if (result.error) throw result.error;
            data = result.data;
          } else {
            data = firstPending ? first : await window.next();
          }
          firstPending = false; first = null; consumed++;
          controller.enqueue(data);
          if (consumed === count) { controller.close(); finish(); }
        } catch (error) { console.error('Image stream failed:', error.message); finish('error'); controller.error(error); }
      },
      cancel() { finish('cancelled'); },
    });
    const fixed = new FixedLengthStream(selected.length);
    body.pipeTo(fixed.writable).catch(() => finish('error'));
    return new Response(fixed.readable, selected);
  } catch (error) { finish('error'); throw error; }
}

async function route(request, env) {
  if (env.BENCHMARK_MODE === 'true') {
    const transport = request.headers.get('X-Beamline-Transport') || 'public';
    if (!['public', 'r2'].includes(transport)) throw new HttpError(400, 'Invalid transport');
    env = { ...env, IMAGE_TRANSPORT: transport };
  }
  const url = new URL(request.url);
  if (!['GET', 'HEAD'].includes(request.method)) return new Response('Method not allowed\n', {
    status: 405, headers: { Allow: 'GET, HEAD', 'Cache-Control': 'no-store' } });
  if (url.pathname === '/healthz') return new Response(request.method === 'HEAD' ? null : 'ok\n', {
    headers: { 'Cache-Control': 'no-store', 'Content-Type': 'text/plain' } });
  if (url.pathname === '/') return env.ASSETS.fetch(request);
  if (/^\/snapshots(?:\/\d{8}\.\d{4}(?:\/(?:aarch64|x86_64)(?:\/update)?)?)?\/?$/.test(url.pathname)) {
    try {
      const directory = url.pathname.endsWith('/') ? url.pathname : url.pathname + '/';
      const bytes = await getBytes(env, 'site' + directory + 'index.html', 4 << 20, { missing: 404, cacheTtl: 60 });
      if (directory !== url.pathname) {
        url.pathname = directory;
        return new Response(null, { status: 308, headers: { Location: url.href, 'Cache-Control': 'public, max-age=60' } });
      }
      return new Response(request.method === 'HEAD' ? null : bytes, { headers: {
        'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'public, max-age=60',
        'Content-Security-Policy': "default-src 'none'; base-uri 'none'; frame-ancestors 'none'",
        'X-Content-Type-Options': 'nosniff',
      } });
    } catch (error) {
      if (error.status !== 404 || !['/snapshots', '/snapshots/'].includes(url.pathname)) throw error;
      return env.ASSETS.fetch(request);
    }
  }
  const match = /^\/snapshots\/(\d{8}\.\d{4})\/(aarch64|x86_64)\/(publication\.json(?:\.gpg)?|virt-[a-z0-9_]+\.install\.raw\.zst|update\/[A-Za-z0-9][A-Za-z0-9._-]*)$/.exec(url.pathname);
  if (!match) {
    if (url.pathname.startsWith('/snapshots/')) throw new HttpError(404, 'Not found');
    return env.ASSETS.fetch(request);
  }
  const [, snapshot, arch, name] = match;
  const release = await publication(env, snapshot, arch);
  if (name === 'publication.json' || name === 'publication.json.gpg') {
    const bytes = name.endsWith('.gpg') ? release.signature : release.bytes;
    return smallFile(request, bytes, await sha256(bytes), name.endsWith('.gpg') ? 'application/pgp-signature' : 'application/json');
  }
  if (Object.hasOwn(release.manifest.metadata, name)) {
    const bytes = await getBytes(env, release.prefix + name, 256 << 10);
    const hash = release.manifest.metadata[name];
    if (await sha256(bytes) !== hash) throw new HttpError(502, 'Metadata digest mismatch');
    return smallFile(request, bytes, hash, name.endsWith('.gpg') ? 'application/pgp-signature' : 'text/plain');
  }
  if (!Object.hasOwn(release.manifest.artifacts, name)) throw new HttpError(404, 'Not found');
  return artifact(request, env, release, release.manifest.artifacts[name], name.split('/').at(-1));
}

export default {
  async fetch(request, env) {
    try { return await route(request, env); }
    catch (error) {
      const status = error instanceof HttpError ? error.status : 502;
      if (status >= 500) console.error('Image request failed:', error.message);
      return new Response(request.method === 'HEAD' ? null : (status === 404 ? 'Not found\n' : 'Image service unavailable\n'), {
        status, headers: { 'Cache-Control': 'no-store', 'Content-Type': 'text/plain',
          ...(status === 503 ? { 'Retry-After': '5' } : {}) },
      });
    }
  },
};
