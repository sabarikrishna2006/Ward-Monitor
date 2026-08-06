"""
Generate EWS ML Formulation PPT for Professor Gautam - July 3 2026.
Run from common_db_main_latest/:   py notebooks/generate_presentation.py
Output: notebooks/EWS_ML_Formulation_July3_2026.pptx
"""
import os
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN

HERE   = os.path.dirname(os.path.abspath(__file__))
CHARTS = os.path.join(HERE, "charts")
OUT    = os.path.join(HERE, "EWS_ML_Formulation_July3_2026.pptx")

NAVY  = RGBColor(0x0D, 0x2B, 0x4E)
BLUE  = RGBColor(0x14, 0x5A, 0x9E)
ORNG  = RGBColor(0xE8, 0x63, 0x3A)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
DARK  = RGBColor(0x1C, 0x1C, 0x2E)
GRN   = RGBColor(0x27, 0xAE, 0x60)
AMB   = RGBColor(0xF3, 0x9C, 0x12)
RED2  = RGBColor(0xC0, 0x39, 0x2B)
LGRY  = RGBColor(0xF0, 0xF4, 0xF8)
LBLUE = RGBColor(0xA0, 0xC4, 0xE8)

SW, SH = Inches(13.33), Inches(7.5)
HH  = Inches(1.1)
OL  = Inches(0.06)
BT  = HH + OL
PAD = Inches(0.35)

prs = Presentation()
prs.slide_width  = SW
prs.slide_height = SH
BLK = prs.slide_layouts[6]


def sl():
    return prs.slides.add_slide(BLK)


def bx(s, l, t, w, h, rgb, bdr=False):
    shp = s.shapes.add_shape(1, l, t, w, h)
    shp.fill.solid()
    shp.fill.fore_color.rgb = rgb
    if bdr:
        shp.line.color.rgb = DARK
        shp.line.width = Pt(0.5)
    else:
        shp.line.color.rgb = rgb  # border matches fill = invisible
    return shp


def tx(s, text, l, t, w, h, sz=16, bold=False, italic=False,
        color=DARK, align=PP_ALIGN.LEFT, wrap=True):
    tb = s.shapes.add_textbox(l, t, w, h)
    tf = tb.text_frame
    tf.word_wrap = wrap
    for i, line in enumerate(str(text).split('\n')):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        run = p.add_run()
        run.text = line
        run.font.size   = Pt(sz)
        run.font.bold   = bold
        run.font.italic = italic
        run.font.color.rgb = color
    return tb


def ml(s, lines, l, t, w, h, sz=16, color=DARK, sp=5, blt=True):
    tb = s.shapes.add_textbox(l, t, w, h)
    tf = tb.text_frame
    tf.word_wrap = True
    for i, line in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.space_before = Pt(sp)
        run = p.add_run()
        prefix = "  " if (not blt or not line or line.startswith("  ")) else "- "
        run.text = (prefix + line) if (blt and line and not line.startswith("  ")) else line
        run.font.size = Pt(sz)
        run.font.color.rgb = color
    return tb


def hdr(s, title):
    bx(s, 0, 0, SW, HH, NAVY)
    bx(s, 0, HH, SW, OL, ORNG)
    tx(s, title, PAD, Inches(0.18), SW - PAD * 2, HH,
       sz=28, bold=True, color=WHITE)


def pic(s, fname, l, t, w, h=None):
    path = os.path.join(CHARTS, fname)
    if h:
        s.shapes.add_picture(path, l, t, w, h)
    else:
        s.shapes.add_picture(path, l, t, w)


# ═══════════════════════════════════════════════════════════════
# SLIDE 1 - Title
# ═══════════════════════════════════════════════════════════════
s1 = sl()
bx(s1, 0, 0, SW, SH, NAVY)
bx(s1, Inches(8.7), 0, SW - Inches(8.7), SH, BLUE)
bx(s1, 0, Inches(3.7), Inches(8.7), Inches(0.07), ORNG)

tx(s1, "Patient Deterioration Prediction",
   PAD, Inches(1.3), Inches(8.2), Inches(1.3), sz=38, bold=True, color=WHITE)
tx(s1, "Mathematical ML Problem Formulation",
   PAD, Inches(2.7), Inches(8.2), Inches(0.8), sz=24, color=LBLUE)
tx(s1, "EWS Ward Monitor  |  Foqal CareOS",
   PAD, Inches(3.9), Inches(8.2), Inches(0.6), sz=18, color=LBLUE)
tx(s1, "Sabari Krishna   |   July 3, 2026",
   PAD, Inches(5.1), Inches(8.2), Inches(0.5), sz=15, italic=True, color=LBLUE)
tx(s1, "NEWS2-based\nStage Transition\nPrediction",
   Inches(9.0), Inches(2.5), Inches(4.0), Inches(2.5),
   sz=22, bold=True, color=WHITE, align=PP_ALIGN.CENTER)


# ═══════════════════════════════════════════════════════════════
# SLIDE 2 - Clinical Motivation
# ═══════════════════════════════════════════════════════════════
s2 = sl()
hdr(s2, "Why ML?  The Gap NEWS2 Cannot Fill")

ml(s2, [
    "Current system: NEWS2 scores from live vitals",
    "  Threshold rule: score >=7 = Critical alert",
    "",
    "Problems with rule-based approach:",
    "  No trend - rising HR looks same as stable HR",
    "  No vital interactions (HR + low BP = worse)",
    "  No probability - just red/amber/green labels",
    "  NEWS2 AUROC: 0.67 - 0.85 (published literature)",
    "",
    "ML learns what rules cannot:",
    "  Trend: HR rising 10 bpm/h is dangerous",
    "  Output: P(deterioration in 6h) = 0.82",
    "",
    "Best-in-class:  eCARTv5  AUROC = 0.895",
    "Our target:     AUROC >= 0.80",
], PAD, BT + PAD, Inches(5.4), SH - BT - PAD * 2, sz=15, color=DARK)

pic(s2, "chart_1_patient_trajectory.png",
    Inches(5.9), BT + PAD * 0.4, Inches(7.1), Inches(5.9))


# ═══════════════════════════════════════════════════════════════
# SLIDE 3 - Prediction Task
# ═══════════════════════════════════════════════════════════════
s3 = sl()
hdr(s3, "The Prediction Task  -  One Sentence")

bx(s3, PAD, BT + PAD, SW - PAD * 2, Inches(1.35), LGRY)
tx(s3,
   "Given the last 6 hours of a CCU patient's vital signs,\n"
   "predict whether their clinical stage will worsen in the next 6 hours.",
   PAD + Inches(0.2), BT + PAD + Inches(0.12),
   SW - PAD * 2 - Inches(0.4), Inches(1.1),
   sz=22, bold=True, color=NAVY, align=PP_ALIGN.CENTER)

mt = BT + Inches(2.1)
sw3 = Inches(3.9)

bx(s3, PAD, mt, sw3, Inches(2.8), NAVY)
tx(s3, "Binary Classification", PAD + Inches(0.15), mt + Inches(0.12),
   sw3 - Inches(0.3), Inches(0.5), sz=17, bold=True, color=ORNG)
tx(s3, "CHOSEN [primary]", PAD + Inches(0.15), mt + Inches(0.65),
   sw3 - Inches(0.3), Inches(0.35), sz=14, bold=True, color=GRN)
ml(s3, [
    "Output: P(deterioration) in [0,1]",
    "Industry standard: eCARTv5, Epic DI,",
    "  NHS CIRCEWS all use this",
    "Clinicians want a single risk score",
], PAD + Inches(0.15), mt + Inches(1.05),
   sw3 - Inches(0.3), Inches(1.7), sz=13, color=WHITE, blt=False)

bx(s3, PAD + sw3 + Inches(0.25), mt, sw3, Inches(2.8), LGRY, bdr=True)
tx(s3, "Regression", PAD + sw3 + Inches(0.4), mt + Inches(0.12),
   sw3 - Inches(0.3), Inches(0.5), sz=17, bold=True, color=DARK)
tx(s3, "Not Used", PAD + sw3 + Inches(0.4), mt + Inches(0.65),
   sw3 - Inches(0.3), Inches(0.35), sz=14, italic=True, color=RED2)
ml(s3, [
    "Output: continuous NEWS2 value",
    "Stage boundaries matter more",
    "  than the exact score number",
    "Rejected: less clinically useful",
], PAD + sw3 + Inches(0.4), mt + Inches(1.05),
   sw3 - Inches(0.3), Inches(1.7), sz=13, color=DARK, blt=False)

bx(s3, PAD + sw3 * 2 + Inches(0.5), mt, sw3, Inches(2.8), LGRY, bdr=True)
tx(s3, "Survival Analysis", PAD + sw3 * 2 + Inches(0.65), mt + Inches(0.12),
   sw3 - Inches(0.3), Inches(0.5), sz=17, bold=True, color=DARK)
tx(s3, "Not Used", PAD + sw3 * 2 + Inches(0.65), mt + Inches(0.65),
   sw3 - Inches(0.3), Inches(0.35), sz=14, italic=True, color=RED2)
ml(s3, [
    "Output: time-to-event distribution",
    "Dynamic-DeepHit / DeepSurv",
    "Noisy MIMIC event timestamps",
    "Clinicians want a score, not a curve",
], PAD + sw3 * 2 + Inches(0.65), mt + Inches(1.05),
   sw3 - Inches(0.3), Inches(1.7), sz=13, color=DARK, blt=False)

tx(s3, "H = 6 hours primary  |  Also test H = 24 hours",
   PAD, BT + Inches(5.2), SW - PAD * 2, Inches(0.4),
   sz=14, bold=True, color=BLUE, align=PP_ALIGN.CENTER)


# ═══════════════════════════════════════════════════════════════
# SLIDE 4 - What Is Deterioration?
# ═══════════════════════════════════════════════════════════════
s4 = sl()
hdr(s4, "What Is 'Deterioration'?  The Label  -  NYHA Analogy")

rw   = BT + PAD * 0.6
sh4  = Inches(2.3)
sw4  = Inches(3.75)
gap4 = Inches(0.25)

bx(s4, PAD, rw, sw4, sh4, GRN)
tx(s4, "Stage 0  -  Normal",
   PAD + Inches(0.15), rw + Inches(0.1), sw4 - Inches(0.3), Inches(0.5),
   sz=17, bold=True, color=WHITE)
tx(s4, "NEWS2 Score:  0 - 4\nRoutine monitoring",
   PAD + Inches(0.15), rw + Inches(0.65), sw4 - Inches(0.3), Inches(0.65),
   sz=14, color=WHITE)
tx(s4, "NYHA Class 1-2:\nno significant limitation",
   PAD + Inches(0.15), rw + Inches(1.35), sw4 - Inches(0.3), Inches(0.85),
   sz=12, italic=True, color=WHITE)

tx(s4, "->",
   PAD + sw4 + Inches(0.02), rw + Inches(0.85), gap4 + Inches(0.1), Inches(0.55),
   sz=28, color=ORNG, align=PP_ALIGN.CENTER)

ml4 = PAD + sw4 + gap4 + Inches(0.12)
bx(s4, ml4, rw, sw4, sh4, AMB)
tx(s4, "Stage 1  -  Moderate",
   ml4 + Inches(0.15), rw + Inches(0.1), sw4 - Inches(0.3), Inches(0.5),
   sz=17, bold=True, color=WHITE)
tx(s4, "NEWS2 Score:  5 - 6\nUrgent review needed",
   ml4 + Inches(0.15), rw + Inches(0.65), sw4 - Inches(0.3), Inches(0.65),
   sz=14, color=WHITE)
tx(s4, "NYHA Class 2-3:\nmarked limitation on exertion",
   ml4 + Inches(0.15), rw + Inches(1.35), sw4 - Inches(0.3), Inches(0.85),
   sz=12, italic=True, color=WHITE)

tx(s4, "->",
   ml4 + sw4 + Inches(0.02), rw + Inches(0.85), gap4 + Inches(0.1), Inches(0.55),
   sz=28, color=ORNG, align=PP_ALIGN.CENTER)

cl4 = ml4 + sw4 + gap4 + Inches(0.12)
bx(s4, cl4, rw, sw4, sh4, RED2)
tx(s4, "Stage 2  -  Critical",
   cl4 + Inches(0.15), rw + Inches(0.1), sw4 - Inches(0.3), Inches(0.5),
   sz=17, bold=True, color=WHITE)
tx(s4, "NEWS2 Score:  >= 7\nEmergency response",
   cl4 + Inches(0.15), rw + Inches(0.65), sw4 - Inches(0.3), Inches(0.65),
   sz=14, color=WHITE)
tx(s4, "NYHA Class 3-4:\nsymptoms at rest",
   cl4 + Inches(0.15), rw + Inches(1.35), sw4 - Inches(0.3), Inches(0.85),
   sz=12, italic=True, color=WHITE)

bx(s4, PAD, rw + sh4 + Inches(0.3), SW - PAD * 2, Inches(1.25), LGRY)
tx(s4,
   "y_p(t) = 1    if    stage( NEWS2_p(t+6h) ) > stage( NEWS2_p(t) )",
   PAD + Inches(0.25), rw + sh4 + Inches(0.44),
   SW - PAD * 2 - Inches(0.5), Inches(0.52),
   sz=19, bold=True, color=NAVY)
tx(s4,
   "y_p(t) = 0    otherwise              (H = 6 hours primary  |  also test H = 24h)",
   PAD + Inches(0.25), rw + sh4 + Inches(0.97),
   SW - PAD * 2 - Inches(0.5), Inches(0.42),
   sz=14, color=DARK)

ml(s4, [
    "Stage-transition advantages: computable from vitals ALONE  (no external event records needed)",
    "Captures early warning BEFORE the crisis  |  directly matches deployed staging UI in EWS dashboard",
], PAD, rw + sh4 + Inches(1.7), SW - PAD * 2, Inches(0.8), sz=13, color=BLUE, blt=False)


# ═══════════════════════════════════════════════════════════════
# SLIDE 5 - Mathematical Formulation
# ═══════════════════════════════════════════════════════════════
s5 = sl()
hdr(s5, "Mathematical Formulation  -  The Core")

bx(s5, PAD, BT + Inches(0.25), Inches(4.6), Inches(5.8), LGRY)
tx(s5, "Notation",
   PAD + Inches(0.15), BT + Inches(0.4), Inches(4.3), Inches(0.38),
   sz=15, bold=True, color=NAVY)

syms = [
    ("p",          "Patient  (identified by hadm_id)"),
    ("t",          "Prediction time  (discrete, hourly)"),
    ("x_p(t)",     "Feature vector at time t"),
    ("X_p(t)",     "Feature matrix over  [t - W, t]"),
    ("W = 6h",     "Lookback window  (how far back we look)"),
    ("H = 6h",     "Prediction horizon  (how far ahead)"),
    ("y_p(t)",     "Binary label  -  did deterioration occur?"),
    ("f_theta",    "ML model with parameters theta"),
    ("yhat_p(t)",  "Predicted probability  in  [0, 1]"),
]
for i, (sym, defn) in enumerate(syms):
    row = BT + Inches(0.85) + i * Inches(0.54)
    tx(s5, sym, PAD + Inches(0.15), row, Inches(1.25), Inches(0.5),
       sz=12, bold=True, color=BLUE)
    tx(s5, defn, PAD + Inches(1.45), row, Inches(2.95), Inches(0.5),
       sz=12, color=DARK)

el = Inches(5.25)
ew = SW - el - PAD

tx(s5, "Prediction Task",
   el, BT + Inches(0.3), ew, Inches(0.38), sz=17, bold=True, color=NAVY)
bx(s5, el, BT + Inches(0.75), ew, Inches(1.05), NAVY)
tx(s5, "yhat_p(t)  =  f_theta( X_p(t) )   in   [0, 1]",
   el + Inches(0.2), BT + Inches(0.85), ew - Inches(0.4), Inches(0.48),
   sz=20, bold=True, color=WHITE)
tx(s5, "~  P( deterioration in (t, t+H]  |  X_p(t) )",
   el + Inches(0.2), BT + Inches(1.35), ew - Inches(0.4), Inches(0.35),
   sz=14, italic=True, color=LBLUE)

tx(s5, "Label Construction",
   el, BT + Inches(2.0), ew, Inches(0.38), sz=17, bold=True, color=NAVY)
bx(s5, el, BT + Inches(2.45), ew, Inches(1.45), LGRY)
tx(s5, "y_p(t) = 1   if   stage( NEWS2_p(t+H) ) > stage( NEWS2_p(t) )",
   el + Inches(0.2), BT + Inches(2.55), ew - Inches(0.4), Inches(0.52),
   sz=16, bold=True, color=DARK)
tx(s5, "y_p(t) = 0   otherwise",
   el + Inches(0.2), BT + Inches(3.1), ew - Inches(0.4), Inches(0.42),
   sz=16, color=DARK)
tx(s5, "  stage: Normal (0-4)  <  Moderate (5-6)  <  Critical (>=7)",
   el + Inches(0.2), BT + Inches(3.52), ew - Inches(0.4), Inches(0.3),
   sz=12, italic=True, color=BLUE)

tx(s5, "Focal Loss Function",
   el, BT + Inches(4.15), ew, Inches(0.38), sz=17, bold=True, color=NAVY)
bx(s5, el, BT + Inches(4.6), ew, Inches(0.95), LGRY)
tx(s5, "L_focal  =  -(1/N) * sum_i [ alpha * (1 - yhat_i)^gamma * log(yhat_i) ]",
   el + Inches(0.2), BT + Inches(4.7), ew - Inches(0.4), Inches(0.5),
   sz=14, bold=True, color=DARK)
tx(s5, "alpha = 0.75  (minority class weight)     gamma = 2.0  (focus on hard examples)",
   el + Inches(0.2), BT + Inches(5.25), ew - Inches(0.4), Inches(0.27),
   sz=12, italic=True, color=BLUE)
tx(s5, "Why focal loss: event rate ~10-20%  |  SMOTE worsens calibration (JAMIA 2022, n=24 studies)",
   el, BT + Inches(5.75), ew, Inches(0.3), sz=11, color=RED2)


# ═══════════════════════════════════════════════════════════════
# SLIDE 6 - Dataset Construction
# ═══════════════════════════════════════════════════════════════
s6 = sl()
hdr(s6, "Dataset Construction  -  Sliding Window over MIMIC-IV")

pic(s6, "chart_2_sliding_window.png",
    PAD, BT + Inches(0.2), Inches(7.5), Inches(3.3))
pic(s6, "chart_3_stage_transitions.png",
    Inches(8.0), BT + Inches(0.2), Inches(5.0), Inches(3.0))

bx(s6, PAD, BT + Inches(3.7), SW - PAD * 2, Inches(1.55), LGRY)
stats = [
    ("MIMIC-IV CCU stays",   "~8,000 - 15,000"),
    ("Training windows",     "~600K - 1.2M"),
    ("Event rate",           "~10 - 20%"),
    ("W = 6h  |  H = 6h",   "Stride = 1h"),
    ("Split",                "70 / 15 / 15"),
]
for i, (lbl, val) in enumerate(stats):
    cx = PAD + Inches(0.2) + i * Inches(2.56)
    tx(s6, lbl, cx, BT + Inches(3.82), Inches(2.4), Inches(0.38), sz=11, color=BLUE)
    tx(s6, val,  cx, BT + Inches(4.22), Inches(2.4), Inches(0.38), sz=14, bold=True, color=NAVY)

bx(s6, PAD, BT + Inches(5.4), SW - PAD * 2, Inches(0.5), NAVY)
tx(s6,
   "CRITICAL:  Split by subject_id (patient), NOT by window - prevents data leakage and inflated metrics",
   PAD + Inches(0.2), BT + Inches(5.48), SW - PAD * 2 - Inches(0.4), Inches(0.35),
   sz=13, bold=True, color=WHITE)


# ═══════════════════════════════════════════════════════════════
# SLIDE 7 - Feature Engineering
# ═══════════════════════════════════════════════════════════════
s7 = sl()
hdr(s7, "Feature Engineering  -  91 Features from a 6-Hour Vital Sign Window")

pic(s7, "chart_4_feature_space.png",
    PAD, BT + Inches(0.15), SW - PAD * 2, Inches(5.85))


# ═══════════════════════════════════════════════════════════════
# SLIDE 8 - Model Architecture
# ═══════════════════════════════════════════════════════════════
s8 = sl()
hdr(s8, "Model Architecture  -  XGBoost Primary, LSTM Secondary")

bx(s8, PAD, BT + Inches(0.3), Inches(5.6), Inches(5.8), LGRY)
tx(s8, "Training Pipeline",
   PAD + Inches(0.2), BT + Inches(0.5), Inches(5.2), Inches(0.38),
   sz=15, bold=True, color=NAVY)

steps = [
    ("MIMIC-IV chartevents",    "Raw vitals: HR, SpO2, RR, SBP, Temp"),
    ("Resample to 1-hour bins", "Forward-fill; max gap 4h"),
    ("Extract features",        "Rolling stats x 3 windows = 91 features"),
    ("Assign labels",           "y_p(t) = stage transition in next 6h"),
    ("Patient-level split",     "70 / 15 / 15 by subject_id"),
    ("XGBoost training",        "scale_pos_weight = N_neg / N_pos"),
    ("Evaluate",                "AUROC, AUPRC, Sensitivity@90Spec"),
]
for i, (name, detail) in enumerate(steps):
    rt = BT + Inches(1.0) + i * Inches(0.67)
    bx(s8, PAD + Inches(0.2), rt + Inches(0.05), Inches(0.44), Inches(0.44), BLUE)
    tx(s8, str(i + 1),
       PAD + Inches(0.28), rt + Inches(0.1), Inches(0.28), Inches(0.34),
       sz=12, bold=True, color=WHITE, align=PP_ALIGN.CENTER)
    tx(s8, name,   PAD + Inches(0.74), rt + Inches(0.06), Inches(2.0), Inches(0.44), sz=13, bold=True, color=DARK)
    tx(s8, detail, PAD + Inches(2.8),  rt + Inches(0.06), Inches(2.6), Inches(0.44), sz=12, italic=True, color=DARK)

rl  = Inches(6.1)
rw8 = SW - rl - PAD

tx(s8, "Why XGBoost  (Primary)",
   rl, BT + Inches(0.5), rw8, Inches(0.38), sz=16, bold=True, color=NAVY)
ml(s8, [
    "eCARTv5 (AUROC 0.895, SOTA) uses gradient boosted trees",
    "MIMIC-IV 2024 benchmark: XGBoost matches LSTM on tabular data",
    "Built-in missing value handling (critical for EHR data)",
    "SHAP feature importance - interpretable to clinicians",
], rl, BT + Inches(0.95), rw8, Inches(2.0), sz=14, color=DARK, blt=False)

tx(s8, "Why LSTM  (Secondary)",
   rl, BT + Inches(3.1), rw8, Inches(0.38), sz=16, bold=True, color=NAVY)
ml(s8, [
    "Captures temporal dependencies beyond rolling stats",
    "Input: X_p(t) in R^{6 x 20}  (timesteps x features)",
    "2-layer LSTM (128 units) -> Dense(64, ReLU) -> sigmoid",
    "Slower - establish XGBoost baseline first",
], rl, BT + Inches(3.55), rw8, Inches(1.9), sz=14, color=DARK, blt=False)

bx(s8, rl, BT + Inches(5.55), rw8, Inches(0.55), NAVY)
tx(s8,
   "Class imbalance ~10-20%  ->  focal loss  (alpha=0.75, gamma=2.0)  |  NOT SMOTE",
   rl + Inches(0.15), BT + Inches(5.63), rw8 - Inches(0.3), Inches(0.38),
   sz=13, bold=True, color=WHITE)


# ═══════════════════════════════════════════════════════════════
# SLIDE 9 - Evaluation Framework
# ═══════════════════════════════════════════════════════════════
s9 = sl()
hdr(s9, "Evaluation Framework  -  How We Measure Success")

pic(s9, "chart_5_auroc_ladder.png",
    Inches(6.9), BT + Inches(0.2), Inches(6.1), Inches(5.8))

tx(s9, "Metrics We Report",
   PAD, BT + Inches(0.5), Inches(6.6), Inches(0.38),
   sz=16, bold=True, color=NAVY)

mets = [
    ("AUROC",                   "Overall discrimination  (primary, literature-comparable)"),
    ("AUPRC",                   "Precision-recall area  (better for rare events <10%)"),
    ("Sensitivity@90%Spec",     "Catch X% of deteriorations at 10% false alarm rate"),
    ("Time-to-Detection",       "Hours before event that model first fires alarm"),
    ("Calibration (ECE)",       "P=0.7 should mean 70% actually deteriorate"),
    ("Alert burden",            "Alerts / patient / day  (alarm fatigue metric)"),
]
for i, (met, desc) in enumerate(mets):
    row = BT + Inches(1.0) + i * Inches(0.72)
    bx(s9, PAD, row, Inches(2.65), Inches(0.57), NAVY)
    tx(s9, met, PAD + Inches(0.1), row + Inches(0.08),
       Inches(2.45), Inches(0.42), sz=13, bold=True, color=WHITE)
    tx(s9, desc, Inches(2.85), row + Inches(0.08),
       Inches(3.85), Inches(0.42), sz=12, color=DARK)

bx(s9, PAD, BT + Inches(5.45), Inches(6.6), Inches(0.5), ORNG)
tx(s9, "Target:  Beat NEWS2 baseline (AUROC 0.67-0.85)  |  Aim for AUROC >= 0.80",
   PAD + Inches(0.15), BT + Inches(5.54), Inches(6.3), Inches(0.35),
   sz=13, bold=True, color=WHITE)


# ═══════════════════════════════════════════════════════════════
# SLIDE 10 - Next Steps
# ═══════════════════════════════════════════════════════════════
s10 = sl()
hdr(s10, "Next Steps  -  5-Phase Roadmap to Production ML")

phases = [
    ("Phase 1", "Now (Jul 2-3)",  GRN,  "Formulation complete. Slack post today. Professor review Thursday."),
    ("Phase 2", "Week 2 (Jul 7)", BLUE, "MIMIC-IV cohort extraction. Sliding window dataset. Label assignment."),
    ("Phase 3", "Week 3 (Jul 14)", AMB, "XGBoost baseline. SHAP feature importance. First AUROC on held-out set."),
    ("Phase 4", "Week 4 (Jul 21)", ORNG,"LSTM secondary model. Ablation study. Live dashboard ml_risk integration."),
    ("Phase 5", "Week 5 (Jul 28)", RED2,"Gautam final review. Demo on live EWS. Comparison to eCARTv5 benchmark."),
]
for i, (ph, when, col, desc) in enumerate(phases):
    rt = BT + Inches(0.4) + i * Inches(1.07)
    bx(s10, PAD, rt, Inches(1.5), Inches(0.82), col)
    tx(s10, ph,   PAD + Inches(0.08), rt + Inches(0.08), Inches(1.35), Inches(0.38),
       sz=13, bold=True, color=WHITE)
    tx(s10, when, PAD + Inches(0.08), rt + Inches(0.47), Inches(1.35), Inches(0.32),
       sz=10, color=WHITE)
    tx(s10, desc, Inches(2.1), rt + Inches(0.2), SW - Inches(2.5), Inches(0.5),
       sz=14, color=DARK)
    if i < 4:
        bx(s10, PAD + Inches(0.6), rt + Inches(0.82), Inches(0.3), Inches(0.25), col)

bx(s10, PAD, BT + Inches(5.8), SW - PAD * 2, Inches(0.48), NAVY)
tx(s10,
   "Integration: ml_risk field exists in main.py:742  -  ML model will replace the placeholder probability",
   PAD + Inches(0.2), BT + Inches(5.88), SW - PAD * 2 - Inches(0.4), Inches(0.35),
   sz=13, bold=True, color=WHITE)


# ═══════════════════════════════════════════════════════════════
# Save
# ═══════════════════════════════════════════════════════════════
prs.save(OUT)
print("[OK] Saved:", OUT)
print("[OK] 10 slides generated with all 5 charts embedded.")
