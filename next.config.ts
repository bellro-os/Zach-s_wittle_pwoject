import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Native/node-API packages the bundler must leave to the Node runtime.
  serverExternalPackages: ["@prisma/client", "better-sqlite3"],
  // Self-contained production server (.next/standalone) — the Docker runtime
  // stage copies it + traced node_modules and runs `node server.js`. No effect
  // on `next dev`; `next start` still works off the regular .next build.
  output: "standalone",
};

export default nextConfig;
