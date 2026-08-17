# Critical Evaluation + Deep-Research Prompt — Is AFT Survival the Right Framing?

> **What this file is:** a durable, standalone research/analysis deliverable —
> not a code-change plan. Contains (A) direct, data-grounded answers to
> dataset/false-positive/metrics questions, (B) an honest from-scratch critical
> evaluation of the current AFT survival framing, and (C) a long, fully
> self-contained research prompt for a dedicated research session (ideally with
> live web search) to go further than any single conversation can. Written
> 2026-07-17, updated same day after a supervisor meeting raised ordinal
> regression as a candidate — the update generalizes Part C so no single
> suggested technique is ever again the only reason a strong candidate gets
> considered.

---

## PART A — Direct answers, grounded in real local data (not estimated)

### A1. Is the dataset only deteriorated patients, or both?
**Both.** Cohort = 10,775 CCU stays (MIMIC-IV). 5,424 (50.3%) reach a sustained
NEWS2≥7 at some point; the remaining 5,351 (49.7%) never do and are the
genuine negative/control population. At the row (anchor) level, of 256,712
hourly observations:

| cause | rows | % |
|---|---|---|
| administrative (stable, discharged without event) | 188,315 | 73.4% |
| deterioration (a true positive window) | 34,079 | 13.3% |
| censored_horizon (will deteriorate, but >24h away from this hour) | 27,160 | 10.6% |
| death (competing risk, censored) | 7,158 | 2.8% |

**Nuance that matters for how this gets communicated:** the *model* (the AFT
fit) already uses all of this — non-event and event patients alike, via the
censored likelihood. But several of the most visually prominent **diagnostic
plots** (the actual-vs-predicted scatter, error-by-bin, per-patient SHAP) are
necessarily computed only on `event==1` rows, because "actual time-to-event"
is undefined for a patient who never had one. If those plots were what got
emphasized in a review meeting, that alone could create the impression the
whole analysis is events-only, even though training is not. Worth
disentangling explicitly before concluding the dataset itself needs rebuilding
versus just needing different plots surfaced more prominently.

**Also confirmed by re-reading the code directly (not memory):** patients who
die during the stay are **not removed** from the cohort. `01_build_labels.py`
right-censors their pre-death anchors (`cause="death", event=0`) and keeps
them. If "patients who die are removed" was communicated to anyone as how the
pipeline works, that is not accurate to the code as it stands.

**An unresolved discrepancy, flagged honestly rather than papered over:** a
verbal description of this same model in a review meeting cited "~37,000
patients, ~5,000 meeting criteria." Direct query of the actual pipeline data
finds 10,775 CCU stays / 5,424 meeting criteria. These do not reconcile. It's
unclear whether 37,000 refers to an earlier, broader, unfiltered pull (e.g.
before CCU-only restriction) or was an approximate verbal figure. **This should
be checked against actual extraction logs before being repeated as fact.**

### A2. Is the dataset diverse? (the uncomfortable answer)
- **Demographically**: mean age 67.7 (range 18–91), 57.8% M / 42.2% F —
  reasonably balanced by sex, skewed older (expected for a cardiac CCU). Event
  rate rises with age (28.9% at 18–50 → 37.7% at 80+) and is higher in DCM
  patients (42.9% vs 33.2%) — clinically sane sanity checks, not red flags.
- **Institutionally: NOT diverse, and this matters.** Single hospital (Beth
  Israel Deaconess via MIMIC-IV), single country, single unit type (CCU), one
  blended era of practice (2008–2019). No external hospital, no non-US
  population, no general-ward data. Generalizability beyond "a CCU that charts
  like BIDMC" is **unproven**.
- **A serious selection bias, found by direct query:** of the 5,424 true
  deteriorators, **2,794 (51.5%) contribute ZERO usable training anchors** —
  not from any censoring rule, but because their *entire recorded CCU stay is
  shorter than the 6-hour minimum lookback window* the pipeline requires
  before generating even one feature row. Only 2,614 (48.2%) of true
  deteriorators ever produce a labeled positive example. **The model is
  trained/evaluated on a population that systematically excludes the fastest,
  most acute deteriorators** — precisely the patients an early-warning system
  matters most for.

### A3. How are false positives / metrics actually computed today?
- Unit of analysis is the **anchor** (one patient-hour), not the patient — "alerts
  per event" counts alarm-hours, not distinct erroneous patients. There is
  currently no alarm-deduplication/hysteresis logic, which inflates the
  apparent false-alarm count relative to bedside experience.
- At horizon h, an anchor's status is only used if **knowable**: event by h,
  or still observed at h without an event. Anchors censored before h with no
  event yet are **dropped**, not counted as negatives.
- A **threshold is picked to catch a fixed 80% of true events**; false
  positive = predicted-positive AND no real event within h. Alerts-per-event =
  (TP+FP)/TP.
- Metrics used: AUC, sensitivity/specificity/PPV at the chosen threshold,
  alerts-per-event, Harrell's C-index. Accuracy deliberately excluded (useless
  under a ~13% event rate).

### A4. Why is sensitivity fixed at 80%?
A chosen, tunable operating point, not a law. Missing a true deterioration is
conventionally treated as costlier than an extra false alarm, so systems are
tuned to catch a high fraction of events (80–90% is a common band) and
false-alarm cost is measured *at that catch rate*. Not yet validated against
this hospital's actual clinical risk tolerance.

### A5. Isotonic calibration, in plain terms
A monotonic step-function correction, fit on held-out data, that remaps a raw
"probability-shaped" score to match real observed frequency — without ever
changing the *ranking* of who is riskier than whom. After calibration, "24%
predicted risk" can be checked against real outcomes and trusted at face value.

### A6. Per-patient SHAP, in plain terms
Global SHAP = "across everyone, which signals matter most on average."
Per-patient SHAP = "for this ONE patient at this ONE hour, which of *their*
numbers pushed the prediction up or down, and by how much" — lets a clinician
interrogate one specific alarm instead of trusting a black box.

---

## PART B — Critical evaluation, from scratch, no sugar-coating

### B1. Steelman for the current AFT survival approach
Uses every patient without discarding non-events; produces a full risk
trajectory, not one number; handles variable observation lengths; is a real,
published clinical-ML approach (Cox PH, Random Survival Forests, DeepSurv,
Dynamic-DeepHit have all been used for ICU time-to-event tasks) — not fringe.

### B2. The uncomfortable case against it
- The raw median is **provably uninterpretable** under our event rate (Pearson
  r=0.13 vs actual time) — required a workaround (conditional expected time +
  horizon-specific calibrated probability) to be usable at all.
- **That workaround — calibrated P(event≤h) — is functionally a classifier
  output.** The survival machinery's real advantage reduces to reading
  probabilities at several horizons from one shared model instead of training
  separate classifiers — a modest efficiency gain, not proof of superiority.
- Major deployed clinical early-warning systems (eCART, Epic Deterioration
  Index, Rothman Index) are built as **classification at a fixed window**, not
  time-to-event survival — worth weighing as a signal, to be verified/
  challenged by the research pass, not taken on faith.
- Plain quantile regression on time (the pre-AFT instinct) is a worse
  alternative, not a fallback — it can't use censored patients at all without
  an ad-hoc fix, which is why the project moved to AFT in the first place.
  Flagging this so a future pass doesn't waste time re-discovering it.
- The high false-positive rate (PPV 0.12–0.35) is **most likely a feature/data
  richness problem, not a framing problem** — NEWS2-only inputs are narrow for
  a heterogeneous CCU population. Switching frameworks alone likely won't fix
  this; the two issues need to be tested separately, not conflated.

### B3. Ordinal regression — added after a supervisor meeting, evaluated on its merits, not accepted on authority
A supervisor raised ordinal regression, citing Cao/Mirjalili/Raschka
("Rank-consistent ordinal regression for neural networks," arXiv:1903.09795 —
the **CORAL**/later **CORN** framework), noting the concept doesn't require
deep learning. On independent evaluation this is a genuinely strong candidate,
for reasons that hold regardless of who suggested it:
- **The core mechanism**: decompose "which time-bucket will this patient
  deteriorate in" into a stack of binary "will it happen by bucket k?"
  questions sharing features, with monotonically-decreasing probabilities
  guaranteed across buckets. The non-deep-learning ancestor of this exact idea
  is **Frank & Hall (2001), "A Simple Approach to Ordinal Classification"** —
  train K−1 binary classifiers on cumulative thresholds with any base learner,
  directly implementable in XGBoost this week.
- It **structurally forces inclusion of non-event patients** ("never
  deteriorates / beyond 24h" becomes the natural terminal category) — a more
  elegant fix for the dataset-composition concern than calibrating a survival
  model after the fact.
- It **sidesteps the median-uninterpretability problem by construction** —
  never estimates a precise timestamp, only bounded, ordered probabilities.
- Classical, non-DL implementation available today: proportional-odds ordinal
  logistic regression (**McCullagh 1980**) with mature tooling
  (`statsmodels.OrderedModel`, R's `polr`, `mord`).
- **Honest caveats, not to be waved away**: the proportional-odds assumption
  (same covariate effect across every threshold) may not hold clinically and
  must be tested (Brant/score test), not assumed; splitting the already-rare
  event across more buckets thins the short-horizon tail further even as total
  usable N grows; bucket boundaries are a design choice needing justification;
  competing-risks (death) handling isn't automatically solved by switching
  frameworks.

### B4. The meta-lesson this update exists to fix
Ordinal regression only entered this analysis because someone happened to
mention it in a meeting. That is a process failure, not a happy accident — if
it hadn't come up, it would have been silently absent from a document that
claimed to be a comprehensive evaluation. **Part C below is restructured so this
cannot happen again**: it enumerates every major modeling family this project
is currently aware of, and separately instructs the research pass to actively
search past that list rather than treat it as exhaustive.

---

## PART C — The detailed research prompt (hand this to a dedicated research session)

```
You are conducting a rigorous, skeptical research review. Do not be diplomatic
or reassuring -- if an approach is weak, say so plainly and explain exactly
why. Do not accept any framing below as settled; re-derive the right answer
from first principles and evidence, even if it contradicts what's described
here. CRITICALLY: the candidate list in section 2 below reflects what the
project team currently knows about -- it is explicitly NOT presented as
exhaustive, and your job includes finding strong candidates this list may be
missing, the same way ordinal regression was nearly missed here simply because
no one had mentioned it yet. Do not silently limit your answer to the named
list.

CONTEXT -- the system as it exists today:
We are building an early-warning model to predict clinical deterioration for
adult patients in a cardiology Coronary Care Unit (CCU), using MIMIC-IV ICU
data (a single US hospital, Beth Israel Deaconess, 2008-2019).

- Cohort: 10,775 CCU stays. 5,424 (50.3%) reach a "deterioration" event at some
  point (sustained NEWS2 >= 7 for 2 consecutive hourly readings); the rest never
  do. Mean age 67.7, 57.8% male / 42.2% female. (A separate verbal account of
  this same project cited ~37,000 patients / ~5,000 events -- this has not been
  reconciled with the numbers above; note the discrepancy rather than resolving
  it silently if you encounter related figures.)
- Data construction: hourly hindsight windows ("anchors") built from a 6-hour
  look-back of vitals per patient-hour, used to predict time-to-event, with an
  administrative censoring cap at 24 hours. 256,712 total anchor-hours; 13.3%
  are true-positive windows, 73.4% are stable/censored, 10.6% are "too far from
  a future event to count within this horizon," 2.8% are competing-risk deaths.
- KNOWN, CONFIRMED DATA LIMITATION: 51.5% of patients who truly deteriorate
  (2,794 of 5,424) are excluded from ever contributing a labeled training
  example, because their entire recorded stay is shorter than the 6-hour
  look-back requirement -- i.e., the fastest/most acute deteriorators are
  invisible to the current pipeline. Design around this; do not explain it away.
- Repeated-measures structure: each patient contributes MANY correlated hourly
  observations (not i.i.d. rows) -- flag whether/how each candidate approach
  below accounts for this (or fails to).
- Competing risk: in-hospital death is currently handled as cause-specific
  right-censoring (a patient who dies without deteriorating first is censored
  at death time, not treated as a deterioration). Evaluate whether this is
  adequate or whether formal competing-risks methods (e.g. Fine-Gray) are
  warranted.
- Features: ONLY the 7 NEWS2 clinical parameters (heart rate, respiratory rate,
  SpO2, systolic/diastolic blood pressure, temperature, consciousness) plus
  their rolling-window trends (mean/std/min/max/rate-of-change), plus minimal
  demographic context (age, sex, hours since admission). No labs, no weight, no
  biomarkers.
- Current model: a single XGBoost `survival:aft` (Accelerated Failure Time)
  model, chosen distribution = logistic. Because the raw median time output was
  found to be nearly uninterpretable (Pearson r = 0.13 against actual
  time-to-event, for mathematical reasons tied to a sub-50% within-horizon event
  rate), the team derives a calibrated probability of "deteriorates within h
  hours" (h = 6, 12, or 24) from the same fitted distribution, isotonic-
  calibrated on a held-out split, as the actual clinically-facing output.
- Current measured results (test set, patient-level train/test split, no
  leakage): C-index 0.782 (train 0.815). AUC for "deteriorates within 12h" =
  0.802 (train 0.834; 6h AUC = 0.821, 24h AUC = 0.778). At an 80%-sensitivity
  operating point: PPV 0.12/0.22/0.35 and 8.2/4.5/2.8 false alarms per true
  event caught, at the 6h/12h/24h horizons respectively. A trivial
  linear-extrapolation-of-NEWS2-score baseline scores C-index ~0.54 (barely
  above chance) and, at the same operating point, degenerates to alerting on
  essentially 100% of patients -- i.e. it adds no real information.
  Decision-curve (net benefit) analysis shows the model beats both "alert
  everyone" and "alert no one" strategies across realistic alert thresholds
  (1-50%).

YOUR TASK:

1. SURVEY DEPLOYED / VALIDATED CLINICAL EARLY-WARNING SYSTEMS, comprehensively:
   NEWS2, MEWS, qSOFA, APACHE II/SAPS, the Rothman Index, eCART / eCARTv5
   (Churpek et al.), the Epic Deterioration Index, and any others you find. For
   each: target/label predicted (binary fixed-window? continuous score?
   time-to-event?), model class, and published false-positive/PPV/AUC/
   sensitivity numbers at comparable operating points (~80% sensitivity where
   possible).

2. EVALUATE EVERY MAJOR MODELING FAMILY BELOW for this specific task
   (repeated-measures hourly vitals -> time/probability of a rare clinical
   deterioration event, with right-censoring and a competing death risk). For
   EACH family, report: what label/target it uses; whether it naturally
   includes censored/non-event patients or needs a workaround; how it handles
   (or ignores) the repeated-measures/correlated-observations structure; its
   calibration maturity; typical false-positive/AUC/PPV numbers reported in
   comparable clinical deterioration literature if available; and
   implementation cost/maturity of tooling. Do not skip a family because it
   seems unlikely -- report the negative verdict explicitly with reasoning
   rather than omitting it.

   FAMILY 1 -- Classical statistical baselines (interpretable, well-understood):
     - Logistic regression at one or more fixed horizons.
     - Ordinal logistic / proportional-odds regression (McCullagh 1980) for
       multi-bucket time-to-event labels (e.g. "<2h / 2-4h / 4-12h / 12-24h /
       never-within-24h"), including whether the proportional-odds assumption
       plausibly holds here and what to do if it doesn't (partial proportional
       odds, generalized ordered logit).
     - Generalized Estimating Equations (GEE) and mixed-effects (hierarchical)
       logistic regression, which explicitly model the repeated-measures/
       within-patient correlation that plain row-wise classifiers ignore.
     - Landmarking (van Houwelingen 2007) -- the formal statistical framework
       for "refit/re-predict at each landmark time using only data available
       so far," which the current hourly-anchor design already resembles;
       compare against landmarking best practices specifically.

   FAMILY 2 -- Classical survival analysis (non-ML, decades of clinical use):
     - Cox Proportional Hazards (the standard the field defaults to before any
       AFT/ML variant -- was this ever benchmarked directly with the same
       features? If not documented, flag it as a missing baseline.)
     - Parametric AFT beyond logistic (Weibull, log-normal, generalized gamma)
       -- partially explored already, confirm nothing better was skipped.
     - Fine-Gray subdistribution hazard model for proper competing-risks
       handling (death vs. deterioration) vs. the current cause-specific
       censoring approach.
     - Aalen additive hazards model (relaxes the proportional-hazards
       assumption Cox relies on).
     - Joint longitudinal-survival models (Rizopoulos 2012 framework) --
       explicitly designed for "predict time-to-event from a repeatedly
       measured biomarker trajectory," which is structurally very close to
       this exact problem (hourly NEWS2/vitals -> time to deterioration).
       Evaluate seriously, not as a footnote.

   FAMILY 3 -- Tree ensembles / gradient boosting (non-deep, practically
   deployable with current tooling):
     - XGBoost/LightGBM/CatBoost binary classifiers at fixed horizons (single-
       or multi-task/shared-tree variants).
     - XGBoost's native `survival:cox` objective as an UNTESTED alternative to
       the `survival:aft` objective already used, within the same toolkit.
     - Random Survival Forests (Ishwaran et al. 2008) and Gradient Boosting
       Survival Analysis / ComponentwiseGradientBoostingSurvivalAnalysis
       (scikit-survival) -- nonparametric, no proportional-hazards or AFT
       distributional assumption.
     - Ordinal regression via extended binary classification with a GBM base
       learner (Frank & Hall 2001) -- the non-deep-learning implementation
       path for the ordinal idea in item below.

   FAMILY 4 -- Discrete-time / hybrid hazard models (a recognized middle
   ground between survival and classification):
     - Discrete-time hazard / "Nnet-survival" (Gensheimer & Narasimhan 2019).
     - Logistic-Hazard / PC-Hazard (Kvamme & Borgan, the `pycox` package).
     - DeepHit (Lee et al. 2018) and its competing-risks/recurrent extension
       Dynamic-DeepHit (Lee et al. 2020) -- explicitly built for repeated
       measurements + competing risks, i.e. structurally close to our exact
       scenario.

   FAMILY 5 -- Deep sequence models (heavier, only worth it if evidence
   justifies the complexity):
     - LSTM/GRU/Temporal-CNN/Transformer classifiers directly on the raw
       vitals time series (cf. Harutyunyan et al. 2019, MIMIC-III multitask
       clinical time-series benchmark).
     - DeepSurv (Katzman et al. 2018, neural Cox model).
     - Deep Survival Machines (Nagpal et al. 2021, mixture-of-parametric-
       experts survival model, more flexible than a single AFT distribution).
     - CORAL / CORN (Cao, Mirjalili & Raschka, arXiv:1903.09795) -- the
       rank-consistent deep ordinal regression framework a supervisor
       specifically raised; evaluate it properly, including whether its
       rank-consistency guarantee actually matters more than the classical
       Frank & Hall non-DL version for a dataset this size.

   FAMILY 6 -- Rare-event / imbalance-specific techniques that can be layered
   on top of ANY of the above (evaluate as modifiers, not standalone
   competitors): focal loss, cost-sensitive boosting, and post-hoc alarm
   deduplication/hysteresis (e.g. requiring elevated risk to persist for N
   consecutive hours before alerting) as a lever specifically for reducing the
   alerts-per-event false-alarm rate independent of model family.

   AFTER covering the above, EXPLICITLY STATE whether your own research
   surfaced any additional model family or technique not listed here that is
   used in comparable clinical deterioration/early-warning literature, and
   include it with the same level of evaluation. If you find nothing beyond
   this list, say so explicitly rather than leaving it ambiguous.

3. ANY PUBLISHED HEAD-TO-HEAD COMPARISONS of two or more of the above framings
   on the SAME clinical deterioration/ICU task (not just isolated papers about
   one framing in the abstract). Also check PhysioNet Challenge results (e.g.
   the 2019 Early Prediction of Sepsis challenge) for concrete achievable
   false-positive rates and which modeling approaches won.

4. ASSESS THE FALSE-POSITIVE RATE we're seeing (PPV 0.12-0.35, i.e. roughly
   65-88% of alerts are false alarms at 80% sensitivity) against what is
   achievable/typical in comparable published systems at similar sensitivity
   targets. What levers (feature richness, cohort narrowing, alarm
   deduplication/hysteresis, different model families, different operating
   points) have other teams used successfully to reduce false alarms without
   sacrificing sensitivity, and which are most likely to help here given
   NEWS2-only features?

5. ASSESS THE DATASET: is a single-hospital, single-ICU-type (CCU),
   ~10,000-patient MIMIC-IV cohort adequate for training/validating a
   deterioration model intended to generalize, per current research
   consensus/best practice (e.g. TRIPOD, PROBAST) on required cohort size,
   diversity, and external validation for clinical ML models?

6. DELIVER A CLEAR, UNHEDGED VERDICT: given everything above, which single
   modeling family (or minimal combination) would you recommend pursuing next,
   and why, with citations? If it's ordinal regression, say so and specify
   which variant (classical proportional-odds vs. Frank & Hall extended binary
   vs. CORAL/CORN) and why. If it's something not yet named in this prompt,
   name it explicitly. If you conclude the current AFT survival approach is
   actually defensible as-is, say so plainly and specify exactly what would
   need to change to fix the false-positive rate. Do not hedge with "it
   depends" without resolving what it depends on for THIS specific case.

Do not lose any of the numeric context above when reasoning -- refer back to
the specific measured numbers (C-index, AUC, PPV, alerts-per-event, the 51.5%
excluded-deteriorator finding, the repeated-measures structure) throughout your
answer rather than discussing the topic in the abstract.
```

---

## Verification / how to use this
- Part A is grounded in live queries against `data/cohort.parquet` and
  `data/anchors_news2.parquet` (session of 2026-07-17); reproducible commands
  are in `SESSION_HANDOFF_2026-07-17.md` §6.
- Part C is fully self-contained — paste it into a fresh research session
  (ideally with live web search) without needing any other file from this
  project.
- If a future session adds yet another candidate technique from a meeting/
  paper/colleague, the correct move is to add it to FAMILY 1-6 (or a new
  family) in this file, not to treat it as a one-off addendum — the whole
  point of the restructure in this update was to stop depending on someone
  happening to mention the right name.
