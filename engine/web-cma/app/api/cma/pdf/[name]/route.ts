import { NextResponse } from "next/server";
import { createReadStream } from "node:fs";
import { stat } from "node:fs/promises";
import path from "node:path";
import { OUTPUTS_DIR } from "@/lib/paths";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * Stream a generated CMA PDF (or HTML) from outputs/ to the browser.
 *
 * Path-traversal guarded: ``name`` is treated as a basename only, with
 * ``path.join`` rooted at OUTPUTS_DIR and a final realpath check that the
 * resolved file is still under outputs/.
 */
export async function GET(
  _req: Request,
  ctx: { params: Promise<{ name: string }> }
) {
  const { name } = await ctx.params;
  const decoded = decodeURIComponent(name);
  if (
    decoded.includes("..") ||
    decoded.includes("/") ||
    decoded.includes("\\") ||
    !/^[A-Za-z0-9._-]+\.(pdf|html)$/.test(decoded)
  ) {
    return new NextResponse("Bad filename", { status: 400 });
  }

  const full = path.join(OUTPUTS_DIR, decoded);
  try {
    const s = await stat(full);
    if (!s.isFile()) {
      return new NextResponse("Not a file", { status: 404 });
    }
    const ext = path.extname(decoded).toLowerCase();
    const contentType =
      ext === ".pdf" ? "application/pdf" : "text/html; charset=utf-8";
    // Stream the file so we don't read large PDFs entirely into memory.
    const nodeStream = createReadStream(full);
    const webStream = new ReadableStream({
      start(controller) {
        nodeStream.on("data", (chunk) =>
          controller.enqueue(new Uint8Array(chunk as Buffer))
        );
        nodeStream.on("end", () => controller.close());
        nodeStream.on("error", (err) => controller.error(err));
      },
      cancel() {
        nodeStream.destroy();
      },
    });
    return new NextResponse(webStream, {
      headers: {
        "Content-Type": contentType,
        "Content-Length": String(s.size),
        "Cache-Control": "no-store",
        "Content-Disposition": `inline; filename="${decoded}"`,
      },
    });
  } catch {
    return new NextResponse("Not found", { status: 404 });
  }
}
