import type { NextRequest } from "next/server";
import { proxyPostUntimed } from "../../lib/proxyUpstream";

// Single-receipt extraction, proxied with the socket timeout disabled so a slow
// vision read isn't cut off at the rewrite's 30s limit. See proxyUpstream.ts.
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 900; // best-effort hint (ignored by the standalone server)

export const POST = (req: NextRequest) => proxyPostUntimed(req, "/extract");
