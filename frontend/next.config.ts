import type { NextConfig } from "next";

const backendUrl = process.env.BACKEND_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  /* config options here */
  // The Docker image runs Next's standalone server (frontend/Dockerfile sets NEXT_OUTPUT); a local
  // build stays a normal one, so `next start` keeps working.
  output: process.env.NEXT_OUTPUT === "standalone" ? "standalone" : undefined,
  cacheComponents: true,
  partialPrefetching: true,
  reactCompiler: true,
  // Next's gzip buffers a text/event-stream until the run ends, so off: progress events must pass
  // through the /api rewrite below as they happen (see CLAUDE.md).
  compress: false,
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
