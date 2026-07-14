import type { NextConfig } from "next";

const config: NextConfig = {
  reactStrictMode: true,
  // The Python CMA builder produces large PDFs (200-500KB). Allow bigger response bodies.
  serverExternalPackages: [],
};

export default config;
