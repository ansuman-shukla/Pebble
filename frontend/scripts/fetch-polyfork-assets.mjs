#!/usr/bin/env node
/*
 * Vendors Polyfork assets listed in src/lib/world/asset-manifest.json.
 *
 *   node scripts/fetch-polyfork-assets.mjs              download missing files, verify every sha256
 *   node scripts/fetch-polyfork-assets.mjs --add <id…>  add assets to the manifest (metadata + pinned sha256)
 *   node scripts/fetch-polyfork-assets.mjs --update     re-download everything and re-pin metadata + sha256
 *
 * The files themselves are gitignored: Polyfork's licence forbids redistributing them, and this repo may be public.
 * Only the manifest (what we use, pinned by hash) is committed.
 */
import { createHash } from 'node:crypto';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';

const ROOT = path.resolve(import.meta.dirname, '..');
const MANIFEST = path.join(ROOT, 'src/lib/world/asset-manifest.json');
const API = 'https://polyfork.dev/api/assets/';
const CDN = 'https://polyfork.dev/cdn/';
const ASSET_DIR = 'public/assets/polyfork';
const CONCURRENCY = 6;

const sha256 = (buffer) => createHash('sha256').update(buffer).digest('hex');

async function download(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`GET ${url} -> HTTP ${response.status}`);
  return Buffer.from(await response.arrayBuffer());
}

async function readLocal(file) {
  try {
    return await readFile(path.join(ROOT, file));
  } catch (error) {
    if (error.code === 'ENOENT') return null;
    throw error;
  }
}

async function writeLocal(file, buffer) {
  const target = path.join(ROOT, file);
  await mkdir(path.dirname(target), { recursive: true });
  await writeFile(target, buffer);
}

const assetFiles = (id, colliders) => ({
  glb: { url: `${CDN}${id}.glb`, path: `${ASSET_DIR}/${id}/${id}.glb` },
  params: {
    url: `${CDN}${id}-params.json`,
    path: `${ASSET_DIR}/${id}/${id}-params.json`,
  },
  ...(colliders && {
    colliders: {
      url: colliders,
      path: `${ASSET_DIR}/${id}/${id}-colliders.json`,
    },
  }),
});

const applyPatch = (buffer, append) =>
  append ? Buffer.concat([buffer, Buffer.from(`\n${append}\n`)]) : buffer;

/** Makes one pinned file present locally; returns false when nothing had to be downloaded. */
async function syncFile({
  url,
  path: file,
  sha256: pinned,
  append,
  patched_sha256,
}) {
  const local = await readLocal(file);
  if (local && sha256(local) === (patched_sha256 ?? pinned)) return false;
  const remote = await download(url);
  const actual = sha256(remote);
  if (actual !== pinned) {
    throw new Error(
      `${file}: upstream changed (sha256 ${actual}, pinned ${pinned}). Review it, then run with --update.`,
    );
  }
  await writeLocal(file, applyPatch(remote, append));
  return true;
}

async function pinFile(url, file, append) {
  const remote = await download(url);
  const written = applyPatch(remote, append);
  await writeLocal(file, written);
  return {
    url,
    path: file,
    sha256: sha256(remote),
    bytes: remote.length,
    ...(append && { append, patched_sha256: sha256(written) }),
  };
}

async function describeAsset(id) {
  const response = await fetch(`${API}${id}`);
  if (!response.ok) throw new Error(`asset ${id}: HTTP ${response.status}`);
  const meta = await response.json();
  if (!meta.free) throw new Error(`asset ${id} is not free`);
  const files = {};
  const colliders = meta.physics?.collision?.colliders_url;
  for (const [kind, { url, path: file }] of Object.entries(
    assetFiles(id, colliders),
  )) {
    files[kind] = await pinFile(url, file);
  }
  return {
    id,
    title: meta.title,
    kit: meta.kit,
    class: meta.class,
    triangles: meta.triangles,
    size_m: meta.size_m,
    license: meta.license,
    files,
  };
}

async function inBatches(items, worker) {
  const results = [];
  for (let i = 0; i < items.length; i += CONCURRENCY) {
    results.push(
      ...(await Promise.all(items.slice(i, i + CONCURRENCY).map(worker))),
    );
  }
  return results;
}

async function sync(manifest) {
  const files = [
    ...manifest.modules,
    ...manifest.assets.flatMap((asset) => Object.values(asset.files)),
  ];
  const downloaded = (await inBatches(files, syncFile)).filter(Boolean).length;
  const bytes = manifest.assets
    .flatMap((asset) => Object.values(asset.files))
    .reduce((sum, file) => sum + file.bytes, 0);
  console.log(
    `polyfork: ${files.length} files verified (${downloaded} downloaded), ` +
      `${(bytes / 1e6).toFixed(1)} MB of assets`,
  );
}

async function main() {
  const args = process.argv.slice(2);
  const manifest = JSON.parse(await readFile(MANIFEST, 'utf8'));

  if (args[0] === '--add' || args[0] === '--update') {
    const ids =
      args[0] === '--add'
        ? args
            .slice(1)
            .filter((id) => !manifest.assets.some((asset) => asset.id === id))
        : manifest.assets.map((asset) => asset.id);
    const described = await inBatches(ids, describeAsset);
    const byId = new Map(
      [...manifest.assets, ...described].map((asset) => [asset.id, asset]),
    );
    manifest.assets = [...byId.values()].sort((a, b) =>
      a.id.localeCompare(b.id),
    );
    manifest.modules = await inBatches(manifest.modules, async (module) =>
      args[0] === '--update' || !module.sha256
        ? {
            ...module,
            ...(await pinFile(module.url, module.path, module.append)),
          }
        : module,
    );
    await writeFile(MANIFEST, `${JSON.stringify(manifest, null, 2)}\n`);
    console.log(`polyfork: pinned ${described.length} assets`);
  }
  await sync(manifest);
}

await main();
