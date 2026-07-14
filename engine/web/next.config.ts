import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // The dashboard reads seller_scores.csv from the project root,
  // so we explicitly include it (and other CSV sources) in the
  // server bundle file-tracing trace.
  outputFileTracingIncludes: {
    "/": ["../outputs/mls_analytics/leads/*.csv", "../data/dashboard/*.csv"],
  },
  experimental: {
    serverActions: { bodySizeLimit: "2mb" },
  },
};

export default nextConfig;
