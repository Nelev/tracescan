import type { NextConfig } from "next";

const backendUrl = process.env.BACKEND_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  /* config options here */
  cacheComponents: true,
  partialPrefetching: true,
  reactCompiler: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  // Same-origin proxy to the FastAPI backend, which has no CORS middleware.
  async rewrites() {
    return [
      { source: "/api/health", destination: `${backendUrl}/health` },
      { source: "/api/:path*", destination: `${backendUrl}/v1/:path*` },
    ];
  },
};

export default nextConfig;
