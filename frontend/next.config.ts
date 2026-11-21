import type { NextConfig } from "next";
// Rewrites so the browser's EventSource and fetches hit the FastAPI backend on the same origin.
const nextConfig: NextConfig = {
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${process.env.BACKEND_URL ?? "http://localhost:8000"}/api/:path*` }];
  },
};
export default nextConfig;
