// SPDX-License-Identifier: MIT
// Independent HTTP consumer; actual desync creates the chunks/index and GPG
// signs the fixtures. The production bundle runs in workerd, not a fetch mock.
import { Miniflare, Log, LogLevel } from 'miniflare';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs/promises';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '../..');
const output = path.join(root, 'out/images-worker');
const configuration = JSON.parse((await fs.readFile(path.join(output, 'wrangler.jsonc'), 'utf8'))
  .split('\n').filter(line => !line.trimStart().startsWith('//')).join('\n'));
const temporary = await fs.mkdtemp(path.join(os.tmpdir(), 'beamline-images-test-'));
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const objects = new Map(), faults = new Map(), requests = [];
let productionStore;
const bytes = Buffer.alloc(3 << 20);
let random = 0x1430;
for (let i = 0; i < bytes.length; i++) {
  random ^= random << 13; random ^= random >>> 17; random ^= random << 5;
  bytes[i] = i % 19 < 7 ? 0 : random & 255;
}
const raw = path.join(temporary, 'image.raw');
await fs.writeFile(raw, bytes);
const indexFile = path.join(temporary, 'image.caibx');
const store = path.join(temporary, 'store');
await fs.mkdir(store);
const desync = process.env.BEAMLINE_DESYNC ?? execFileSync('python3', ['-c',
  'import sys; from pathlib import Path; sys.path.insert(0, "tools"); from desync_tool import install; print(install(Path("out/images-worker-build/desync")))'],
{ cwd: root, encoding: 'utf8' }).trim();
execFileSync(desync, ['--digest', 'sha512-256', 'make', '-m', '16:64:256', '-s', store, indexFile, raw]);
const rawIndex = await fs.readFile(indexFile);
const digest = hash(bytes), indexPath = `indexes/${digest}.caibx`;
const firstId = rawIndex.subarray(72, 104).toString('hex');
const secondId = rawIndex.subarray(112, 144).toString('hex');
let id = 1000;
async function release(change = () => {}) {
  const snapshot = `20261016.${id++}`;
  const prefix = `snapshots/${snapshot}/aarch64/`;
  const filename = `posix-devel_${snapshot}.sysext.raw`;
  const metadata = Buffer.from(`${digest}  ${filename}\n`);
  const signature = Buffer.from('fixture channel signature');
  const file = { sha256: digest, size: bytes.length, index: indexPath, index_sha256: hash(rawIndex) };
  const manifest = { schema: 1, snapshot, arch: 'aarch64',
    chunking: { desync_version: '1.1.4', digest: 'sha512-256', sizes_kib: [16, 64, 256], store: 'store/' },
    installer_uncompressed_sha256: digest,
    artifacts: { [`update/${filename}`]: file, 'virt-aarch64.install.raw.zst': { ...file } },
    metadata: { 'update/SHA256SUMS': hash(metadata), 'update/SHA256SUMS.gpg': hash(signature) } };
  change(manifest);
  const marker = Buffer.from(JSON.stringify(manifest));
  const markerFile = path.join(temporary, 'publication.json');
  await fs.writeFile(markerFile, marker);
  await fs.rm(markerFile + '.gpg', { force: true });
  execFileSync('python3', ['-c', 'import sys; from pathlib import Path; sys.path.insert(0, "tools"); import publish; publish.sign_manifest(Path(sys.argv[1]))', markerFile], { cwd: root });
  objects.set(prefix + 'publication.json', marker);
  objects.set(prefix + 'publication.json.gpg', await fs.readFile(markerFile + '.gpg'));
  objects.set(prefix + indexPath, rawIndex);
  objects.set(prefix + 'update/SHA256SUMS', metadata);
  objects.set(prefix + 'update/SHA256SUMS.gpg', signature);
  return { snapshot, prefix, filename, url: '/' + prefix + 'update/' + filename, manifest };
}

const origin = http.createServer(async (request, response) => {
  const key = request.url.slice(1);
  requests.push(key);
  try {
    const fault = faults.get(key);
    if (typeof fault === 'number') { response.writeHead(fault); response.end(); return; }
    let data = objects.get(key);
    if (!data && /^store\/[0-9a-f]{4}\/[0-9a-f]{64}\.cacnk$/.test(key)) {
      const name = path.basename(key);
      try { data = await fs.readFile(path.join(store, name.slice(0, 4), name)); }
      catch (error) {
        if (!productionStore || error.code !== 'ENOENT') throw error;
        data = await fs.readFile(path.join(productionStore, name.slice(0, 4), name));
      }
    }
    if (!data) { response.writeHead(404); response.end(); return; }
    if (fault === 'corrupt') { data = Buffer.from(data); data[Math.floor(data.length / 2)] ^= 1; }
    response.writeHead(200, { 'Content-Length': data.length }); response.end(data);
  } catch { response.writeHead(404); response.end(); }
});
await new Promise(resolve => origin.listen(0, '127.0.0.1', resolve));
let mf;
let checks = 0;
const check = (condition, message) => { assert.ok(condition, message); checks++; };
try {
  const w = (await WebAssembly.instantiate(await fs.readFile(path.join(output, 'reader.wasm')), {})).instance.exports;
  const pointer = w.alloc(rawIndex.length);
  const load = data => {
    new Uint8Array(w.memory.buffer, pointer, data.length).set(data);
    return w.load_index(pointer, data.length);
  };
  const handle = load(rawIndex);
  check(handle !== 0 && w.image_size(handle) === BigInt(bytes.length), 'native caibx accepted');
  for (const mutate of [
    b => b.writeBigUInt64LE(47n, 0), b => b.writeBigUInt64LE(0n, 16),
    b => b.writeBigUInt64LE(0n, 48), b => b.writeBigUInt64LE(0n, 64),
    b => b.writeBigUInt64LE(262145n, 64), b => b.writeBigUInt64LE(0n, b.length - 8),
  ]) {
    const bad = Buffer.from(rawIndex); mutate(bad);
    check(load(bad) === 0, 'malformed caibx rejected');
  }
  check(load(rawIndex.subarray(0, -1)) === 0, 'truncated caibx rejected');
  const plan = w.alloc(12);
  check(w.read_plan(handle, BigInt(bytes.length), 1n, plan, 1) === -1, 'range past EOF');
  check(w.read_plan(handle, (1n << 64n) - 1n, 2n, plan, 1) === -1, 'range integer overflow');
  w.free(plan, 12); w.drop_index(handle); w.free(pointer, rawIndex.length);
  mf = new Miniflare({ cf: false, log: new Log(LogLevel.ERROR), telemetry: { enabled: false },
    workers: [{ config: {
      name: 'beamline-images-test', compatibilityDate: configuration.compatibility_date,
      limits: { cpuMs: configuration.limits.cpu_ms, subrequests: configuration.limits.subrequests },
      manifest: { mainModule: 'worker.mjs', modulesRoot: output, modules: {
        'worker.mjs': { type: 'esm', contents: await fs.readFile(path.join(output, 'worker.mjs'), 'utf8') },
        'reader.wasm': { type: 'wasm', contents: new Uint8Array(await fs.readFile(path.join(output, 'reader.wasm'))) },
      } },
      env: { STORE_ORIGIN: { type: 'text', value: `http://127.0.0.1:${origin.address().port}` }, ASSETS: { type: 'assets' } },
      assets: { directory: path.join(output, 'public'), hasUserWorker: true,
        runWorkerFirst: configuration.assets.run_worker_first },
    } }],
  });
  const get = (url, options) => mf.dispatchFetch('https://images.example' + url, options);
  const good = await release();
  const chunkRequests = () => requests.filter(key => key.startsWith('store/')).length;

  for (const url of ['/snapshots/invalid/aarch64/a.raw', '/snapshots/20261016.1000/aarch64/update/a%2fb.raw']) {
    check((await get(url)).status === 404, 'invalid route');
  }
  check(requests.length === 0, 'invalid routes do not consult store');
  check((await get(good.url, { method: 'POST' })).status === 405, 'method');
  check((await get('/snapshots/20261016.9999/aarch64/update/missing.raw')).status === 404, 'missing publication');
  check((await get('/' + good.prefix + 'update/missing.raw')).status === 404, 'unlisted filename');
  const retry = await release();
  const held = objects.get(retry.prefix + 'publication.json');
  objects.delete(retry.prefix + 'publication.json');
  check((await get(retry.url)).status === 404, 'uncommitted publication');
  objects.set(retry.prefix + 'publication.json', held);
  check((await get(retry.url, { method: 'HEAD' })).status === 200, 'publication appears without redeployment after 404');
  let response = await get(good.url, { method: 'HEAD' });
  check(response.status === 200 && response.headers.get('Content-Length') === String(bytes.length), 'HEAD size');
  check(chunkRequests() === 0 && !requests.includes(good.prefix + indexPath), 'HEAD has no index/chunk reads');
  const etag = response.headers.get('ETag');
  response = await get(good.url, { headers: { 'If-None-Match': `"other", W/${etag}` } });
  check(response.status === 304 && chunkRequests() === 0, 'conditional');

  response = await get(good.url);
  check(response.status === 200 && hash(Buffer.from(await response.arrayBuffer())) === digest, 'complete desync reconstruction');
  const ranges = [[0, 0], [0, 65536], [65530, 266000], [bytes.length - 1, bytes.length - 1],
    [Number(rawIndex.readBigUInt64LE(64)) - 1, Number(rawIndex.readBigUInt64LE(64)) + 1]];
  for (let i = 0; i < 20; i++) {
    random ^= random << 13; random ^= random >>> 17; random ^= random << 5;
    const start = (random >>> 0) % bytes.length;
    ranges.push([start, Math.min(start + 122345, bytes.length - 1)]);
  }
  for (const [start, end] of ranges) {
    response = await get(good.url, { headers: { Range: `bytes=${start}-${end}` } });
    check(response.status === 206 && response.headers.get('Content-Range') === `bytes ${start}-${end}/${bytes.length}`, 'range headers');
    check(Buffer.from(await response.arrayBuffer()).equals(bytes.subarray(start, end + 1)), 'range bytes');
  }
  response = await get(good.url, { headers: { Range: 'bytes=-777' } });
  check(Buffer.from(await response.arrayBuffer()).equals(bytes.subarray(-777)), 'suffix');
  response = await get(good.url, { headers: { Range: `bytes=${bytes.length - 777}-` } });
  check(Buffer.from(await response.arrayBuffer()).equals(bytes.subarray(-777)), 'open range');
  for (const range of [`bytes=${bytes.length}-`, 'bytes=2-1', 'bytes=-0', 'bytes=999999999999999999999-']) {
    response = await get(good.url, { headers: { Range: range } });
    check(response.status === 416 && response.headers.get('Content-Range') === `bytes */${bytes.length}`, 'unsatisfiable');
  }
  response = await get(good.url, { headers: { Range: 'bytes=0-10', 'If-Range': '"old"' } });
  check(response.status === 200 && hash(Buffer.from(await response.arrayBuffer())) === digest, 'If-Range mismatch');
  response = await get('/' + good.prefix + 'virt-aarch64.install.raw.zst', { method: 'HEAD' });
  check(response.headers.get('ETag') === etag, 'alias content identity');
  response = await get('/' + good.prefix + 'publication.json');
  check(Buffer.from(await response.arrayBuffer()).equals(objects.get(good.prefix + 'publication.json')), 'preserve signed manifest bytes');
  response = await get('/' + good.prefix + 'update/SHA256SUMS');
  check(Buffer.from(await response.arrayBuffer()).equals(objects.get(good.prefix + 'update/SHA256SUMS')), 'channel metadata');

  const concurrent = await Promise.all([get(good.url), get(good.url)]);
  for (const read of concurrent) check(hash(Buffer.from(await read.arrayBuffer())) === digest, 'concurrent reader');
  response = await get(good.url); await response.body.cancel();
  response = await get(good.url, { headers: { Range: 'bytes=0-127' } });
  check(Buffer.from(await response.arrayBuffer()).equals(bytes.subarray(0, 128)), 'read after cancellation');

  // More than 10,000 fast chunk reads reproduce leaked fetch-deadline timers.
  // Repeat a real desync chunk in a valid caibx; consume without buffering the
  // reconstructed image. The expected hash is computed independently here.
  let smallest = { length: Infinity }, previousEnd = 0;
  for (let at = 64; at < rawIndex.length - 40; at += 40) {
    const end = Number(rawIndex.readBigUInt64LE(at));
    if (end - previousEnd < smallest.length) smallest = { length: end - previousEnd, start: previousEnd,
      id: rawIndex.subarray(at + 8, at + 40) };
    previousEnd = end;
  }
  const repeats = 10010;
  const repeatedChunk = bytes.subarray(smallest.start, smallest.start + smallest.length);
  const expectedLongHash = createHash('sha256');
  for (let n = 0; n < repeats; n++) expectedLongHash.update(repeatedChunk);
  const longHash = expectedLongHash.digest('hex');
  const longIndex = Buffer.alloc(104 + repeats * 40);
  rawIndex.copy(longIndex, 0, 0, 64);
  for (let n = 0; n < repeats; n++) {
    longIndex.writeBigUInt64LE(BigInt((n + 1) * smallest.length), 64 + n * 40);
    smallest.id.copy(longIndex, 72 + n * 40);
  }
  rawIndex.copy(longIndex, longIndex.length - 40, rawIndex.length - 40);
  longIndex.writeBigUInt64LE(BigInt(longIndex.length - 48), longIndex.length - 16);
  const longFile = { sha256: longHash, size: repeats * smallest.length, index: `indexes/${longHash}.caibx`, index_sha256: hash(longIndex) };
  const long = await release(manifest => {
    manifest.artifacts[`update/posix-devel_${manifest.snapshot}.sysext.raw`] = longFile;
  });
  objects.set(long.prefix + longFile.index, longIndex);
  response = await get(long.url);
  const longActualHash = createHash('sha256'); let longSize = 0;
  for await (const piece of response.body) { longActualHash.update(piece); longSize += piece.length; }
  check(longSize === longFile.size && longActualHash.digest('hex') === longHash, 'more than 10,000 chunk fetches release timers');

  const badSignature = await release();
  objects.get(badSignature.prefix + 'publication.json')[1] ^= 1;
  check((await get(badSignature.url)).status === 502, 'signature rejection');
  const absent = await release();
  faults.set(absent.prefix + indexPath, 404);
  check((await get(absent.url)).status === 502, 'listed missing index is upstream failure');
  const corrupt = await release();
  faults.set(corrupt.prefix + indexPath, 'corrupt');
  check((await get(corrupt.url)).status === 502, 'index digest rejection');
  const wrongIdentity = await release(manifest => { manifest.snapshot = '20261016.0000'; });
  check((await get(wrongIdentity.url)).status === 502, 'signed publication identity rejection');
  const wrongSize = await release(manifest => { Object.values(manifest.artifacts)[0].size++; });
  check((await get(wrongSize.url)).status === 502, 'signed size disagrees with index');
  faults.set(good.prefix + 'update/SHA256SUMS', 'corrupt');
  check((await get('/' + good.prefix + 'update/SHA256SUMS')).status === 502, 'metadata digest rejection');
  faults.delete(good.prefix + 'update/SHA256SUMS');
  faults.set(`store/${firstId.slice(0, 4)}/${firstId}.cacnk`, 'corrupt');
  check((await get(good.url)).status === 502, 'corrupt first chunk');
  faults.delete(`store/${firstId.slice(0, 4)}/${firstId}.cacnk`);
  faults.set(`store/${secondId.slice(0, 4)}/${secondId}.cacnk`, 404);
  response = await get(good.url);
  await assert.rejects(() => response.arrayBuffer()); checks++;
  faults.clear();
  for (let i = 0; i < 5; i++) {
    response = await get(good.url, { headers: { Range: 'bytes=0-15' } });
    check(Buffer.from(await response.arrayBuffer()).equals(bytes.subarray(0, 16)), 'reader slots released on failure');
  }

  response = await get('/');
  const rootHtml = await response.text();
  check((rootHtml.match(/<a /g) ?? []).length === 1 && rootHtml.includes('href="/snapshots/">snapshots/</a>'), 'root lists only snapshots');
  response = await get('/snapshots/');
  check(response.status === 200 && (await response.text()).includes('>../</a>'), 'empty snapshots fallback');
  const setPages = manifests => {
    const pages = JSON.parse(execFileSync('python3', ['-c',
      'import json, sys; sys.path.insert(0, "tools"); from image_page import render; print(json.dumps({key: value.decode() for key, value in render(json.load(sys.stdin)).items()}))'],
    { cwd: root, input: JSON.stringify(manifests), encoding: 'utf8' }));
    for (const [key, value] of Object.entries(pages)) objects.set(key, Buffer.from(value));
  };
  setPages([good.manifest, retry.manifest]);
  response = await get('/snapshots/');
  let html = await response.text();
  check(html.includes(`>${good.snapshot}/</a>`) && html.includes(`>${retry.snapshot}/</a>`) && !html.includes('posix-devel'), 'snapshot level');
  response = await get(`/snapshots/${good.snapshot}/`);
  html = await response.text();
  check(html.includes('>aarch64/</a>') && !html.includes('virt-aarch64'), 'architecture level');
  response = await get('/' + good.prefix);
  html = await response.text();
  check(html.includes('>update/</a>') && html.includes('>virt-aarch64.install.raw.zst</a>') && !html.includes(good.filename), 'snapshot files and subdirectories');
  response = await get('/' + good.prefix + 'update/');
  html = await response.text();
  check(html.includes(`>${good.filename}</a>`) && html.includes('>SHA256SUMS</a>') && !html.includes('>update/</a>'), 'update files');
  response = await get('/snapshots', { redirect: 'manual' });
  check(response.status === 308 && response.headers.get('Location') === 'https://images.example/snapshots/', 'directory trailing slash');
  check((await get('/snapshots/20261016.9999/')).status === 404, 'unknown directory');
  const later = await release();
  setPages([good.manifest, retry.manifest, later.manifest]);
  response = await get('/snapshots/');
  check((await response.text()).includes(`>${later.snapshot}/</a>`) && response.headers.get('Cache-Control') === 'public, max-age=60', 'directory refresh without deployment');
  check((await get('/style.css')).status === 404, 'no stylesheet');

  // Optionally test retained production bytes without downloading or uploading
  // them again. Reuse their local publication, indexes, chunks and saved image.
  if (process.env.BEAMLINE_IMAGES_SNAPSHOT_ROOT) {
    const snapshot = '20261015.1430';
    const prefix = `snapshots/${snapshot}/aarch64/`;
    const prepared = path.resolve(process.env.BEAMLINE_IMAGES_METADATA, snapshot, 'aarch64');
    const manifest = JSON.parse(await fs.readFile(path.join(prepared, 'publication.json')));
    const filename = `posix-devel_${snapshot}.sysext.raw`;
    const file = manifest.artifacts['update/' + filename];
    for (const name of ['publication.json', 'publication.json.gpg', file.index]) objects.set(prefix + name, await fs.readFile(path.join(prepared, name)));
    const image = await fs.open(path.join(process.env.BEAMLINE_IMAGES_SNAPSHOT_ROOT, snapshot, 'update', filename));
    productionStore = path.resolve(process.env.BEAMLINE_IMAGES_STORE);
    const url = '/' + prefix + 'update/' + filename;
    for (const start of [0, 16380, 65530, 12345678, file.size - 300000]) {
      const expected = Buffer.alloc(299999);
      await image.read(expected, 0, expected.length, start);
      response = await get(url, { headers: { Range: `bytes=${start}-${start + expected.length - 1}` } });
      check(Buffer.from(await response.arrayBuffer()).equals(expected), 'saved posix-devel range');
    }
    const download = await get(url);
    const fullHash = createHash('sha256'); let length = 0;
    for await (const piece of download.body) { fullHash.update(piece); length += piece.length; }
    check(length === file.size && fullHash.digest('hex') === file.sha256, 'saved complete posix-devel');
    await image.close();
  }
  const report = { result: 'passed', checks, originRequests: requests.length,
    longStreamChunks: repeats, savedPosixDevel: Boolean(process.env.BEAMLINE_IMAGES_SNAPSHOT_ROOT) };
  await fs.writeFile(path.join(root, 'out/images-worker-test.json'), JSON.stringify(report, null, 2) + '\n');
  console.log(JSON.stringify(report));
} finally {
  await mf?.dispose();
  origin.closeAllConnections();
  await new Promise(resolve => origin.close(resolve));
  await fs.rm(temporary, { recursive: true, force: true });
}
