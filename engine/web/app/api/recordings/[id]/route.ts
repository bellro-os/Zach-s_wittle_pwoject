/** GET /api/recordings/[id] — fetch a single recording's metadata + transcript.
 *  DELETE /api/recordings/[id] — remove the DB row + the audio file from disk. */

import { NextRequest, NextResponse } from "next/server";
import { unlink } from "node:fs/promises";
import { existsSync } from "node:fs";
import { join } from "node:path";
import { db } from "@/lib/data/db";
import { revalidatePath } from "next/cache";

const RECORDINGS_DIR = join(process.cwd(), "recordings");

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const rec = await db.recording.findUnique({
    where: { id },
    select: {
      id: true,
      clientId: true,
      status: true,
      durationSec: true,
      sizeBytes: true,
      mimeType: true,
      transcript: true,
      segmentsJson: true,
      createdAt: true,
      completedAt: true,
      error: true,
    },
  });
  if (!rec) return NextResponse.json({ error: "Not found" }, { status: 404 });
  return NextResponse.json(rec);
}

export async function DELETE(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const rec = await db.recording.findUnique({
    where: { id },
    select: { id: true, clientId: true, filename: true },
  });
  if (!rec) return NextResponse.json({ error: "Not found" }, { status: 404 });

  const filePath = join(RECORDINGS_DIR, rec.filename);
  try {
    if (existsSync(filePath)) await unlink(filePath);
  } catch {
    // Disk error shouldn't block the DB delete; the file may already be gone.
  }
  await db.recording.delete({ where: { id } });
  revalidatePath(`/clients/${rec.clientId}`);
  return NextResponse.json({ success: true });
}
