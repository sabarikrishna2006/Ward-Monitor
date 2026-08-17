"""
Build the Master Presentation PowerPoint (.pptx) Deck.

Every number is measured; provenance is RESULTS_2026-07-30.md. Charts come from
deck_plots.py, which this script runs automatically if the PNGs are absent.

Design rules for this revision:
  * SELF-CONTAINED slides. The full argument is readable from the slide itself;
    notes are a rehearsal aid, not where the content lives.
  * Professional tone throughout. No individual names, no attribution of whose
    suggestion something was, no self-criticism framing.
  * NO per-patient-hour metrics and NO alarms-per-day rates anywhere. Absolute
    alert-episode counts only - they need no denominator to explain.
  * Every method slide states HOW its quantity is computed, on the slide.
  * A chart wherever a curve or a comparison exists.

Run: PYTHONUTF8=1 py -3 build_presentation_deck.py
"""
import os
import subprocess
import sys

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.util import Inches, Pt

HERE = os.path.dirname(os.path.abspath(__file__))
CHARTS = os.path.join(HERE, "data", "deck_charts")

BG_DARK = RGBColor(15, 23, 42)
CARD_BG = RGBColor(30, 41, 59)
HEAD_BG = RGBColor(30, 58, 138)
TEXT_LIGHT = RGBColor(248, 250, 252)
TEXT_MUTED = RGBColor(148, 163, 184)
CYAN = RGBColor(56, 189, 248)
GOLD = RGBColor(251, 191, 36)
GREEN = RGBColor(52, 211, 153)
RED = RGBColor(248, 113, 113)
VIOLET = RGBColor(167, 139, 250)
WHITE = RGBColor(255, 255, 255)

NEEDED = ["gap_curve.png", "sens_curve.png", "hysteresis.png", "field_scatter.png",
          "architecture.png", "two_by_two.png", "features.png", "windows.png",
          "precision_at_k.png", "conformal.png", "calibration.png",
          "esc_operating.png"]


def ensure_charts():
    if all(os.path.exists(os.path.join(CHARTS, n)) for n in NEEDED):
        return
    print("charts missing - running deck_plots.py")
    subprocess.run([sys.executable, os.path.join(HERE, "deck_plots.py")], check=True)


def create_deck():
    ensure_charts()
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    blank = prs.slide_layouts[6]

    def new_slide(title, kicker="CLINICAL DETERIORATION EARLY WARNING SYSTEM", notes=""):
        s = prs.slides.add_slide(blank)
        f = s.background.fill
        f.solid()
        f.fore_color.rgb = BG_DARK
        tb = s.shapes.add_textbox(Inches(0.6), Inches(0.26), Inches(12.2), Inches(0.95))
        tf = tb.text_frame
        tf.word_wrap = True
        tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0
        p = tf.paragraphs[0]
        p.text = kicker.upper()
        p.font.size, p.font.bold, p.font.color.rgb, p.font.name = Pt(9.5), True, CYAN, "Calibri"
        p = tf.add_paragraph()
        p.text = title
        p.font.size, p.font.bold, p.font.color.rgb, p.font.name = Pt(20), True, TEXT_LIGHT, "Calibri"
        if notes:
            s.notes_slide.notes_text_frame.text = notes
        return s

    def card(s, l, t, w, h, bg=CARD_BG):
        sh = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, l, t, w, h)
        sh.fill.solid()
        sh.fill.fore_color.rgb = bg
        sh.line.color.rgb = RGBColor(51, 65, 85)
        sh.line.width = Pt(1)
        sh.shadow.inherit = False
        return sh

    def txt(s, l, t, w, h, blocks):
        tb = s.shapes.add_textbox(l, t, w, h)
        tf = tb.text_frame
        tf.word_wrap = True
        first = True
        for item in blocks:
            text, size, bold, col = item[0], item[1], item[2], item[3]
            gap = item[4] if len(item) > 4 else False
            p = tf.paragraphs[0] if first else tf.add_paragraph()
            first = False
            p.text = ("\n" if gap else "") + text
            p.font.size, p.font.bold, p.font.color.rgb = Pt(size), bold, col
            p.font.name = "Calibri"
        return tf

    def table(s, l, t, w, h, headers, rows, hi=(), col_w=None, fs=10):
        shp = s.shapes.add_table(len(rows) + 1, len(headers), l, t, w, h)
        tbl = shp.table
        if col_w:
            for j, cw in enumerate(col_w):
                tbl.columns[j].width = Inches(cw)
        for j, htxt in enumerate(headers):
            c = tbl.cell(0, j)
            c.text = htxt
            c.fill.solid()
            c.fill.fore_color.rgb = HEAD_BG
            for pr in c.text_frame.paragraphs:
                pr.font.size, pr.font.bold, pr.font.color.rgb = Pt(fs), True, WHITE
        for i, row in enumerate(rows):
            for j, val in enumerate(row):
                c = tbl.cell(i + 1, j)
                c.text = str(val)
                c.fill.solid()
                c.fill.fore_color.rgb = RGBColor(20, 45, 70) if i in hi else CARD_BG
                for pr in c.text_frame.paragraphs:
                    pr.font.size = Pt(fs)
                    pr.font.color.rgb = GOLD if i in hi else TEXT_LIGHT
                    pr.font.bold = i in hi
        return tbl

    def pic(s, name, l, t, w):
        return s.shapes.add_picture(os.path.join(CHARTS, name), l, t, width=w)

    # ═════════════════════════════════════════════════════════════════════
    # 1  TITLE
    # ═════════════════════════════════════════════════════════════════════
    s = prs.slides.add_slide(blank)
    f = s.background.fill; f.solid(); f.fore_color.rgb = BG_DARK
    card(s, Inches(1.0), Inches(1.3), Inches(11.3), Inches(4.9))
    txt(s, Inches(1.6), Inches(1.95), Inches(10.1), Inches(3.9), [
        ("IN-UNIT CLINICAL DETERIORATION EARLY WARNING SYSTEM", 12, True, CYAN),
        ("Reducing False Alarms in a Coronary Care Unit", 30, True, WHITE),
        ("Measurement discipline, alerting behaviour, and target design",
         17, False, TEXT_MUTED),
        ("MIMIC-IV Coronary Care Unit  •  7,860 admissions  •  298,679 hourly "
         "predictions  •  patient-level data split", 12, False, GOLD, True),
        ("Discrete-time hazard survival model  •  seven prediction horizons  •  "
         "isotonic-calibrated probabilities", 12, False, TEXT_MUTED),
    ])

    # ═════════════════════════════════════════════════════════════════════
    # 2  EXECUTIVE SUMMARY
    # ═════════════════════════════════════════════════════════════════════
    s = new_slide("Executive Summary", notes=(
        "The threshold method appears on this slide deliberately, so the operating "
        "point is never mistaken for a result. 80% sensitivity is a CHOSEN point; the "
        "evidence is what precision, lift and recall do at that point."))
    card(s, Inches(0.6), Inches(1.3), Inches(12.15), Inches(1.55))
    txt(s, Inches(0.95), Inches(1.45), Inches(11.6), Inches(1.35), [
        ("WHAT THE MODEL PREDICTS", 11, True, CYAN),
        ("For every patient, every hour: the calibrated probability of crossing "
         "NEWS2 ≥ 7 sustained for at least two consecutive hours, within the next "
         "2 / 4 / 6 / 9 / 12 / 18 / 24 hours.", 14, False, TEXT_LIGHT),
        ("How the alert threshold is set:  on a held-out calibration split, take the "
         "score below which only 20% of true events fall — capturing 80% of them — "
         "then freeze that value and apply it unchanged to the test split. The "
         "resulting out-of-sample sensitivity is 81.1%.", 11, False, TEXT_MUTED),
    ])
    cards = [
        ("DETECTION", GREEN, [
            ("96.7%", 30, True, GREEN),
            ("Patient recall", 12.5, True, TEXT_LIGHT),
            ("967 of every 1,000 deteriorating patients are flagged at least once "
             "before their event.", 10, False, TEXT_MUTED, True),
            ("AUROC        0.812", 11, True, TEXT_LIGHT, True),
            ("AUPRC        0.398", 11, True, TEXT_LIGHT),
            ("    no-skill floor 0.120  →  3.31×", 9.5, False, TEXT_MUTED),
            ("C-index      0.786", 11, True, TEXT_LIGHT),
            ("    95% CI  [0.767 – 0.806]", 9.5, False, TEXT_MUTED),
            ("Brier score  0.088", 11, False, TEXT_MUTED),
        ]),
        ("PRECISION", GOLD, [
            ("0.331", 30, True, GOLD),
            ("Episode PPV at 12 hours", 12.5, True, TEXT_LIGHT),
            ("Of every 100 alarms raised, 33 are followed by a real deterioration "
             "inside the horizon. Computed per ALARM, not per hour.",
             10, False, TEXT_MUTED, True),
            ("After alarm consolidation and", 10, False, TEXT_MUTED, True),
            ("the hysteresis latch:", 10, False, TEXT_MUTED),
            ("0.410  at 12 hours", 15, True, GREEN),
            ("0.500  at 24 hours", 15, True, GREEN),
            ("Lift  2.75×  →  3.41×", 11, True, TEXT_LIGHT, True),
        ]),
        ("ALARM LOAD", CYAN, [
            ("2,069 → 1,551", 21, True, CYAN),
            ("Alert episodes", 12.5, True, TEXT_LIGHT),
            ("A 25% reduction in the number of distinct alarms across the test "
             "population.", 10, False, TEXT_MUTED, True),
            ("Achieved with no loss of detection:", 10, False, TEXT_MUTED, True),
            ("recall 0.967 → 0.975", 12, True, GREEN),
            ("Median warning time", 10, False, TEXT_MUTED, True),
            ("7.0 h → 8.0 h", 12, True, GREEN),
        ]),
        ("CALIBRATION", VIOLET, [
            ("1.007", 30, True, VIOLET),
            ("Calibration slope", 12.5, True, TEXT_LIGHT),
            ("A slope of 1.0 means a predicted risk of 30% corresponds to an observed "
             "event rate of 30% — the probabilities can be read at face value rather "
             "than only as a ranking.", 10, False, TEXT_MUTED, True),
            ("Expected calibration error", 10, False, TEXT_MUTED, True),
            ("0.013", 15, True, TEXT_LIGHT),
            ("Mean absolute gap between predicted and observed frequency across "
             "probability deciles.", 9.5, False, TEXT_MUTED),
        ]),
    ]
    for i, (label, col, blocks) in enumerate(cards):
        x = Inches(0.6 + i * 3.06)
        card(s, x, Inches(3.05), Inches(2.9), Inches(3.85))
        txt(s, x + Inches(0.2), Inches(3.18), Inches(2.5), Inches(3.6),
            [(label, 10, True, col)] + blocks)

    # ═════════════════════════════════════════════════════════════════════
    # 3  MODEL, OUTPUTS, CALIBRATION
    # ═════════════════════════════════════════════════════════════════════
    s = new_slide("Model Formulation, Outputs, and Probability Calibration")
    card(s, Inches(0.6), Inches(1.25), Inches(6.7), Inches(5.7))
    txt(s, Inches(0.88), Inches(1.4), Inches(6.15), Inches(5.4), [
        ("DISCRETE-TIME HAZARD SURVIVAL MODEL", 12, True, CYAN),
        ("Time is divided into ordered intervals ending at 2, 4, 6, 9, 12, 18 and 24 "
         "hours. One gradient-boosted classifier per interval estimates the "
         "conditional hazard — the probability of the event occurring inside that "
         "interval, given the patient is still at risk when it begins:",
         10.5, False, TEXT_LIGHT, True),
        ("h_j  =  P( event in interval j  |  still at risk at its start )",
         12, True, GOLD, True),
        ("The survival curve is the running product of the complements:",
         10.5, False, TEXT_LIGHT, True),
        ("S(c_j)  =  S(c_j−1) × (1 − h_j)            P(T ≤ c_j)  =  1 − S(c_j)",
         12, True, GOLD, True),
        ("Because every hazard lies between 0 and 1, the survival curve can only "
         "decrease. Monotonicity holds by construction and no correction is applied "
         "afterwards.", 10, False, TEXT_MUTED, True),
        ("Censoring is handled per interval: a patient discharged partway through an "
         "interval contributes no row for that interval or any later one, since their "
         "outcome there is unknowable. Stable patients contribute a negative row to "
         "every interval they survive, so they are used as training signal rather than "
         "discarded.", 10, False, TEXT_MUTED),
        ("THREE OUTPUTS PER PATIENT-HOUR", 12, True, CYAN, True),
        ("1.   Seven calibrated probabilities, one per horizon. This is the primary "
         "output and the quantity the alert threshold is applied to.",
         10.5, False, TEXT_LIGHT),
        ("2.   A conditional expected time to the event, used to order the worklist "
         "by urgency.", 10.5, False, TEXT_LIGHT),
        ("3.   The shape of the hazard curve across intervals, used as an additional "
         "severity signal — described on a later slide.", 10.5, False, TEXT_LIGHT),
    ])
    card(s, Inches(7.6), Inches(1.25), Inches(5.15), Inches(5.7))
    txt(s, Inches(7.85), Inches(1.4), Inches(4.65), Inches(0.75), [
        ("PROBABILITY CALIBRATION", 12, True, CYAN),
        ("Each interval's raw score is mapped to a probability by an isotonic "
         "regression fitted on the calibration split.", 10, False, TEXT_LIGHT),
    ])
    pic(s, "calibration.png", Inches(7.85), Inches(2.25), Inches(4.65))
    txt(s, Inches(7.85), Inches(5.55), Inches(4.65), Inches(1.3), [
        ("Isotonic regression fits a monotone step function minimising squared error "
         "against the observed outcome. Being non-parametric it corrects any shape of "
         "miscalibration; being monotone it cannot reverse the ordering of patients, "
         "so discrimination — and therefore AUROC — is preserved exactly while the "
         "numbers become interpretable as probabilities.", 10, False, TEXT_LIGHT),
    ])

    # ═════════════════════════════════════════════════════════════════════
    # 4  ALARM DEFINITION AND HOW PRECISION IS COMPUTED
    # ═════════════════════════════════════════════════════════════════════
    s = new_slide("How an Alarm Is Defined, and How Precision Is Computed")
    card(s, Inches(0.6), Inches(1.25), Inches(6.15), Inches(5.7))
    txt(s, Inches(0.88), Inches(1.4), Inches(5.6), Inches(5.4), [
        ("THE ALARM EPISODE", 12, True, CYAN),
        ("A patient whose risk remains above threshold for five consecutive hours "
         "produces one alarm that a clinician responds to, not five. The unit of "
         "evaluation is therefore the alarm EPISODE: a maximal run of consecutive "
         "alerting hours for a single patient.", 10.5, False, TEXT_LIGHT, True),
        ("Successive alerting hours belong to the same episode when they are no more "
         "than two hours apart. The comparison is made on timestamps, so a gap in "
         "charting cannot split one clinical episode into two.",
         10.5, False, TEXT_LIGHT, True),
        ("HOW EPISODE PRECISION IS COMPUTED", 12, True, CYAN, True),
        ("An episode counts as TRUE when the patient's deterioration occurs within the "
         "prediction horizon of any hour inside that episode.",
         10.5, False, TEXT_LIGHT),
        ("Episode PPV   =   true episodes  ÷  all episodes", 12.5, True, GOLD, True),
        ("At the 12-hour horizon:   685  ÷  2,069   =   0.331", 12.5, True, GREEN),
        ("HOW DETECTION IS COMPUTED", 12, True, CYAN, True),
        ("Patient recall  =  deteriorating patients with at least one alerting hour "
         "inside the horizon before their event  ÷  all deteriorating patients",
         10.5, False, TEXT_LIGHT),
        ("At the 12-hour horizon:   621  ÷  642   =   0.967", 12.5, True, GREEN),
        ("HOW LIFT IS COMPUTED", 12, True, CYAN, True),
        ("Lift  =  episode PPV  ÷  base rate.  A value of 1.0 means an alarm carries "
         "no more information than selecting a patient at random. At 12 hours: "
         "0.331 ÷ 0.120 = 2.75×.", 10.5, False, TEXT_LIGHT),
    ])
    card(s, Inches(7.05), Inches(1.25), Inches(5.7), Inches(5.7))
    txt(s, Inches(7.32), Inches(1.4), Inches(5.15), Inches(5.4), [
        ("THREE UNITS OF EVALUATION, AND WHAT EACH ANSWERS", 12, True, CYAN),
        ("Prediction row   —   39,046 in the test set", 11.5, True, TEXT_LIGHT, True),
        ("One patient at one hour. This is the unit the model scores, and the unit "
         "over which AUROC, AUPRC and calibration are computed. It answers: how well "
         "does the model rank risk?", 10.5, False, TEXT_MUTED),
        ("Alarm episode   —   2,069 in the test set", 11.5, True, GOLD, True),
        ("One continuous run of alerting. This is the unit a clinician actually "
         "experiences, and the unit precision is reported in. It answers: when the "
         "system raises an alarm, how often is it right?", 10.5, False, TEXT_MUTED),
        ("Patient   —   1,236 admissions in the test set", 11.5, True, GREEN, True),
        ("One coronary care admission. This is the unit detection is reported in. It "
         "answers: was this deteriorating patient warned about at all?",
         10.5, False, TEXT_MUTED),
        ("WHY THE DISTINCTION IS ENFORCED", 12, True, CYAN, True),
        ("The three units have different denominators, so a ratio formed from two of "
         "them has no interpretation. Throughout this work every precision figure is "
         "episode-level, every detection figure is patient-level, and the two are "
         "never combined into a single ratio.", 10.5, False, TEXT_LIGHT),
        ("Reporting precision per prediction row would make a stable patient with 60 "
         "charted hours weigh 60 times as heavily as a patient who deteriorates after "
         "three — which is why the episode is used instead.",
         10.5, False, TEXT_MUTED, True),
    ])

    # ═════════════════════════════════════════════════════════════════════
    # 5  FALSE-ALARM COMPOSITION + REFINED EVENT DEFINITION
    # ═════════════════════════════════════════════════════════════════════
    s = new_slide("Composition of the False Alarms, and the Refined Event Definition")
    card(s, Inches(0.6), Inches(1.25), Inches(6.15), Inches(5.7))
    txt(s, Inches(0.88), Inches(1.4), Inches(5.6), Inches(0.5), [
        ("WHAT THE 1,384 FALSE EPISODES AT 12 HOURS ACTUALLY ARE", 11.5, True, CYAN)])
    table(s, Inches(0.88), Inches(1.95), Inches(5.6), Inches(1.4),
          ["The patient's NEWS2 record", "Episodes", "Share"],
          [["Never reached NEWS2 ≥ 7 at any point in the stay", "360", "26.0%"],
           ["Reached NEWS2 ≥ 7, never for two consecutive hours", "700", "50.6%"],
           ["Sustained NEWS2 ≥ 7, outside this horizon", "324", "23.4%"]],
          hi=(0,), col_w=[3.5, 1.05, 1.05], fs=9.5)
    txt(s, Inches(0.88), Inches(3.65), Inches(5.6), Inches(3.2), [
        ("Only 26% of alarms fire on a patient who shows no critical deterioration at "
         "any point during the admission.", 12, True, GOLD),
        ("Half fire on patients who did cross the critical threshold, but whose "
         "crossing was not sustained for two consecutive hours — so the original event "
         "definition recorded them as never having deteriorated.",
         10.5, False, TEXT_LIGHT, True),
        ("This locates a substantial share of the apparent false-alarm burden in the "
         "event definition rather than in the model, and motivates the refinement "
         "opposite.", 10.5, False, TEXT_MUTED, True),
        ("An alternating pattern such as 8, 6, 9, 6, 8 spends three hours in the "
         "critical band yet satisfies no two-consecutive-hour rule, because each hour "
         "below threshold resets the count.", 10.5, False, TEXT_MUTED, True),
    ])
    card(s, Inches(7.05), Inches(1.25), Inches(5.7), Inches(5.7))
    txt(s, Inches(7.32), Inches(1.4), Inches(5.15), Inches(5.4), [
        ("REFINED EVENT DEFINITION", 12, True, CYAN),
        ("Original:   NEWS2 ≥ 7 for two CONSECUTIVE hours.", 11, True, TEXT_LIGHT, True),
        ("Refined — the earliest time at which any of four rules is satisfied:",
         11, True, GOLD, True),
        ("(a)   NEWS2 ≥ 7 for two consecutive hours, as before\n"
         "(b)   at least two hours at NEWS2 ≥ 7 within any four-hour window\n"
         "(c)   one hour at NEWS2 ≥ 7 followed by death within six hours\n"
         "(d)   one hour at NEWS2 ≥ 7 with the record ending under two hours later, "
         "so the two-hour rule could not physically be satisfied",
         10.5, False, TEXT_LIGHT),
        ("Rule (a) is retained as a candidate, so the refined definition is a strict "
         "superset of the original: it can only move an event earlier, and can never "
         "remove one.", 10, False, TEXT_MUTED, True),
        ("EFFECT ON THE FALSE-ALARM BURDEN", 12, True, CYAN, True),
        ("Rule (b) reclassifies 515 of the 2,019 transient patients as genuine events. "
         "Of those remaining, 1,008 recorded exactly one high hour in the entire "
         "admission — a pattern indistinguishable from a single artefactual reading, "
         "which is precisely what a two-reading requirement exists to filter. "
         "Recovering them would exchange one form of label noise for another.",
         10.5, False, TEXT_LIGHT),
        ("Measured at 12 hours:", 10.5, True, TEXT_LIGHT, True),
        ("Episode PPV                  0.331  →  0.345\n"
         "False episodes               1,384  →  1,209\n"
         "Episodes on transient patients  700  →  584", 11, True, GREEN),
    ])

    # ═════════════════════════════════════════════════════════════════════
    # 6  VALIDATING THE REFINED DEFINITION
    # ═════════════════════════════════════════════════════════════════════
    s = new_slide("Validating the Refined Definition: Better Signal, or Harder Task?")
    card(s, Inches(0.6), Inches(1.25), Inches(12.15), Inches(5.7))
    txt(s, Inches(0.95), Inches(1.42), Inches(11.5), Inches(1.15), [
        ("THE AMBIGUITY THAT HAS TO BE RESOLVED", 12, True, CYAN),
        ("A broader event definition admits harder cases, so the prediction task itself "
         "becomes harder. Precision rises because prevalence rises, while lift falls "
         "because the added events are intrinsically less predictable. Neither movement "
         "on its own distinguishes a better training signal from a harder target.",
         11.5, False, TEXT_LIGHT),
    ])
    txt(s, Inches(0.95), Inches(2.7), Inches(11.5), Inches(0.45), [
        ("THE RESOLUTION — cross the TRAINING definition against the EVALUATION "
         "definition, on the same 261,436 prediction rows", 12, True, GOLD)])
    table(s, Inches(0.95), Inches(3.2), Inches(11.5), Inches(1.2),
          ["", "Evaluated against the original definition",
           "Evaluated against the refined definition"],
          [["Trained on the original definition",
            "AUROC 0.7956        AUPRC 0.3086", "AUROC 0.7948        AUPRC 0.3783"],
           ["Trained on the refined definition",
            "AUROC 0.7982        AUPRC 0.3208", "AUROC 0.7968        AUPRC 0.3845"]],
          hi=(1,), col_w=[3.3, 4.1, 4.1], fs=11)
    txt(s, Inches(0.95), Inches(4.7), Inches(11.5), Inches(2.15), [
        ("The model trained on the refined definition performs better even when judged "
         "against the ORIGINAL definition, which it was never trained for: "
         "AUROC +0.0026 and AUPRC +4.0% relative.", 13, True, GREEN),
        ("The refined definition is therefore a better training signal, and the fall in "
         "headline lift is attributable entirely to the harder target rather than to a "
         "degraded label.", 11.5, False, TEXT_LIGHT, True),
        ("Sizing this honestly: the AUROC gain of +0.0026 lies inside the confidence "
         "interval and should not be presented as decisive on its own. The AUPRC gain "
         "is the more credible of the two, because AUPRC is not inflated by the large "
         "true-negative pool that a rare outcome produces. The comparison is valid only "
         "because split assignment is a deterministic function of patient identifier, "
         "so the same patient is a test patient under both definitions and the two "
         "models are scored on identical people.", 10.5, False, TEXT_MUTED, True),
    ])

    # ═════════════════════════════════════════════════════════════════════
    # 7  EPISODE GAP + CHART
    # ═════════════════════════════════════════════════════════════════════
    s = new_slide("Alarm Consolidation: the Episode-Gap Parameter")
    card(s, Inches(0.6), Inches(1.25), Inches(12.15), Inches(5.7))
    pic(s, "gap_curve.png", Inches(0.85), Inches(1.5), Inches(7.5))
    txt(s, Inches(8.6), Inches(1.45), Inches(3.95), Inches(5.4), [
        ("WHAT THE PARAMETER IS", 11.5, True, CYAN),
        ("The maximum interval between two alerting hours for them to be counted as "
         "one alarm rather than two.", 10.5, False, TEXT_LIGHT),
        ("PUBLISHED PRECEDENT", 11.5, True, CYAN, True),
        ("Alarm consolidation is standard practice in deployed early-warning systems. "
         "Reported windows:", 10.5, False, TEXT_LIGHT),
        ("4 hours     MEWS++, Mount Sinai\n\n"
         "6 hours     DETERIO, UC San Diego —\n"
         "                 declared explicitly as an\n"
         "                 end-user clinical response\n"
         "                 policy rather than a model\n"
         "                 property\n\n"
         "8 hours     MC-EWS, Mayo Clinic\n\n"
         "4–48 hrs    range reported across the\n"
         "                 fourteen systems in the\n"
         "                 JAMIA 2024 review",
         9.5, True, GOLD, True),
        ("WHY TWO HOURS WAS SELECTED", 11.5, True, CYAN, True),
        ("Patient recall is identical at every setting, so this parameter affects only "
         "how alarms are counted and never how many patients are detected.",
         10.5, False, TEXT_LIGHT),
        ("A twelve-hour window would report precision of 0.446 rather than 0.331 with "
         "no change to the model. Two hours is the shortest window that consolidates a "
         "single-hour dip below threshold, and nothing beyond that.",
         10.5, False, GOLD, True),
    ])

    # ═════════════════════════════════════════════════════════════════════
    # 8  OPERATING POINT + CHART
    # ═════════════════════════════════════════════════════════════════════
    s = new_slide("The Operating Point: Where the Alert Threshold Is Set")
    card(s, Inches(0.6), Inches(1.25), Inches(12.15), Inches(5.7))
    pic(s, "sens_curve.png", Inches(0.85), Inches(1.5), Inches(7.5))
    txt(s, Inches(8.6), Inches(1.45), Inches(3.95), Inches(5.4), [
        ("HOW THE THRESHOLD IS SET", 11.5, True, CYAN),
        ("On the calibration split, take the score below which only a chosen fraction "
         "of true events fall. Freeze that value. Apply it unchanged to the test "
         "split.", 10.5, False, TEXT_LIGHT),
        ("At a target of 80%, the out-of-sample sensitivity is 81.1%. The small "
         "discrepancy confirms the score distribution transfers between splits; a "
         "large one would indicate distribution shift.", 10.5, False, TEXT_MUTED, True),
        ("WHY LIFT IS THE HONEST METRIC", 11.5, True, CYAN, True),
        ("Lift  =  episode PPV  ÷  base rate", 11.5, True, GOLD),
        ("A value of 1.0 means an alarm carries no more information than selecting a "
         "patient at random; the ceiling is one divided by the base rate. Because the "
         "base rate is constant along this curve, rising lift represents a real "
         "increase in the information each alarm carries.", 10.5, False, TEXT_LIGHT),
        ("THE TRADE, QUANTIFIED", 11.5, True, CYAN, True),
        ("Lowering the sensitivity target raises precision monotonically from 0.331 at "
         "80% to 0.578 at 20%, and raises lift from 2.75× to 4.80×. The cost is "
         "detection: patient recall falls from 0.967 to 0.494.",
         10.5, False, TEXT_LIGHT),
        ("Deployed systems in the reviewed literature operate between 25% and 63% "
         "sensitivity, chosen to match the alarm volume a ward can absorb.",
         10.5, False, GOLD, True),
    ])

    # ═════════════════════════════════════════════════════════════════════
    # 9  FIELD COMPARISON
    # ═════════════════════════════════════════════════════════════════════
    s = new_slide("Comparison Against Published Deterioration Systems",
                  kicker="JAMIA 2024 SYSTEMATIC REVIEW — FOURTEEN SYSTEMS — PLUS DETERIO, UC SAN DIEGO")
    card(s, Inches(0.6), Inches(1.2), Inches(6.5), Inches(5.75))
    table(s, Inches(0.8), Inches(1.4), Inches(6.1), Inches(4.35),
          ["System", "Model family", "Vars", "Sens", "PPV", "AUROC"],
          [["OUR MODEL, 12h", "Discrete-time hazard", "55", "81%", "33.1%", "0.812"],
           ["MEWS++, Mount Sinai", "Random forest", "36", "79%", "12%", "0.88"],
           ["MC-EWS, Mayo", "Gradient boosting", "59", "73%", "12%", "0.91–0.94"],
           ["eCART, Chicago", "Logistic regression", "27–33", "60–77%", "—", "0.88"],
           ["APPROVE, Mayo", "Random forest", "36", "63%", "21%", "0.87"],
           ["Duke", "XGBoost", "57", "60%", "8–9%", "0.87"],
           ["DETERIO, UC San Diego", "Neural network", "229", "46%", "22%", "0.775"],
           ["Univ. of Washington", "Logistic regression", "36", "41%", "30%", "0.73"],
           ["CHARTwatch, Toronto", "Ensemble", "526", "40%", "71% → 21%", "0.95 → 0.63"],
           ["Epic Deterioration Index", "Logistic regression", ">125", "39%", "74%", "0.79"],
           ["DEWS, Korea", "LSTM", "4–7", "37%", "4%", "0.85"],
           ["HBI Solutions", "Random forest", "349", "23%", "31%", "0.88"],
           ["eCARTv2", "Logistic regression", "—", "—", "8.2%", "—"]],
          hi=(0,), col_w=[1.75, 1.55, 0.6, 0.65, 0.85, 0.75], fs=8.5)
    txt(s, Inches(0.8), Inches(5.95), Inches(6.1), Inches(1.0), [
        ("CHARTwatch is shown with retrospective figures followed by deployed figures. "
         "Precision fell from 71% to 21% and AUROC from 0.95 to 0.63 on live data — the "
         "largest degradation among the reviewed systems, and the one using the most "
         "variables. Every system reporting both stages degraded.",
         9.5, False, TEXT_MUTED),
    ])
    card(s, Inches(7.35), Inches(1.2), Inches(5.4), Inches(5.75))
    pic(s, "field_scatter.png", Inches(7.6), Inches(1.45), Inches(4.9))
    txt(s, Inches(7.6), Inches(4.5), Inches(4.9), Inches(2.4), [
        ("Precision and sensitivity trade against one another, so neither figure is "
         "interpretable alone. At a matched sensitivity of 79–81%, the published "
         "systems achieve 12% precision.", 10.5, True, GOLD),
        ("The two systems reporting precision above 70% operate near 40% sensitivity — "
         "roughly half of ours — and one of them lost two-thirds of that precision on "
         "deployment.", 10, False, TEXT_LIGHT, True),
        ("Interpretive caveat: our event definition is derived from the same vital "
         "signs used as model inputs, whereas most reviewed systems predict an "
         "independent outcome such as intensive-care transfer or death. The comparison "
         "is favourable but not exact, and Part 2 addresses this directly.",
         10, False, TEXT_MUTED, True),
    ])

    # ═════════════════════════════════════════════════════════════════════
    # 10  HYSTERESIS
    # ═════════════════════════════════════════════════════════════════════
    s = new_slide("Hysteresis: a Dual-Threshold Alerting Rule")
    card(s, Inches(0.6), Inches(1.2), Inches(12.15), Inches(5.75))
    txt(s, Inches(0.9), Inches(1.35), Inches(11.6), Inches(1.55), [
        ("THE PROBLEM WITH A SINGLE THRESHOLD", 12, True, CYAN),
        ("A single threshold raises the alert when risk rises above it and clears the "
         "alert when risk falls below it. A patient whose risk hovers near that line "
         "therefore alternates on and off, producing several separate alarms from "
         "measurement noise rather than from any change in the patient's condition.",
         11, False, TEXT_LIGHT),
        ("THE RULE", 12, True, GOLD, True),
        ("Raise the alert when risk exceeds τ_high. Keep it raised until risk falls "
         "below a LOWER release threshold τ_low, set here to 50% of τ_high. Between "
         "the two thresholds the alert holds whatever state it is already in. This is "
         "a Schmitt trigger — the same mechanism that prevents a thermostat from "
         "cycling continuously around its set point.", 11, False, TEXT_LIGHT),
    ])
    pic(s, "hysteresis.png", Inches(0.9), Inches(3.05), Inches(7.6))
    txt(s, Inches(8.75), Inches(3.0), Inches(3.8), Inches(3.8), [
        ("MEASURED EFFECT AT 12 HOURS", 11.5, True, CYAN),
        ("Alert episodes       2,069 → 1,551\n"
         "Episode PPV          0.331 → 0.410\n"
         "Episode lift          2.75× → 3.41×\n"
         "Patient recall       0.967 → 0.975\n"
         "Median warning      7.0 h → 8.0 h", 11, True, GOLD, True),
        ("WHY PRECISION IMPROVES", 11.5, True, CYAN, True),
        ("False alarms are predominantly brief excursions across the threshold, while "
         "true alarms are sustained. Holding the alert through the deadband therefore "
         "consolidates the brief excursions preferentially. Across the test set, false "
         "episodes fell by 34% while true episodes fell by only 7%.",
         10.5, False, TEXT_LIGHT),
        ("WHY DETECTION IS PRESERVED", 11.5, True, CYAN, True),
        ("The condition for RAISING an alert is unchanged; only the condition for "
         "clearing it is altered. The first alert on any patient can therefore never "
         "be delayed or lost, so recall is preserved by construction. It rises "
         "slightly because a patient whose risk dips briefly remains under alert when "
         "their event arrives.", 10.5, False, TEXT_LIGHT),
    ])

    # ═════════════════════════════════════════════════════════════════════
    # 11  MULTI-WINDOW DYNAMICS
    # ═════════════════════════════════════════════════════════════════════
    s = new_slide("Multi-Window Time-Series Dynamics: Construction and Contribution")
    card(s, Inches(0.6), Inches(1.2), Inches(12.15), Inches(5.75))
    txt(s, Inches(0.9), Inches(1.35), Inches(5.6), Inches(5.5), [
        ("HOW THE FEATURES ARE CONSTRUCTED", 12, True, CYAN),
        ("Each physiological variable is summarised over three overlapping look-back "
         "windows, all ending at the prediction hour:", 10.5, False, TEXT_LIGHT),
        ("2 hours      acute change, high temporal resolution\n"
         "6 hours      the patient's current state\n"
         "12 hours    the patient's own recent baseline", 11, True, GOLD, True),
        ("Within each window, three statistics are computed: the mean (level), the "
         "standard deviation (volatility), and the slope (velocity).",
         10.5, False, TEXT_LIGHT, True),
        ("TREND-ACCELERATION FEATURES", 12, True, CYAN, True),
        ("trend_2h_vs_12h   =   mean over 2 h   −   mean over 12 h",
         11.5, True, GOLD),
        ("A heart rate of 100 with a twelve-hour mean of 100 describes a stably "
         "elevated patient. A heart rate of 100 with a twelve-hour mean of 70 "
         "describes a patient accelerating into crisis. The two require different "
         "responses, yet they are indistinguishable from any single window.",
         10.5, False, TEXT_LIGHT, True),
        ("Supplying the difference explicitly matters because decision trees split on "
         "one variable at a time. Separating those two patients from the two means "
         "independently requires a staircase of many splits, and at a maximum tree "
         "depth of four a single such boundary would consume the entire tree. The "
         "explicit difference reduces it to one split.", 10.5, False, TEXT_MUTED, True),
        ("TWO FURTHER FEATURE CLASSES", 12, True, CYAN, True),
        ("Deviation from the patient's own twelve-hour baseline, so that an abnormal "
         "value is judged against that individual rather than a population norm; and "
         "the time elapsed since each variable was last measured, which captures that "
         "clinical teams measure more frequently when concerned.",
         10.5, False, TEXT_LIGHT),
    ])
    pic(s, "windows.png", Inches(6.7), Inches(1.9), Inches(5.85))
    txt(s, Inches(6.7), Inches(5.35), Inches(5.85), Inches(1.5), [
        ("CONTRIBUTION TO FALSE-ALARM REDUCTION", 11.5, True, CYAN),
        ("Window, trend and acceleration features account for 47.3% of total model "
         "gain. Each window contributes independently, and the twelve-hour baseline "
         "contributes most of the three — evidence that the model is separating acute "
         "deterioration from stable elevation. That distinction is precisely what a "
         "single-window model resolves as a false alarm, which is the mechanism by "
         "which the multi-window construction reduces them.", 10.5, False, GOLD),
    ])

    # ═════════════════════════════════════════════════════════════════════
    # 12  COMPLETE METHOD INVENTORY
    # ═════════════════════════════════════════════════════════════════════
    s = new_slide("False-Alarm Reduction: Complete Method Inventory")
    card(s, Inches(0.6), Inches(1.2), Inches(12.15), Inches(5.75))
    txt(s, Inches(0.9), Inches(1.35), Inches(11.6), Inches(0.9), [
        ("Reducing false alarms means three structurally different things. Separating "
         "them is what makes each claim interpretable: one category changes how alarms "
         "are counted, one changes how the alerting system behaves, and one changes the "
         "precision–detection trade itself. Each row below states its mechanism and its "
         "cost.", 11.5, False, TEXT_LIGHT),
    ])
    table(s, Inches(0.9), Inches(2.35), Inches(11.6), Inches(3.4),
          ["Category", "Method", "Mechanism", "Cost to detection", "Measured result"],
          [["ORDERING", "Worklist ranked by predicted severity",
            "Every alarm is displayed; the most urgent are presented first",
            "None — nothing is withheld",
            "Precision on the leading 10% of alarms rises from 0.19 to 0.57"],
           ["BEHAVIOUR", "Hysteresis dual-threshold latch",
            "The alert holds through a deadband instead of clearing at a single line",
            "None — the raise condition is unchanged",
            "Episodes 2,069 → 1,551;  PPV 0.331 → 0.410;  recall 0.967 → 0.975"],
           ["TRADE", "Operating point: sensitivity and horizon",
            "Moves the threshold along the precision–detection curve",
            "Real, and quantified on the curve",
            "PPV 0.331 → 0.578 as sensitivity falls from 80% to 20%"],
           ["TRADE", "Conformal abstention, three-tier output",
            "Low-confidence hours are routed to a review list rather than paged",
            "Real; the abstention rate is chosen explicitly",
            "Paged-tier lift 2.88× → 3.45× at α = 0.20"],
           ["COUNTING", "Episode consolidation, gap parameter",
            "Defines how many alerting hours constitute one alarm",
            "None — recall is invariant at every setting",
            "A reporting convention; the full curve is always shown"],
           ["DEFINITION", "Refined event definition",
            "Recognises non-consecutive critical excursions as events",
            "Improves — recall rises",
            "False episodes 1,384 → 1,209; validated as a better training signal"]],
          hi=(0, 1), col_w=[1.4, 2.5, 2.9, 2.0, 2.8], fs=8.5)
    txt(s, Inches(0.9), Inches(5.95), Inches(11.6), Inches(1.0), [
        ("The ORDERING and BEHAVIOUR categories improve the clinician's experience at "
         "no cost to detection, so they are adopted unconditionally. The TRADE category "
         "is where genuine precision is purchased and the price is stated alongside. "
         "The COUNTING category is reported as a curve rather than a single value, so "
         "the convention chosen is visible rather than embedded.", 11, True, GOLD),
    ])

    # ═════════════════════════════════════════════════════════════════════
    # 13  ARCHITECTURE COMPARISON
    # ═════════════════════════════════════════════════════════════════════
    s = new_slide("Architecture Comparison: Gradient-Boosted Trees and Neural Networks")
    card(s, Inches(0.6), Inches(1.2), Inches(12.15), Inches(5.75))
    txt(s, Inches(0.9), Inches(1.35), Inches(5.55), Inches(5.5), [
        ("THE QUESTION", 12, True, CYAN),
        ("The baseline trains seven independent classifiers, one per interval, sharing "
         "no parameters. An alternative is a single network with a shared "
         "representation and one output head per interval, trained on a combined loss "
         "so that gradient from every interval updates the same trunk — allowing the "
         "intervals to inform one another.", 10.5, False, TEXT_LIGHT),
        ("Moving directly between those designs changes both the parameter sharing and "
         "the base learner simultaneously. Four configurations were therefore trained "
         "so that each change can be attributed separately.",
         10.5, False, TEXT_MUTED, True),
        ("THE FOUR CONFIGURATIONS", 12, True, CYAN, True),
        ("1.   Seven independent gradient-boosted classifiers   —   0.7860",
         10.5, False, TEXT_LIGHT),
        ("2.   One pooled classifier taking the interval index as an input feature, so "
         "all parameters are shared while the base learner is held fixed   —   0.7853",
         10.5, False, TEXT_LIGHT),
        ("3.   Shared-trunk network, 55 → 128 → 64, with seven hazard heads trained on "
         "a masked cross-entropy loss   —   0.7779", 10.5, False, TEXT_LIGHT),
        ("4.   Shared-trunk network with monotone cumulative heads   —   0.7767",
         10.5, False, TEXT_LIGHT),
        ("FINDINGS", 12, True, GOLD, True),
        ("Parameter sharing in isolation changes the C-index by −0.0007. The total "
         "spread across all four architectures is 0.0093, against confidence intervals "
         "approximately 0.040 wide — the four are statistically indistinguishable.",
         10.5, False, TEXT_LIGHT),
        ("Sharing behaves as theory predicts in detail: it improves the data-poor late "
         "intervals, from 0.7387 to 0.7455 at twelve hours, and degrades the data-rich "
         "early one, from 0.8707 to 0.8645 at two hours. The two effects cancel. "
         "Parameter sharing benefits a task starved of data, and the smallest interval "
         "here still holds 105,416 training rows.", 10.5, False, TEXT_MUTED, True),
        ("A search across eight network configurations spanned only 0.7% of validation "
         "loss, indicating the neural result reflects the architecture rather than "
         "insufficient tuning.", 10.5, False, TEXT_MUTED, True),
    ])
    pic(s, "architecture.png", Inches(6.65), Inches(1.5), Inches(5.9))
    txt(s, Inches(6.65), Inches(4.5), Inches(5.9), Inches(2.4), [
        ("CALIBRATION APPLIED IDENTICALLY ACROSS ALL FOUR", 11.5, True, CYAN),
        ("Each interval's raw score is mapped to a probability by an isotonic "
         "regression fitted on the calibration split. Isotonic regression fits a "
         "monotone step function minimising squared error against the observed outcome. "
         "Being non-parametric it corrects any shape of miscalibration; being monotone "
         "it cannot alter the ordering of patients, and therefore leaves AUROC exactly "
         "unchanged.", 10.5, False, TEXT_LIGHT),
        ("Applying the identical calibration procedure to every configuration ensures "
         "the architecture comparison measures the hazard estimate itself, rather than "
         "differences in how the scores were post-processed. Resulting calibration "
         "slope 1.007, expected calibration error 0.013.", 10.5, False, GOLD, True),
    ])

    # ═════════════════════════════════════════════════════════════════════
    # 14  PART 2 DIVIDER
    # ═════════════════════════════════════════════════════════════════════
    s = new_slide("Part 2: Redefining the Prediction Target",
                  kicker="PART 2 — THE ESCALATION-OF-CARE MODEL")
    card(s, Inches(0.6), Inches(1.25), Inches(5.9), Inches(5.7))
    txt(s, Inches(0.88), Inches(1.45), Inches(5.35), Inches(5.4), [
        ("PREVALENCE OF THE CURRENT TARGET", 12, True, CYAN),
        ("NEWS2 ≥ 7 sustained for two hours occurs in 50.3% of coronary care "
         "admissions.", 12.5, True, GOLD, True),
        ("Published prevalence of the outcomes used by deployed deterioration systems:",
         10.5, False, TEXT_LIGHT, True),
        ("Intensive care settings          11.3% – 32.8%\n"
         "Non-intensive settings             2.1% – 22.7%", 11.5, True, TEXT_LIGHT),
        ("The current target lies above the entire published intensive-care range.",
         11, True, RED, True),
        ("WHY THIS CONSTRAINS PRECISION", 12, True, CYAN, True),
        ("Precision is bounded by prevalence. When an outcome occurs in half of all "
         "admissions, an alarm indicating that outcome cannot carry much information, "
         "because the alarm state and the ordinary state of the unit are nearly the "
         "same condition.", 10.5, False, TEXT_LIGHT),
        ("This is a property of the target, not of the model, and no change to the "
         "model can remove it.", 10.5, False, TEXT_MUTED, True),
    ])
    card(s, Inches(6.8), Inches(1.25), Inches(5.95), Inches(5.7))
    txt(s, Inches(7.08), Inches(1.45), Inches(5.4), Inches(5.4), [
        ("WHY THE PREVALENCE IS SO HIGH", 12, True, CYAN),
        ("Under national protocol, NEWS2 ≥ 7 mandates an emergency response, "
         "continuous monitoring, and escalation to intensive-care-level care.",
         11, False, TEXT_LIGHT, True),
        ("Patients in a coronary care unit already receive all three.",
         12.5, True, GOLD, True),
        ("The response the score exists to trigger is therefore already in place. For "
         "this population the threshold describes a routine state rather than an "
         "exceptional one — which is both why half the unit reaches it, and why an "
         "alarm based on it does not identify a decision that still needs to be taken.",
         10.5, False, TEXT_LIGHT, True),
        ("WHAT DEPLOYED SYSTEMS PREDICT INSTEAD", 12, True, CYAN, True),
        ("All fourteen systems in the JAMIA 2024 review predict transfer to intensive "
         "care, escalation of treatment, cardiac arrest, or death. None predicts a "
         "vital-sign score threshold.", 10.5, False, TEXT_LIGHT),
        ("An outcome that is actionable within the unit is required — one where the "
         "alarm identifies a clinical decision not yet made.", 11, True, GREEN, True),
    ])

    # ═════════════════════════════════════════════════════════════════════
    # 15  ESCALATION TARGET DEFINITION
    # ═════════════════════════════════════════════════════════════════════
    s = new_slide("The Escalation-of-Care Target: Full Definition",
                  kicker="PART 2 — THE ESCALATION-OF-CARE MODEL")
    card(s, Inches(0.6), Inches(1.2), Inches(6.15), Inches(5.75))
    txt(s, Inches(0.86), Inches(1.35), Inches(5.6), Inches(2.4), [
        ("EVENT DEFINITION", 12, True, CYAN),
        ("The first occurrence, more than two hours after unit admission, of any "
         "escalation of organ support, of death, or of sustained circulatory collapse. "
         "All three are timestamped clinical facts rather than derived scores.",
         10.5, False, TEXT_LIGHT),
        ("COHORT RESTRICTION", 12, True, CYAN, True),
        ("Admissions whose event occurs within the first two hours are excluded from "
         "the modelling population. Median time from admission to first escalation in "
         "this unit is 1.07 hours, so for those patients the event is concurrent with "
         "or precedes the first available observation and there is nothing to forecast. "
         "They are covered instead by an admission rule that alerts immediately, so no "
         "patient is left unmonitored.", 10.5, False, TEXT_LIGHT),
    ])
    table(s, Inches(0.86), Inches(3.95), Inches(5.6), Inches(1.15),
          ["Cohort construction", "Admissions"],
          [["All coronary care admissions", "10,775"],
           ["Excluded: event within the first two hours", "− 2,965"],
           ["Excluded: stay shorter than two hours", "− 53"],
           ["Modelling population", "7,757"]], hi=(3,), col_w=[4.3, 1.3], fs=10)
    txt(s, Inches(0.86), Inches(5.35), Inches(5.6), Inches(1.5), [
        ("2,034 events  ÷  7,757 admissions  =  26.2% prevalence", 13, True, GREEN),
        ("Inside the published intensive-care range of 11.3% – 32.8%, and derived from "
         "clinical actions rather than from the vital signs used as model inputs — so "
         "the target is independent of the feature set.", 10.5, False, TEXT_MUTED, True),
    ])
    card(s, Inches(7.05), Inches(1.2), Inches(5.7), Inches(5.75))
    txt(s, Inches(7.3), Inches(1.35), Inches(5.2), Inches(0.5), [
        ("CONSTITUENT EVENTS, BY THE TRACK THAT FIRED FIRST", 11.5, True, CYAN)])
    table(s, Inches(7.3), Inches(1.88), Inches(5.2), Inches(2.9),
          ["Event track", "Events", "New"],
          [["Vasopressor or inotrope initiation", "696", ""],
           ["Death without prior escalation", "424", ""],
           ["Mechanical ventilation initiation", "350", ""],
           ["Renal replacement therapy initiation", "164", ""],
           ["Intubation, pericardiocentesis, pacing", "127", "yes"],
           ["Sustained circulatory collapse", "116", "yes"],
           ["Cardiac arrest or defibrillation", "97", "yes"],
           ["IABP, Impella, or ECMO", "60", "yes"]],
          col_w=[3.4, 0.9, 0.9], fs=9.5)
    txt(s, Inches(7.3), Inches(4.95), Inches(5.2), Inches(1.95), [
        ("Sustained circulatory collapse is defined as a mean arterial pressure below "
         "55 mmHg together with a shock index — heart rate divided by systolic "
         "pressure — of at least 1.1, persisting two hours or longer. It captures "
         "patients in unambiguous physiological collapse who are nonetheless not "
         "escalated, for instance under a treatment-limitation order, and who would "
         "otherwise be recorded as having no event at all.", 10, False, TEXT_LIGHT),
        ("The four tracks marked new contribute 400 of the 2,034 events. Mechanical "
         "circulatory support is the definitive rescue for cardiogenic shock in this "
         "population and had not previously been represented.", 10, False, GOLD, True),
    ])

    # ═════════════════════════════════════════════════════════════════════
    # 16  ESCALATION MODEL RESULTS
    # ═════════════════════════════════════════════════════════════════════
    s = new_slide("Escalation Model: Results, and the Effect of the Feature Set",
                  kicker="PART 2 — THE ESCALATION-OF-CARE MODEL")
    card(s, Inches(0.6), Inches(1.2), Inches(6.4), Inches(5.75))
    txt(s, Inches(0.85), Inches(1.35), Inches(5.9), Inches(0.45), [
        ("DOES THE FEATURE SET MATTER, AND ON WHICH TARGET?", 11.5, True, CYAN)])
    pic(s, "two_by_two.png", Inches(0.85), Inches(1.82), Inches(5.9))
    txt(s, Inches(0.85), Inches(4.8), Inches(5.9), Inches(2.1), [
        ("The identical feature set improves the escalation target by 0.0725 AUROC and "
         "the NEWS2 target by 0.0021.", 11.5, True, GOLD),
        ("NEWS2 is computed deterministically from seven vital signs. Anion gap, mean "
         "arterial pressure, lactate and infusion titration therefore cannot improve a "
         "prediction of NEWS2: they do not enter its formula, and can act only through "
         "their eventual effect on those same seven vitals, which the vital features "
         "already represent.", 10.5, False, TEXT_LIGHT, True),
        ("Against escalation of care, where metabolic acidosis and hypoperfusion are "
         "direct causal mechanisms, the same features carry substantial information.",
         10.5, False, TEXT_LIGHT),
    ])
    card(s, Inches(7.3), Inches(1.2), Inches(5.45), Inches(5.75))
    txt(s, Inches(7.55), Inches(1.35), Inches(4.95), Inches(0.45), [
        ("ESCALATION MODEL PERFORMANCE", 11.5, True, CYAN)])
    table(s, Inches(7.55), Inches(1.85), Inches(4.95), Inches(2.6),
          ["Metric", "Value"],
          [["Prevalence, admission level", "26.2%"],
           ["Base rate at 12 h, row level", "0.0465"],
           ["AUROC at 12 h", "0.797"],
           ["AUPRC at 12 h", "0.214"],
           ["AUPRC ÷ no-skill floor", "4.59×"],
           ["C-index", "0.771  [0.736 – 0.806]"],
           ["Episode PPV at 12 h", "0.134"],
           ["Episode lift at 12 h", "2.88×"],
           ["Patient recall at 12 h", "0.944"],
           ["Features retained after pruning", "80"]],
          hi=(4, 7), col_w=[2.9, 2.05], fs=9.5)
    txt(s, Inches(7.55), Inches(4.6), Inches(4.95), Inches(2.3), [
        ("READING THE PRECISION FIGURE", 11.5, True, CYAN),
        ("Episode PPV of 0.134 is lower than the NEWS2 model's 0.331, on a base rate "
         "that is 2.6 times lower. Precision is bounded by prevalence, so the two "
         "figures are not directly comparable.", 10.5, False, TEXT_LIGHT),
        ("Lift divides prevalence out and is comparable across targets: 2.88× for the "
         "escalation model against 2.75× for the NEWS2 model — equivalent "
         "discrimination on an outcome that is actionable within the unit.",
         10.5, True, GREEN, True),
        ("The following three slides show how precision is raised from this baseline "
         "without changing the model.", 10.5, False, TEXT_MUTED, True),
    ])

    # ═════════════════════════════════════════════════════════════════════
    # 17  FEATURE EVIDENCE
    # ═════════════════════════════════════════════════════════════════════
    s = new_slide("Which Physiology Drives the Prediction",
                  kicker="PART 2 — THE ESCALATION-OF-CARE MODEL")
    card(s, Inches(0.6), Inches(1.2), Inches(12.15), Inches(5.75))
    pic(s, "features.png", Inches(0.85), Inches(1.45), Inches(6.4))
    txt(s, Inches(7.5), Inches(1.4), Inches(5.05), Inches(5.5), [
        ("METABOLIC ACIDOSIS LEADS", 11.5, True, CYAN),
        ("Anion gap occupies the first, second, third and fifth positions among "
         "individual features. It measures the accumulation of unmeasured acids from "
         "anaerobic metabolism, and it rises while heart rate and blood pressure remain "
         "within acceptable limits — identifying the patient who is deteriorating "
         "before the vital signs reflect it.", 10.5, False, TEXT_LIGHT),
        ("Renal markers form the largest single family, consistent with renal "
         "replacement therapy being a constituent event and with renal hypoperfusion "
         "preceding overt circulatory failure.", 10.5, False, TEXT_LIGHT, True),
        ("VITAL SIGNS REMAIN CENTRAL", 11.5, True, CYAN, True),
        ("Systolic pressure, heart rate, shock index, oxygen saturation, respiratory "
         "rate, mean arterial pressure, temperature and diastolic pressure together "
         "account for 32.5% of total gain — the largest block in the model.",
         10.5, False, TEXT_LIGHT),
        ("Individual vital features appear lower in a ranked list because each variable "
         "is represented by roughly nineteen window-and-statistic combinations, which "
         "divides its importance among them, whereas anion gap is represented by "
         "twelve. Importance is therefore aggregated by variable family — the only "
         "comparison that is valid when variables have unequal feature counts.",
         10.5, False, TEXT_MUTED, True),
        ("AGREEMENT WITH PUBLISHED FINDINGS", 11.5, True, CYAN, True),
        ("Laboratory and organ-function markers account for 37% of gain against 32.5% "
         "for vital signs. Published intensive-care work reports the same ordering, and "
         "identifies anion gap, lactate, bicarbonate, urea and pH specifically among "
         "the strongest predictors of deterioration — an independent corroboration of "
         "this feature profile.", 10.5, False, GOLD),
    ])

    # ═════════════════════════════════════════════════════════════════════
    # 18  PRECISION AND FALSE POSITIVES: THE ARITHMETIC
    # ═════════════════════════════════════════════════════════════════════
    s = new_slide("How Precision and False Positives Are Determined",
                  kicker="PART 2 — THE ESCALATION-OF-CARE MODEL")
    card(s, Inches(0.6), Inches(1.2), Inches(12.15), Inches(5.75))
    txt(s, Inches(0.9), Inches(1.4), Inches(11.6), Inches(1.2), [
        ("THE IDENTITY", 12, True, CYAN),
        ("Precision  =  ( sensitivity × prevalence )  ÷  [ ( sensitivity × prevalence )"
         "  +  ( false-positive rate × ( 1 − prevalence ) ) ]", 13.5, True, GOLD),
        ("Precision therefore depends on three quantities: the sensitivity chosen, the "
         "prevalence of the outcome, and the model's false-positive rate. Only the "
         "third is a property of the model.", 11, False, TEXT_LIGHT),
    ])
    table(s, Inches(0.9), Inches(2.8), Inches(11.6), Inches(1.2),
          ["Horizon", "Prevalence",
           "Specificity required for precision 0.30 at 80% sensitivity",
           "Specificity achieved", "What that would require"],
          [["12 hours", "0.0465", "0.909", "0.610",
            "removing 77% of current false positives while retaining every true positive"],
           ["24 hours", "0.0948", "0.805", "0.561",
            "removing 55% of current false positives while retaining every true positive"]],
          hi=(0, 1), col_w=[1.2, 1.4, 4.1, 1.7, 3.2], fs=9.5)
    txt(s, Inches(0.9), Inches(4.35), Inches(11.6), Inches(2.55), [
        ("Precision at high sensitivity is constrained by prevalence rather than by "
         "model quality.", 13, True, RED),
        ("The three levers that do move it, all applied in this system:", 11.5, True,
         CYAN, True),
        ("1.    A longer prediction horizon.  The twenty-four-hour horizon has twice "
         "the prevalence of the twelve-hour horizon, which raises the ceiling itself "
         "rather than trading along the existing curve — and simultaneously increases "
         "the available warning time.", 11, False, TEXT_LIGHT),
        ("2.    The alerting rule.  The hysteresis latch consolidates brief threshold "
         "excursions, which are disproportionately false, without altering the "
         "condition for raising an alert.", 11, False, TEXT_LIGHT),
        ("3.    The presentation order.  Ranking the alarms already raised concentrates "
         "true events at the top of the worklist without withholding anything from the "
         "clinician.", 11, False, TEXT_LIGHT),
        ("Six independent modelling directions — additional laboratory features, an "
         "alternative survival formulation, parameter sharing, two neural "
         "architectures, and an alternative input representation — each changed AUROC "
         "by less than 0.01. That is the evidence that the constraint is not a "
         "modelling one.", 10.5, False, TEXT_MUTED, True),
    ])

    # ═════════════════════════════════════════════════════════════════════
    # 19  WORKLIST RE-RANKING
    # ═════════════════════════════════════════════════════════════════════
    s = new_slide("Raising Precision by Ordering the Worklist",
                  kicker="PART 2 — THE ESCALATION-OF-CARE MODEL")
    card(s, Inches(0.6), Inches(1.2), Inches(12.15), Inches(5.75))
    pic(s, "precision_at_k.png", Inches(0.85), Inches(1.5), Inches(6.5))
    txt(s, Inches(7.6), Inches(1.4), Inches(4.95), Inches(5.5), [
        ("THE METHOD", 11.5, True, CYAN),
        ("Every alarm continues to be displayed. They are ordered by a severity score "
         "derived from the model's own hazard curve, so that the alarms most likely to "
         "precede a real escalation are presented first.", 10.5, False, TEXT_LIGHT),
        ("THE SEVERITY SCORE", 11.5, True, CYAN, True),
        ("Two quantities are combined, both taken from the hazard curve the model "
         "already produces:", 10.5, False, TEXT_LIGHT),
        ("Cumulative hazard,  Λ(t) = −log S(t).  Unlike a probability this is unbounded "
         "and additive, so differences between patients remain meaningful across the "
         "whole range rather than being compressed near zero.",
         10.5, False, TEXT_LIGHT, True),
        ("Hazard-curve shape.  The seven interval hazards are estimated independently, "
         "so the profile across them carries information that the single cumulative "
         "probability discards. A concentrated profile indicates risk focused in a "
         "specific interval; a flat profile indicates a stable patient. Measured across "
         "profile deciles, precision ranges from 0.08 to 0.36.",
         10.5, False, TEXT_LIGHT, True),
        ("RESULT", 11.5, True, GOLD, True),
        ("Of the leading 135 alarms, 57% precede a real escalation, against 19% across "
         "all 1,359. Precision on the leading quarter is 43%.", 11, True, GREEN),
        ("This is the only method available that raises precision at no cost to "
         "detection, because it changes the order in which alarms are presented rather "
         "than which alarms exist.", 10.5, False, TEXT_LIGHT, True),
    ])

    # ═════════════════════════════════════════════════════════════════════
    # 20  THREE-TIER ALERTING
    # ═════════════════════════════════════════════════════════════════════
    s = new_slide("Three-Tier Alerting With a Statistical Confidence Guarantee",
                  kicker="PART 2 — THE ESCALATION-OF-CARE MODEL")
    card(s, Inches(0.6), Inches(1.2), Inches(12.15), Inches(5.75))
    txt(s, Inches(0.9), Inches(1.35), Inches(5.75), Inches(5.5), [
        ("THE PRINCIPLE", 12, True, CYAN),
        ("A binary alert forces a decision at every patient-hour, including those where "
         "the model has no real basis for one. A three-tier output allows the system to "
         "decline: page when the evidence supports an alert, clear when it supports no "
         "alert, and refer to a review list otherwise.", 10.5, False, TEXT_LIGHT),
        ("HOW THE TIERS ARE DERIVED", 12, True, CYAN, True),
        ("Conformal prediction, computed on a held-out half of the calibration split. "
         "For each true event a nonconformity score of 1 − p is recorded; for each "
         "non-event, p. The (1 − α) quantile of each set becomes a threshold, and for a "
         "new patient-hour each label is admitted into the output set if its score "
         "falls below the corresponding threshold.", 10.5, False, TEXT_LIGHT),
        ("{ 1 }  only            PAGE        a clinician is notified\n"
         "{ 0 }  only            CLEAR       no alert is raised\n"
         "{ 0, 1 }  both        WATCH       review list, no notification\n"
         "{ }  neither          WATCH       the observation is unlike anything\n"
         "                                              seen in calibration",
         10, True, GOLD, True),
        ("WHY THIS RATHER THAN A CONFIDENCE CUT-OFF", 12, True, CYAN, True),
        ("The single parameter α sets the abstention rate directly and carries a "
         "distribution-free guarantee: the true label is contained in the emitted set "
         "at least (1 − α) of the time, whatever the underlying distribution. An "
         "arbitrary confidence cut-off offers no such guarantee — on this data a fixed "
         "cut-off would have abstained on 0.5% of alerts, an effectively inert rule.",
         10.5, False, TEXT_LIGHT),
        ("The calibration split is halved by patient, so the quantiles are computed on "
         "data the probability calibration never saw. That separation is what makes the "
         "guarantee valid.", 10, False, TEXT_MUTED, True),
    ])
    pic(s, "conformal.png", Inches(6.85), Inches(1.55), Inches(5.75))
    txt(s, Inches(6.85), Inches(4.65), Inches(5.75), Inches(2.25), [
        ("INTERPRETING THE SETTING", 11.5, True, CYAN),
        ("At α = 0.20, one quarter of patient-hours are paged with precision 0.160 and "
         "lift 3.45×, against 2.88× for the unfiltered baseline. 89% of deteriorating "
         "patients are still paged, and the remaining 20% of events appear on the "
         "review list rather than being discarded — nothing is suppressed.",
         10.5, False, TEXT_LIGHT),
        ("Lowering α raises the precision of the paged tier and increases the "
         "proportion of events routed to review. The choice of α is a clinical "
         "judgement about how the review list will be used in practice, and the "
         "guarantee makes that trade explicit rather than leaving it implicit in a "
         "threshold.", 10.5, False, GOLD, True),
    ])

    # ═════════════════════════════════════════════════════════════════════
    # 21  RECOMMENDED CONFIGURATION
    # ═════════════════════════════════════════════════════════════════════
    s = new_slide("Recommended Configuration", kicker="PART 2 — RECOMMENDATION")
    card(s, Inches(0.6), Inches(1.2), Inches(6.6), Inches(5.75))
    txt(s, Inches(0.85), Inches(1.35), Inches(6.1), Inches(0.5), [
        ("ESCALATION TARGET   •   24-HOUR HORIZON   •   HYSTERESIS LATCH   •   "
         "RANKED WORKLIST", 10, True, CYAN)])
    table(s, Inches(0.85), Inches(1.9), Inches(6.1), Inches(2.7),
          ["Measure", "NEWS2 model, 12 h", "Recommended"],
          [["Episode lift", "2.75×", "2.73×"],
           ["Patient recall", "0.967", "0.970"],
           ["Alert episodes", "2,069", "912"],
           ["Median warning time", "7.0 hours", "11.0 hours"],
           ["Episode PPV, all alarms", "0.331", "0.259"],
           ["Episode PPV, leading 10%", "—", "0.570"],
           ["Actionable within the unit", "no", "yes"]],
          hi=(2, 3, 5), col_w=[2.6, 1.85, 1.65], fs=10)
    txt(s, Inches(0.85), Inches(4.75), Inches(6.1), Inches(2.15), [
        ("At equivalent lift and equivalent detection, the recommended configuration "
         "produces 56% fewer distinct alarms and 57% more warning time, on an outcome "
         "that identifies a decision not yet taken.", 11.5, True, GREEN),
        ("Precision across all alarms is lower because prevalence is 2.4 times lower. "
         "Lift is the quantity that is comparable across targets, and it is "
         "equivalent.", 10.5, False, TEXT_MUTED, True),
        ("Precision on the leading tenth of the worklist — the alarms a clinician "
         "addresses first — is 0.570.", 10.5, True, GOLD, True),
    ])
    card(s, Inches(7.5), Inches(1.2), Inches(5.25), Inches(5.75))
    txt(s, Inches(7.75), Inches(1.35), Inches(4.75), Inches(0.5), [
        ("ALTERNATIVE OPERATING POINTS", 10.5, True, CYAN)])
    pic(s, "esc_operating.png", Inches(7.75), Inches(1.88), Inches(4.75))
    txt(s, Inches(7.75), Inches(4.5), Inches(4.75), Inches(2.4), [
        ("If a higher precision figure is required, reducing the sensitivity target to "
         "60% yields episode PPV 0.321 and lift 3.39× — 23% above the NEWS2 model — "
         "with 8.7 hours of warning and patient recall 0.864.",
         10.5, False, TEXT_LIGHT),
        ("The operating point and the alerting rule are independent levers and they "
         "compose: the latch improves precision at every sensitivity setting without "
         "affecting detection.", 10.5, False, GOLD, True),
        ("Selecting between these points is a clinical decision about the acceptable "
         "balance between missed events and alarm volume, and is presented as a curve "
         "rather than a single recommendation.", 10.5, False, TEXT_MUTED, True),
    ])

    # ═════════════════════════════════════════════════════════════════════
    # 22  LIMITATIONS
    # ═════════════════════════════════════════════════════════════════════
    s = new_slide("Limitations and Validation Status")
    card(s, Inches(0.6), Inches(1.2), Inches(6.15), Inches(5.75))
    txt(s, Inches(0.86), Inches(1.4), Inches(5.6), Inches(5.5), [
        ("VALIDATION STATUS", 12, True, RED),
        ("Single institution, single unit type, single era from 2008 to 2019. No "
         "external validation on an independent cohort. Under TRIPOD and PROBAST "
         "reporting standards this constitutes model development rather than validated "
         "performance.", 11, False, TEXT_LIGHT, True),
        ("No prospective or silent-mode evaluation has been performed. Every reviewed "
         "system that reported both retrospective and live performance showed "
         "degradation, in one case from 0.95 to 0.63 AUROC.", 11, False, TEXT_LIGHT, True),
        ("No human-factors evaluation, no defined clinical override protocol, and no "
         "regulatory assessment.", 11, False, TEXT_LIGHT, True),
        ("STRUCTURAL COVERAGE LIMIT", 12, True, RED, True),
        ("1,516 patients deteriorate a median of sixteen minutes after admission. Two "
         "vital-sign readings cannot exist before their event at any look-back setting, "
         "so they lie outside the reach of an hourly model entirely. The limiting factor "
         "is observation frequency rather than model design, and addressing it requires "
         "continuous monitoring data that the source dataset does not provide.",
         11, False, TEXT_LIGHT),
    ])
    card(s, Inches(7.05), Inches(1.2), Inches(5.7), Inches(5.75))
    txt(s, Inches(7.3), Inches(1.4), Inches(5.2), Inches(5.5), [
        ("STATISTICAL LIMITS", 12, True, RED),
        ("The escalation model shows a train-to-test C-index gap of 0.056 on 1,475 "
         "event-positive admissions. Reducing the feature count from 371 to 80 closed "
         "only 18% of that gap, indicating the binding constraint is sample size rather "
         "than model complexity; it is unlikely to fall below approximately 0.05 on a "
         "cohort of this size.", 11, False, TEXT_LIGHT, True),
        ("Confidence intervals on the C-index are approximately 0.040 wide, so "
         "differences smaller than that are described as indistinguishable rather than "
         "as improvements.", 11, False, TEXT_LIGHT, True),
        ("DEPENDENCE ON CLINICAL PRACTICE", 12, True, RED, True),
        ("The timing of an escalation partly reflects clinician judgement, so the target "
         "is not purely physiological. Death and renal replacement therapy are less "
         "discretionary than the timing of vasopressor initiation, and NEWS2 "
         "performance is reported alongside as a secondary outcome to keep the "
         "comparison balanced.", 11, False, TEXT_LIGHT),
        ("The safety of the review tier depends on the review list being examined in "
         "practice. That is an operational assumption which has not been evaluated, and "
         "it should be tested before the three-tier output is used clinically.",
         11, False, TEXT_LIGHT, True),
    ])

    out = os.path.join(HERE, "final_presentation_deck.pptx")
    prs.save(out)
    print(f"SUCCESS: {len(prs.slides._sldIdLst)} slides -> {out}")
    print(f"charts embedded from {CHARTS}")


if __name__ == "__main__":
    create_deck()
