import type { NextRequest } from "next/server";
import { proxyPostUntimed } from "../../../lib/proxyUpstream";

// Batch extraction — the endpoint the Add-receipts UI actually calls.
//
// This route used to be missing, so /api/extract/batch fell through to the
// generic `/api/:path*` rewrite, which aborts at 30s. Every upload therefore
// failed with "The model took too long to read these receipts", even though the
// backend was reading the receipt fine (~100s for one page, minutes for a batch).
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 900; // best-effort hint (ignored by the standalone server)

export const POST = (req: NextRequest) => proxyPostUntimed(req, "/extract/batch");
