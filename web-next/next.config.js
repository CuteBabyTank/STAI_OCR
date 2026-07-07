/** @type {import('next').NextConfig} */

// The browser calls same-origin "/api/*"; Next proxies it to the FastAPI service
// (no CORS). API_BASE is set per-environment: http://api:8000 in docker-compose,
// http://localhost:8001 for local dev against the dockerized API.
const API_BASE = process.env.API_BASE || "http://api:8000";

module.exports = {
  output: "standalone",
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_BASE}/:path*` }];
  },
};
