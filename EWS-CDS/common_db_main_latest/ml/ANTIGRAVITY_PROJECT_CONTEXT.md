# Project Context — EWS Deterioration Model (read this in full before answering any question)

**Purpose of this file:** complete, accurate, numbers-grounded context for an AI assistant
(Antigravity or otherwise) picking this project up cold. Every number below is read directly
from `data/metrics_focused.json` / `data/stage0_verification_news2.json` on 2026-07-23, not
estimated or remembered. If asked anything about this project, ground the answer in this file
and the source files it points to — do not guess at numbers.

**STALENESS NOTICE (added later, read this first):** `SESSION_HANDOFF_ordinal_model_v1.md` in
this same directory was written 2026-07-27, four days after this file, by a session that
re-ran the Stage-0 pipeline fix and got slightly larger/better numbers (e.g. 298,679 anchor
rows / 9,157 stays, vs. this file's 256,712 / 7,724). **Where the two files disagree on a
headline number, trust `SESSION_HANDOFF_ordinal_model_v1.md` — it is newer.** This file remains
accurate for mechanics, the FAQ, and anything not superseded by a rerun. Read both; if in doubt,
recompute from `data/metrics_focused.json` directly rather than trusting either file's prose.

**Standing rule for any answer about this project (from the user's global CLAUDE.md, applies
here directly):** never state a metric, chart, or number without defining it, showing how it's
computed, and explaining how to read it. This project had one meeting go badly from unexplained
numbers — do not repeat that.

---

## 1. What this project is, in one paragraph

An early-warning model predicting clinical deterioration for adult patients in a cardiology
Coronary Care Unit (CCU), built on MIMIC-IV ICU data (single hospital — Beth Israel Deaconess,
2008–2019). Part of a larger integrated hospital product (Foqal CareOS); this `ml/` folder is
a standalone research pipeline, separate from the live Ward Monitor app (`ashmit project/`) —
changes here do not need deployment and do not touch the live system. Owner/user: Sabari
(a student); academic supervisor: Prof. Gautam Shroff, who has reviewed this work twice and
driven several of the design decisions below.

---

## 2. The arc of this project (chronological, so history questions can be answered correctly)

1. **Composite-event AFT model** (earliest): event = escalation OR sustained NEWS2≥7 OR death.
   C-index 0.75/0.80(DCM). Superseded.
2. **Pivot to "focused" model** (professor's instruction: validate one clean event before
   adding complexity): event narrowed to **sustained NEWS2≥7 alone**, features narrowed to
   **NEWS2-only** (~54 columns: the 7 clinical parameters, rolling-window trends, NEWS2 score
   dynamics, minimal context). Model: XGBoost `survival:aft`. This surfaced two real problems:
   the raw AFT median was mathematically uninterpretable (Pearson r≈0.13 vs actual time — a
   known artifact when P(event≤horizon)<50%), and a **51.5% coverage gap**: 2,794 of 5,424 true
   NEWS2-deteriorators produced **zero training anchors** because the pipeline required a full
   6-hour vitals look-back before generating any row.
3. **Second professor review (2026-07-23, harshest round)** raised five specific, unanswered
   questions (what exactly does the model output — time/probability/curve; what happens at
   different alert thresholds; what does "horizon" mean precisely — worked example needed; how
   are false positives actually computed; which line in each plot is which) and suggested
   **ordinal regression** as an alternative, citing his own paper
   (arXiv:1903.09795, Vishnu/Malhotra/Vig/**Shroff** 2019 — not CORAL, despite an early
   misidentification in this project's history). Key finding on re-reading his paper: its
   censoring-handling mechanism (mask unknown post-censoring binary sub-problems in the loss)
   is **structurally identical to discrete-time survival modeling** — so his suggestion and a
   time-to-event framing are the same family, not competitors.
4. **This session (2026-07-23): rebuilt as a discrete-time hazard model** (conditional-hazard
   parameterization — chosen over the literal cumulative form from his paper because
   monotonicity of the survival curve then falls out automatically from the math, `S(c_j) =
   S(c_{j-1})×(1−hazard_j)`, rather than needing a post-hoc patch), XGBoost base learner (MLP
   considered, deferred — see §7). **Also fixed the 51.5% coverage gap** via a
   graceful-degradation pipeline change (see §5). **Also added alarm-episode deduplication**
   and a full "industry-grade" report (Brier score, ECE, calibration slope, bootstrapped CIs,
   Table 1, subgroup breakdown, external-benchmark comparison, written limitations).

**The plan file for this whole effort** (comprehensive, self-contained, has its own execution
history):
`C:\Users\sabari krishna\.claude\plans\common-db-main-latest-session-handoff-20-melodic-abelson.md`

---

## 3. Where everything lives — file map

**Pipeline (run in this order to reproduce):**
| File | Role |
|---|---|
| `00_extract_cohort.py` | BigQuery → parquet extraction (already run; data on disk, no need to re-run) |
| `01_build_labels.py` | Builds hourly vitals grid, NEWS2 replay, survival labels/anchors. Has `--event {composite,news2}`. **Contains the Stage-0 lookback fix** (see §5). |
| `02_build_features.py` | Feature engineering (rolling-window stats, NEWS2 dynamics, labs axis). **Contains the `hours_of_history` feature** (Stage-0 fix) and the labs feature block (`LABS_FEATURE_PREFIXES`, referenced from `09_focused_train.py`). |
| `03_train.py` | Shared helpers: `three_way_split` (patient-level 70/15/15, `GroupShuffleSplit`, no patient crosses splits), `make_dmatrix` (AFT censored-label encoding), `train_aft`. Imported by both AFT scripts. |
| `known_status.py` | `known_at`/`label_at`/`known_subset`/`dropped_fraction` — the "is the outcome knowable at horizon h" masking logic. |
| `09_focused_train.py` | **AFT model, NEWS2-only features** (retrained on Stage-0-fixed data). |
| `13_focused_train_labs.py` | AFT retrained with labs/congestion features added (labs barely changed the numbers — see §6). |
| `12_ordinal_train.py` | **The primary v1 model: discrete-time hazard, NEWS2-only features.** Person-period table construction, per-interval XGBoost classifiers, isotonic calibration, survival-curve reconstruction. |
| `14_ordinal_train_labs.py` | Discrete-time hazard retrained with labs added (also barely changed the numbers). |
| `10_focused_report.py` | Generates all 14 charts + `metrics_focused.json`. Reusable/model-agnostic — reads whichever `preds_*.parquet` it's pointed at. |
| `verify_stage0_fix.py` | Verifies the lookback fix recovered the expected patients; writes `data/stage0_verification_news2.json`. |

**Key data files:**
- `data/metrics_focused.json` — **every number in this project, traceable.** Top-level keys:
  `horizon_utility`, `alarm_episode_comparison`, `threshold_sweep`, `calibration`,
  `overfit_check`, `decision_curve`, `case_studies`, `table1_cohort`, `model_comparison`,
  `benchmark_context`, `subgroup_breakdown`, `scatter_corrected`, `error_by_bin`,
  `scatter_naive_aft`, `limitations`, `meta`, `meta_aft`.
- `data/stage0_verification_news2.json` — the lookback-fix recovery numbers (§5).
- `data/preds_ordinal_news2.parquet` — primary model's full predictions (train+calib+test).
- `data/preds_focused_news2.parquet` — AFT's predictions, same (Stage-0-fixed) data, for fair
  comparison.
- `data/anchors_news2.parquet`, `data/features_news2.parquet` — the Stage-0-regenerated
  training data (larger/different from the original pre-fix versions still on disk as
  `anchors.parquet`/`features.parquet`, which are the OLD composite-event build — do not confuse
  the two).

**Charts** — `data/charts_focused/*.png`, 14 files, numbered in presentation order:
| # | File | What it shows |
|---|---|---|
| 00 | `00_ordinal_concept_diagram.png` | Explains the discrete-time hazard concept itself |
| 01 | `01_horizon_utility.png` | Sensitivity/specificity/PPV/alerts-per-event per horizon |
| 01b | `01b_alarm_episode_comparison.png` | Anchor-level vs episode-level (deduplicated) alarm rate — the ~6.4× reduction (§6) |
| 02 | `02_threshold_sweep.png` | Sensitivity vs. alerts-per-event tradeoff curve |
| 03 | `03_calibration.png` | Reliability plot — predicted probability vs. observed frequency |
| 04 | `04_overfit_check.png` | Train vs. test metric gap |
| 05 | `05_decision_curve.png` | Net-benefit vs. treat-all/treat-none (Vickers & Elkin) |
| 06 | `06_case_studies.png` | Real patient trajectories: NEWS2 vs. calibrated risk vs. alert threshold |
| 07 | `07_table1_cohort.png` | Cohort description table |
| 08 | `08_model_comparison.png` | Hazard vs. AFT vs. ruler, side by side |
| 08b | `08b_benchmark_context.png` | Our PPV vs. published industry systems (eCART, Epic DI, Hyland et al.) |
| 09 | `09_subgroup_breakdown.png` | Performance split by DCM flag and age band |
| 10 | `10_scatter_corrected.png` | Actual vs. predicted time — **secondary output, see §4** |
| 11 | `11_error_by_bin.png` | MAE/MAPE of the time estimate by actual-time bin |
| 12 | `12_scatter_naive_aft.png` | The old naive AFT scatter, kept for before/after reference |
| 13 | `13_scorecard.png` | Executive summary tile grid |
| 14 | `14_limitations.png` | **Written limitations, rendered into the report itself** — not left implicit |

**Background/history docs** (read only if asked about *why*, not *what*):
- `RESEARCH_PROMPT_deterioration_model.md` — the original deep-research prompt (Part C).
- `RESEARCH_FINDINGS_deterioration_model_2026-07-20.md` — the research pass's findings (industry
  benchmark survey, model-family evaluation). Some content here (e.g. "fix the label to
  escalation") was later **superseded** by the professor's explicit direction that predicting
  future NEWS2 is not leakage — see §7.
- `FALSE_POSITIVE_COMPARISON_and_professor_reply.md` — cross-system PPV comparison + a drafted
  reply to the professor.
- `FOCUSED_MODEL_EXPLAINED.md`, `DIAGNOSTICS_EXPLAINED.md` — plain-language explainers for the
  (now superseded) focused-AFT-only iteration.

---

## 4. The primary model — precisely, so it can be explained correctly

**What it is:** a **discrete-time hazard** model. Time is cut into ordered intervals
`h ∈ {2,4,6,9,12,18,24h}`. For each interval, one XGBoost binary classifier predicts the
**conditional hazard** — `P(fail in this interval | still at risk at its start)` — trained on a
**person-period table** (each patient-anchor contributes one row per interval they're at risk
for; a patient discharged/censored mid-interval contributes no row for that interval or later —
this masking is what makes the model use every patient, not just those who deteriorate).
Each interval's hazard is isotonic-calibrated. The survival curve is reconstructed as a running
product: `S(c_j) = S(c_{j-1}) × (1 − calibrated_hazard_j)` — monotonically non-increasing **by
construction**, not by a post-hoc patch.

**Output priority — primary vs. secondary, do not conflate:**
- **PRIMARY output: calibrated per-interval/cumulative probability** — `P(deteriorate by h)`
  at each horizon. This is what drives alerting and is the evidence of the model's accuracy
  (via AUC, AUPRC, calibration, Brier score).
- **SECONDARY output: `E[T|T≤24h]`**, a conditional expected time-to-deterioration, derived by
  weighting bucket midpoints by their probability. **This is reported as context only, never as
  evidence of accuracy** — collapsing a probability profile into one scalar re-introduces a
  version of the same fake-precision problem that made the raw AFT median misleading. If asked
  "why is the time estimate still not great," the honest answer is in §6 — it's a real,
  disclosed, only-partially-fixed limitation.

**Model comparison (12h horizon, all on the same Stage-0-fixed data — fair comparison):**

| Model | AUC | AUPRC | PPV | Alerts/event | Lift | C-index |
|---|---|---|---|---|---|---|
| **Discrete-time hazard (PRIMARY)** | 0.810 | 0.362 | 0.234 | 4.27 | 2.03× | 0.791 |
| Discrete-time hazard + labs | 0.810 | 0.365 | 0.236 | 4.24 | 2.04× | 0.789 |
| AFT (retrained, NEWS2-only) | 0.808 | 0.350 | 0.225 | 4.45 | 1.95× | 0.789 |
| NEWS2-slope ruler (floor) | 0.545 | 0.151 | 0.115 | 8.66 | 1.00× | 0.540 |

**Definitions (state these before quoting the table):**
- **AUC** — probability the model ranks a random true-event patient above a random non-event
  one, at this horizon. 0.5 = random, 1.0 = perfect.
- **AUPRC** — area under precision-recall curve; more honest than AUC under rare events (13%
  base rate here); a no-skill model scores equal to the base rate, not 0.5.
- **PPV** — of patients flagged positive, the fraction who actually deteriorate within the
  horizon. This is what a clinician experiences directly as "was this alarm real."
  **AUPRC/PPV/Lift, not raw AUC, are the numbers that matter for the false-positive
  conversation** — see §6.
- **Lift** — `PPV / base_rate`. 1.0× = the alert carries no information over random selection;
  higher is better; ceiling = `1/base_rate`. The honest headline number, not "alerts per event"
  (which is just `1/PPV` with no reference point).
- **C-index** — Harrell's concordance, the survival-analysis analogue of AUC across all
  follow-up time, not just one horizon.

**Split (patient-level, no leakage):** train 206,141 anchors / 5,501 stays; calib 46,771 /
1,180 stays; test 45,767 / 1,179 stays.

**Calibration is genuinely good:** Expected Calibration Error 0.0087 raw → 0.0079 calibrated
(near-zero is excellent; this means predicted probabilities can be trusted at face value).
Brier score rises with horizon as expected (2h: 0.020 → 24h: 0.141 — predicting further out is
intrinsically harder, this is not a flaw).

---

## 5. The 51.5% coverage-gap fix — exact numbers, exact residual (from `stage0_verification_news2.json`)

**The problem:** `build_anchors()` originally required a full 6-hour vitals look-back before
generating any anchor. Median time from CCU admission to deterioration is ~6.7h; a quarter of
deteriorators cross the threshold within 1.4h — so the fastest-declining, most acute patients
were **structurally invisible** to the model (2,794 of 5,424 true deteriorators, 51.5%,
contributed zero training anchors).

**The fix:** replaced the fixed 6h gate with the existing `MIN_VITALS_IN_WINDOW` (≥2 readings)
check applied to *however much* look-back has actually elapsed, capped at 6h as a maximum, not
a requirement. Added `hours_of_history` as a feature so the model can itself discount
short-history predictions.

**Result, exactly as measured:**
| | |
|---|---|
| True deteriorators, originally zero anchors | 2,794 (51.5%) |
| **Recovered by the fix** | **1,278 (45.7% of the previously-invisible group)** |
| **Residual — still zero anchors** | **1,516 (54.3%)** |
| Of the residual, deteriorate within 2h of admission | **90.4%** |
| Median onset time for the residual group | **0.27h (16 minutes)** |

**The honest, important conclusion — say this exactly if asked why the residual exists:** the
fix worked precisely as designed. What it reveals is that the true floor was never really "6
hours" — it's the **charting frequency itself**. You cannot obtain 2 vital readings before an
event that happens in under an hour on an hourly-ish charting cadence. No further pipeline
tuning closes this; it would require higher-frequency (continuous) monitoring data, which
standard MIMIC-IV chartevents don't provide at that resolution. **This is a sharper, truer
version of the original concern than either "you're right" or "you're wrong" — say it this way
if the professor raises it again.**

---

## 6. What actually reduced false positives, and what didn't — be honest about both

**What worked, dramatically — alarm-episode deduplication.** Every patient-hour was originally
counted as an independent alarm, which inflates apparent false-alarm burden far beyond what a
bedside clinician would experience (a patient trending up for 5 consecutive hours = 5 counted
"false alarms" for one real clinical event). Deduplicating consecutive alerting hours into
single episodes:

| Horizon | Anchor-based alarm rate (patient-hour⁻¹) | Episode-based alarm rate | Reduction |
|---|---|---|---|
| 12h | 0.395 | **0.061** | **~6.4×** |

Patients caught (alerted at least once) barely changes under episode counting, and the mean
number of distinct alarm episodes per correctly-caught patient at 12h is only 1.83 — i.e. most
correctly-flagged patients trigger fewer than 2 real-world alarms, not the dozens implied by
raw anchor counting. **This was the single highest-value, cheapest fix identified across the
whole project, and the numbers confirm it.**

**What did NOT meaningfully help — feature richness (labs).** Adding the labs/congestion axis
(lactate, troponin, creatinine/eGFR, potassium, weight trend, urine rate, rhythm flags) changed
AUC from 0.8099→0.8096, AUPRC 0.362→0.365, lift 2.03×→2.04× — essentially no change. This was
a genuinely useful, somewhat surprising negative result: it argues the ceiling here is **not**
primarily a feature-richness problem for these specific labs.

**What did NOT meaningfully help — the AFT-to-discrete-time-hazard framing switch itself.**
AUC 0.808 (AFT) vs 0.810 (hazard); C-index 0.789 vs 0.791; lift 1.95× vs 2.03× — a small,
real improvement, not a large one. **This is important and should not be oversold**: the
framing switch fixed real things (native calibration, no fake-median pathology, clean answers
to "what does the model output," monotonicity by construction) but did **not** meaningfully
move discrimination or PPV, because AFT and discrete-time hazard are both extracting
approximately the same signal from the same NEWS2-only features. **The implication, stated
honestly: whatever caps this model's discrimination/false-positive rate is very likely the
label/feature information ceiling, not the model family** — confirmed empirically by two
independent negative results (framing didn't move it much, labs didn't move it much either).

**Unresolved, worth surfacing if asked "what would actually move this further":**
- **Time correlation remains genuinely weak** even after all fixes: corrected/conditional
  scatter Pearson r = **0.250**, Spearman r = **0.265** (up from the raw naive-AFT scatter's
  0.153/0.235, but still weak in absolute terms). The honest explanation: comparing a single
  point-time prediction against a single realized event time is an inherently high-noise
  statistical comparison — even a well-specified model has a low ceiling here if genuine
  physiological timing variability (measurement noise, intervention timing, spontaneous
  fluctuation) is a large share of the total variance in exact time-to-event. **Rank-based and
  probability-based metrics (C-index 0.79, AUC 0.81, near-zero ECE) are the fair test of
  whether the model captured real signal — they are good.** The point-time Pearson r was
  probably never going to be strong, regardless of model family, and should be presented that
  way rather than as a discrete-time-hazard shortcoming.
- **A genuinely different, not-yet-built alternative worth naming if pressed further**: the
  professor's own phrasing — "future NEWS score is just that... it's just another albeit
  composite vital" — could be read as suggesting a more direct **regression of the future NEWS2
  value itself** (or its ordinal band) at fixed horizons, evaluated on every patient uniformly
  (no censoring machinery needed at all, since every patient has a real NEWS2 value at +6h
  whether or not they ever cross 7), rather than a threshold-crossing/time-to-event framing.
  This might reduce label-construction noise (a binary "sustained ≥7 for 2h" event superimposed
  on a continuous, gradually-evolving score discards information at the discretization boundary)
  and could show a stronger point-alignment because it isn't conditioned on "T≤24h" at all. Not
  built — flagged as the deepest open direction, not a same-day fix.

---

## 7. Design decisions made and their rationale (so "why did you choose X" is answered correctly)

- **Conditional-hazard over cumulative-form ordinal regression**: monotonicity is automatic
  (`S` is a running product of terms ≤1) rather than needing a post-hoc `cumulative-max` patch.
  Matches the discrete-time model used as the TTE comparator in the strongest published
  head-to-head (Prioritising deteriorating patients using time-to-event analysis, Critical Care
  2024, PMC11256441).
- **XGBoost over MLP as base learner**: lower risk, no new dependency, native SHAP, already
  proven in this codebase. MLP (shared-trunk, CORAL-style, architecturally-guaranteed
  monotonicity) remains a documented next-step benchmark, not built.
- **Vanilla/classical ordinal regression (proportional-odds, Frank & Hall, CORAL) rejected**:
  they require every observation to have a fully-known category; applied properly here it would
  mean dropping ~22–40% of anchors (the `dropped_unknown_pct` at each horizon) rather than
  masking them — directly contradicting the professor's explicit priority ("incorporate normal
  data rather than discarding").
- **NEWS2≥7 label, not escalation or death, kept as the target**: an earlier research pass
  argued this was "target leakage" (predicting a function of the same 7 vitals used as
  features). The professor explicitly rejected this framing: predicting a *future* value of a
  composite vital is not leakage, "it's just another albeit composite vital" to forecast. This
  is accepted and settled — do not re-raise "fix the label to escalation" as if it's still open;
  that specific idea is superseded. The unresolved deeper question is the discretization/
  construct-validity point in §6, which is different from leakage.
- **Cox not yet run**: the professor's own stated prior experience is that it underperforms
  here; given AFT and discrete-time hazard (two structurally different frameworks) landed
  within 0.002 AUC of each other, Cox is predicted to land in the same range too — a cheap
  confirmatory run, not expected to change the conclusion.

---

## 8. Honest deployment-readiness assessment (state plainly if ever asked "is this ready for real patients")

**No — and this should never be implied otherwise.** Reasons: zero external validation (single
hospital, single unit type, one era, 2008–2019 — TRIPOD/PROBAST would classify this as
development-only); the 54.3% residual coverage gap for the fastest-declining patients (§5); no
prospective/shadow-mode testing; no defined clinical override protocol; no human-factors
testing; no regulatory review. This is strong, defensible **research-iteration** work, not a
clinical-deployment-ready system. If asked to help present this, present it as exactly that.

---

## 9. Exact mechanics, verified against the source code (`10_focused_report.py`) — not inferred

**How training data is built for each interval (the "ordinal"/discrete-time-hazard mechanic).**
Chart `00_ordinal_concept_diagram.png` illustrates this precisely with three patients — use
this exact framing if asked "how does this actually work," since it's what appears on the slide:
- **Patient A, deteriorates at 5h** (cutpoints `2,4,6,9,12,18,24`): contributes `label=0` to
  interval 1 (0–2h, survived) and interval 2 (2–4h, survived), then `label=1` to interval 3
  (4–6h, failed inside it) — **and that is their last row.** No rows contributed to intervals
  4–7; once a patient fails, there is nothing further to predict from that anchor.
- **Patient B, discharged/censored at 10h**: contributes `label=0` to intervals 1–4 (survived
  each outright). Their censoring time (10h) falls **partway through** interval 5 (9–12h) — the
  outcome for that interval is unknowable (would they have failed between hour 10 and 12? we
  don't know, they left). That row is **masked** (excluded), and B contributes nothing to
  intervals 6–7 either. This masking-not-deleting is exactly the mechanism in Prof. Shroff's
  paper (arXiv:1903.09795), applied per-interval.
- **Patient C, stable to 24h**: contributes `label=0` to **all seven** intervals — this is how
  stable patients are used as real training signal, repeatedly, not excluded.

Each interval trains one independent XGBoost binary classifier on whoever validly contributes
a row to it, predicting `P(fail in this interval | at risk at its start)`. Each is isotonic-
calibrated separately. `S(c_j) = S(c_{j-1}) × (1 − calibrated_hazard_j)` — a running product,
so the survival curve can only decrease; monotonicity is automatic, not enforced.

**How the false-positive/threshold numbers are actually computed (`_confusion_at`,
`10_focused_report.py:153`).** The alert threshold at a given horizon is set to the quantile of
the **true events'** own predicted-score distribution that puts exactly the target fraction
(default 80%) of them above it: `threshold = quantile(score[event==1], 1 − target_sensitivity)`.
**Important, easy-to-misstate nuance: this makes "80% sensitivity" a chosen operating point,
true almost by construction on this test set — not independent evidence of anything.** The
genuine, non-circular result is what happens to **PPV, specificity, lift, and alerts-per-event
at that fixed point** — none of those are constrained to any target value, and they are the
real evidence of model quality. State it this way if asked "is 80% sensitivity a real result."

**How alarm-episode deduplication works (`alarm_episode_metrics`,
`10_focused_report.py:332`).** Per anchor-hour: `alert = calibrated_probability ≥ threshold`
(the same threshold as above). Sort by patient and time; `episode_start = alert AND NOT
(this same patient's previous hour also alerted)` — a rising-edge detector collapsing
consecutive alerting hours into one episode. This produced the ~6.4× alarm-rate reduction
(§6). **Honest limitation to volunteer, not wait to be caught on**: this is a *simple*
consecutive-run collapse, not a smoothed hysteresis with a grace period — if a patient's
calibrated risk dips below threshold for even one hour between two alerting runs, that
currently counts as **two** separate episodes, not one continuous one. A short grace-period
extension would very likely reduce the episode count further; not yet built. Two genuinely
different statistics are reported and must not be compared to each other: (a) alarms per
patient-hour, anchor-level vs. episode-level — same denominator both sides, episode-rate ≤
anchor-rate is asserted in code as a correctness check; (b) mean episodes per successfully-
caught patient — a different, patient-level denominator, not comparable to the row-level
"alerts per event" figure.

**How calibration is measured precisely.** ECE = mean absolute (observed − predicted)
frequency across probability deciles (`pd.qcut`, 10 bins) — a single-number summary of the
reliability plot. Calibration slope/intercept come from a logistic regression of the true
outcome on `logit(calibrated probability)` — slope=1/intercept=0 is perfect; slope<1 signals
overconfidence at the extremes.

---

## 10. Comprehensive anticipated-question reference (answer from this, don't improvise)

**Mechanics / model family**
- *What does the model predict — time, probability, or a curve?* A discrete survival curve
  (7 calibrated probabilities, one per horizon). Primary output = the probability; secondary =
  a derived conditional time estimate. See §4 and §9.
- *Is the output a continuous CDF?* No — discrete, sampled at 7 fixed cutpoints, by design.
- *How does monotonicity work — is it enforced?* No, automatic: a running product of terms ≤1
  can only decrease. See §9.
- *Is this really "ordinal regression"? How does it relate to the paper you were sent?* Yes —
  the conditional-hazard form. His paper's censoring mechanism (mask unknown post-censoring
  sub-problems) is the same idea as this model's per-interval masking; this parameterization
  was chosen over his paper's literal cumulative form because monotonicity then requires no
  post-hoc patch. See §7.
- *Why XGBoost, not the MLP you suggested?* Lower risk, no new dependency, native SHAP, already
  proven in this codebase for a first pass. MLP (shared-trunk, CORAL-style) is a documented,
  not-yet-built next-step benchmark. See §7.
- *Did you try Cox?* Not yet run. You said your own experience is that it underperforms here;
  given AFT and the hazard model (two structurally different frameworks) landed within 0.002
  AUC of each other, Cox is predicted to land in the same range too — cheap to add as a
  confirmatory benchmark, not expected to change the conclusion.
- *What features does it use? Did richer features (labs) help?* 54 NEWS2-only columns (§4's
  meta list) by default. A labs-augmented variant was also trained (`13_/14_..._labs.py`) —
  AUC/AUPRC/lift **barely moved** (hazard: 0.8099→0.8096 AUC, C-index 0.791→0.789 — a very
  slight, likely noise-level regression, not an improvement). Report this honestly: these
  specific labs did not meaningfully help.

**Label / event definition**
- *Isn't predicting NEWS2 from NEWS2 circular?* No — you clarified this yourself: forecasting a
  *future* value of a composite vital from current state is legitimate, not leakage (leakage
  would require using the future value as an input feature, which never happens here). The
  model is still required to beat a trivial NEWS2-slope-extrapolation baseline to prove it adds
  real value, and it does by a wide margin (ruler AUC 0.545 vs. model 0.810).
- *Why NEWS2≥7 sustained 2h specifically?* Standard urgent-clinical-response trigger threshold
  in NEWS2 protocols, not an arbitrary choice.
- *Could the label definition itself be adding noise?* Yes, a real, disclosed, unresolved
  concern — a hand-crafted composite score's threshold-crossing is coarser than the underlying
  continuous physiology, and may be part of why point-time correlation is capped regardless of
  model. An alternative not yet built: direct regression of the future NEWS2 value/band at each
  horizon rather than time-to-threshold-crossing. See §6's last bullet.
- *Why not escalation or death as the label?* You said predicting death isn't clinically useful
  and deterioration is more useful; the label choice is a domain decision, and NEWS2≥7 was kept
  per your explicit direction.
- *How is death handled?* Cause-specific right-censoring — a competing risk, not the event.

**The coverage-gap fix**
- *What was wrong originally?* A hard 6h vitals look-back requirement made the 51.5% fastest-
  declining true deteriorators contribute zero training anchors. See §5.
- *What did you actually do, and did it work?* Graceful-degradation eligibility (≥2 readings in
  whatever history is available, capped not required at 6h). Recovered 1,278 of 2,794 (45.7%).
- *Why is there still a residual — did the fix fail?* No — it worked exactly as designed. The
  residual 1,516 (54.3%) deteriorate this fast because 90.4% of them cross the threshold within
  2 hours of admission (median 16 minutes) — the true floor is vitals-charting frequency, not
  the look-back window. Closing it further needs continuous/high-frequency monitoring data.
- *Was the comparison to AFT fair after this pipeline change?* Yes — AFT was retrained on the
  identical Stage-0-regenerated data, not compared against a stale pre-fix version.

**False positives**
- *What is your false-positive rate, precisely?* See the horizon_utility table in §4 — PPV
  0.234 at 12h, 0.372 at 24h, lift 2.03×/1.66×. Always give PPV and lift together with the
  horizon, never a bare "false positive rate."
- *Is that rate acceptable — compared to what?* Inside/above the published deployed-system band
  (eCARTv2 PPV 0.082, Epic DI 0.338, eCART risk-spikes 0.07–0.35) — **with the caveat that our
  label (NEWS2≥7) is a same-signal target, not an independent clinical outcome like those
  systems' ICU-transfer/death**, so this is a favorable but not perfectly apples-to-apples
  comparison. State the caveat every time this number is used.
- *What did you actually do to reduce false positives, and what worked?* Alarm-episode
  deduplication (~6.4× real-world alarm-rate reduction — the single biggest lever, see §9).
  Labs did not help (above). The AFT→hazard framing switch barely helped (§6) — direct evidence
  the bottleneck is feature/label information content, not model family.
- *What would reduce it further?* A grace-period extension to the episode logic (§9); richer or
  different features than the labs already tried; narrower/subgroup-specific thresholds; or
  accepting a lower sensitivity operating point — the last is a clinical risk-tolerance decision
  for you and Harshika, not a purely technical one.

**Time-correlation**
- *Why is Pearson r still only ~0.25?* Point-time prediction vs. a single realized event time
  is an inherently high-noise comparison, even for a well-specified model, if real physiological
  timing variability (measurement timing, intervention timing, spontaneous fluctuation) is a
  large share of the total variance in exact time-to-event. Rank-based (C-index 0.79) and
  probability-based (AUC 0.81, ECE≈0.008) metrics are the fair test of real signal, and those
  are good. Lead with those, not the point-time correlation.
- *Did the new model improve this at all?* Yes, modestly: r=0.153 (naive AFT) → r=0.250
  (hazard model's corrected estimate) — real, not dramatic, and not expected to become "strong"
  given the argument above.
- *Are we comparing the wrong parameter by using raw time?* Plausibly yes for judging model
  quality — it's a much harder, noisier statistic than rank or probability agreement.

**Validation / deployment**
- *Is this ready for real patients?* No. Single-hospital, one era, no external validation, the
  54.3% residual coverage gap, no prospective testing, no override protocol, no regulatory
  review. Research-iteration work — say so plainly if asked.
- *How would you validate this properly?* External validation (e.g. eICU-CRD; comparable
  cross-database work reports <4% AUC degradation for a similar task), prospective shadow-mode
  testing, TRIPOD+AI/PROBAST-guided reporting.

**Statistical rigor**
- *How do you know it's not overfit?* Train/test C-index gap ~0.01–0.02; patient-level
  (`subject_id`) split with no patient crossing splits; patient-clustered bootstrap 95% CIs on
  every headline metric.
- *N=256,000+ rows sounds huge — is the sample really that big?* No — always pair the row count
  with the patient count: ~7,860 independent CCU stays total (train 5,501 + calib 1,180 + test
  1,179). Repeated hourly rows from one patient are correlated, not independent evidence; this
  is exactly why splits and CIs are done by `subject_id`, not by row.
