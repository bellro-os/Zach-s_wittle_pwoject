import type { NextConfig } from "next";
import { securityHeaders } from "./src/lib/security-headers";

const nextConfig: NextConfig = {
  // Native/node-API packages the bundler must leave to the Node runtime.
  serverExternalPackages: ["@prisma/client", "better-sqlite3"],
  // Self-contained production server (.next/standalone) — the Docker runtime
  // stage copies it + traced node_modules and runs `node server.js`. No effect
  // on `next dev`; `next start` still works off the regular .next build.
  output: "standalone",
  // Don't advertise the framework.
  poweredByHeader: false,
  // Security-header baseline (launch security review 2026-07). The CSP's
  // third-party allowances (OSM tiles, Meta/Google pixels) are documented in
  // src/lib/security-headers.ts next to the directives themselves.
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: securityHeaders(process.env.NODE_ENV !== "production"),
      },
    ];
  },
};

export default nextConfig;
