const API_URL = process.env.NEXUSRAG_API_URL ?? "http://localhost:8000";

/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    return [
      // Proxy all /api/* calls to the NexusRAG backend, stripping /api prefix.
      {
        source: "/api/:path*",
        destination: `${API_URL}/v1/:path*`,
      },
    ];
  },
};

export default nextConfig;
