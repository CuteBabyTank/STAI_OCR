import http from "node:http";
import https from "node:https";
import type { NextRequest } from "next/server";

// Dedicated proxy for receipt extraction.
//
// The generic `/api/:path*` rewrite in next.config.js proxies through a client
// that gives up after ~30s. A 7B vision model (qwen2.5vl) running partly on CPU
// can take several MINUTES to read one receipt and sends no bytes until it's
// done — so the rewrite would time out and return a plain "Internal Server Error"
// (which the browser then fails to parse as JSON). This route forwards the upload
// with the socket timeout DISABLED, so slow extractions run to completion.
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 900; // best-effort hint (ignored by the standalone server)

const API_BASE = process.env.API_BASE || "http://api:8000";

export async function POST(req: NextRequest): Promise<Response> {
  const body = Buffer.from(await req.arrayBuffer());
  const url = new URL(`${API_BASE}/extract`);
  const client = url.protocol === "https:" ? https : http;

  return await new Promise<Response>((resolve) => {
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
              headers: { "content-type": res.headers["content-type"] || "application/json" },
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

    // No response timeout — vision extraction on a large model can take minutes.
    upstream.setTimeout(0);
    upstream.write(body);
    upstream.end();
  });
}
