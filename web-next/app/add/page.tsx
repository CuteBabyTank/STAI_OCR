"use client";
// The phone tab bar's + lands here. A page rather than a sheet on purpose: the
// two ways in — upload a photo, or use the camera — are the whole point of the
// screen, and a sheet would put them under chrome that has to be dismissed
// before the staged files below are readable.
//
// It renders the same components as the Receipts page's Add dialog
// (ReceiptCapture.tsx) against the same run store, so a read started here shows
// up in the corner toast and survives navigating away mid-read.
import Link from "next/link";
import { CaptureChoices, CaptureQueue, RunOcrButton } from "../components/ReceiptCapture";

export default function AddReceiptPage() {
  return (
    <main>
      <header>
        <div>
          <h1>Add a receipt</h1>
          <p className="subhead">Upload a photo, or take one now.</p>
        </div>
      </header>

      <div className="card">
        <CaptureChoices />
      </div>

      <CaptureQueue />

      {/* Full width because on a phone this is the page's primary action, not
          one button among several in a dialog footer. */}
      <div className="add-run">
        <RunOcrButton />
      </div>

      <p className="muted-note">
        Filed receipts land in <Link className="link" href="/receipts">Receipts</Link>.
      </p>
    </main>
  );
}
