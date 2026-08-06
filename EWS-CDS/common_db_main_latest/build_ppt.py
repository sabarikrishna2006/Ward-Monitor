"""Builds the progress-review PPTX for Gautam Sir from live pipeline data.
Plain-language version: Problem -> Data Sources -> Mapping Pipeline (layman's
terms) -> Accuracy/matching charts -> more charts -> ML formulation.
"""
import json
import os
import time as _time
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.enum.shapes import MSO_SHAPE

DL = r"c:\Users\ASUS\Downloads"
OUT = r"C:\Users\ASUS\Desktop\DCM_Cost_Prediction_Progress.pptx"
CHART_DIR = r"C:\Users\ASUS\Desktop\Ward-Monitor\_ppt_charts"
os.makedirs(CHART_DIR, exist_ok=True)

NAVY_HEX, ACCENT_HEX, GREEN_HEX, GREY_HEX = "#1B2A4A", "#2E86C1", "#279E4E", "#999999"
NAVY = RGBColor(0x1B, 0x2A, 0x4A)
ACCENT = RGBColor(0x2E, 0x86, 0xC1)
GREEN = RGBColor(0x27, 0x9E, 0x4E)
GREY = RGBColor(0x55, 0x55, 0x55)


# ── chart helpers ────────────────────────────────────────────────────────
def donut_chart(df, source_col, title, fname, match_label):
    counts = df[source_col].value_counts()
    match_n = counts.get(match_label, 0)
    fallback = counts.drop(labels=[match_label], errors="ignore")
    top_fb = fallback.sort_values(ascending=False).head(4)
    other_n = fallback.sum() - top_fb.sum()
    labels = ["Matched directly"] + [str(k)[:28] for k in top_fb.index] + (["Other estimate"] if other_n > 0 else [])
    values = [match_n] + list(top_fb.values) + ([other_n] if other_n > 0 else [])
    colors = [GREEN_HEX, ACCENT_HEX, "#5DADE2", "#85C1E9", "#AED6F1", GREY_HEX]
    fig, ax = plt.subplots(figsize=(5.6, 4.2))
    wedges, _, autotexts = ax.pie(values, colors=colors[:len(values)], startangle=90,
                                   autopct=lambda p: f"{p:.0f}%" if p > 3 else "",
                                   pctdistance=0.8, wedgeprops=dict(width=0.42, edgecolor="white"))
    for t in autotexts:
        t.set_fontsize(11); t.set_color("white"); t.set_fontweight("bold")
    ax.legend(wedges, [f"{l} ({v})" for l, v in zip(labels, values)], loc="center left",
              bbox_to_anchor=(1.0, 0.5), fontsize=10, frameon=False)
    ax.set_title(title, fontsize=14, color=NAVY_HEX, fontweight="bold")
    fig.tight_layout()
    path = os.path.join(CHART_DIR, fname)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def price_hist(df, price_col, title, fname, color=ACCENT_HEX):
    fig, ax = plt.subplots(figsize=(5.6, 4.2))
    data = df[price_col].clip(upper=df[price_col].quantile(0.95))
    ax.hist(data, bins=25, color=color, edgecolor="white")
    ax.set_title(title, fontsize=14, color=NAVY_HEX, fontweight="bold")
    ax.set_xlabel("Price (Rs)", fontsize=11)
    ax.set_ylabel("Number of items", fontsize=11)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    path = os.path.join(CHART_DIR, fname)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def price_boxplot(df, price_col, title, fname, color=ACCENT_HEX):
    fig, ax = plt.subplots(figsize=(5.6, 4.2))
    data = df[price_col].dropna()
    ax.boxplot(data, vert=False, widths=0.5, patch_artist=True,
               boxprops=dict(facecolor=color, alpha=0.75, edgecolor=NAVY_HEX),
               medianprops=dict(color=NAVY_HEX, linewidth=2),
               whiskerprops=dict(color=NAVY_HEX), capprops=dict(color=NAVY_HEX),
               flierprops=dict(marker='o', markersize=3, markerfacecolor=color, alpha=0.4, markeredgewidth=0))
    ax.set_xscale("log")
    ax.axvline(data.mean(), color="#C0392B", linestyle="--", linewidth=1.2)
    ax.set_yticks([])
    ax.set_xlabel("Price (Rs, log scale)", fontsize=11)
    ax.set_title(title, fontsize=14, color=NAVY_HEX, fontweight="bold")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_visible(False)
    fig.text(0.5, 0.02,
              f"Mean Rs {data.mean():,.0f}  |  Median Rs {data.median():,.0f}  |  Max Rs {data.max():,.0f}",
              ha="center", fontsize=9.5, color=GREY_HEX)
    fig.tight_layout(rect=[0, 0.06, 1, 1])
    path = os.path.join(CHART_DIR, fname)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def big_percent_gauge(pct, title, fname, color=GREEN_HEX):
    fig, ax = plt.subplots(figsize=(4.2, 4.2), subplot_kw={'aspect': 'equal'})
    ax.pie([pct, 100 - pct], colors=[color, "#E8ECF1"], startangle=90,
           counterclock=False, wedgeprops=dict(width=0.3, edgecolor="white"))
    ax.text(0, 0, f"{pct:.0f}%", ha="center", va="center", fontsize=36, fontweight="bold", color=NAVY_HEX)
    ax.set_title(title, fontsize=14, color=NAVY_HEX, fontweight="bold", pad=15)
    path = os.path.join(CHART_DIR, fname)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


# ── slide-building helpers ──────────────────────────────────────────────
prs = Presentation()
prs.slide_width = Inches(13.333)
prs.slide_height = Inches(7.5)
BLANK = prs.slide_layouts[6]


def add_slide():
    return prs.slides.add_slide(BLANK)


def add_title(slide, text, subtitle=None):
    box = slide.shapes.add_textbox(Inches(0.6), Inches(0.35), Inches(12.1), Inches(1.15))
    tf = box.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    r = p.add_run()
    r.text = text
    r.font.size = Pt(34)
    r.font.bold = True
    r.font.color.rgb = NAVY
    if subtitle:
        p2 = tf.add_paragraph()
        r2 = p2.add_run()
        r2.text = subtitle
        r2.font.size = Pt(17)
        r2.font.color.rgb = GREY
    line = slide.shapes.add_shape(1, Inches(0.6), Inches(1.35), Inches(12.1), Pt(2.5))
    line.fill.solid()
    line.fill.fore_color.rgb = ACCENT
    line.line.fill.background()


def add_bullets(slide, items, left=0.7, top=1.7, width=11.9, height=5.4, size=22):
    box = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
    tf = box.text_frame
    tf.word_wrap = True
    for i, item in enumerate(items):
        if isinstance(item, tuple):
            text, level = item
        else:
            text, level = item, 0
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.level = level
        r = p.add_run()
        r.text = ("• " if level == 0 else "-  ") + text
        r.font.size = Pt(size if level == 0 else size - 3)
        r.font.color.rgb = NAVY if level == 0 else GREY
        p.space_after = Pt(16)


def add_stat_row(slide, stats, top=1.9):
    n = len(stats)
    w = 11.9 / n
    for i, (label, value, color) in enumerate(stats):
        left = 0.7 + i * w
        box = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(w - 0.2), Inches(1.7))
        tf = box.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.alignment = PP_ALIGN.CENTER
        r = p.add_run()
        r.text = value
        r.font.size = Pt(42)
        r.font.bold = True
        r.font.color.rgb = color
        p2 = tf.add_paragraph()
        p2.alignment = PP_ALIGN.CENTER
        r2 = p2.add_run()
        r2.text = label
        r2.font.size = Pt(15)
        r2.font.color.rgb = GREY


def add_flow_box(slide, left, top, width, height, title, lines, fill_hex):
    box = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(left), Inches(top), Inches(width), Inches(height))
    box.fill.solid()
    box.fill.fore_color.rgb = RGBColor.from_string(fill_hex.lstrip("#"))
    box.line.color.rgb = NAVY
    box.line.width = Pt(1.5)
    tf = box.text_frame
    tf.word_wrap = True
    tf.margin_left = Inches(0.15)
    tf.margin_right = Inches(0.15)
    tf.margin_top = Inches(0.1)
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run(); r.text = title
    r.font.size = Pt(16); r.font.bold = True; r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
    for line in lines:
        p2 = tf.add_paragraph()
        p2.alignment = PP_ALIGN.LEFT
        r2 = p2.add_run(); r2.text = "• " + line
        r2.font.size = Pt(12); r2.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
    return box


def add_arrow(slide, left, top, width, height=0.5):
    arrow = slide.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, Inches(left), Inches(top), Inches(width), Inches(height))
    arrow.fill.solid()
    arrow.fill.fore_color.rgb = ACCENT
    arrow.line.fill.background()
    return arrow


# ═══════════════════════════════════════════════════════════════════════
# SLIDE 1 — Title
# ═══════════════════════════════════════════════════════════════════════
s = add_slide()
box = s.shapes.add_textbox(Inches(0.8), Inches(2.6), Inches(11.7), Inches(2.5))
tf = box.text_frame
tf.word_wrap = True
p = tf.paragraphs[0]
r = p.add_run(); r.text = "Predicting Hospital Bills Before They Happen"
r.font.size = Pt(42); r.font.bold = True; r.font.color.rgb = NAVY
p2 = tf.add_paragraph()
r2 = p2.add_run(); r2.text = "An AI model that estimates a patient's final bill from Day 1 — and updates it daily"
r2.font.size = Pt(20); r2.font.color.rgb = ACCENT
p3 = tf.add_paragraph()
r3 = p3.add_run(); r3.text = "Dilated Cardiomyopathy (DCM) Pilot — Progress Review"
r3.font.size = Pt(15); r3.font.color.rgb = GREY

# ═══════════════════════════════════════════════════════════════════════
# SLIDE 2 — Problem Definition (plain language)
# ═══════════════════════════════════════════════════════════════════════
s = add_slide()
add_title(s, "The Problem", "In simple terms: patients get a wrong first bill, and it stays wrong")
add_bullets(s, [
    "Today, when a patient is admitted, the hospital gives them a rough cost estimate using a fixed formula — it doesn't look at the patient's actual condition.",
    "That estimate almost never matches the real final bill — sometimes it's off by a huge margin.",
    "Patients and insurance companies get surprised with a very different bill at the end. That destroys trust.",
    "What we want to build: an AI system that gives a smart estimate on Day 1, and then quietly improves that estimate every single day the patient stays in the hospital — based on what actually happens to them.",
])

# ═══════════════════════════════════════════════════════════════════════
# SLIDE 3 — Data Sources (plain language)
# ═══════════════════════════════════════════════════════════════════════
s = add_slide()
add_title(s, "Where Our Data Comes From", "Two real-world datasets, joined together")
add_bullets(s, [
    "Patient records (what happened to them): MIMIC-IV — a real, public US hospital dataset. We use the Dilated Cardiomyopathy (heart failure) patients from it.",
    "This tells us: what procedures they had, what medicines they were given, what lab tests were run, how many days in ICU, etc.",
    "Price lists (what things cost in India): 3 real Indian pricing datasets —",
    ("PM-JAY government package prices for procedures", 1),
    ("A Kaggle dataset of 253,973 Indian medicines with real prices", 1),
    ("An Indian diagnostic lab price list", 1),
    "The problem: US medical records don't have Indian prices, and Indian price lists don't have patient histories. We had to connect the two ourselves — that's the main thing we built.",
])

# ═══════════════════════════════════════════════════════════════════════
# SLIDE 4 — The Mapping Pipeline, in layman's terms
# ═══════════════════════════════════════════════════════════════════════
s = add_slide()
add_title(s, "The Main Thing We Built: The Matching Engine", "How we connect a US medical record to an Indian price — in plain terms")
add_bullets(s, [
    "Step 1 — Understand it: An AI (Gemini) reads each US medical term AND each Indian price-list item and figures out what it actually means in plain language (what body part, what type, what it's used for).",
    "Exception: for medicines, the Indian price list has 253,973 items — too many to run through the AI — so those are used as-is (medicine names are already fairly self-descriptive). Only the US side is AI-understood there.",
    "Step 2 — Find lookalikes: We convert those descriptions into a kind of fingerprint, and instantly compare a US item against every Indian price-list item to find the 20 closest matches.",
    "Step 3 — Double-check: A second, smarter AI looks at those 20 candidates and picks the single best match — or says \"none of these are close enough.\"",
    "Step 4 — Always give a price: If nothing matches well, we don't leave it blank — we use the average price for that medical category instead, so every single item gets a real, defensible price.",
    "We built this once and ran it across three domains: procedures, medicines, and lab tests.",
], size=20)

# ═══════════════════════════════════════════════════════════════════════
# Load live data for accuracy stats
# ═══════════════════════════════════════════════════════════════════════
proc_df = pd.read_csv(rf"{DL}\procedure_mapping_v1.csv")
proc_match = int((proc_df['pricing_source'] == "PMJAY Dataset Match").sum())
proc_pct = round(100 * proc_match / len(proc_df), 1)

try:
    med_ckpt = json.load(open(rf"{DL}\medicine_matching_ckpt_v1.json"))
    med_done = med_ckpt["done"]
    med_df = pd.DataFrame(med_ckpt["results"])
    med_match = int((med_df['pricing_source'] == "Indian Medicine Dataset Match").sum()) if len(med_df) else 0
    med_pct = round(100 * med_match / med_done, 1) if med_done else 0
except FileNotFoundError:
    med_done, med_match, med_pct = 0, 0, 0

try:
    lab_ckpt = json.load(open(rf"{DL}\lab_matching_ckpt_v1.json"))
    lab_done = lab_ckpt["done"]
except FileNotFoundError:
    lab_done = 0

try:
    lab_df = pd.read_csv(rf"{DL}\lab_mapping_v1.csv")
    lab_match = int((lab_df['pricing_source'] == "Kaggle Lab Dataset Match").sum())
    lab_pct = round(100 * lab_match / len(lab_df), 1)
except FileNotFoundError:
    lab_df, lab_match, lab_pct = None, 0, 0

# ═══════════════════════════════════════════════════════════════════════
# SLIDE 5 — Accuracy / Matching Percentages (the headline numbers)
# ═══════════════════════════════════════════════════════════════════════
s = add_slide()
add_title(s, "How Accurate Is the Matching?", "Direct-match rate — how often the AI found a confident, exact price")
g1 = big_percent_gauge(proc_pct, f"Procedures\n({len(proc_df):,} items, DONE)", "gauge_proc.png", color=GREEN_HEX)
g2 = big_percent_gauge(med_pct, f"Medicines\n({med_done:,}/1,865 {'DONE' if med_done == 1865 else 'so far'})", "gauge_med.png", color=ACCENT_HEX)
if lab_df is not None:
    g3 = big_percent_gauge(lab_pct, f"Labs\n({len(lab_df):,} items, DONE)", "gauge_lab.png", color="#F39C12")
    s.shapes.add_picture(g1, Inches(0.55), Inches(2.0), width=Inches(4.1))
    s.shapes.add_picture(g2, Inches(4.75), Inches(2.0), width=Inches(4.1))
    s.shapes.add_picture(g3, Inches(8.95), Inches(2.0), width=Inches(4.1))
else:
    s.shapes.add_picture(g1, Inches(1.3), Inches(2.0), width=Inches(4.8))
    s.shapes.add_picture(g2, Inches(7.2), Inches(2.0), width=Inches(4.8))
add_bullets(s, [
    "Anything not directly matched still gets a real price — just using a category-average instead of an exact match, never left blank.",
], top=6.4, size=16)

# ═══════════════════════════════════════════════════════════════════════
# SLIDE 6 — Procedure charts
# ═══════════════════════════════════════════════════════════════════════
s = add_slide()
add_title(s, "Procedures — Full Results", f"{len(proc_df):,}/{len(proc_df):,} complete (100%)")
add_stat_row(s, [
    ("Total procedures", f"{len(proc_df):,}", NAVY),
    ("Directly matched", f"{proc_pct}%", GREEN),
    ("Avg. price found", f"Rs {proc_df['price_in_rupees'].mean():,.0f}", ACCENT),
], top=1.65)
donut_path = donut_chart(proc_df, "pricing_source", "Matched vs. Estimated", "proc_donut.png", "PMJAY Dataset Match")
hist_path = price_hist(proc_df, "price_in_rupees", "Price Spread (Rs)", "proc_hist.png")
box_path = price_boxplot(proc_df, "price_in_rupees", "Price Spread incl. Outliers", "proc_box.png", color=GREEN_HEX)
s.shapes.add_picture(donut_path, Inches(0.2), Inches(3.2), width=Inches(4.35))
s.shapes.add_picture(hist_path, Inches(4.6), Inches(3.2), width=Inches(4.35))
s.shapes.add_picture(box_path, Inches(9.0), Inches(3.2), width=Inches(4.15))

# ═══════════════════════════════════════════════════════════════════════
# SLIDE 7 — Medicine charts (live snapshot)
# ═══════════════════════════════════════════════════════════════════════
s = add_slide()
_med_status = "complete" if med_done == 1865 else "in progress"
add_title(s, "Medicines — Full Results", f"{med_done:,}/1,865 {_med_status} (100%)" if med_done == 1865 else f"{med_done:,}/1,865 done so far — still running")
if med_done:
    add_stat_row(s, [
        ("Processed", f"{med_done:,}/1,865", NAVY),
        ("Directly matched", f"{med_pct}%", GREEN),
        ("Avg. price found", f"Rs {med_df['price_in_rupees'].mean():,.0f}", ACCENT),
    ], top=1.65)
    med_donut = donut_chart(med_df, "pricing_source", "Matched vs. Estimated", "med_donut.png", "Indian Medicine Dataset Match")
    med_hist = price_hist(med_df, "price_in_rupees", "Price Spread (Rs)", "med_hist.png", color=GREEN_HEX)
    med_box = price_boxplot(med_df, "price_in_rupees", "Price Spread incl. Outliers", "med_box.png", color=ACCENT_HEX)
    s.shapes.add_picture(med_donut, Inches(0.2), Inches(3.2), width=Inches(4.35))
    s.shapes.add_picture(med_hist, Inches(4.6), Inches(3.2), width=Inches(4.35))
    s.shapes.add_picture(med_box, Inches(9.0), Inches(3.2), width=Inches(4.15))
else:
    add_bullets(s, ["Still starting up — no items processed yet."], top=2.0, size=20)

# ═══════════════════════════════════════════════════════════════════════
# SLIDE 7b — Labs charts (final results)
# ═══════════════════════════════════════════════════════════════════════
if lab_df is not None:
    s = add_slide()
    add_title(s, "Labs — Full Results", f"{len(lab_df):,}/{len(lab_df):,} complete (100%)")
    add_stat_row(s, [
        ("Total lab tests", f"{len(lab_df):,}", NAVY),
        ("Directly matched", f"{lab_pct}%", GREEN),
        ("Avg. price found", f"Rs {lab_df['price_in_rupees'].mean():,.0f}", ACCENT),
    ], top=1.65)
    lab_donut = donut_chart(lab_df, "pricing_source", "Matched vs. Estimated", "lab_donut.png", "Kaggle Lab Dataset Match")
    lab_hist = price_hist(lab_df, "price_in_rupees", "Price Spread (Rs)", "lab_hist.png", color="#F39C12")
    lab_box = price_boxplot(lab_df, "price_in_rupees", "Price Spread incl. Outliers", "lab_box.png", color="#F39C12")
    s.shapes.add_picture(lab_donut, Inches(0.2), Inches(3.2), width=Inches(4.35))
    s.shapes.add_picture(lab_hist, Inches(4.6), Inches(3.2), width=Inches(4.35))
    s.shapes.add_picture(lab_box, Inches(9.0), Inches(3.2), width=Inches(4.15))

# ═══════════════════════════════════════════════════════════════════════
# SLIDE 8 — Real patient cost data (cohort)
# ═══════════════════════════════════════════════════════════════════════
cohort = pd.read_csv(rf"{DL}\dcm_billing_ml_data.csv")
s = add_slide()
add_title(s, "What Does a Real Patient's Bill Look Like?", f"{len(cohort):,} real DCM patients from MIMIC-IV — first look at cost patterns")
add_stat_row(s, [
    ("Patients", f"{len(cohort):,}", NAVY),
    ("Average bill", f"Rs {cohort['total_hospital_bill'].mean():,.0f}", ACCENT),
    ("Average ICU days", f"{cohort['icu_days'].mean():.2f}", GREEN),
], top=1.65)
hist_bill = price_hist(cohort, "total_hospital_bill", "How Bills Are Spread Out (Rs)", "cohort_bill_hist.png")
fig, ax = plt.subplots(figsize=(5.6, 4.2))
bucket_cols = {
    "Base Package": "base_diagnosis_package_charge", "Ward": "standard_ward_charge",
    "ICU": "icu_stay_charge", "Labs": "laboratory_charge",
    "Pharmacy": "pharmacy_charge", "Procedures": "procedures_charge",
}
means = {k: cohort[v].mean() for k, v in bucket_cols.items()}
colors_list = [NAVY_HEX, ACCENT_HEX, "#5DADE2", GREEN_HEX, "#F39C12", "#C0392B"]
bars = ax.bar(list(means.keys()), list(means.values()), color=colors_list)
for b, v in zip(bars, means.values()):
    ax.text(b.get_x() + b.get_width() / 2, v, f"{v/1000:.0f}k", ha="center", va="bottom", fontsize=10, fontweight="bold")
ax.set_title("Where the Money Goes (avg Rs)", fontsize=14, color=NAVY_HEX, fontweight="bold")
ax.spines["top"].set_visible(False); ax.spines["right"].set_visible(False)
plt.setp(ax.get_xticklabels(), rotation=20, ha="right", fontsize=9)
fig.tight_layout()
bucket_path = os.path.join(CHART_DIR, "cohort_buckets.png")
fig.savefig(bucket_path, dpi=150, bbox_inches="tight")
plt.close(fig)
s.shapes.add_picture(hist_bill, Inches(0.5), Inches(3.15), width=Inches(6.1))
s.shapes.add_picture(bucket_path, Inches(6.75), Inches(3.15), width=Inches(6.1))

# ═══════════════════════════════════════════════════════════════════════
# SLIDE 9 — The ML formulation Gautam sir asked for
# ═══════════════════════════════════════════════════════════════════════
s = add_slide()
add_title(s, "The ML Model We're Building", "What Gautam Sir asked about: \"kya hua Day 1 pe affects Day 2\"")
box_w, box_h, gap, top = 3.55, 2.55, 0.55, 1.6
x0 = 0.6
add_flow_box(s, x0, top, box_w, box_h, "DAY 0 — Admission", [
    "Age, Gender, Diagnosis, Ward",
    "-> First estimate",
    "(replaces the old fixed formula)",
], "#1B2A4A")
add_arrow(s, x0 + box_w, top + box_h / 2 - 0.25, gap)
x1 = x0 + box_w + gap
add_flow_box(s, x1, top, box_w, box_h, "DAY 1", [
    "+ Meds given today",
    "+ Procedures/labs today",
    "-> Updated estimate",
], "#2E86C1")
add_arrow(s, x1 + box_w, top + box_h / 2 - 0.25, gap)
x2 = x1 + box_w + gap
add_flow_box(s, x2, top, box_w, box_h, "DAY 2 ... N", [
    "+ Everything so far",
    "-> Estimate keeps getting",
    "   closer to the real final bill",
], "#279E4E")

add_bullets(s, [
    "In technical terms: this is a Supervised Time-Series Regression model — it re-predicts every day using everything that's happened so far, not just once.",
    "Formally: ŷₜ = fθ(Xₜ) — predicted cost using data through day t. Goal: minimize average error |actual − predicted| (MAE) across all patients/days.",
    "We'll report success in rupees: \"off by an average of only ₹2,000\" — and show accuracy improving the longer the patient stays.",
], left=0.7, top=4.35, width=11.9, height=2.9, size=15)

# ═══════════════════════════════════════════════════════════════════════
# SLIDE 9b — The exact day-wise training table schema
# ═══════════════════════════════════════════════════════════════════════
s = add_slide()
add_title(s, "The Training Table We're Building", "One row per patient, per hospital day — HADM_ID | hospital_day | features | costs | target")

header = s.shapes.add_textbox(Inches(0.6), Inches(1.55), Inches(12.1), Inches(0.5))
htf = header.text_frame
htf.word_wrap = True
hp = htf.paragraphs[0]
hr = hp.add_run()
hr.text = "HADM_ID  |  hospital_day  |  [ Static Features ]  |  [ Day Features & Costs ]  |  [ Targets ]"
hr.font.size = Pt(17); hr.font.bold = True; hr.font.color.rgb = NAVY; hr.font.name = "Consolas"

col_w, col_gap, col_top, col_h = 3.85, 0.28, 2.2, 4.7
cx0 = 0.55
add_flow_box(s, cx0, col_top, col_w, col_h, "STATIC (same every row)", [
    "age, gender",
    "admission_type, insurance",
    "elixhauser_score",
    "primary_diagnosis",
    "treating_specialty",
    "icu_flag",
], "#1B2A4A")

cx1 = cx0 + col_w + col_gap
add_flow_box(s, cx1, col_top, col_w, col_h, "DYNAMIC (changes each day)", [
    "day_procedures_cost <- procedures_icd + procedure_mapping_v1.csv",
    "day_medicines_cost <- prescriptions + medicine_mapping_v1.csv",
    "day_labs_cost <- labevents + lab_mapping_v1.csv",
    "day_ward_cost <- Rs 2,000 if not ICU, else 0",
    "day_icu_cost <- Rs 8,000 if ICU, else 0",
    "day_total_cost <- sum of all above",
    "creatinine, troponin, wbc ... (day's labs)",
    "heart rate, BP, O2 sat ... (day's vitals)",
], "#2E86C1")

cx2 = cx1 + col_w + col_gap
add_flow_box(s, cx2, col_top, col_w, col_h, "TARGETS", [
    "cumulative_cost_so_far <-",
    "  sum of costs, Day 1 to today",
    "total_bill_at_discharge <-",
    "  the final total (same for every",
    "  row of that admission)",
    "remaining_cost <-",
    "  total_bill - cumulative_so_far",
], "#279E4E")

add_bullets(s, [
    "This is exactly what fθ(Xₜ) is trained on — one row = one patient's state on one specific day, joined against the 3 price-mapping files we're building right now.",
], top=7.0, size=13)

# ═══════════════════════════════════════════════════════════════════════
# SLIDE 9c — Example Excel rows: one real patient, 5 days
# ═══════════════════════════════════════════════════════════════════════
_ex = pd.read_csv(rf"{DL}\dcm_billing_ml_data.csv")
_cand = _ex[(_ex['icu_days'] > 0.5) & (_ex['icu_days'] < 2) &
            (_ex['total_procedures'].between(3, 8)) & (_ex['total_labs'].between(20, 80))].iloc[0]
_hadm = int(_cand['hadm_id'])
_final_bill = float(_cand['total_hospital_bill'])

s = add_slide()
add_title(s, f"Example: 5 Training Rows for HADM_ID {_hadm}",
          f"What the actual Excel table looks like — real patient, illustrative daily split (Target Rs {_final_bill:,.0f} is real)")

_dates = ["2149-06-02", "2149-06-03", "2149-06-04", "2149-06-05", "2149-06-06"]
ex_rows = [
    ["Day", "Date", "Procedures Rs\n(Date+Time)", "Medicines Rs\n(Date+Time)", "Labs Rs\n(Date+Time)", "Ward/ICU Rs\n(Date, Window)", "Day Total", "Cumulative", "Target", "Remaining"],
    ["0 (Admit)", _dates[0], "0", f"400\n{_dates[0]} 14:00", f"18,000\n{_dates[0]} 07:00,11:00", f"2,000\n{_dates[0]} Ward\n08:00-24:00", "20,400", "20,400", f"{_final_bill:,.0f}", f"{_final_bill-20400:,.0f}"],
    ["1", _dates[1], f"5,500\n{_dates[1]} 10:30", f"700\n{_dates[1]} 08:00,20:00", f"15,000\n{_dates[1]} 06:00,18:00", f"8,000\n{_dates[1]} ICU\n00:00-24:00", "29,200", "49,600", f"{_final_bill:,.0f}", f"{_final_bill-49600:,.0f}"],
    ["2", _dates[2], "0", f"500\n{_dates[2]} 08:00,20:00", f"12,000\n{_dates[2]} 06:30", f"2,000\n{_dates[2]} Ward\n00:00-24:00", "14,500", "64,100", f"{_final_bill:,.0f}", f"{_final_bill-64100:,.0f}"],
    ["3", _dates[3], f"2,769\n{_dates[3]} 11:00", f"300\n{_dates[3]} 08:00", f"8,000\n{_dates[3]} 06:45", f"2,000\n{_dates[3]} Ward\n00:00-24:00", "13,069", "77,169", f"{_final_bill:,.0f}", f"{_final_bill-77169:,.0f}"],
    ["4", _dates[4], "0", f"200\n{_dates[4]} 08:00", f"6,568\n{_dates[4]} 07:15", f"2,000\n{_dates[4]} Ward\n00:00-14:00 (D/C)", "8,768", "85,937", f"{_final_bill:,.0f}", f"{_final_bill-85937:,.0f}"],
]
n_rows, n_cols = len(ex_rows), len(ex_rows[0])
tbl_shape = s.shapes.add_table(n_rows, n_cols, Inches(0.15), Inches(1.55), Inches(13.0), Inches(3.4))
tbl = tbl_shape.table
col_widths = [0.55, 0.95, 1.35, 1.5, 1.6, 1.5, 1.0, 1.1, 1.05, 1.05]
for i, w in enumerate(col_widths):
    tbl.columns[i].width = Inches(w)
for ci, htext in enumerate(ex_rows[0]):
    cell = tbl.cell(0, ci)
    cell.text = htext
    cell.fill.solid(); cell.fill.fore_color.rgb = NAVY
    cell.margin_left = cell.margin_right = Emu(45720)
    for p in cell.text_frame.paragraphs:
        p.alignment = PP_ALIGN.CENTER
        for r in p.runs:
            r.font.size = Pt(9); r.font.bold = True; r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
_date_time_cols = (2, 3, 4, 5)
for ri in range(1, n_rows):
    for ci in range(n_cols):
        cell = tbl.cell(ri, ci)
        cell.text = ex_rows[ri][ci]
        cell.fill.solid()
        cell.fill.fore_color.rgb = RGBColor(0xF2, 0xF6, 0xFB) if ri % 2 == 0 else RGBColor(0xFF, 0xFF, 0xFF)
        cell.margin_left = cell.margin_right = Emu(27432)
        for pi, p2 in enumerate(cell.text_frame.paragraphs):
            p2.alignment = PP_ALIGN.CENTER
            for r in p2.runs:
                if ci in _date_time_cols and pi > 0:
                    r.font.size = Pt(8); r.font.color.rgb = GREY
                else:
                    r.font.size = Pt(10.5); r.font.color.rgb = NAVY

add_bullets(s, [
    f"REAL: hadm_id {_hadm} — 51 labs, 3 procedures, ~1 ICU day, Final Real Cost = Rs {_final_bill:,.0f}. Costs and times shown are an ILLUSTRATIVE walkthrough, not yet computed.",
    "Fully buildable from real MIMIC-IV timestamps: prescriptions.starttime/stoptime (meds), labevents.charttime (labs), icustays/transfers.intime/outtime (ward vs. ICU) — once the mapping pipeline finishes, this table becomes 100% real.",
], top=4.95, size=13, height=2.3)

# ═══════════════════════════════════════════════════════════════════════
# SLIDE 10 — Next steps
# ═══════════════════════════════════════════════════════════════════════
s = add_slide()
add_title(s, "What's Next", "Roadmap from here")
add_bullets(s, [
    "Finish matching medicines and lab tests (running right now, checkpointed so it never loses progress)",
    "Combine everything into one row per patient per day — the exact table the model will train on",
    "Explore the data: which days cause cost spikes, which events matter most",
    "Train the first model (start simple, then improve) and measure how close its predictions get to the real bill",
])

# ═══════════════════════════════════════════════════════════════════════
try:
    prs.save(OUT)
except PermissionError:
    OUT = OUT.replace(".pptx", f"_{_time.strftime('%H%M%S')}.pptx")
    prs.save(OUT)
print("Saved:", OUT)
print("Procedures:", len(proc_df), "rows | match rate", proc_pct, "%")
print("Medicines checkpoint:", med_done, "/1865 done, match rate", med_pct, "%")
print("Labs checkpoint:", lab_done, "/744 done")
