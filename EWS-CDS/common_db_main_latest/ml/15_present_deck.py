"""
Stage 15 — the presentation deck: discrete-time hazard deterioration model,
built for a live ML showcase. Every metric and every plot ships with its own
in-slide definition/formula/interpretation (standing rule: never hand over a
number without explaining it first) so the deck is self-contained without
verbal narration.

Excludes the labs/congestion retrain from the narrative per explicit direction
(it showed no significant improvement -- see 13_focused_train_labs.py /
14_ordinal_train_labs.py and metrics_focused.json if it needs to be referenced
live in Q&A; it is not part of this deck's story).

Reuses 11_build_deck.py's slide-building helpers (title_slide, section_slide,
image_slide, bullets_slide, add_text, add_bullets, add_image_centered) rather
than reimplementing them. Adds one new helper, add_native_table(), for the
three tables rebuilt as real PowerPoint tables (not embedded images) so the
labs column can be cleanly omitted and so text stays crisp at any zoom level.

Run: EWS_TAG=news2 py -3 15_present_deck.py
"""
from __future__ import annotations

import importlib
import json
import os

from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN

import config

_deck = importlib.import_module("11_build_deck")
new_deck, blank_slide, add_bg = _deck.new_deck, _deck.blank_slide, _deck.add_bg
add_text, add_bullets, add_image_centered = _deck.add_text, _deck.add_bullets, _deck.add_image_centered
title_slide, section_slide = _deck.title_slide, _deck.section_slide
image_slide, bullets_slide = _deck.image_slide, _deck.bullets_slide
NAVY, TEAL, TEALD, GREY, LIGHT, WHITE = _deck.NAVY, _deck.TEAL, _deck.TEALD, _deck.GREY, _deck.LIGHT, _deck.WHITE
SLIDE_W, SLIDE_H = _deck.SLIDE_W, _deck.SLIDE_H
CHARTS = config.dpath("charts_focused")
OUT_PPTX = config.dpath("presentation_deck.pptx")

RED = RGBColor(0xB4, 0x45, 0x3C)
GREEN = RGBColor(0x2E, 0x7D, 0x57)


def add_native_table(slide, col_labels, rows_data, left, top, width, height,
                     font_size=12.5, header_font_size=13, col_widths=None):
    n_rows, n_cols = len(rows_data) + 1, len(col_labels)
    shape = slide.shapes.add_table(n_rows, n_cols, left, top, width, height)
    table = shape.table
    if col_widths:
        for j, w in enumerate(col_widths):
            table.columns[j].width = w
    for j, label in enumerate(col_labels):
        cell = table.cell(0, j)
        cell.text = str(label)
        cell.fill.solid(); cell.fill.fore_color.rgb = TEALD
        p = cell.text_frame.paragraphs[0]; p.alignment = PP_ALIGN.CENTER
        for r in p.runs:
            r.font.size = Pt(header_font_size); r.font.bold = True; r.font.color.rgb = WHITE
    for i, row in enumerate(rows_data, start=1):
        for j, val in enumerate(row):
            cell = table.cell(i, j)
            cell.text = str(val)
            p = cell.text_frame.paragraphs[0]; p.alignment = PP_ALIGN.CENTER
            for r in p.runs:
                r.font.size = Pt(font_size); r.font.color.rgb = NAVY
    return table


def wide_title_slide(prs, title, subtitle_lines):
    """title_slide() clone with more vertical room for a 2-line title -- the
    shared helper's fixed y-offsets (bar at 2.3in, subtitle at 2.7in) overlap
    a title this long; not editing 11_build_deck.py since it's shared with the
    historical AFT-only deck."""
    s = blank_slide(prs); add_bg(s, LIGHT)
    bar = s.shapes.add_shape(1, 0, Inches(3.05), SLIDE_W, Inches(0.06))
    bar.fill.solid(); bar.fill.fore_color.rgb = TEAL; bar.line.fill.background()
    add_text(s, "FOQAL CAREOS · EARLY WARNING SYSTEM", Inches(0.8), Inches(1.3), Inches(11.5), Inches(0.5),
             size=14, bold=True, color=TEAL)
    add_text(s, title, Inches(0.8), Inches(1.7), Inches(11.7), Inches(1.3), size=32, bold=True, color=NAVY)
    y = Inches(3.35)
    for line in subtitle_lines:
        add_text(s, line, Inches(0.8), y, Inches(11.7), Inches(0.5), size=16, color=GREY)
        y += Inches(0.5)
    return s


def table_slide(prs, title, col_labels, rows_data, kicker=None, footnote=None,
                col_widths=None, table_top=Inches(1.5), table_height=Inches(4.2)):
    s = blank_slide(prs); add_bg(s, WHITE)
    y = Inches(0.4)
    if kicker:
        add_text(s, kicker, Inches(0.7), y, Inches(12), Inches(0.4), size=12.5, bold=True, color=TEAL)
        y += Inches(0.4)
    add_text(s, title, Inches(0.7), y, Inches(12.3), Inches(0.9), size=21, bold=True, color=NAVY)
    table_left = Inches(0.7)
    table_width = SLIDE_W - Inches(1.4)
    add_native_table(s, col_labels, rows_data, table_left, table_top, table_width, table_height,
                     col_widths=col_widths)
    if footnote:
        add_text(s, footnote, Inches(0.7), Inches(6.85), Inches(12), Inches(0.5), size=10.5,
                 italic=True, color=GREY)
    return s


def main():
    M = json.load(open(config.dpath("metrics_focused.json")))
    meta, meta_aft = M["meta"], M["meta_aft"]
    hu = M["horizon_utility"]; h12, h24 = hu["12"], hu["24"]
    aep = M["alarm_episode_comparison"]; aep12 = aep["12"]
    cal = M["calibration"]; ofc = M["overfit_check"]
    scc = M["scatter_corrected"]; stage0 = M["limitations"]["stage0_verification"]

    prs = new_deck()

    # ══════════════════════════════════════════════════════════ 1. TITLE
    wide_title_slide(prs, "Deterioration Early-Warning Model\nDiscrete-Time Hazard Survival Model — v1", [
        "CCU (Coronary Care Unit) · MIMIC-IV v3.1 · Sustained NEWS2 ≥ 7",
        f"Test C-index {meta['c_index_hazard_test']:.3f} vs {meta['c_index_ruler_test']:.3f} floor  ·  "
        f"Lift {h12['lift_model']:.2f}x @ 12h  ·  {aep12['episode_alarms_per_patient_hour']:.2f} alarms/patient-hour",
    ])

    # ══════════════════════════════════════════════════════════ 2. AGENDA
    bullets_slide(prs, "What This Covers", [
        "The problem: what we predict, on what data, and why",
        "Why time-to-event framing, and why discrete-time hazard specifically (vs. AFT, vs. Cox)",
        "How the model is actually trained — the masking mechanism, step by step",
        "Every metric defined BEFORE it's shown: C-index, ROC/AUC, PR/AUPRC, calibration, thresholds",
        "Results: discrimination, calibration, clinical utility, case studies",
        "The false-positive story — what's real, what was miscounted, and the fix",
        "Honest limitations, stated plainly — not implied away",
    ], kicker="AGENDA")

    # ══════════════════════════════════════════════════════════ 3. PROBLEM DEFINITION
    bullets_slide(prs, "The Problem We're Predicting", [
        "Event: a patient's NEWS2 score (a validated 7-parameter acute-illness composite: "
        "heart rate, resp. rate, SpO2, BP, temperature, consciousness, supplemental O2) "
        "sustains ≥7 for 2 consecutive hours — a recognized deterioration threshold.",
        "Cohort: Coronary Care Unit (CCU) stays, MIMIC-IV v3.1 — a cardiac-monitored, "
        "already-ICU-level population. CVICU (surgical) excluded — different population, different risk drivers.",
        "Prediction task: at every hour of a stay (an \"anchor\"), using only vitals/NEWS2 history "
        "up to that hour, estimate the probability this patient crosses NEWS2≥7 within the next "
        "2 / 4 / 6 / 9 / 12 / 18 / 24 hours.",
        "Competing outcomes handled as censoring, not dropped: discharge and death before the "
        "event both correctly remove a patient from the risk set at that point (standard survival "
        "analysis) — they are not treated as \"confirmed stable forever.\"",
    ], kicker="PROBLEM DEFINITION")

    # ══════════════════════════════════════════════════════════ 4. DATA / COHORT (native table)
    table_slide(prs, "Data & Cohort — Row-Level AND Patient-Level N",
        ["Description", "Value"],
        [[r[0], r[1]] for r in M["table1_cohort"]["rows"][:9]],
        kicker="DATA",
        footnote="Row count alone overstates independent evidence — a stable patient contributes dozens of "
                 "correlated hourly snapshots. Always the patient-level N is quoted alongside it.",
        col_widths=[Inches(8.0), Inches(3.9)])

    # ══════════════════════════════════════════════════════════ 5. WHY TIME-TO-EVENT
    bullets_slide(prs, "Why Time-to-Event, Not a Plain Classifier", [
        "A fixed-horizon binary classifier (\"will this patient deteriorate in the next 12h, yes/no\") "
        "answers only ONE horizon, and must either drop every patient discharged before 12h "
        "(losing information) or wrongly label them \"stable\" (a real bug we specifically avoid — see Q3 later).",
        "Survival/hazard framing uses every patient, including those discharged early, via CENSORING: "
        "their contribution stops exactly when their true outcome becomes unknown, not before.",
        "A single time-to-event model naturally answers ALL horizons at once, from one fitted model, "
        "as a full risk curve — not seven independently-fit, possibly-inconsistent classifiers.",
    ], kicker="MODELING FRAMEWORK")

    # ══════════════════════════════════════════════════════════ 6. THREE APPROACHES COMPARED
    bullets_slide(prs, "Three Survival Approaches Considered", [
        "AFT (Accelerated Failure Time) — models raw time-to-event directly via a fitted parametric "
        "distribution (we used logistic). Produces one median time. KNOWN FAILURE MODE: when event "
        "probability is under 50% (true here for most anchors), a perfectly-calibrated median is "
        "mathematically forced PAST the horizon — this is why the old AFT deck's time-scatter looked broken.",
        "Cox Proportional Hazards — the classical semi-parametric survival model. Assumes hazard "
        "ratios stay CONSTANT over time and is typically linear in covariates. With 55+ correlated, "
        "non-linear rolling-window vital-sign features, both assumptions are questionable here — "
        "not benchmarked this round because it is very unlikely to beat a tree-based learner on this feature set.",
        "Discrete-time hazard (chosen) — breaks time into intervals, trains one flexible XGBoost "
        "classifier per interval, masks (not discards) censored patients, and reconstructs a full "
        "survival curve as a running product — monotonic BY CONSTRUCTION, no distributional "
        "assumption, and it is exactly the framing Prof. Shroff's own paper (arXiv:1903.09795) "
        "describes for censored ordinal regression.",
    ], kicker="MODEL FAMILY COMPARISON")

    # ══════════════════════════════════════════════════════════ 7. HOW IT WORKS — DIAGRAM
    image_slide(prs, "How The Model Is Actually Trained", "00_ordinal_concept_diagram.png",
               kicker="APPROACH — STEP BY STEP",
               caption="Each of the 7 intervals gets its OWN binary classifier, trained only on patients "
                       "still validly \"at risk\" for that interval — censored patients are masked out from "
                       "the point their true outcome becomes unknowable, not discarded entirely or mislabeled.")

    # ══════════════════════════════════════════════════════════ 8. HOW IT WORKS — RECONSTRUCTION
    bullets_slide(prs, "Reconstructing the Risk Curve — the Exact Math", [
        "Step 1 — per-interval hazard: each of the 7 XGBoost classifiers outputs "
        "h_j = P(fail in interval j | still at risk at its start). Isotonic-calibrated so \"30%\" "
        "really means 30% observed frequency in held-out data.",
        "Step 2 — survival product: S(0)=1;  S(interval j) = S(interval j-1) × (1 − h_j). "
        "A running product of terms in [0,1] is NON-INCREASING by construction — no post-hoc "
        "monotonicity patch needed, unlike independently-fit per-horizon classifiers.",
        "Step 3 — primary output: P(deteriorate within h) = 1 − S(h), for h ∈ {2,4,6,9,12,18,24}. "
        "This calibrated probability profile IS the model's headline answer.",
        "Step 4 — secondary output only: E[T | T≤24h], a probability-weighted average of interval "
        "midpoints — shown for clinical color (\"if it happens, roughly when\"), never as evidence "
        "of accuracy. See the \"secondary output\" section later for why this number is intentionally "
        "de-emphasized.",
    ], kicker="APPROACH — THE MATH")

    # ══════════════════════════════════════════════════════════ 9. WHAT THE MODEL OUTPUTS
    bullets_slide(prs, "What Exactly Does The Model Output?", [
        "PRIMARY: a discretized cumulative probability curve — P(deteriorate by h) at each of 7 "
        "horizons, calibrated (isotonic-regressed against real held-out outcomes).",
        "Also derivable: the single most-likely interval, argmax_j P(fail in interval j) — a "
        "human-readable one-line summary of the same curve.",
        "SECONDARY: E[T | T≤24h], a conditional expected time — reported explicitly as secondary, "
        "clinical-color-only context, never as the accuracy evidence.",
        "The alert trigger is the calibrated probability at a chosen operating horizon "
        "(e.g. P(T≤12h) crossing a threshold) — the time estimate never drives an alert.",
    ], kicker="MODEL OUTPUT")

    # ══════════════════════════════════════════════════════════ 10. METRICS I — DISCRIMINATION
    bullets_slide(prs, "Metrics Explained (1/3) — Discrimination: Can It Rank Risk?", [
        "C-INDEX (concordance): take every pair of patients where we can actually tell who failed "
        "first (accounting for censoring); C-index = fraction of those pairs the model ranks "
        "correctly. 0.5 = coin flip, 1.0 = perfect. Ours: test C-index "
        f"{meta['c_index_hazard_test']:.3f} (95% CI [{meta['c_index_hazard_test_ci'][0]:.3f}, "
        f"{meta['c_index_hazard_test_ci'][1]:.3f}]) vs a {meta['c_index_ruler_test']:.3f} floor "
        "(linear NEWS2-trend extrapolation).",
        "ROC / AUC: plots True-Positive-Rate vs False-Positive-Rate across every possible threshold. "
        "AUC = probability a random true-event patient is scored riskier than a random non-event "
        "patient. Threshold-independent, but can look artificially good under rare events, because a "
        "huge true-negative pool inflates specificity.",
        "PR curve / AUPRC: plots Precision (PPV) vs Recall (sensitivity) across thresholds. AUPRC "
        f"does NOT get inflated by a large true-negative pool — the honest metric under our "
        f"~11-23%-base-rate event rate. Ours: {h12['auprc_model']:.3f} @ 12h vs ruler "
        f"{h12['auprc_ruler']:.3f}.",
    ], kicker="METRICS DEFINED")

    # ══════════════════════════════════════════════════════════ 11. METRICS II — CALIBRATION
    bullets_slide(prs, "Metrics Explained (2/3) — Calibration: Can You Trust The Number?", [
        "RELIABILITY DIAGRAM: bin predictions into deciles; x = mean predicted probability in that "
        "bin, y = the ACTUAL observed event fraction in that bin. The diagonal is \"perfectly "
        "honest\"; below it = overconfident.",
        f"ECE (Expected Calibration Error): mean |predicted − observed| across bins, one number "
        f"summarizing the whole diagram. Ours: {cal['p_raw_12h']['ece']:.3f} raw → "
        f"{cal['p_calibrated_12h']['ece']:.3f} after isotonic calibration (lower = better; 0 = perfect).",
        f"CALIBRATION SLOPE/INTERCEPT: fit logistic regression of the true outcome on "
        f"logit(predicted probability). Slope=1, intercept=0 is perfect; slope<1 = systematically "
        f"overconfident. Ours: slope={cal['calibration_slope']:.2f}, intercept={cal['calibration_intercept']:.2f}.",
        "BRIER SCORE: mean squared error between predicted probability and the actual 0/1 outcome. "
        "Combines calibration AND discrimination into one number; 0 = perfect, lower is better "
        f"(ours: {h12['brier_model']:.3f} @ 12h — reported per-horizon in the results table).",
    ], kicker="METRICS DEFINED")

    # ══════════════════════════════════════════════════════════ 12. METRICS III — THRESHOLDS
    bullets_slide(prs, "Metrics Explained (3/3) — Thresholds Are a CHOICE, Not a Model Property", [
        "Sensitivity (recall) = TP/(TP+FN): fraction of TRUE events successfully caught.",
        "Specificity = TN/(TN+FP): fraction of true negatives correctly left un-alarmed.",
        "PPV (precision) = TP/(TP+FP): of everyone alarmed, the fraction who were real events.",
        "THE KEY POINT: sensitivity, specificity, and PPV ALL move together as you slide the alert "
        "threshold along the model's continuous probability output — raise the threshold and PPV/"
        "specificity rise while sensitivity FALLS; lower it and the opposite happens. There is no "
        "single \"correct\" threshold, only a clinical policy tradeoff — which is why we show the "
        "FULL sweep curve (next section), not one cherry-picked point.",
        "Lift = PPV / base rate: how many times more informative an alert is than chance. 1.0x = "
        "useless; ceiling = 1/base_rate. This is our headline false-positive metric, not raw alert counts.",
        "\"Known-status\" horizon rule: a patient discharged before horizon h has an UNKNOWN outcome "
        "at h, not a confirmed negative — such rows are dropped from that horizon's evaluation "
        "entirely (the % dropped is reported alongside every horizon's numbers, never hidden).",
    ], kicker="METRICS DEFINED")

    # ══════════════════════════════════════════════════════════ 13-16. RESULTS
    image_slide(prs, "Primary Results — Utility at Every Horizon", "01_horizon_utility.png",
               kicker="RESULTS",
               caption="Known-status anchors only, 80%-sensitivity reference operating point. "
                       "AUC/AUPRC/PPV/Lift all beat the NEWS2-slope ruler at every horizon.")
    image_slide(prs, "Threshold Tuning — the Sensitivity/Alarm Tradeoff", "02_threshold_sweep.png",
               kicker="RESULTS",
               caption="This is the full tradeoff underlying every PPV/sensitivity number quoted anywhere "
                       "in this deck — moving right always costs more false alarms per true catch.")
    image_slide(prs, "Is The Risk Probability Trustworthy?", "03_calibration.png",
               kicker="RESULTS",
               caption="Reliability curves before/after isotonic calibration, plus ECE and calibration "
                       "slope/intercept (both defined on the metrics slide above).")
    image_slide(prs, "Generalization Check — Train vs Test", "04_overfit_check.png",
               kicker="RESULTS",
               caption=f"C-index gap = {ofc['c_index_gap']:.3f} (small ⇒ the model generalized, not memorized).")

    # ══════════════════════════════════════════════════════════ 17. FALSE POSITIVE STORY
    bullets_slide(prs, "The False-Positive Story — What Was Actually Being Counted", [
        "The naive count treats every HOURLY re-alert on the same rising patient as a separate false "
        "positive. A patient trending upward for 8 straight hours was counted as 8 alerts, not 1.",
        f"FIX — alarm-episode deduplication: collapse each patient's consecutive run of alerts into "
        f"ONE episode before computing alarm burden. This is the real-world quantity — what a nurse "
        f"actually experiences, one page per rising episode, not one per hour.",
        f"Result: episode-level alarm rate is FLAT at ~{aep12['episode_alarms_per_patient_hour']:.2f} "
        f"alarms/patient-hour across ALL 7 horizons (vs. the anchor-level rate that roughly doubles "
        f"from 2h to 24h, {aep['2']['anchor_alarms_per_patient_hour']:.2f} → "
        f"{aep['24']['anchor_alarms_per_patient_hour']:.2f}).",
        f"That ~{aep12['episode_alarms_per_patient_hour']:.2f}/patient-hour figure sits right next to "
        f"Hyland et al. 2020's published 0.05 alarms/patient-hour benchmark (Nature Medicine) — a "
        f"genuinely competitive number once counted correctly.",
        f"A caught patient personally generates {aep12['mean_episodes_per_caught_patient']:.1f} "
        f"separate alarm episodes on average before their event — not the 4-5 the anchor-level count implied.",
    ], kicker="FALSE POSITIVES — THE FIX")
    image_slide(prs, "Real Alarm Burden vs Naive Hourly Counting", "01b_alarm_episode_comparison.png",
               kicker="FALSE POSITIVES — THE DATA")

    # ══════════════════════════════════════════════════════════ 18. BENCHMARK CONTEXT (native table)
    bench_rows = [[r[0], r[1], r[2], r[3], r[4]] for r in M["benchmark_context"]["ours"]]
    for b in M["benchmark_context"]["external"]:
        ppv_str = f"{b['ppv']:.3f}" if b.get("ppv") is not None else b.get("ppv_range", "—")
        bench_rows.append([b["system"], b["outcome"], ppv_str, "—", b["alarm_burden"]])
    table_slide(prs, "Is Our False-Positive Rate Actually Abnormal? — PPV In Context",
        ["System", "Outcome", "PPV", "Lift", "Alarm burden"], bench_rows,
        kicker="FALSE POSITIVES — INDUSTRY CONTEXT",
        footnote="eCARTv2 predicts an unambiguously INDEPENDENT outcome (ICU transfer/death) and still has "
                 "WORSE PPV (0.082) than ours — evidence the rare-event base rate sets this band for everyone, "
                 "not our label choice. Sources: FALSE_POSITIVE_COMPARISON_and_professor_reply.md.",
        col_widths=[Inches(2.0), Inches(3.9), Inches(1.4), Inches(1.4), Inches(2.9)])

    # ══════════════════════════════════════════════════════════ 19-20. DECISION CURVE, CASE STUDIES
    image_slide(prs, "Decision Curve Analysis — Clinical Net Benefit", "05_decision_curve.png",
               kicker="CLINICAL UTILITY",
               caption="Net benefit = value of true alerts minus cost of false alerts, weighted by how many "
                       "false alerts you'd tolerate per true catch at that threshold. Above BOTH \"alert "
                       "everyone\" and \"alert no one\" means the model adds real clinical value there.")
    image_slide(prs, "Real Patient Trajectories", "06_case_studies.png",
               kicker="CASE STUDIES",
               caption="Grey = actual NEWS2 score; teal = calibrated P(deteriorate ≤h); amber dashed = the "
                       "alert threshold; the crossing point is when this patient would have triggered an alarm.")

    # ══════════════════════════════════════════════════════════ 21. MODEL COMPARISON (native table, 3 cols)
    mc = M["model_comparison"]["columns"]
    hz, aft, ruler = mc["Discrete-time hazard\n(v1, PRIMARY)"], mc["AFT\n(prior iteration)"], mc["NEWS2-slope ruler\n(floor)"]
    comp_rows = [
        ["C-index (test)", f"{hz['c_index']:.3f}", f"{aft['c_index']:.3f}", f"{ruler['c_index']:.3f}"],
        ["AUC @ 12h", f"{hz['auc']:.3f}", f"{aft['auc']:.3f}", f"{ruler['auc']:.3f}"],
        ["AUPRC @ 12h", f"{hz['auprc']:.3f}", f"{aft['auprc']:.3f}", f"{ruler['auprc']:.3f}"],
        ["PPV @ 12h (80% sens.)", f"{hz['ppv']:.2f}", f"{aft['ppv']:.2f}", f"{ruler['ppv']:.2f}"],
        ["Alerts/event @ 12h", f"{hz['alerts_per_event']:.1f}", f"{aft['alerts_per_event']:.1f}", f"{ruler['alerts_per_event']:.1f}"],
        ["Lift @ 12h", f"{hz['lift']:.2f}x", f"{aft['lift']:.2f}x", f"{ruler['lift']:.2f}x"],
    ]
    table_slide(prs, "Model Comparison — Identical Event / Split / Horizons",
        ["Metric", "Discrete-time hazard (PRIMARY)", "AFT (prior iteration)", "NEWS2-slope ruler (floor)"],
        comp_rows, kicker="RESULTS — MODEL COMPARISON",
        footnote="Hazard model and AFT perform almost identically — expected: both are flexible learners on "
                 "the SAME features and SAME label, so model family alone has little headroom left to exploit. "
                 "Both decisively beat the ruler. See 'Why the small gap' on the limitations slide.",
        col_widths=[Inches(3.0), Inches(3.0), Inches(2.9), Inches(2.9)])

    # ══════════════════════════════════════════════════════════ 22. SUBGROUPS
    image_slide(prs, "Subgroup Check — DCM Flag and Age Band", "09_subgroup_breakdown.png",
               kicker="RESULTS — SUBGROUPS",
               caption="Same discrimination (AUC) and calibration (Brier) recomputed within each subgroup, "
                       "to check the model isn't silently failing a group it looks fine on average over.")

    # ══════════════════════════════════════════════════════════ 23-24. SECONDARY OUTPUT
    bullets_slide(prs, "Secondary Output — Why The Predicted-Time Correlation Looks Weak", [
        f"Actual-vs-predicted TIME correlation: Pearson r = {scc['pearson_r']:.2f}, "
        f"Spearman = {scc['spearman_r']:.2f} — genuinely weak, reported exactly as measured.",
        "THIS IS NOT the wrong comparison, and not a misalignment bug: the predicted time "
        "(a probability-weighted average over only 7 interval midpoints) has ~8.5x LESS variance "
        "than the actual event time, which spans the full 0-24h range. A low-variance estimator "
        "cannot correlate well with a high-variance target, no matter how good the underlying "
        "probabilities are.",
        "The ranking direction IS correct: grouped by actual-time bucket, the mean predicted time "
        "increases monotonically bucket-to-bucket — the model knows relative ordering, it just "
        "can't pinpoint the exact hour from vitals trend alone.",
        "This is exactly why the calibrated PROBABILITY output (shown earlier) is the primary "
        "evidence of accuracy, and this time estimate is secondary, clinical color only — never "
        "the headline, and never the alert trigger.",
    ], kicker="SECONDARY OUTPUT")
    image_slide(prs, "Actual vs. Predicted Time (Secondary)", "10_scatter_corrected.png",
               kicker="SECONDARY OUTPUT")
    image_slide(prs, "Where The Time Estimate Decays", "11_error_by_bin.png",
               kicker="SECONDARY OUTPUT",
               caption="Error grows for very fast (<4h) and very slow (>18h) events — expected, not hidden.")

    # ══════════════════════════════════════════════════════════ 25. AFT HISTORICAL REFERENCE
    image_slide(prs, "Historical Reference — Why We Moved Off The AFT Median", "12_scatter_naive_aft.png",
               kicker="HISTORICAL CONTEXT, NOT THIS MODEL'S RESULT",
               caption="The prior AFT iteration's raw median is mathematically forced past the horizon "
                       "whenever event probability is under 50% — the exact failure mode the discrete-time "
                       "hazard reframing removes by construction.")

    # ══════════════════════════════════════════════════════════ 26. LIMITATIONS (native bullets, labs omitted)
    # split across 2 slides -- 7 substantial bullets on one slide overflows past the
    # slide's bottom edge (bullets_slide doesn't auto-shrink text to fit).
    limitation_bullets = [t for t in M["limitations"]["text"] if "Labs/congestion" not in t]
    mid = (len(limitation_bullets) + 1) // 2
    bullets_slide(prs, "Limitations (1/2) — Stated Plainly, Not Implied Away",
                 limitation_bullets[:mid], kicker="LIMITATIONS")
    bullets_slide(prs, "Limitations (2/2) — Stated Plainly, Not Implied Away",
                 limitation_bullets[mid:], kicker="LIMITATIONS")

    # ══════════════════════════════════════════════════════════ 27. PROFESSOR'S 5 QUESTIONS
    bullets_slide(prs, "The Five Questions — Answered From Live Model Output", [
        "Q1 (What does it output?) — A calibrated probability curve P(deteriorate ≤h) at 7 horizons "
        "(primary); a secondary conditional time estimate, heavily caveated, never the alert trigger.",
        "Q2 (Threshold behavior?) — Full sensitivity/alarms tradeoff curve shown, not one cherry-picked "
        "number; 80% used as a reference operating point, not the only option.",
        "Q3 (Horizon semantics?) — known_status.py's censoring-correct rule, unchanged and reused: "
        "discharged-before-h patients are DROPPED from that horizon's evaluation, not miscounted as "
        "negatives; % dropped reported at every horizon.",
        "Q4 (False positives?) — Full AUC/AUPRC/PPV/Lift/alarm-burden table at every horizon, PLUS the "
        "alarm-episode fix and industry-benchmark context — the honest, complete answer, not a bare number.",
        "Q5 (Plot legend clarity?) — every figure in this deck ships with its own axis/line/threshold "
        "explanation, in-slide, so no plot requires verbal narration to be understood.",
    ], kicker="Q&A CHEAT SHEET")

    # ══════════════════════════════════════════════════════════ 28. ROADMAP
    bullets_slide(prs, "Next Steps", [
        "External validation: other hospitals, other units, other eras — none attempted yet.",
        "Prospective / shadow-mode testing before any real-patient use.",
        "Human-factors testing and a defined clinical override protocol.",
        "The imminent-deterioration blind spot: even after the Stage-0 look-back fix, "
        f"{stage0['residual_n']:,} of the original {stage0['old_gate_zero_anchor_n']:,} fastest "
        f"deteriorators ({stage0['residual_pct_of_old_zero']}%) still contribute zero anchors — a hard "
        "floor set by charting frequency, not solved by this iteration.",
        "Repeated-measures / stable-class down-sampling (v1-light stride) if time allows in a future pass.",
    ], kicker="ROADMAP")

    # ══════════════════════════════════════════════════════════ 29. THANK YOU
    section_slide(prs, "QUESTIONS", "Thank You")

    prs.save(OUT_PPTX)
    print(f"wrote {OUT_PPTX}  ({len(prs.slides._sldIdLst)} slides)")


if __name__ == "__main__":
    main()
