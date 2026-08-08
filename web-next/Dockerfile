# Multi-stage build for the Next.js frontend (standalone output).
FROM node:20-slim AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install

FROM node:20-slim AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
# next.config.js resolves API_BASE into the /api/:path* rewrite, and Next serializes
# rewrites into .next/routes-manifest.json at BUILD time — neither `next start` nor the
# standalone server.js re-reads next.config.js. So API_BASE has to be set HERE, not only
# in the runtime environment: with it missing the build bakes in the local-dev fallback
# (localhost:8001) and every proxied /api/* call inside the container dies with
# ECONNREFUSED, while /api/extract and /api/agent/stream keep working because those are
# route handlers that read API_BASE at runtime. Default to the compose service hostname.
ARG API_BASE=http://api:8000
ENV API_BASE=${API_BASE}
RUN npm run build

FROM node:20-slim AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
# standalone output bundles a minimal server + only the needed node_modules
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public
EXPOSE 3000
CMD ["node", "server.js"]
