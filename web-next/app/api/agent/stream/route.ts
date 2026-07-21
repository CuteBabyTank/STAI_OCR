import type { NextRequest } from "next/server";

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

const API_BASE = process.env.API_BASE || "http://api:8000";

export async function POST(req: NextRequest): Promise<Response> {
  const body = await req.text();
  let upstream: Response;
  try {
    upstream = await fetch(`${API_BASE}/agent/stream`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body,
    });
  } catch (e: any) {
    return new Response(
      `data: ${JSON.stringify({ type: "error", message: `agent proxy: ${e?.message || e}` })}\n\n`,
      { status: 502, headers: { "content-type": "text/event-stream" } },
    );
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
