"""
Central configuration for the EWS survival-ML pipeline.

Everything that the numbered pipeline scripts (00_..04_) share lives here:
BigQuery coordinates, MIMIC-IV itemid vocabularies (verified against
d_items/d_labitems on 2026-07-09), the cohort SQL, and modeling constants.

Nothing here writes or trains — it is pure declaration so every stage agrees on
the same itemids, thresholds, and horizons.
"""
from __future__ import annotations

import os

# Register BigQuery's db_dtypes extension types (dbdate/dbtime) so parquet files
# written from BQ downloads (which store DATE columns as 'dbdate') can be read
# back. All pipeline scripts import config, so this registration is global.
import db_dtypes  # noqa: F401

# ── BigQuery coordinates ────────────────────────────────────────────────────
# Billing project = one where the active IIIT gcloud user has BOTH job-create
# and Storage-Read (readsessions) perms. avid-stone-497321-r3 is Sabari's own
# project and was verified to allow the fast Storage API against physionet-data.
BQ_BILLING_PROJECT = os.getenv("BQ_BILLING_PROJECT", "avid-stone-497321-r3")
BQ_DATA_PROJECT    = os.getenv("BQ_DATA_PROJECT", "physionet-data")
BQ_HOSP = os.getenv("BQ_HOSP_DATASET", "mimiciv_3_1_hosp")
BQ_ICU  = os.getenv("BQ_ICU_DATASET",  "mimiciv_3_1_icu")

def hosp(t: str) -> str:  return f"`{BQ_DATA_PROJECT}.{BQ_HOSP}.{t}`"
def icu(t: str)  -> str:  return f"`{BQ_DATA_PROJECT}.{BQ_ICU}.{t}`"

# ── Data locations (parquet intermediates) ──────────────────────────────────
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)
def dpath(name: str) -> str:  return os.path.join(DATA_DIR, name)

# EWS_TAG lets a run's outputs coexist with earlier runs instead of clobbering
# them (e.g. EWS_TAG=news2 -> anchors_news2.parquet, features_news2.parquet).
# tpath("anchors.parquet") == dpath("anchors.parquet") when TAG is unset.
TAG = os.getenv("EWS_TAG", "")
def tpath(name: str) -> str:
    if not TAG:
        return dpath(name)
    stem, ext = os.path.splitext(name)
    return dpath(f"{stem}_{TAG}{ext}")

# ── Cohort definition ───────────────────────────────────────────────────────
# CCU (medical Coronary Care Unit) ONLY. CVICU is cardiac-SURGERY ICU (post-op
# recovery) — a different population whose escalations are surgical, not medical
# HF deterioration — so it is excluded. ~10.7k CCU stays in MIMIC-IV v3.1.
CAREUNITS = ("Coronary Care Unit (CCU)",)
MIN_AGE = 18
# DCM = dilated cardiomyopathy (ICD-10 I42.0 / ICD-9 425.4). Broader I42* / 425*
# is "cardiomyopathy" — we flag strict DCM for up-weighting + holdout eval.
DCM_ICD10 = ("I420", "I42")     # I420 strict; I42* = cardiomyopathy family
DCM_ICD9  = ("4254", "425")

# ── Vital-sign itemids (chartevents) — from loader.py, MIMIC-IV verified ─────
VITAL_ITEMIDS: dict[str, list[int]] = {
    "heart_rate": [220045],
    "sbp":        [220179, 220050],   # NBP + arterial-line systolic
    "dbp":        [220180, 220051],
    "spo2":       [220277],
    "resp_rate":  [220210],
    "temp_c":     [223762],           # Temperature Celsius
    "temp_f":     [223761],           # Temperature Fahrenheit  -> convert to C
    "weight_kg":  [224639, 226512],   # Daily Weight + Admission Weight (congestion)
}
GCS_TOTAL_ITEMID = 226755             # GCS Total -> AVPU/consciousness proxy
O2_FLOW_ITEMID   = 223834             # O2 flow (L/min) -> air_or_oxygen flag
FIO2_ITEMID      = 223835             # Inspired O2 fraction (richer O2 signal)
HEART_RHYTHM_ITEMID = 220048          # categorical rhythm (SR/AF/VT...) best-effort
ALL_VITAL_ITEMIDS = sorted({
    i for ids in VITAL_ITEMIDS.values() for i in ids
} | {GCS_TOTAL_ITEMID, O2_FLOW_ITEMID, FIO2_ITEMID, HEART_RHYTHM_ITEMID})

# Urine output (outputevents) — fluid status / congestion
URINE_ITEMIDS = [226559, 226560, 226561, 226563, 226584, 227488, 227489]

# ── Lab itemids (labevents) — DCM/HF substrate + severity ───────────────────
LAB_ITEMIDS: dict[str, list[int]] = {
    "potassium":   [50971],
    "creatinine":  [50912],
    "lactate":     [50813],
    "inr":         [51237],
    "bnp":         [50963],
    "nt_probnp":   [51221],           # NT-proBNP (folded with BNP as congestion marker)
    "troponin_t":  [51003],
    "sodium":      [50983],
    "hemoglobin":  [51222],
    "platelets":   [51265],
}
ALL_LAB_ITEMIDS = sorted({i for ids in LAB_ITEMIDS.values() for i in ids})

# ── Escalation-therapy itemids (define the deterioration EVENT) ──────────────
# Verified in d_items 2026-07-09.
VASOPRESSOR_ITEMIDS = [221289, 221653, 221662, 221749, 221906, 221986, 222315]
#                      epi     dobut  dopa   phenyl norepi milri  vasopressin  (inputevents)
VENT_ITEMIDS = [225792, 225794]        # invasive + non-invasive ventilation (procedureevents)
RRT_ITEMIDS  = [225802, 225803, 225805, 225809, 225955, 225441]  # CRRT/CVVHD/PD/CVVHDF/SCUF/HD
# NOTE: 224270 (Dialysis Catheter) deliberately EXCLUDED — line placement, not RRT therapy.
ESCALATION_INPUT_ITEMIDS = VASOPRESSOR_ITEMIDS
ESCALATION_PROC_ITEMIDS  = VENT_ITEMIDS + RRT_ITEMIDS

# ── CCU-SPECIFIC ESCALATION THERAPIES (added 2026-07-30) ────────────────────
# The lists above were chosen for a GENERAL deterioration model and are badly
# incomplete for a cardiology unit. Verified against d_items on 2026-07-30, with
# stay counts measured on this exact 10,775-stay CCU cohort.
#
# CRITICAL GOTCHA: 00_extract_cohort.py filters inputevents/procedureevents to
# ESCALATION_*_ITEMIDS, so data/inputevents.parquet and data/procedureevents.parquet
# contain ONLY the therapies already in the old definition. A filtered extract
# makes its own definition look complete -- these itemids required a d_items query
# to find, and require a RE-EXTRACTION to use.

# Mechanical circulatory support -- ~6% of this CCU and previously 100% absent.
# For cardiogenic shock this is THE escalation; a patient rescued with an IABP
# instead of norepinephrine was invisible to the old definition.
MCS_ITEMIDS = [
    224272,   # IABP line                    522 stays  4.8%
    228169,   # Impella Line                 122 stays  1.1%
    229529,   # ECMO Inflow Line              11 stays  0.1%
    229530,   # ECMO Outflow Line             11 stays  0.1%
]
# Unambiguous acute-deterioration events (procedureevents, category
# "3-Significant Events" / "4-Procedures").
ACUTE_EVENT_ITEMIDS = [
    225466,   # Cardiac Arrest               139 stays  1.3%
    225475,   # Respiratory Arrest            12 stays  0.1%
    225464,   # Cardioversion/Defibrillation  287 stays  2.7%
]
# Airway + rescue procedures. NOTE 224385 (Intubation) is a DISTINCT itemid from
# VENT_ITEMIDS -- some stays log an intubation with no matching ventilation
# procedure, so omitting it loses those patients.
RESCUE_PROC_ITEMIDS = [
    224385,   # Intubation                   623 stays  5.8%
    225449,   # Pericardiocentesis            19 stays  0.2%
    226477,   # Temporary Pacemaker Wires Inserted  53 stays  0.5%
]

# TIER 2 -- deliberately EXCLUDED from the primary target, kept for a sensitivity
# analysis. Amiodarone for rate control in new AF is routine CCU care, not
# deterioration; including ~10% of stays' worth of routine antiarrhythmic would
# inflate prevalence with normal practice. Alteplase is ambiguous between planned
# STEMI lysis and rescue thrombolysis.
AMBIGUOUS_ESCALATION_INPUT_ITEMIDS = [
    221347, 230034, 229654, 228339,   # Amiodarone (4 formulations)  ~1,385 stays
    225945,                            # Lidocaine                      297 stays
    221319,                            # Alteplase (TPA)                 75 stays
]

# The full extraction list for the re-pull (task: re-extract escalation events).
ESCALATION_PROC_ITEMIDS_EXT = (
    VENT_ITEMIDS + RRT_ITEMIDS + MCS_ITEMIDS + ACUTE_EVENT_ITEMIDS + RESCUE_PROC_ITEMIDS
)
ESCALATION_INPUT_ITEMIDS_EXT = VASOPRESSOR_ITEMIDS + AMBIGUOUS_ESCALATION_INPUT_ITEMIDS

# An escalation occurring at/near CCU admission is not a prediction -- the event is
# concurrent with the first observation. Measured on this cohort: median time to
# first escalation is 1.07h, 21.6% of stays escalate inside 2h, and 3.9% arrive
# already escalated. Those are handled by an ADMISSION RULE (alert immediately, no
# model); the model is trained and evaluated only on escalations after this cutoff.
ESCALATION_MIN_HOURS = 2.0

# Multi-window feature engine. 2h = acute resolution, 6h = current baseline,
# 12h = the patient's own longer-run baseline. 4h and 8h are deliberately omitted:
# they are subsets of the 12h window (recombinations, not new observations).
LOOKBACK_WINDOWS = [2, 6, 12]


# ══════════════════════════════════════════════════════════════════════════════
# EXPANDED EXTRACTION (added 2026-07-30)
#
# EVERY local parquet was extracted filtered for the NEWS2 target: chartevents to
# ALL_VITAL_ITEMIDS (the 7 NEWS2 parameters) and labevents to 10 labs. So the whole
# feature substrate was selected to compute NEWS2 -- and a filtered extract makes
# its own feature set look complete. Coverage below is MEASURED on this exact
# 10,775-stay CCU cohort via d_items/d_labitems, not assumed.
# ══════════════════════════════════════════════════════════════════════════════

# --- Hemodynamics. MAP is the single most important shock variable and we were
# APPROXIMATING it as (SBP + 2*DBP)/3 while the measured value sat unused at 98.3%.
HEMO_ITEMIDS = {
    220181: "NIBP mean",                  # 98.3%, 56 rows/stay  <- better covered than SBP/DBP
    220052: "Arterial BP mean",           # 26.7%, 72 rows/stay
}

# --- Labs as charted in CHARTEVENTS (the nursing flowsheet), not labevents.
# The flowsheet duplicates lab results at the bedside with far better ICU coverage
# than labevents, ~5-6 readings/stay, so these are genuine TREND features.
# HCO3 and anion gap are entirely new and are direct metabolic-acidosis markers --
# the classic precursor of circulatory collapse.
FLOWSHEET_LAB_ITEMIDS = {
    227442: "Potassium (serum)",  220645: "Sodium (serum)",   220602: "Chloride (serum)",
    220615: "Creatinine (serum)", 225624: "BUN",              227443: "HCO3 (serum)",
    227073: "Anion gap",          220621: "Glucose (serum)",  220545: "Hematocrit",
    220228: "Hemoglobin",         220635: "Magnesium",        227457: "Platelet Count",
    220546: "WBC",                225625: "Calcium non-ionized", 225677: "Phosphorous",
    227467: "INR",                227465: "Prothrombin time", 227429: "Troponin-T",
    223830: "PH (Arterial)",
}   # all >=95.8% except INR/PT 88.5%, troponin-T 55.1%, arterial pH 35.6%

# --- Neurological. We currently hold only GCS TOTAL (226755); the components are
# charted at 99.1% and motor response is the most prognostic of the three.
NEURO_ITEMIDS = {
    223901: "GCS - Motor Response",  220739: "GCS - Eye Opening",
    223900: "GCS - Verbal Response", 227346: "Mental status",
}

# --- "Nurse worry" signals. The alarm limits a nurse SETS, and how often they
# check parameters, encode clinical concern that no vital VALUE carries. The JAMIA
# 2024 review of 14 deployed systems explicitly lists a purpose-built "nurse worry
# factor" among the features that helped. All ~99% covered. This is DETERIO's
# "time since last measured" idea in a richer form.
NURSE_CONCERN_ITEMIDS = {
    220046: "Heart rate Alarm - High", 220047: "Heart Rate Alarm - Low",
    223769: "SpO2 Alarm - High",       223770: "SpO2 Alarm - Low",
    224161: "Resp Alarm - High",       224162: "Resp Alarm - Low",
    223751: "NIBP Alarm - High",       223752: "NIBP Alarm - Low",
    224641: "Alarms On",               224168: "Parameters Checked",
    226253: "SpO2 Desat Limit",
}

# --- Frailty / functional status (Braden scale components, 98.2%).
FRAILTY_ITEMIDS = {
    224054: "Braden Sensory Perception", 224057: "Braden Mobility",
    224056: "Braden Activity",           224055: "Braden Moisture",
    224058: "Braden Nutrition",          224059: "Braden Friction/Shear",
}

# --- Invasive monitors: too sparse to use as VALUES, but their PRESENCE is itself
# informative -- somebody floated a PA catheter because they were worried.
# Used as presence/duration flags only.
INVASIVE_MONITOR_ITEMIDS = {
    220074: "Central Venous Pressure",          # 19.9%
    220059: "PA Pressure systolic",             # 11.6%
    220060: "PA Pressure diastolic",            # 11.6%
    220061: "PA Pressure mean",                 # 11.5%
    225674: "Mixed Venous O2% Sat",             # 13.1%
    223772: "SvO2",                             # 8.6%
    226063: "Venous O2 Pressure",               # 27.4%
}

# --- DELIBERATELY EXCLUDED: ventilator settings (220339 PEEP set, 224685/224684/
# 224686 tidal volume, 224700 total PEEP). They only exist AFTER intubation, and
# intubation IS an event in the escalation target -- including them leaks the
# outcome. Their coverage (~27%) is exactly the ventilated fraction, which is the
# giveaway.
LEAKY_POST_ESCALATION_ITEMIDS = {
    220339: "PEEP set", 224685: "Tidal Volume (observed)",
    224684: "Tidal Volume (set)", 224686: "Tidal Volume (spontaneous)",
    224700: "Total PEEP Level",
}

EXTRA_CHART_ITEMIDS = sorted(set(
    list(HEMO_ITEMIDS) + list(FLOWSHEET_LAB_ITEMIDS) + list(NEURO_ITEMIDS)
    + list(NURSE_CONCERN_ITEMIDS) + list(FRAILTY_ITEMIDS)
    + list(INVASIVE_MONITOR_ITEMIDS) + [226531]     # Admission Weight (lbs)
))

# --- Labs only available in LABEVENTS (not duplicated to the flowsheet).
# Coverage is per-admission; lactate at 64% is usable as a FEATURE but too sparse
# and too clinician-ordering-dependent to define an EVENT.
EXTRA_LAB_ITEMIDS = {
    50813: "Lactate",          # 64.0%, 8.2 rows/adm
    50885: "Bilirubin, Total", # 72.1%
    50820: "pH",               # 62.1%
    50821: "pO2",              # 60.8%
    50818: "pCO2",             # 60.7%
    50802: "Base Excess",      # 60.7%
    50862: "Albumin",          # 56.8%
    51006: "Urea Nitrogen",    # 99.2%
}

# ── INFUSION DYNAMICS ───────────────────────────────────────────────────────
# In a CCU, changes to continuous drips precede acute escalation: nitroglycerin
# weaned as pressure falls, furosemide escalated for congestion, fluid rate raised.
# Coverage measured on this cohort.
#
# THIS IS AN ALLOW-LIST, NOT A GENERIC "on_continuous_iv_infusion" FLAG. A generic
# flag would leak the outcome three ways, so the exclusions below are ASSERTED in
# code (see 00d_extract_infusions.py) rather than merely intended.
INFUSION_ALLOWED_ITEMIDS = {
    225158: "NaCl 0.9%",                  # 63.3%
    220949: "Dextrose 5%",                # 56.3%
    225152: "Heparin Sodium",             # 31.8%
    227523: "Magnesium Sulfate (Bolus)",  # 29.8%
    227522: "KCL (Bolus)",                # 16.0%
    222056: "Nitroglycerin",              # 12.8%
    228340: "Furosemide (Lasix) 250/50",  # 10.8%
}

# Never features. Each would leak the escalation target.
INFUSION_FORBIDDEN_ITEMIDS = {
    # (a) vasopressors/inotropes ARE the target -- a generic infusion flag includes them
    221906: "Norepinephrine", 221662: "Dopamine", 221749: "Phenylephrine",
    221653: "Dobutamine", 222315: "Vasopressin", 221289: "Epinephrine",
    221986: "Milrinone",
    # (b) induction/sedation agents are given AT intubation, and intubation is an
    #     event -- their start is essentially concurrent with the outcome
    222168: "Propofol", 225942: "Fentanyl (Concentrate)", 221668: "Midazolam (Versed)",
    # (c) transfusion is arguably an escalation in its own right
    225168: "Packed Red Blood Cells",
}

# ── Modeling constants ──────────────────────────────────────────────────────
LOOKBACK_H = 6            # feature look-back window W
STRIDE_H   = 1            # anchor stride
HMAX_H     = 24           # primary administrative censoring cap (also report 48)
HMAX_ABLATION_H = 48
SUSTAINED_READINGS = 2    # NEWS2>=7 must persist >= this many consecutive readings
MIN_VITALS_IN_WINDOW = 2  # anchor needs >=2 vital timestamps in [t-W, t]
NEWS2_HIGH_BAND = 2       # band index for score>=7 (see news2.news2_band)

# Quantiles for the uncertainty band
QUANTILES = [0.05, 0.50, 0.95]

RANDOM_SEED = 42

# ── Focused NEWS2-only base model (2026-07 review: single event, single feature
# family — no DCM/congestion axis, no labs). Feature-name prefixes selected from
# the full features.parquet produced by 02_build_features.py.
NEWS2_FEATURE_PREFIXES = (
    "news2_",                                   # NEWS2 score dynamics
    "heart_rate_", "resp_rate_", "spo2_", "sbp_", "dbp_", "temperature_",
    "hours_in_band", "on_oxygen", "not_alert", "fio2_",
)
CONTEXT_FEATURES = ["age", "is_female", "hours_since_adm", "hours_of_history"]
# Candidate actionable horizons (hours) evaluated for the cutoff analysis.
# v1 ordinal/discrete-time hazard model cutpoints (plan §3): c_0=0 < c_1=2 < ... < c_7=24.
HORIZONS_H = [2, 4, 6, 9, 12, 18, 24]
