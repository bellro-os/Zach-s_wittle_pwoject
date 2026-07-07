import { NextResponse } from "next/server";
import { checkRateLimit, getClientIp } from "@/lib/compbird-ratelimit";
import { parseLatLng } from "@/lib/compbird/validate";

/**
 * Public Street View image proxy.
 *
 * Keeps the Google Maps key (if any) server-side: the client never sees it and
 * never calls Google directly. GET ?lat=&lng= streams back a single 640x400 JPEG
 * for the nearest panorama, or 404s so the client can show its link-out fallback.
 *
 * Behavior is intentionally graceful — this never throws and never 500s:
 *   - rate-limited          → 429
 *   - malformed coords      → 400 (NaN/Infinity/off-planet — a bad REQUEST,
 *                             not missing imagery; bounds in validate.ts)
 *   - no key configured     → 404 (client renders its fallback tile)
 *   - missing coords        → 404
 *   - no imagery here       → 404 (metadata status !== "OK")
 *   - any fetch failure     → 404
 */
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 10;

const notFound = () => new NextResponse(null, { status: 404 });

export async function GET(req: Request) {
  // Loose per-IP throttle — the proxy is cheap and day-cached.
  const rl = checkRateLimit("compbird:streetview", await getClientIp());
  if (rl.limited) {
    return NextResponse.json(
      { error: "Too many requests. Please slow down." },
      { status: 429, headers: { "Retry-After": String(rl.retryAfterSeconds) } },
    );
  }

  // Coordinate plausibility FIRST (before the key check) so a malformed request
  // is a 400 regardless of deployment config: absent coords keep the graceful
  // 404 contract, but NaN/Infinity/off-planet values are a caller bug.
  const url = new URL(req.url);
  const coords = parseLatLng(url.searchParams.get("lat"), url.searchParams.get("lng"));
  if (coords && "error" in coords) {
    return NextResponse.json({ error: coords.error }, { status: 400 });
  }
  if (!coords) return notFound();

  const key = process.env.GOOGLE_MAPS_API_KEY;
  // No key → 404 so the client shows its link-out fallback (no imagery available).
  if (!key) return notFound();

  const location = `${coords.lat},${coords.lng}`;

  try {
    // 1) Metadata first — cheap, free, tells us if a panorama actually exists.
    const metaUrl =
      `https://maps.googleapis.com/maps/api/streetview/metadata` +
      `?location=${encodeURIComponent(location)}&key=${encodeURIComponent(key)}`;
    const metaRes = await fetch(metaUrl, { cache: "no-store" });
    if (!metaRes.ok) return notFound();
    const meta = (await metaRes.json().catch(() => null)) as { status?: string } | null;
    if (!meta || meta.status !== "OK") return notFound();

    // 2) Fetch the actual tile.
    const imgUrl =
      `https://maps.googleapis.com/maps/api/streetview` +
      `?size=640x400&location=${encodeURIComponent(location)}` +
      `&fov=80&pitch=0&return_error_code=true&key=${encodeURIComponent(key)}`;
    const imgRes = await fetch(imgUrl, { cache: "no-store" });
    if (!imgRes.ok) return notFound();

    const bytes = await imgRes.arrayBuffer();
    if (!bytes.byteLength) return notFound();

    return new NextResponse(bytes, {
      status: 200,
      headers: {
        "Content-Type": "image/jpeg",
        "Cache-Control": "public, max-age=86400",
      },
    });
  } catch {
    // Network hiccup, abort, malformed response — degrade to the fallback.
    return notFound();
  }
}
