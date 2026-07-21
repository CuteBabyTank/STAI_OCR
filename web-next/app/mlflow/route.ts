import type { NextRequest } from "next/server";

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
  let html: string;
  let status = 200;
  try {
    const r = await fetch(`${MLFLOW_BASE}/mlflow/`, { headers: { accept: "text/html" } });
    status = r.status;
    html = await r.text();
  } catch (e: any) {
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
