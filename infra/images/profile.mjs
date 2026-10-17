// SPDX-License-Identifier: MIT

import assert from 'node:assert/strict';
import WebSocket from 'ws';

export async function allocations(mf, download) {
  const inspector = await mf.getInspectorURL();
  inspector.protocol = 'http:'; inspector.pathname = '/json/list';
  const targets = await (await fetch(inspector)).json();
  const target = targets.find(value => value.webSocketDebuggerUrl.includes('beamline-images-test'));
  assert(target, 'reader inspector target exists');
  const url = new URL(target.webSocketDebuggerUrl);
  assert(['127.0.0.1', 'localhost'].includes(url.hostname), 'inspector stays on loopback');
  const socket = new WebSocket(url, { headers: { Origin: 'http://localhost' } });
  const pending = new Map(); let next = 0;
  socket.on('message', data => {
    const message = JSON.parse(data.toString());
    const call = pending.get(message.id);
    if (!call) return;
    pending.delete(message.id); clearTimeout(call.timer);
    if (message.error) call.reject(new Error(JSON.stringify(message.error)));
    else call.resolve(message.result);
  });
  const disconnected = () => {
    for (const call of pending.values()) { clearTimeout(call.timer); call.reject(new Error('Inspector disconnected')); }
    pending.clear();
  };
  socket.on('close', disconnected);
  await new Promise((resolve, reject) => { socket.once('open', resolve); socket.once('error', reject); });
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++next;
    const timer = setTimeout(() => { pending.delete(id); reject(new Error('Inspector timeout: ' + method)); }, 10000);
    pending.set(id, { resolve, reject, timer });
    socket.send(JSON.stringify({ id, method, params }));
  });
  try {
    await send('Runtime.enable');
    await send('HeapProfiler.enable');
    const cases = [];
    for (const [scheduling, prefetch] of [['legacy', 4], ['rolling', 16]]) {
      const before = await send('Runtime.getHeapUsage');
      await send('HeapProfiler.startSampling', { samplingInterval: 4096,
        includeObjectsCollectedByMajorGC: true, includeObjectsCollectedByMinorGC: true });
      const usage = [];
      for (let repeat = 0; repeat < 3; repeat++) {
        await download(scheduling, prefetch);
        usage.push(await send('Runtime.getHeapUsage'));
      }
      const { profile } = await send('HeapProfiler.stopSampling');
      const after = await send('Runtime.getHeapUsage');
      assert(profile.samples.length > 0 && after.usedSize > 0, 'isolate allocation evidence is populated');
      cases.push({ scheduling, prefetch, before, usage, after,
        sampledAllocatedBytes: profile.samples.reduce((total, sample) => total + sample.size, 0), profile });
    }
    return { scope: 'local-workerd-reader-isolate', forcedGC: false, samplingInterval: 4096, cases };
  } finally { socket.close(); disconnected(); }
}
