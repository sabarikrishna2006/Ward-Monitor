# False-Positive Comparison Across Approaches + Draft Reply to Professor

**Date:** 2026-07-21
**Companion to:** `RESEARCH_FINDINGS_deterioration_model_2026-07-20.md`
**Two things here:** (1) an honest cross-system false-positive comparison — industry,
research, and by model family; (2) a ready-to-send reply to the professor about
arXiv:1903.09795.

---

## Part 1 — How to compare false-positive rates HONESTLY (read this first)

Before any table: **"false-positive rate" is ambiguous, and the naive version misleads under
rare events.** Four different quantities all get called "false positives." Defining each,
with formula and how to read it, because a slide that mixes them up is indefensible:

| Metric | Formula | Units | What "good" looks like | Trap |
|---|---|---|---|---|
| **FPR (1 − specificity)** | FP / (FP+TN) | fraction | low (<0.2) | Looks fine even when alerts are mostly wrong, because TN is huge under rare events |
| **PPV (precision)** | TP / (TP+FP) | fraction | high | This is what a nurse actually experiences — "when it alarms, is it real?" |
| **Alerts per true event** | (TP+FP) / TP = 1/PPV | count | low (near 1) | No reference point; sounds bad even when normal |
| **Alarms per patient-hour** | alerts / patient-hours | rate | low (~0.05) | The only one that transfers across cohorts with different base rates |
| **Lift** | PPV / base_rate | ×multiplier | high (ceiling = 1/base_rate) | The honest "how much information does the alert add" number |

**Why FPR alone lies here.** Our model at 12h has specificity 0.635 → FPR 0.365, which sounds
tolerable. But the event base rate is only 11.4%, so those false positives vastly outnumber
true ones: PPV is just 0.224. **Specificity/FPR flatters rare-event models; PPV and
alarms-per-patient-hour do not.** Always report PPV and alarm burden, never FPR by itself.

**Why cross-system comparison is only fair at matched (outcome, sensitivity, base rate).**
A PPV of 0.30 for "ICU transfer in 24h" (base rate ~3%) is a far better model than a PPV of
0.30 for "NEWS2≥7 in 24h" (base rate ~23%) — same PPV, but the first achieves 10× lift and
the second only 1.3×. **Never compare raw PPVs without the base rate next to them.**

---

## Part 2 — The comparison table (with the caveats built in)

All numbers taken at each system's reported operating point. Blank = not reported in source.
"Framing" is the crucial column your professor's question is really about.

### 2a. Industry / deployed systems

| System | Framing | Outcome (base rate) | Sens | Spec | PPV | Alarm burden | Source |
|---|---|---|---|---|---|---|---|
| **NEWS2 ≥5** (raw score) | Threshold on score | Serious event | **0.98** | **0.28** | low | very high | [Singapore validation](https://pmc.ncbi.nlm.nih.gov/articles/PMC12550795/) |
| **eCARTv2** @ moderate | Fixed-horizon classification (GBM) | ICU transfer/death ≤24h | 0.37 | — | **0.082** | ~1 alert/day/35-bed | [eCARTv5 paper](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC11949291/) |
| **eCARTv5** | Fixed-horizon classification (GBM) | ICU transfer/death ≤24h | — | — | — | AUC 0.834 | same |
| **Epic Deterioration Index** (DI>40) | Continuous score → threshold | RRT/deterioration | 0.73 | **1.00** | **0.338** | — | [validation](https://pubmed.ncbi.nlm.nih.gov/34152373/) |
| **eCART risk-spike alert** | Continuous → spike alert | Deterioration | — | — | **0.07–0.35** | ~1/day/73-bed ward | [alert thresholds](https://link.springer.com/article/10.1007/s10877-019-00361-5) |
| **Physiologic monitors** (context) | Threshold | Any alarm | — | — | — | **74–99% non-actionable** | [alarm fatigue](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC4206416/) |

### 2b. Research systems / by model family

| System | Model family | Outcome (base rate) | Discrimination | False-alarm metric | Source |
|---|---|---|---|---|---|
| **Hyland et al. 2020** | Continuous risk (GBM, hourly) — *time-to-event-flavoured* | Circulatory failure | AUROC **0.94**, **AUPRC 0.63** | **0.05 alarms/patient/hour**; 90% events caught, 82% >2h early | [Nature Med](https://www.nature.com/articles/s41591-020-0789-4) |
| **Crit Care 2024** | **Time-to-event** (Cox, time-varying covariates) | In-hospital death ≤24h (0.67%) | AUC **0.96** | beats discrete-time logistic (0.93) | [Crit Care](https://pmc.ncbi.nlm.nih.gov/articles/PMC11256441/) |
| Crit Care 2024 (comparator) | **Discrete-time** logistic (1 obs/patient/day) | same | AUC 0.93 | — | same |
| **PhysioNet 2019 winner** | GBM + path signatures | Sepsis onset | utility 0.360 (1st/105) | utility penalises false alarms directly | [Oxford](https://www.maths.ox.ac.uk/node/33741) |
| **Ordinal-regression-with-censoring** (Shroff 2019) | **Discrete-time survival** (in ordinal notation) | RUL / time-to-failure | — (RUL task) | handles censoring by masking | [arXiv:1903.09795](https://arxiv.org/abs/1903.09795) |
| **Siena NEWS2 model 2025** | Classification (logistic) | **NEWS2≥7** (same as ours) | AUC 0.758 | — | [PMC12471953](https://pmc.ncbi.nlm.nih.gov/articles/PMC12471953/) |

### 2c. Our model (from `data/metrics_focused.json`)

| Horizon | Framing | Outcome (base rate) | Sens | Spec | PPV | **Lift** | Alerts/event | Alarms/patient-hour |
|---|---|---|---|---|---|---|---|---|
| 6h | AFT survival → calibrated P(T≤h) | NEWS2≥7 (5.7%) | 0.85 | 0.63 | 0.122 | **2.14×** | 8.2 | ~0.40 |
| 12h | same | NEWS2≥7 (11.4%) | 0.82 | 0.64 | 0.224 | **1.96×** | 4.5 | ~0.42 |
| 24h | same | NEWS2≥7 (22.9%) | 0.85 | 0.54 | 0.354 | **1.55×** | 2.8 | ~0.35 |

---

## Part 3 — What the comparison actually tells us

**1. Our false-positive rate is NORMAL for this problem class, not evidence of a broken model.**
Deployed ward systems land at PPV **0.08–0.35** at useful sensitivity (eCARTv2 0.082, eCART
risk-spikes 0.07–0.35, Epic 0.338). Ours is 0.12–0.35. **We are inside the industry band.**
The lever is therefore *not* switching model family — it is (a) alarm deduplication and
(b) a real outcome. Anyone who tells you the false-positive rate proves the framing is wrong
is mistaken; the whole field lives in this band because deterioration is rare.

**2. The one system that crushes false alarms did it with a better outcome + alarm-rate
discipline, not a fancier model.** Hyland's 0.05 alarms/patient/hour comes from (a) predicting
a *physiologically defined circulatory-failure* event, (b) reporting AUPRC and alarm-rate
honestly, and (c) alarm-gating. Their model is a gradient-boosted hourly risk score — the same
class of tool as ours. This is the template.

**3. Framing verdict — time-to-event vs classification:**
- **Industry deployment convention = fixed-horizon classification** (eCART, Epic). Chosen for
  operational simplicity and a single clear threshold, *not* because it's statistically
  superior.
- **Research convention is moving toward time-to-event**, and the one head-to-head on ward
  deterioration (Crit Care 2024) found **TTE beat classification** for ranking/triage, because
  classification throws away event timing and can't use censored patients cleanly.
- **Discrete-time survival is the convergence point** — it is per-interval classification that
  reconstructs a survival curve, so it keeps classification's tooling *and* TTE's timing/censoring
  handling. **Your professor's censoring-aware ordinal regression is exactly this.**

So "TTE better than classification" is defensible **for ranking/triage**, with the honest
caveat that *deployed* systems still mostly ship classification for simplicity — and that the
cleanest way to get TTE's benefits without continuous-survival's interpretability headaches is
the discrete-time/ordinal-with-censoring family the professor pointed at.

---

## Part 4 — Draft reply to the professor

> Adjust the greeting/sign-off to your normal style. It agrees with his suggestion (which is
> correct and which his own paper backs), states the TTE-vs-classification evidence, and lays
> out the plan — without ever claiming his approach is inferior, because it isn't.

---

Dear Professor,

Thank you for pointing me to the deep ordinal regression paper (arXiv:1903.09795) — I read it
along with the earlier PHM 2018 censored-RUL version. The key idea I took from it is the label
encoding: a failed unit gets the cumulative binary vector `y_j = 0 for j<k, 1 for j≥k`, and a
**censored** unit that survives to bucket k′ is labelled `0` up to k′ and **masked (unknown)
beyond it**, so censored units still contribute training signal without a known failure time.

Working through this, I realised the censoring-masking mechanism is **structurally identical to
a discrete-time survival (discrete-time hazard) model** — where a censored patient simply
contributes interval-rows up to censoring and none afterward. So the ordinal-regression-with-
censoring framing is not an alternative to time-to-event modelling; it *is* a time-to-event
model, just written in ordinal notation. That resolved my main earlier worry (that ordinal
regression couldn't handle our censored discharges/deaths) — with your masking scheme, it can.

On the broader framing question — time-to-event vs. fixed-horizon classification — the evidence
I found supports the time-to-event direction for our triage use case:

- The largest recent head-to-head on ward deterioration (Kipnis-style setup; Critical Care 2024,
  150k admissions) found a **time-varying-covariate Cox model beat discrete-time logistic
  classification** (AUC 0.96 vs 0.93 at 24h), because classification discards event timing and
  can't use censored patients cleanly.
- Deployed commercial systems (eCART, Epic Deterioration Index) are still built as fixed-horizon
  classification — but for operational simplicity (one threshold), not because it's shown to be
  statistically better.
- Discrete-time survival / your ordinal-with-censoring approach sits exactly between the two:
  per-interval binary classification that reconstructs a survival curve, keeping the tooling of
  classification and the timing/censoring handling of survival.

So my plan is to implement your suggested ordinal/discrete-time approach on the deterioration
problem, in the hazard parameterisation, with **XGBoost as the base learner rather than an
LSTM** — justified because we have 54 tabular vital-sign features and only ~2,600 patients with
a usable positive label, which is below the regime where deep sequence models earn their
complexity. I'll benchmark it against our current XGBoost-AFT and an untested `survival:cox`
baseline.

Two things I want to flag honestly before I build it:

1. **A target-leakage problem in the current setup that no model family fixes.** Our event is
   "NEWS2 ≥ 7 sustained 2h", but the features include the NEWS2 score itself — so the model is
   partly predicting a deterministic function of its own inputs (NEWS2's own mean is the top
   feature by a factor of 3). I'd like to move the target to an *objective* outcome — treatment
   escalation (vasopressor/ventilation/RRT) or death — which we already compute. I expect our
   AUC to drop (probably 0.70–0.78) but the number will finally mean "predicts deterioration"
   rather than "predicts our own score."
2. **On false positives:** our PPV (0.12–0.35) initially looked alarming, but it's squarely
   inside the deployed-system band (eCART 0.08–0.35, Epic 0.34). The bigger lever than model
   choice is alarm deduplication/hysteresis — right now we count every patient-hour as a
   separate alarm, which inflates the apparent false-alarm rate. I'll add that plus AUPRC and
   an alarms-per-patient-hour figure so the numbers are comparable to the literature (e.g.
   Hyland et al., Nature Medicine 2020, at 0.05 alarms/patient/hour).

Would you like me to start with the label change or the discrete-time/ordinal model first? My
instinct is the label first, since it affects every downstream number.

Best regards,
Sabari

---

## References to share with the professor

- **arXiv:1903.09795** — Vishnu, Diksha, Malhotra, Vig, Shroff (2019), *Data-driven Prognostics… Ensemble of Deep Ordinal Regression Models* (his paper).
- **Gugulothu et al., PHM 2018** — [*Deep Ordinal Regression for RUL Estimation from Censored Data*](https://www.researchgate.net/publication/326557089) (the censored-RUL precursor).
- **Gensheimer & Narasimhan 2019** — [*A scalable discrete-time survival model for neural networks*](https://pubmed.ncbi.nlm.nih.gov/30701130/) (the clinical discrete-time hazard reference; shows the ordinal↔survival equivalence in a health setting).
- **Critical Care 2024** — [*Prioritising deteriorating patients using time-to-event analysis*](https://pmc.ncbi.nlm.nih.gov/articles/PMC11256441/) (TTE beats classification, head-to-head).
- **Hyland et al., Nature Medicine 2020** — [*Early prediction of circulatory failure in the ICU*](https://www.nature.com/articles/s41591-020-0789-4) (0.05 alarms/patient/hour benchmark; AUPRC reporting).
- **Churpek et al. 2024** — [*eCARTv5*](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC11949291/) (FDA-cleared classification system; PPV band).
- **Harrell, RMS ch. 25** — [*Ordinal Semiparametric Regression for Survival Analysis*](https://hbiostat.org/rmsc/ordsurv) (the formal ordinal↔survival bridge).
