import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Native/node-API packages the bundler must leave to the Node runtime.
  serverExternalPackages: ["@prisma/client", "better-sqlite3"],
};

export default nextConfig;
