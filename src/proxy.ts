import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { SESSION_COOKIE, verifyAppSessionToken } from "@/lib/auth";

/**
 * compbird's auth wall. Public: the landing (/), the self-serve auth pages
 * (/join, /signin), and the API namespace (/api/*) — API routes enforce their
 * OWN auth + usage metering per-route (the paid artifact stream and the
 * metered generate both check the session server-side). Gated: the STUDIO
 * (/comps) requires a free account; anonymous visitors are sent to /join with
 * a redirect back.
 */
export async function proxy(req: NextRequest) {
  const path = req.nextUrl.pathname;

  if (path === "/comps" || path.startsWith("/comps/")) {
    const session = await verifyAppSessionToken(req.cookies.get(SESSION_COOKIE)?.value);
    if (!session) {
      const url = req.nextUrl.clone();
      url.pathname = "/join";
      url.search = new URLSearchParams({ redirect: path }).toString();
      return NextResponse.redirect(url);
    }
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/comps", "/comps/:path*"],
};
