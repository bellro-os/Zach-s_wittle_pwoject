import type { MetadataRoute } from "next";

const BASE_URL = process.env.NEXT_PUBLIC_APP_URL || "http://localhost:4310";

export default function sitemap(): MetadataRoute.Sitemap {
  return ["/", "/join", "/signin"].map((path) => ({
    url: path === "/" ? BASE_URL : `${BASE_URL}${path}`,
    lastModified: new Date(),
    changeFrequency: "weekly",
    priority: path === "/" ? 1 : 0.6,
  }));
}
