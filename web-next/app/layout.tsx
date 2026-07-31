import type { Metadata } from "next";
import "./globals.css";
import AppShell from "./components/AppShell";
import { OcrJobsProvider } from "./lib/ocrJobs";

export const metadata: Metadata = {
  title: "Receipt Ledger",
  description: "Scan receipts, track spending, ask your receipts anything.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      {/* AppShell holds the persistent Sidebar + FAB; each route renders only its
          <main> into it, so the chrome no longer remounts on navigation.
          OcrJobsProvider sits OUTSIDE AppShell so the shell itself can read the
          run state (it moves the quick-add FAB aside for the progress toast). */}
      <body>
        <OcrJobsProvider>
          <AppShell>{children}</AppShell>
        </OcrJobsProvider>
      </body>
    </html>
  );
}
