"""Builds the progress-review PPTX for Gautam Sir from live pipeline data."""
import json
import os
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.enum.shapes import MSO_SHAPE
from pptx.oxml.ns import qn

DL = r"c:\Users\ASUS\Downloads"
OUT = r"C:\Users\ASUS\Desktop\DCM_Cost_Prediction_Progress.pptx"
CHART_DIR = r"C:\Users\ASUS\Desktop\Ward-Monitor\_ppt_charts"
os.makedirs(CHART_DIR, exist_ok=True)

NAVY_HEX, ACCENT_HEX, GREEN_HEX, GREY_HEX = "#1B2A4A", "#2E86C1", "#279E4E", "#999999"


def donut_chart(df, source_col, title, fname, match_label):
    counts = df[source_col].value_counts()
    match_n = counts.get(match_label, 0)
    fallback = counts.drop(labels=[match_label], errors="ignore")
    top_fb = fallback.sort_values(ascending=False).head(4)
    other_n = fallback.sum() - top_fb.sum()
    labels = ["Direct Match"] + [str(k)[:28] for k in top_fb.index] + (["Other fallback"] if other_n > 0 else [])
    values = [match_n] + list(top_fb.values) + ([other_n] if other_n > 0 else [])
    colors = [GREEN_HEX, ACCENT_HEX, "#5DADE2", "#85C1E9", "#AED6F1", GREY_HEX]
    fig, ax = plt.subplots(figsize=(5.6, 4.2))
    wedges, _, autotexts = ax.pie(values, colors=colors[:len(values)], startangle=90,
                                   autopct=lambda p: f"{p:.0f}%" if p > 3 else "",
                                   pctdistance=0.8, wedgeprops=dict(width=0.42, edgecolor="white"))
    for t in autotexts:
        t.set_fontsize(10); t.set_color("white"); t.set_fontweight("bold")
    ax.legend(wedges, [f"{l} ({v})" for l, v in zip(labels, values)], loc="center left",
              bbox_to_anchor=(1.0, 0.5), fontsize=9, frameon=False)
    ax.set_title(title, fontsize=13, color=NAVY_HEX, fontweight="bold")
    fig.tight_layout()
    path = os.path.join(CHART_DIR, fname)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def price_hist(df, price_col, title, fname, color=ACCENT_HEX):
    fig, ax = plt.subplots(figsize=(5.6, 4.2))
    data = df[price_col].clip(upper=df[price_col].quantile(0.95))
    ax.hist(data, bins=25, color=color, edgecolor="white")
    ax.set_title(title, fontsize=13, color=NAVY_HEX, fontweight="bold")
    ax.set_xlabel("Price (Rs)", fontsize=10)
    ax.set_ylabel("Item count", fontsize=10)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    path = os.path.join(CHART_DIR, fname)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path

NAVY = RGBColor(0x1B, 0x2A, 0x4A)
ACCENT = RGBColor(0x2E, 0x86, 0xC1)
GREY = RGBColor(0x55, 0x55, 0x55)

prs = Presentation()
prs.slide_width = Inches(13.333)
prs.slide_height = Inches(7.5)
BLANK = prs.slide_layouts[6]


def add_slide():
    return prs.slides.add_slide(BLANK)


def add_title(slide, text, subtitle=None):
    box = slide.shapes.add_textbox(Inches(0.6), Inches(0.35), Inches(12.1), Inches(1.0))
    tf = box.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    r = p.add_run()
    r.text = text
    r.font.size = Pt(32)
    r.font.bold = True
    r.font.color.rgb = NAVY
    if subtitle:
        p2 = tf.add_paragraph()
        r2 = p2.add_run()
        r2.text = subtitle
        r2.font.size = Pt(16)
        r2.font.color.rgb = GREY
    line = slide.shapes.add_shape(1, Inches(0.6), Inches(1.25), Inches(12.1), Pt(2.2))
    line.fill.solid()
    line.fill.fore_color.rgb = ACCENT
    line.line.fill.background()


def add_bullets(slide, items, left=0.7, top=1.55, width=11.9, height=5.5, size=18):
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
        r.font.size = Pt(size if level == 0 else size - 2)
        r.font.color.rgb = NAVY if level == 0 else GREY
        p.space_after = Pt(10)


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


def add_stat_row(slide, stats, top=1.7):
    n = len(stats)
    w = 11.9 / n
    for i, (label, value, color) in enumerate(stats):
        left = 0.7 + i * w
        box = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(w - 0.2), Inches(1.6))
        tf = box.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.alignment = PP_ALIGN.CENTER
        r = p.add_run()
        r.text = value
        r.font.size = Pt(40)
        r.font.bold = True
        r.font.color.rgb = color
        p2 = tf.add_paragraph()
        p2.alignment = PP_ALIGN.CENTER
        r2 = p2.add_run()
        r2.text = label
        r2.font.size = Pt(14)
        r2.font.color.rgb = GREY


# ── Slide 1: Title ───────────────────────────────────────────────────────
s = add_slide()
box = s.shapes.add_textbox(Inches(0.8), Inches(2.5), Inches(11.7), Inches(2.5))
tf = box.text_frame
tf.word_wrap = True
p = tf.paragraphs[0]
r = p.add_run(); r.text = "Dynamic Cost Variance Prediction"
r.font.size = Pt(44); r.font.bold = True; r.font.color.rgb = NAVY
p2 = tf.add_paragraph()
r2 = p2.add_run(); r2.text = "Foundational Billing Data Pipeline — Progress Review"
r2.font.size = Pt(22); r2.font.color.rgb = ACCENT
p3 = tf.add_paragraph()
r3 = p3.add_run(); r3.text = "DCM Cohort | MIMIC-IV -> PMJAY / Indian Medicine / Lab Pricing"
r3.font.size = Pt(16); r3.font.color.rgb = GREY

# ── Slide 2: Business Problem ────────────────────────────────────────────
s = add_slide()
add_title(s, "The Business Problem", "Why the hospital's current cost estimates fail patients")
add_bullets(s, [
    "Current process: initial cost estimate is a static, hardcoded formula (PM-JAY package x fixed private multiplier)",
    "The issue: hardcoded estimates ignore real patient history, and medical needs evolve as a stay progresses",
    "Result: large variance between the Day-0 estimate and the actual final bill",
    "The goal — Patient Trust: replace the hardcoded template with an ML model that proactively updates the cost prediction every day of the stay",
    "Communicating cost changes early to patients and insurers (TPA) builds transparency and trust",
])

# ── Slide 3: ML Problem Definition ───────────────────────────────────────
s = add_slide()
add_title(s, "What ML Are We Building?", "Addressing Gautam Sir's point: \"kya hua Day 1 pe affects Day 2\"")
add_bullets(s, [
    "Task type: Supervised Time-Series Regression (Sequential Predictive Model)",
    "Not a single Day-0 prediction — the model re-predicts the final cost every single day of the stay",
    "Target variable: Final Real Cost of the encounter (equivalently, Cost Variance = Final Real Cost - Initial Estimate)",
    "Static Day-0 features: Initial estimate, Age, Gender, Primary Diagnosis, Admission Ward",
    "Dynamic Day-t features: Length of stay so far, new medications today, procedures/labs done today, condition changes, ward/ICU transfers",
    "Day 0 -> Static features predict Initial Estimate. Day 1..N -> Static + cumulative daily events update the Final Cost prediction",
])

# ── Slide 4: Data Strategy Challenge ─────────────────────────────────────
s = add_slide()
add_title(s, "Data Strategy: The Core Challenge", "Why we can't just merge two public datasets")
add_bullets(s, [
    "Need rich, day-by-day clinical timelines -> public billing datasets lack this",
    "Need realistic financial costs -> clinical datasets (MIMIC-IV) lack this due to privacy",
    "Cannot randomly merge datasets at the patient level (\"Data Mismatch\" risk, e.g. a broken-leg patient billed for chemotherapy)",
    "Solution: Itemized Procedure Mapping — MIMIC-IV supplies the clinical timeline for the Dilated Cardiomyopathy (DCM) cohort; Indian pricing datasets (PM-JAY / Kaggle medicine & lab data) act as the Hospital Charge Master",
])

# ── Slide 3b: Day-by-Day Prediction Mechanism (flow diagram) ─────────────
s = add_slide()
add_title(s, "The Prediction Mechanism", "\"Kya hua Day 1 pe affects Day 2\" — how the model updates daily")

box_w, box_h, gap, top = 3.55, 3.6, 0.55, 2.1
x0 = 0.6
add_flow_box(s, x0, top, box_w, box_h, "DAY 0 — Admission", [
    "Initial Generated Estimate",
    "Patient Age, Gender",
    "Primary Diagnosis",
    "Admission Ward",
    "-> Predicts Initial Cost Estimate",
    "(replaces hardcoded formula)",
], "#1B2A4A")
add_arrow(s, x0 + box_w, top + box_h / 2 - 0.25, gap)

x1 = x0 + box_w + gap
add_flow_box(s, x1, top, box_w, box_h, "DAY 1", [
    "Static features (carried fwd)",
    "+ New meds prescribed today",
    "+ Procedures/labs done today",
    "+ Condition changes",
    "+ Ward <-> ICU transfers",
    "-> Updates Final Cost prediction",
], "#2E86C1")
add_arrow(s, x1 + box_w, top + box_h / 2 - 0.25, gap)

x2 = x1 + box_w + gap
add_flow_box(s, x2, top, box_w, box_h, "DAY 2 ... DAY N", [
    "Static features (carried fwd)",
    "+ Cumulative Day 1 events",
    "+ New Day 2+ events",
    "+ Length of stay so far",
    "-> Prediction converges toward",
    "   the true Final Real Cost",
], "#279E4E")

add_bullets(s, [
    "Target variable: Final Real Cost of the encounter (= Cost Variance + Initial Estimate)",
    "This is a Supervised Time-Series Regression problem, not a single-shot prediction — every additional day of real clinical data should sharpen the estimate",
], top=6.05, size=14)

# ── Slide 4b: Data Sources ────────────────────────────────────────────────
s = add_slide()
add_title(s, "Data Sources", "Exactly where every number in this pipeline comes from")
add_bullets(s, [
    ("Clinical timeline — MIMIC-IV (via Google BigQuery, physionet-data.mimiciv_3_1_hosp)", 0),
    ("DCM cohort selected via diagnoses_icd (ICD codes 4254 / I420) -> distinct hadm_id/subject_id admissions", 1),
    ("procedures_icd, prescriptions, labevents, icustays tables give the real per-patient clinical events", 1),
    ("Procedure pricing — PM-JAY Assam Package Rates (pmjay_assam_procedures.csv)", 0),
    ("Government-published package prices per procedure, used as the Indian price reference", 1),
    ("Medicine pricing — Indian Medicine Dataset (Kaggle), 253,973 branded medicines with MRP", 0),
    ("Lab pricing — Indian diagnostic lab price dataset (Kaggle)", 0),
    ("All 3 real-world Indian price lists get matched against the real MIMIC clinical codes item-by-item", 0),
])

# ── Slide 4c: Day-wise view of the cohort ─────────────────────────────────
s = add_slide()
add_title(s, "Day-Wise View: Length of Stay", "Real MIMIC admission dates -> why a Day-0-only estimate fails")
adm = pd.read_csv(rf"{DL}\admissions.csv")
adm["admittime"] = pd.to_datetime(adm["admittime"])
adm["dischtime"] = pd.to_datetime(adm["dischtime"])
adm["los_days"] = (adm["dischtime"] - adm["admittime"]).dt.total_seconds() / 86400.0
adm = adm[adm["los_days"] >= 0]
add_stat_row(s, [
    ("Sample admissions", f"{len(adm)}", NAVY),
    ("Mean length of stay", f"{adm['los_days'].mean():.1f} days", ACCENT),
    ("Max length of stay", f"{adm['los_days'].max():.0f} days", RGBColor(0x27, 0x9E, 0x4E)),
], top=1.55)
los_path = price_hist(adm, "los_days", "Length of Stay Distribution (days)", "los_hist.png", color="#F39C12")
fig, ax = plt.subplots(figsize=(5.6, 4.2))
max_day = int(min(adm["los_days"].max(), 20)) + 1
still_admitted_pct = [100.0 * (adm["los_days"] >= d).sum() / len(adm) for d in range(max_day)]
ax.plot(range(max_day), still_admitted_pct, color=ACCENT_HEX, linewidth=2.5, marker="o", markersize=3)
ax.fill_between(range(max_day), still_admitted_pct, color=ACCENT_HEX, alpha=0.15)
ax.set_title("% of Patients Still Admitted, by Day", fontsize=13, color=NAVY_HEX, fontweight="bold")
ax.set_xlabel("Day of stay", fontsize=10)
ax.set_ylabel("% still admitted", fontsize=10)
ax.spines["top"].set_visible(False)
ax.spines["right"].set_visible(False)
fig.tight_layout()
still_path = os.path.join(CHART_DIR, "still_admitted.png")
fig.savefig(still_path, dpi=150, bbox_inches="tight")
plt.close(fig)
s.shapes.add_picture(los_path, Inches(0.5), Inches(3.05), width=Inches(6.1))
s.shapes.add_picture(still_path, Inches(6.75), Inches(3.05), width=Inches(6.1))

# ── Slide 5: Billing Buckets ──────────────────────────────────────────────
s = add_slide()
add_title(s, "Billing Aggregation Strategy", "Mapping millions of MIMIC micro-events into 4 standard billing buckets")
add_bullets(s, [
    ("Bucket A — Room & Board (ICU/Ward)", 0),
    ("icustays, transfers, chartevents, inputevents -> flat daily ICU/Ward rate bundles nursing, vitals, routine orders", 1),
    ("Bucket B — Itemized Big-Ticket (Procedures & Imaging)", 0),
    ("procedures_icd, hcpcsevents -> explicitly mapped to PM-JAY package prices (this pipeline)", 1),
    ("Bucket C — Pharmacy & Labs", 0),
    ("prescriptions, labevents, microbiologyevents -> mapped to Indian medicine/lab prices (this pipeline)", 1),
    ("Bucket D — Baseline Diagnosis", 0),
    ("diagnoses_icd -> sets the PM-JAY package base rate", 1),
])

# ── Slide 6: Mapping Pipeline Methodology ────────────────────────────────
s = add_slide()
add_title(s, "Mapping Pipeline Methodology", "How each MIMIC item gets an Indian price")
add_bullets(s, [
    "Step 1 — Clinical Enrichment: Gemini Flash extracts structured clinical context (specialty, organ system, active ingredient, route, indication) for every US code",
    "Step 2 — Semantic Embedding: MedCPT (ncbi/MedCPT-Query-Encoder) embeds the enriched clinical text for both the MIMIC item and the full Indian pricing corpus",
    "Step 3 — Candidate Retrieval: cosine similarity surfaces the top 20 closest Indian price-list candidates per MIMIC item",
    "Step 4 — LLM Validation: Gemini Pro reviews the top candidates against hard clinical rules (organ system, intent, route) and returns a best match + confidence score",
    "Step 5 — Threshold + Fallback: matches below the confidence threshold (0.70) fall back to a Specialty/Drug-Class average, then a Global average — so every item always gets a defensible price, never a blank",
])

# ── Slide 7: Progress overview ────────────────────────────────────────────
s = add_slide()
add_title(s, "Progress: 3 Foundational Datasets", "Procedures / Medicines / Labs mapping status")


def load_meta(name):
    try:
        return json.load(open(rf"{DL}\mapping_metadata_{name}_v1.json"))
    except FileNotFoundError:
        return None


proc_df = pd.read_csv(rf"{DL}\procedure_mapping_v1.csv")
proc_match = int((proc_df['pricing_source'] == "PMJAY Dataset Match").sum())

try:
    med_ckpt = json.load(open(rf"{DL}\medicine_matching_ckpt_v1.json"))
    med_done = med_ckpt["done"]
    med_df = pd.DataFrame(med_ckpt["results"])
    med_match = int((med_df['pricing_source'] == "Indian Medicine Dataset Match").sum()) if len(med_df) else 0
except FileNotFoundError:
    med_done, med_match = 0, 0

add_stat_row(s, [
    ("Procedures\nmapped (of 1,515)", f"{len(proc_df)}", RGBColor(0x27, 0x9E, 0x4E)),
    ("Medicines\nprocessed (of 1,865)", f"{med_done}", ACCENT),
    ("Labs\nqueued (744 items)", "0", GREY),
], top=1.9)

add_bullets(s, [
    "Procedures: COMPLETE — 1,515/1,515 MIMIC procedures mapped to PM-JAY packages",
    f"Medicines: IN PROGRESS — {med_done}/1,865 MIMIC drugs mapped to Indian medicine pricing (running overnight, checkpointed — resumes automatically on any interruption)",
    "Labs: QUEUED — runs automatically after medicines completes, same LLM+embedding methodology",
    "Every stage is checkpointed to disk, so the pipeline never restarts from zero even if the process is killed",
], top=3.7, size=17)

# ── Slide 8: Procedure results detail ────────────────────────────────────
s = add_slide()
add_title(s, "Procedure Mapping — Results", "1,515/1,515 complete")
match_pct = round(100 * proc_match / len(proc_df), 1)
add_stat_row(s, [
    ("Total procedures", f"{len(proc_df)}", NAVY),
    ("Direct PM-JAY match", f"{match_pct}%", RGBColor(0x27, 0x9E, 0x4E)),
    ("Avg. mapped price", f"Rs {proc_df['price_in_rupees'].mean():,.0f}", ACCENT),
], top=1.55)
donut_path = donut_chart(proc_df, "pricing_source", "Match vs. Fallback Breakdown", "proc_donut.png", "PMJAY Dataset Match")
hist_path = price_hist(proc_df, "price_in_rupees", "Mapped Price Distribution (Rs)", "proc_hist.png")
s.shapes.add_picture(donut_path, Inches(0.5), Inches(3.05), width=Inches(6.1))
s.shapes.add_picture(hist_path, Inches(6.75), Inches(3.05), width=Inches(6.1))

# ── Slide 8b: Procedure confidence & specialty breakdown ─────────────────
s = add_slide()
add_title(s, "Procedure Mapping — Confidence & Specialty", "From procedure_audit_v1.csv — how the LLM validated each match")
proc_audit = pd.read_csv(rf"{DL}\procedure_audit_v1.csv")

fig, ax = plt.subplots(figsize=(5.6, 4.2))
cat_order = ["High", "Medium", "Low"]
cat_counts = proc_audit["Confidence Category"].value_counts().reindex(cat_order).fillna(0)
cat_colors = [GREEN_HEX, "#F39C12", "#C0392B"]
bars = ax.bar(cat_order, cat_counts.values, color=cat_colors)
for b, v in zip(bars, cat_counts.values):
    ax.text(b.get_x() + b.get_width() / 2, v, f"{int(v)}", ha="center", va="bottom", fontsize=11, fontweight="bold")
ax.set_title("LLM Confidence Category", fontsize=13, color=NAVY_HEX, fontweight="bold")
ax.set_ylabel("Procedure count", fontsize=10)
ax.spines["top"].set_visible(False)
ax.spines["right"].set_visible(False)
fig.tight_layout()
cat_path = os.path.join(CHART_DIR, "proc_confidence.png")
fig.savefig(cat_path, dpi=150, bbox_inches="tight")
plt.close(fig)

fig, ax = plt.subplots(figsize=(5.6, 4.2))
top_spec = proc_audit["Specialty"].value_counts().head(8).sort_values()
ax.barh([str(s)[:22] for s in top_spec.index], top_spec.values, color=ACCENT_HEX)
ax.set_title("Top Specialties (by procedure count)", fontsize=13, color=NAVY_HEX, fontweight="bold")
ax.set_xlabel("Procedure count", fontsize=10)
ax.spines["top"].set_visible(False)
ax.spines["right"].set_visible(False)
fig.tight_layout()
spec_path = os.path.join(CHART_DIR, "proc_specialty.png")
fig.savefig(spec_path, dpi=150, bbox_inches="tight")
plt.close(fig)

s.shapes.add_picture(cat_path, Inches(0.5), Inches(1.65), width=Inches(6.1))
s.shapes.add_picture(spec_path, Inches(6.75), Inches(1.65), width=Inches(6.1))
add_bullets(s, [
    "High confidence (>=0.85) = direct PM-JAY match used as-is. Medium/Low = Specialty-Average fallback pricing applied instead (never left blank).",
], top=6.15, size=13)

# ── Slide 9: Medicine results detail ─────────────────────────────────────
s = add_slide()
add_title(s, "Medicine Mapping — Live Snapshot", f"{med_done}/1,865 processed so far, pipeline still running")
if med_done:
    med_pct = round(100 * med_match / med_done, 1)
    add_stat_row(s, [
        ("Processed so far", f"{med_done}/1865", NAVY),
        ("Direct match rate", f"{med_pct}%", RGBColor(0x27, 0x9E, 0x4E)),
        ("Avg. mapped price", f"Rs {med_df['price_in_rupees'].mean():,.0f}", ACCENT),
    ], top=1.55)
    med_donut = donut_chart(med_df, "pricing_source", "Match vs. Fallback (so far)", "med_donut.png", "Indian Medicine Dataset Match")
    med_hist = price_hist(med_df, "price_in_rupees", "Mapped Price Distribution (Rs)", "med_hist.png", color=GREEN_HEX)
    s.shapes.add_picture(med_donut, Inches(0.5), Inches(3.05), width=Inches(6.1))
    s.shapes.add_picture(med_hist, Inches(6.75), Inches(3.05), width=Inches(6.1))
    add_bullets(s, [f"Snapshot as of last checkpoint — pipeline keeps running and will be refreshed with the latest numbers before presenting."], top=6.85, size=13)
else:
    add_bullets(s, ["No items processed yet — pipeline starting."], top=1.8, size=17)

# ── Slide 9b: Real cohort EDA (from dcm_billing_ml_data.csv) ─────────────
cohort = pd.read_csv(rf"{DL}\dcm_billing_ml_data.csv")

s = add_slide()
add_title(s, "Preliminary Cost Dataset — Real DCM Cohort", f"n = {len(cohort):,} real MIMIC-IV admissions | flat-rate charge master (being replaced by the item-level mapping pipeline)")
add_stat_row(s, [
    ("Patients (hadm_id)", f"{len(cohort):,}", NAVY),
    ("Mean total bill", f"Rs {cohort['total_hospital_bill'].mean():,.0f}", ACCENT),
    ("Mean ICU days", f"{cohort['icu_days'].mean():.2f}", RGBColor(0x27, 0x9E, 0x4E)),
], top=1.55)

hist_bill = price_hist(cohort, "total_hospital_bill", "Total Bill Distribution (Rs)", "cohort_bill_hist.png")

fig, ax = plt.subplots(figsize=(5.6, 4.2))
drivers = ["icu_days", "total_procedures", "total_labs", "cardiac_cath_count", "pharmacy_charge"]
corr = cohort[drivers + ["total_hospital_bill"]].corr()["total_hospital_bill"].drop("total_hospital_bill")
corr = corr.sort_values()
bar_colors = [GREEN_HEX if v >= 0 else "#C0392B" for v in corr.values]
ax.barh([d.replace("_", " ").title() for d in corr.index], corr.values, color=bar_colors)
ax.set_title("Correlation with Total Bill", fontsize=13, color=NAVY_HEX, fontweight="bold")
ax.set_xlabel("Correlation coefficient", fontsize=10)
ax.spines["top"].set_visible(False)
ax.spines["right"].set_visible(False)
fig.tight_layout()
corr_path = os.path.join(CHART_DIR, "cohort_corr.png")
fig.savefig(corr_path, dpi=150, bbox_inches="tight")
plt.close(fig)

s.shapes.add_picture(hist_bill, Inches(0.5), Inches(3.05), width=Inches(6.1))
s.shapes.add_picture(corr_path, Inches(6.75), Inches(3.05), width=Inches(6.1))

# ── Slide 9c: Cost bucket breakdown ───────────────────────────────────────
s = add_slide()
add_title(s, "Cost Bucket Breakdown", "Where the money goes, on average, per DCM admission")
bucket_cols = {
    "Base Diagnosis Package": "base_diagnosis_package_charge",
    "Standard Ward": "standard_ward_charge",
    "ICU Stay": "icu_stay_charge",
    "Laboratory": "laboratory_charge",
    "Pharmacy": "pharmacy_charge",
    "Procedures": "procedures_charge",
}
means = {k: cohort[v].mean() for k, v in bucket_cols.items()}
fig, ax = plt.subplots(figsize=(9.5, 4.6))
labels = list(means.keys())
values = list(means.values())
colors_list = [NAVY_HEX, ACCENT_HEX, "#5DADE2", GREEN_HEX, "#F39C12", "#C0392B"]
bars = ax.bar(labels, values, color=colors_list)
for b, v in zip(bars, values):
    ax.text(b.get_x() + b.get_width() / 2, v, f"Rs {v:,.0f}", ha="center", va="bottom", fontsize=10, fontweight="bold")
ax.set_ylabel("Average Rs per admission", fontsize=11)
ax.set_title(f"Average Bucket Contribution (n={len(cohort):,} admissions)", fontsize=14, color=NAVY_HEX, fontweight="bold")
ax.spines["top"].set_visible(False)
ax.spines["right"].set_visible(False)
plt.setp(ax.get_xticklabels(), rotation=15, ha="right")
fig.tight_layout()
bucket_path = os.path.join(CHART_DIR, "cohort_buckets.png")
fig.savefig(bucket_path, dpi=150, bbox_inches="tight")
plt.close(fig)
s.shapes.add_picture(bucket_path, Inches(1.6), Inches(1.7), width=Inches(10.1))
add_bullets(s, [
    "NOTE: current per-unit rates (Rs 300/lab, Rs 150/med, Rs 2,000/procedure, Rs 15,000/ICU-day) are a placeholder flat charge master",
    "The item-level LLM-validated mapping pipeline (running now) will replace these flat rates with actual PM-JAY / Indian medicine / lab prices per item",
], top=6.5, size=13)

# ── Slide 10: Modeling Plan ───────────────────────────────────────────────
s = add_slide()
add_title(s, "Next: EDA & Modeling Plan", "Once all 3 mapping datasets are complete")
add_bullets(s, [
    ("Exploratory Data Analysis", 0),
    ("Cost distribution histogram across DCM patients — identify expensive outliers", 1),
    ("Cost-driver correlation heatmap (ICU days, cardiac MRIs, labs vs. bill spikes)", 1),
    ("Day-by-day cumulative cost trajectory — find when costs suddenly spike", 1),
    ("Day-0 estimate vs. Final Real Cost variance plot — prove static estimates are failing", 1),
    ("Modeling Strategy", 0),
    ("Baseline: Linear Regression on Day-0 features only (to show why static models fail)", 1),
    ("Primary model: Rolling XGBoost/LightGBM with daily features (cumulative ICU days, procedures/meds today, day of stay)", 1),
    ("Stretch goal: LSTM for sequential daily cost prediction if time allows", 1),
])

# ── Slide 11: Evaluation & Next Steps ────────────────────────────────────
s = add_slide()
add_title(s, "Evaluation Metrics & Timeline", "How we prove it works")
add_bullets(s, [
    "MAE (Mean Absolute Error) in INR — e.g. \"our model predicts the final bill within an average of Rs 2,000\"",
    "Day-wise convergence curve — show prediction accuracy improving as the stay progresses (Day 1 -> Day 5)",
    "Immediate next steps:",
    ("Finish medicine + lab mapping pipeline (running now, checkpointed)", 1),
    ("Join the 3 mapping tables into the daily billing-bucket aggregation (Room & Board / Procedures / Pharmacy-Labs / Diagnosis)", 1),
    ("Generate the Day-by-Day cost trajectory dataset per DCM patient", 1),
    ("Begin EDA once the trajectory dataset is generated", 1),
])

import time as _time
try:
    prs.save(OUT)
except PermissionError:
    OUT = OUT.replace(".pptx", f"_{_time.strftime('%H%M%S')}.pptx")
    prs.save(OUT)
print("Saved:", OUT)
print("Procedures:", len(proc_df), "rows | match rate", match_pct, "%")
print("Medicines checkpoint:", med_done, "/1865 done")
