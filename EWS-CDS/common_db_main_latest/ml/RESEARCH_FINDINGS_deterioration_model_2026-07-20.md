# Research Findings — Is AFT Survival the Right Framing for the EWS Deterioration Model?

**Date:** 2026-07-20
**Input:** Part C of `RESEARCH_PROMPT_deterioration_model.md`, executed with live web search
**Grounding:** every "our" number below is read from `data/metrics_focused.json` and
`data/models_news2/meta.json`, not from memory or from the prose in the prompt.

> **How to read this file.** Section 0 is the verdict. Section 1 is the finding that
> matters more than the question that was asked. Sections 2–3 place our numbers against
> the published field. Section 4 works through every model family. Section 5 is the
> recommendation. Section 6 lists what the research prompt itself got wrong.
> Every metric introduced is defined, computed, and interpreted before it is used —
> per the standing rule, nothing here should go into a slide you can't defend out loud.

---

## 0. Verdict up front

**The modeling family is not your problem, and switching it will not help you.**

Three findings, in order of how much they should change what you do next:

1. **The label is computed from the features.** The event is "NEWS2 ≥ 7 for 2 consecutive
   hours"; the features are the 7 NEWS2 parameters *and the NEWS2 score itself*. The model
   is not learning to predict deterioration — it is learning to extrapolate a deterministic
   function of its own inputs. No change of model family fixes this. **This is the single
   most important thing to address.**
2. **Your headline AUC is not evidence of a good model, because the task is easier than
   the field's.** eCART Lite gets AUC 0.792 predicting *real ICU transfer* from only age,
   heart rate and respiratory rate. You get 0.802 predicting *your own score crossing a
   line* from 54 features. Same ballpark number, much easier question.
3. **The alerts-per-event number is not the right lens, and the right lens looks worse.**
   Your model concentrates true events in the alerted group by a factor of **1.5×–2.1×**.
   That is the honest measure of how much information it adds, and it is modest.

**Recommendation: keep a time-to-event framing, but move from continuous AFT to
discrete-time survival (logistic hazard), and — before any of that — fix the label.**
Rationale in §5. Ordinal regression, as your supervisor suggested, is pointing at the
right structure, but the correctly-named method for it is discrete-time survival; the
reason why is in §4.1.

---

## 1. The finding that outranks the question you asked

### 1.1 What the code actually does

From `01_build_labels.py:180`:

```python
if event_mode == "news2":
    ev["deterioration_time"] = ev["news2_sustained_time"]
```

The event time is the first hour at which NEWS2 stays in the HIGH band (≥7) for 2
consecutive readings. From `09_focused_train.py:74-79`, the feature set is every column
prefixed by `config.NEWS2_FEATURE_PREFIXES` — the 7 NEWS2 parameters, their rolling
statistics, **and the NEWS2 score's own value, mean, max, rate, and hours-in-band.**

NEWS2 is a deterministic lookup table over those 7 vitals. So the target is a fixed,
known, closed-form function of the input features, evaluated a few hours later.

This is why `news2_mean` has a SHAP importance of 0.56 — more than three times the next
feature. That is not the model discovering that mean NEWS2 is clinically informative. That
is the model finding the shortest path to the answer key.

### 1.2 Why this is not merely a technicality

There are two defensible things a model like this can be, and they need different labels:

| If you want to claim… | The label must be… | Do we have it? |
|---|---|---|
| "This predicts clinical deterioration" | An outcome that exists independently of the score — ICU/CCU transfer, cardiac arrest, death, unplanned intervention | **No** |
| "This gives you a head start on the NEWS2 alarm you would have gotten anyway" | NEWS2 threshold crossing | Yes |

The second claim is legitimate and has precedent — a 2025 Siena study
([PMC12471953](https://pmc.ncbi.nlm.nih.gov/articles/PMC12471953/)) defines exactly the same
outcome (NEWS2 ≥ 7 during stay, given admission NEWS2 < 7) and says so openly:

> "While this outcome inherently links to NEWS2 as a key predictor, which could lead to
> concerns about **target leakage**, our primary objective in this exploratory study was
> not to predict clinical deterioration in its broadest sense."

But note what happens to the second claim under scrutiny. If you are only predicting when
the NEWS2 alarm will fire, the natural challenge is: *why not just wait for the NEWS2 alarm?*
Answer: because you get a few hours of lead time. That is a real but narrow benefit, and it
puts you in direct competition with your own ruler baseline rather than with clinical
practice.

**The uncomfortable comparison:** that Siena study got a validation AUC of **0.758** using
**stepwise logistic regression** on **2,108 patients** with admission-time data only. You
get **0.802** at 12h using XGBoost AFT on 256,712 anchors from 10,775 stays with hourly
updating. Different setups, not a like-for-like comparison — but a gap of 0.04 AUC over a
vastly heavier pipeline is not the margin you would hope for, and it is a hint that most
of the achievable signal in this target is trivially available.

### 1.3 The recommended fix

You already have the ingredients. `compute_stay_events()` in `01_build_labels.py:158-187`
already computes `escalation_time` — first vasopressor / ventilation / RRT start — and
`deathtime`. The `composite` event mode already combines them.

The strongest version of this project defines the event as **treatment escalation or death,
excluding the NEWS2 crossing entirely**, and uses NEWS2 features to predict it. That is a
genuine prediction task, matches what eCART and the Epic Deterioration Index actually
predict, and it removes the circularity in one change.

The professor's instruction to "start with ONE focused event" was correct. The error was in
which one — the focused event should have been the *objective* one, not the *score-defined*
one. Note the irony: the earlier composite model, which was pivoted away from, was closer
to the right target than the focused one that replaced it.

---

## 2. Where our numbers actually sit against the published field

### 2.1 The benchmark table

| System | Outcome predicted | Cohort | AUC | Notes |
|---|---|---|---|---|
| **eCARTv5** (Churpek, 2024) | ICU transfer or death ≤24h | 21 hospitals, prospective | **0.834** | FDA-cleared |
| **eCART Lite** (Churpek, 2021) | ICU transfer ≤24h | 556,848 admissions | **0.792** | **only age + HR + RR** |
| eCART Lite | ICU transfer or death | same | 0.795 | |
| eCARTv2 | ICU transfer or death | same | 0.775–0.786 | |
| NEWS (as comparator) | ICU transfer | same | 0.743 | |
| MEWS (as comparator) | ICU transfer | same | 0.711 | |
| **Epic Deterioration Index** | deterioration | vendor-reported | 0.76–0.83 | external validation of the sibling sepsis model fell to **0.63** |
| **Hyland et al.** (Nature Med, 2020) | circulatory failure | HiRID, 240 patient-yrs | **0.94** | AUPRC 0.63, **0.05 alarms/patient/hour** |
| **Cox time-varying** (Crit Care, 2024) | in-hospital death ≤24h | 150,342 admissions | **0.96** | beat discrete-time logistic (0.93) |
| Siena NEWS2 model (2025) | **NEWS2 ≥ 7** (same as ours) | 2,108 patients | 0.758 | acknowledges target leakage |
| **Ours (focused AFT)** | **NEWS2 ≥ 7** ≤12h | 10,775 CCU stays | **0.802** | ≤6h: 0.821, ≤24h: 0.778 |

**Sources:** [eCARTv5](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC11949291/) ·
[eCART Lite](https://pmc.ncbi.nlm.nih.gov/articles/PMC9128300/) ·
[Epic external validation](https://pubmed.ncbi.nlm.nih.gov/34152373/) ·
[Hyland](https://www.nature.com/articles/s41591-020-0789-4) ·
[Cox time-varying](https://pmc.ncbi.nlm.nih.gov/articles/PMC11256441/) ·
[Siena](https://pmc.ncbi.nlm.nih.gov/articles/PMC12471953/)

### 2.2 How to read that table honestly

**Do not say "our AUC of 0.80 is competitive with eCART's 0.83."** It is not a comparison.
The right statement is:

> "Our model reaches AUC 0.802 for predicting a NEWS2 threshold crossing within 12 hours.
> Published systems reach 0.79–0.83 predicting *ICU transfer or death* — a harder and
> clinically meaningful target. Our number is therefore not directly comparable and should
> not be presented as competitive until we predict a comparable outcome."

The eCART Lite result is the one that should worry you most. Three inputs — age, heart rate,
respiratory rate — plus 24-hour trends, gradient-boosted, gets **0.792 on real ICU transfer**.
Your 54 features on an easier target get 0.802. That strongly suggests the extra feature
engineering is buying very little, and the field's own conclusion ("less is more") is that
vital-sign trend features saturate quickly.

---

## 3. The false-positive question, answered properly

### 3.1 First, a metric you should be using and aren't

**Lift (enrichment factor).**

- **Definition:** how many times more concentrated true events are among the patients you
  alert on, compared to the population base rate.
- **Formula:** `lift = PPV / base_rate`
- **Units:** dimensionless multiplier.
- **Interpretation:** lift = 1 means your alert carries zero information (alerting at random
  gives the same yield). lift = 10 means an alerted patient is 10× more likely to be a true
  event than a randomly chosen one. Higher is better; there is no upper bound, but it is
  capped in practice by `1/base_rate` (the lift you'd get from a perfect model).

Computed from `metrics_focused.json`:

| Horizon | Base rate | PPV @ ~80% sens | **Lift** | Max possible lift |
|---|---|---|---|---|
| 6h | 0.0569 | 0.1216 | **2.14×** | 17.6× |
| 12h | 0.1140 | 0.2237 | **1.96×** | 8.8× |
| 24h | 0.2290 | 0.3540 | **1.55×** | 4.4× |

**This is the number to lead with, and it is sobering.** At the 12-hour horizon, the model
roughly doubles the concentration of true events in the alerted group — against a ceiling of
8.8×. It is capturing about a fifth of the available separation.

Why this beats "alerts per event": alerts-per-event (4.47 at 12h) sounds like a workload
figure but is really just `1/PPV`. It has no reference point, which is exactly why it was
hard to defend when questioned. Lift has a built-in reference point (1.0 = useless) and a
built-in ceiling, so you can always answer "compared to what?"

### 3.2 Second, a metric the field uses and we never computed

**AUPRC (area under the precision-recall curve).** For rare events, AUROC is optimistic
because it rewards a large true-negative count that comes free with imbalance. The
[critical-illness literature](https://pmc.ncbi.nlm.nih.gov/articles/PMC12133047/) is
explicit that AUPRC is the appropriate summary. Hyland et al. report AUPRC 0.63; we report
nothing. **A no-skill AUPRC equals the base rate**, so our 12h reference floor would be
0.114 — that context makes the number immediately interpretable.

**Action:** add AUPRC at each horizon to `10_focused_report.py`. It is a two-line change
(`sklearn.metrics.average_precision_score`) and it is the single cheapest credibility win
available.

### 3.3 Third, the alarm-rate metric that translates to a ward

Hyland reports **0.05 alarms per patient per hour** — i.e. roughly one alarm per patient
per 20 hours. That is a number a nurse manager can act on. Ours is currently unstated but
derivable: at 12h, 12,083 alerts across 29,025 known anchor-hours ≈ **0.42 alarms per
patient-hour** — about one alarm per patient every 2.4 hours. **That is roughly 8× Hyland's
alarm burden**, and in a real ward it would be dismissed as unusable within a week.

This is the number that makes the false-positive problem concrete, and it should replace
alerts-per-event in any clinical-facing presentation.

### 3.4 The levers that actually reduce false alarms — ranked by expected payoff here

1. **Alarm deduplication / hysteresis (largest, cheapest win).** You currently count every
   alerting patient-hour as a separate false alarm. The literature standard is to suppress
   repeat alarms for a refractory period (e.g. 30 minutes to several hours) after one fires,
   and to require risk to persist across consecutive readings before firing at all. A
   [neonatal ICU program](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC10990340/) cut alarm
   frequency 64% with delay-and-threshold changes alone. **Because your anchors are hourly
   and highly autocorrelated, most of your 9,380 false positives at 12h are almost certainly
   the same patients alerting repeatedly.** Deduplicating to patient-episodes could plausibly
   cut the apparent false-alarm count by a large factor *with zero change to the model*.
   This should be done first, before any modeling work, because it may reframe the entire
   problem.
2. **Feature richness.** eCART v5 (0.834) uses labs and documentation; eCART Lite (0.792)
   uses three vitals. The gap between them — about 0.04 AUC — is what labs buy you. Real,
   but not transformative. Do not expect labs to rescue the false-positive rate.
3. **Fix the label (§1).** A non-circular target will likely *lower* your AUC while making
   the number mean something. Expect this and say so in advance.
4. **Cohort narrowing.** Restricting to DCM patients raised C-index to 0.80 in the earlier
   composite model. Real, but shrinks an already-small cohort.
5. **Different model family.** Last, and least. See §4.

---

## 4. Every model family, evaluated

Ranked by what I'd actually do, not by the order in the prompt.

### 4.1 Discrete-time survival / logistic hazard — **the recommendation**

**What it is.** Chop the follow-up into intervals (here: hourly, or 2h/4h/8h/24h buckets).
For each patient-interval that the patient entered event-free, ask one binary question: "did
the event happen *in this interval*?" Train any binary classifier — XGBoost included — on
that person-period table. The classifier's calibrated output *is* the discrete hazard, and
survival is the running product of `(1 − hazard)`.

**Why it wins for this problem:**
- **It handles censoring natively and correctly.** A patient discharged at hour 9 simply
  contributes rows for hours 1–9 and none after. No dropping, no imputation, no workaround.
- **It removes the median-uninterpretability pathology by construction.** You never estimate
  a timestamp, so there is no median to be forced beyond the horizon by a sub-50% event rate.
  The `P(T≤h)` you already compute as a workaround becomes the model's *native* output rather
  than a post-hoc derivation from a distribution you assumed.
- **It drops the AFT distributional assumption.** You currently assume a logistic AFT with
  **σ hardcoded to 1.0** (`09_focused_train.py:67`), never tuned — and σ directly controls
  the spread of every `P(T≤h)` the system emits. Discrete-time has no σ.
- **Tooling is trivial.** It is XGBoost binary classification on a reshaped table. No new
  library, no new objective, and every calibration/SHAP tool you have already built keeps
  working unchanged.
- **Published support:** [Gensheimer & Narasimhan 2019](https://pubmed.ncbi.nlm.nih.gov/30701130/);
  a clear applied introduction is
  [Survival prediction models: an introduction to discrete-time modeling](https://pmc.ncbi.nlm.nih.gov/articles/PMC9316420/).

**Honest caveat:** in the one head-to-head I found on ward deterioration
([Crit Care 2024](https://pmc.ncbi.nlm.nih.gov/articles/PMC11256441/)), continuous-time Cox
with time-varying covariates **beat** discrete-time logistic (AUC 0.96 vs 0.93 at 24h). But
their discrete-time implementation deliberately used *one observation per patient per day*,
discarding the rest — that handicap is what they were criticising, and it does not apply to
an hourly person-period table. Their finding argues against *coarse* discretisation, not
against discrete-time hazard modeling.

### 4.2 Ordinal regression (your supervisor's suggestion) — right instinct, wrong name

This deserves a careful answer, and it needs a correction that a first pass (including an
earlier draft of this document) gets wrong.

**Which paper the supervisor actually sent.** arXiv:1903.09795 is **not** CORAL/CORN. It is
*"Data-driven Prognostics with Predictive Uncertainty Estimation using Ensemble of Deep
Ordinal Regression Models"* (Vishnu, Diksha, Malhotra, Vig, **Shroff**, 2019) — the
supervisor is a co-author. It, and its precursor
[*Deep Ordinal Regression for RUL Estimation from Censored Data*](https://www.researchgate.net/publication/326557089)
(Gugulothu et al., PHM 2018), are about remaining-useful-life prognostics and, critically,
**they explicitly handle right-censored data.** Any reply must engage with this specific
work, not a generic ordinal-regression method.

**The appeal is real.** Bucketing time and modeling ordered probabilities sidesteps the
median problem and structurally includes non-event units as a terminal category. Those are
the two things we wanted.

**The censoring objection I raised earlier is WRONG for this specific method.** I previously
claimed "ordinal regression has no principled way to handle censoring." That is true only of
the *vanilla* forms (proportional-odds, `mord`, Frank & Hall, CORAL/CORN), which assume every
label is fully observed. Shroff's variant does not assume that. Reading the paper directly,
its label encoding is:

- Discretize RUL into K buckets; a **failed** unit at bucket k gets the binary target
  `y_j = 0 for j<k, 1 for j≥k` (a cumulative "still-alive-past-threshold-j" vector).
- A **censored** unit observed to bucket k′ (but not failed) gets `y_j = 0 for j<k′,
  **unknown** for j≥k′`, and the loss **masks the unknowns** — it "sums only over j=1..k′−1,
  excluding unknown labels from gradient computation."

**That masking of unknown post-censoring buckets is exactly the discrete-time survival
construction.** In discrete-time hazard modeling, a censored patient simply contributes
interval-rows up to censoring and none after — identical treatment, different notation. So:

> **Shroff's censoring-aware ordinal regression and discrete-time survival are the same idea.**
> His suggestion is therefore *not an alternative to time-to-event modeling — it IS a
> time-to-event model.* It is fully consistent with the conclusion that TTE beats fixed-horizon
> classification, because it is itself a TTE method.

**The one real design choice that remains** is cumulative vs. hazard encoding of the K binary
sub-problems:
- **Cumulative** (Shroff's form): each classifier predicts `P(survive past threshold j)`
  directly — gives the survival function in one shot.
- **Hazard** (Gensheimer discrete-time): each classifier predicts the *conditional* hazard
  `P(fail in interval j | survived to j)`; survival is the running product. Cleaner
  probabilistic interpretation, is the textbook "discrete-time survival" form, and is what
  most clinical implementations use.
Both are defensible; they are near-equivalent for our purposes. The recommendation to use the
hazard form (§4.1) is a mild preference for interpretability, **not** a disagreement with the
supervisor's structural suggestion.

**Bottom line for the meeting:** adopt the suggestion. Frame our plan as implementing his
censoring-aware ordinal/discrete-time approach on the ward-deterioration problem, in the
hazard parameterization, with XGBoost as the base learner instead of an LSTM (justified by
54 tabular features and ~2,600 usable positive patients — far below where deep sequence models
earn their complexity). This agrees with him, is technically precise, and cannot be refuted by
his own paper.

CORAL/CORN specifically (the paper this was *initially mis-identified as*): rank-consistency
guarantees for deep ordinal nets. Not relevant here — different paper, and even on its own
terms it targets many-bucket deep models, not our tabular ~5-bucket censored setting.

### 4.3 XGBoost `survival:cox` — the missing baseline, test it this week

The prompt correctly flags this as untested. There is a concrete reason to expect it to help.

The [XGBoost AFT paper's own benchmarks](https://arxiv.org/pdf/2006.04920) (Barnwal et al. 2022)
report that AFT edges out Cox at **20% censoring**, they tie at **50%**, and **scikit-survival's
Cox-PH wins at 80% censoring.** Our anchor-level event rate is 13.3%, i.e. **~87% censored** —
past the point where their benchmark favours Cox.

This is a one-line objective swap in `03_train.py`'s `train_aft` helper and costs an afternoon.
**Do it, because right now you cannot answer "did you try Cox?" and that is the first question
any statistician asks.** Cox is the field's default; AFT was chosen without a documented
head-to-head.

### 4.4 Cox with time-varying covariates — the strongest classical alternative

The [Crit Care 2024 study](https://pmc.ncbi.nlm.nih.gov/articles/PMC11256441/) is the closest
published analogue to your setup and the most useful single paper in this review. 150,342
admissions, 4.6M observations, one row per vital-signs measurement, outcome = death before the
next observation. AUC 0.96 at 24h, beating discrete-time logistic at 0.93.

Two things to take from it:

1. **Measurement frequency is itself a predictor.** Nurses chart more often when worried. Their
   model exploits the varying interval between observations; **your hourly grid with 6-hour
   forward-fill deliberately erases that signal.** Adding "time since last real (non-ffilled)
   observation" and "observations in the last 6h" as features is cheap and may be one of the
   more informative things you can add. This is a genuinely actionable idea you would not have
   found without this paper.
2. **They advocate ranking over thresholding** — "which patients should we assess first?"
   rather than "is this patient high-risk?". This dissolves the alerts-per-event problem by
   changing the deliverable to a ranked worklist. Given your Ward Monitor UI already displays
   a patient list, **this may be a better product decision than any modeling change** — and
   it plays directly to your model's genuine strength, which is ranking (C-index 0.782), not
   timing (Pearson r 0.21).

Caveat on their AUC: 0.67% mortality. Extreme imbalance inflates AUROC. Do not treat 0.96 as
a target you should reach.

### 4.5 Everything else — brief verdicts

| Family | Verdict | Reasoning |
|---|---|---|
| **Fine-Gray competing risks** | **Not now.** | Death is only 2.8% of your anchors. [Austin 2021](https://pmc.ncbi.nlm.nih.gov/articles/PMC8360146/) shows Fine-Gray can produce predicted risks exceeding 1 and recommends cause-specific hazards when you want per-cause risk. Your current cause-specific censoring is defensible. Say so and move on. |
| **Parametric AFT (Weibull, log-normal)** | Already covered. | You selected logistic over normal/extreme by validation nloglik. The unexplored gap is **σ, hardcoded at 1.0** — tune it before concluding anything about AFT. |
| **Random Survival Forests / scikit-survival GBSA** | Low priority. | No distributional assumption, but slow at 256k rows and unlikely to beat tuned XGBoost on tabular data. |
| **Joint longitudinal-survival (Rizopoulos)** | **No.** | Structurally elegant for biomarker-trajectory → event, but computationally infeasible at 256k observations and needs a specified longitudinal submodel per vital. Dynamic-DeepHit was invented largely because joint models don't scale. |
| **DeepHit / Dynamic-DeepHit** | **Not yet.** | Genuinely designed for repeated measures + competing risks. But you have 2,614 patients with usable positive labels and 54 tabular features — far below where deep survival beats gradient boosting. Revisit only if the label is fixed and data expands. |
| **LSTM / Transformer on raw series** | **No.** | Same reason, more so. |
| **GEE / mixed-effects logistic** | **Useful for inference, not prediction.** | These correctly model within-patient correlation, which your row-wise model ignores. Worth it if you need defensible *effect estimates*; they will not improve ranking. |
| **Landmarking (van Houwelingen)** | **You are already doing it.** | Your hourly-anchor design *is* landmarking. Worth naming explicitly in write-ups — it is the established statistical framework for what you built, and citing it pre-empts "isn't this just leakage?" |
| **Focal loss / cost-sensitive boosting** | **Marginal.** | Reweighting shifts the operating point, which you already control via the threshold. Rarely improves ranking. Low priority. |

### 4.6 Techniques found by this research that were NOT in the prompt's list

Per the prompt's instruction to state this explicitly — yes, three:

1. **Signature methods (path signatures).** The
   [PhysioNet 2019 sepsis challenge winner](https://www.maths.ox.ac.uk/node/33741) (Oxford,
   utility 0.360 of 105 entries) used gradient boosting over *signature features* — a
   principled mathematical summary of a multivariate time series that captures ordering and
   interaction between channels, not just per-channel rolling statistics. This is a direct
   upgrade path for your feature engineering that stays inside gradient boosting, and it is
   the one genuinely novel technical idea this review surfaced. See
   [Morrill et al.](https://pubmed.ncbi.nlm.nih.gov/32897664/).
2. **Temporal label smoothing** ([arXiv:2208.13764](https://arxiv.org/pdf/2208.13764)) —
   a loss function for early-event prediction that treats "predicted 3h early" as better
   than "predicted 20h early" rather than equally correct. Directly targets your false-alarm
   problem at the loss level.
3. **Measurement-frequency as a feature** — from §4.4. Not a model family, but the highest
   value-per-hour idea in this document.

---

## 5. What to do next, in order

**Stage 0 — before touching any model (1 day).**
- Add **AUPRC** and **alarms per patient-hour** to `10_focused_report.py`. Report lift
  alongside PPV. These three numbers change how the current results read, at near-zero cost.
- Implement **alarm deduplication** (one alert per patient per N hours) and recompute the
  false-alarm figures. There is a real chance this alone reframes the problem, and it would
  be wasteful to change models before knowing.

**Stage 1 — fix the label (the main event).**
- Rebuild with the event = **treatment escalation or death**, dropping the NEWS2 crossing.
  `compute_stay_events()` already computes both. Expect AUC to *fall* — probably into the
  0.70–0.78 range — and say so before you run it, so the drop reads as expected rather than
  as failure. **A lower AUC on a real outcome is worth more than a higher AUC on a circular one.**
- Address the **51.5% excluded deteriorators** at the same time by lowering the minimum
  look-back from 6h to 2h (with features degrading gracefully), and re-examine whether
  dropping already-HIGH-band anchors (`01_build_labels.py:221`) is the right call for the
  new label — for an objective outcome, a patient already at NEWS2 ≥ 7 is exactly who you
  want to score.

**Stage 2 — swap the framing (only after Stage 1).**
- Reshape to a **person-period table** and fit a **discrete-time hazard** model with XGBoost
  binary classification. Keep the AFT as the comparator and report both.
- In the same pass, run **`survival:cox`** as the missing baseline (§4.3), and **tune σ**
  for the AFT so the comparison is fair.

**Stage 3 — product framing.**
- Consider shipping a **ranked worklist** rather than a threshold alarm (§4.4). Your model's
  ranking is genuinely good (C-index 0.782 vs the ruler's 0.540); its timing is not
  (Pearson r 0.21). Ship the strength.

**Stage 4 — validation, when someone asks about generalisability.**
- Single-hospital, single-unit, one era. Per TRIPOD+AI / PROBAST this is a
  development-only study and **must not be described as validated**. The credible next step
  is **eICU-CRD** external validation — bidirectional MIMIC↔eICU studies report performance
  degradation under 4% ([example](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12868282/)),
  so this is an achievable, high-credibility addition.
- On cohort size: avoid the "10 events per predictor" rule of thumb —
  [Riley et al. 2019](https://pmc.ncbi.nlm.nih.gov/articles/PMC6519266/) shows required EPP
  varies from ~5 to ~23 by problem. Run `pmsampsize` and quote the actual requirement. With
  2,614 patients contributing positive labels and 54 features, you are likely adequate for
  development and clearly inadequate for claiming validation.

---

## 6. Where the research prompt itself was wrong

Worth recording, since the prompt asked to be challenged rather than followed.

1. **"Deployed systems are classification-based, therefore survival is suspect" — the
   evidence does not support this.** The strongest recent ward-deterioration paper found
   time-to-event Cox *beating* binary classification (0.96 vs 0.93). The field is moving
   toward, not away from, time-to-event framings. The prompt treated a convention as evidence.
2. **The prompt asked the wrong top-level question.** It asked "is AFT the right family?"
   The binding constraint is the label, which no answer to that question touches. Framing
   the review around model families was itself the error — the same class of process failure
   the prompt's own §B4 was written to prevent.
3. **Ordinal regression was accepted too readily as a strong candidate.** §B3 called it
   "genuinely strong" without checking censoring compatibility, which turns out to be
   disqualifying in its standard forms (§4.2).
4. **The 37,000 vs 10,775 discrepancy remains unreconciled.** Not resolvable from the code;
   still needs checking against extraction logs before being repeated.
5. **Two code-level issues the prompt never mentioned**, both found by reading the source:
   **σ hardcoded to 1.0** (`09_focused_train.py:67`) despite controlling every emitted
   probability, and **already-HIGH-band anchors silently dropped** (`01_build_labels.py:221`),
   which narrows the cohort further on top of the known 51.5% exclusion.

---

## Sources

- [Multicenter Development and Prospective Validation of eCARTv5](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC11949291/) — Churpek et al.
- [Less is More: Detecting Clinical Deterioration Using Only Age, Heart Rate, and Respiratory Rate](https://pmc.ncbi.nlm.nih.gov/articles/PMC9128300/) — eCART Lite
- [External Validation of a Widely Implemented Proprietary Sepsis Prediction Model](https://pubmed.ncbi.nlm.nih.gov/34152373/) — Epic
- [Early prediction of circulatory failure in the ICU using machine learning](https://www.nature.com/articles/s41591-020-0789-4) — Hyland et al., Nature Medicine 2020
- [Prioritising deteriorating patients using time-to-event analysis](https://pmc.ncbi.nlm.nih.gov/articles/PMC11256441/) — Critical Care 2024
- [Development and Validation of a NEWS2-Enhanced Multivariable Prediction Model](https://pmc.ncbi.nlm.nih.gov/articles/PMC12471953/) — the target-leakage precedent
- [Survival prediction models: an introduction to discrete-time modeling](https://pmc.ncbi.nlm.nih.gov/articles/PMC9316420/)
- [A scalable discrete-time survival model for neural networks](https://pubmed.ncbi.nlm.nih.gov/30701130/) — Gensheimer & Narasimhan
- [Ordinal Semiparametric Regression for Survival Analysis](https://hbiostat.org/rmsc/ordsurv) — Harrell, RMS
- [Survival regression with accelerated failure time model in XGBoost](https://arxiv.org/pdf/2006.04920) — Barnwal et al.
- [Fine-Gray models: cumulative total failure probability may exceed 1](https://pmc.ncbi.nlm.nih.gov/articles/PMC8360146/) — Austin
- [Use of AUPRC to Evaluate Prediction Models of Rare Critical Illness Events](https://pmc.ncbi.nlm.nih.gov/articles/PMC12133047/)
- [Minimum sample size for developing a multivariable prediction model, Part II](https://pmc.ncbi.nlm.nih.gov/articles/PMC6519266/) — Riley et al.
- [Reducing Alarm Burden in a Level IV NICU](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC10990340/)
- [PhysioNet/CinC Challenge 2019 winner — signature methods](https://www.maths.ox.ac.uk/node/33741) · [Morrill et al.](https://pubmed.ncbi.nlm.nih.gov/32897664/)
- [Temporal Label Smoothing for Early Event Prediction](https://arxiv.org/pdf/2208.13764)
- [Bidirectional MIMIC-IV / eICU cross-validation](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12868282/)
