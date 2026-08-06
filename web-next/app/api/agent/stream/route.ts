import type { NextRequest } from "next/server";
import { slog, serr, nextReqId, errFields, connHint } from "../../../lib/serverLog";

// Dedicated streaming proxy for the ReAct agent (Server-Sent Events).
//
// The generic `/api/:path*` rewrite in next.config.js proxies through a client
// that gives up after ~30s. The agent can take much longer than that — it runs a
// multi-step reasoning loop against a shared LLM — so the rewrite would cut the
// SSE stream off mid-answer and the chat would appear to "break". This route
// forwards the request and pipes the upstream event stream straight back to the
// browser with no such timeout, so long answers stream to completion.
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 900;

// Same fallback as next.config.js's rewrite, deliberately: "api" only resolves
// inside the compose network, so defaulting to it here made plain local dev fail
// with ENOTFOUND api on this route while the rewrite-served routes worked. Compose
// sets API_BASE explicitly (build arg + runtime), so both paths agree there too.
const API_BASE = process.env.API_BASE || "http://localhost:8001";

export async function POST(req: NextRequest): Promise<Response> {
  const body = await req.text();
  const id = nextReqId("agent");
  const started = Date.now();
  slog("agent-proxy", "-> upstream", { id, url: `${API_BASE}/agent/stream`, bytes: body.length });

  let upstream: Response;
  try {
    upstream = await fetch(`${API_BASE}/agent/stream`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body,
    });
  } catch (e: any) {
    // fetch() wraps the real network error in a generic "fetch failed", so the
    // useful code (ENOTFOUND / ECONNREFUSED) is on `e.cause`. Unwrap it, or the
    // log says nothing the browser didn't already show.
    const root = e?.cause ?? e;
    const hint = connHint(root, API_BASE);
    serr("agent-proxy", "<- request failed", {
      id,
      ms: Date.now() - started,
      ...errFields(root),
      ...(hint ? { hint } : {}),
    });
    return new Response(
      `data: ${JSON.stringify({ type: "error", message: `agent proxy: ${e?.message || e}` })}\n\n`,
      { status: 502, headers: { "content-type": "text/event-stream" } },
    );
  }

  if (!upstream.ok) {
    serr("agent-proxy", "<- upstream error status", {
      id,
      status: upstream.status,
      ms: Date.now() - started,
    });
  } else {
    slog("agent-proxy", "<- streaming", { id, status: upstream.status, ms: Date.now() - started });
  }

  // Pipe the upstream SSE body straight through, unbuffered.
  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      "content-type": "text/event-stream; charset=utf-8",
      "cache-control": "no-cache, no-transform",
      connection: "keep-alive",
      "x-accel-buffering": "no",
    },
  });
}
