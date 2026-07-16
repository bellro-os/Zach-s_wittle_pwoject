import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { SESSION_COOKIE, verifyAppSessionToken } from "@/lib/auth";

/**
 * compbird's auth wall. Public: the landing (/), the self-serve auth pages
 * (/join, /signin), and the API namespace (/api/*) — API routes enforce their
 * OWN auth + usage metering per-route (the paid artifact stream and the
 * metered generate both check the session server-side). Gated: the STUDIO
 * (/comps) requires a free account; anonymous visitors are sent to /join with
 * a redirect back. The redirect carries the ORIGINAL query string too, so
 * arrival intent (?demo=1 / ?address= / ?parcelId= / ?intent=) survives the
 * auth wall — safeAuthRedirect re-sanitizes it down to the whitelisted keys
 * on the way back out.
 */
export async function proxy(req: NextRequest) {
  const path = req.nextUrl.pathname;

  if (path === "/comps" || path.startsWith("/comps/")) {
    const session = await verifyAppSessionToken(req.cookies.get(SESSION_COOKIE)?.value);
    if (!session) {
      const url = req.nextUrl.clone();
      url.pathname = "/join";
      // `search` is "" or "?…", so this concatenation round-trips exactly.
      url.search = new URLSearchParams({ redirect: path + req.nextUrl.search }).toString();
      return NextResponse.redirect(url);
    }
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/comps", "/comps/:path*"],
};
