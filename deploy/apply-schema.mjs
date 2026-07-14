// deploy/apply-schema.mjs
// Boot-time SQLite schema sync for the Compbird app on the Railway volume.
//
// Replaces `prisma db push` at runtime. It applies prisma/schema.sql (generated
// at BUILD time by `prisma migrate diff --from-empty`, see deploy/Dockerfile.app)
// using better-sqlite3 — a GUARANTEED runtime dependency (the app already opens
// the search index with it). This deliberately keeps the Prisma CLI, and its
// transitive closure (@prisma/config -> c12/effect/empathic/deepmerge-ts), OUT
// of the boot path: Next's standalone trace carries only @prisma/client, not the
// CLI, so invoking the CLI at boot crash-looped with "Cannot find module 'effect'".
//
// Idempotent: every CREATE is rewritten to `IF NOT EXISTS`, so a first boot on a
// fresh volume creates the whole schema and every later boot is a no-op.
// LIMITATION: this creates missing tables/indexes but does NOT alter existing
// ones. A post-launch schema change needs a real migration — run it once with
//   railway run --service <app> -- node node_modules/prisma/build/index.js db push
// against a build that still ships the CLI, or apply hand-written ALTER SQL.

import Database from 'better-sqlite3';
import { readFileSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url)); // /app/deploy
const appRoot = resolve(__dirname, '..'); // /app
const schemaFile = resolve(appRoot, 'prisma/schema.sql');

function dbPathFromUrl(url) {
  if (!url) throw new Error('DATABASE_URL is not set');
  const m = /^file:(.*)$/.exec(url.trim());
  if (!m) throw new Error(`DATABASE_URL is not a file: URL (got "${url}")`);
  // Production uses an absolute path (file:/data/compbird.db); resolve() keeps a
  // relative file:./x sane too (against the app root, mirroring dev layout).
  return resolve(appRoot, m[1]);
}

let dbFile;
try {
  dbFile = dbPathFromUrl(process.env.DATABASE_URL);
} catch (e) {
  console.error(`!! schema sync: ${e.message}`);
  process.exit(1);
}

if (!existsSync(schemaFile)) {
  console.error(`!! schema sync: schema.sql missing at ${schemaFile}`);
  process.exit(1);
}

let sql = readFileSync(schemaFile, 'utf8').trim();
if (!sql) {
  console.error(`!! schema sync: schema.sql at ${schemaFile} is empty`);
  process.exit(1);
}

// Make every CREATE re-runnable. Prisma always emits quoted identifiers
// (CREATE TABLE "Foo", CREATE [UNIQUE] INDEX "Bar"), and never emits
// IF NOT EXISTS itself, so a plain substitution cannot double-insert.
sql = sql
  .replace(/\bCREATE TABLE "/g, 'CREATE TABLE IF NOT EXISTS "')
  .replace(/\bCREATE UNIQUE INDEX "/g, 'CREATE UNIQUE INDEX IF NOT EXISTS "')
  .replace(/\bCREATE INDEX "/g, 'CREATE INDEX IF NOT EXISTS "');

const db = new Database(dbFile);
try {
  db.pragma('foreign_keys = OFF'); // creation order is arbitrary; FKs re-enable per-connection
  const countTables = () =>
    db
      .prepare("SELECT count(*) AS n FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
      .get().n;
  const before = countTables();
  db.exec(sql);
  const after = countTables();
  console.log(`-> schema sync ok (${dbFile}): tables ${before} -> ${after}`);
} catch (e) {
  console.error(`!! schema sync FAILED (${dbFile}): ${e.message}`);
  process.exit(1);
} finally {
  db.close();
}
