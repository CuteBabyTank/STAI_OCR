/** @type {import('next').NextConfig} */

// The browser calls same-origin "/api/*"; Next proxies it to the FastAPI service
// (no CORS). docker-compose sets API_BASE=http://api:8000 explicitly, so the
// fallback here is the local-dev target: a uvicorn (or the dockerized API's
// published port) on 8001. Defaulting to the compose hostname instead would make
// plain `npm run dev` fail with ENOTFOUND api, since "api" only resolves inside
// the compose network.
const API_BASE = process.env.API_BASE || "http://localhost:8001";

module.exports = {
  output: "standalone",
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_BASE}/:path*` }];
  },
};
