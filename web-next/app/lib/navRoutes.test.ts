/**
 * The sidebar and the phone tab bar both have to agree on which route is
 * "current", and `/wallet` is an ancestor of `/wallet/payments` — so a naive
 * prefix match lights up two entries at once. `activeHref` resolves that by
 * returning only the longest matching href. `tabForPath` then folds that answer
 * into one of five tabs, since the tab bar has five slots for ~20 routes.
 */
import { describe, expect, it } from "vitest";

import { activeHref, tabForPath } from "./navRoutes";

describe("activeHref", () => {
  it("matches the root only exactly", () => {
    expect(activeHref("/")).toBe("/");
    expect(activeHref("/history")).toBe("/history");
  });

  it("prefers the most specific match over its ancestor", () => {
    expect(activeHref("/wallet")).toBe("/wallet");
    expect(activeHref("/wallet/payments")).toBe("/wallet/payments");
  });

  it("resolves the routes the tab bar owns but the sidebar does not list", () => {
    expect(activeHref("/add")).toBe("/add");
    expect(activeHref("/scan")).toBe("/scan");
  });

  it("resolves nested group routes", () => {
    expect(activeHref("/plan/budgets")).toBe("/plan/budgets");
    expect(activeHref("/lending/receivable-activity")).toBe("/lending/receivable-activity");
  });

  it("does not match on a bare string prefix", () => {
    // "/historyz" starts with "/history" but is not a descendant of it.
    expect(activeHref("/historyz")).toBeNull();
  });

  it("returns null for an unknown route", () => {
    expect(activeHref("/nope")).toBeNull();
  });
});

describe("tabForPath", () => {
  it("maps the four navigable tabs", () => {
    expect(tabForPath("/")).toBe("home");
    expect(tabForPath("/history")).toBe("history");
    expect(tabForPath("/receipts")).toBe("receipts");
    expect(tabForPath("/settings")).toBe("more");
  });

  it("gives adding a receipt the centre slot rather than folding it into More", () => {
    // The whole point of the centre bubble: it owns a slot, so More does not
    // light up while you are adding a receipt.
    expect(tabForPath("/add")).toBe("add");
  });

  it("shares the centre slot between /add and the standalone camera flow", () => {
    // Two entrances to the same job; lighting a different tab for each is noise.
    expect(tabForPath("/scan")).toBe("add");
  });

  it("sends Wallet to More, since the centre slot took its place", () => {
    expect(tabForPath("/wallet")).toBe("more");
    expect(tabForPath("/wallet/payments")).toBe("more");
  });

  it("folds everything else into More, so the bar is never fully unlit", () => {
    expect(tabForPath("/plan/budgets")).toBe("more");
    expect(tabForPath("/lending/debts")).toBe("more");
    expect(tabForPath("/statistics")).toBe("more");
    expect(tabForPath("/settings")).toBe("more");
    expect(tabForPath("/nope")).toBe("more");
  });
});
