import type { Metadata, Viewport } from "next";
import "./globals.css";
import AppShell from "./components/AppShell";
import { OcrJobsProvider } from "./lib/ocrJobs";

export const metadata: Metadata = {
  title: "Receipt Ledger",
  description: "Scan receipts, track spending, ask your receipts anything.",
  // Standalone mode on iOS, so a home-screen shortcut opens without Safari chrome.
  appleWebApp: { capable: true, title: "Ledger", statusBarStyle: "default" },
};

// Next injects a default viewport tag, but not `viewport-fit=cover` — without it
// iOS letterboxes the page on notched devices and every env(safe-area-inset-*)
// in globals.css resolves to 0. `maximumScale` is deliberately absent: capping
// zoom would lock out anyone who needs to magnify the ledger.
//
// themeColor is the light canvas unconditionally, matching the default theme —
// a prefers-color-scheme split here would paint the browser chrome dark around
// a light page for anyone whose OS is set to dark.
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: "#F7F8FA",
};

// Runs before the first paint (Next inlines a beforeInteractive-equivalent inside
// <head> when the script is rendered here). Only a saved "dark" preference does
// anything — the default is already light in CSS, so there is nothing to apply and
// nothing to flash. Wrapped in try/catch because localStorage throws outright in
// Safari private mode, and a theme preference is not worth a blank page.
const THEME_INIT = `try{if(localStorage.getItem('theme')==='dark')document.documentElement.setAttribute('data-theme','dark')}catch(e){}`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        {/* Sets data-theme before React hydrates, so a saved dark preference is
            already on <html> when the page first paints. suppressHydrationWarning
            on <html> is required: the server renders no attribute and this script
            may add one before hydration compares them. */}
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT }} />
      </head>
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
