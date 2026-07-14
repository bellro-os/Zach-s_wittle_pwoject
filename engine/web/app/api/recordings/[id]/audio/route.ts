/** GET /api/recordings/[id]/audio — stream the audio file. The frontend
 * `<audio>` element points here instead of the public/ path, which keeps
 * recordings out of the static asset URL space. */

import { NextRequest, NextResponse } from "next/server";
import { createReadStream, existsSync, statSync } from "node:fs";
import { join } from "node:path";
import { db } from "@/lib/data/db";

const RECORDINGS_DIR = join(process.cwd(), "recordings");

export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const rec = await db.recording.findUnique({
    where: { id },
    select: { filename: true, mimeType: true },
  });
  if (!rec) return NextResponse.json({ error: "Not found" }, { status: 404 });

  const filePath = join(RECORDINGS_DIR, rec.filename);
  if (!existsSync(filePath)) {
    return NextResponse.json({ error: "File missing on disk" }, { status: 404 });
  }

  const stat = statSync(filePath);
  const range = req.headers.get("range");

  if (range) {
    // Range request — HTML5 audio uses these for seeking. Parse and stream.
    const match = range.match(/bytes=(\d+)-(\d*)/);
    if (match) {
      const start = parseInt(match[1]);
      const end = match[2] ? parseInt(match[2]) : stat.size - 1;
      const chunkSize = end - start + 1;
      const stream = createReadStream(filePath, { start, end });
      return new NextResponse(stream as unknown as ReadableStream, {
        status: 206,
        headers: {
          "Content-Range": `bytes ${start}-${end}/${stat.size}`,
          "Accept-Ranges": "bytes",
          "Content-Length": chunkSize.toString(),
          "Content-Type": rec.mimeType,
        },
      });
    }
  }

  const stream = createReadStream(filePath);
  return new NextResponse(stream as unknown as ReadableStream, {
    headers: {
      "Content-Length": stat.size.toString(),
      "Content-Type": rec.mimeType,
      "Accept-Ranges": "bytes",
    },
  });
}
