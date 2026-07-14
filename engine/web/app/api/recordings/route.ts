/** POST /api/recordings — upload an audio blob, create a Recording row,
 * kick off background transcription. Returns the created Recording id.
 *
 * GET /api/recordings?clientId=… — list recordings for a client. */

import { NextRequest, NextResponse } from "next/server";
import { mkdir, writeFile } from "node:fs/promises";
import { join, extname } from "node:path";
import { db } from "@/lib/data/db";
import { transcribe, isTranscriptionConfigured } from "@/lib/transcribe";

const RECORDINGS_DIR = join(process.cwd(), "recordings");

function extFromMime(mime: string, fallback = ".webm"): string {
  if (mime.includes("webm")) return ".webm";
  if (mime.includes("ogg")) return ".ogg";
  if (mime.includes("mp4")) return ".m4a";
  if (mime.includes("mpeg")) return ".mp3";
  if (mime.includes("wav")) return ".wav";
  if (mime.includes("flac")) return ".flac";
  return fallback;
}

export async function POST(req: NextRequest) {
  const formData = await req.formData();
  const audio = formData.get("audio");
  const clientId = formData.get("clientId")?.toString();
  const filenameHint = formData.get("filename")?.toString() ?? "";

  if (!clientId) {
    return NextResponse.json({ error: "clientId is required" }, { status: 400 });
  }
  if (!(audio instanceof Blob)) {
    return NextResponse.json({ error: "audio file required" }, { status: 400 });
  }

  // Verify the client exists (don't trust the form input)
  const client = await db.client.findUnique({
    where: { id: clientId },
    select: { id: true },
  });
  if (!client) {
    return NextResponse.json({ error: "Client not found" }, { status: 404 });
  }

  const mimeType = audio.type || "audio/webm";
  const ext = filenameHint ? extname(filenameHint) || extFromMime(mimeType) : extFromMime(mimeType);

  // Create the recording row first to get the id
  const recording = await db.recording.create({
    data: {
      clientId,
      filename: "", // updated below once we know the path
      mimeType,
      sizeBytes: audio.size,
      status: "uploaded",
    },
  });

  // Save to disk under recordings/<clientId>/<recordingId>.<ext>
  const clientDir = join(RECORDINGS_DIR, clientId);
  await mkdir(clientDir, { recursive: true });
  const relPath = `${clientId}/${recording.id}${ext}`;
  const fullPath = join(RECORDINGS_DIR, relPath);
  const buf = Buffer.from(await audio.arrayBuffer());
  await writeFile(fullPath, buf);

  await db.recording.update({
    where: { id: recording.id },
    data: { filename: relPath },
  });

  // Kick off transcription in the background. We don't await — return the
  // upload success immediately so the UI can show "transcribing" status.
  if (isTranscriptionConfigured()) {
    void runTranscription(recording.id, fullPath, mimeType);
  }

  return NextResponse.json({
    id: recording.id,
    status: "uploaded",
    transcriptionEnabled: isTranscriptionConfigured(),
  });
}

export async function GET(req: NextRequest) {
  const clientId = req.nextUrl.searchParams.get("clientId");
  if (!clientId) {
    return NextResponse.json({ error: "clientId required" }, { status: 400 });
  }
  const recordings = await db.recording.findMany({
    where: { clientId },
    orderBy: { createdAt: "desc" },
    select: {
      id: true,
      status: true,
      durationSec: true,
      sizeBytes: true,
      transcript: true,
      mimeType: true,
      createdAt: true,
      completedAt: true,
      error: true,
    },
  });
  return NextResponse.json({ recordings });
}

/** Background transcription job — best effort. */
async function runTranscription(id: string, fullPath: string, mimeType: string) {
  try {
    await db.recording.update({
      where: { id },
      data: { status: "transcribing" },
    });
    const result = await transcribe(fullPath, mimeType);
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
  } catch (e) {
    await db.recording.update({
      where: { id },
      data: {
        status: "error",
        error: (e as Error).message,
      },
    });
  }
}
