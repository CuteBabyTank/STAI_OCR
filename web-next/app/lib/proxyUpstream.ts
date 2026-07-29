import http from "node:http";
import https from "node:https";
import type { NextRequest } from "next/server";

// Server-only: forwards a POST to the FastAPI service with NO socket timeout.
//
// Why this exists: the generic `/api/:path*` rewrite in next.config.js proxies
// through a client that gives up after exactly 30s and replies with a plain-text
// "Internal Server Error" (which the browser then can't parse as JSON). A 7B
// vision model reading one receipt takes ~100s, and a batch takes minutes, so
// every real extraction died at the 30s mark. Route handlers that bypass that
// rewrite call this instead.
//
// IMPORTANT: array-form rewrites are checked BEFORE dynamic routes, so a
// catch-all (`[[...path]]`) route handler here would still lose to the rewrite.
// Each endpoint needs its own STATIC route file (/api/extract, /api/extract/batch).
const API_BASE = process.env.API_BASE || "http://api:8000";

export function proxyPostUntimed(req: NextRequest, upstreamPath: string): Promise<Response> {
  return req.arrayBuffer().then(
    (buf) =>
      new Promise<Response>((resolve) => {
        const body = Buffer.from(buf);
        const url = new URL(`${API_BASE}${upstreamPath}${req.nextUrl.search}`);
        const client = url.protocol === "https:" ? https : http;

        const upstream = client.request(
          {
            protocol: url.protocol,
            hostname: url.hostname,
            port: url.port || (url.protocol === "https:" ? 443 : 80),
            path: url.pathname + url.search,
            method: "POST",
            headers: {
              "content-type": req.headers.get("content-type") || "application/octet-stream",
              "content-length": body.length,
            },
          },
          (res) => {
            const chunks: Buffer[] = [];
            res.on("data", (c: Buffer) => chunks.push(c));
            res.on("end", () => {
              resolve(
                new Response(Buffer.concat(chunks), {
                  status: res.statusCode || 502,
                  headers: {
                    "content-type": res.headers["content-type"] || "application/json",
                  },
                }),
              );
            });
          },
        );

        upstream.on("error", (e: Error) => {
          resolve(
            new Response(JSON.stringify({ detail: `Extraction proxy error: ${e.message}` }), {
              status: 502,
              headers: { "content-type": "application/json" },
            }),
          );
        });

        // The socket sits idle for minutes while the model reads a page — never
        // let either end time it out.
        upstream.setTimeout(0);
        upstream.on("socket", (s) => s.setTimeout(0));
        upstream.write(body);
        upstream.end();
      }),
  );
}
