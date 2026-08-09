"use client";
// Drop-in empty state for any route.
//
// The real component carries the animation runtime and only ever renders when a
// page has nothing in it, so loading it eagerly would bill every visitor who
// *does* have data — the common case — for art they never see. Splitting it here
// means every call site gets that for free, and `loading` holds the same box the
// loaded state occupies so arriving at it does not shift the page.
import dynamic from "next/dynamic";
import type { EmptyStateProps } from "./EmptyState";

const Impl = dynamic(() => import("./EmptyState"), {
  ssr: false,
  loading: () => <div className="es-reserve" aria-hidden="true" />,
});

const ImplPanel = dynamic(() => import("./EmptyState"), {
  ssr: false,
  loading: () => <div className="es-reserve-panel" aria-hidden="true" />,
});

export default function EmptyState(props: EmptyStateProps) {
  const C = props.size === "panel" ? ImplPanel : Impl;
  return <C {...props} />;
}

export type { EmptyStateProps };
