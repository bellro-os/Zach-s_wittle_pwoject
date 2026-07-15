import type { MetadataRoute } from "next";

const BASE_URL = process.env.NEXT_PUBLIC_APP_URL?.trim() || "https://www.compbird.com";

// Bump when the marketing copy on these pages materially changes, so lastmod is
// truthful instead of "whenever the build ran" (the old `new Date()` reset it
// every deploy and told crawlers nothing).
const CONTENT_UPDATED = new Date("2026-07-15");

// Indexable marketing/legal pages only. NOTE: /signin is intentionally omitted
// (a login form has no organic value and shouldn't surface in SERPs); the
// app/studio surfaces (/comps, /account) are Disallowed in robots.ts.
const PAGES: { path: string; priority: number }[] = [
  { path: "/", priority: 1.0 },
  { path: "/pricing", priority: 0.9 },
  { path: "/join", priority: 0.5 },
  { path: "/terms", priority: 0.3 },
  { path: "/privacy", priority: 0.3 },
];

export default function sitemap(): MetadataRoute.Sitemap {
  return PAGES.map(({ path, priority }) => ({
    url: path === "/" ? BASE_URL : `${BASE_URL}${path}`,
    lastModified: CONTENT_UPDATED,
    changeFrequency: "monthly",
    priority,
  }));
}
