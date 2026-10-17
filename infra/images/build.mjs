// SPDX-License-Identifier: MIT
import { build } from 'esbuild';
import { execFileSync } from 'node:child_process';
import { cp, mkdir, copyFile, rm, readFile, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '../..');
const output = path.join(root, 'out/images-worker');
const target = path.join(root, 'out/images-worker-build/cargo');
await rm(output, { recursive: true, force: true });
await mkdir(output, { recursive: true });
execFileSync('cargo', ['build', '--manifest-path', path.join(here, 'reader/Cargo.toml'),
  '--target', 'wasm32-unknown-unknown', '--release', '--locked', '--target-dir', target], {
  stdio: 'inherit', env: { ...process.env, RUSTFLAGS: '-C link-arg=--max-memory=33554432' },
});
await copyFile(path.join(target, 'wasm32-unknown-unknown/release/beamline_image_reader.wasm'),
  path.join(output, 'reader.wasm'));
await build({ entryPoints: [path.join(here, 'worker.mjs')], outfile: path.join(output, 'worker.mjs'),
  bundle: true, format: 'esm', platform: 'browser', target: 'es2022', conditions: ['browser'],
  loader: { '.pgp': 'binary' }, external: ['*.wasm'], minify: true, legalComments: 'eof' });
await cp(path.join(here, 'public'), path.join(output, 'public'), { recursive: true });
await copyFile(path.join(here, 'wrangler.jsonc'), path.join(output, 'wrangler.jsonc'));
const preview = JSON.parse((await readFile(path.join(here, 'wrangler.jsonc'), 'utf8'))
  .split('\n').filter(line => !line.trimStart().startsWith('//')).join('\n'));
preview.name = 'beamline-images-preview'; preview.routes = [];
preview.vars.BENCHMARK_MODE = 'true';
preview.r2_buckets = [{ binding: 'STORE_R2', bucket_name: 'beamlineos-store' }];
await writeFile(path.join(output, 'wrangler.preview.jsonc'), JSON.stringify(preview, null, 2) + '\n');
await copyFile(path.join(here, 'reader/LICENSE.desync'), path.join(output, 'LICENSE.desync'));
await copyFile(path.join(root, 'LICENSE'), path.join(output, 'LICENSE'));
await copyFile(path.join(here, 'node_modules/openpgp/LICENSE'), path.join(output, 'LICENSE.openpgp'));
const files = ['worker.mjs', 'reader.wasm', 'wrangler.jsonc', 'wrangler.preview.jsonc', 'public/index.html',
  'public/snapshots/index.html', 'LICENSE', 'LICENSE.desync', 'LICENSE.openpgp'];
const sums = [];
for (const name of files) {
  const digest = createHash('sha256').update(await readFile(path.join(output, name))).digest('hex');
  sums.push(`${digest}  ${name}\n`);
}
await writeFile(path.join(output, 'SHA256SUMS'), sums.join(''));
console.log(`Worker artifact: ${output}`);
