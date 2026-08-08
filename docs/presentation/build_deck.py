"""Build the Snag Final Capstone slide deck (STAI100) — diagram edition.

Run:  python docs/presentation/build_deck.py
Out:  docs/presentation/Snag_Final_Capstone.pptx

Design rule: every slide is a picture. Words appear inside a box, on an arrow, or
under a number — nowhere else. If a slide needs a sentence to make sense, the
diagram is wrong.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches, Pt

HERE = Path(__file__).resolve().parent
ASSETS = HERE / "assets"
OUT = HERE / "Snag_Final_Capstone.pptx"

AGENT = "Snag"
TAGLINE = "every peso traced back to the paper it came from"
LLM_LINE = ("Gemma 4 — e4b vision (OCR) + 12B text (planner)  ·  nomic-embed-text 137M  ·  "
            "served through Ollama")

TEAM = [
    ("Nathaniel Adiong", "Chat UI · API · Docker"),
    ("Clarence Ang", "Prompts · Schema · Guardrails"),
    ("Fraser Sim", "RAG · Memory · Tools"),
    ("Aaron Go", "SQL · ReAct · LLMOps"),
]
SECTIONS = ["Use case", "RRL", "Architecture", "Components", "Findings",
            "Retrospective", "Demo"]

# One neutral ramp, one accent, and two colours that mean something.
# Green and red are never decorative here: they only ever mean pass / fail.
INK = RGBColor(0x11, 0x18, 0x27)       # headings, dark blocks
BODY = RGBColor(0x37, 0x41, 0x51)      # body text
MUTED = RGBColor(0x6B, 0x72, 0x80)     # secondary text
FAINT = RGBColor(0x9C, 0xA3, 0xAF)     # tertiary text, inactive nav
LINE = RGBColor(0xE5, 0xE7, 0xEB)      # hairlines
GREY = RGBColor(0xD1, 0xD5, 0xDB)      # arrows
PAPER = RGBColor(0xFF, 0xFF, 0xFF)
WASH = RGBColor(0xF9, 0xFA, 0xFB)      # the one grouping fill
ACCENT = RGBColor(0xB4, 0x53, 0x09)    # emphasis, used sparingly
ACCENT_SOFT = RGBColor(0xFE, 0xF6, 0xE7)
GOOD = RGBColor(0x04, 0x78, 0x57)
GOOD_SOFT = RGBColor(0xEC, 0xFD, 0xF5)
BAD = RGBColor(0xB9, 0x1C, 0x1C)
BAD_SOFT = RGBColor(0xFE, 0xF2, 0xF2)

# Aliases, so the slide bodies keep reading naturally. Every decorative hue
# collapses onto the neutral ramp; only the semantic ones survive.
SOFT = WASH
T_GREY = WASH
TEAL = MUTED
VIOLET = MUTED
RED = BAD
GREEN = GOOD
T_TEAL = WASH
T_VIOLET = WASH
T_AMBER = ACCENT_SOFT
T_GREEN = GOOD_SOFT
T_RED = BAD_SOFT

FONT = "Segoe UI"
MONO = "Consolas"   # prompt excerpts and typed signatures
W, H = Inches(13.333), Inches(7.5)
M = Inches(0.7)
FULL = W - 2 * M
TOP = Inches(1.60)

facts = json.loads((ASSETS / "facts.json").read_text(encoding="utf-8"))
U = facts["uom"]
TRAJ = facts["trajectory"]

prs = Presentation()
prs.slide_width, prs.slide_height = W, H
BLANK = prs.slide_layouts[6]


# ------------------------------------------------------------------ primitives

def E(v):
    """Geometry must reach the XML as whole EMUs.

    Half this file computes positions by dividing widths, which yields floats;
    a float in an `off`/`ext` attribute produces a file PowerPoint refuses to
    open. Every primitive rounds through here, so callers can do arithmetic
    freely.
    """
    return Emu(int(round(float(v))))


def text(sl, x, y, w, h, runs, *, size=13, color=BODY, bold=False,
         align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, line=1.15, font=FONT):
    box = sl.shapes.add_textbox(E(x), E(y), E(w), E(h))
    tf = box.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = anchor
    paras = runs if isinstance(runs, list) else [runs]
    for i, para in enumerate(paras):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.line_spacing = line
        p.space_after = Pt(2)
        for chunk in (para if isinstance(para, list) else [(para, {})]):
            content, opts = chunk if isinstance(chunk, tuple) else (chunk, {})
            r = p.add_run()
            r.text = content
            r.font.name = opts.get("font", font)
            r.font.size = Pt(opts.get("size", size))
            r.font.bold = opts.get("bold", bold)
            r.font.italic = opts.get("italic", False)
            r.font.color.rgb = opts.get("color", color)
    return box


def rect(sl, x, y, w, h, *, fill=WASH, edge=LINE, edge_w=1.0, radius=0.05,
         shape=MSO_SHAPE.ROUNDED_RECTANGLE):
    s = sl.shapes.add_shape(shape, E(x), E(y), E(w), E(h))
    if fill is None:
        s.fill.background()
    else:
        s.fill.solid(); s.fill.fore_color.rgb = fill
    if edge is None:
        s.line.fill.background()
    else:
        s.line.color.rgb = edge; s.line.width = Pt(edge_w)
    if shape == MSO_SHAPE.ROUNDED_RECTANGLE:
        try:
            s.adjustments[0] = radius
        except (IndexError, ValueError):
            pass
    s.shadow.inherit = False
    s.text_frame.word_wrap = True
    return s


def label(sl, x, y, w, h, title, sub=None, *, fill=PAPER, edge=LINE, edge_w=1.0,
          accent=None, ts=12.5, ss=9.5, tc=INK, sc=MUTED, shape=MSO_SHAPE.ROUNDED_RECTANGLE):
    """A box with a bold line and an optional grey line under it."""
    s = rect(sl, x, y, w, h, fill=fill, edge=edge, edge_w=edge_w, shape=shape)
    tf = s.text_frame
    tf.margin_left = tf.margin_right = Inches(0.05)
    tf.margin_top = tf.margin_bottom = Inches(0.02)
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]; p.alignment = PP_ALIGN.CENTER; p.line_spacing = 1.0
    r = p.add_run(); r.text = title
    r.font.name = FONT; r.font.size = Pt(ts); r.font.bold = True; r.font.color.rgb = tc
    if sub:
        p2 = tf.add_paragraph(); p2.alignment = PP_ALIGN.CENTER; p2.line_spacing = 1.0
        r2 = p2.add_run(); r2.text = sub
        r2.font.name = FONT; r2.font.size = Pt(ss); r2.font.color.rgb = sc
    if accent:
        rect(sl, x, y, Inches(0.05), h, fill=accent, edge=None, shape=MSO_SHAPE.RECTANGLE)
    return s


def store(sl, x, y, w, h, title, sub=None):
    return label(sl, x, y, w, h, title, sub, fill=PAPER, edge=GREY, ts=11.5, ss=9,
                 shape=MSO_SHAPE.FLOWCHART_MAGNETIC_DISK)


def line(sl, x1, y1, x2, y2, *, color=GREY, w=1.25):
    c = sl.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, E(x1), E(y1), E(x2), E(y2))
    c.line.color.rgb = color; c.line.width = Pt(w)
    return c


def head(sl, x, y, *, color=GREY, direction="right", size=0.11):
    rot = {"right": 90, "left": 270, "down": 180, "up": 0}[direction]
    s = Inches(size)
    t = sl.shapes.add_shape(MSO_SHAPE.ISOSCELES_TRIANGLE,
                            E(x - s / 2), E(y - s / 2), E(s), E(s))
    t.fill.solid(); t.fill.fore_color.rgb = color
    t.line.fill.background(); t.rotation = rot; t.shadow.inherit = False
    return t


def arrow(sl, x1, y1, x2, y2, *, color=GREY, w=1.25, size=0.11):
    line(sl, x1, y1, x2, y2, color=color, w=w)
    d = ("right" if x2 > x1 else "left") if abs(y2 - y1) < abs(x2 - x1) else \
        ("down" if y2 > y1 else "up")
    head(sl, x2, y2, color=color, direction=d, size=size)


def chip(sl, x, y, txt, *, fill=WASH, color=BODY, size=10, h=0.30):
    w = Inches(0.30 + 0.098 * len(txt))
    s = rect(sl, x, y, w, Inches(h), fill=fill, edge=None, radius=0.5)
    tf = s.text_frame
    tf.margin_left = tf.margin_right = Inches(0.05)
    tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]; p.alignment = PP_ALIGN.CENTER
    r = p.add_run(); r.text = txt
    r.font.name = FONT; r.font.size = Pt(size); r.font.bold = True; r.font.color.rgb = color
    return x + w + Inches(0.10)


def mark(sl, x, y, kind, *, d=0.34):
    """A tick or a cross in a filled circle."""
    color, glyph = (GREEN, "✓") if kind == "ok" else (RED, "✗")
    c = rect(sl, x, y, Inches(d), Inches(d), fill=color, edge=None, radius=0.5)
    tf = c.text_frame; tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    p = tf.paragraphs[0]; p.alignment = PP_ALIGN.CENTER
    r = p.add_run(); r.text = glyph
    r.font.name = FONT; r.font.size = Pt(d * 40); r.font.bold = True; r.font.color.rgb = PAPER
    return c


def picture(sl, name, x, y, max_w, max_h, *, center=True):
    path = ASSETS / name
    pw, ph = Image.open(path).size
    sc = min(max_w / pw, max_h / ph)
    w, h = int(pw * sc), int(ph * sc)
    ox = int((max_w - w) / 2) if center else 0
    return sl.shapes.add_picture(str(path), E(x + ox), E(y), width=E(w), height=E(h))


def bignum(sl, x, y, w, value, cap, *, color=INK, vs=40, cs=11.5):
    text(sl, x, y, w, Inches(0.7), value, size=vs, bold=True, color=color,
         align=PP_ALIGN.CENTER)
    text(sl, x, y + Inches(vs * 0.0158), w, Inches(0.4), cap, size=cs, color=MUTED,
         align=PP_ALIGN.CENTER, line=1.15)


def flow(sl, y, boxes, *, x0=None, w=None, h=0.80, gap=0.20, ts=12, ss=9,
         arrow_color=GREY):
    """A left-to-right chain of boxes with arrows between them."""
    n = len(boxes)
    x0 = M if x0 is None else x0
    total = (FULL if w is None else w)
    bw = (total - Inches(gap) * (n - 1)) / n
    for i, b in enumerate(boxes):
        title, sub, fill, edge = (list(b) + [None, PAPER, LINE])[:4]
        x = x0 + (bw + Inches(gap)) * i
        label(sl, x, Inches(y), bw, Inches(h), title, sub, fill=fill, edge=edge,
              ts=ts, ss=ss)
        if i < n - 1:
            arrow(sl, x + bw + Inches(0.03), Inches(y + h / 2),
                  x + bw + Inches(gap - 0.03), Inches(y + h / 2), color=arrow_color)
    return bw


def note(sl, y, lead, body, *, fill=None, edge=None, h=0.56, size=12.5, tone=ACCENT,
         keep=False):
    """A footnote: a short accent rule, then the line. No box, no fill.

    Opt-in. Twenty-three of these made the deck a wall of asides; only the seven
    that carry a claim someone could challenge are still drawn. The rest of the
    calls stay in the source so the point is not lost, they just do not render.
    """
    if not keep:
        return
    rect(sl, M, Inches(y + 0.05), Inches(0.032), Inches(h - 0.10), fill=tone, edge=None,
         shape=MSO_SHAPE.RECTANGLE)
    text(sl, M + Inches(0.24), Inches(y + (h - 0.30) / 2), FULL - Inches(0.30),
         Inches(0.32), [[(lead + "   ", {"bold": True, "color": INK}),
                         (body, {"color": MUTED})]], size=size)


# ---------------------------------------------------------------- slide frame

_no = 0


def slide(section=None, title=None, kicker=None):
    global _no
    sl = prs.slides.add_slide(BLANK)
    _no += 1
    if section is not None:
        x = M
        for name in SECTIONS:
            on = name == section
            w = Inches(0.10 + 0.076 * len(name))
            text(sl, x, Inches(0.34), w, Inches(0.24), name, size=9.5, bold=on,
                 color=INK if on else FAINT)
            if on:
                rect(sl, x, Inches(0.585), w - Inches(0.12), Inches(0.022), fill=ACCENT,
                     edge=None, shape=MSO_SHAPE.RECTANGLE)
            x += w + Inches(0.16)
    if title:
        text(sl, M, Inches(0.80), Inches(11.9), Inches(0.5), title, size=28, bold=True,
             color=INK)
    if kicker:
        text(sl, M, Inches(1.30), Inches(12.0), Inches(0.3), kicker, size=12.5,
             color=MUTED)
    text(sl, M, Inches(7.06), Inches(9.0), Inches(0.3),
         [[(AGENT, {"bold": True, "color": MUTED}),
           (f"  ·  {TAGLINE}", {"color": FAINT})]], size=9)
    text(sl, W - M - Inches(2.4), Inches(7.06), Inches(2.4), Inches(0.3),
         f"{_no:02d}", size=9, color=FAINT, align=PP_ALIGN.RIGHT)
    return sl


# ============================================================ 1 · TITLE
s = slide()
rect(s, 0, 0, W, Inches(2.5), fill=INK, edge=None, shape=MSO_SHAPE.RECTANGLE)
text(s, M, Inches(0.52), Inches(11), Inches(0.7),
     [[("Snag", {"size": 56, "bold": True, "color": PAPER})]], size=56)
text(s, M, Inches(1.44), Inches(11.6), Inches(0.4),
     [[("A receipt-ledger agent — ", {"color": PAPER}),
       (TAGLINE, {"color": ACCENT, "bold": True})]], size=17)
text(s, M, Inches(1.92), Inches(11.8), Inches(0.4), LLM_LINE, size=11.5,
     color=RGBColor(0x94, 0xA3, 0xB8))

flow(s, 3.00, [("Photo", "any receipt", PAPER, LINE),
               ("Read", "local vision model", ACCENT_SOFT, ACCENT),
               ("Check", "10 arithmetic tests", PAPER, LINE),
               ("File or hold", "ledger, or human review", PAPER, LINE),
               ("Ask & record", "in plain English", PAPER, LINE)],
     h=1.00, ts=14, ss=10)

# Tech-stack marks. These are brand-coloured monogram tiles, sized and placed as
# real logo slots — drop a PNG on top of a tile in PowerPoint and it lines up.
# Brand colour is allowed to break the one-accent rule here: a logo strip reads
# as logos precisely because it is not our palette.
STACK = [("N", "Next.js", RGBColor(0x00, 0x00, 0x00)),
         ("F", "FastAPI", RGBColor(0x05, 0x99, 0x8B)),
         ("O", "Ollama", RGBColor(0x1F, 0x1F, 0x1F)),
         ("S", "SQLite", RGBColor(0x00, 0x36, 0xB0)),
         ("M", "MLflow", RGBColor(0x02, 0x94, 0xE4)),
         ("D", "Docker", RGBColor(0x1D, 0x63, 0xED)),
         ("P", "Pydantic", RGBColor(0xE9, 0x2A, 0x63))]
x = M
for glyph, name, brand in STACK:
    tile = rect(s, x, Inches(4.34), Inches(0.42), Inches(0.42), fill=brand, edge=None,
                radius=0.22)
    tf = tile.text_frame
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    tf.word_wrap = False
    pr = tf.paragraphs[0]; pr.alignment = PP_ALIGN.CENTER
    r = pr.add_run(); r.text = glyph
    r.font.name = FONT; r.font.size = Pt(17); r.font.bold = True; r.font.color.rgb = PAPER
    text(s, x + Inches(0.52), Inches(4.44), Inches(1.4), Inches(0.26), name, size=11,
         bold=True, color=BODY)
    x += Inches(0.52) + Inches(0.14 + 0.077 * len(name))

for i, (name, mods) in enumerate(TEAM):
    label(s, M + Inches(i * 3.10), Inches(5.10), Inches(2.95), Inches(0.72), name, mods,
          fill=SOFT, ts=12, ss=9.5)
text(s, M, Inches(6.10), Inches(12.0), Inches(0.3),
     "Introduction to Agentic AI (STAI100)  ·  Stratpoint × DLSU  ·  Week 14",
     size=11, color=MUTED)


# ============================================================ 2 · THE PROBLEM
s = slide("Use case", "Today", "300 paper receipts a month, one pair of hands")

flow(s, 1.86, [("300 receipts", "a month", PAPER, LINE),
               ("Typed by hand", "2 min each", PAPER, LINE),
               ("10 hours", "every month", ACCENT_SOFT, ACCENT),
               ("₱1,562", "of labour a month", ACCENT_SOFT, ACCENT)],
     h=1.05, ts=16, ss=11)

text(s, M, Inches(3.36), Inches(12.0), Inches(0.3),
     "AND NOBODY CHECKS THE MATH", size=10, bold=True, color=RED)
for i, (t, sub) in enumerate([("A line misread", "the total still looks fine"),
                              ("VAT added twice", "on a VAT-inclusive receipt"),
                              ("Entered twice", "one purchase, two rows")]):
    x = M + Inches(i * 4.06)
    rect(s, x, Inches(3.70), Inches(3.85), Inches(1.02), fill=T_RED, edge=RED, edge_w=1.3)
    mark(s, x + Inches(0.24), Inches(4.02), "bad", d=0.36)
    text(s, x + Inches(0.76), Inches(3.94), Inches(3.0), Inches(0.3), t, size=14,
         bold=True)
    text(s, x + Inches(0.76), Inches(4.26), Inches(3.0), Inches(0.3), sub, size=11,
         color=MUTED)

arrow(s, Inches(6.66), Inches(4.90), Inches(6.66), Inches(5.32), color=RED, w=2.4)
rect(s, Inches(3.4), Inches(5.34), Inches(6.5), Inches(0.76), fill=INK, edge=None)
text(s, Inches(3.4), Inches(5.54), Inches(6.5), Inches(0.35),
     "Found at filing time. Months later. If at all.", size=15, bold=True, color=PAPER,
     align=PP_ALIGN.CENTER)


# ============================================================ 3 · SCOPE
s = slide("Use case", "Scope")

rect(s, M, TOP, Inches(6.1), Inches(3.52), fill=T_GREEN, edge=GREEN, edge_w=1.5)
mark(s, M + Inches(0.26), TOP + Inches(0.18), "ok", d=0.42)
text(s, M + Inches(0.84), TOP + Inches(0.24), Inches(4.0), Inches(0.35), "IN",
     size=16, bold=True, color=GREEN)
cy = TOP + Inches(0.82)
for t in ["Photographed PH retail receipt", "Its own printed arithmetic",
          "Hold the bad, file the good", "A ledger you can ask, month after month",
          "Bank / card statement CSV"]:
    rect(s, M + Inches(0.30), cy, Inches(5.5), Inches(0.44), fill=PAPER, edge=GREEN)
    text(s, M + Inches(0.50), cy + Inches(0.10), Inches(5.1), Inches(0.3), t, size=13)
    cy += Inches(0.52)

rect(s, Inches(7.2), TOP, Inches(5.5), Inches(3.52), fill=T_RED, edge=RED, edge_w=1.5)
mark(s, Inches(7.46), TOP + Inches(0.18), "bad", d=0.42)
text(s, Inches(8.04), TOP + Inches(0.24), Inches(4.0), Inches(0.35), "OUT",
     size=16, bold=True, color=RED)
cy = TOP + Inches(0.82)
for t in ["Invoices, payslips, contracts", "Auto-correcting what the model read",
          "Multi-user accounts, cloud sync", "PDF statements, refunds", "Handwriting"]:
    rect(s, Inches(7.5), cy, Inches(4.9), Inches(0.44), fill=PAPER, edge=RED)
    text(s, Inches(7.7), cy + Inches(0.10), Inches(4.5), Inches(0.3), t, size=13)
    cy += Inches(0.52)

note(s, 5.50, "PoC pivot:", "one thing done well beats five done adequately.", h=0.72)


# ============================================================ 4 · VS CHATGPT
s = slide("Use case", "Why not just ask ChatGPT?")

text(s, M, TOP, Inches(6.0), Inches(0.3), "BROWSER LLM", size=11, bold=True, color=MUTED)
rect(s, M, TOP + Inches(0.30), Inches(5.9), Inches(1.55), fill=T_GREY, edge=GREY)
flow(s, 2.10, [("Upload", None, PAPER, GREY), ("Read", None, PAPER, GREY),
               ("Answer", None, PAPER, GREY)],
     x0=M + Inches(0.25), w=Inches(5.4), h=0.60, gap=0.16, ts=12)
text(s, M + Inches(0.25), Inches(2.86), Inches(5.4), Inches(0.3),
     "then it forgets — nothing typed, nothing stored", size=11, color=MUTED)

text(s, Inches(7.0), TOP, Inches(6.0), Inches(0.3), "SNAG", size=11, bold=True,
     color=ACCENT)
rect(s, Inches(7.0), TOP + Inches(0.30), Inches(5.7), Inches(1.55), fill=ACCENT_SOFT,
     edge=ACCENT, edge_w=1.2)
flow(s, 2.10, [("Read", None, PAPER, ACCENT), ("Check", None, PAPER, ACCENT),
               ("Re-read", None, PAPER, ACCENT), ("Store", None, PAPER, ACCENT)],
     x0=Inches(7.25), w=Inches(5.2), h=0.60, gap=0.12, ts=12, arrow_color=ACCENT)
text(s, Inches(7.25), Inches(2.86), Inches(5.2), Inches(0.3),
     "and every receipt stays, typed, forever", size=11, color=MUTED)

text(s, M, Inches(3.52), Inches(12.0), Inches(0.3),
     "THREE THINGS A CHAT WINDOW CANNOT DO", size=10, bold=True, color=RED)
for i, t in enumerate(["Re-photograph the paper", "Keep a typed ledger",
                       "Stay on your machine"]):
    x = M + Inches(i * 4.06)
    rect(s, x, Inches(3.90), Inches(3.85), Inches(0.86), fill=PAPER, edge=BAD, edge_w=1.2)
    text(s, x, Inches(4.20), Inches(3.85), Inches(0.3), t, size=14, bold=True,
         align=PP_ALIGN.CENTER)

note(s, 5.28, "Our test:", "if a browser LLM can do it in one sitting, it is not our pitch.",
     h=0.72, keep=True)


# ============================================================ 5 · 10× RULE
s = slide("Use case", "The 10× rule", "Our mentor's bar: you need two of the three")

for i, (t, sub, color, fill, kind) in enumerate(
        [("CHEAPER", "₱1,562 → ₱64\nper month", GREEN, T_GREEN, "ok"),
         ("FASTER", "10 hours → 23 min\nper month", GREEN, T_GREEN, "ok"),
         ("BETTER", "unmeasured —\nnot claimed", RED, T_RED, "bad")]):
    cx = Inches(2.35 + i * 4.30)
    rect(s, cx - Inches(1.42), TOP + Inches(0.10), Inches(2.84), Inches(2.84),
         fill=fill, edge=color, edge_w=2.2, shape=MSO_SHAPE.OVAL)
    text(s, cx - Inches(1.3), TOP + Inches(0.80), Inches(2.6), Inches(0.4), t,
         size=20, bold=True, color=color, align=PP_ALIGN.CENTER)
    text(s, cx - Inches(1.3), TOP + Inches(1.34), Inches(2.6), Inches(0.7), sub,
         size=12.5, align=PP_ALIGN.CENTER, line=1.25)
    mark(s, cx - Inches(0.23), TOP + Inches(2.50), kind, d=0.46)

text(s, M, Inches(4.90), Inches(12.0), Inches(0.4), "2 of 3", size=24, bold=True,
     color=GREEN, align=PP_ALIGN.CENTER)
note(s, 5.55, "Why not \"better\":",
     "no labelled receipts means no accuracy figure — and we will not invent one.",
     h=0.72, tone=BAD, keep=True)


# ============================================================ 6 · UoM
s = slide("Use case", "The arithmetic", "Every input carries its unit")


def equation(sl, y, tag, tag_color, fill, edge, items):
    rect(sl, M, Inches(y), FULL, Inches(1.06), fill=fill, edge=edge, edge_w=1.3)
    text(sl, M + Inches(0.30), Inches(y + 0.03), Inches(4.0), Inches(0.25), tag,
         size=10, bold=True, color=tag_color)
    x = M + Inches(0.30)
    for val, unit in items:
        w = Inches(0.40 if unit is None else 0.95 + 0.05 * len(val))
        text(sl, x, Inches(y + 0.28), w, Inches(0.35), val, size=18 if unit else 15,
             bold=True, align=PP_ALIGN.CENTER, color=INK if unit else MUTED)
        if unit:
            text(sl, x, Inches(y + 0.66), w, Inches(0.3), unit, size=9.5, color=MUTED,
                 align=PP_ALIGN.CENTER)
        x += w + Inches(0.10)


equation(s, 1.60, "TODAY", MUTED, WASH, LINE, [
    ("300", "receipts / mo"), ("×", None), ("2.0", "min / receipt"), ("=", None),
    ("600", "min / mo"), ("=", None), ("10.0", "hours"), ("×", None),
    ("₱156.25", "/ hour"), ("=", None), ("₱1,562", "/ month")])
arrow(s, Inches(6.66), Inches(2.74), Inches(6.66), Inches(2.94), color=INK, w=2.4)
equation(s, 2.96, "WITH SNAG", ACCENT, ACCENT_SOFT, ACCENT, [
    ("300", "receipts / mo"), ("×", None), ("15.4%", "held for review"), ("×", None),
    ("0.5", "min / held"), ("=", None), ("23", "min / mo"), ("=", None),
    ("₱64", "/ month")])

for i, (v, cap, col) in enumerate([("9.6 h", "saved / month", INK),
                                   ("₱1,498", "saved / month", INK),
                                   ("₱17,982", "saved / year", ACCENT),
                                   ("26×", "less human time", ACCENT)]):
    bignum(s, M + Inches(i * 3.05), Inches(4.42), Inches(2.9), v, cap, color=col, vs=32)

note(s, 5.92, "Measured vs assumed:",
     "15.4% and 14.9 s/page come from our own traces. The other six inputs are declared assumptions.",
     fill=SOFT, edge=LINE, h=0.72)


# ============================================================ 7 · BUSINESS MODEL
s = slide("Use case", "Business model", "Flat per organisation — and where we lose")

picture(s, "chart_breakeven.png", M, TOP, Inches(7.5), Inches(4.00))

cy = TOP
for name, price, sub, color, fill in [
        ("Self-host", "₱0", "you bring the machine", ACCENT, ACCENT_SOFT),
        ("Appliance", "₱60,000 once", "₱1,667/mo over 36 mo", GREY, PAPER),
        ("Hosted", "₱1,500 / org / mo", "flat, not per seat", GREY, PAPER)]:
    rect(s, Inches(8.45), cy, Inches(4.25), Inches(1.15), fill=fill, edge=color,
         edge_w=1.4)
    text(s, Inches(8.68), cy + Inches(0.16), Inches(2.2), Inches(0.3), name, size=14,
         bold=True)
    text(s, Inches(10.5), cy + Inches(0.17), Inches(2.0), Inches(0.3), price, size=12,
         bold=True, color=ACCENT if color == ACCENT else MUTED, align=PP_ALIGN.RIGHT)
    text(s, Inches(8.68), cy + Inches(0.56), Inches(3.8), Inches(0.3), sub, size=11,
         color=MUTED)
    cy += Inches(1.32)

note(s, 5.92, "Read the red line against us:",
     "under ~334 receipts a month the box costs more than the bookkeeper it replaces.",
     h=0.72, tone=BAD, keep=True)


# ============================================================ 8 · RRL MATRIX
s = slide("RRL", "Review of related literature", "Two questions killed three of four")

ox, oy, ow, oh = Inches(2.7), TOP + Inches(0.18), Inches(7.5), Inches(3.95)
for qx, qy, fill, edge, ew in [(0, 0, T_RED, LINE, 1.0), (ow / 2, 0, T_RED, LINE, 1.0),
                               (0, oh / 2, T_RED, LINE, 1.0),
                               (ow / 2, oh / 2, T_GREEN, GREEN, 2.2)]:
    rect(s, ox + qx, oy + qy, ow / 2, oh / 2, fill=fill, edge=edge, edge_w=ew,
         shape=MSO_SHAPE.RECTANGLE)

text(s, ox, oy - Inches(0.34), ow / 2, Inches(0.3), "LEAVES THE MACHINE", size=10.5,
     bold=True, color=RED, align=PP_ALIGN.CENTER)
text(s, ox + ow / 2, oy - Inches(0.34), ow / 2, Inches(0.3), "STAYS LOCAL", size=10.5,
     bold=True, color=GREEN, align=PP_ALIGN.CENTER)
text(s, Inches(0.6), oy + Inches(0.75), Inches(1.95), Inches(0.8),
     "NEEDS\nLABELLED\nDATA", size=10.5, bold=True, color=RED, align=PP_ALIGN.RIGHT,
     line=1.2)
text(s, Inches(0.6), oy + Inches(2.75), Inches(1.95), Inches(0.5), "ZERO-SHOT",
     size=10.5, bold=True, color=GREEN, align=PP_ALIGN.RIGHT)

label(s, ox + Inches(0.30), oy + Inches(0.55), Inches(3.15), Inches(0.85),
      "Cloud Document AI", "Textract · Google · Azure", edge=RED, ts=12.5)
label(s, ox + ow / 2 + Inches(0.30), oy + Inches(0.55), Inches(3.15), Inches(0.85),
      "Layout transformers", "LayoutLMv3 · Donut", edge=RED, ts=12.5)
label(s, ox + Inches(0.30), oy + oh / 2 + Inches(0.55), Inches(3.15), Inches(0.85),
      "Classical OCR", "Tesseract · PaddleOCR", edge=RED, ts=12.5)
label(s, ox + ow / 2 + Inches(0.30), oy + oh / 2 + Inches(0.48), Inches(3.15),
      Inches(1.00), "Open vision-language models",
      "Qwen2.5-VL · Llama 3.2-V · Gemma 4", edge=GREEN, edge_w=2.2, ts=12.5)
for qx, qy in [(0.30, 1.52), (ow / Inches(1.0) / 2 + 0.30, 1.52), (0.30, 3.50)]:
    mark(s, ox + Inches(qx + 2.90), oy + Inches(qy - 0.62), "bad", d=0.34)
mark(s, ox + ow / 2 + Inches(3.20), oy + oh / 2 + Inches(0.72), "ok", d=0.40)

note(s, 5.92, "We had one unlabelled receipt.",
     "That decided it before accuracy ever came up.", h=0.72)


# ============================================================ 9 · MODELS
s = slide("RRL", "Three models, three jobs")

for i, (t, model, spec, color, fill) in enumerate(
        [("Vision", "gemma4:e4b", "~4B · ≈6 s per call", ACCENT, ACCENT_SOFT),
         ("Planner", "gemma4:12b", "12B · routes the tools", GREY, PAPER),
         ("Embedding", "nomic-embed-text", "137M · 768-dim vectors", GREY, PAPER)]):
    x = M + Inches(i * 4.06)
    rect(s, x, TOP, Inches(3.85), Inches(1.30), fill=fill, edge=color, edge_w=1.5)
    text(s, x + Inches(0.25), TOP + Inches(0.14), Inches(3.3), Inches(0.35), t,
         size=15, bold=True)
    text(s, x + Inches(0.25), TOP + Inches(0.54), Inches(3.3), Inches(0.3), model,
         size=13, bold=True, color=ACCENT if color == ACCENT else MUTED)
    text(s, x + Inches(0.25), TOP + Inches(0.86), Inches(3.3), Inches(0.3), spec,
         size=11, color=MUTED)

text(s, M, Inches(3.22), Inches(12.0), Inches(0.3),
     "THE VISION TRADE-OFF WE RECORDED RATHER THAN RESOLVED", size=10, bold=True,
     color=MUTED)
for i, (model, tag, tagfill, good, bad, edge) in enumerate([
        ("gemma4:e4b", "≈6 s", T_GREEN, "fast", "misses line items and the VAT block", ACCENT),
        ("gemma4:12b", "≈20 s", T_RED, "reads the VAT block exactly",
         "garbles descriptions and the OR number", RED)]):
    x = M + Inches(i * 6.2)
    rect(s, x, Inches(3.58), Inches(5.8), Inches(1.50), fill=PAPER, edge=edge, edge_w=1.5)
    text(s, x + Inches(0.25), Inches(3.72), Inches(2.6), Inches(0.3), model, size=13.5,
         bold=True)
    chip(s, x + Inches(4.55), Inches(3.70), tag, fill=tagfill, size=11)
    mark(s, x + Inches(0.25), Inches(4.14), "ok", d=0.28)
    text(s, x + Inches(0.62), Inches(4.15), Inches(5.0), Inches(0.3), good, size=12)
    mark(s, x + Inches(0.25), Inches(4.56), "bad", d=0.28)
    text(s, x + Inches(0.62), Inches(4.57), Inches(5.0), Inches(0.3), bad, size=12)

arrow(s, Inches(6.66), Inches(5.16), Inches(6.66), Inches(5.44), color=INK, w=2.4)
rect(s, Inches(2.4), Inches(5.46), Inches(8.5), Inches(0.74), fill=INK, edge=None)
text(s, Inches(2.4), Inches(5.66), Inches(8.5), Inches(0.35),
     "Neither is reliably accurate — so the audit catches what the fast one misses.",
     size=14, bold=True, color=PAPER, align=PP_ALIGN.CENTER)


# ============================================================ 10 · ARCHITECTURE
s = slide("Architecture", "System architecture")

for lab, top, h, fill in [("BROWSER", Inches(1.58), Inches(0.86), T_GREY),
                          ("SERVICES", Inches(2.54), Inches(1.70), SOFT),
                          ("MODELS & STORAGE", Inches(4.38), Inches(1.66), T_GREY)]:
    rect(s, M, top, FULL, h, fill=fill, edge=None, radius=0.03)
    text(s, M + Inches(0.10), top + Inches(0.06), Inches(3), Inches(0.25), lab, size=8,
         bold=True, color=MUTED)

for i, (t, sub) in enumerate([("Scanner", "drag · camera · PDF"),
                              ("Dashboard", "cashflow · budgets"),
                              ("Chat panel", "streams its thinking"),
                              ("Review table", "confidence badges")]):
    label(s, Inches(1.0 + i * 2.70), Inches(1.82), Inches(2.5), Inches(0.52), t, sub,
          accent=GREY, ts=12, ss=8.5)
chip(s, Inches(11.75), Inches(1.94), "Next.js", fill=PAPER, size=9)

for i, (t, sub, col) in enumerate([("Web server", "same-origin proxy", GREY),
                                   ("API server", "~70 endpoints", GREY),
                                   ("Extraction", "guardrails · audit", ACCENT),
                                   ("Agent runtime", "ReAct · 10 tools", ACCENT),
                                   ("Finance", "balances", GREY)]):
    label(s, Inches(1.0 + i * 2.42), Inches(2.80), Inches(2.25), Inches(0.60), t, sub,
          accent=col, ts=12, ss=8.5)
for i, (t, sub) in enumerate([("Reconciler", "no model"), ("Index builder", "embeds"),
                              ("Query planner", "text-to-SQL"),
                              ("Tracer", "one run per call")]):
    label(s, Inches(1.0 + i * 2.90), Inches(3.56), Inches(2.70), Inches(0.52), t, sub,
          fill=SOFT, accent=MUTED, ts=11.5, ss=8.5)

store(s, Inches(1.0), Inches(4.66), Inches(2.15), Inches(1.26), "Ledger",
      "18 tables · persists")
store(s, Inches(3.4), Inches(4.66), Inches(1.85), Inches(1.26), "Vectors", "embeddings")
rect(s, Inches(5.6), Inches(4.66), Inches(5.05), Inches(1.26), fill=T_AMBER, edge=ACCENT,
     edge_w=1.3)
text(s, Inches(5.78), Inches(4.74), Inches(4.7), Inches(0.25), "LOCAL INFERENCE SERVER",
     size=8.5, bold=True, color=ACCENT)
for i, (n, tag) in enumerate([("Vision", "gemma4:e4b"), ("Planner", "gemma4:12b"),
                              ("Embed", "nomic-embed-text")]):
    label(s, Inches(5.75 + i * 1.60), Inches(5.02), Inches(1.50), Inches(0.76), n, tag,
          edge=ACCENT, ts=10.5, ss=8)
store(s, Inches(10.9), Inches(4.66), Inches(1.8), Inches(1.26), "Traces", "every call")

for x in (2.25, 4.95, 7.65, 10.35):
    arrow(s, Inches(x), Inches(2.38), Inches(x), Inches(2.78), color=GREY, w=1.4)
for x, lab, col in [(2.07, "persist", VIOLET), (4.32, "index", VIOLET),
                    (8.12, "infer", ACCENT), (11.80, "trace", VIOLET)]:
    arrow(s, Inches(x), Inches(4.10), Inches(x), Inches(4.62), color=col, w=1.8)
    text(s, Inches(x + 0.08), Inches(4.20), Inches(0.9), Inches(0.2), lab, size=8,
         bold=True, color=col)

note(s, 6.10, "One command brings up four containers:",
     "web · API · traces · inference.", h=0.62, keep=True)


# ============================================================ 11 · DATA FLOW
s = slide("Architecture", "One receipt, ten stages", "Strictly in order")

for i, (num, t, fill, edge) in enumerate(
        [("1", "Guardrail", PAPER, LINE), ("2", "Normalise", PAPER, LINE),
         ("3", "Read", ACCENT_SOFT, ACCENT), ("4", "Clean up", PAPER, LINE),
         ("5", "Recover", ACCENT_SOFT, ACCENT), ("6", "Re-read", ACCENT_SOFT, ACCENT),
         ("7", "Validate", PAPER, LINE), ("8", "Audit", PAPER, LINE),
         ("9", "Hold?", PAPER, LINE), ("10", "Save", PAPER, LINE)]):
    col, row = i % 5, i // 5
    x = M + Inches(col * 2.45)
    y = TOP + Inches(row * 1.12)
    rect(s, x, y, Inches(2.25), Inches(0.84), fill=fill, edge=edge, edge_w=1.3)
    text(s, x + Inches(0.14), y + Inches(0.08), Inches(0.4), Inches(0.3), num, size=12,
         bold=True, color=ACCENT if edge == ACCENT else FAINT)
    text(s, x, y + Inches(0.34), Inches(2.25), Inches(0.35), t, size=14, bold=True,
         align=PP_ALIGN.CENTER)
    if col < 4:
        arrow(s, x + Inches(2.27), y + Inches(0.42), x + Inches(2.42), y + Inches(0.42))
text(s, M, TOP + Inches(0.92), Inches(4.0), Inches(0.2),
     [[("…continues below", {"italic": True})]], size=9, color=MUTED)

text(s, M, Inches(3.94), Inches(12.0), Inches(0.3),
     "STAGE 4 — SIX DETERMINISTIC PASSES, IN THIS ORDER", size=10, bold=True, color=MUTED)
x = M
chain = ["Parse", "Clean names", "Remap tax lines", "De-duplicate", "Fix payments",
         "Coerce numbers"]
for i, t in enumerate(chain):
    rect(s, x, Inches(4.28), Inches(1.85), Inches(0.50), fill=PAPER, edge=LINE)
    text(s, x, Inches(4.40), Inches(1.85), Inches(0.3), t, size=11.5, bold=True,
         color=BODY, align=PP_ALIGN.CENTER)
    if i < len(chain) - 1:
        arrow(s, x + Inches(1.87), Inches(4.53), x + Inches(2.01), Inches(4.53))
    x += Inches(2.03)

rect(s, M, Inches(5.10), FULL, Inches(1.10), fill=INK, edge=None)
text(s, M, Inches(5.28), FULL, Inches(0.4),
     "Transcribe, then repair — never compute.", size=18, bold=True, color=ACCENT,
     align=PP_ALIGN.CENTER)
text(s, M, Inches(5.76), FULL, Inches(0.3),
     "Only stage 6 may overwrite a figure, and only if the receipt's own arithmetic improves.",
     size=12, color=RGBColor(0x94, 0xA3, 0xB8), align=PP_ALIGN.CENTER)


# ============================================================ 12 · PARALLEL
s = slide("Architecture", "Parallel or sequential?", "Asked at the midterm — here is the timeline")

text(s, M, TOP, Inches(6.0), Inches(0.3), "PAGES — THREE AT A TIME", size=10, bold=True,
     color=ACCENT)
lane_x = Inches(2.1)
for i in range(6):
    y = TOP + Inches(0.34 + i * 0.30)
    text(s, M, y + Inches(0.02), Inches(1.3), Inches(0.25), f"page {i + 1}", size=10,
         color=MUTED)
    rect(s, lane_x + Inches((i // 3) * 3.0), y, Inches(2.85), Inches(0.24),
         fill=ACCENT_SOFT, edge=ACCENT, radius=0.4)
line(s, lane_x + Inches(3.0), TOP + Inches(0.28), lane_x + Inches(3.0),
     TOP + Inches(2.16), color=GREY, w=1.0)
text(s, lane_x + Inches(3.1), TOP + Inches(2.18), Inches(3.4), Inches(0.25),
     "worker pool refills", size=9, color=MUTED)

text(s, M, Inches(3.90), Inches(12.0), Inches(0.3),
     "EVERYTHING ELSE — ONE AFTER THE OTHER", size=10, bold=True, color=MUTED)
for i, (t, sub) in enumerate([("10 stages", "each eats the last one's output"),
                              ("10 checks", "all run, none short-circuits"),
                              ("2 re-reads", "the 2nd is chosen by the 1st"),
                              ("1 tool per step", "that is what ReAct is")]):
    x = M + Inches(i * 3.05)
    rect(s, x, Inches(4.24), Inches(2.85), Inches(0.86), fill=PAPER, edge=LINE)
    text(s, x, Inches(4.36), Inches(2.85), Inches(0.3), t, size=14, bold=True,
         align=PP_ALIGN.CENTER)
    text(s, x + Inches(0.15), Inches(4.70), Inches(2.55), Inches(0.35), sub, size=10,
         color=MUTED, align=PP_ALIGN.CENTER)
    if i < 3:
        arrow(s, x + Inches(2.87), Inches(4.67), x + Inches(3.01), Inches(4.67))

text(s, M, Inches(5.50), FULL, Inches(0.3),
     [[("Tracing", {"bold": True, "color": INK}),
       (" runs on the calling thread — not parallel.      ", {"color": MUTED}),
       ("Embedding", {"bold": True, "color": INK}),
       (" is deferred to the next search.", {"color": MUTED})]], size=13)

note(s, 6.20, "One bad page never stops the batch.",
     "It is recorded as an error; the other thirty-nine still persist.",
     fill=SOFT, edge=LINE, h=0.56)


# ============================================================ 13 · CV LOOP
s = slide("Architecture", "Component 14 — the CV model")

flow(s, 1.58, [("Image", None, PAPER, LINE),
               ("Vision model", None, ACCENT_SOFT, ACCENT),
               ("Typed record", None, PAPER, LINE),
               ("Confidence", "from token probabilities", PAPER, LINE)],
     h=0.74, ts=13, ss=9)

cx, cy, rx, ry = Inches(6.66), Inches(4.45), Inches(2.90), Inches(1.15)
steps = [("Audit fails", ACCENT), ("Pick the band", ACCENT), ("Crop + enlarge", ACCENT),
         ("Ask again", ACCENT), ("Keep only if better", ACCENT)]
pts = [(cx + rx * math.cos(-math.pi / 2 + i * 2 * math.pi / 5),
        cy + ry * math.sin(-math.pi / 2 + i * 2 * math.pi / 5)) for i in range(5)]
for i in range(5):
    x1, y1 = pts[i]
    x2, y2 = pts[(i + 1) % 5]
    dx, dy = x2 - x1, y2 - y1
    d = math.hypot(dx, dy)
    ux, uy = dx / d, dy / d
    arrow(s, x1 + ux * Inches(1.15), y1 + uy * Inches(0.45),
          x2 - ux * Inches(1.15), y2 - uy * Inches(0.45),
          color=ACCENT, w=1.8, size=0.14)
for (px, py), (t, col) in zip(pts, steps):
    bw, bh = Inches(2.25), Inches(0.60)
    label(s, px - bw / 2, py - bh / 2, bw, bh, t, None, edge=col, edge_w=1.6, ts=12.5)
text(s, cx - Inches(1.5), cy - Inches(0.14), Inches(3.0), Inches(0.4),
     "THE RE-READ LOOP", size=13, bold=True, color=ACCENT, align=PP_ALIGN.CENTER)

text(s, M, Inches(2.55), Inches(5.6), Inches(0.3),
     [[("Why a crop:  ", {"bold": True, "color": INK}),
       ("900 px → 1,600 px across the same band", {"color": MUTED})]], size=12)
text(s, Inches(7.4), Inches(2.55), Inches(5.6), Inches(0.3),
     [[("Why the score is real:  ", {"bold": True, "color": INK}),
       ("it is the token probabilities", {"color": MUTED})]], size=12)

note(s, 6.10, "Not decorative:",
     "the audit, the review gate, the ledger and every answer come from what it read.",
     h=0.62, keep=True)


# ============================================================ 14 · COMPONENTS
s = slide("Components", "13 of 14 components", "Spec asks for 8. Owner initials in each tile.")

# Neutral tiles; the owner is named in the corner. Only the two that carry a
# claim are coloured: #14 is the mandatory one, #11 is the one we do not claim.
owners = {"C": (LINE, PAPER), "F": (LINE, PAPER), "N": (LINE, PAPER),
          "A": (LINE, PAPER), "-": (LINE, WASH), "*": (ACCENT, ACCENT_SOFT)}
initials = {"C": "CA", "F": "FS", "N": "NA", "A": "AG", "-": "—", "*": "ALL"}
tiles = [("1", "Prompt\nengineering", "C"), ("2", "Disambiguation", "F"),
         ("3", "RAG", "F"), ("4", "Memory", "F"), ("5", "Guardrails", "C"),
         ("6", "Chat UI", "N"), ("7", "API endpoint", "N"), ("8", "LLMOps", "A"),
         ("9", "ReAct / tools", "A"), ("10", "SQL + critique", "A"),
         ("11", "Multi-agent", "-"), ("12", "Advanced RAG", "F"),
         ("13", "Evals", "A"), ("14", "CV / DS  ★", "*")]
for i, (num, name, who) in enumerate(tiles):
    col, row = i % 7, i // 7
    x = M + Inches(col * 1.74)
    y = TOP + Inches(row * 1.26)
    color, fill = owners[who]
    dim = who == "-"
    rect(s, x, y, Inches(1.60), Inches(1.16), fill=fill, edge=color,
         edge_w=1.6 if who == "*" else 1.0)
    text(s, x, y + Inches(0.09), Inches(1.60), Inches(0.35), num, size=17, bold=True,
         color=FAINT if dim else (ACCENT if who == "*" else INK), align=PP_ALIGN.CENTER)
    text(s, x + Inches(0.06), y + Inches(0.48), Inches(1.48), Inches(0.5), name,
         size=10, bold=(who == "*"), align=PP_ALIGN.CENTER, line=1.15,
         color=FAINT if dim else BODY)
    text(s, x, y + Inches(0.90), Inches(1.60), Inches(0.22),
         "not claimed" if dim else initials[who], size=8.5, bold=True,
         color=BAD if dim else FAINT, align=PP_ALIGN.CENTER)

x = M
for who, name in [("C", "CA — Clarence"), ("F", "FS — Fraser"), ("N", "NA — Nathaniel"),
                  ("A", "AG — Aaron"), ("*", "ALL — CV/DS ★")]:
    x = chip(s, x, Inches(4.44), name, fill=owners[who][1] if who == "*" else WASH,
             color=ACCENT if who == "*" else BODY, size=11, h=0.34)

note(s, 5.18, "Why #11 is grey:",
     "one planner over ten tools is not several collaborating agents. We do not claim it.",
     h=0.62, tone=BAD, keep=True)
note(s, 6.00, "Component 14 is mandatory —",
     "the vision model as a callable tool, and the spine of everything else.", h=0.62)


# ============================================================ 15 · PROMPTS
s = slide("Components", "Prompt engineering", "Every rule is a bug we already had")

# The reviewer asked for the prompt itself, with the clause under discussion
# highlighted — so the real text is on the slide and the highlight is a shape
# behind it, not a colour change in the run.
rect(s, M, TOP, Inches(7.5), Inches(3.98), fill=WASH, edge=LINE)
text(s, M + Inches(0.24), TOP + Inches(0.14), Inches(4.0), Inches(0.25),
     "EXTRACTION PROMPT — 16 RULES, 3 OF THEM", size=9, bold=True, color=MUTED)

PROMPT_LINES = [
    ("7b.  NUMBERS INSIDE A PRODUCT NAME ARE PART OF THE NAME —", None),
    ("     NEVER A PRICE, NEVER A QUANTITY.", "hi"),
    ('     "Mineral Water 500ml   25.00"  ->  amount 25.00', None),
    ('        (NOT amount 500, NOT qty 500)', None),
    ("", None),
    ("10b. A tax breakdown does NOT get added to anything.", None),
    ("     VATable 486.61 / 12% VAT 58.39 is a BREAKDOWN of the", None),
    ("     545.00 already charged — not a tax to add on top.", "hi"),
    ("", None),
    ("14b. items_printed_count is how many product lines you", None),
    ("     counted printed in the item block during PASS 1.", None),
    ("     Never adjust it to match how many rows you produced.", "hi"),
]
cy = TOP + Inches(0.46)
for prompt_line, flag in PROMPT_LINES:   # not `line` — that is a drawing primitive
    if flag == "hi":
        rect(s, M + Inches(0.20), cy - Inches(0.02), Inches(6.55), Inches(0.25),
             fill=ACCENT_SOFT, edge=None, radius=0.2)
    text(s, M + Inches(0.24), cy, Inches(6.9), Inches(0.24), prompt_line, size=10.5,
         font=MONO, color=INK if flag else BODY)
    cy += Inches(0.28)

text(s, Inches(8.5), TOP + Inches(0.02), Inches(4.2), Inches(0.25),
     "EACH RULE IS A BUG WE ALREADY HAD", size=9, bold=True, color=MUTED)
y = TOP + Inches(0.36)
for tag, before, after in [("7b", "amount = 500", "amount = 25.00"),
                           ("10b", "total = 603.39", "total = 545.00"),
                           ("14b", "12 rows, filed", "12 of 30 → held")]:
    rect(s, Inches(8.5), y, Inches(4.2), Inches(1.14), fill=PAPER, edge=LINE)
    text(s, Inches(8.70), y + Inches(0.12), Inches(1.0), Inches(0.25), "RULE " + tag,
         size=9, bold=True, color=ACCENT)
    text(s, Inches(8.70), y + Inches(0.40), Inches(3.8), Inches(0.28), before,
         size=13, bold=True, color=BAD)
    arrow(s, Inches(8.82), y + Inches(0.74), Inches(9.20), y + Inches(0.74),
          color=INK, w=1.8)
    text(s, Inches(9.36), y + Inches(0.64), Inches(3.2), Inches(0.28), after,
         size=13, bold=True, color=GOOD)
    y += Inches(1.24)

x = M
for t in ["3 read passes", "16 numbered rules", "self-report clause", "fixed JSON schema",
          "per-image fingerprint"]:
    x = chip(s, x, Inches(5.78), t, size=11, h=0.34)


# ============================================================ 16 · GUARDRAILS
s = slide("Components", "Guardrails", "Seven gates. Each drops one kind of failure.")

gates = [("File check", "wrong type\n> 25 MB", GREY),
         ("Schema check", "malformed\nreply", GREY),
         ("SQL filter", "not a\nSELECT", GREY),
         ("Scope lock", "reading the\nwhole ledger", GREY),
         ("Sanitiser", "injection via a\nvendor name", GREY),
         ("Grounding", "a figure no\ntool returned", GREY),
         ("Write guards", "wrong account\ndouble entry", GREY)]
gw = (FULL - Inches(0.28) * 6) / 7
text(s, M, TOP - Inches(0.02), Inches(4.0), Inches(0.3), "REQUEST", size=11, bold=True,
     color=MUTED)
text(s, W - M - Inches(4.0), TOP - Inches(0.02), Inches(4.0), Inches(0.3), "LEDGER",
     size=11, bold=True, color=GREEN, align=PP_ALIGN.RIGHT)
for i, (t, drops, col) in enumerate(gates):
    x = M + (gw + Inches(0.28)) * i
    rect(s, x, TOP + Inches(0.30), gw, Inches(1.20), fill=PAPER, edge=col, edge_w=1.2)
    text(s, x, TOP + Inches(0.55), gw, Inches(0.6), t, size=12, bold=True,
         align=PP_ALIGN.CENTER, line=1.15)
    if i < 6:
        arrow(s, x + gw + Inches(0.02), TOP + Inches(0.90),
              x + gw + Inches(0.26), TOP + Inches(0.90), color=GREY, w=1.5)
    arrow(s, x + gw / 2, TOP + Inches(1.54), x + gw / 2, TOP + Inches(1.92),
          color=RED, w=1.6)
    text(s, x - Inches(0.12), TOP + Inches(1.98), gw + Inches(0.24), Inches(0.6),
         drops, size=9.5, color=RED, align=PP_ALIGN.CENTER, line=1.2)


rect(s, M, Inches(4.90), FULL, Inches(1.30), fill=T_GREEN, edge=GREEN, edge_w=1.6)
bignum(s, M + Inches(0.3), Inches(5.06), Inches(2.4), "0", "ungrounded numbers",
       color=GREEN, vs=36, cs=11)
text(s, Inches(3.9), Inches(5.32), Inches(8.6), Inches(0.55),
     "across 64 traced agent runs — every figure the agent stated appeared in a tool "
     "observation first", size=14, line=1.25)


# ============================================================ 17 · SQL + RAG
s = slide("Components", "Two ways to answer", "Numbers go left. Content goes right.")

text(s, M, TOP, Inches(6.0), Inches(0.3), "SQL AGENT  ·  \"how much did I spend?\"",
     size=11, bold=True, color=ACCENT)
cy = TOP + Inches(0.36)
for i, (t, sub) in enumerate([("Scope", "read-only copy"), ("Generate", "schema + examples"),
                              ("Validate", "SELECT only"), ("Run", "in-scope rows"),
                              ("Format", "the exact figure")]):
    rect(s, M, cy, Inches(5.85), Inches(0.58), fill=WASH, edge=LINE, edge_w=1.0)
    text(s, M + Inches(0.25), cy + Inches(0.14), Inches(2.2), Inches(0.3), t, size=13,
         bold=True)
    text(s, M + Inches(2.5), cy + Inches(0.16), Inches(3.1), Inches(0.3), sub, size=11,
         color=MUTED)
    if i < 4:
        arrow(s, M + Inches(2.9), cy + Inches(0.60), M + Inches(2.9), cy + Inches(0.74),
              color=GREY, w=1.3)
    cy += Inches(0.76)
line(s, M + Inches(5.90), TOP + Inches(2.28), M + Inches(6.20), TOP + Inches(2.28),
     color=RED, w=1.6)
line(s, M + Inches(6.20), TOP + Inches(2.28), M + Inches(6.20), TOP + Inches(0.94),
     color=RED, w=1.6)
arrow(s, M + Inches(6.20), TOP + Inches(0.94), M + Inches(5.92), TOP + Inches(0.94),
      color=RED, w=1.6)
text(s, M + Inches(6.28), TOP + Inches(1.50), Inches(0.9), Inches(0.5),
     "retry\n×1", size=9.5, bold=True, color=RED, line=1.2)

text(s, Inches(7.5), TOP, Inches(6.0), Inches(0.3), "RETRIEVAL  ·  \"what did I buy?\"",
     size=11, bold=True, color=ACCENT)
cy = TOP + Inches(0.36)
for i, (t, sub) in enumerate([("Compose", "one sentence per receipt"),
                              ("Embed", "\"document:\" prefix"),
                              ("Store", "768-dim vector"),
                              ("Match", "cosine, floor 0.5"),
                              ("Answer", "cited (Receipt #N)")]):
    fill, edge = WASH, LINE
    rect(s, Inches(7.5), cy, Inches(5.2), Inches(0.58), fill=fill, edge=edge, edge_w=1.0)
    text(s, Inches(7.75), cy + Inches(0.14), Inches(2.2), Inches(0.3), t, size=13,
         bold=True)
    text(s, Inches(9.8), cy + Inches(0.16), Inches(2.8), Inches(0.3), sub, size=11,
         color=MUTED)
    if i < 4:
        arrow(s, Inches(10.1), cy + Inches(0.60), Inches(10.1), cy + Inches(0.74),
              color=GREY, w=1.3)
    cy += Inches(0.76)

note(s, 6.02, "Scope is a different database, not a WHERE clause —",
     "a model that forgets the filter cannot leak, because the rows are not there.", h=0.72)


# ============================================================ 18 · REACT LOOP
s = slide("Components", "The ReAct loop")

label(s, M, TOP + Inches(0.28), Inches(2.1), Inches(0.70), "Question",
      "+ the last 10 turns", ts=13, ss=9.5)
label(s, Inches(3.1), TOP + Inches(0.28), Inches(2.3), Inches(0.60), "Ambiguous?", None,
      fill=WASH, ts=13)
arrow(s, Inches(2.85), TOP + Inches(0.58), Inches(3.06), TOP + Inches(0.58))
label(s, Inches(3.1), TOP + Inches(1.36), Inches(2.3), Inches(0.54), "Ask once",
      "nothing runs", fill=T_RED, edge=RED, ts=12.5, ss=9)
arrow(s, Inches(4.0), TOP + Inches(0.90), Inches(4.0), TOP + Inches(1.32), color=RED,
      w=1.8)
text(s, Inches(4.15), TOP + Inches(0.98), Inches(1.4), Inches(0.25), "yes", size=10,
     bold=True, color=RED)

rect(s, Inches(6.1), TOP, Inches(4.5), Inches(2.45), fill=SOFT, edge=ACCENT, edge_w=1.6)
text(s, Inches(6.30), TOP + Inches(0.08), Inches(4.0), Inches(0.25),
     "THE LOOP — max 4 steps", size=9, bold=True, color=ACCENT)
for i, (t, sub) in enumerate([("Thought", "what next?"), ("Action", "one tool"),
                              ("Observation", "sanitised result")]):
    label(s, Inches(6.30), TOP + Inches(0.38 + i * 0.64), Inches(4.1), Inches(0.52), t,
          sub, edge=ACCENT, ts=12.5, ss=9)
    if i < 2:
        arrow(s, Inches(8.35), TOP + Inches(0.92 + i * 0.64), Inches(8.35),
              TOP + Inches(1.00 + i * 0.64), color=ACCENT, w=1.6)
line(s, Inches(10.45), TOP + Inches(1.92), Inches(10.85), TOP + Inches(1.92),
     color=ACCENT, w=1.6)
line(s, Inches(10.85), TOP + Inches(1.92), Inches(10.85), TOP + Inches(0.64),
     color=ACCENT, w=1.6)
arrow(s, Inches(10.85), TOP + Inches(0.64), Inches(10.47), TOP + Inches(0.64),
      color=ACCENT, w=1.6)
text(s, Inches(10.95), TOP + Inches(1.14), Inches(1.7), Inches(0.4), "loop", size=10,
     bold=True, color=ACCENT)
arrow(s, Inches(5.45), TOP + Inches(0.58), Inches(6.06), TOP + Inches(0.86))

label(s, Inches(6.1), TOP + Inches(2.68), Inches(4.5), Inches(0.54), "Final Answer",
      "only what the tools returned", fill=T_GREEN, edge=GREEN, ts=13, ss=9)
arrow(s, Inches(8.35), TOP + Inches(2.48), Inches(8.35), TOP + Inches(2.64), color=GREEN,
      w=1.8)
label(s, Inches(11.0), TOP + Inches(2.68), Inches(1.7), Inches(0.54), "Forced final",
      "budget spent", fill=T_AMBER, edge=ACCENT, ts=11, ss=8.5)
arrow(s, Inches(10.65), TOP + Inches(2.95), Inches(10.96), TOP + Inches(2.95),
      color=ACCENT, w=1.6)

text(s, M, TOP + Inches(2.24), Inches(5.2), Inches(0.3), "GUARDS", size=10, bold=True,
     color=MUTED)
x = M
for t in ["4-step budget", "repeat cache", "loop steering", "grounding check"]:
    x = chip(s, x, TOP + Inches(2.56), t, fill=T_GREY, size=10.5, h=0.32)

rect(s, M, Inches(5.40), FULL, Inches(0.92), fill=INK, edge=None)
text(s, M, Inches(5.60), FULL, Inches(0.4),
     [[("Are you ", {"color": PAPER}), ("TELLING", {"color": ACCENT, "bold": True}),
       (" me, or ", {"color": PAPER}), ("ASKING", {"color": ACCENT, "bold": True}),
       (" me?    That is the planner's first decision.", {"color": PAPER})]],
     size=16, align=PP_ALIGN.CENTER)


# ============================================================ 19 · TOOLS
s = slide("Components", "Ten tools, one planner")

cx, cy = Inches(6.66), Inches(4.00)
rect(s, cx - Inches(1.15), cy - Inches(0.50), Inches(2.3), Inches(1.0), fill=INK,
     edge=None, radius=0.3)
text(s, cx - Inches(1.15), cy - Inches(0.30), Inches(2.3), Inches(0.35), "PLANNER",
     size=14, bold=True, color=ACCENT, align=PP_ALIGN.CENTER)
text(s, cx - Inches(1.15), cy + Inches(0.04), Inches(2.3), Inches(0.3), "gemma4:12b",
     size=10, color=RGBColor(0x94, 0xA3, 0xB8), align=PP_ALIGN.CENTER)

def tool_box(x, y, w, h, name, sig, out, fill, edge):
    """A tool with its typed contract — the reviewer asked for input and output
    data types, not just a one-word purpose."""
    rect(s, x, y, w, h, fill=fill, edge=edge, edge_w=1.0)
    text(s, x + Inches(0.16), y + Inches(0.10), w - Inches(0.3), Inches(0.26), name,
         size=12, bold=True, font=MONO)
    text(s, x + Inches(0.16), y + Inches(0.36), w - Inches(0.3), Inches(0.24),
         [[("in  ", {"color": FAINT}), (sig, {"color": BODY})]], size=8.5, font=MONO)
    text(s, x + Inches(0.16), y + Inches(0.57), w - Inches(0.3), Inches(0.24),
         [[("out ", {"color": FAINT}), (out, {"color": BODY})]], size=8.5, font=MONO)


for i, (t, sig, out) in enumerate([
        ("sql_ledger", "question: str", "str — one exact figure, or rows in prose"),
        ("search_receipts", "phrase: str, k: int = 4", "str — k receipt docs, each cited (#N)"),
        ("list_accounts", "—", "str — names, types, balances, categories"),
        ("list_plans", "filter: str", "str — goals, debts, budgets + progress")]):
    y = TOP + Inches(0.30 + i * 0.98)
    tool_box(M, y, Inches(3.9), Inches(0.86), t, sig, out, PAPER, GREY)
    arrow(s, M + Inches(3.95), y + Inches(0.43), cx - Inches(1.20), cy, color=GREY, w=1.3)

for i, (t, sig, out) in enumerate([
        ("add_expense", "amount: float, account: str,\n     category?: str, date?: str", "str — txn id + new balance"),
        ("add_income", "amount: float, account: str", "str — txn id + new balance"),
        ("transfer_money", "amount: float, from: str,\n     to: str, fee?: float", "str — both balances"),
        ("record_activity", "type: goal|debt|receivable,\n     target: str, amount: float", "str — plan progress"),
        ("create_plan", "type: str, name: str,\n     amount: float, due?: date", "str — plan id, no money moves"),
        ("update_plan", "type: str, target: str,\n     amount?: float, delete?: bool", "str — edit or deletion")]):
    y = TOP + Inches(0.00 + i * 0.78)
    rect(s, Inches(8.8), y, Inches(3.9), Inches(0.70), fill=ACCENT_SOFT, edge=ACCENT,
         edge_w=1.0)
    text(s, Inches(8.96), y + Inches(0.05), Inches(3.6), Inches(0.24), t, size=11.5,
         bold=True, font=MONO)
    text(s, Inches(8.96), y + Inches(0.27), Inches(3.6), Inches(0.28),
         [[("in  ", {"color": FAINT}), (sig.replace("\n     ", " "), {"color": BODY})]],
         size=8, font=MONO, line=1.1)
    text(s, Inches(8.96), y + Inches(0.48), Inches(3.6), Inches(0.22),
         [[("out ", {"color": FAINT}), (out, {"color": BODY})]], size=8, font=MONO)
    arrow(s, cx + Inches(1.20), cy, Inches(8.75), y + Inches(0.35), color=ACCENT, w=1.3)

text(s, M, TOP - Inches(0.04), Inches(3.4), Inches(0.3), "4 READ", size=11, bold=True,
     color=MUTED)
text(s, Inches(8.8), TOP - Inches(0.32), Inches(3.9), Inches(0.3), "6 WRITE", size=11,
     bold=True, color=ACCENT, align=PP_ALIGN.RIGHT)

note(s, 6.32, "One shared spine for every write:",
     "amount · account · category · date · duplicate. No tool carries its own guards.",
     h=0.56, keep=True)


# ============================================================ 20 · API
s = slide("Components", "The API")

# The reviewer liked the endpoint table and asked for input/output types on it,
# so this stays a table rather than becoming a diagram.
COLS = [(0.00, 2.55, "Endpoint"), (2.60, 3.55, "In  (type)"),
        (6.25, 5.05, "Out  (type)"), (11.35, 1.55, "Errors")]
rect(s, M, TOP, FULL, Inches(0.34), fill=INK, edge=None)
for dx, w, col_head in COLS:   # not `head` — that is a drawing primitive
    text(s, M + Inches(dx + 0.18), TOP + Inches(0.07), Inches(w), Inches(0.25), col_head,
         size=9.5, bold=True, color=PAPER)

API = [
    ("POST /extract", "file: image | pdf", "fields · line items · confidence · audit", "422 · 500"),
    ("POST /extract/batch", "files: list[image | pdf]", "list[result]  one per page, own error slot", "in band"),
    ("GET /receipts", "limit: int = 100", "list[receipt]", "—"),
    ("GET /receipts/{id}/items", "id: int", "list[line_item]", "404"),
    ("GET /analytics", "granularity: str, year?: int, month?: int",
     "cashflow · category totals · budgets · deltas", "—"),
    ("POST /ask", "question: str, receipt_ids?: list[int]",
     "answer: str, sql: str, rows: list", "422"),
    ("POST /search", "query: str, k: int = 4", "answer: str, sources: list[int]", "—"),
    ("POST /agent", "question: str, receipt_ids?: list[int]",
     "answer: str, steps: list[step], grounded: bool", "422 · 500"),
    ("POST /agent/stream", "question: str, receipt_ids?: list[int]",
     "SSE: start · token · action · observation · final", "in stream"),
]
y = TOP + Inches(0.40)
for path, sin, sout, err in API:
    text(s, M + Inches(0.18), y, Inches(2.5), Inches(0.26), path, size=11, bold=True,
         font=MONO)
    text(s, M + Inches(2.78), y + Inches(0.01), Inches(3.5), Inches(0.26), sin, size=9.5,
         font=MONO, color=BODY)
    text(s, M + Inches(6.43), y + Inches(0.01), Inches(5.0), Inches(0.26), sout, size=9.5,
         font=MONO, color=BODY)
    text(s, M + Inches(11.53), y + Inches(0.01), Inches(1.5), Inches(0.26), err, size=9.5,
         color=MUTED)
    y += Inches(0.38)
    rect(s, M, y - Inches(0.07), FULL, Inches(0.008), fill=LINE, edge=None,
         shape=MSO_SHAPE.RECTANGLE)

note(s, 5.98, "Typed in, typed out —",
     "every request and response is a schema-validated model, so ~70 endpoints behave the same way.",
     h=0.56, keep=True)


# ============================================================ 21 · LLMOPS
s = slide("Components", "Every model call is traced")

flow(s, 1.66, [("Model call", None, T_AMBER, ACCENT),
               ("Traced run", None, T_GREY, INK),
               ("Trace store", None, T_VIOLET, VIOLET)],
     x0=Inches(2.4), w=Inches(6.6), h=0.70, gap=0.5, ts=14)
bignum(s, Inches(9.6), Inches(1.99), Inches(3.1), f"{facts['total_runs']}",
       "runs recorded", vs=32, cs=11)

for i, (name, color, fill, items) in enumerate([
        ("EXTRACTION", MUTED, WASH,
         ["latency", "tokens in / out", "audit codes", "confidence"]),
        ("AGENT TURN", MUTED, WASH,
         ["latency", "steps taken", "tools used", "grounded?"]),
        ("SQL / SEARCH", MUTED, WASH,
         ["latency", "generated query", "retry?", "rows returned"])]):
    x = M + Inches(i * 4.06)
    rect(s, x, Inches(3.62), Inches(3.85), Inches(1.90), fill=fill, edge=color, edge_w=1.0)
    text(s, x + Inches(0.22), Inches(3.74), Inches(3.4), Inches(0.3), name, size=11,
         bold=True, color=color)
    for j, it in enumerate(items):
        rect(s, x + Inches(0.22), Inches(4.07 + j * 0.33), Inches(3.4), Inches(0.28),
             fill=PAPER, edge=None, radius=0.3)
        text(s, x + Inches(0.36), Inches(4.11 + j * 0.33), Inches(3.1), Inches(0.25),
             it, size=11)
    arrow(s, Inches(5.0), Inches(2.81), x + Inches(1.9), Inches(3.58), color=GREY, w=1.3)

note(s, 5.85, "This is where every number in the next section comes from.",
     "Not a sample — a count over every run.", fill=SOFT, edge=LINE, h=0.72)


# ============================================================ 22 · EVAL PYRAMID
s = slide("Findings", "How we evaluate", "Four layers. The top one is blocked.")

y = TOP + Inches(0.02)
for name, sub, tag, color, fill, w in [
        ("LAYER 3 — end to end", "receipt accuracy vs labelled truth", "NOT RUN",
         RED, T_RED, 5.4),
        ("LAYER 2 — trajectory", "the agent's path, live model", "7 cases",
         GREY, PAPER, 7.3),
        ("LAYER 1 — component", "guardrails · isolation · backup", "found 4 defects",
         GREY, PAPER, 9.3),
        ("LAYER 0 — unit", "deterministic functions", "831 tests", GREY, PAPER, 11.4)]:
    x = M + (FULL - Inches(w)) / 2
    rect(s, x, y, Inches(w), Inches(0.96), fill=fill, edge=color,
         edge_w=1.5 if color == BAD else 1.0)
    text(s, x + Inches(0.26), y + Inches(0.13), Inches(w - 2.5), Inches(0.3), name,
         size=13, bold=True, color=BAD if color == BAD else INK)
    text(s, x + Inches(0.26), y + Inches(0.45), Inches(w - 2.5), Inches(0.3), sub,
         size=11, color=MUTED)
    chip(s, x + Inches(w - 2.05), y + Inches(0.30), tag,
         fill=BAD_SOFT if color == BAD else WASH, color=BAD if color == BAD else MUTED,
         size=11, h=0.34)
    y += Inches(1.06)

note(s, 5.92, "The rule the harness enforces on itself:",
     "an unmeasured metric returns null — never 0%, never 100%.", h=0.72, keep=True)


# ============================================================ 23 · METRIC 1
s = slide("Findings", "Metric 1 — trajectory",
          f"{TRAJ['passed']} of {TRAJ['cases']} cases pass · eight checks each")

picture(s, "chart_trajectory.png", M, TOP, Inches(7.6), Inches(3.60))

for i, (v, cap, col) in enumerate([("7 / 8", "checks perfect", INK),
                                   ("1", "check failed", BAD)]):
    bignum(s, Inches(8.5) + Inches(i * 2.2), TOP, Inches(2.0), v, cap, color=col, vs=32)

rect(s, Inches(8.5), TOP + Inches(1.20), Inches(4.2), Inches(2.40), fill=T_RED, edge=RED,
     edge_w=1.5)
text(s, Inches(8.75), TOP + Inches(1.34), Inches(3.8), Inches(0.3),
     "THE ONE THAT FAILED", size=10, bold=True, color=RED)
text(s, Inches(8.75), TOP + Inches(1.72), Inches(3.8), Inches(1.4),
     "It was our scorer,\nnot the agent.", size=17, bold=True, line=1.3)
text(s, Inches(8.75), TOP + Inches(2.76), Inches(3.8), Inches(0.4),
     "Next slide.", size=13, color=MUTED)

note(s, 5.55, "Each run records its own gaps:",
     "\"working tree is dirty\" · \"model digests unset\" — a result that cannot be reproduced says so.",
     fill=SOFT, edge=LINE, h=0.72)


# ============================================================ 24 · TRACE
s = slide("Findings", "One full reasoning trace", "Case RCT-006")

y = TOP
for lab, body, fill, edge in [
        ("USER", "What is the capital of France?", T_TEAL, TEAL),
        ("THOUGHT", "Not this user's money. My scope says no.", T_AMBER, ACCENT),
        ("ACTION", "none — no tool was called", SOFT, GREY),
        ("FINAL", "\"I'm not sure how to answer that.\"", T_GREEN, GREEN)]:
    rect(s, M, y, Inches(7.6), Inches(0.72), fill=fill, edge=edge, edge_w=1.4)
    text(s, M + Inches(0.20), y + Inches(0.23), Inches(1.2), Inches(0.3), lab, size=10,
         bold=True, color=edge if edge != GREY else MUTED)
    text(s, M + Inches(1.50), y + Inches(0.20), Inches(5.9), Inches(0.35), body, size=13)
    if y < TOP + Inches(2.2):
        arrow(s, M + Inches(3.8), y + Inches(0.74), M + Inches(3.8), y + Inches(0.86),
              color=GREY, w=1.4)
    y += Inches(0.88)

text(s, M, Inches(5.20), Inches(7.6), Inches(0.3), "SCORECARD", size=10, bold=True,
     color=MUTED)
x = M
for lab in ["events ✓", "no error ✓", "budget ✓", "no repeat ✓", "ends ✓"]:
    x = chip(s, x, Inches(5.52), lab, fill=T_GREEN, color=GREEN, size=11, h=0.34)
chip(s, x, Inches(5.52), "observation ✗", fill=T_RED, color=RED, size=11, h=0.34)

rect(s, Inches(8.5), TOP, Inches(4.2), Inches(4.24), fill=INK, edge=None)
text(s, Inches(8.75), TOP + Inches(0.20), Inches(3.8), Inches(0.3), "VERDICT", size=10,
     bold=True, color=ACCENT)
cy = TOP + Inches(0.62)
for lab, val, col in [("Agent", "correct", GREEN), ("Scorer", "wrong", RED),
                      ("Code changed", "none", GREY), ("Failure deleted", "none", GREY)]:
    text(s, Inches(8.75), cy, Inches(2.1), Inches(0.3), lab, size=12.5, color=PAPER)
    text(s, Inches(10.5), cy, Inches(1.95), Inches(0.3), val, size=12.5, bold=True,
         color=col, align=PP_ALIGN.RIGHT)
    cy += Inches(0.50)
text(s, Inches(8.75), TOP + Inches(2.80), Inches(3.75), Inches(1.2),
     "A benchmark you edit\nwhen it embarrasses you\nmeasures nothing.", size=14,
     bold=True, color=ACCENT, line=1.35)


# ============================================================ 25 · METRIC 2
s = slide("Findings", "Metric 2 — latency", "The spread is the finding")

picture(s, "chart_latency.png", M, Inches(1.58), Inches(7.5), Inches(2.55))
picture(s, "chart_latency_spread.png", M, Inches(4.26), Inches(7.5), Inches(2.45))

for i, (v, cap, col) in enumerate([("~9 s", "SQL question", INK),
                                   ("~27 s", "agent turn", INK),
                                   ("10–200 s", "OCR page", ACCENT)]):
    bignum(s, Inches(8.5), Inches(1.66) + Inches(i * 1.18), Inches(4.2), v, cap,
           color=col, vs=30)

rect(s, Inches(8.5), Inches(5.28), Inches(4.2), Inches(1.44), fill=T_RED, edge=RED,
     edge_w=1.5)
text(s, Inches(8.75), Inches(5.42), Inches(3.8), Inches(0.3), "CAVEAT", size=10,
     bold=True, color=RED)
text(s, Inches(8.75), Inches(5.72), Inches(3.8), Inches(0.9),
     "Development traces, not a\nfrozen benchmark. Mixed\nmodels, mixed load.",
     size=12.5, line=1.3)


# ============================================================ 26 · METRIC 3
s = slide("Findings", "Metric 3 — behaviour", "Trustworthy, as opposed to fast")

for i, (v, lab, sub, col, fill) in enumerate([
        (f"{facts['ungrounded_total']:.0f}", "ungrounded numbers", "in 64 runs", GREEN, T_GREEN),
        (f"{100 * facts['grounded_rate']:.0f}%", "answers grounded", "in a tool result", GREEN, T_GREEN),
        (f"{facts['steps_mean']:.1f}", "steps per turn", "budget is 4", INK, PAPER),
        (f"{100 * facts['clarify_rate']:.0f}%", "asked first", "before acting", INK, PAPER)]):
    x = M + Inches(i * 3.05)
    rect(s, x, TOP, Inches(2.9), Inches(1.32), fill=fill, edge=col, edge_w=1.6)
    text(s, x, TOP + Inches(0.12), Inches(2.9), Inches(0.5), v, size=32, bold=True,
         color=col, align=PP_ALIGN.CENTER)
    text(s, x, TOP + Inches(0.74), Inches(2.9), Inches(0.3), lab, size=12.5, bold=True,
         align=PP_ALIGN.CENTER)
    text(s, x, TOP + Inches(1.00), Inches(2.9), Inches(0.3), sub, size=10, color=MUTED,
         align=PP_ALIGN.CENTER)

picture(s, "chart_tools.png", M, Inches(3.18), Inches(7.4), Inches(3.50))

rect(s, Inches(8.5), Inches(3.24), Inches(4.2), Inches(3.20), fill=SOFT, edge=LINE)
text(s, Inches(8.75), Inches(3.38), Inches(3.8), Inches(0.3), "ROUTING, NOT DEFAULTING",
     size=10, bold=True, color=ACCENT)
cy = Inches(3.80)
for q, tool, col in [("numbers", "sql_ledger", BODY), ("content", "search_receipts", BODY),
                     ("statements", "a write tool", ACCENT)]:
    text(s, Inches(8.75), cy, Inches(1.5), Inches(0.3), q, size=12.5, color=MUTED)
    arrow(s, Inches(10.1), cy + Inches(0.11), Inches(10.45), cy + Inches(0.11),
          color=col, w=1.5)
    text(s, Inches(10.6), cy, Inches(2.0), Inches(0.3), tool, size=12.5, bold=True,
         color=col)
    cy += Inches(0.54)



# ============================================================ 27 · METRIC 4
s = slide("Findings", "Metric 4 — engineering", "Measured before and after")

picture(s, "chart_engineering.png", M, TOP, Inches(12.0), Inches(2.46))

for i, (v, lab, why) in enumerate([
        ("2 → 1", "model calls per SQL question", "a removed round trip beats a faster loop"),
        ("227×", "faster per-receipt lookup", "one missing index on line items"),
        ("24×", "faster scoped retrieval", "scope pushed into the query")]):
    x = M + Inches(i * 4.06)
    rect(s, x, Inches(4.30), Inches(3.85), Inches(1.50), fill=PAPER, edge=LINE)
    text(s, x + Inches(0.25), Inches(4.42), Inches(3.4), Inches(0.5), v, size=28,
         bold=True, color=ACCENT)
    text(s, x + Inches(0.25), Inches(4.98), Inches(3.4), Inches(0.3), lab, size=12.5,
         bold=True)
    text(s, x + Inches(0.25), Inches(5.30), Inches(3.4), Inches(0.4), why, size=10.5,
         color=MUTED, line=1.2)

note(s, 6.02, "An intermediate version was slower —",
     "which is exactly why every one of these was measured rather than assumed.",
     fill=SOFT, edge=LINE, h=0.72)


# ============================================================ 28 · OUTPUTS OK
s = slide("Findings", "It works")

good = [("Pepper Lunch", "₱545.00", "VAT-inclusive:\nbreakdown ≠ addition"),
        ("Shake Shack", "₱475.00", "cash & change kept\nout of the total"),
        ("DBarn Manila", "₱216.00", "270 − 54 discount,\nthe discounted figure filed"),
        ("Wendy's", "₱835.00", "7 lines read in full,\ncard: no cash line"),
        ("SM Supermarket", "₱1,608.00", "printed 0.00 kept\nas a real value")]
bw = (FULL - Inches(0.24) * 4) / 5
for i, (name, total, why) in enumerate(good):
    x = M + (bw + Inches(0.24)) * i
    rect(s, x, TOP, bw, Inches(2.86), fill=PAPER, edge=GREEN, edge_w=1.6)
    rect(s, x, TOP, bw, Inches(0.06), fill=GREEN, edge=None, shape=MSO_SHAPE.RECTANGLE)
    mark(s, x + bw / 2 - Inches(0.19), TOP + Inches(0.22), "ok", d=0.38)
    text(s, x + Inches(0.10), TOP + Inches(0.74), bw - Inches(0.20), Inches(0.5), name,
         size=12.5, bold=True, align=PP_ALIGN.CENTER, line=1.15)
    text(s, x + Inches(0.10), TOP + Inches(1.26), bw - Inches(0.20), Inches(0.4), total,
         size=17, bold=True, color=GREEN, align=PP_ALIGN.CENTER)
    text(s, x + Inches(0.10), TOP + Inches(1.84), bw - Inches(0.20), Inches(0.9), why,
         size=10.5, color=MUTED, align=PP_ALIGN.CENTER, line=1.25)

note(s, 5.05, "\"Clean\" means internally consistent —",
     "all ten checks passed. It does not mean every character matches the paper.",
     h=0.72, keep=True)
note(s, 5.90, "Which is exactly why the next slide exists.", "", h=0.72)


# ============================================================ 29 · OUTPUTS BAD
s = slide("Findings", "It fails too", "Three caught. One not.")

cases = [("Ikkoryu Ramen", "items ≠ subtotal ≠ total", "HELD", GREEN, T_GREEN, "ok"),
         ("Handwritten slip", "confidence 0.41 vs 0.96", "HELD", GREEN, T_GREEN, "ok"),
         ("Same photo twice", "cash 101.00 vs cash 1.00", "FLAGGED", ACCENT, T_AMBER, "ok"),
         ("DBarn Manila", "VAT 540.00 = subtotal 540.00", "FILED", RED, T_RED, "bad")]
bw = (FULL - Inches(0.30) * 3) / 4
for i, (name, what, verdict, col, fill, kind) in enumerate(cases):
    x = M + (bw + Inches(0.30)) * i
    rect(s, x, TOP, bw, Inches(2.70), fill=fill, edge=col, edge_w=1.7)
    mark(s, x + bw / 2 - Inches(0.21), TOP + Inches(0.20), kind, d=0.42)
    text(s, x + Inches(0.12), TOP + Inches(0.76), bw - Inches(0.24), Inches(0.5), name,
         size=13, bold=True, align=PP_ALIGN.CENTER, line=1.15)
    text(s, x + Inches(0.12), TOP + Inches(1.28), bw - Inches(0.24), Inches(0.7), what,
         size=11, color=MUTED, align=PP_ALIGN.CENTER, line=1.25)
    chip(s, x + bw / 2 - Inches(0.62), TOP + Inches(2.08), verdict, fill=PAPER,
         color=col, size=11.5, h=0.36)

rect(s, M, Inches(4.90), FULL, Inches(1.32), fill=T_RED, edge=RED, edge_w=1.7)
text(s, M + Inches(0.25), Inches(5.04), Inches(4.0), Inches(0.3), "THE ONE WE MISSED",
     size=10, bold=True, color=RED)
text(s, M + Inches(0.25), Inches(5.36), Inches(11.5), Inches(0.75),
     "The VAT check is a warning, not an error — so nothing stopped it. A tax figure "
     "equal to the whole subtotal should be an error. That is a fix, not an excuse.",
     size=13.5, line=1.3)


# ============================================================ 30 · LIMITATIONS
s = slide("Findings", "What we cannot claim")

for i, (name, effect, fix) in enumerate([
        ("No labelled receipts", "accuracy is uncomputed", "label ~50 receipts"),
        ("No LLM-as-judge", "answer quality unscored", "a judge prompt"),
        ("7 trajectory cases", "one family only", "9 more families"),
        ("Carry-forward inert", "the toggle does nothing", "a product decision"),
        ("Posting drops currency", "USD looks like PHP", "a schema change"),
        ("\"Local\" is conditional", "our default uses a shared endpoint", "one env var")]):
    col, row = i % 3, i // 3
    x = M + Inches(col * 4.06)
    y = TOP + Inches(row * 1.84)
    rect(s, x, y, Inches(3.85), Inches(1.66), fill=PAPER, edge=RED, edge_w=1.5)
    rect(s, x, y, Inches(3.85), Inches(0.06), fill=RED, edge=None,
         shape=MSO_SHAPE.RECTANGLE)
    text(s, x + Inches(0.22), y + Inches(0.22), Inches(3.4), Inches(0.35), name,
         size=13.5, bold=True)
    text(s, x + Inches(0.22), y + Inches(0.60), Inches(3.4), Inches(0.35), effect,
         size=11.5, color=MUTED)
    arrow(s, x + Inches(0.30), y + Inches(1.10), x + Inches(0.62), y + Inches(1.10),
          color=GREEN, w=1.8)
    text(s, x + Inches(0.78), y + Inches(1.00), Inches(2.9), Inches(0.35), fix, size=12,
         bold=True, color=GREEN)

note(s, 5.60, "A limitation you disclose is a limitation.",
     "One a grader finds is a defect.", h=0.72, keep=True)


# ============================================================ 31 · RETRO
s = slide("Retrospective", "Retrospective")

y = TOP
for lab, body, col, fill in [
        ("EASIEST", "The deterministic half — ordinary code, ordinary tests", GREY, PAPER),
        ("MOST SURPRISING", "Two receipts came back identical — a prompt cache, not a misread",
         ACCENT, ACCENT_SOFT),
        ("HARDEST", "A full eval harness that still cannot report an accuracy figure",
         ACCENT, ACCENT_SOFT),
        ("DO DIFFERENTLY", "Label fifty receipts in week one", GREY, PAPER),
        ("NEXT TIME", "Pin models by digest; freeze one config before any result",
         GREY, PAPER)]:
    rect(s, M, y, FULL, Inches(0.92), fill=fill, edge=col, edge_w=1.5)
    text(s, M + Inches(0.25), y + Inches(0.29), Inches(2.9), Inches(0.35), lab, size=12,
         bold=True, color=ACCENT if col == ACCENT else MUTED)
    text(s, M + Inches(3.4), y + Inches(0.25), Inches(8.4), Inches(0.45), body, size=14,
         line=1.2)
    y += Inches(1.02)


# ============================================================ 32 · TEAM
s = slide("Retrospective", "Who built what")

for i, (name, owns) in enumerate(TEAM):
    x = M + Inches(i * 3.10)
    color, fill = GREY, PAPER
    rect(s, x, TOP, Inches(2.95), Inches(3.24), fill=fill, edge=color, edge_w=1.6)
    circ = rect(s, x + Inches(1.10), TOP + Inches(0.22), Inches(0.75), Inches(0.75),
                fill=INK, edge=None, radius=0.5)
    tf = circ.text_frame; tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.word_wrap = False
    p = tf.paragraphs[0]; p.alignment = PP_ALIGN.CENTER
    r = p.add_run(); r.text = name.split()[0][0] + name.split()[-1][0]
    r.font.name = FONT; r.font.size = Pt(22); r.font.bold = True; r.font.color.rgb = PAPER
    text(s, x + Inches(0.15), TOP + Inches(1.10), Inches(2.65), Inches(0.35), name,
         size=14, bold=True, align=PP_ALIGN.CENTER)
    for j, part in enumerate(owns.split(" · ")):
        rect(s, x + Inches(0.25), TOP + Inches(1.58 + j * 0.48), Inches(2.45),
             Inches(0.38), fill=WASH, edge=None)
        text(s, x + Inches(0.25), TOP + Inches(1.65 + j * 0.48), Inches(2.45),
             Inches(0.3), part, size=12, bold=True, align=PP_ALIGN.CENTER)

rect(s, M, Inches(5.16), FULL, Inches(1.00), fill=INK, edge=None)
text(s, M, Inches(5.34), FULL, Inches(0.35),
     "Component 14 — CV/DS integration ★ mandatory", size=15, bold=True, color=ACCENT,
     align=PP_ALIGN.CENTER)
text(s, M, Inches(5.74), FULL, Inches(0.3),
     "owned by all four:  the prompt · the confidence · the audit · the re-read loop",
     size=12, color=RGBColor(0x94, 0xA3, 0xB8), align=PP_ALIGN.CENTER)


# ============================================================ 33 · DEMO
s = slide("Demo", "Live demo")

steps = ["Scan a receipt", "Show a held one", "Ask for a number", "Ask for content",
         "Record by talking", "Try to break it", "Open the traces"]
bw = (FULL - Inches(0.18) * 6) / 7
for i, t in enumerate(steps):
    x = M + (bw + Inches(0.18)) * i
    rect(s, x, TOP + Inches(0.30), bw, Inches(1.60), fill=PAPER, edge=INK, edge_w=1.6)
    c = rect(s, x + bw / 2 - Inches(0.24), TOP + Inches(0.46), Inches(0.48), Inches(0.48),
             fill=INK, edge=None, radius=0.5)
    tf = c.text_frame; tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]; p.alignment = PP_ALIGN.CENTER
    r = p.add_run(); r.text = str(i + 1)
    r.font.name = FONT; r.font.size = Pt(15); r.font.bold = True; r.font.color.rgb = PAPER
    text(s, x + Inches(0.06), TOP + Inches(1.08), bw - Inches(0.12), Inches(0.7), t,
         size=12, bold=True, align=PP_ALIGN.CENTER, line=1.2)
    if i < 6:
        arrow(s, x + bw + Inches(0.02), TOP + Inches(1.10),
              x + bw + Inches(0.16), TOP + Inches(1.10), color=GREY, w=1.4)

rect(s, M, Inches(4.10), Inches(5.9), Inches(1.30), fill=T_AMBER, edge=ACCENT, edge_w=1.5)
text(s, M + Inches(0.25), Inches(4.24), Inches(5.4), Inches(0.3), "DISCLOSED UP FRONT",
     size=10, bold=True, color=ACCENT)
text(s, M + Inches(0.25), Inches(4.54), Inches(5.4), Inches(0.7),
     "Shared endpoint. If it is down we switch to a recording — and say so as we switch.",
     size=13, line=1.3)

rect(s, Inches(7.1), Inches(4.10), Inches(5.6), Inches(1.30), fill=INK, edge=None)
text(s, Inches(7.35), Inches(4.24), Inches(5.0), Inches(0.3), "WHERE TO LOOK", size=10,
     bold=True, color=ACCENT)
x = Inches(7.35)
for t in ["Dashboard", "API docs", "Trace UI"]:
    x = chip(s, x, Inches(4.62), t, fill=RGBColor(0x1E, 0x29, 0x3B), color=PAPER,
             size=11, h=0.34)
text(s, Inches(7.35), Inches(5.06), Inches(5.0), Inches(0.3),
     "Fallback recording on disk, same seven steps.", size=11,
     color=RGBColor(0x94, 0xA3, 0xB8))

note(s, 5.70, "The demo is the argument.", "Everything before this slide was setup.",
     h=0.72)


# ============================================================ 34 · CLOSE
s = slide("Demo", "Take away four things")

for i, (t, sub, col, fill) in enumerate([
        ("The CV model IS the product",
         "audit · gate · ledger · answers all derive from it", ACCENT, ACCENT_SOFT),
        ("Two of three tens, honestly",
         f"26× faster · ₱{U['php_saved_year']:,.0f}/yr · \"better\" not claimed",
         GREY, PAPER),
        ("The eval knows its own edge",
         "6/7 cases · 0 ungrounded · accuracy uncomputed", GREY, PAPER),
        ("We found our own failures",
         "and wrote each one down with its fix", GREY, PAPER)]):
    x = M + Inches((i % 2) * 6.2)
    y = TOP + Inches((i // 2) * 1.66)
    rect(s, x, y, Inches(5.8), Inches(1.42), fill=fill, edge=col, edge_w=1.7)
    text(s, x + Inches(0.28), y + Inches(0.26), Inches(5.2), Inches(0.4), t, size=17,
         bold=True)
    text(s, x + Inches(0.28), y + Inches(0.80), Inches(5.3), Inches(0.45), sub,
         size=12.5, color=MUTED, line=1.2)

rect(s, M, Inches(5.20), FULL, Inches(1.00), fill=INK, edge=None)
text(s, M, Inches(5.42), FULL, Inches(0.45),
     [[("Snag", {"bold": True, "size": 20, "color": PAPER}),
       (f"   —   {TAGLINE}", {"size": 16, "color": RGBColor(0x94, 0xA3, 0xB8)})]],
     align=PP_ALIGN.CENTER)
text(s, M, Inches(5.90), FULL, Inches(0.3), "Questions?", size=13, color=ACCENT,
     align=PP_ALIGN.CENTER)


prs.save(OUT)
print(f"Saved {OUT}  ({len(prs.slides._sldIdLst)} slides)")
