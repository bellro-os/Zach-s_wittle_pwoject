/** POST /api/recordings/[id]/process — (re-)run transcription. Used to
 * retry after an error, or to backfill when DEEPGRAM_API_KEY is added
 * after the fact. */

import { NextRequest, NextResponse } from "next/server";
import { join } from "node:path";
import { db } from "@/lib/data/db";
import { transcribe, isTranscriptionConfigured } from "@/lib/transcribe";
import { revalidatePath } from "next/cache";

const RECORDINGS_DIR = join(process.cwd(), "recordings");

export async function POST(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  if (!isTranscriptionConfigured()) {
    return NextResponse.json(
      { error: "DEEPGRAM_API_KEY is not set. Add it to .env.local." },
      { status: 400 },
    );
  }
  const rec = await db.recording.findUnique({
    where: { id },
    select: { id: true, filename: true, mimeType: true, clientId: true },
  });
  if (!rec) return NextResponse.json({ error: "Not found" }, { status: 404 });

  await db.recording.update({
    where: { id },
    data: { status: "transcribing", error: null },
  });

  try {
    const result = await transcribe(join(RECORDINGS_DIR, rec.filename), rec.mimeType);
    await db.recording.update({
      where: { id },
      data: {
        status: "done",
        transcript: result.text,
        segmentsJson: JSON.stringify(result.paragraphs),
        durationSec: result.durationSec,
        completedAt: new Date(),
      },
    });
    revalidatePath(`/clients/${rec.clientId}`);
    return NextResponse.json({ success: true, status: "done" });
  } catch (e) {
    const message = (e as Error).message;
    await db.recording.update({
      where: { id },
      data: { status: "error", error: message },
    });
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}
