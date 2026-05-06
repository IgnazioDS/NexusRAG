// Rewrite the local /api/* path to the FastAPI BFF.
// In the unified Vercel deployment the FastAPI app is co-located with the
// dashboard (vercel.json routes /v1/* to api/index.py on the same origin),
// so the default base is empty (same-origin). For local dev, override with
// NEXT_PUBLIC_API_BASE or NEXUSRAG_API_URL to point at a remote backend.
const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ||
  process.env.NEXUSRAG_API_URL ||
  "";

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
