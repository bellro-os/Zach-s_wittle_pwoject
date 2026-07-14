/** Import an agent's transactions from a brokerage sales-transactions CSV
 * export into the dashboard's Deal table.
 *
 *   node scripts/import-brokerage-sales.mjs "<csv path>" "<agent name>"
 *
 * Behavior:
 *  - Keeps only rows where the agent is on the listing OR buying side.
 *  - side  = sell (listing agent) | buy (buying agent).
 *  - stage = closed (Closed) | contract (Pending) | lost (Cancelled).
 *  - commissionEarned = that side's agent-net, split equally when the agent
 *    co-represented the side with teammates.
 *  - Dedups within the CSV by normalized address (keeps Closed > Pending >
 *    Cancelled, then latest contract date).
 *  - Merges into existing deals by sourceRef, else by normalized address —
 *    brokerage data wins on conflict. Re-running is idempotent.
 */

import { readFileSync } from "node:fs";
import { PrismaClient } from "@prisma/client";

const db = new PrismaClient();

const CSV_PATH = process.argv[2] || "../sales-transactions.csv";
const AGENT = process.argv[3] || "Zachary Stotz";

/* ---------- CSV ---------- */
function parseCsv(t) {
  const rows = [];
  let cur = [], field = "", q = false;
  for (let i = 0; i < t.length; i++) {
    const c = t[i];
    if (q) {
      if (c === '"') {
        if (t[i + 1] === '"') { field += '"'; i++; } else q = false;
      } else field += c;
    } else if (c === '"') q = true;
    else if (c === ",") { cur.push(field); field = ""; }
    else if (c === "\n" || c === "\r") {
      if (c === "\r" && t[i + 1] === "\n") i++;
      cur.push(field); rows.push(cur); cur = []; field = "";
    } else field += c;
  }
  if (field.length || cur.length) { cur.push(field); rows.push(cur); }
  return rows;
}

const SUFFIX = {
  STREET: "ST", AVENUE: "AVE", DRIVE: "DR", ROAD: "RD", LANE: "LN",
  COURT: "CT", BOULEVARD: "BLVD", HIGHWAY: "HWY", CIRCLE: "CIR",
  PLACE: "PL", PARKWAY: "PKWY", TERRACE: "TER", TRAIL: "TRL",
  SQUARE: "SQ", NORTHWEST: "NW", NORTHEAST: "NE", SOUTHWEST: "SW",
  SOUTHEAST: "SE", NORTH: "N", SOUTH: "S", EAST: "E", WEST: "W",
};
/** Normalize a street address for cross-source matching. */
function normAddr(s) {
  let t = (s || "").toUpperCase().replace(/[.,#]/g, " ");
  t = t.replace(/\s+/g, " ").trim();
  return t.split(" ").map((w) => SUFFIX[w] ?? w).filter(Boolean).join(" ")
    .replace(/-\d{4}\b/, "");
}

function num(v) {
  const n = parseFloat(String(v || "").replace(/[,$]/g, ""));
  return isNaN(n) ? null : n;
}
function parseDate(v) {
  const s = (v || "").trim();
  if (!s) return null;
  const d = new Date(s);
  return isNaN(d.getTime()) ? null : d;
}

/* ---------- Load + filter ---------- */
const rows = parseCsv(readFileSync(CSV_PATH, "utf-8"));
const header = rows[0];
const recs = rows.slice(1).filter((r) => r.length > 5).map((r) => {
  const o = {};
  header.forEach((h, i) => (o[h] = r[i] ?? ""));
  return o;
});

const onAgent = (s) => (s || "").includes(AGENT);
const agentRows = recs.filter(
  (r) => onAgent(r.Listing_Agent_Name) || onAgent(r.Buying_Agent_Name),
);

/** Translate a raw transaction row into a canonical deal record. */
function toDeal(r) {
  const onListing = onAgent(r.Listing_Agent_Name);
  const side = onListing ? "sell" : "buy";
  const sideAgents = (onListing ? r.Listing_Agent_Name : r.Buying_Agent_Name)
    .split(",").map((s) => s.trim()).filter(Boolean);
  const sideNet =
    num(onListing ? r.Listing_Side_Agent_Net : r.Buying_Side_Agent_Net) ?? 0;
  // Equal split when co-represented.
  const commission = sideAgents.length > 1 ? sideNet / sideAgents.length : sideNet;
  const coAgents = sideAgents.filter((a) => a !== AGENT);

  const status = r.Transaction_Status;
  const stage =
    status === "Closed" ? "closed"
    : status === "Pending" ? "contract"
    : "lost";

  const price =
    num(r.Sale_Price) ?? num(r.Listing_Price) ?? null;

  const noteParts = [`Imported from brokerage transactions (${status}).`];
  if (coAgents.length) {
    noteParts.push(
      `Co-represented ${side} side with ${coAgents.join(", ")} — ` +
      `commission split equally (side agent-net $${sideNet.toLocaleString()}).`,
    );
  }

  return {
    sourceRef: "brokerage:" + r.Transaction_Identifier_TransactionGuid,
    property: r.Property_Address || r.Address_Line1,
    normAddr: normAddr(r.Property_Address || r.Address_Line1),
    side,
    stage,
    status,
    listPrice: price,
    commissionEarned: Math.round(commission * 100) / 100,
    closedDate: parseDate(r.Closed_Date),
    contractDate: parseDate(r.Contract_Date),
    notes: noteParts.join(" "),
  };
}

const deals = agentRows.map(toDeal);

// Within-CSV dedup by normalized address.
const rank = { Closed: 3, Pending: 2, Cancelled: 1 };
const byAddr = new Map();
for (const d of deals) {
  const prev = byAddr.get(d.normAddr);
  if (
    !prev ||
    rank[d.status] > rank[prev.status] ||
    (rank[d.status] === rank[prev.status] &&
      (d.contractDate?.getTime() ?? 0) > (prev.contractDate?.getTime() ?? 0))
  ) {
    byAddr.set(d.normAddr, d);
  }
}
const unique = [...byAddr.values()];

/* ---------- Upsert into the dashboard ---------- */
async function main() {
  console.log(`${AGENT}: ${agentRows.length} transactions -> ${unique.length} unique properties`);

  const existing = await db.deal.findMany({
    where: {},
    select: { id: true, displayId: true, property: true, sourceRef: true },
  });
  const bySourceRef = new Map(existing.filter((e) => e.sourceRef).map((e) => [e.sourceRef, e]));
  const byNorm = new Map(existing.map((e) => [normAddr(e.property), e]));
  let counter = await db.deal.count();

  let created = 0, merged = 0;
  for (const d of unique) {
    const match = bySourceRef.get(d.sourceRef) || byNorm.get(d.normAddr);
    const data = {
      side: d.side,
      stage: d.stage,
      property: d.property,
      listPrice: d.listPrice,
      commissionEarned: d.commissionEarned,
      estCommissionPct: null,
      expectedClose: d.stage === "contract" ? d.closedDate : null,
      notes: d.notes,
      sourceRef: d.sourceRef,
    };

    let dealId, displayId;
    if (match) {
      const updated = await db.deal.update({ where: { id: match.id }, data });
      dealId = updated.id;
      displayId = updated.displayId;
      merged++;
    } else {
      displayId = "D" + String(++counter).padStart(4, "0");
      const createdDeal = await db.deal.create({
        data: { displayId, clientId: null, ...data },
      });
      dealId = createdDeal.id;
      created++;
    }

    // Re-seed stage history (brokerage data is authoritative). One terminal
    // event dated to the real transaction date drives the analytics trend.
    await db.dealStage.deleteMany({ where: { dealId } });
    const stageDate =
      d.stage === "closed" ? (d.closedDate ?? d.contractDate ?? new Date())
      : (d.contractDate ?? new Date());
    await db.dealStage.create({
      data: {
        dealId,
        stage: d.stage,
        changedAt: stageDate,
        notes: "imported from brokerage transactions",
      },
    });

    console.log(
      `  ${match ? "merged " : "created"} ${displayId}  ${d.stage.padEnd(8)} ${d.side}  ` +
      `$${(d.listPrice ?? 0).toLocaleString()}  comm $${d.commissionEarned.toLocaleString()}  ${d.property}`,
    );
  }
  console.log(`\nDone: ${created} created, ${merged} merged.`);
  await db.$disconnect();
}

main().catch((e) => { console.error(e); process.exit(1); });
