# EWS ML Problem Formulation Plan
## Sabari's Patient Deterioration Early Warning System

---

## Context

Gautam's directive (meeting 2026-07-02): before writing a single line of ML code, formulate the prediction problem mathematically with:
- What exactly is being predicted (the target variable)
- For whom, at what time, using what inputs
- How the label is constructed from retrospective MIMIC-IV data
- Whether the problem is classification, regression, or survival analysis
- How to evaluate the model

The EWS system already computes NEWS2 scores from live vitals and has a placeholder `ml_risk` field in the frontend. The ML model will replace that placeholder with a real, trained risk probability.

Deliverable for Thursday: mathematical formulation posted on Slack. Deliverable for tomorrow: PPT-style presentation slides to Gautam covering the full formulation.

---

## Part 1: Mathematical Problem Formulation

### 1.1 Entities and Notation

| Symbol | Meaning |
|--------|---------|
| `p` | A patient (identified by `hadm_id`) |
| `t` | A prediction time point (discrete, hourly) |
| `x_p(t)` | Feature vector for patient `p` at time `t` — vitals + derived features |
| `X_p(t)` | Feature matrix: all `x_p(s)` for `s ∈ [t - W, t]` (the lookback window) |
| `W` | Lookback window width (how far back we look at history) |
| `H` | Prediction horizon (how far into the future we are predicting) |
| `y_p(t)` | Binary label: did patient `p` deteriorate within H hours of time `t`? |
| `f_θ` | The ML model with parameters θ |
| `ŷ_p(t)` | Model's predicted probability of deterioration |

---

### 1.2 Task Definition

**The Prediction Task (one sentence):**

> Given a patient's vital signs observed over the last `W` hours, predict whether a clinically significant deterioration event will occur within the next `H` hours.

**Formal statement:**

```
Predict:   ŷ_p(t) = f_θ(X_p(t))  ∈ [0, 1]

Where:     ŷ_p(t) ≈ P(deterioration event in (t, t+H] | X_p(t))
```

This is **binary classification** — not regression, not survival analysis.

**Why binary classification (not survival analysis)?**

Survival analysis (DeepSurv, DeepHit) is theoretically richer but:
- Requires precise event timestamps from MIMIC-IV (ICU transfer time-stamps available but noisier)
- Outputs a survival curve, not a single clinical alarm score
- All top commercial systems (eCARTv5 AUROC 0.895, Epic DI, InSight) use binary classification
- Clinicians need a single probability score per patient, not a survival curve

Binary classification produces exactly that: "This patient has a 78% chance of deteriorating in the next 6 hours."

**Why this is better than the current rule-based NEWS2 system:**

NEWS2 is a static threshold on current vitals only. The ML model captures:
- Trends over time (a rising HR is worse than a stable HR at the same value)
- Interaction between vitals (HR + low BP together = worse than each alone)
- Patient history (how long have they been at this level?)
- AUROC gap: NEWS2 achieves ~0.67-0.85; eCARTv5 achieves 0.895 on the same task

---

### 1.3 Deterioration Event Definition (the Label)

**The label is a NEWS2 stage transition (stage worsening):**

The system has three clinically meaningful stages based on NEWS2 score:

| Stage | NEWS2 Score | Clinical Meaning | NYHA Analogy |
|-------|-------------|-----------------|--------------|
| **Normal** | 0 – 4 | Stable; routine monitoring | Class 1–2: no significant limitation |
| **Moderate** | 5 – 6 | At risk; urgent review needed | Class 2–3: marked limitation on exertion |
| **Critical** | ≥ 7 | High risk; emergency response | Class 3–4: symptoms at rest or minimal exertion |

**Formal label construction:**

```
Define the stage function:
  stage(score) = Normal   if score ∈ [0, 4]
                 Moderate if score ∈ [5, 6]
                 Critical if score ≥ 7

Define deterioration:
  event_p(t, t+H) = 1  if stage(NEWS2_p(t+H)) > stage(NEWS2_p(t))
                    0  otherwise

Binary label:
  y_p(t) = event_p(t, t+H)

Where H = 6 hours (primary prediction horizon)
```

**Concrete deterioration examples:**
- Normal (0-4) → Moderate (5-6): **early deterioration** — model should alert for close monitoring
- Normal (0-4) → Critical (≥7): **rapid deterioration** — model should alert immediately
- Moderate (5-6) → Critical (≥7): **primary target** — clinically most actionable; CCU patients are likely already in Moderate range

**Why this label is better than ICU-transfer/death composite:**

| Criterion | Stage-Transition Label | ICU-Transfer/Death Composite |
|-----------|----------------------|------------------------------|
| Computable from vitals only | ✅ Yes — NEWS2 from HR, SpO2, RR, SBP, Temp | ❌ Needs EHR event records |
| Available in MIMIC-IV | ✅ Yes — compute from `chartevents` | ⚠️ Transfer timestamps exist but noisy |
| Clinical interpretability | ✅ Direct: "patient's stage worsened" | ⚠️ Confounded by bed availability |
| Captures early warning | ✅ Catches deterioration before ICU transfer | ❌ Only triggers at crisis point |
| Used in our deployed system | ✅ Matches existing staging UI | ❌ Not reflected in product |

**Additional label: any single parameter = 3 (low-medium borderline)**
As per current code logic, a single vital sign scoring 3 in NEWS2 (e.g., SpO2 ≤91%) triggers an urgent review even if total score is low. This can be a secondary label.

**The formal binary label:**

```
y_p(t) = 1  if stage(NEWS2_p(t+H)) > stage(NEWS2_p(t))
y_p(t) = 0  otherwise

Where H = 6 hours (primary); also test H = 24 hours
```

---

### 1.4 Sliding Window Dataset Construction

**How to build training examples from raw MIMIC-IV time-series:**

```
For each patient p in the cohort:
    For each hour t ∈ {t_admit + W, t_admit + W + 1, ..., t_discharge}:

        FEATURE MATRIX:  X_p(t) = vitals + derived features from [t - W, t]
        LABEL:           y_p(t) = 1 if deterioration in (t, t+H]  else 0
        CENSORED:        if patient discharged before t+H without event:
                            exclude this window (right-censored)

Window parameters (literature-backed):
    W  = 6 hours  (lookback; captures a clinical shift's worth of trend)
    H  = 6 hours  (primary prediction horizon; actionable within a shift)
    stride = 1 hour
```

**Three-window diagram:**

```
──────────────────────────────────────────────────────────────▶ time
│←─── W = 6h lookback ───→│        │←── H = 6h horizon ──→│
│  features extracted here │   t   │    label defined here  │
│ X_p(t) = f(vitals[t-6,t])│       │ y_p(t) = event in here │
```

**Expected dataset size from MIMIC-IV (CCU patients only):**
- MIMIC-IV CCU/cardiac ICU admissions: ~8,000–15,000 stays (filtered from ~50,000 total ICU stays)
- Average CCU stay ~3-4 days = ~72–96 hours
- Each stay generates ~66–90 windows (minus first 6h lookback)
- Total: ~600,000–1.2 million labeled training examples
- Estimated event rate (stage transition in 6h): ~10-20% (higher than ICU-transfer composite because stage transitions are more frequent)

Note: If CCU admissions alone produce too few examples, broaden to all cardiac/step-down ICU types in MIMIC-IV.

**Critical: patient-level train/test split**

The split must be on `subject_id` (patient), not on individual windows. Otherwise, windows from the same patient appear in both train and test → data leakage → inflated metrics.

```
Split: 70% train / 15% validation / 15% test
       by subject_id (patient-level grouping)
```

Also preferred: **temporal split** — train on MIMIC years 2008-2017, test on 2018-2019. This reflects real deployment conditions (model trained on past, tested on future).

---

### 1.5 Feature Space

Features are extracted from each 6-hour lookback window. All features are computed from data available at prediction time `t` — no lookahead.

#### Core Vital Signs (raw values at each hourly timestep)

| Variable | MIMIC-IV itemid | Clinical Meaning |
|----------|-----------------|------------------|
| Heart Rate (HR) | 220045 | Cardiac function |
| SpO2 | 220277 | Oxygen saturation |
| Respiratory Rate (RR) | 220210 | Breathing effort |
| Systolic Blood Pressure (SBP) | 220179 | Cardiovascular pressure |
| Temperature | 223761 | Infection/inflammation |

#### Rolling Statistical Features (per vital, per time window)

For each vital `v` and each lookback sub-window `w ∈ {1h, 3h, 6h}`:

| Feature | Formula | Clinical Meaning |
|---------|---------|-----------------|
| Mean | `μ(v, w) = mean(v[t-w:t])` | Average level |
| Standard deviation | `σ(v, w) = std(v[t-w:t])` | Variability |
| Min / Max | `min/max(v[t-w:t])` | Extremes reached |
| Slope (trend) | `β from OLS on (timestamps, values)` | Direction of change |
| Rate of change | `(v[t] - v[t-1]) / Δt` | Instantaneous velocity |
| Last observed value | `v[t]` | Current state |

For 5 vitals × 6 features × 3 time windows = **90 rolling features**

#### Derived Clinical Score

| Feature | Formula |
|---------|---------|
| NEWS2 score | Already computed in `main.py:calculate_news2()` — use as a feature |
| NEWS2 slope | Change in NEWS2 over last 3h |

#### Patient Context Features

| Feature | Source |
|---------|--------|
| Age | `active_patients.anchor_age` |
| Gender | `active_patients.gender` |
| Hours since admission | `chart_time - admit_time` |
| Ward location | `active_patients.ward_location` (CCU vs GW) |

#### Missingness Indicators

For each vital `v`: binary flag `m_v(t) = 1` if vital was actually measured at time `t`.
Missingness is informative in EHR data — clinicians measure more frequently when worried.

**Total feature vector: ~100-110 features per prediction time point**

---

### 1.6 Model Architecture

#### Recommended Architecture: XGBoost (Primary)

```
Input:   feature_vector ∈ ℝ^{~100}   (flattened rolling statistics per patient)
Model:   Gradient Boosted Decision Trees (XGBoost)
Output:  P(deterioration in next 6h) ∈ [0, 1]

Why XGBoost first:
- MIMIC-IV 2024-2025 benchmarks: XGBoost matches/beats LSTM on tabular features
- Fast to train, interpretable via SHAP values
- eCARTv5 (AUROC 0.895, best-in-class) uses gradient boosted trees
- Robustness to missing values built-in
```

#### Secondary Architecture: LSTM (if time permits)

```
Input:   X_p(t) ∈ ℝ^{W × d}    (time series: 6 timesteps × ~20 raw features)
Encoder: 2-layer LSTM (128 hidden units, dropout=0.3)
Output:  h_T ∈ ℝ^128   (final hidden state)
Head:    Dense(64, ReLU) → Dense(1, Sigmoid)
Output:  P(deterioration) ∈ [0, 1]

Why LSTM second:
- Captures temporal dynamics (trend patterns) beyond what rolling stats capture
- But slower to train, needs more data
- Start with XGBoost to establish baseline, add LSTM if time and data allow
```

---

### 1.7 Loss Function

**Standard binary cross-entropy will not work well** because the event rate (~5-15%) creates class imbalance. Most windows will be labeled 0 (no event), and a naive model that always outputs 0 would achieve >85% accuracy while being clinically useless.

**Recommended: Focal Loss**

```
ℒ_focal = -(1/N) Σ_i  α_t · (1 - ŷ_i)^γ · log(ŷ_i)

Where:
  α   = 0.75  (weight for minority positive class; upweights deterioration events)
  γ   = 2.0   (focusing parameter; downweights easy negatives the model already gets right)
  ŷ_i = predicted probability for window i
  
For XGBoost: use scale_pos_weight = N_negative / N_positive  (equivalent effect)
```

**Why focal loss (from literature):**
- Standard in clinical deterioration ML (arXiv 2603.14719 uses α=0.75, γ=2.0 on MIMIC-IV)
- Prevents the model from "cheating" by always predicting the majority class
- SMOTE/oversampling is explicitly NOT recommended — 2022 JAMIA study and 2025 systematic review show it worsens calibration in clinical prediction

---

### 1.8 Evaluation Metrics

**Report ALL of these — not just AUROC:**

| Metric | Formula | What It Measures |
|--------|---------|-----------------|
| **AUROC** | Area under ROC curve | Overall discrimination; primary comparability metric |
| **AUPRC** | Area under precision-recall curve | Performance on imbalanced data (more informative than AUROC when event rate <10%) |
| **Sensitivity at 90% Specificity** | True positive rate when false positive rate = 10% | Clinically interpretable: "catch X% of deteriorations with Y% false alarms" |
| **Time-to-Detection** | Hours before clinical event the model first alarms | Clinical actionability: how much lead time does the model give? |
| **Calibration (ECE)** | Expected Calibration Error | Does P=0.7 actually mean 70% of those patients deteriorated? |
| **Alert burden** | Alerts per patient per day | Operational feasibility: alarm fatigue risk |

**Baseline comparisons required (Gautam will ask):**

| Baseline | AUROC (expected) | What we're trying to beat |
|----------|-----------------|---------------------------|
| Predict all 0 (never alarm) | 0.50 | The floor |
| NEWS2 threshold ≥7 | ~0.67-0.85 | The current rule system |
| Logistic Regression on raw vitals | ~0.70-0.75 | Simple ML baseline |
| XGBoost (our primary model) | ~0.78-0.89 | Target |
| LSTM (secondary) | ~0.80-0.91 | Stretch target |
| eCARTv5 (literature best) | 0.895 | Industry gold standard |

---

## Part 2: Training Data Pipeline (MIMIC-IV)

### 2.1 Cohort Selection

```sql
-- Inclusion criteria:
--   Adult patients (age >= 18)
--   CCU/cardiac ICU admissions only (first_careunit LIKE '%CCU%' OR '%Cardiac%')
--   ICU stay >= 24 hours (need enough time-series to form windows)
--   Has at least 10 vital sign measurements across the stay

-- Exclusion criteria:
--   Death within first 6 hours (can't form a meaningful prediction window)
--   Missing >60% of vital signs across the stay
--   Stage already Critical (NEWS2 ≥7) at admission (can't worsen further — or predict separately)
```

**MIMIC-IV tables needed:**
- `icu.icustays` — ICU admission/discharge times; filter on `first_careunit`
- `icu.chartevents` — Hourly vitals (itemid mapping in Section 1.5)
- `hosp.admissions` — Age, gender, death timestamps
- (NO need for `hosp.transfers` — label is computed from vitals alone)

**Key advantage of this cohort + label design:**
Label construction (`y_p(t) = stage transition`) requires ONLY `icu.chartevents` vitals. No need for ICU transfer records or death records. The model is fully self-contained in vital signs.

### 2.2 Label Assignment (Stage Transition from Vitals)

```python
# For each patient p and each prediction time t:
# Compute NEWS2 at time t (current stage)
# Compute NEWS2 at time t+H (future stage)
# Label is 1 if future stage is worse

def get_stage(news2_score):
    if news2_score >= 7:
        return 2  # Critical
    elif news2_score >= 5:
        return 1  # Moderate
    else:
        return 0  # Normal

# news2(t) — computed from vitals at time t using existing calculate_news2()
# news2(t+H) — computed from vitals H hours later (from MIMIC-IV chartevents)

y_t = int(get_stage(news2_at_t_plus_H) > get_stage(news2_at_t))

# Handle missing future vitals:
#   If vitals not available at t+H: forward-fill with last known values
#   If no vitals within 4h of t+H: mark as censored, exclude from training
```

### 2.3 Feature Extraction

```python
# Per patient, per hour:
# 1. Resample chartevents to 1-hour bins (forward-fill, max gap = 4h)
# 2. For each prediction time t, extract last W=6 hours
# 3. Compute rolling stats: mean, std, min, max, slope per vital
# 4. Compute NEWS2 score at time t (reuse existing calculate_news2() function)
# 5. Add patient context: age, gender, hours-since-admission
# 6. Add missingness indicators
```

---

## Part 3: PPT Presentation Structure (Tomorrow)

### Recommended Slide Deck: 10 slides

**Slide 1: Title**
- "Patient Deterioration Prediction: ML Problem Formulation"
- Sabari Krishna, EWS System — Foqal CareOS
- Date: July 3, 2026

**Slide 2: Clinical Motivation (Why This Matters)**
- Current system: NEWS2 score (rule-based, computed from current vitals only)
- Problem: Does not capture trends over time; no probability estimate
- Goal: Replace rule-based threshold with ML-predicted probability
- Quote from literature: "NEWS2 AUROC ~0.67-0.85 vs. eCARTv5 AUROC 0.895"
- Visual: system screenshot showing current `ml_risk: placeholder`

**Slide 3: What Are We Predicting? (The Task)**
- One sentence: "Given the last 6 hours of vital signs, predict if the patient will deteriorate in the next 6 hours"
- Visual: the three-window diagram (lookback | NOW | prediction horizon)
- Bullet points: Binary classification (not regression, not survival analysis), output = probability 0-100%

**Slide 4: What Is "Deterioration"? (The Label — Our Unique Formulation)**
- Label = NEWS2 **stage transition**: patient moves from a lower severity stage to a higher one
- Three stages (analogous to NYHA functional class worsening):
  - Normal (NEWS2 0-4) ≈ NYHA Class 1-2
  - Moderate (NEWS2 5-6) ≈ NYHA Class 2-3 (marked limitation)
  - Critical (NEWS2 ≥7) ≈ NYHA Class 3-4 (symptoms at rest)
- Deterioration = stage(NEWS2 at t+H) > stage(NEWS2 at t)
- Key advantage over ICU-transfer label: computable from vitals alone, no external events needed
- Diagram: three-box stage diagram with arrows showing possible transitions

**Slide 5: Mathematical Formulation (The Core)**
- Formal notation of X_p(t), y_p(t), f_θ
- The three-window equation
- Loss function (focal loss with α, γ)
- One slide, clean math, no prose

**Slide 6: Dataset Construction (MIMIC-IV)**
- Sliding window methodology diagram
- Numbers: ~50,000 patients → ~4.5M labeled windows
- Event rate: ~5-15% (composite deterioration)
- Train/validation/test split: 70/15/15 by patient
- Key: patient-level split (not window-level) to prevent data leakage

**Slide 7: Feature Engineering**
- Table of features: 5 core vitals + rolling stats (mean, std, slope, min, max) × 3 time windows
- NEWS2 score as engineered feature
- Missingness indicators
- Patient context: age, gender, ward, hours-since-admit
- Total: ~100-110 features

**Slide 8: Model Architecture**
- Primary: XGBoost (gradient boosted trees)
  - Industry best practice: eCARTv5 uses GBT
  - MIMIC-IV 2024 benchmark: XGBoost matches LSTM on tabular features
  - Interpretable via SHAP feature importance
- Secondary (stretch): 2-layer LSTM for temporal dynamics
- Visual: simple pipeline diagram (features → XGBoost → probability)

**Slide 9: Evaluation Framework**
- Table: all metrics, what each measures, expected range
- Baseline ladder: Predict-all-zero → NEWS2 → Logistic Regression → XGBoost → LSTM → eCARTv5
- Key claim: if we beat NEWS2's AUROC (~0.67-0.85), we've shown ML value
- Target: AUROC ≥ 0.80 on MIMIC-IV test set

**Slide 10: Timeline and Next Steps**
- Phase 1 (this week): Formulation finalized (TODAY), Slack post
- Phase 2 (next week): MIMIC-IV data extraction + label construction
- Phase 3 (week 3): XGBoost baseline training + evaluation
- Phase 4 (week 4): LSTM + ablation study + integration into `ml_risk` field
- Phase 5 (week 5): Gautam review, demo

---

## Part 4: Answers to Gautam's Key Questions

Gautam will ask these in the Thursday review. Have answers ready:

**Q: What is the label?**
A: Binary. y=1 if the patient's NEWS2 stage worsens within the next H hours — i.e., stage(NEWS2 at t+H) > stage(NEWS2 at t). Three stages: Normal (0-4), Moderate (5-6), Critical (≥7). This is analogous to a NYHA Class 2→3 transition in cardiac function classification.

**Q: Is it classification, regression, or survival analysis?**
A: Binary classification. Justification: All best-in-class clinical systems use this formulation. Survival analysis produces richer output but is harder to clinically interpret; we can add it in a Phase 2.

**Q: What prediction horizon?**
A: Primary = 6 hours. Literature consensus for ICU/CCU settings; actionable within a nursing shift. We will also test 24 hours.

**Q: How are training examples constructed?**
A: Sliding window over MIMIC-IV ICU stays. At each hour t, create one training example with features from [t-6h, t] and label from [t, t+6h]. Each patient generates ~90 labeled examples.

**Q: What data do we have?**
A: MIMIC-IV from PhysioNet: ~50,000 ICU admissions, hourly vital signs (HR, SpO2, RR, SBP, Temp), ICU transfer timestamps, death timestamps. All needed for this formulation.

**Q: What is the evaluation target?**
A: Primary: AUROC > NEWS2 baseline (~0.67-0.85). Secondary: AUPRC, sensitivity at 90% specificity, mean detection lead time > 3 hours. Clinical target from eCARTv5: detecting 81.8% of events > 2 hours before clinical manifestation.

---

## Part 5: Key Literature References for PPT

1. **eCARTv5** (Churpek et al., 2025) — Best-in-class model, AUROC 0.895, GBT on 97 features, multicenter validation. PMC11949291
2. **Multimodal BiLSTM on MIMIC-IV** (arXiv:2603.14719, 2025) — 74,822 ICU stays, composite label, AUROC 0.7857, focal loss α=0.75 γ=2.0
3. **CIRCEWS** (Hyland et al., 2020, Nature Medicine) — Binary classification, >2h lead time, AUROC 0.94 for circulatory failure, three-window construction
4. **Systematic Review** (PMC7892287, 2021) — 24 studies, all binary classification, AUROC range 0.57-0.97
5. **NEWS2 vs ML** (Nature Scientific Data, MIMIC-IV) — NEWS2 AUROC 0.67 vs XGBoost 0.77 on same data
6. **Class imbalance JAMIA paper** (2022) — Do NOT use SMOTE; use class weighting or focal loss instead

---

## Part 6: Verification

Before presenting:
- [ ] Read MIMIC-IV access status — does the team have PhysioNet credentials?
- [ ] Confirm `ml_risk` placeholder exists in frontend (already confirmed in code: `main.py:742`)
- [ ] Confirm `ews_ccu_transfers` and `ews_escalations` tables have timestamps (confirmed: `decided_at`, `escalated_at`)
- [ ] Confirm NEWS2 calculation exists in code (confirmed: `main.py:79 calculate_news2()`)
- [ ] Slide deck: build in PowerPoint/Google Slides from 10-slide structure above
- [ ] Slack post: share formulation equations from Section 1 as text/image

---

## Open Questions (one remaining)

1. **MIMIC-IV access:** Does the team have PhysioNet credentialing to download MIMIC-IV? This is a gated dataset requiring a training course + data use agreement. If not, the formulation is complete, but the data pipeline step needs to wait until credentials are obtained.

**Answered:**
- Label = NEWS2 stage transition (Normal→Moderate or Moderate→Critical within H hours)
- Three stages: Normal (0-4), Moderate (5-6), Critical (≥7)
- MIMIC-IV has the vitals needed; raw vitals + timestamps are present
- CCU patients only
- Presentation audience: Professor Gautam only (mathematical rigor expected)
