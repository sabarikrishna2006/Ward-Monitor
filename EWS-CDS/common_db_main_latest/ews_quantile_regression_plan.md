# EWS Time-to-Event (Survival) Model — Formulation & Results

**Foqal CareOS Early Warning System · CCU deterioration prediction**
Author: Sabari Krishna R · For review by Prof. Gautam Shroff & clinical guide
Status: retrospective **CCU proof-of-concept** on MIMIC-IV v3.1 (not yet ward-deployable)

---

## 1. Why we moved from binary classification to survival analysis
The earlier formulation (`ml_plan.md`) predicted a **binary** "deteriorate within 6 h?" label.
That framing (a) throws away *when* deterioration happens, (b) suffers temporal-ambiguity noise
at the horizon boundary, and (c) forces a single fixed horizon. Per Prof. Gautam's directive we
now predict the **time to the next deterioration** as a **survival / time-to-event** problem, with
**quantile uncertainty bands** ("expected deterioration in ~T h, 5–95% band [a, b]").

## 2. Scope decision — CCU only (honest about the data)
MIMIC-IV charts routine vitals **only during ICU stays**; there are no general-ward vitals. Our
product's general ward therefore **keeps its rules-based NEWS2**, and the **ML model is trained and
validated on the CCU (Coronary Care Unit) population only** — the medical cardiology unit that
matches our CCU use-case. (CVICU, the cardiac-*surgery* ICU, is excluded: its escalations are
post-operative, not medical HF deterioration.) General-ward ML is deferred to Medanta prospective
data. **Cohort: 10,775 adult CCU stays; 735 (6.8%) with dilated cardiomyopathy (DCM).**

## 3. The deterioration EVENT (the survival label)
1. **Treatment escalation** — first start of a vasopressor/inotrope (norepinephrine, epinephrine,
   dopamine, dobutamine, phenylephrine, milrinone, vasopressin), invasive/non-invasive
   **ventilation**, or **RRT** (`inputevents`/`procedureevents`). *Objective; the clinician acted.*
2. **Sustained NEWS2 ≥ 7** — high-risk band held over **2 consecutive hourly readings** (a clinical
   action threshold; the 2-reading rule suppresses async-charting artifacts).

**Death is a COMPETING RISK**, not folded in: a patient who dies **without** a preceding
deterioration is **censored at death** (cause-specific). Rationale — a slow, preventable death is
*preceded* by escalation/NEWS2≥7 (so we still catch it), whereas a sudden unpredictable death has no
vital-sign precursor and must not be forced onto a vitals model.

> **Why not pure NEWS2-crossing?** A label defined *purely* by NEWS2 would be **circular** (we'd
> predict NEWS2 from NEWS2) and would inherit NEWS2's blind spot for DCM's slow congestive drift.
> Anchoring the event mostly on *treatment escalation* (an action independent of the input vitals)
> fixes this. Soft NEWS2 crossings (4→5, 5→6) are kept as **features**, never as the event.

**Observed on the real cohort:** 6,844 / 10,775 stays reach a deterioration event (4,167 by
escalation, 5,424 by sustained NEWS2≥7); 1,471 in-hospital deaths (competing).

## 4. Dataset construction (sliding window)
- Irregular MIMIC charting → **regular hourly grid** per stay (last-value-per-hour + ≤6 h
  forward-fill). NEWS2 replayed every hour with the **production scorer** (`news2.py`, a faithful
  copy of `calculate_news2`).
- **Anchors** at every hour `t` from `intime + 6 h` onward; look-back window **W = 6 h**.
- **Label** at `t`: `T_t = τ − t`, `event = 1` if a deterioration event follows within the
  **H_max = 24 h** horizon; else right-censored (`event = 0`) at discharge / competing-death /
  horizon. Anchors already at NEWS2 ≥ 7, or with < 2 vitals in the window, are excluded.
- **Result:** 149,779 anchors from 5,439 stays; **13.5% event rate**; unique stays with a
  deterioration event = 1,704. (Anchors from one stay overlap heavily → we report **cluster-bootstrap
  CIs by patient**, and *unique* event counts, to avoid false precision.)

## 5. Features `X_t` — two clinical axes (all strictly from `[t−W, t]`)
**Acute (NEWS2) axis:** per-vital `last/mean/std/min/max/rate/Δ-from-admission` for HR, RR, SpO₂,
SBP, DBP, temperature; NEWS2 value/mean/max/rate; hours-in-band; O₂/FiO₂/consciousness flags.
**Congestion / substrate axis (the DCM-specific layer):** weight trend Δ24 h/Δ72 h with **ESC
(≥2 kg/3 d) & HFSA (≥0.9 kg/1 d)** flags; urine-output rate; **NT-proBNP/BNP, troponin, lactate,
sodium, creatinine→eGFR (CKD-EPI 2021), hemoglobin, potassium, INR, platelets** (carry-forward +
missingness); cardiac-rhythm (AF / VT-VF) flags. **Context:** age, sex, hours-since-admission,
DCM indicator, **Charlson comorbidity index** (Quan 2005). **94 model features.**

> Data-availability note: NT-proBNP is present for ~95% of anchors (BNP's older assay is ~85%
> missing — expected); labs modelled with explicit missingness (informative). Features MIMIC lacks
> (HRV, CMR strain/scar, bio-impedance, structured NYHA) are documented as **Medanta-only** upgrades.

## 6. Model — XGBoost AFT + calibrated quantiles
- **Primary:** XGBoost **`survival:aft`** (Barnwal, Cho & Hocking 2022) — handles right-censoring
  via `[lower, upper]` label bounds (`[T,T]` for events, `[T,∞)` for censored), using **every**
  patient. Distribution chosen by validation nloglik: **logistic** (0.693) beat normal (0.737) and
  extreme (0.697).
- **Uncertainty band:** parametric AFT quantiles AND **split-conformal** calibration of the median
  on a held-out calibration split (empirically-targeted ~90% coverage) — because the raw parametric
  tail is not trustworthy under heavy censoring.
- **Ablations / baselines (pre-registered gates):** NEWS2-acute-only AFT; **Cox PH**; a trivial
  **NEWS2-slope heuristic** the model must beat; and a `reg:quantileerror` model (uncensored only —
  documents that pure quantile regression *cannot* use censored data).
- **Split:** `GroupShuffleSplit` by `subject_id` → 70/15/15 (no patient leakage). DCM rows
  up-weighted 3×; metrics reported overall **and** on the held-out DCM subcohort.

## 7. Evaluation protocol
Harrell C-index (+ cluster-bootstrap 95% CI by patient); **alert burden** (PPV / alerts-per-true-
event at fixed 80% sensitivity — the metric that reflects the false-alarm complaint); 5–95%
interval **coverage**; median-time MAE and lead-time; SHAP global importance. **Gates:** (1) beat
the NEWS2-slope heuristic on C-index; (2) beat it on alert burden; (3) coverage ≈ 0.90.

## 8. Results (held-out test patients — 751 subjects, 22,697 anchors, 3,072 events)

**Discrimination & alert burden at fixed 80% sensitivity** (alerts/event = false-alarm load):

| Model | C-index (95% CI) | PPV | Alerts / true event | Specificity |
|-------|------------------|-----|--------------------|-------------|
| **AFT-full (primary)** | **0.752 (0.719–0.784)** | **0.24** | **4.17** | 0.60 |
| AFT — NEWS2-acute only | 0.751 (0.713–0.782) | 0.23 | 4.33 | 0.58 |
| Cox PH (linear baseline) | 0.711 (0.679–0.740) | 0.21 | 4.87 | 0.52 |
| **NEWS2-slope heuristic (must-beat)** | 0.657 (0.636–0.677) | 0.18 | 5.67 | 0.40 |

**DCM subcohort** (1,307 anchors, 161 events) — the model does its *best* here:

| Model | C-index (95% CI) | Alerts / true event | PPV |
|-------|------------------|--------------------|-----|
| **AFT-full** | **0.804 (0.683–0.898)** | **3.62** | 0.28 |
| AFT — NEWS2-only (ablation) | 0.785 (0.657–0.906) | 4.03 | 0.25 |
| NEWS2-slope heuristic | 0.691 (0.599–0.779) | 6.14 | 0.16 |

**Interval coverage** (5–95% band): **conformal 0.905** overall / 0.95 DCM (target ≈0.90) vs
**parametric 0.731** — confirming the raw AFT tail is mis-calibrated and the conformal band is
required. **SHAP top signals:** `news2_mean` ≫ `egfr`, `news2_last`, `on_oxygen`, `resp_rate_mean`,
`sbp_max`, **`urine_rate_24h`**, `heart_rate_last`, `hours_in_band`, `age`, **`rhythm_af`**,
**`charlson`** — i.e. NEWS2 dynamics dominate, but four **congestion/substrate** features
(eGFR, urine rate, AF rhythm, Charlson) rank in the top 12.

### What passes / what to caveat
- **GATE 1 (beat heuristic): PASS** — 0.752 vs 0.657, non-overlapping CIs.
- **GATE 2 (alert burden): PASS** — at 80% sensitivity the model cuts false alarms from **5.67 →
  4.17 alerts/event overall (−26%)** and **6.14 → 3.62 on DCM (−41%)**; PPV +36%/+69%.
- **GATE 3 (coverage): PASS** — conformal 0.905.
- **Congestion axis earns its place *on DCM*** (C 0.785→0.804, alerts 4.03→3.62) but adds little on
  the general CCU population (full≈NEWS2-only overall) — an honest, expected finding.
- **Caveats:** DCM CI is wide (161 events → 0.68–0.90); absolute median-time MAE is poor (~103 h
  overall) because heavy censoring makes the raw median optimistic — so the tool is trustworthy as a
  **risk ranking / near-term alert**, not a literal countdown (we surface the conformal band).

## 9. Honest limitations (read before trusting any number)
- **Retrospective ICU PoC**, not a ward tool. MIMIC (US, 2008–2019) ≠ Medanta; requires prospective
  external validation + recalibration (incl. the `india_news2` thresholds) before clinical use.
- **Effective sample size** is far below the row count (1,704 unique deterioration stays); CIs are
  cluster-bootstrapped by patient for honesty.
- Absolute time-to-event is **optimistically long** under heavy censoring — the model is more
  trustworthy as a *risk ranking / near-term alert* than as a literal countdown; we surface the
  conformal band, not the raw median, at the bedside.
- Consciousness is derived from GCS (imperfect for sedated patients); rhythm is sparsely charted.
- **NYHA is not in MIMIC** — captured at Medanta via the labeling UI for future fine-tuning.

## 10. References
XGBoost AFT (Barnwal 2022); Cox 1972; Fine & Gray 1999; conformal survival (Lei/Candès; Teng 2021);
Harrell 1982 & Antolini 2005; Haider 2020 (D-calibration); NEWS2 (RCP 2017); DCM/HF: Hammersley
(CMR/GLS/LGE), ESC & HFSA weight rules (PMC4777885), Seattle HFM / MAGGIC / Miura.
