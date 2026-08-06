"""Leadership pitch deck: Ward-Monitor discharge-summary product -- current
state, screens/flows, CMO pilot dashboard, cost estimator, and path to
production. Excludes sabari_project/ (his separate NEWS2 app) and Sabari's
ordinal-regression proposal entirely -- this deck covers Ashmit's own build.
Run: python build_leadership_ppt.py
"""
import os
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE
from pptx.oxml.ns import qn

OUT = os.environ.get("PPT_OUT", r"C:\Users\ASUS\Desktop\Ward_Monitor_Leadership_Pitch.pptx")
COST_PDF_PAGES_DIR = r"C:\Users\ASUS\AppData\Local\Temp\claude\C--Users-ASUS-Desktop-Ward-Monitor\35e5c21a-18c6-48a2-ba70-b7a8c6041704\scratchpad\cost_pdf_pages"

# ---------------------------------------------------------------- palette --
NAVY    = RGBColor(0x14, 0x23, 0x3F)
INK     = RGBColor(0x28, 0x32, 0x44)
MUTED   = RGBColor(0x76, 0x82, 0x94)
PAPER   = RGBColor(0xFF, 0xFF, 0xFF)
WASH    = RGBColor(0xF3, 0xF6, 0xF8)
ACCENT  = RGBColor(0x1F, 0x6F, 0x8B)
ACCENT_D= RGBColor(0x15, 0x50, 0x66)
ACCENT_WASH = RGBColor(0xE7, 0xF1, 0xF4)
LINE    = RGBColor(0xDD, 0xE3, 0xE8)
T1_C    = RGBColor(0x5C, 0x76, 0x96)
T2_C    = RGBColor(0xC8, 0x8A, 0x12)
T3_C    = RGBColor(0xB8, 0x3A, 0x3A)
OK_C    = RGBColor(0x2E, 0x8B, 0x57)
T1_WASH = RGBColor(0xE9, 0xED, 0xF3)
T2_WASH = RGBColor(0xFA, 0xEF, 0xDA)
T3_WASH = RGBColor(0xF6, 0xE3, 0xE3)

FONT = "Segoe UI"
SLIDE_W, SLIDE_H = Inches(13.333), Inches(7.5)
ML, MR, MTOP, MBOT = Inches(0.62), Inches(0.62), Inches(0.5), Inches(0.35)
CONTENT_TOP = Inches(1.62)

prs = Presentation()
prs.slide_width = SLIDE_W
prs.slide_height = SLIDE_H
BLANK = prs.slide_layouts[6]


def add_slide():
    return prs.slides.add_slide(BLANK)


def set_bg(slide, color=PAPER):
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = color


def _set_run(r, text, size, color, bold=False, italic=False, font=FONT, caps=False):
    r.text = text
    r.font.name = font
    r.font.size = Pt(size)
    r.font.color.rgb = color
    r.font.bold = bold
    r.font.italic = italic
    if caps:
        rPr = r._r.get_or_add_rPr()
        rPr.set('cap', 'all')


def textbox(slide, left, top, width, height, anchor=MSO_ANCHOR.TOP, wrap=True):
    tb = slide.shapes.add_textbox(left, top, width, height)
    tf = tb.text_frame
    tf.word_wrap = wrap
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    return tb, tf


def header(slide, eyebrow, title, idx, total):
    set_bg(slide)
    _, tf = textbox(slide, ML, Inches(0.5), Inches(11.0), Inches(0.3))
    p = tf.paragraphs[0]
    r = p.add_run()
    _set_run(r, eyebrow, 11.5, ACCENT, bold=True, caps=True)
    rPr = r._r.get_or_add_rPr()
    rPr.set('spc', '150')

    _, tf2 = textbox(slide, ML, Inches(0.82), Inches(11.6), Inches(0.6))
    p2 = tf2.paragraphs[0]
    r2 = p2.add_run()
    _set_run(r2, title, 27, NAVY, bold=True)

    rule = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, ML, Inches(1.42), Inches(0.55), Pt(3))
    rule.fill.solid(); rule.fill.fore_color.rgb = ACCENT
    rule.line.fill.background()
    rule.shadow.inherit = False

    _, tf3 = textbox(slide, ML, Inches(7.14), Inches(6), Inches(0.28))
    p3 = tf3.paragraphs[0]
    r3 = p3.add_run()
    _set_run(r3, "Ward-Monitor · Foqal CareOS · Confidential", 9, MUTED)

    _, tf4 = textbox(slide, Inches(11.6), Inches(7.14), Inches(1.1), Inches(0.28))
    p4 = tf4.paragraphs[0]
    p4.alignment = PP_ALIGN.RIGHT
    r4 = p4.add_run()
    _set_run(r4, f"{idx:02d} / {total:02d}", 9, MUTED)


def bullets(slide, left, top, width, height, items, size=15.5, color=INK,
            lead_size=None, gap=8, lh=1.12):
    _, tf = textbox(slide, left, top, width, height)
    first = True
    for lead, body, level in items:
        p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        p.space_after = Pt(gap)
        p.line_spacing = lh
        marker = "—" if level == 0 else "–"
        indent = "" if level == 0 else "    "
        r0 = p.add_run()
        _set_run(r0, f"{indent}{marker}  ", size, ACCENT if level == 0 else MUTED, bold=(level == 0))
        if lead:
            r1 = p.add_run()
            _set_run(r1, f"{lead}  ", lead_size or size, NAVY, bold=True)
        r2 = p.add_run()
        _set_run(r2, body, size, color)
    return tf


def business_box(slide, left, top, width, height, text, label="IN PLAIN TERMS"):
    box = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, top, width, height)
    box.adjustments[0] = 0.05
    box.fill.solid(); box.fill.fore_color.rgb = ACCENT_WASH
    box.line.color.rgb = ACCENT; box.line.width = Pt(0.75)
    box.shadow.inherit = False
    tf = box.text_frame
    tf.word_wrap = True
    tf.margin_left = Inches(0.22); tf.margin_right = Inches(0.22)
    tf.margin_top = Inches(0.14); tf.margin_bottom = Inches(0.14)
    p0 = tf.paragraphs[0]
    r0 = p0.add_run()
    _set_run(r0, label, 10, ACCENT_D, bold=True, caps=True)
    rPr = r0._r.get_or_add_rPr(); rPr.set('spc', '150')
    p1 = tf.add_paragraph()
    p1.space_before = Pt(4)
    p1.line_spacing = 1.15
    r1 = p1.add_run()
    _set_run(r1, text, 13.5, INK, italic=True)
    return box


def card(slide, left, top, width, height, fill=WASH, line=LINE, line_w=0.75):
    box = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, top, width, height)
    box.adjustments[0] = 0.045
    box.fill.solid(); box.fill.fore_color.rgb = fill
    box.line.color.rgb = line; box.line.width = Pt(line_w)
    box.shadow.inherit = False
    return box


def kicker(tf, text, size, color, bold=True, caps=True, space_after=4):
    p = tf.paragraphs[0]
    r = p.add_run()
    _set_run(r, text, size, color, bold=bold, caps=caps)
    if caps:
        rPr = r._r.get_or_add_rPr(); rPr.set('spc', '120')
    p.space_after = Pt(space_after)
    return p


def flow_row(slide, top, boxes, box_w, box_h, gap_w, start_left=None, fill=WASH, line=ACCENT, text_color=NAVY, size=12.5):
    n = len(boxes)
    total_w = n * box_w + (n - 1) * gap_w
    left = start_left if start_left is not None else (SLIDE_W - total_w) / 2
    for i, label in enumerate(boxes):
        x = left + i * (box_w + gap_w)
        b = card(slide, x, top, box_w, box_h, fill=fill, line=line, line_w=1.25)
        tf = b.text_frame
        tf.word_wrap = True
        tf.vertical_anchor = MSO_ANCHOR.MIDDLE
        tf.margin_left = tf.margin_right = Inches(0.1)
        p = tf.paragraphs[0]
        p.alignment = PP_ALIGN.CENTER
        r = p.add_run()
        _set_run(r, label, size, text_color, bold=True)
        if i < n - 1:
            ax = x + box_w
            _, atf = textbox(slide, ax, top, gap_w, box_h, anchor=MSO_ANCHOR.MIDDLE)
            ap = atf.paragraphs[0]
            ap.alignment = PP_ALIGN.CENTER
            ar = ap.add_run()
            _set_run(ar, "→", 20, ACCENT, bold=True)
    return left, total_w


def kv_card(slide, left, top, width, height, title, rows):
    b = card(slide, left, top, width, height)
    tf = b.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = Inches(0.2); tf.margin_top = Inches(0.16)
    kicker(tf, title, 12, NAVY, caps=False, space_after=8)
    for k, v in rows:
        p = tf.add_paragraph()
        p.space_after = Pt(6); p.line_spacing = 1.1
        r1 = p.add_run(); _set_run(r1, f"{k}:  ", 12.5, MUTED)
        r2 = p.add_run(); _set_run(r2, v, 12.5, INK, bold=True)
    return b


# =====================================================================
# SLIDES
# =====================================================================

def s_title():
    slide = add_slide()
    set_bg(slide, NAVY)
    band = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, Inches(4.55), SLIDE_W, Inches(0.045))
    band.fill.solid(); band.fill.fore_color.rgb = ACCENT
    band.line.fill.background(); band.shadow.inherit = False

    _, tf = textbox(slide, Inches(0.9), Inches(2.55), Inches(11.5), Inches(0.4))
    p = tf.paragraphs[0]
    r = p.add_run(); _set_run(r, "FOQAL CAREOS · WARD-MONITOR", 13, RGBColor(0x8F, 0xB9, 0xC9), bold=True, caps=True)
    rPr = r._r.get_or_add_rPr(); rPr.set('spc', '200')

    _, tf2 = textbox(slide, Inches(0.9), Inches(3.0), Inches(11.5), Inches(1.4))
    p2 = tf2.paragraphs[0]
    r2 = p2.add_run(); _set_run(r2, "AI Discharge Summary Platform", 40, PAPER, bold=True)
    p2b = tf2.add_paragraph()
    r2b = p2b.add_run(); _set_run(r2b, "Current State, Live Pilot Metrics, and Path to Production", 20, RGBColor(0xB9, 0xCE, 0xD8))

    _, tf3 = textbox(slide, Inches(0.9), Inches(4.85), Inches(9), Inches(0.4))
    p3 = tf3.paragraphs[0]
    r3 = p3.add_run(); _set_run(r3, "Leadership Briefing · Prepared for CEO & Stakeholder Review", 14, RGBColor(0x8F, 0xB9, 0xC9))

    _, tf4 = textbox(slide, Inches(0.9), Inches(6.85), Inches(9), Inches(0.35))
    p4 = tf4.paragraphs[0]
    r4 = p4.add_run(); _set_run(r4, "Presented by Harshika", 12, MUTED)


def s_exec_summary(idx, total):
    slide = add_slide()
    header(slide, "Executive Summary", "Where We Are, and What We're Asking For", idx, total)
    items = [
        ("Live today.", "AI drafts a discharge summary, an independent AI pass fact-checks it against the source chart, a doctor reviews and signs — and a CMO-facing dashboard already tracks quality and safety on a live pilot at Medanta.", 0),
        ("Built-in safety mechanism.", "A Pilot Safety Gate auto-flags the system if the rate of critical (Tier-3) errors crosses a set threshold — this isn't a future idea, it's already running.", 0),
        ("Two more modules, same platform.", "A rule-based drug-lab interaction checker runs alongside the AI, and a separate cost-estimation module (quantile regression) gives patients a bill-range estimate.", 0),
        ("The ask.", "Sign-off to move from demo/pilot data to a live hospital data feed, formalize the safety-gate threshold with clinical stakeholders, and approve the phased rollout plan in this deck.", 0),
    ]
    bullets(slide, ML, CONTENT_TOP, Inches(11.9), Inches(4.6), items, size=16, gap=16, lh=1.2)


def s_product_overview(idx, total):
    slide = add_slide()
    header(slide, "Product Overview", "How a Discharge Summary Moves Through the System", idx, total)
    flow_row(slide, Inches(2.05), ["Patient\nQueue / Intake", "AI Draft\n(2-Pass Gen.)", "AI Fact-Check\n(T1/T2/T3)", "Doctor\nReview & Sign", "Signed\nRecord"],
             Inches(2.05), Inches(1.05), Inches(0.42), start_left=Inches(0.62), size=13)
    _, tf = textbox(slide, Inches(0.62), Inches(3.55), Inches(11.9), Inches(0.4))
    p = tf.paragraphs[0]
    r = p.add_run(); _set_run(r, "Every signed record feeds two leadership-facing views, plus a second safety layer runs throughout:", 13.5, MUTED, italic=True)

    cards = [
        ("CMO DASHBOARD", "Live pilot quality metrics, safety gate status, and baseline-vs-pilot impact — built for exactly this kind of review.", T2_WASH, T2_C),
        ("WARD ADMIN", "Operational view: pipeline status, full audit log, and document version history for every case.", ACCENT_WASH, ACCENT),
        ("DRUG-LAB SAFETY NET", "Independent, rule-based interaction checker running alongside the AI on every case.", T1_WASH, T1_C),
    ]
    w = Inches(3.78); gap = Inches(0.28); left0 = Inches(0.62)
    for i, (kick, desc, fill, line) in enumerate(cards):
        x = left0 + i * (w + gap)
        b = card(slide, x, Inches(4.1), w, Inches(1.55), fill=fill, line=line)
        tf1 = b.text_frame; tf1.word_wrap=True; tf1.margin_left=Inches(0.18); tf1.margin_top=Inches(0.14); tf1.margin_right=Inches(0.16)
        kicker(tf1, kick, 10.5, line, space_after=6)
        p1 = tf1.add_paragraph(); r1 = p1.add_run()
        _set_run(r1, desc, 12.5, INK)

    business_box(slide, Inches(0.62), Inches(5.9), Inches(11.7), Inches(0.85),
                 "Every summary passes an automated safety check before a doctor ever sees it, and the whole pipeline is already visible to leadership through a live dashboard — not a black box.")


def s_algo_architecture(idx, total):
    slide = add_slide()
    header(slide, "Current State — Algorithm", "Two-Pass Generation, Then Independent Verification", idx, total)
    items = [
        ("Pass 1 & 2 — Generation.", "The AI drafts, then refines, a discharge summary across 15 standard NABH sections (Chief Complaint, Hospital Course, Discharge Medications, etc.), each version-tracked.", 0),
        ("Pass 3 — Verification.", "A separate AI pass re-reads each section against ONLY that section's own source data (labs, meds, diagnoses) — no cross-section leakage — and tags it OK, T1, T2, or T3.", 0),
        ("Worst tier wins.", "Where a section is flagged by more than one check, the most severe tier is what the doctor sees — the system never quietly downgrades a serious flag.", 0),
        ("Gate before the queue.", "This entire check completes before a case is marked “Ready for Review” — doctors only ever see already fact-checked drafts.", 0),
    ]
    bullets(slide, ML, CONTENT_TOP, Inches(7.1), Inches(4.6), items, size=15, gap=14, lh=1.18)
    business_box(slide, Inches(7.95), CONTENT_TOP, Inches(4.6), Inches(4.5),
                 "Think of Pass 3 as a second, independent AI reading the chart fresh and fact-checking the first AI's draft — closer to a peer reviewer than a spell-checker. It runs automatically, on every case, before a doctor's time is spent.",
                 label="IN PLAIN TERMS")


def s_tiers(idx, total):
    slide = add_slide()
    header(slide, "Current State — Severity Scale", "Tier Definitions (T1 → T2 → T3)", idx, total)
    tiers = [
        ("T1", "Formatting / Phrasing", T1_C, T1_WASH, "Wording or formatting differences; clinical meaning unchanged.",
         "e.g. a date format or unit-label mismatch where the number and meaning are identical."),
        ("T2", "Wrong Drug / Dose / Duration", T2_C, T2_WASH, "A medication detail doesn't match the source record.",
         "e.g. AI states a different dose or frequency than what's actually on the chart."),
        ("T3", "Wrong Diagnosis, Hallucination, or Missed Finding", T3_C, T3_WASH, "Patient-safety-relevant error.",
         "e.g. a diagnosis, lab value, or finding appears that isn't anywhere in the source data."),
    ]
    w = Inches(3.78); gap = Inches(0.28); left0 = Inches(0.62); top = CONTENT_TOP
    for i, (code, name, c, wash, desc, ex) in enumerate(tiers):
        x = left0 + i * (w + gap)
        b = card(slide, x, top, w, Inches(3.7), fill=wash, line=c, line_w=1.5)
        tf = b.text_frame; tf.word_wrap = True
        tf.margin_left = tf.margin_right = Inches(0.22); tf.margin_top = Inches(0.22)
        p0 = tf.paragraphs[0]
        r0 = p0.add_run(); _set_run(r0, code, 34, c, bold=True)
        p1 = tf.add_paragraph(); p1.space_before = Pt(0); p1.line_spacing = 1.05
        r1 = p1.add_run(); _set_run(r1, name, 14.5, NAVY, bold=True)
        p2 = tf.add_paragraph(); p2.space_before = Pt(14); p2.line_spacing = 1.2
        r2 = p2.add_run(); _set_run(r2, desc, 13, INK)
        p3 = tf.add_paragraph(); p3.space_before = Pt(12); p3.line_spacing = 1.15
        r3 = p3.add_run(); _set_run(r3, "Illustrative — ", 11.5, MUTED, italic=True, bold=True)
        r3b = p3.add_run(); _set_run(r3b, ex, 11.5, MUTED, italic=True)
    business_box(slide, Inches(0.62), Inches(6.15), Inches(11.7), Inches(0.85),
                 "This exact tier legend is what a doctor sees on every flagged passage, and what leadership sees rolled up per NABH section on the CMO Dashboard (next section).")


def s_limitations(idx, total):
    slide = add_slide()
    header(slide, "Current State — Limitations", "Known Gaps, Stated Plainly", idx, total)
    items = [
        ("Pilot/demo data, not a live hospital feed yet.", "The pipeline currently runs on MIMIC-IV (public, de-identified) data and a Medanta-branded pilot dashboard — not a production HIS connection.", 0),
        ("Safety-gate threshold isn't yet clinically ratified.", "The Tier-3 auto-flag defaults to a 25% threshold in code — a reasonable starting point, but not yet a number clinical leadership has formally signed off on.", 0),
        ("SLA breach flagging is admin-triggered.", "The “review taking too long” alert is raised by a ward admin today, not an automatic timer watching case age.", 0),
        ("Polling, not real-time.", "Screens refresh on a 5–8 second poll cycle rather than push updates — fine at pilot scale, a cost to revisit as case volume grows.", 0),
        ("Cost Estimator isn't wired to live patients yet.", "The quantile-regression cost model currently serves only the historical training cohort — connecting it to live, in-pilot patients is a scoped next step, not done.", 0),
    ]
    bullets(slide, ML, CONTENT_TOP, Inches(11.9), Inches(4.05), items, size=14.5, gap=11, lh=1.15)
    business_box(slide, ML, Inches(6.05), Inches(11.9), Inches(0.95),
                 "The platform already works end to end, with real quality tracking on a live pilot. What's left is moving the data source, the safety threshold, and the cost model from “pilot-ready” to “clinically signed-off and production-connected.”")


def s_flow_screens(idx, total):
    slide = add_slide()
    header(slide, "Doctor Workflow", "Screen by Screen — Intake, Queue, Review, Sign-Off", idx, total)
    cards = [
        ("1. INTAKE / QUEUE", "Patient Queue & Upload", "New cases enter the patient queue; every case awaiting sign-off shows live T1/T2/T3 counts and auto-refreshes while an AI draft regenerates."),
        ("2. REVIEW", "Document Review", "Full summary shown section by section; flagged passages are highlighted inline with tier + explanation, next to the original source data."),
        ("3. SIGN-OFF", "Digital Sign-Off", "Doctor signs with their signature and registration number; the record is finalized, timestamped, and triggers billing reconciliation."),
    ]
    w = Inches(3.78); gap = Inches(0.28); left0 = Inches(0.62)
    for i, (kick, title, desc) in enumerate(cards):
        x = left0 + i * (w + gap)
        b = card(slide, x, CONTENT_TOP, w, Inches(3.55))
        tf = b.text_frame; tf.word_wrap = True
        tf.margin_left = tf.margin_right = Inches(0.22); tf.margin_top = Inches(0.24)
        kicker(tf, kick, 10.5, ACCENT, space_after=6)
        p1 = tf.add_paragraph(); r1 = p1.add_run(); _set_run(r1, title, 17, NAVY, bold=True)
        p2 = tf.add_paragraph(); p2.space_before = Pt(10); p2.line_spacing = 1.2
        r2 = p2.add_run(); _set_run(r2, desc, 13.5, INK)
    business_box(slide, Inches(0.62), Inches(6.15), Inches(11.7), Inches(0.85),
                 "Doctors work from one queue, review the full document with every AI claim checkable against the source chart, and sign off with a real digital signature — nothing is a black box.")


def s_override_amend(idx, total):
    slide = add_slide()
    header(slide, "Doctor Workflow", "Override, Rejection & Amendment", idx, total)
    items = [
        ("Doctor can always override.", "Any AI-flagged claim can be corrected inline; the correction is logged against the original AI output in the audit trail — the doctor's word is what stands.", 0),
        ("Reject & regenerate.", "A doctor can send a section or the whole summary back for regeneration; the system tracks rejection count and restores review state on refresh, so nothing is lost mid-flow.", 0),
        ("Post-sign amendment.", "A doctor can request a correction to an already-signed record — reason, section, and details — which creates a new tracked version (v1.0 → v1.1) rather than silently overwriting the signed original.", 0),
        ("Billing reconciliation.", "Sign-off automatically triggers the downstream billing reconciliation step, so the clinical and billing records move in lockstep without a manual handoff.", 0),
    ]
    bullets(slide, ML, CONTENT_TOP, Inches(11.9), Inches(4.6), items, size=15, gap=14, lh=1.18)


def s_drug_lab(idx, total):
    slide = add_slide()
    header(slide, "Patient Safety", "A Second, Independent Safety Net", idx, total)
    _, tf = textbox(slide, ML, CONTENT_TOP, Inches(11.9), Inches(0.5))
    p = tf.paragraphs[0]; r = p.add_run()
    _set_run(r, "Drug-Lab Interaction Review — rule-based, separate from the AI verifier", 16, NAVY, bold=True)

    items = [
        ("What it is.", "A curated set of drug–drug and drug–lab interaction rules (e.g. Warfarin + Aspirin, Digoxin + low potassium), each sourced from published clinical guidance (ACCP, ESC, ICMR, FDA).", 0),
        ("How it's tiered.", "Each rule carries a fixed severity — T1 (monitor) or T2 (hold / act immediately) — and a required action, so it's deterministic, not model-generated.", 0),
        ("Who maintains it.", "Clinically editable through the Super Admin panel as guidance evolves, independent of any AI model update cycle.", 0),
    ]
    bullets(slide, ML, Inches(2.25), Inches(7.1), Inches(3.9), items, size=15, gap=14, lh=1.18)
    business_box(slide, Inches(7.95), Inches(2.25), Inches(4.6), Inches(3.85),
                 "This is deliberately not AI-based — it's a guideline checklist that runs alongside the AI fact-checker. Two independent lines of defense, not one, so a weakness in either doesn't become a single point of failure.")


def s_ops_governance(idx, total):
    slide = add_slide()
    header(slide, "Operations & Governance", "Ward Admin & Super Admin Controls", idx, total)
    kv_card(slide, Inches(0.62), CONTENT_TOP, Inches(5.85), Inches(4.55), "Ward Admin", [
        ("Summary Pipeline", "Live status of every case in flight"),
        ("Audit Log", "Full trail of AI output, doctor edits, and actions"),
        ("DS Version History", "Every generation and amendment, versioned"),
        ("Module Health", "System status monitoring"),
    ])
    kv_card(slide, Inches(6.72), CONTENT_TOP, Inches(5.85), Inches(4.55), "Super Admin", [
        ("User Management", "Role-based access control (RBAC)"),
        ("Drug-Lab Rules", "Add / edit interaction rules & severities"),
        ("Threshold Config", "Module toggles and safety thresholds"),
    ])
    business_box(slide, ML, Inches(6.35), Inches(11.9), Inches(0.75),
                 "Nothing runs unmonitored or unowned — every case, every AI decision, and every rule change has an audit trail and a role responsible for it.")


def s_cmo_dashboard(idx, total):
    slide = add_slide()
    header(slide, "Leadership Visibility", "CMO Dashboard — Live Pilot Monitoring", idx, total)
    items = [
        ("System status, right now.", "Cases in progress, cases signed off today, and average turnaround per case — visible live, not in a monthly report.", 0),
        ("Pilot Safety Gate.", "The system tracks the Tier-3 (critical error) rate and flags/pauses the pilot if it crosses a set threshold — defaults to 25% in code today, pending clinical ratification (see Limitations).", 0),
        ("Section-wise accuracy.", "Every NABH section (Chief Complaint, Medications, etc.) gets its own accuracy score and T1/T2/T3 rate, rolled up from real reviewed cases.", 0),
        ("Cases needing attention.", "A live worklist of every open case still carrying an unresolved AI-accuracy flag, with assigned doctor and how long it's been open.", 0),
    ]
    bullets(slide, ML, CONTENT_TOP, Inches(11.9), Inches(4.2), items, size=15, gap=13, lh=1.18)
    business_box(slide, ML, Inches(6.0), Inches(11.9), Inches(0.95),
                 "This dashboard already exists and is built specifically for a CMO / leadership audience — it's the same lens this presentation is using, just live and continuously updated.")


def s_cmo_baseline(idx, total):
    slide = add_slide()
    header(slide, "Leadership Visibility", "Baseline vs. Pilot — What Changes for the Hospital", idx, total)
    rows = [
        ("Documentation time", "Manual drafting", "AI-assisted, doctor-reviewed", ACCENT),
        ("Error detection", "Manual review only", "Auto-detected on every section", ACCENT),
        ("NABH section compliance", "Tracked ad hoc", "Tracked automatically, per section", ACCENT),
        ("Re-admission risk flagging", "Not flagged today", "New: AI flags risk at discharge", OK_C),
    ]
    top = CONTENT_TOP
    header_row = card(slide, ML, top, Inches(11.9), Inches(0.55), fill=NAVY, line=NAVY)
    tf = header_row.text_frame; tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    tf.margin_left = Inches(0.25)
    p = tf.paragraphs[0]
    cols = [("Metric", 3.4), ("Baseline (pre-pilot)", 3.9), ("Pilot (this platform)", 3.4), ("", 1.2)]
    # simple 3-col header text
    r = p.add_run(); _set_run(r, "Metric", 12.5, PAPER, bold=True)
    top += Inches(0.65)
    for metric, base, pilot, c in rows:
        row = card(slide, ML, top, Inches(11.9), Inches(0.85))
        tf = row.text_frame; tf.vertical_anchor = MSO_ANCHOR.MIDDLE
        tf.margin_left = Inches(0.25); tf.margin_right = Inches(0.2)
        p = tf.paragraphs[0]
        r1 = p.add_run(); _set_run(r1, f"{metric}", 13.5, NAVY, bold=True)
        r2 = p.add_run(); _set_run(r2, "   —   ", 13, MUTED)
        r3 = p.add_run(); _set_run(r3, f"{base}", 13, MUTED)
        r4 = p.add_run(); _set_run(r4, "   →   ", 13, MUTED)
        r5 = p.add_run(); _set_run(r5, f"{pilot}", 13.5, c, bold=True)
        top += Inches(1.0)
    business_box(slide, ML, top + Inches(0.05), Inches(11.9), Inches(0.85),
                 "These deltas are already tracked live on the CMO Dashboard for the Medanta pilot cohort — precise figures intentionally omitted here pending a finalized measurement window; the dashboard itself is the source of truth.")


def s_cost_estimator(idx, total):
    slide = add_slide()
    header(slide, "Also on This Platform", "Cost Estimator (Module B)", idx, total)
    items = [
        ("What it is.", "A patient-facing cost estimation module — Cost Estimator, Live Bill, Cost Reconciliation, and a shareable estimate — sitting alongside the discharge-summary workflow in the same product.", 0),
        ("What's under the hood.", "A day-wise cost prediction model (quantile regression) that gives a P10 / P50 / P90 style range estimate rather than a single number, replacing older flat-rate scheme lookups.", 0),
        ("Status.", "Trained and serving on the historical cohort; not yet wired to live, in-pilot patients — that connection is a scoped next step.", 0),
        ("Reviewed.", "Approach and results reviewed and approved by Gautam Sir, academic advisor on this model.", 0),
        ("Not covered here.", "Model performance figures are covered in a separate, dedicated deck for this model — intentionally out of scope for this presentation.", 0),
    ]
    bullets(slide, ML, CONTENT_TOP, Inches(11.9), Inches(4.4), items, size=15.5, gap=15, lh=1.2)


def s_data_architecture(idx, total):
    slide = add_slide()
    header(slide, "Data Architecture", "Inflows, Outflows, and Single Source of Truth", idx, total)
    flow_row(slide, Inches(2.1), ["Hospital\nData Source", "Ingestion &\nMapping", "Active Patient\nStore (source\nof truth)", "AI Gen +\nVerification", "Doctor\nReview & Sign", "Signed Record\n(+ Amendments)"],
             Inches(1.85), Inches(1.1), Inches(0.22), start_left=Inches(0.62), size=11.5)
    items = [
        ("Today.", "The pipeline runs on MIMIC-IV, a public de-identified research dataset, pulled via BigQuery into our Cloud SQL store — the same architecture pattern a live HIS feed would plug into.", 0),
        ("Single source of truth.", "The active-patient store is already the authoritative identity record end to end — every downstream view (doctor review, CMO dashboard, ward admin) reads from the same record, so nothing can drift out of sync.", 0),
        ("Outflow.", "Signed summaries, the amendment log, and version history write back out — designed to hand off to a hospital's records system, not just live inside this product.", 0),
    ]
    bullets(slide, ML, Inches(3.65), Inches(11.9), Inches(2.7), items, size=13.5, gap=10, lh=1.15)


def s_path_realdata(idx, total):
    slide = add_slide()
    header(slide, "Path to Production", "Moving From Pilot Data to a Live Hospital Feed", idx, total)
    items = [
        ("Connect a live HIS feed.", "Replace the MIMIC-IV / demo data source with a real-time feed from one pilot hospital (Medanta) — same ingestion architecture, new data source.", 0),
        ("Ratify the Safety Gate.", "Take the Tier-3 auto-pause threshold (currently a 25% code default) to clinical leadership and set it as a formally agreed number.", 0),
        ("Wire up the Cost Estimator.", "Extend the quantile-regression cost model's live-feature pipeline so it can price in-pilot patients, not just the historical training cohort.", 0),
        ("Reconcile against outcomes.", "Compare CMO Dashboard section-accuracy numbers against real chart audits over a defined pilot window, before treating them as a settled baseline.", 0),
    ]
    bullets(slide, ML, CONTENT_TOP, Inches(11.9), Inches(4.4), items, size=15.5, gap=15, lh=1.2)


def s_action_timeline(idx, total):
    slide = add_slide()
    header(slide, "Action Plan", "Timeline Overview", idx, total)
    phases = [
        ("SCOPING", "1–2 wks", "Agree the Safety Gate threshold and pilot data-access terms with the hospital.", ACCENT),
        ("INTEGRATION", "3–4 wks", "Connect the live HIS feed and wire the Cost Estimator to live patients.", ACCENT),
        ("SHADOW MONITORING", "2–3 wks", "Run live data through the pipeline with dashboard tracking, before any workflow change for doctors.", T2_C),
        ("PHASED ROLLOUT", "Ongoing", "Expand ward by ward, gated on Safety Gate status staying green.", OK_C),
    ]
    w = Inches(2.78); gap = Inches(0.24); left0 = Inches(0.62)
    for i, (name, dur, desc, c) in enumerate(phases):
        x = left0 + i * (w + gap)
        top_bar = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, x, CONTENT_TOP, w, Inches(0.55))
        top_bar.adjustments[0] = 0.15
        top_bar.fill.solid(); top_bar.fill.fore_color.rgb = c
        top_bar.line.fill.background(); top_bar.shadow.inherit = False
        tf = top_bar.text_frame; tf.vertical_anchor = MSO_ANCHOR.MIDDLE
        p = tf.paragraphs[0]; p.alignment = PP_ALIGN.CENTER
        r = p.add_run(); _set_run(r, name, 12.5, PAPER, bold=True, caps=True)

        b = card(slide, x, Inches(2.35), w, Inches(2.55))
        tf2 = b.text_frame; tf2.word_wrap = True
        tf2.margin_left = tf2.margin_right = Inches(0.16); tf2.margin_top = Inches(0.2)
        p1 = tf2.paragraphs[0]; r1 = p1.add_run(); _set_run(r1, dur, 20, c, bold=True)
        p2 = tf2.add_paragraph(); p2.space_before = Pt(10); p2.line_spacing = 1.18
        r2 = p2.add_run(); _set_run(r2, desc, 12.5, INK)
        if i < 3:
            _, atf = textbox(slide, x + w, Inches(2.35), gap, Inches(2.55), anchor=MSO_ANCHOR.MIDDLE)
            ap = atf.paragraphs[0]; ap.alignment = PP_ALIGN.CENTER
            ar = ap.add_run(); _set_run(ar, "→", 18, MUTED, bold=True)
    business_box(slide, Inches(0.62), Inches(5.25), Inches(11.7), Inches(0.85),
                 "Indicative durations — to be firmed up in Scoping once hospital data-access timelines are confirmed.")


def s_scalability(idx, total):
    slide = add_slide()
    header(slide, "Action Plan", "Scalability & Architecture", idx, total)
    items = [
        ("Refresh strategy.", "Screens currently poll every 5–8 seconds — fine at pilot scale, a database-load cost worth revisiting as concurrent case volume grows. Options: longer intervals for low-priority views, event-driven push specifically for the review queue.", 0),
        ("Versioning, already built.", "Amendments already have full version history and an audit log. The same pattern extends naturally to any future model or rule change — always know which version produced which result.", 0),
        ("Multi-hospital formats.", "The pipeline currently supports one data schema. A multi-hospital rollout needs a mapping/normalization layer per HIS vendor — scoped explicitly as part of the real-data integration phase, not an afterthought.", 0),
    ]
    bullets(slide, ML, CONTENT_TOP, Inches(11.9), Inches(4.7), items, size=15, gap=16, lh=1.2)


def s_gating(idx, total):
    slide = add_slide()
    header(slide, "Action Plan", "Deployment & Leadership Gating Criteria", idx, total)
    _, tf = textbox(slide, ML, CONTENT_TOP, Inches(11.9), Inches(0.4))
    p = tf.paragraphs[0]; r = p.add_run()
    _set_run(r, "What must be true before full production sign-off:", 15.5, NAVY, bold=True)
    items = [
        (None, "Safety Gate threshold formally ratified by clinical leadership, not just the current code default.", 0),
        (None, "Live HIS connectivity validated end to end for the pilot hospital.", 0),
        (None, "Doctor override stays available and always wins — the system is never fully autonomous.", 0),
        (None, "Cost Estimator wired to live patients, not just the historical cohort.", 0),
        (None, "CMO Dashboard numbers reconciled against real chart audits over a defined window.", 0),
    ]
    bullets(slide, ML, Inches(2.35), Inches(11.9), Inches(3.4), items, size=16, gap=13, lh=1.2)
    business_box(slide, ML, Inches(6.05), Inches(11.9), Inches(0.95),
                 "This is the checklist we're asking leadership to bless today — the bar the platform has to clear before it moves from pilot to production.")


def s_risk(idx, total):
    slide = add_slide()
    header(slide, "Risk & Mitigation", "The Risk That Matters, and How We Cover It", idx, total)
    b = card(slide, ML, CONTENT_TOP, Inches(11.9), Inches(1.35), fill=T3_WASH, line=T3_C, line_w=1.25)
    tf = b.text_frame; tf.word_wrap = True; tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    tf.margin_left = Inches(0.25); tf.margin_right=Inches(0.25)
    kicker(tf, "PRIMARY RISK", 11, T3_C, space_after=4)
    p1 = tf.add_paragraph(); p1.line_spacing=1.15
    r1 = p1.add_run(); _set_run(r1, "A critical (Tier-3) error reaches a doctor undetected — a real patient-safety consequence, not a UX bug.", 14.5, INK)

    items = [
        ("Pilot Safety Gate.", "The system already auto-flags/pauses on elevated Tier-3 rates — this exists today, and gets formally ratified as part of Path to Production.", 0),
        ("Human stays final authority.", "A doctor reviews and signs every case — the platform is decision support, never a fully automated sign-off.", 0),
        ("Two independent safety layers.", "AI verifier + rule-based drug-lab checks run in parallel, so a weakness in one isn't a single point of failure.", 0),
        ("Full audit trail.", "Every AI output, doctor edit, rejection, and amendment is logged and versioned — nothing is unrecoverable or untraceable.", 0),
    ]
    bullets(slide, ML, Inches(3.35), Inches(11.9), Inches(3.4), items, size=14.5, gap=12, lh=1.15)


def s_ask(idx, total):
    slide = add_slide()
    set_bg(slide, NAVY)
    _, tf = textbox(slide, Inches(0.9), Inches(0.9), Inches(9), Inches(0.4))
    p = tf.paragraphs[0]; r = p.add_run()
    _set_run(r, "THE ASK", 13, RGBColor(0x8F,0xB9,0xC9), bold=True, caps=True)
    rPr = r._r.get_or_add_rPr(); rPr.set('spc', '200')
    _, tf2 = textbox(slide, Inches(0.9), Inches(1.3), Inches(11), Inches(0.8))
    p2 = tf2.paragraphs[0]; r2 = p2.add_run()
    _set_run(r2, "What We Need From Leadership Today", 30, PAPER, bold=True)

    items = [
        ("1.", "Sign-off to move from pilot/demo data to a live HIS feed at the pilot hospital."),
        ("2.", "Formalize the Pilot Safety Gate threshold with clinical stakeholders."),
        ("3.", "Approve the phased rollout plan and gating criteria (Safety Gate, HIS validation, cost-estimator connection, audit reconciliation) as the bar for go-live."),
    ]
    top = Inches(2.7)
    for num, text in items:
        card_b = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.9), top, Inches(11.4), Inches(1.05))
        card_b.adjustments[0] = 0.1
        card_b.fill.solid(); card_b.fill.fore_color.rgb = RGBColor(0x1C, 0x30, 0x52)
        card_b.line.color.rgb = ACCENT; card_b.line.width = Pt(0.75)
        card_b.shadow.inherit = False
        tf3 = card_b.text_frame; tf3.word_wrap = True; tf3.vertical_anchor = MSO_ANCHOR.MIDDLE
        tf3.margin_left = Inches(0.3); tf3.margin_right = Inches(0.3)
        p3 = tf3.paragraphs[0]
        r3a = p3.add_run(); _set_run(r3a, f"{num}  ", 16, ACCENT, bold=True)
        r3b = p3.add_run(); _set_run(r3b, text, 15, PAPER)
        top += Inches(1.25)


def s_appendix_divider(idx, total):
    slide = add_slide()
    set_bg(slide, NAVY)
    _, tf = textbox(slide, Inches(0.9), Inches(3.1), Inches(11), Inches(0.4))
    p = tf.paragraphs[0]; r = p.add_run()
    _set_run(r, "APPENDIX", 13, RGBColor(0x8F, 0xB9, 0xC9), bold=True, caps=True)
    rPr = r._r.get_or_add_rPr(); rPr.set('spc', '200')
    _, tf2 = textbox(slide, Inches(0.9), Inches(3.5), Inches(11), Inches(1.1))
    p2 = tf2.paragraphs[0]; r2 = p2.add_run()
    _set_run(r2, "Cost Prediction Model — Full Deck", 32, PAPER, bold=True)
    p2b = tf2.add_paragraph()
    r2b = p2b.add_run(); _set_run(r2b, "Day-wise cost prediction (quantile regression) — reference material, in full", 16, RGBColor(0xB9, 0xCE, 0xD8))

    badge = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.9), Inches(4.95), Inches(6.1), Inches(0.55))
    badge.adjustments[0] = 0.4
    badge.fill.solid(); badge.fill.fore_color.rgb = RGBColor(0x1C, 0x30, 0x52)
    badge.line.color.rgb = OK_C; badge.line.width = Pt(1)
    badge.shadow.inherit = False
    btf = badge.text_frame; btf.vertical_anchor = MSO_ANCHOR.MIDDLE
    btf.margin_left = Inches(0.2); btf.margin_right = Inches(0.2)
    bp = btf.paragraphs[0]
    br1 = bp.add_run(); _set_run(br1, "✓  ", 14, OK_C, bold=True)
    br2 = bp.add_run(); _set_run(br2, "Approved by Gautam Sir (Academic Advisor)", 13.5, PAPER, bold=True)

    _, tf3 = textbox(slide, Inches(0.9), Inches(7.14), Inches(6), Inches(0.28))
    p3 = tf3.paragraphs[0]; r3 = p3.add_run()
    _set_run(r3, "Ward-Monitor · Foqal CareOS · Confidential", 9, RGBColor(0x6E, 0x82, 0x9E))
    _, tf4 = textbox(slide, Inches(11.6), Inches(7.14), Inches(1.1), Inches(0.28))
    p4 = tf4.paragraphs[0]; p4.alignment = PP_ALIGN.RIGHT
    r4 = p4.add_run(); _set_run(r4, f"{idx:02d} / {total:02d}", 9, RGBColor(0x6E, 0x82, 0x9E))


def s_appendix_image(img_path, idx, total):
    slide = add_slide()
    set_bg(slide, PAPER)
    slide.shapes.add_picture(img_path, 0, 0, width=SLIDE_W, height=SLIDE_H)
    _, tf4 = textbox(slide, Inches(11.6), Inches(7.14), Inches(1.1), Inches(0.28))
    p4 = tf4.paragraphs[0]; p4.alignment = PP_ALIGN.RIGHT
    r4 = p4.add_run(); _set_run(r4, f"{idx:02d} / {total:02d}", 9, RGBColor(0x99, 0x99, 0x99))


# ---------------------------------------------------------------- build --
CONTENT_BUILDERS = [
    s_exec_summary, s_product_overview, s_algo_architecture, s_tiers, s_limitations,
    s_flow_screens, s_override_amend, s_drug_lab, s_ops_governance,
    s_cmo_dashboard, s_cmo_baseline, s_cost_estimator, s_data_architecture,
    s_path_realdata, s_action_timeline, s_scalability, s_gating, s_risk,
]

cost_pages = []
if os.path.isdir(COST_PDF_PAGES_DIR):
    cost_pages = sorted(
        os.path.join(COST_PDF_PAGES_DIR, f) for f in os.listdir(COST_PDF_PAGES_DIR) if f.lower().endswith(".png")
    )

# +1 title, +1 ask, +appendix (divider + pages) if present
total = 1 + len(CONTENT_BUILDERS) + (1 + len(cost_pages) if cost_pages else 0) + 1

s_title()
for i, fn in enumerate(CONTENT_BUILDERS, start=1):
    fn(i, total)

next_idx = len(CONTENT_BUILDERS) + 1
if cost_pages:
    s_appendix_divider(next_idx, total)
    next_idx += 1
    for img in cost_pages:
        s_appendix_image(img, next_idx, total)
        next_idx += 1

s_ask(next_idx, total)

os.makedirs(os.path.dirname(OUT), exist_ok=True)
prs.save(OUT)
print(f"Saved {total} slides to {OUT} ({len(cost_pages)} appendix pages from cost-model PDF)")
