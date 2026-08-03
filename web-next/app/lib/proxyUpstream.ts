import http from "node:http";
import https from "node:https";
import type { NextRequest } from "next/server";
import { slog, serr, nextReqId, errFields, connHint } from "./serverLog";

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

// Printed once when the module first loads, so the very first line in the log
// says where this process will send extractions. API_BASE is read at RUNTIME here
// (unlike the next.config.js rewrite, which bakes it in at BUILD time) — setting
// it for the build but not for the server is a real and easy mistake, and it fails
// only on this path while the rest of the app looks healthy. Make it observable.
slog("extract-proxy", "upstream configured", {
  API_BASE,
  from: process.env.API_BASE ? "env" : "default (compose-only hostname)",
});

export function proxyPostUntimed(req: NextRequest, upstreamPath: string): Promise<Response> {
  return req.arrayBuffer().then(
    (buf) =>
      new Promise<Response>((resolve) => {
        const body = Buffer.from(buf);
        const url = new URL(`${API_BASE}${upstreamPath}${req.nextUrl.search}`);
        const client = url.protocol === "https:" ? https : http;

        const id = nextReqId("extract");
        const started = Date.now();
        const ms = () => Date.now() - started;
        slog("extract-proxy", "-> upstream", {
          id,
          url: url.toString(),
          bytes: body.length,
        });

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
            // A mid-response socket failure (upstream restarted, connection reset)
            // fires here, NOT on the request — without this the promise would never
            // settle and the browser would hang until it gave up on its own.
            res.on("error", (e: Error) => {
              serr("extract-proxy", "<- response stream failed", {
                id,
                ms: ms(),
                ...errFields(e),
              });
              resolve(
                new Response(
                  JSON.stringify({ detail: `Extraction proxy error (response): ${e.message}` }),
                  { status: 502, headers: { "content-type": "application/json" } },
                ),
              );
            });
            res.on("end", () => {
              const payload = Buffer.concat(chunks);
              const status = res.statusCode || 502;
              if (status >= 400) {
                // Include a slice of the body: FastAPI puts the real reason in
                // {"detail": ...}, and that reason is the whole point of the log.
                serr("extract-proxy", "<- upstream error status", {
                  id,
                  status,
                  ms: ms(),
                  body: payload.subarray(0, 500).toString("utf8"),
                });
              } else {
                slog("extract-proxy", "<- ok", { id, status, ms: ms(), bytes: payload.length });
              }
              resolve(
                new Response(payload, {
                  status,
                  headers: {
                    "content-type": res.headers["content-type"] || "application/json",
                  },
                }),
              );
            });
          },
        );

        upstream.on("error", (e: Error) => {
          const hint = connHint(e, API_BASE);
          serr("extract-proxy", "<- request failed", {
            id,
            url: url.toString(),
            ms: ms(),
            ...errFields(e),
            ...(hint ? { hint } : {}),
          });
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
