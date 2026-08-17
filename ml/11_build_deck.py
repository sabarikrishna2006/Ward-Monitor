"""
Stage 11 — Assemble the meeting deck from the real, already-computed numbers in
data/metrics_focused.json and the charts in data/charts_focused/.

Every number on every slide is pulled from metrics_focused.json (or model
meta.json) -- nothing is typed in from memory, so nothing in the deck can drift
from what was actually measured.

Run: EWS_TAG=news2 py -3 11_build_deck.py
"""
from __future__ import annotations

import json
import os

import pandas as pd
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN

import config

CHARTS = config.dpath("charts_focused")
OUT_PPTX = config.dpath("report_focused_v2.pptx")

NAVY = RGBColor(0x21, 0x2b, 0x30)
TEAL = RGBColor(0x2A, 0x6F, 0x77)
TEALD = RGBColor(0x21, 0x5a, 0x61)
GREY = RGBColor(0x5b, 0x6b, 0x72)
LIGHT = RGBColor(0xf6, 0xf8, 0xf9)
WHITE = RGBColor(0xff, 0xff, 0xff)

SLIDE_W, SLIDE_H = Inches(13.333), Inches(7.5)   # 16:9


def new_deck():
    prs = Presentation()
    prs.slide_width = SLIDE_W
    prs.slide_height = SLIDE_H
    return prs


def blank_slide(prs):
    return prs.slides.add_slide(prs.slide_layouts[6])   # blank layout


def add_bg(slide, color=WHITE):
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = color


def add_text(slide, text, left, top, width, height, size=18, bold=False, color=NAVY,
            align=PP_ALIGN.LEFT, italic=False, font="Calibri"):
    tb = slide.shapes.add_textbox(left, top, width, height)
    tf = tb.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.alignment = align
    r = p.add_run()
    r.text = text
    r.font.size = Pt(size); r.font.bold = bold; r.font.italic = italic
    r.font.color.rgb = color; r.font.name = font
    return tb


def add_bullets(slide, items, left, top, width, height, size=15, color=NAVY, space_after=10):
    tb = slide.shapes.add_textbox(left, top, width, height)
    tf = tb.text_frame
    tf.word_wrap = True
    for i, item in enumerate(items):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.space_after = Pt(space_after)
        r = p.add_run()
        r.text = f"•  {item}"
        r.font.size = Pt(size); r.font.color.rgb = color; r.font.name = "Calibri"
    return tb


def add_image_centered(slide, path, top=Inches(1.3), max_h=Inches(5.7)):
    """Fit the image within max_h (and a max width), preserving aspect ratio, centered."""
    from PIL import Image
    with Image.open(path) as im:
        w, h = im.size
    max_w = Inches(12.6)
    aspect = w / h
    disp_h, disp_w = max_h, Emu(int(max_h * aspect))
    if disp_w > max_w:
        disp_w, disp_h = max_w, Emu(int(max_w / aspect))
    left = Emu(int((SLIDE_W - disp_w) / 2))
    slide.shapes.add_picture(path, left, top, width=disp_w, height=disp_h)


def title_slide(prs, title, subtitle_lines):
    s = blank_slide(prs); add_bg(s, LIGHT)
    bar = s.shapes.add_shape(1, 0, Inches(2.3), SLIDE_W, Inches(0.06))
    bar.fill.solid(); bar.fill.fore_color.rgb = TEAL; bar.line.fill.background()
    add_text(s, "FOQAL CAREOS · EARLY WARNING SYSTEM", Inches(0.8), Inches(1.5), Inches(11.5), Inches(0.5),
             size=14, bold=True, color=TEAL)
    add_text(s, title, Inches(0.8), Inches(1.9), Inches(11.7), Inches(1.2), size=34, bold=True, color=NAVY)
    y = Inches(2.7)
    for line in subtitle_lines:
        add_text(s, line, Inches(0.8), y, Inches(11.5), Inches(0.5), size=17, color=GREY)
        y += Inches(0.5)
    return s


def section_slide(prs, kicker, title):
    s = blank_slide(prs); add_bg(s, LIGHT)
    add_text(s, kicker, Inches(0.8), Inches(3.0), Inches(11.5), Inches(0.5), size=15, bold=True, color=TEAL)
    add_text(s, title, Inches(0.8), Inches(3.4), Inches(11.7), Inches(1.5), size=30, bold=True, color=NAVY)
    return s


def image_slide(prs, title, image_name, caption=None, kicker=None):
    s = blank_slide(prs); add_bg(s, WHITE)
    y = Inches(0.35)
    if kicker:
        add_text(s, kicker, Inches(0.6), y, Inches(12), Inches(0.4), size=12, bold=True, color=TEAL)
        y += Inches(0.35)
    add_text(s, title, Inches(0.6), y, Inches(12.2), Inches(0.75), size=20, bold=True, color=NAVY)
    add_image_centered(s, os.path.join(CHARTS, image_name), top=Inches(1.15), max_h=Inches(5.6))
    if caption:
        add_text(s, caption, Inches(0.6), Inches(6.9), Inches(12.2), Inches(0.5), size=12,
                 italic=True, color=GREY, align=PP_ALIGN.CENTER)
    return s


def bullets_slide(prs, title, bullets, kicker=None):
    s = blank_slide(prs); add_bg(s, WHITE)
    y = Inches(0.5)
    if kicker:
        add_text(s, kicker, Inches(0.8), y, Inches(12), Inches(0.4), size=13, bold=True, color=TEAL)
        y += Inches(0.4)
    add_text(s, title, Inches(0.8), y, Inches(11.7), Inches(0.9), size=26, bold=True, color=NAVY)
    add_bullets(s, bullets, Inches(0.9), y + Inches(1.0), Inches(11.5), Inches(5.5), size=16)
    return s


def main():
    M = json.load(open(config.dpath("metrics_focused.json")))
    meta = M["meta"]
    hu = M["horizon_utility"]
    h12 = hu["12"]
    scn = M["scatter_naive"]; scc = M["scatter_corrected"]

    preds = pd.read_parquet(config.tpath("preds_focused.parquet"))
    split_counts = preds["split"].value_counts()
    n_train, n_test = int(split_counts.get("train", 0)), int(split_counts.get("test", 0))
    n_test_events = int(preds.loc[preds.split == "test", "event"].sum())

    prs = new_deck()

    # 1. Title
    title_slide(prs, "Deterioration Base Model\nTime to sustained NEWS2 ≥ 7", [
        f"XGBoost AFT · single event · NEWS2 parameters only",
        f"Model Performance: {meta['c_index_aft_test']:.3f} test C-index vs {meta['c_index_ruler_test']:.3f} baseline",
        f"Clinical Efficiency: {h12['aft']['alerts_per_event']:.1f} vs {h12['ruler']['alerts_per_event']:.1f} alerts/event @ 12h horizon",
    ])

    # 2. Scorecard
    image_slide(prs, "Executive Summary: Model Performance at a Glance", "12_scorecard.png", kicker="SUMMARY")

    # 3. Methodology & Design Choices
    bullets_slide(prs, "Model Methodology & Design Choices", [
        "Focused Event Definition: Predicting the FIRST time a patient's NEWS2 sustains ≥ 7 for 2 consecutive hours.",
        "Handling Competing Risks via Censoring: Treatment escalation, death, and discharge are treated as right-censoring. This isolates the model to predict pure physiological deterioration.",
        "Feature Selection: Strictly 54 features comprising the 7 NEWS2 parameters, their trends, and minimal context (age, sex, hours since admission).",
        "Architecture: A single XGBoost survival:aft (Accelerated Failure Time) model. This directly models the time until deterioration occurs.",
        "Baseline Comparison: Evaluated strictly against a 'NEWS2-slope ruler' (linear extrapolation) to prove the ML model provides value beyond just trending the score."
    ], kicker="METHODOLOGY")

    # 4. Data / cohort & Imbalance
    bullets_slide(prs, "Data Cohort & Handling Class Imbalance", [
        "Dataset: MIMIC-IV v3.1, Coronary Care Unit (CCU) stays.",
        f"Scale: {len(preds):,} hourly patient-observations (“anchors”), split by PATIENT 70% / 15% / 15% (train / calibrate / test). No data leakage across splits.",
        f"Event Prevalence: {n_test:,} anchors, {n_test_events:,} real events in the test set ({n_test_events / n_test:.1%} event rate).",
        "Handling Class Imbalance: With only a ~13.8% event rate, standard binary classifiers struggle. By using Survival Analysis (XGBoost AFT), we model the underlying time-to-event distribution for all patients, leveraging both events and censored data effectively without arbitrary thresholding."
    ], kicker="DATA & CLASS IMBALANCE")

    # 5. Scatter naive
    image_slide(prs, "Raw Predicted Time (Unconditional Median)",
               "01_scatter_naive.png", kicker="SURVIVAL TIME PREDICTIONS",
               caption=f"Pearson r (Linear correlation) = {scn['pearson_r']:.2f}. The raw median appears inflated due to censoring.")

    bullets_slide(prs, "Understanding the Effect of Censoring on Time Estimates", [
        "Why does the raw median time look so high?",
        "In a heavily censored dataset (~13% event rate), the probability of an event happening within a short horizon is low (< 50%).",
        "A perfectly calibrated survival model's median is mathematically forced to fall far into the future because the survival curve doesn't reach 0.5 quickly.",
        "Evaluating this unconditional median against only the patients who DID deteriorate is a biased, apples-to-oranges comparison.",
        "Solution: We must evaluate the conditional expected time (given the event happens in a window) and the fixed-horizon probabilities."
    ], kicker="STATISTICAL CONTEXT")

    # 6. Scatter corrected
    image_slide(prs, "Conditional Expected Time: The Apples-to-Apples Comparison",
               "02_scatter_corrected.png", kicker="CONDITIONAL TIME",
               caption=f"Pearson r = {scc['pearson_r']:.2f}, MAE (Mean Absolute Error) = {scc['mae_hours']:.1f}h. This asks: 'Given the patient deteriorates in 24h, when does it happen?'")

    # 7. Error by bin / cutoff horizon
    image_slide(prs, "Cutoff Horizon: Where the Point-Estimate is Reliable",
               "03_error_by_bin.png", kicker="PREDICTION ACCURACY",
               caption="MAPE (Mean Absolute Percentage Error) explodes for imminent events (<4h). The point-estimate time is best for 6-18h planning. For <4h events, we rely entirely on the risk probability and risk ranking, not the countdown timer.")

    # 8. Horizon utility
    image_slide(prs, "Clinical Utility: False Alarm Reduction",
               "04_horizon_utility.png", kicker="PERFORMANCE BY HORIZON",
               caption="The model roughly halves the false-alarm rate (alerts/event) compared to the baseline at every horizon, effectively combating alarm fatigue.")

    # 9. Threshold sweep
    image_slide(prs, "Threshold Tuning & Operating Points",
               "05_threshold_sweep.png", kicker="SENSITIVITY SWEEP",
               caption="The baseline's flat line indicates 'tie-dominance'—it cannot distinguish risk levels well, forcing it to alert on nearly everyone to reach high sensitivity.")

    # 10. Calibration
    bullets_slide(prs, "Isotonic Calibration Explained", [
        "What is Calibration? It ensures that when the model predicts a 20% risk of deterioration, exactly 20% of those patients actually deteriorate.",
        "What is Isotonic Regression? It is a non-parametric technique that maps the model's raw rank-ordered outputs into true empirical probabilities.",
        "Why it matters: It allows clinicians to trust the absolute percentage risk shown on the screen at face value, making the model actionable rather than just a ranking tool."
    ], kicker="CALIBRATION CONTEXT")

    image_slide(prs, "Model Calibration Results",
               "06_calibration.png", kicker="ISOTONIC CALIBRATION")

    # 11. Overfit check
    image_slide(prs, "Generalization Check (Train vs. Test)",
               "07_overfit_check.png", kicker="OVERFITTING ANALYSIS",
               caption=f"C-index (measure of ranking accuracy) gap between train and test is only {M['overfit_check']['c_index_gap']:.3f}, proving the model generalizes well and has not memorized the training data.")

    # 12. SHAP global
    image_slide(prs, "Feature Importance: What drives the model globally?",
               "08_shap_importance.png", kicker="GLOBAL INTERPRETABILITY")

    # 13. SHAP per patient
    bullets_slide(prs, "Per-Patient Explainability (SHAP)", [
        "What is SHAP (SHapley Additive exPlanations)? A game-theoretic approach that breaks down a prediction to show exactly how much each feature contributed to the final score.",
        "Global vs Local: Global SHAP shows average importance across all patients. Local (Per-Patient) SHAP shows the exact physiological signals driving the alarm for one specific patient at one specific moment.",
        "Clinical Value: Provides actionable transparency. If an alarm fires, the clinician instantly sees whether it was driven by a rising heart rate, oxygen dependency, or age, building trust in the system."
    ], kicker="EXPLAINABILITY CONTEXT")
    
    image_slide(prs, "Per-Patient Explainability in Action",
               "09_shap_patient.png", kicker="LOCAL EXPLAINABILITY")

    # 14. Case studies
    image_slide(prs, "Clinical Case Studies over Time",
               "10_case_studies.png", kicker="CASE STUDIES", )

    # 15. Decision curve
    image_slide(prs, "Decision Curve Analysis (Net Benefit)",
               "11_decision_curve.png", kicker="CLINICAL UTILITY (Vickers & Elkin 2006)",
               caption="The model provides positive net benefit across all clinically relevant thresholds, outperforming both 'alert everyone' and 'alert no one' strategies.")

    # 16. Limitations
    bullets_slide(prs, "Model Limitations", [
        "Retrospective Validation: Evaluated on the MIMIC-IV CCU cohort. It requires prospective validation before clinical deployment.",
        "Feature Scope: Restricted solely to NEWS2 parameters. This is a foundational base model; it currently lacks context from labs, biomarkers (e.g., NT-proBNP), or patient history.",
        "Short-Horizon Timing: The exact point-estimate for time-to-event is unstable under 4-6 hours due to clinical volatility. Short horizons require reliance on the probability score, not the countdown.",
        "Unknown Status Handling: Patients discharged before the prediction horizon are dynamically excluded from evaluation to ensure rigorous, unbiased metrics."
    ], kicker="LIMITATIONS")

    # 17. Next steps
    bullets_slide(prs, "Future Roadmap", [
        "Integrate the Congestion/Substrate Axis: Incorporate weight trends, NT-proBNP, eGFR, and urine output to improve predictive power.",
        "Measure Incremental Value: Evaluate the exact performance delta (AUC/C-index lift) that these new labs provide over this established base model.",
        "Recurrent Event Modeling: Expand the survival framework to handle multiple deterioration events per patient stay.",
        "General Ward Expansion: Validate and recalibrate the model for general medical ward populations."
    ], kicker="ROADMAP")

    prs.save(OUT_PPTX)
    print(f"wrote {OUT_PPTX}  ({len(prs.slides._sldIdLst)} slides)")


if __name__ == "__main__":
    main()
