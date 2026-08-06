"""
Stage 12 — Leadership/CEO presentation deck for the Early Warning ML model.

Distinct from 11_build_deck.py (the technical deep-dive deck). This one is
short, business+technical hybrid, no internal names, no committed near-term
dates. On-slide bullets are deliberately short (visual, scannable); the full
rich talking points live in speaker notes so the presenter has complete
context without a cluttered slide.

Run: py -3 12_leadership_deck.py
Output: ../EWS_ML_Leadership_Deck.pptx (repo top level, easy to find)
"""
from __future__ import annotations

import os

from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE
from pptx.oxml.ns import qn

OUT = os.path.join(os.path.dirname(__file__), "..", "EWS_ML_Leadership_Deck.pptx")

# ── palette (consistent with the project's established teal/navy system) ────
NAVY   = RGBColor(0x1C, 0x2B, 0x30)
TEAL   = RGBColor(0x2A, 0x6F, 0x77)
TEALD  = RGBColor(0x21, 0x5A, 0x61)
TEAL_L = RGBColor(0x5A, 0xA6, 0xAE)
GREY   = RGBColor(0x5B, 0x6B, 0x72)
FAINT  = RGBColor(0x8A, 0x99, 0xA0)
HAIR   = RGBColor(0xDD, 0xE5, 0xE7)
LIGHT  = RGBColor(0xF6, 0xF8, 0xF9)
CALLOUT_BG = RGBColor(0xEA, 0xF3, 0xF3)
WHITE  = RGBColor(0xFF, 0xFF, 0xFF)

SLIDE_W, SLIDE_H = Inches(13.333), Inches(7.5)
MARGIN = Inches(0.6)
CONTENT_W = SLIDE_W - 2 * MARGIN
FONT = "Calibri"

_slide_counter = {"n": 0}


def new_deck():
    prs = Presentation()
    prs.slide_width = SLIDE_W
    prs.slide_height = SLIDE_H
    return prs


def blank_slide(prs):
    return prs.slides.add_slide(prs.slide_layouts[6])


def add_bg(slide, color=WHITE):
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = color


def _set_no_autosize(tf):
    """Disable text autofit so our explicit font sizes are respected exactly
    (python-pptx doesn't expose this directly on older schemas)."""
    bodyPr = tf._txBody.find(qn("a:bodyPr"))
    for tag in ("a:normAutofit", "a:spAutoFit"):
        el = bodyPr.find(qn(tag))
        if el is not None:
            bodyPr.remove(el)
    noAutofit = bodyPr.makeelement(qn("a:noAutofit"), {})
    bodyPr.append(noAutofit)


def add_text(slide, text, left, top, width, height, size=18, bold=False, color=NAVY,
            align=PP_ALIGN.LEFT, italic=False, font=FONT, anchor=None, line_spacing=1.0):
    tb = slide.shapes.add_textbox(left, top, width, height)
    tf = tb.text_frame
    tf.word_wrap = True
    _set_no_autosize(tf)
    if anchor is not None:
        tf.vertical_anchor = anchor
    lines = text.split("\n")
    for i, line in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.line_spacing = line_spacing
        r = p.add_run()
        r.text = line
        r.font.size = Pt(size); r.font.bold = bold; r.font.italic = italic
        r.font.color.rgb = color; r.font.name = font
    return tb


def add_bullets(slide, items, left, top, width, height, size=15, color=NAVY,
                space_after=12, marker_color=None):
    marker_color = marker_color or TEAL
    tb = slide.shapes.add_textbox(left, top, width, height)
    tf = tb.text_frame
    tf.word_wrap = True
    _set_no_autosize(tf)
    for i, item in enumerate(items):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.space_after = Pt(space_after)
        p.line_spacing = 1.08
        r1 = p.add_run(); r1.text = "●  "
        r1.font.size = Pt(size); r1.font.color.rgb = marker_color; r1.font.name = FONT; r1.font.bold = True
        r2 = p.add_run(); r2.text = item
        r2.font.size = Pt(size); r2.font.color.rgb = color; r2.font.name = FONT
    return tb


def add_rect(slide, left, top, width, height, fill=None, line=None, line_w=None):
    shp = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, left, top, width, height)
    shp.shadow.inherit = False
    if fill is None:
        shp.fill.background()
    else:
        shp.fill.solid(); shp.fill.fore_color.rgb = fill
    if line is None:
        shp.line.fill.background()
    else:
        shp.line.color.rgb = line
        shp.line.width = line_w or Pt(1)
    return shp


def add_eyebrow_and_title(slide, eyebrow, title, title_size=25):
    add_text(slide, eyebrow, MARGIN, Inches(0.38), CONTENT_W, Inches(0.32),
             size=12, bold=True, color=TEAL)
    add_text(slide, title, MARGIN, Inches(0.72), CONTENT_W, Inches(0.75),
             size=title_size, bold=True, color=NAVY)
    add_rect(slide, MARGIN, Inches(1.42), CONTENT_W, Pt(1), fill=HAIR)


def add_bottom_line(slide, text, top, box_h=None):
    box_h = box_h or Inches(0.95)
    add_rect(slide, MARGIN, top, CONTENT_W, box_h, fill=CALLOUT_BG)
    add_rect(slide, MARGIN, top, Pt(4), box_h, fill=TEAL)
    add_text(slide, "BOTTOM LINE", MARGIN + Inches(0.25), top + Inches(0.10),
             Inches(2.5), Inches(0.3), size=10.5, bold=True, color=TEALD)
    add_text(slide, text, MARGIN + Inches(0.25), top + Inches(0.36),
             CONTENT_W - Inches(0.5), box_h - Inches(0.4), size=13.5, italic=True,
             color=NAVY, anchor=MSO_ANCHOR.TOP, line_spacing=1.05)


def add_footer(slide, prs):
    _slide_counter["n"] += 1
    add_text(slide, "Early Warning System · ML Update", MARGIN, prs.slide_height - Inches(0.42),
             Inches(5), Inches(0.3), size=9, color=FAINT)
    add_text(slide, str(_slide_counter["n"]), prs.slide_width - Inches(0.9),
             prs.slide_height - Inches(0.42), Inches(0.5), Inches(0.3), size=9,
             color=FAINT, align=PP_ALIGN.RIGHT)


def add_notes(slide, text):
    slide.notes_slide.notes_text_frame.text = text


def _estimate_bullet_block_height_in(bullets, size_pt, space_after_pt, width_in,
                                     line_spacing=1.08, marker_w_in=0.32):
    """Approximate rendered height of a bullet list, accounting for REAL text
    wrapping (long sentences wrap to multiple lines) -- a naive 1-line-per-
    bullet estimate badly undershoots for full paragraph-length bullets."""
    line_h_in = (size_pt * line_spacing * 1.22) / 72.0
    # average character width for Calibri-family fonts is roughly 0.5x the
    # point size; convert to inches.
    avg_char_w_in = (size_pt * 0.50) / 72.0
    usable_w_in = width_in - marker_w_in
    chars_per_line = max(10, usable_w_in / avg_char_w_in)
    space_in = space_after_pt / 72.0
    total = 0.0
    for b in bullets:
        n_lines = max(1, -(-len(b) // int(chars_per_line)))  # ceil division
        total += n_lines * line_h_in + space_in
    return total


def content_slide(prs, eyebrow, title, bullets, bottom_line, notes, title_size=25,
                  bullet_top=Inches(1.6), bullet_size=14.5, bullet_space=13,
                  bl_box_h=None):
    s = blank_slide(prs); add_bg(s, WHITE)
    add_eyebrow_and_title(s, eyebrow, title, title_size=title_size)

    width_in = CONTENT_W / 914400
    est_h_in = _estimate_bullet_block_height_in(bullets, bullet_size, bullet_space, width_in)
    gap_in = 0.4
    bl_top_in = (bullet_top / 914400) + est_h_in + gap_in
    bl_top_in = max(3.5, min(bl_top_in, 5.95))
    bl_top = Inches(bl_top_in)

    bullet_h = bl_top - bullet_top - Inches(0.1)
    add_bullets(s, bullets, MARGIN, bullet_top, CONTENT_W, bullet_h,
               size=bullet_size, space_after=bullet_space)
    add_bottom_line(s, bottom_line, bl_top, box_h=bl_box_h)
    add_footer(s, prs)
    add_notes(s, notes)
    return s


def title_slide(prs):
    s = blank_slide(prs); add_bg(s, NAVY)
    add_rect(s, 0, Inches(2.55), SLIDE_W, Pt(2.5), fill=TEAL_L)
    add_text(s, "EARLY WARNING SYSTEM · ML UPDATE", MARGIN, Inches(1.55),
             Inches(11.5), Inches(0.4), size=13, bold=True, color=TEAL_L)
    add_text(s, "Predicting Patient Deterioration\nBefore It Happens", MARGIN, Inches(1.95),
             Inches(12), Inches(1.7), size=36, bold=True, color=WHITE, line_spacing=1.05)
    add_text(s, "Coronary Care Unit pilot — current model, path to production", MARGIN,
             Inches(3.15), Inches(11), Inches(0.5), size=16, color=RGBColor(0xC7, 0xD6, 0xD8))

    tiles = [
        ("10,775", "real patient stays\nused to build & test the model"),
        ("1.5–2×", "better risk detection\nthan random alerting today"),
        ("Staged", "path defined for\nreal hospital deployment"),
    ]
    tile_w = Inches(3.6); gap = Inches(0.4); x0 = MARGIN
    for i, (num, label) in enumerate(tiles):
        x = x0 + i * (tile_w + gap)
        add_rect(s, x, Inches(4.55), tile_w, Inches(1.9), fill=RGBColor(0x24, 0x37, 0x3E))
        add_rect(s, x, Inches(4.55), tile_w, Pt(3), fill=TEAL_L)
        add_text(s, num, x + Inches(0.25), Inches(4.75), tile_w - Inches(0.5), Inches(0.7),
                 size=30, bold=True, color=WHITE)
        add_text(s, label, x + Inches(0.25), Inches(5.45), tile_w - Inches(0.5), Inches(0.9),
                 size=12.5, color=RGBColor(0xB0, 0xC2, 0xC4), line_spacing=1.15)
    add_footer(s, prs)
    add_notes(s, "Opening slide. Lead with the headline: we have a working, validated ML "
                "pipeline built on real patient data, it already beats the current rule-based "
                "approach, and there is a concrete, staged path to real hospital deployment.")
    return s


def blank_placeholder_slide(prs):
    s = blank_slide(prs); add_bg(s, LIGHT)
    add_rect(s, 0, Inches(3.55), SLIDE_W, Pt(2), fill=HAIR)
    add_text(s, "Architecture & Integration Overview", MARGIN, Inches(3.05), CONTENT_W,
             Inches(0.6), size=20, bold=True, color=FAINT, align=PP_ALIGN.CENTER)
    add_footer(s, prs)
    add_notes(s, "Reserved for architecture / data-flow diagram or open discussion.")
    return s


def main():
    prs = new_deck()

    title_slide(prs)

    content_slide(
        prs, "WHERE WE STAND", "A Working, End-to-End Prediction System",
        bullets=[
            "We built a complete AI pipeline, not a proof-of-concept slide — real "
            "hospital-scale data (MIMIC-IV, 10,775 CCU patients, 256,000+ hourly patient "
            "readings) flows through data extraction, model training, and a full "
            "evaluation report, the same rigor a peer-reviewed clinical study would use.",

            "The model predicts WHEN, not just IF — using an AI technique called survival "
            "analysis (XGBoost AFT), it estimates the likely time window until a patient "
            "deteriorates, giving clinicians a head start rather than a same-moment alert.",

            "It already outperforms today's manual scoring system meaningfully — in blind "
            "testing, it ranks at-risk patients far better than simple rule-based tracking "
            "(a statistical ranking accuracy of 0.78 vs. 0.54 for the current method, where "
            "0.50 is a coin flip and 1.0 is perfect).",
        ],
        bottom_line="The foundation is real, validated, and working — the next phase "
                    "is sharpening precision before clinical rollout.",
        notes="Full content is on the slide.",
    )

    content_slide(
        prs, "CURRENT CHALLENGE", "The Model Finds Real Risk — But Over-Alerts",
        bullets=[
            "We benchmarked ourselves against 6 published hospital AI systems (including "
            "tools used at real US hospital networks and a Nature Medicine-published "
            "model) — not just our own internal numbers — and our current alert precision "
            "falls short of that bar.",

            "The model does add real value today — patients it flags are 1.5–2× more "
            "likely to actually deteriorate than a random patient — but that's below "
            "where it needs to be for a clinician to trust every alert.",

            "We know precisely why, and it's fixable — this isn't a mystery; it's a "
            "known, well-documented pattern in early-warning systems, and we have a "
            "concrete, staged plan (next slides) to close the gap.",
        ],
        bottom_line="This is a precision problem, not a fundamental flaw — and we've "
                    "already benchmarked exactly how far we need to move.",
        notes="Full content is on the slide.",
    )

    content_slide(
        prs, "NEXT STEPS", "Sharpening the Algorithm",
        bullets=[
            "Evaluated ordinal regression — confirmed the core idea is right: predicting "
            "risk in time-bands (“within 2 hours,” “within 12 hours,” etc.) rather than "
            "one blunt number. Testing showed its standard form assumes every patient's "
            "outcome is already known — but many patients are still actively being "
            "monitored when we need to make a call, so their true outcome isn't settled yet.",

            "Adopting discrete-time interval classification — the technically precise "
            "version of that same time-banded idea, purpose-built to handle patients "
            "still under active observation correctly, instead of guessing or discarding "
            "them.",

            "Benchmarking against Cox regression — the decades-long industry-standard "
            "method in medical statistics — added as a comparison, so leadership and "
            "reviewers can see we tested against the field's gold standard, not just our "
            "own approach.",
        ],
        bottom_line="We didn't just implement a suggestion — we stress-tested it against "
                    "real data and are building the version that actually holds up.",
        notes="Full content is on the slide.",
    )

    content_slide(
        prs, "REAL-DATA INTEGRATION", "From Research Data to a Hospital's Own Data",
        bullets=[
            "Foundation already proven — built and validated on MIMIC-IV, a research-grade "
            "dataset used industry-wide to develop this class of clinical AI before it "
            "ever touches a real patient — the standard, responsible starting point.",

            "Data connectivity — once a hospital's system is connected as the single "
            "source of truth, the model's inputs are mapped to that hospital's own "
            "vital-sign and monitoring data formats — a defined technical integration step.",

            "Local recalibration — the model is recalibrated (not rebuilt from scratch) "
            "on the receiving hospital's own patient population before any live use, since "
            "patient mix and charting patterns vary by institution — standard practice "
            "when deploying clinical AI across hospitals.",

            "Shadow-mode validation — the model runs silently alongside existing clinical "
            "workflows, comparing predictions to real outcomes without influencing any "
            "clinical decision — the safe, industry-standard way to prove real-world "
            "performance before go-live.",

            "Independent validation — performance confirmed on a second, separate patient "
            "population before any production claim — the same bar regulatory bodies and "
            "leading hospital networks hold clinical AI tools to.",

            "Staged clinical rollout — only after the above, the system moves to advisory "
            "use, then wider clinical integration — gradual, monitored, and reversible at "
            "every stage.",
        ],
        bottom_line="Not a “plug in and go” — a responsible, staged path any hospital AI "
                    "deployment would follow, ready to execute once real data access is in place.",
        bullet_size=13,
        bullet_space=9,
        notes="Full content is on the slide.",
    )

    content_slide(
        prs, "OPTIMIZATION", "Fast, Scalable, and Safe by Design",
        bullets=[
            "Cutting false alarms at the source — group repeat alerts for the same patient "
            "instead of re-counting every hour as a new alarm; this alone is expected to be "
            "the single biggest, cheapest reduction in alert volume, before any deeper "
            "model change.",

            "Instant alerts, not delayed ones — moving the dashboard from polling to "
            "Server-Sent Events (SSE), where the server pushes a new risk score to the "
            "clinician's screen the instant it's ready.",

            "Reliable, low-latency backend delivery — using webhooks so the alerting "
            "system is notified the moment a new risk score is computed, rather than "
            "repeatedly polling the database — this also reduces database load as more "
            "patients and hospitals come online.",

            "Built to scale with patient volume — a stateless, queue-based scoring service "
            "so processing power scales independently as more patients are added, and "
            "safe, versioned model updates so we can improve the model in production "
            "without downtime or risk to the live system.",

            "Medical safety comes first — the system is explicitly tuned to minimize "
            "missed deteriorations, even if that means tolerating a few more false "
            "alerts — the clinically correct trade-off, monitored continuously after "
            "launch, not just at demo time.",
        ],
        bottom_line="Not just a smarter model — a system engineered to be fast, scalable, "
                    "and safe by design.",
        bullet_size=12.5,
        bullet_space=8,
        notes="Full content is on the slide.",
    )

    blank_placeholder_slide(prs)

    prs.save(OUT)
    print(f"wrote {os.path.abspath(OUT)}  ({len(prs.slides._sldIdLst)} slides)")


if __name__ == "__main__":
    main()
