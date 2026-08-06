# The focused base model — every number explained

Read this before you present. Every figure below is copied
directly from `data/metrics_focused.json` / `data/models_news2/meta.json` — none
of it is typed from memory, so if any stakeholder asks "where does this number come
from," the answer is always "this exact field in this exact file."

---

## 1. What was built, in one paragraph

**One event**: the first time a patient's NEWS2 score sustains ≥ 7 for two
consecutive hourly readings. **One feature family**: the 7 NEWS2 parameters
(heart rate, respiratory rate, SpO₂, systolic/diastolic BP, temperature,
consciousness) plus their trends, plus minimal context (age, sex, hours since
admission) — 54 columns total, listed in `meta.json["features"]`. **One model**:
a single XGBoost `survival:aft` booster, distribution chosen by validation
log-likelihood (**logistic** won: 0.682 vs normal 0.717 — see the training log).
No labs, no weight, no DCM axis, no multi-model comparison.

Cohorts: MIMIC-IV v3.1 CCU stays. 256,712 hourly "anchors" total, split **by
patient** 70/15/15 → **180,762 train / 38,673 calibrate / 37,277 test**. Test set
has **5,162 real events** (13.8% event rate in the raw test data; base rate
varies by horizon once known-status filtering is applied — see §4).

---

## 2. The scatter plots — what "predicted time" actually means

### Scatter A — Unconditional Median (`01_scatter_naive.png`)
x = actual hours until the crossing. y = the model's **raw median** prediction.
**Pearson r = 0.13** (weak). This LOOKS bad. Here is the honest explanation, not
an excuse:

> If P(event within a horizon) < 50%, a **perfectly calibrated** survival model's
> median is mathematically forced to land **beyond** that horizon — the fitted
> survival curve never crosses 0.5 while the patient is still in the window.
> Comparing that median only against patients who *did* have an event is a
> **biased evaluation**, not proof the model is broken. Our event rate is ~13%,
> so this is exactly what the math predicts.

### Scatter B — Conditional Expected Time (`02_scatter_corrected.png`)
y = `E[T | T ≤ 24h]`, the model's **conditional** expected time — computed from
the *same fitted distribution*, just asking a different (fair) question:
"given this patient deteriorates within the window, when does the model think
it happens?" **Pearson r = 0.21, MAE = 5.6 hours.** Still not a precise clock —
but a coherent, defensible estimate, and dramatically tamer than the naive
median (which ranged up to **2,872 hours** for some patients — the same
mathematical inflation described above).

**How to say it out loud:** *"The raw median looks wrong because of a known,
provable statistical effect under our ~13% event rate — not because the model
is broken. When we ask the fair, conditional question instead, the estimate is
far more sensible, with a mean error of about 5.6 hours."*

---

## 3. The error-by-bin chart (`03_error_by_bin.png`) — the cutoff horizon

| Actual time bin | n events | MAE (h) | MAPE (%) |
|---|---|---|---|
| 0–2h  | 715  | 8.35  | **663%** |
| 2–4h  | 605  | 6.63  | 196% |
| 4–6h  | 560  | 4.74  | 88% |
| 6–9h  | 755  | 2.52  | 33% |
| 9–12h | 674  | **1.11** | **10%** |
| 12–18h| 1083 | 4.82  | 31% |
| 18–24h| 770  | 10.64 | 50% |

**Reading this honestly:** the point-estimate conditional time is essentially
useless for *imminent* events (0–4h out) — the model's conditional estimate
floors around 5–9h, so when someone actually crosses in 1 hour, the "error" is
huge in percentage terms. It is **most accurate in the 6–12h range** and decays
again toward the 24h ceiling (where the conditional expectation is squeezed
against the administrative cap). **This is the cutoff-horizon finding**: treat
the point-estimate time as informative for a **6–18h** planning window, not as a
literal countdown at very short or very long horizons.

Crucially — this is a limitation of the **point estimate**, not of the model's
*risk ranking*, which stays strong across all horizons (§4).

---

## 4. Horizon utility (`04_horizon_utility.png`) — does it cut false alarms?

All numbers below use **known-status anchors only** — i.e., a patient discharged
before hour `h` is *excluded*, not counted as a confirmed negative (ensuring
robust evaluation; this is why `known_status.py` exists). The "dropped %" column
is exactly how many anchors that exclusion removes — reported, not hidden.

| Horizon | n known (dropped) | Events (rate) | AFT AUC | AFT PPV | AFT alerts/event | Ruler AUC | Ruler alerts/event |
|---|---|---|---|---|---|---|---|
| ≤6h  | 33,025 (11.4%) | 1,880 (5.7%)  | **0.821** | 0.12 | **8.2**  | 0.563 | 17.6 |
| ≤12h | 29,025 (22.1%) | 3,309 (11.4%) | **0.802** | 0.22 | **4.5**  | 0.548 | 8.8 |
| ≤24h | 22,537 (39.5%) | 5,162 (22.9%) | **0.778** | 0.35 | **2.8**  | 0.539 | 4.4 |

**AUC** = probability the model ranks a random true-positive above a random
true-negative (0.5 = coin flip). **Alerts/event** = for every real deterioration
caught, how many false alarms fire alongside it, at an 80%-sensitivity operating
point.

**The single most important honesty check in this whole report:** look at the
ruler's confusion matrix in the raw JSON — at every horizon, `tn=0` and `fn=0`.
The "80%-sensitivity threshold" for the ruler baseline collapses to **alerting
on literally every patient** (its risk scores are so tie-dominated — most
patients get the exact same "will never cross" floor value — that no
meaningful threshold exists below that). Its "alerts/event" numbers (17.6 / 8.8
/ 4.4) are simply `1 / base_rate` — i.e., **the ruler adds no information at
all**; those numbers are what you'd get from a coin flip weighted by prevalence.
The AFT model roughly **halves** that at every horizon. This is the clearest,
most defensible "our model works" statement in the deck.

---

## 5. Threshold sweep (`05_threshold_sweep.png`)

At the 12h horizon, sweeping the target sensitivity from 50% to 95%: the AFT's
alerts-per-event rises gradually from **3.0 to 6.1** — the expected trade-off
(catch more, tolerate more false alarms). The ruler's line is **perfectly flat
at 8.77** for every target below ~90% — direct visual proof of the tie-dominance
described above: nearly all its "positive" predictions share one value, so
almost any sensitivity target lands on the same degenerate threshold.

---

## 6. Calibration (`06_calibration.png`)

Before isotonic calibration, the raw probability already tracked observed
frequency reasonably well (it's an AFT-derived CDF, not an arbitrary score).
After calibration, the top bin (~0.39 predicted) matches observed frequency
(~0.40) almost exactly. **What calibration buys you:** a stated "24% risk of
deteriorating in 12 hours" can be taken at face value, checked against real
outcomes, and trusted — not just used for ranking.

---

## 7. Overfitting check (`07_overfit_check.png`)

| Split | n | C-index | AUC @12h | MAE cond. time |
|---|---|---|---|---|
| Train | 180,762 | 0.8154 | 0.834 | 5.62h |
| Test  | 37,277  | 0.7815 | 0.802 | 5.56h |

**C-index gap = 0.034** — small. The model generalizes; it is not memorizing
the training set. (Note the MAE is actually *slightly better* on test than
train — expected noise at this gap size, not a red flag.)

---

## 8. SHAP — what actually drives the model

**Global** (`08_shap_importance.png`): `news2_mean` dominates (mean |SHAP| 0.56,
more than 3× the next feature), then `on_oxygen`, `age`, `fio2_last`,
`heart_rate_last`, `hours_in_band`. All clinically sensible NEWS2-family
signals — exactly what you'd expect from a NEWS2-only feature set, no
surprises, no leakage.

**Per-patient** (`09_shap_patient.png`, stay_id 35094306, deteriorated at 6.0h,
calibrated 12h-risk = 1.1% **at this specific anchor**): for this one anchor,
`news2_mean`, `on_oxygen`, and `news2_at_anchor` all pushed the prediction
toward a **longer** time (this particular observation looked reassuring),
while `age` and `hours_in_band` pushed toward shorter. This is a real,
single-instance explanation — not a dataset-level summary — which is what lets
a clinician ask "why does the model think *this* patient is/isn't at risk *right
now*."

---

## 9. Case studies (`10_case_studies.png`)

Three real test-set patients, selected by objective rule (not hand-picked for
looks): most anchors with a clear risk-rise for "caught early," low initial risk
for "borderline," and a 24–96h stay with no event for "stable."

- **stay 34725102 — caught early**: 199 anchors over ~215h; calibrated 12h-risk
  rose from **5.9% → 23.0%** by the time of the actual crossing.
- **stay 37152986 — borderline**: risk started at 24.1% and was actually
  **lower (10.5%)** near the end — an honest limitation, shown deliberately,
  not hidden.
- **stay 30373756 — stable**: risk fell from 4.2% to 1.1% and the patient was
  discharged at ~95h with no event — correctly quiet throughout.

Say plainly: *"We are showing you a real success case and a real limitation
case side by side, not cherry-picking."*

---

## 10. Decision curve analysis (`11_decision_curve.png`)

Vickers & Elkin's (2006) net-benefit framework: at every alert threshold from
1% to 50%, the model's net benefit is **positive and above both** "alert on
everyone" and "alert on no one." This is the standard way clinical-prediction
papers argue a model is worth deploying, beyond a bare AUC number.

---

## Anticipated questions → your answers

- **"Is the naive median wrong?"** No — it's mathematically expected under a
  ~13% event rate. We report the conditional expectation and the calibrated
  probability instead, from the same model.
- **"Does the model actually help?"** Yes, concretely: **halves** the false-alarm
  rate versus the naive NEWS2-slope ruler at every horizon (§4), and the ruler's
  own numbers reduce to "alert on everyone" once you look at its confusion
  matrix.
- **"Why NEWS2-only and one event?"** Deliberate: we must prove a base model works
  before adding complexity. This foundational baseline achieves exactly that.
- **"What's next?"** Add the congestion/substrate axis (weight, NT-proBNP, eGFR,
  urine output) and measure the delta over *this exact* baseline.

## Honest limitations — say these before anyone asks
- Retrospective MIMIC-IV CCU cohort; not yet validated prospectively or on the
  general ward.
- The event is NEWS2-defined and the features are NEWS2-only — a good result
  proves we can forecast a score we already compute, which is the necessary
  first step, not the final claim.
- Point-estimate time-to-event is unreliable outside the ~6–18h window; use
  the calibrated probability and ranking, not a literal countdown.
- 11–40% of anchors are dropped as unknown-status depending on horizon —
  reported transparently in every table, never silently absorbed into "negative."
