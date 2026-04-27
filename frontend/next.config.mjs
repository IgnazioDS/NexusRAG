// Rewrite the local /api/* path to the FastAPI BFF.
// In production we point at the deployed NexusRAG API. In development
// the same host can be overridden with NEXT_PUBLIC_API_BASE / NEXUSRAG_API_URL.
const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ||
  process.env.NEXUSRAG_API_URL ||
  "https://nexusrag-lyart.vercel.app";

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  experimental: {
    optimizePackageImports: ["lucide-react", "recharts"],
  },
  async rewrites() {
    return [
      // Public telemetry endpoint stays canonical (no /v1 prefix).
      { source: "/api/stats", destination: `${API_BASE}/api/stats` },
      // Versioned BFF endpoints.
      { source: "/api/:path*", destination: `${API_BASE}/v1/:path*` },
    ];
  },
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "X-Frame-Options", value: "DENY" },
          {
            key: "Permissions-Policy",
            value: "camera=(), microphone=(), geolocation=()",
          },
        ],
      },
    ];
  },
};

export default nextConfig;
