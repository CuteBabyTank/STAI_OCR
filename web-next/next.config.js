/** @type {import('next').NextConfig} */

// The browser calls same-origin "/api/*"; Next proxies it to the FastAPI service
// (no CORS). The fallback here is the local-dev target: a uvicorn (or the
// dockerized API's published port) on 8001. Defaulting to the compose hostname
// instead would make plain `npm run dev` fail with ENOTFOUND api, since "api"
// only resolves inside the compose network.
//
// BUILD TIME, NOT RUNTIME: Next serializes rewrites into .next/routes-manifest.json
// during `next build`, and neither `next start` nor the standalone server.js re-reads
// this file. Setting API_BASE only in the server's environment therefore does nothing
// for the rewrite — it must be set for the build. web-next/Dockerfile takes it as an
// ARG and docker-compose.yml passes it as both a build arg and a runtime variable.
const API_BASE = process.env.API_BASE || "http://localhost:8001";

module.exports = {
  output: "standalone",
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_BASE}/:path*` }];
  },
};
