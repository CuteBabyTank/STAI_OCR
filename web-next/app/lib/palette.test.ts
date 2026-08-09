/**
 * Contrast is a property of the stylesheet, not of any TS module, so this test
 * reads globals.css and checks the real token values. The point is the
 * regression guard: --ink-3 shipped at 2.63:1 in light and 3.70:1 in dark, and
 * nothing in the build would have complained. Now something does.
 */
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const css = readFileSync(new URL("../globals.css", import.meta.url), "utf8");

/** The declaration body of the first rule whose selector contains `selector`. */
function block(selector: string): string {
  const at = css.indexOf(selector);
  if (at < 0) throw new Error(`no rule containing selector: ${selector}`);
  const open = css.indexOf("{", at);
  const close = css.indexOf("}", open);
  if (open < 0 || close < 0) throw new Error(`unterminated rule: ${selector}`);
  return css.slice(open, close);
}

function token(body: string, name: string): string {
  const m = new RegExp(`--${name}\\s*:\\s*(#[0-9A-Fa-f]{6})`).exec(body);
  if (!m) throw new Error(`no --${name} in block`);
  return m[1];
}

/** WCAG 2.1 relative luminance. */
function luminance(hex: string): number {
  const ch = (i: number) => {
    const c = parseInt(hex.slice(1 + i * 2, 3 + i * 2), 16) / 255;
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * ch(0) + 0.7152 * ch(1) + 0.0722 * ch(2);
}

function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

const LIGHT = block(':root[data-theme="light"]');
const DARK = block(':root[data-theme="dark"]');

describe("text tokens clear WCAG AA (4.5:1)", () => {
  for (const [theme, body] of [["light", LIGHT], ["dark", DARK]] as const) {
    const surface = token(body, "surface");
    const canvas = token(body, "canvas");

    for (const ink of ["ink", "ink-2", "ink-3"]) {
      it(`${theme}: --${ink} on surface and canvas`, () => {
        const c = token(body, ink);
        expect(contrast(c, surface)).toBeGreaterThanOrEqual(4.5);
        expect(contrast(c, canvas)).toBeGreaterThanOrEqual(4.5);
      });
    }
  }
});

describe("the secondary/tertiary hierarchy survives the fix", () => {
  it("keeps --ink-3 lighter than --ink-2 in both themes", () => {
    for (const body of [LIGHT, DARK]) {
      const surface = token(body, "surface");
      expect(contrast(token(body, "ink-3"), surface))
        .toBeLessThan(contrast(token(body, "ink-2"), surface));
    }
  });
});
