// deploy/apply-schema.mjs
// Boot-time Postgres schema provisioning for the compbird app.
//
// Applies prisma/schema.sql (generated at BUILD by `prisma migrate diff
// --from-empty --to-schema-datamodel`, Postgres dialect) using the `pg` driver.
// It deliberately does NOT use the Prisma CLI, whose transitive closure
// (@prisma/config -> c12/effect/...) is not carried by Next's standalone trace
// and crash-looped boot with "Cannot find module 'effect'".
//
// Strategy: GUARDED apply-if-fresh, in ONE transaction. Postgres CREATE
// TYPE/TABLE have no IF NOT EXISTS, so rather than rewrite the DDL we check for
// a sentinel table and, only when the schema isn't there yet, run the whole
// script atomically. First boot on an empty database creates everything; every
// later boot is a no-op. A partial/failed apply rolls back cleanly and the boot
// crashes visibly so Railway restarts and retries on a still-empty DB.
//
// LIMITATION: this provisions the INITIAL schema only. A post-launch schema
// change needs a real migration — run `prisma migrate deploy` (or `db push`)
// against DATABASE_URL from a dev/CI context, or apply hand-written ALTER SQL.

import pg from "pg";
import { readFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url)); // /app/deploy
const appRoot = resolve(__dirname, ".."); // /app
const schemaFile = resolve(appRoot, "prisma/schema.sql");

const url = process.env.DATABASE_URL;
if (!url || !url.trim()) {
  console.error("!! schema sync: DATABASE_URL is not set");
  process.exit(1);
}
if (!/^postgres(ql)?:\/\//i.test(url.trim())) {
  console.error(`!! schema sync: DATABASE_URL is not a postgres URL (starts "${url.trim().slice(0, 12)}")`);
  process.exit(1);
}
if (!existsSync(schemaFile)) {
  console.error(`!! schema sync: schema.sql missing at ${schemaFile}`);
  process.exit(1);
}
const sql = readFileSync(schemaFile, "utf8").trim();
if (!sql) {
  console.error(`!! schema sync: schema.sql at ${schemaFile} is empty`);
  process.exit(1);
}

const client = new pg.Client({ connectionString: url.trim() });

async function main() {
  await client.connect();
  // Sentinel: to_regclass returns NULL when the (case-sensitive) table is absent.
  const { rows } = await client.query(`SELECT to_regclass('public."AuthUser"') AS t`);
  if (rows[0]?.t) {
    console.log('-> schema sync ok: schema already present ("AuthUser" exists) — skipping');
    return;
  }
  console.log("-> applying Postgres schema (fresh database)...");
  await client.query("BEGIN");
  try {
    await client.query(sql); // simple-query protocol runs the whole multi-statement script
    await client.query("COMMIT");
  } catch (e) {
    await client.query("ROLLBACK").catch(() => {});
    throw e;
  }
  const { rows: after } = await client.query(
    `SELECT count(*)::int AS n FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE'`,
  );
  console.log(`-> schema sync ok: provisioned ${after[0].n} tables`);
}

main()
  .then(() => client.end())
  .catch(async (e) => {
    console.error(`!! schema sync FAILED: ${e.message}`);
    try {
      await client.end();
    } catch {
      /* already closing */
    }
    process.exit(1);
  });
