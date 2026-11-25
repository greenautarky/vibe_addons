// npm-pin.js — replace ONE npm package inside the vendor app at /workspace,
// and assert the result. Used by the Dockerfile in this directory; build-time only.
//
//   node npm-pin.js install <name> <version> <integrity> <tarball>
//       Verifies <tarball> against the npm integrity string (sha512-...), replaces
//       /workspace/node_modules/<name> with its contents and updates that entry in
//       /workspace/package-lock.json. Refuses if the package was not installed
//       before: this only REPLACES, it never adds to the vendor tree.
//
//   node npm-pin.js assert <name> <min-version>
//       Finds EVERY copy of <name> in the image filesystem and fails unless each
//       is >= <min-version>; fails on zero copies (a check over nothing is not a
//       pass). Then checks that express resolves <name> to the top-level copy and
//       that both load.
'use strict';
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { execFileSync } = require('child_process');

const APP = '/workspace';
const die = (msg) => { console.error(`npm-pin: ${msg}`); process.exit(1); };

function cmp(a, b) {
  const pa = a.split(/[.+-]/).slice(0, 3).map(Number);
  const pb = b.split(/[.+-]/).slice(0, 3).map(Number);
  for (let i = 0; i < 3; i++) {
    if (pa[i] !== pb[i]) return pa[i] < pb[i] ? -1 : 1;
  }
  return 0;
}

function install(name, version, integrity, tarball) {
  const [algo, want] = integrity.split(/-(.*)/s);
  const got = crypto.createHash(algo).update(fs.readFileSync(tarball)).digest('base64');
  if (got !== want) die(`${name}@${version}: integrity mismatch (${algo}-${got})`);

  const dst = path.join(APP, 'node_modules', name);
  if (!fs.existsSync(path.join(dst, 'package.json'))) die(`${dst} is not installed — refusing to add a package`);
  const before = JSON.parse(fs.readFileSync(path.join(dst, 'package.json'), 'utf8')).version;
  fs.rmSync(dst, { recursive: true, force: true });
  fs.mkdirSync(dst, { recursive: true });
  execFileSync('tar', ['-xzf', tarball, '-C', dst, '--strip-components=1'], { stdio: 'inherit' });
  const after = JSON.parse(fs.readFileSync(path.join(dst, 'package.json'), 'utf8')).version;
  if (after !== version) die(`${dst} holds ${after} after extraction, expected ${version}`);

  const lockFile = path.join(APP, 'package-lock.json');
  const lock = JSON.parse(fs.readFileSync(lockFile, 'utf8'));
  const entry = lock.packages && lock.packages[`node_modules/${name}`];
  if (!entry) die(`no "node_modules/${name}" entry in ${lockFile}`);
  entry.version = version;
  entry.resolved = `https://registry.npmjs.org/${name}/-/${name}-${version}.tgz`;
  entry.integrity = integrity;
  fs.writeFileSync(lockFile, JSON.stringify(lock, null, 2) + '\n');
  console.log(`npm-pin: ${name} ${before} -> ${after} (${dst}, lockfile updated)`);
}

function findCopies(name) {
  const hits = [];
  const skip = new Set(['/proc', '/sys', '/dev']);
  const walk = (dir) => {
    let ents;
    try { ents = fs.readdirSync(dir, { withFileTypes: true }); } catch { return; }
    for (const e of ents) {
      if (!e.isDirectory() || e.isSymbolicLink()) continue;
      const p = path.join(dir, e.name);
      if (skip.has(p)) continue;
      if (e.name === name && path.basename(dir) === 'node_modules' && fs.existsSync(path.join(p, 'package.json'))) {
        hits.push(path.join(p, 'package.json'));
      }
      walk(p);
    }
  };
  walk('/');
  return hits;
}

function assert(name, min) {
  const copies = findCopies(name);
  if (copies.length === 0) die(`no copy of ${name} found in the image`);
  let bad = 0;
  for (const p of copies) {
    const v = JSON.parse(fs.readFileSync(p, 'utf8')).version;
    const ok = cmp(v, min) >= 0;
    console.log(`npm-pin: ${ok ? 'OK ' : 'LOW'} ${name} ${v} ${p}`);
    if (!ok) bad++;
  }
  if (bad) die(`${bad} of ${copies.length} copies of ${name} are below ${min}`);

  const top = path.join(APP, 'node_modules', name);
  const viaExpress = require.resolve(name, { paths: [path.join(APP, 'node_modules', 'express')] });
  if (!viaExpress.startsWith(top + path.sep)) die(`express resolves ${name} to ${viaExpress}, not ${top}`);
  require(path.join(APP, 'node_modules', 'express'));
  require(top);
  console.log(`npm-pin: ${copies.length} cop${copies.length === 1 ? 'y' : 'ies'} of ${name} >= ${min}; express loads it from ${top}`);
}

const [cmd, ...args] = process.argv.slice(2);
if (cmd === 'install' && args.length === 4) install(...args);
else if (cmd === 'assert' && args.length === 2) assert(...args);
else die('usage: npm-pin.js install <name> <version> <integrity> <tarball> | assert <name> <min-version>');
