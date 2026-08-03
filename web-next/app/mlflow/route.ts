import type { NextRequest } from "next/server";
import { slog, serr, nextReqId, errFields, connHint } from "../lib/serverLog";

// Serves the MLflow UI shell at /mlflow. MLflow's index.html references its JS/CSS
// with RELATIVE paths (e.g. "static-files/static/js/main.js"). Since the browser
// lands on /mlflow (no trailing slash), those relatives would resolve against the
// site root (/static-files/...) and 404 → blank white screen. We fetch the shell
// and inject <base href="/mlflow/"> so every relative asset/API path resolves under
// /mlflow/, where the next.config rewrite proxies it to the MLflow server.
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const MLFLOW_BASE = process.env.MLFLOW_BASE || "http://127.0.0.1:5000";

export async function GET(_req: NextRequest): Promise<Response> {
  const id = nextReqId("mlflow");
  const started = Date.now();
  let html: string;
  let status = 200;
  try {
    const r = await fetch(`${MLFLOW_BASE}/mlflow/`, { headers: { accept: "text/html" } });
    status = r.status;
    html = await r.text();
    slog("mlflow-proxy", "<- shell fetched", { id, status, ms: Date.now() - started });
  } catch (e: any) {
    // Unwrap fetch()'s generic "fetch failed" to reach the real errno.
    const root = e?.cause ?? e;
    serr("mlflow-proxy", "<- request failed", {
      id,
      url: `${MLFLOW_BASE}/mlflow/`,
      ms: Date.now() - started,
      ...errFields(root),
      hint:
        connHint(root, MLFLOW_BASE) ??
        `MLflow must be running separately — docker-compose started it, a raw deploy does not. ` +
          `Either start it (mlflow ui --host 0.0.0.0 --port 5000 --backend-store-uri ` +
          `sqlite:///<repo>/mlflow.db) or point MLFLOW_BASE elsewhere. /mlflow 502s until then.`,
    });
    return new Response(`MLflow proxy error: ${e?.message || e}`, { status: 502 });
  }

  const baseTag = '<base href="/mlflow/">';
  if (!/<base\s/i.test(html)) {
    if (/<head[^>]*>/i.test(html)) {
      html = html.replace(/<head[^>]*>/i, (m) => m + baseTag);
    } else if (/<html[^>]*>/i.test(html)) {
      html = html.replace(/<html[^>]*>/i, (m) => m + "<head>" + baseTag + "</head>");
    } else {
      html = baseTag + html;
    }
  }

  return new Response(html, {
    status,
    headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" },
  });
}
