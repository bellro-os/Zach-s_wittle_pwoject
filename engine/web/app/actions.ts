"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { z } from "zod";
import { db } from "@/lib/data/db";
import { HOT_OUTCOMES } from "@/lib/data/outcomes";
import { getProspect } from "@/lib/data/prospects";

/** Standard result shape returned by every action. Client components
 * inspect this to render success/error toasts. */
export type ActionResult<T = unknown> = {
  success: boolean;
  message?: string;
  error?: string;
  data?: T;
};

/** Days-from-now-to-follow-up by outcome — mirrors the Python data_layer. */
const FOLLOWUP_DAYS: Record<string, number> = {
  interested: 1,
  talk_later: 14,
  left_voicemail: 7,
  no_answer: 3,
  callback: 2,
  meeting_scheduled: 1,
  left_flyer: 21,
  nobody_home: 7,
  not_interested: 365,
  bad_number: 36500,
  dnc: 36500,
  wrong_owner: 36500,
};

function followupDate(outcome: string): Date | null {
  const days = FOLLOWUP_DAYS[outcome] ?? 30;
  if (days >= 36000) return null;
  return new Date(Date.now() + days * 86_400_000);
}

function followupLabel(outcome: string): string {
  const days = FOLLOWUP_DAYS[outcome] ?? 30;
  if (days >= 36000) return "suppress permanently";
  return `follow up in ${days}d`;
}

function parseDate(s: string): Date | null {
  if (!s) return null;
  const d = new Date(s);
  return isNaN(d.getTime()) ? null : d;
}

const callSchema = z.object({
  parcelId: z.string().min(1),
  county: z.string().default(""),
  owner: z.string().default(""),
  siteAddr: z.string().default(""),
  outcome: z.string().min(1),
  notes: z.string().default(""),
});

/* ---------- Calls + door-knocks ---------- */

/** When a hot outcome (interested/meeting_scheduled/callback) is logged on a
 * parcel, ensure that parcel has an active Deal in the pipeline. Dedup policy:
 *   - existing active deal: no-op, return its displayId
 *   - existing soft-deleted deal: restore + reset stage to "lead"
 *   - existing closed/lost deal: do NOT reanimate
 *   - no existing deal: create one in stage=lead with prospect's leadType. */
async function ensureLeadDeal(args: {
  parcelId: string;
  county: string;
  owner: string;
  siteAddr: string;
}): Promise<{ created: boolean; displayId: string | null }> {
  const county = args.county.toUpperCase();
  const existing = await db.deal.findFirst({
    where: { parcelId: args.parcelId, county },
    orderBy: { created: "desc" },
  });
  if (existing) {
    if (["closed", "lost"].includes(existing.stage.toLowerCase())) {
      return { created: false, displayId: null };
    }
    if (existing.deletedAt) {
      await db.deal.update({
        where: { id: existing.id },
        data: { deletedAt: null, stage: "lead" },
      });
      await db.dealStage.create({
        data: { dealId: existing.id, stage: "lead", notes: "restored from hot outcome" },
      });
      return { created: false, displayId: existing.displayId };
    }
    return { created: false, displayId: existing.displayId };
  }
  const prospect = await getProspect(args.parcelId, county);
  const leadType = prospect?.leadType ?? null;
  const displayId = await nextDealDisplayId();
  const deal = await db.deal.create({
    data: {
      displayId,
      stage: "lead",
      side: "sell",
      property: args.siteAddr || `Parcel ${args.parcelId}`,
      parcelId: args.parcelId,
      county,
      leadType,
      clientId: null,
    },
  });
  await db.dealStage.create({
    data: { dealId: deal.id, stage: "lead", notes: "auto-promoted from hot outcome" },
  });
  return { created: true, displayId };
}

/** Shared core — write a single call row from plain args. */
async function doLogCall(args: z.infer<typeof callSchema>) {
  const call = await db.call.create({
    data: {
      parcelId: args.parcelId,
      county: args.county.toUpperCase(),
      owner: args.owner,
      siteAddr: args.siteAddr,
      outcome: args.outcome,
      notes: args.notes || null,
      nextFollowup: followupDate(args.outcome),
    },
  });
  let promotionMessage = "";
  if (HOT_OUTCOMES.has(args.outcome)) {
    const result = await ensureLeadDeal({
      parcelId: args.parcelId,
      county: args.county,
      owner: args.owner,
      siteAddr: args.siteAddr,
    });
    if (result.created) {
      promotionMessage = ` · added to pipeline as ${result.displayId}`;
    } else if (result.displayId) {
      promotionMessage = ` · already in pipeline as ${result.displayId}`;
    }
  }
  revalidatePath("/");
  revalidatePath("/pipeline");
  return {
    success: true as const,
    message: `Logged ${args.outcome.replace(/_/g, " ")} · ${followupLabel(args.outcome)}${promotionMessage}`,
    data: { callId: call.id, outcome: args.outcome },
  };
}

/** Direct JSON-args variant — preferred when calling from a Client Component
 * via `action({...})`. Survives Next.js server-action RPC reliably (FormData
 * passed as a function arg does not always round-trip). */
export async function logCallArgs(
  args: z.infer<typeof callSchema>,
): Promise<ActionResult<{ callId: number; outcome: string }>> {
  const parsed = callSchema.safeParse(args);
  if (!parsed.success) {
    return { success: false, error: parsed.error.message };
  }
  try {
    return await doLogCall(parsed.data);
  } catch (e) {
    return { success: false, error: (e as Error).message };
  }
}

/** FormData variant — used by `<form action={logCall}>` and ActionForm. */
export async function logCall(
  formData: FormData,
): Promise<ActionResult<{ callId: number; outcome: string }>> {
  const parsed = callSchema.safeParse({
    parcelId: formData.get("parcelId"),
    county: formData.get("county"),
    owner: formData.get("owner"),
    siteAddr: formData.get("siteAddr"),
    outcome: formData.get("outcome"),
    notes: formData.get("notes"),
  });
  if (!parsed.success) {
    return { success: false, error: "Invalid call data: " + parsed.error.message };
  }
  try {
    return await doLogCall(parsed.data);
  } catch (e) {
    return { success: false, error: (e as Error).message };
  }
}

async function doLogDoorknock(args: z.infer<typeof callSchema>) {
  const knock = await db.doorknock.create({
    data: {
      parcelId: args.parcelId,
      county: args.county.toUpperCase(),
      owner: args.owner,
      siteAddr: args.siteAddr,
      outcome: args.outcome,
      notes: args.notes || null,
    },
  });
  let promotionMessage = "";
  if (HOT_OUTCOMES.has(args.outcome)) {
    const result = await ensureLeadDeal({
      parcelId: args.parcelId,
      county: args.county,
      owner: args.owner,
      siteAddr: args.siteAddr,
    });
    if (result.created) {
      promotionMessage = ` · added to pipeline as ${result.displayId}`;
    } else if (result.displayId) {
      promotionMessage = ` · already in pipeline as ${result.displayId}`;
    }
  }
  revalidatePath("/");
  revalidatePath("/pipeline");
  return {
    success: true as const,
    message: `Logged ${args.outcome.replace(/_/g, " ")} (door-knock)${promotionMessage}`,
    data: { knockId: knock.id, outcome: args.outcome },
  };
}

export async function logDoorknockArgs(
  args: z.infer<typeof callSchema>,
): Promise<ActionResult<{ knockId: number; outcome: string }>> {
  const parsed = callSchema.safeParse(args);
  if (!parsed.success) return { success: false, error: parsed.error.message };
  try {
    return await doLogDoorknock(parsed.data);
  } catch (e) {
    return { success: false, error: (e as Error).message };
  }
}

export async function logDoorknock(
  formData: FormData,
): Promise<ActionResult<{ knockId: number; outcome: string }>> {
  const parsed = callSchema.safeParse({
    parcelId: formData.get("parcelId"),
    county: formData.get("county"),
    owner: formData.get("owner"),
    siteAddr: formData.get("siteAddr"),
    outcome: formData.get("outcome"),
    notes: formData.get("notes"),
  });
  if (!parsed.success) return { success: false, error: "Invalid doorknock data: " + parsed.error.message };
  try {
    return await doLogDoorknock(parsed.data);
  } catch (e) {
    return { success: false, error: (e as Error).message };
  }
}

/** Undo a recently-logged call by id. */
export async function deleteCall(id: number): Promise<ActionResult> {
  try {
    await db.call.delete({ where: { id } });
    revalidatePath("/");
    return { success: true, message: "Reverted" };
  } catch (e) {
    return { success: false, error: (e as Error).message };
  }
}

export async function deleteDoorknock(id: number): Promise<ActionResult> {
  try {
    await db.doorknock.delete({ where: { id } });
    revalidatePath("/");
    return { success: true, message: "Reverted" };
  } catch (e) {
    return { success: false, error: (e as Error).message };
  }
}

/** Edit a logged call's outcome + notes. Re-derives the follow-up date from
 * the (possibly changed) outcome so the queue suppression stays correct. */
export async function updateCall(formData: FormData): Promise<ActionResult> {
  const id = Number(formData.get("id"));
  const outcome = (formData.get("outcome") ?? "").toString();
  const notes = (formData.get("notes") ?? "").toString();
  if (!id || !outcome) return { success: false, error: "id and outcome required" };
  try {
    await db.call.update({
      where: { id },
      data: { outcome, notes: notes || null, nextFollowup: followupDate(outcome) },
    });
    revalidatePath("/");
    revalidatePath(`/calls/${id}`);
    return { success: true, message: "Call updated" };
  } catch (e) {
    return { success: false, error: (e as Error).message };
  }
}

/** Edit a logged door-knock's outcome + notes. */
export async function updateDoorknock(formData: FormData): Promise<ActionResult> {
  const id = Number(formData.get("id"));
  const outcome = (formData.get("outcome") ?? "").toString();
  const notes = (formData.get("notes") ?? "").toString();
  if (!id || !outcome) return { success: false, error: "id and outcome required" };
  try {
    await db.doorknock.update({
      where: { id },
      data: { outcome, notes: notes || null },
    });
    revalidatePath("/");
    revalidatePath(`/doorknocks/${id}`);
    return { success: true, message: "Door-knock updated" };
  } catch (e) {
    return { success: false, error: (e as Error).message };
  }
}

/* ---------- Bulk endpoints ---------- */

const bulkSchema = z.object({
  outcome: z.string().min(1),
  parcels: z.array(
    z.object({
      parcelId: z.string().min(1),
      county: z.string().default(""),
      owner: z.string().default(""),
      siteAddr: z.string().default(""),
    }),
  ).min(1),
});

export async function logCallBulk(
  payload: z.infer<typeof bulkSchema>,
): Promise<ActionResult<{ inserted: number }>> {
  const parsed = bulkSchema.safeParse(payload);
  if (!parsed.success) return { success: false, error: "Invalid bulk payload" };
  const { outcome, parcels } = parsed.data;
  const fu = followupDate(outcome);
  try {
    await db.call.createMany({
      data: parcels.map((p) => ({
        parcelId: p.parcelId,
        county: p.county.toUpperCase(),
        owner: p.owner,
        siteAddr: p.siteAddr,
        outcome,
        nextFollowup: fu,
      })),
    });
    revalidatePath("/");
    return {
      success: true,
      message: `Logged ${parcels.length} ${outcome.replace(/_/g, " ")} ${parcels.length === 1 ? "call" : "calls"}`,
      data: { inserted: parcels.length },
    };
  } catch (e) {
    return { success: false, error: (e as Error).message };
  }
}

export async function logDoorknockBulk(
  payload: z.infer<typeof bulkSchema>,
): Promise<ActionResult<{ inserted: number }>> {
  const parsed = bulkSchema.safeParse(payload);
  if (!parsed.success) return { success: false, error: "Invalid bulk payload" };
  const { outcome, parcels } = parsed.data;
  try {
    await db.doorknock.createMany({
      data: parcels.map((p) => ({
        parcelId: p.parcelId,
        county: p.county.toUpperCase(),
        owner: p.owner,
        siteAddr: p.siteAddr,
        outcome,
      })),
    });
    revalidatePath("/");
    return {
      success: true,
      message: `Logged ${parcels.length} ${outcome.replace(/_/g, " ")} door-knocks`,
      data: { inserted: parcels.length },
    };
  } catch (e) {
    return { success: false, error: (e as Error).message };
  }
}

/* ---------- Clients ---------- */

const clientSchema = z.object({
  name: z.string().min(1),
  phone: z.string().default(""),
  altPhone: z.string().default(""),
  email: z.string().default(""),
  source: z.string().default(""),
  category: z.string().default(""),
  tags: z.string().default(""),
  anniversary: z.string().default(""),
  birthday: z.string().default(""),
  parcelId: z.string().default(""),
  county: z.string().default(""),
  referredById: z.string().default(""),
  notes: z.string().default(""),
});

/** Atomic count+create — eliminates the displayId race condition. */
async function nextClientDisplayId(): Promise<string> {
  return db.$transaction(async (tx) => {
    const count = await tx.client.count();
    return `C${String(count + 1).padStart(4, "0")}`;
  });
}

async function nextDealDisplayId(): Promise<string> {
  return db.$transaction(async (tx) => {
    const count = await tx.deal.count();
    return `D${String(count + 1).padStart(4, "0")}`;
  });
}

function clientFieldsFromForm(formData: FormData) {
  return clientSchema.safeParse({
    name: formData.get("name"),
    phone: formData.get("phone"),
    altPhone: formData.get("altPhone"),
    email: formData.get("email"),
    source: formData.get("source"),
    category: formData.get("category"),
    tags: formData.get("tags"),
    anniversary: formData.get("anniversary"),
    birthday: formData.get("birthday"),
    parcelId: formData.get("parcelId"),
    county: formData.get("county"),
    referredById: formData.get("referredById"),
    notes: formData.get("notes"),
  });
}

function clientWriteFields(data: z.infer<typeof clientSchema>) {
  return {
    name: data.name,
    phone: data.phone || null,
    altPhone: data.altPhone || null,
    email: data.email || null,
    source: data.source || null,
    category: data.category || null,
    tags: data.tags || null,
    anniversary: parseDate(data.anniversary),
    birthday: parseDate(data.birthday),
    parcelId: data.parcelId || null,
    county: data.county ? data.county.toUpperCase() : null,
    referredById: data.referredById || null,
    notes: data.notes || null,
  };
}

export async function addClient(
  formData: FormData,
): Promise<ActionResult<{ id: string; displayId: string }>> {
  const parsed = clientFieldsFromForm(formData);
  if (!parsed.success) return { success: false, error: parsed.error.message };
  try {
    const displayId = await nextClientDisplayId();
    const client = await db.client.create({
      data: { displayId, ...clientWriteFields(parsed.data) },
    });
    revalidatePath("/clients");
    return {
      success: true,
      message: `${client.name} added as ${displayId}`,
      data: { id: client.id, displayId: client.displayId },
    };
  } catch (e) {
    return { success: false, error: (e as Error).message };
  }
}

/** Variant of addClient that redirects to the new client's detail page on
 * success. Used by the "Convert prospect to client" flow. */
export async function addClientAndRedirect(formData: FormData) {
  const parsed = clientFieldsFromForm(formData);
  if (!parsed.success) {
    redirect("/clients?error=invalid");
  }
  const displayId = await nextClientDisplayId();
  const client = await db.client.create({
    data: { displayId, ...clientWriteFields(parsed.data) },
  });
  revalidatePath("/clients");
  redirect(`/clients/${client.id}`);
}

export async function updateClient(
  formData: FormData,
): Promise<ActionResult> {
  const id = formData.get("id")?.toString();
  if (!id) return { success: false, error: "client id required" };
  const parsed = clientFieldsFromForm(formData);
  if (!parsed.success) return { success: false, error: parsed.error.message };
  try {
    await db.client.update({
      where: { id },
      data: clientWriteFields(parsed.data),
    });
    revalidatePath("/clients");
    revalidatePath(`/clients/${id}`);
    return { success: true, message: "Client updated" };
  } catch (e) {
    return { success: false, error: (e as Error).message };
  }
}

/* ---------- Touches ---------- */

const touchSchema = z.object({
  clientId: z.string().min(1),
  kind: z.string().min(1),
  direction: z.string().default(""),
  notes: z.string().default(""),
  duration: z.string().default(""),
});

export async function logTouch(
  formData: FormData,
): Promise<ActionResult> {
  const parsed = touchSchema.safeParse({
    clientId: formData.get("clientId"),
    kind: formData.get("kind"),
    direction: formData.get("direction"),
    notes: formData.get("notes"),
    duration: formData.get("duration"),
  });
  if (!parsed.success) return { success: false, error: "Invalid touch data" };
  const data = parsed.data;
  try {
    await db.touch.create({
      data: {
        clientId: data.clientId,
        kind: data.kind,
        direction: data.direction || null,
        notes: data.notes || null,
        duration: data.duration ? parseInt(data.duration) : null,
      },
    });
    revalidatePath(`/clients/${data.clientId}`);
    revalidatePath("/clients");
    revalidatePath("/activity");
    return {
      success: true,
      message: `${data.kind.replace(/_/g, " ")} logged`,
    };
  } catch (e) {
    return { success: false, error: (e as Error).message };
  }
}

export async function deleteTouch(formData: FormData): Promise<ActionResult> {
  const id = formData.get("id")?.toString();
  const clientId = formData.get("clientId")?.toString();
  if (!id || !clientId) return { success: false, error: "id and clientId required" };
  try {
    await db.touch.delete({ where: { id } });
    revalidatePath(`/clients/${clientId}`);
    revalidatePath("/activity");
    return { success: true, message: "Touch deleted" };
  } catch (e) {
    return { success: false, error: (e as Error).message };
  }
}

/* ---------- Deals ---------- */

const dealSchema = z.object({
  clientDisplayId: z.string().default(""),
  clientId: z.string().default(""),
  stage: z.string().default("lead"),
  side: z.string().default("sell"),
  property: z.string().min(1),
  listPrice: z.string().default(""),
  expectedClose: z.string().default(""),
  estCommissionPct: z.string().default("3.0"),
  notes: z.string().default(""),
});

export async function addDeal(
  formData: FormData,
): Promise<ActionResult> {
  // FormData.get() returns null when the input isn't rendered (e.g. the
  // optional "Client ID" field is hidden when a clientCuid is already
  // selected). The dealSchema uses `z.string().default("")`, which only
  // covers `undefined` — null still fails. Coerce here.
  const g = (k: string) => (formData.get(k) ?? "").toString();
  const parsed = dealSchema.safeParse({
    clientDisplayId: g("clientId"), // legacy field name for the displayId
    clientId: g("clientCuid"),
    stage: g("stage"),
    side: g("side"),
    property: g("property"),
    listPrice: g("listPrice"),
    expectedClose: g("expectedClose"),
    estCommissionPct: g("estCommissionPct"),
    notes: g("notes"),
  });
  if (!parsed.success) return { success: false, error: parsed.error.message };
  const data = parsed.data;
  try {
    // Resolve either a direct cuid or a displayId-style "C0001"
    let clientCuid: string | null = data.clientId || null;
    if (!clientCuid && data.clientDisplayId) {
      const c = await db.client.findUnique({
        where: { displayId: data.clientDisplayId },
      });
      clientCuid = c?.id ?? null;
    }
    const displayId = await nextDealDisplayId();
    await db.deal.create({
      data: {
        displayId,
        clientId: clientCuid,
        stage: data.stage,
        side: data.side,
        property: data.property,
        listPrice: data.listPrice ? parseFloat(data.listPrice) : null,
        expectedClose: data.expectedClose ? new Date(data.expectedClose) : null,
        estCommissionPct: data.estCommissionPct ? parseFloat(data.estCommissionPct) : null,
        notes: data.notes || null,
      },
    });
    revalidatePath("/pipeline");
    if (clientCuid) revalidatePath(`/clients/${clientCuid}`);
    return { success: true, message: `Deal ${displayId} created` };
  } catch (e) {
    return { success: false, error: (e as Error).message };
  }
}

export async function updateDealStage(formData: FormData): Promise<ActionResult> {
  const dealId = formData.get("dealId")?.toString();
  const stage = formData.get("stage")?.toString();
  if (!dealId || !stage) return { success: false, error: "dealId and stage required" };
  const validStages = ["lead", "listing", "showing", "offer", "contract", "closing", "closed", "lost"];
  if (!validStages.includes(stage)) {
    return { success: false, error: `Invalid stage: ${stage}` };
  }
  try {
    const deal = await db.deal.findUnique({ where: { displayId: dealId } });
    if (!deal) return { success: false, error: "Deal not found" };
    if (deal.stage === stage) {
      return { success: true, message: "Stage unchanged" };
    }
    await db.$transaction([
      db.deal.update({ where: { displayId: dealId }, data: { stage } }),
      db.dealStage.create({
        data: { dealId: deal.id, stage, notes: `from ${deal.stage}` },
      }),
    ]);
    revalidatePath("/pipeline");
    revalidatePath(`/pipeline/${dealId}`);
    return { success: true, message: `Stage → ${stage}` };
  } catch (e) {
    return { success: false, error: (e as Error).message };
  }
}

/** Edit a deal's fields (everything except stage — use updateDealStage for that).
 * `clientId` carries a Client cuid to link, or "" to unlink. */
const dealEditSchema = z.object({
  displayId: z.string().min(1),
  side: z.string().min(1),
  property: z.string().min(1),
  clientId: z.string().default(""),
  listPrice: z.string().default(""),
  expectedClose: z.string().default(""),
  estCommissionPct: z.string().default(""),
  commissionEarned: z.string().default(""),
  notes: z.string().default(""),
});

export async function updateDeal(formData: FormData): Promise<ActionResult> {
  // Coerce null (absent inputs) to "" — z.string().default() only covers undefined.
  const g = (k: string) => (formData.get(k) ?? "").toString();
  const parsed = dealEditSchema.safeParse({
    displayId: g("displayId"),
    side: g("side"),
    property: g("property"),
    clientId: g("clientId"),
    listPrice: g("listPrice"),
    expectedClose: g("expectedClose"),
    estCommissionPct: g("estCommissionPct"),
    commissionEarned: g("commissionEarned"),
    notes: g("notes"),
  });
  if (!parsed.success) return { success: false, error: parsed.error.message };
  const data = parsed.data;
  try {
    const updated = await db.deal.update({
      where: { displayId: data.displayId },
      data: {
        side: data.side,
        property: data.property,
        clientId: data.clientId || null,
        listPrice: data.listPrice ? parseFloat(data.listPrice) : null,
        expectedClose: data.expectedClose ? new Date(data.expectedClose) : null,
        estCommissionPct: data.estCommissionPct ? parseFloat(data.estCommissionPct) : null,
        commissionEarned: data.commissionEarned ? parseFloat(data.commissionEarned) : null,
        notes: data.notes || null,
      },
    });
    revalidatePath("/pipeline");
    revalidatePath(`/pipeline/${data.displayId}`);
    revalidatePath("/clients");
    if (updated.clientId) revalidatePath(`/clients/${updated.clientId}`);
    return { success: true, message: "Deal updated" };
  } catch (e) {
    return { success: false, error: (e as Error).message };
  }
}

export async function deleteDeal(formData: FormData): Promise<ActionResult> {
  const displayId = formData.get("displayId")?.toString();
  if (!displayId) return { success: false, error: "displayId required" };
  try {
    await db.deal.update({
      where: { displayId },
      data: { deletedAt: new Date() },
    });
    revalidatePath("/pipeline");
    revalidatePath(`/pipeline/${displayId}`);
    return { success: true, message: "Deal deleted" };
  } catch (e) {
    return { success: false, error: (e as Error).message };
  }
}

export async function deleteClient(formData: FormData): Promise<ActionResult> {
  const id = formData.get("id")?.toString();
  if (!id) return { success: false, error: "id required" };
  try {
    await db.client.update({
      where: { id },
      data: { deletedAt: new Date() },
    });
    revalidatePath("/clients");
    revalidatePath(`/clients/${id}`);
    return { success: true, message: "Client deleted" };
  } catch (e) {
    return { success: false, error: (e as Error).message };
  }
}

/** Restore a soft-deleted client. */
export async function restoreClient(formData: FormData): Promise<ActionResult> {
  const id = formData.get("id")?.toString();
  if (!id) return { success: false, error: "id required" };
  try {
    await db.client.update({ where: { id }, data: { deletedAt: null } });
    revalidatePath("/clients");
    revalidatePath(`/clients/${id}`);
    return { success: true, message: "Client restored" };
  } catch (e) {
    return { success: false, error: (e as Error).message };
  }
}

/** Update a touch's notes / kind / direction. */
const touchEditSchema = z.object({
  id: z.string().min(1),
  notes: z.string().default(""),
  kind: z.string().optional(),
  direction: z.string().optional(),
});

export async function updateTouch(formData: FormData): Promise<ActionResult> {
  const parsed = touchEditSchema.safeParse({
    id: formData.get("id"),
    notes: formData.get("notes"),
    kind: formData.get("kind") ?? undefined,
    direction: formData.get("direction") ?? undefined,
  });
  if (!parsed.success) return { success: false, error: parsed.error.message };
  const data = parsed.data;
  try {
    const touch = await db.touch.update({
      where: { id: data.id },
      data: {
        notes: data.notes || null,
        ...(data.kind ? { kind: data.kind } : {}),
        ...(data.direction !== undefined ? { direction: data.direction || null } : {}),
      },
    });
    revalidatePath(`/clients/${touch.clientId}`);
    revalidatePath("/activity");
    return { success: true, message: "Touch updated" };
  } catch (e) {
    return { success: false, error: (e as Error).message };
  }
}

/** Merge `fromId` into `intoId` — move touches/deals, then soft-delete `fromId`. */
const mergeSchema = z.object({
  fromId: z.string().min(1),
  intoId: z.string().min(1),
});

export async function mergeClients(formData: FormData): Promise<ActionResult> {
  const parsed = mergeSchema.safeParse({
    fromId: formData.get("fromId"),
    intoId: formData.get("intoId"),
  });
  if (!parsed.success) return { success: false, error: parsed.error.message };
  const { fromId, intoId } = parsed.data;
  if (fromId === intoId) return { success: false, error: "Cannot merge a client into itself" };
  try {
    await db.$transaction([
      db.touch.updateMany({ where: { clientId: fromId }, data: { clientId: intoId } }),
      db.deal.updateMany({ where: { clientId: fromId }, data: { clientId: intoId } }),
      db.client.updateMany({
        where: { referredById: fromId },
        data: { referredById: intoId },
      }),
      db.client.update({ where: { id: fromId }, data: { deletedAt: new Date() } }),
    ]);
    revalidatePath("/clients");
    revalidatePath(`/clients/${intoId}`);
    return { success: true, message: "Merged into target" };
  } catch (e) {
    return { success: false, error: (e as Error).message };
  }
}

/** Dismiss a client's anniversary or birthday reminder for this year. */
export async function acknowledgeReminder(formData: FormData): Promise<ActionResult> {
  const id = formData.get("id")?.toString();
  const kind = formData.get("kind")?.toString(); // "anniversary" | "birthday"
  if (!id || !kind) return { success: false, error: "id and kind required" };
  const year = new Date().getFullYear();
  try {
    await db.client.update({
      where: { id },
      data:
        kind === "anniversary"
          ? { anniversaryAckYear: year }
          : { birthdayAckYear: year },
    });
    revalidatePath(`/clients/${id}`);
    revalidatePath("/clients");
    revalidatePath("/");
    return { success: true, message: `Dismissed for ${year}` };
  } catch (e) {
    return { success: false, error: (e as Error).message };
  }
}

/* ---------- Prospect notes (notes on a parcel without converting) ---------- */

const prospectNoteSchema = z.object({
  parcelId: z.string().min(1),
  county: z.string().default(""),
  body: z.string().min(1),
});

export async function addProspectNote(formData: FormData): Promise<ActionResult> {
  const parsed = prospectNoteSchema.safeParse({
    parcelId: formData.get("parcelId"),
    county: formData.get("county"),
    body: formData.get("body"),
  });
  if (!parsed.success) return { success: false, error: parsed.error.message };
  const data = parsed.data;
  try {
    await db.prospectNote.create({
      data: {
        parcelId: data.parcelId,
        county: (data.county || "").toUpperCase(),
        body: data.body,
      },
    });
    revalidatePath(`/prospect/${encodeURIComponent(data.parcelId)}`);
    return { success: true, message: "Note saved" };
  } catch (e) {
    return { success: false, error: (e as Error).message };
  }
}

export async function deleteProspectNote(formData: FormData): Promise<ActionResult> {
  const id = formData.get("id")?.toString();
  const parcelId = formData.get("parcelId")?.toString();
  if (!id) return { success: false, error: "id required" };
  try {
    await db.prospectNote.delete({ where: { id } });
    if (parcelId) revalidatePath(`/prospect/${encodeURIComponent(parcelId)}`);
    return { success: true, message: "Note deleted" };
  } catch (e) {
    return { success: false, error: (e as Error).message };
  }
}

/** Edit a prospect note's body. */
export async function updateProspectNote(formData: FormData): Promise<ActionResult> {
  const id = formData.get("id")?.toString();
  const body = (formData.get("body") ?? "").toString().trim();
  if (!id) return { success: false, error: "id required" };
  if (!body) return { success: false, error: "Note body cannot be empty" };
  try {
    const note = await db.prospectNote.update({ where: { id }, data: { body } });
    revalidatePath(`/prospect-notes/${id}`);
    revalidatePath(`/prospect/${encodeURIComponent(note.parcelId)}`);
    return { success: true, message: "Note updated" };
  } catch (e) {
    return { success: false, error: (e as Error).message };
  }
}

/* ---------- Recordings ---------- */

/** Edit a recording's title + reviewed flag. Audio/transcript are managed by
 * the /api/recordings routes; this only touches the lightweight metadata. */
export async function updateRecordingMeta(formData: FormData): Promise<ActionResult> {
  const id = formData.get("id")?.toString();
  if (!id) return { success: false, error: "id required" };
  const title = (formData.get("title") ?? "").toString().trim();
  const reviewed = formData.get("reviewed") === "on" || formData.get("reviewed") === "true";
  try {
    const rec = await db.recording.update({
      where: { id },
      data: { title: title || null, reviewed },
    });
    revalidatePath(`/recordings/${id}`);
    revalidatePath(`/clients/${rec.clientId}`);
    return { success: true, message: "Recording updated" };
  } catch (e) {
    return { success: false, error: (e as Error).message };
  }
}

// ---------------------------------------------------------------------------
// Saved searches
// ---------------------------------------------------------------------------

import {
  createSavedSearch,
  updateSavedSearch,
  deleteSavedSearch,
  type SearchCriteria,
} from "@/lib/data/saved-searches";
import {
  runAllSavedSearches,
  installHourlySchedule,
} from "@/lib/data/saved-searches-runner";

function parseNum(v: FormDataEntryValue | null): number | undefined {
  if (v == null) return undefined;
  const s = v.toString().trim();
  if (!s) return undefined;
  const n = Number(s);
  return Number.isFinite(n) ? n : undefined;
}

function parseList(v: FormDataEntryValue | null): string[] | undefined {
  if (v == null) return undefined;
  const items = v
    .toString()
    .split(/[,\n]/)
    .map((s) => s.trim())
    .filter(Boolean);
  return items.length ? items : undefined;
}

function parseChecks(formData: FormData, prefix: string): string[] | undefined {
  const all = formData.getAll(prefix).map((v) => v.toString()).filter(Boolean);
  return all.length ? all : undefined;
}

/** Best-effort geocode via OSM Nominatim. Honors their fair-use policy with
 * a custom User-Agent. Returns null on any failure — caller falls back to
 * pasted lat/lng. */
async function geocodeNominatim(
  query: string,
): Promise<{ lat: number; lng: number; displayName: string } | null> {
  try {
    const url = new URL("https://nominatim.openstreetmap.org/search");
    url.searchParams.set("q", query);
    url.searchParams.set("format", "json");
    url.searchParams.set("limit", "1");
    url.searchParams.set("countrycodes", "us");
    const r = await fetch(url, {
      headers: { "User-Agent": "MLSBot Dashboard (zstotz5528@gmail.com)" },
    });
    if (!r.ok) return null;
    const arr = (await r.json()) as Array<{ lat: string; lon: string; display_name: string }>;
    if (!arr.length) return null;
    return {
      lat: parseFloat(arr[0].lat),
      lng: parseFloat(arr[0].lon),
      displayName: arr[0].display_name,
    };
  } catch {
    return null;
  }
}

function criteriaFromForm(formData: FormData): SearchCriteria {
  const c: SearchCriteria = {};
  const classes = parseChecks(formData, "classes");
  if (classes) c.classes = classes;
  const statuses = parseChecks(formData, "statuses");
  if (statuses) c.statuses = statuses;
  const districts = parseChecks(formData, "school_districts");
  if (districts) c.school_districts = districts;
  const cities = parseList(formData.get("cities"));
  if (cities) c.cities = cities;
  c.price_min = parseNum(formData.get("price_min"));
  c.price_max = parseNum(formData.get("price_max"));
  c.beds_min = parseNum(formData.get("beds_min"));
  c.baths_min = parseNum(formData.get("baths_min"));
  c.sqft_min = parseNum(formData.get("sqft_min"));
  c.sqft_max = parseNum(formData.get("sqft_max"));
  c.acres_min = parseNum(formData.get("acres_min"));
  c.acres_max = parseNum(formData.get("acres_max"));
  c.radius_mi = parseNum(formData.get("radius_mi"));
  c.center_lat = parseNum(formData.get("center_lat"));
  c.center_lng = parseNum(formData.get("center_lng"));
  c.listed_within_days = parseNum(formData.get("listed_within_days"));
  // Strip undefined keys so the stored JSON is tight.
  return Object.fromEntries(
    Object.entries(c).filter(([, v]) => v !== undefined && v !== null && v !== ""),
  ) as SearchCriteria;
}

const saveSchema = z.object({
  name: z.string().min(1, "Name is required"),
  description: z.string().optional(),
  clientId: z.string().optional(),
  center_address: z.string().optional(),
});

async function buildCriteriaWithGeocode(
  formData: FormData,
): Promise<{ criteria: SearchCriteria; centerLabel: string | null }> {
  const criteria = criteriaFromForm(formData);
  let centerLabel: string | null = null;
  const centerAddress = formData.get("center_address")?.toString().trim();
  if (centerAddress) {
    // If user pasted lat/lng directly in the address field as "lat, lng",
    // accept it without a network call.
    const m = /^\s*(-?\d{1,3}\.\d+)\s*,\s*(-?\d{1,3}\.\d+)\s*$/.exec(
      centerAddress,
    );
    if (m) {
      criteria.center_lat = parseFloat(m[1]);
      criteria.center_lng = parseFloat(m[2]);
      centerLabel = centerAddress;
    } else if (criteria.radius_mi || true) {
      // Geocode the address. If geocoding fails we still save the search
      // and surface the address in centerLabel; the radius filter will be
      // skipped at run time because center_lat/lng are missing.
      const geo = await geocodeNominatim(centerAddress);
      if (geo) {
        criteria.center_lat = geo.lat;
        criteria.center_lng = geo.lng;
        centerLabel = centerAddress;
      } else {
        centerLabel = centerAddress;
      }
    }
  } else if (criteria.center_lat && criteria.center_lng) {
    centerLabel = `${criteria.center_lat.toFixed(4)}, ${criteria.center_lng.toFixed(4)}`;
  }
  return { criteria, centerLabel };
}

export async function addSavedSearchAndRedirect(formData: FormData) {
  const parsed = saveSchema.safeParse({
    name: formData.get("name")?.toString() ?? "",
    description: formData.get("description")?.toString() ?? "",
    clientId: formData.get("clientId")?.toString() ?? "",
    center_address: formData.get("center_address")?.toString() ?? "",
  });
  if (!parsed.success) {
    redirect("/searches/new?error=invalid");
  }
  const { criteria, centerLabel } = await buildCriteriaWithGeocode(formData);
  const search = await createSavedSearch({
    name: parsed.data.name,
    description: parsed.data.description || null,
    clientId: parsed.data.clientId || null,
    criteria,
    centerLabel,
  });
  // Kick off the runner so the user lands on a populated detail page instead
  // of waiting an hour. If the run fails, persist the error on the search row
  // so the user can see it on the detail page (vs. eternal "never").
  const r = await runAllSavedSearches();
  if (!r.ok) {
    await db.savedSearch.update({
      where: { id: search.id },
      data: {
        lastRunAt: new Date(),
        lastError: r.error ?? r.output.split(/\r?\n/).slice(-3).join(" | "),
      },
    });
  }
  revalidatePath("/searches");
  if (parsed.data.clientId) revalidatePath(`/clients/${parsed.data.clientId}`);
  redirect(`/searches/${search.id}`);
}

export async function runSavedSearchesAction(): Promise<ActionResult> {
  const r = await runAllSavedSearches();
  revalidatePath("/searches");
  if (!r.ok) {
    return {
      success: false,
      error: r.error ?? r.output.split(/\r?\n/).slice(-5).join(" | ") ?? "unknown error",
    };
  }
  return { success: true, message: "Saved searches refreshed" };
}

export async function installHourlyScheduleAction(): Promise<ActionResult> {
  const r = await installHourlySchedule();
  revalidatePath("/searches");
  if (!r.ok) {
    return {
      success: false,
      error: r.error ?? r.output.slice(-300) ?? "install failed",
    };
  }
  return {
    success: true,
    message: "MLSHourly scheduled task registered — running every hour.",
  };
}

export async function updateSavedSearchAction(
  formData: FormData,
): Promise<ActionResult> {
  const id = formData.get("id")?.toString();
  if (!id) return { success: false, error: "Missing id" };
  const name = formData.get("name")?.toString().trim();
  if (!name) return { success: false, error: "Name is required" };
  try {
    const { criteria, centerLabel } = await buildCriteriaWithGeocode(formData);
    await updateSavedSearch(id, {
      name,
      description: formData.get("description")?.toString() ?? "",
      clientId: formData.get("clientId")?.toString() || null,
      criteria,
      centerLabel,
    });
    revalidatePath("/searches");
    revalidatePath(`/searches/${id}`);
    return { success: true, message: "Search updated" };
  } catch (e) {
    return { success: false, error: (e as Error).message };
  }
}

export async function toggleSavedSearchPause(
  formData: FormData,
): Promise<ActionResult> {
  const id = formData.get("id")?.toString();
  const paused = formData.get("paused")?.toString() === "true";
  if (!id) return { success: false, error: "Missing id" };
  try {
    await updateSavedSearch(id, { isPaused: paused });
    revalidatePath("/searches");
    revalidatePath(`/searches/${id}`);
    return { success: true, message: paused ? "Paused" : "Resumed" };
  } catch (e) {
    return { success: false, error: (e as Error).message };
  }
}

export async function deleteSavedSearchAction(
  formData: FormData,
): Promise<ActionResult> {
  const id = formData.get("id")?.toString();
  if (!id) return { success: false, error: "Missing id" };
  try {
    await deleteSavedSearch(id);
    revalidatePath("/searches");
    return { success: true, message: "Search deleted" };
  } catch (e) {
    return { success: false, error: (e as Error).message };
  }
}
