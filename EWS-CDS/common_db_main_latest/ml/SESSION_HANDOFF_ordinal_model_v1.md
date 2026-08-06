# Session Handoff — Discrete-Time Hazard Deterioration Model (v1)

Working directory for everything below: `E:\IP_EarlyWarning\EWS-CDS\common_db_main_latest\ml\`

Read this file first in a new session instead of re-deriving any of it. It covers
everything built, verified, and discussed in the prior session **except** the
PowerPoint deck (`15_present_deck.py`, `data/presentation_deck.pptx`) — that
part is intentionally omitted here.

## 0. Environment (don't rediscover)

- Use `py -3`, never `python`.
- PowerShell: set `$env:PYTHONUTF8=1` before running any script. Bash tool: `PYTHONUTF8=1`.
- Every script needs `EWS_TAG=news2` set — tags all `config.tpath()` reads/writes
  to this run's artifacts (e.g. `anchors_news2.parquet`, `preds_ordinal_news2.parquet`).
- Always `import config` before reading any parquet file directly in a scratch
  script — it registers a BigQuery `db_dtypes` extension type parquet needs.
- No BigQuery re-pull needed. All data already exists as parquet in `data/`.

## 1. What This Session Was For

Executed the approved plan at
`C:\Users\sabari krishna\.claude\plans\common-db-main-latest-session-handoff-20-melodic-abelson.md`:
fix a data-construction gap (§0b), retrain the AFT baseline on the fix, build a
new **discrete-time hazard survival model** (the plan's primary deliverable),
and rebuild the reporting pipeline around it. Then, at the user's request, did
an honest post-hoc critique of the results and built two additive improvements
(alarm-episode deduplication, external benchmark context) plus one experiment
(labs/congestion feature retrain — came back a null result).

## 2. Critical Historical Context — Do Not Re-litigate

- **The event label is LOCKED as "sustained NEWS2≥7 for 2 consecutive hours."**
  A prior session (2026-07-21) proposed changing it to treatment
  escalation/death, calling the current setup "target leakage." **Prof. Gautam
  Shroff (project supervisor) explicitly rejected this on 2026-07-22/23**:
  "predicting a future NEWS2 value is not leakage — it's just another albeit
  composite vital," and predicting death isn't clinically actionable enough.
  Escalation-as-label is deferred to a *future general-ward* model (where
  escalation = ICU transfer is the natural event; inside a CCU, patients are
  already ICU-level, so "escalation" doesn't mean the same thing).
- **Independent re-analysis this session mostly agrees with that rejection**,
  for a sharper reason than his: escalation-as-label has its own worse problem
  (confounded by clinician practice variation — who starts pressors when), and
  cross-system PPV evidence (below) shows independent-outcome systems don't
  actually have better false-positive rates, undercutting the "leakage causes
  the FP rate" theory. **Do not re-propose changing the label** unless new
  evidence specifically overturns this.
- Model-family direction is **confirmed, not open for re-litigation**:
  primary = discrete-time/ordinal survival (this IS Prof. Shroff's own
  suggested paper, arXiv:1903.09795 — masking censored patients per-interval).
  Cox = benchmark only, expected to underperform, not built this round.
- Relevant memory files (auto-loaded in Claude Code sessions under this
  project): `project_ews_label_circularity.md`, `project_ews_survival_model.md`.
- Background docs in this directory: `RESEARCH_FINDINGS_deterioration_model_2026-07-20.md`,
  `FALSE_POSITIVE_COMPARISON_and_professor_reply.md` (source of the external
  benchmark numbers below — eCARTv2, Epic DI, Hyland et al.).

## 3. Stage 0 — The Pipeline Fix (§0b)

**Problem found:** `build_anchors()` in `01_build_labels.py` required a full 6h
look-back before generating any anchor row. Median time-to-deterioration in
this CCU population is 6.7h; 25th percentile is 1.4h — the population
deteriorates faster than the feature window assumed, leaving 2,794/5,424
(51.5%) of true deteriorators with **zero usable anchors**.

**Fix applied:**
- `01_build_labels.py::build_anchors()` (~line 213) — removed the
  `if t < intime + W: continue` gate entirely. The existing
  `MIN_VITALS_IN_WINDOW` check (already present, needs ≥2 readings in the
  window) is sufficient on its own — the vitals grid already starts at
  `intime`, so it naturally caps the window without a separate gate.
- `02_build_features.py::acute_features()` — the `*_rate` and `news2_rate`
  features used a fixed `shift(W-1)` that returned NaN for any anchor with
  <5h of history. Replaced with `_rate_over_available_window()`, a rolling
  `.apply()` that computes rate over whatever history is actually available
  (min 2 points). Added new feature `hours_of_history` (hours since admission,
  capped at `LOOKBACK_H`=6) to `CONTEXT_FEATURES` in `config.py`.
- Leakage-guard assertion in `02_build_features.py` relaxed from
  `hours_since_adm >= LOOKBACK_H` to `>= 0` (anchor just can't be before
  admission; no longer requires a full 6h).
- `config.py::HORIZONS_H` changed from `[6, 12, 24]` to the plan's 7-cutpoint
  grid `[2, 4, 6, 9, 12, 18, 24]`.

**New durable verification script:** `verify_stage0_fix.py` (re-runnable, not
a one-off) — writes `data/stage0_verification_news2.json`. **Key finding,
larger than the plan expected:**

| | Value |
|---|---|
| True NEWS2-only deteriorators | 5,424 |
| Zero-anchor under OLD gate | 2,794 (51.5%) |
| **Recovered by the fix** | **1,278 (45.7% of the 2,794)** |
| **Still zero-anchor (residual)** | **1,516 (54.3% of the 2,794)** |
| Of residual, deteriorates within 2h of admission | 90.4% (median onset: 16 min) |

The residual is **structural, not a bug**: patients crashing within ~1h of
admission cannot have 2 hourly vital readings before their event, no matter
how the look-back window is defined. Report this plainly if asked — it is not
solved by this iteration.

**Rerun commands (order matters):**
```
EWS_TAG=news2 py -3 01_build_labels.py --event news2
EWS_TAG=news2 py -3 02_build_features.py
EWS_TAG=news2 py -3 verify_stage0_fix.py
```
Result: 298,679 anchor rows (was 256,712), 9,157 stays (was 7,724), 15.1%
row-level event rate (was 13.3%), 3,891 unique deteriorating stays (was 2,614).

## 4. The Models

### 4a. AFT (retrained on Stage-0-fixed data) — `09_focused_train.py`
No code change needed, just rerun on regenerated data:
```
EWS_TAG=news2 py -3 09_focused_train.py
```
Test C-index: **0.7895** (train 0.8113, gap 0.0218). Ruler floor: 0.5398.
Outputs `data/preds_focused_news2.parquet`, `data/models_news2/`.

### 4b. Discrete-time hazard model (NEW, primary deliverable) — `12_ordinal_train.py`
**Design:** conditional-hazard parameterization, XGBoost per interval (not an
LSTM — justified by ~2,600 usable positive patients, below the regime where
deep sequence models earn their complexity), isotonic-calibrated,
monotonic-by-construction survival curve.

**Cutpoints:** `config.HORIZONS_H = [2, 4, 6, 9, 12, 18, 24]` (c₀=0 implicit).

**Core new function — `build_person_period_table(df, horizons)`:** expands
each anchor into one row per interval it's validly at-risk for. Per interval j
spanning (c_{j-1}, c_j]:
- at risk iff `T_hours > c_{j-1}`
- `event=1` and `T_hours <= c_j` → label=1, patient exits (terminal row)
- `event=1` and `T_hours > c_j`, OR `event=0` and `T_hours >= c_j` → label=0, continues
- `event=0` (censored) and `c_{j-1} < T_hours < c_j` → **MASKED**: excluded
  from this interval AND every later interval (Shroff's masking idea, applied
  per-interval instead of per-cumulative-horizon)

Then: one XGBoost binary classifier per interval on its person-period subset
→ isotonic-calibrate each → reconstruct `S(c_j) = S(c_{j-1}) × (1 − hazard_j)`
(non-increasing by construction, no post-hoc patch) → `P(T≤c_j) = 1 − S(c_j)`.

**Known numerical edge case, already fixed:** `IsotonicRegression(y_min=0,
y_max=1).predict()` can return a value marginally outside [0,1] (e.g.
1.0000001) due to floating-point interpolation, which breaks the
non-increasing assertion. Fixed by `np.clip(calibrated_hazard, 0.0, 1.0)`
immediately after calibration, in both `12_ordinal_train.py` and
`14_ordinal_train_labs.py`'s `calibrated_hazard_matrix()`. If you see the
assertion `"S(c_j) is not non-increasing"` fail again, check this first.

**Rerun:**
```
EWS_TAG=news2 py -3 12_ordinal_train.py
```
Test C-index: **0.7906** [95% CI 0.7715, 0.8118] (train 0.8004, gap 0.0098).
Both AFT and hazard model clear the ruler (0.5398) by a wide margin.
Outputs `data/preds_ordinal_news2.parquet`, `data/models_ordinal_news2/`.

### 4c. Labs/congestion retrain experiment — NULL RESULT
`09_focused_train.py::focused_plus_labs_feature_cols()` adds an input-feature
axis (lactate, troponin, creatinine/eGFR, potassium, weight trend + ESC/HFSA
congestion flags, urine output rate, rhythm flags — chosen by mechanistic
plausibility for a CCU population, not "add everything"; BNP/sodium/
hemoglobin/INR/platelets included too but flagged low-confidence in code
comments given missingness/indirectness). **Compatible with the professor's
label ruling — this changes features only, not the label.**

New scripts `13_focused_train_labs.py` (AFT+labs) and
`14_ordinal_train_labs.py` (hazard+labs), mirroring 09/12 exactly.

**Result: no significant improvement.**
- AFT: 0.7900 (+labs) vs 0.7895 (NEWS2-only) — negligible.
- Hazard: 0.7889 (+labs) vs 0.7906 (NEWS2-only) — slightly *worse*, well
  within overlapping bootstrap CIs.
- Only `urine_rate_24h` / `egfr` / `lactate_delta_adm` cracked the top-15
  features by XGBoost gain in either model; the rest of the labs axis
  contributed little. Most plausible explanation: NEWS2's own vitals already
  capture most of the extractable signal at these 2-24h horizons.

This was **excluded from the presentation deck** per explicit direction ("I
don't think adding the values after adding labs makes sense") but the
scripts/models still exist if you want to reference the experiment.

## 5. The Report Script — `10_focused_report.py`

Fully rewritten this session. Primary model = hazard model
(`preds_ordinal_news2.parquet`); AFT loaded only for the comparison table and
as a labeled historical reference (its old unconditional-median pathology).
Report ordering: bucket-probability/calibration metrics first (primary),
actual-vs-predicted-TIME scatter after (secondary, explicitly caveated).

Run: `EWS_TAG=news2 py -3 10_focused_report.py` — writes 16 charts to
`data/charts_focused/*.png` (numbered in presentation order) and
`data/metrics_focused.json` (every number, traceable).

Chart list: `00_ordinal_concept_diagram`, `01_horizon_utility`,
`01b_alarm_episode_comparison`, `02_threshold_sweep`, `03_calibration`,
`04_overfit_check`, `05_decision_curve`, `06_case_studies`,
`07_table1_cohort`, `08_model_comparison`, `08b_benchmark_context`,
`09_subgroup_breakdown`, `10_scatter_corrected`, `11_error_by_bin`,
`12_scatter_naive_aft`, `13_scorecard`, `14_limitations`.

### 5a. Alarm-episode deduplication — `alarm_episode_metrics()`
**The false-positive fix.** The naive "alerts per event" metric counts every
hourly re-alert on one rising patient as a separate false positive (547 true-
event patients averaged 7.8 consecutive alerted hours before their event,
counted as 7.8 alerts each). Fix: collapse consecutive alerts per patient into
one "episode" before computing alarm rate.

**Important implementation lesson:** the first version compared "episodes /
true-event-patients-caught" directly against the old "alerted-rows /
true-positive-rows" metric and asserted episode ≤ anchor — this **failed**,
because the two metrics have different-kind denominators (patients vs. rows)
with no guaranteed ordering. Fixed by instead comparing **rates on the same
denominator** (episodes/patient-hour vs. anchor-alerts/patient-hour, both
divided by `n_known` known-status anchors) — THIS comparison is mathematically
guaranteed episode-rate ≤ anchor-rate, since an episode is a strict collapse
of a run of alerted rows.

**Result:** episode-level alarm rate is **flat at ~0.06 alarms/patient-hour
across all 7 horizons**, while the anchor-level rate roughly doubles (0.22 →
0.48) as horizon grows. 0.06/patient-hour sits right next to Hyland et al.
2020's published 0.05/patient-hour benchmark (Nature Medicine). A caught
patient personally generates ~1.8 separate alarm episodes on average before
their event, not the anchor-level count's implied 4.3.

### 5b. Benchmark context — `benchmark_context_table()`
Hardcoded, cited external figures (from `FALSE_POSITIVE_COMPARISON_and_professor_reply.md`):
eCARTv2 PPV=0.082 (ICU transfer/death, independent outcome), Epic
Deterioration Index PPV=0.338, eCART risk-spikes PPV=0.07-0.35, Hyland et al.
0.05 alarms/patient-hour. **Key point: eCARTv2 predicts an unambiguously
independent outcome and still has WORSE PPV than ours (0.082 vs our 0.22-0.35)
— evidence against "the false-positive rate proves the label is broken."**

### 5c. Model comparison table — `model_comparison_table()`
Generalized to optionally take a 4th ("+labs") column
(`te_labs=None, meta_labs=None` params) — pass both when the labs models
exist, omit for a clean 3-column comparison.

## 6. Metrics/Numbers Glossary (for defending any of this out loud)

- **C-index (concordance):** fraction of comparable patient pairs (accounting
  for censoring) the model ranks correctly by time-to-event. 0.5=chance,
  1.0=perfect.
- **AUC (ROC):** P(random true-event patient scored riskier than random
  non-event patient). Threshold-independent but inflated by large
  true-negative pools under rare events.
- **AUPRC (PR curve):** area under Precision-vs-Recall; does NOT get inflated
  by rare events — the honest discrimination metric here (base rate 11-23%
  depending on horizon).
- **PPV (precision) = TP/(TP+FP).** Depends on the alert threshold — not a
  fixed model property.
- **Lift = PPV / base_rate.** 1.0x=useless; ceiling=1/base_rate. Preferred
  headline false-positive metric over raw "alerts per event" (per prior
  research review's own explicit recommendation).
- **ECE (Expected Calibration Error):** mean |predicted−observed| across
  decile bins. Ours: raw 0.009 → calibrated 0.008 @ 12h.
- **Calibration slope/intercept:** logistic regression of outcome on
  logit(predicted prob); slope=1/intercept=0 is perfect. Ours: slope=0.96,
  intercept=0.02 @ 12h — already close to perfect even pre-calibration.
- **Known-status / dropped_unknown_pct:** `known_status.py`'s censoring-
  correct rule — a patient discharged before horizon h has UNKNOWN status at
  h, not a confirmed negative; such anchors are dropped from that horizon's
  evaluation, and the % dropped is reported alongside every horizon (11.4% at
  6h → 34.4% at 24h in the original plan text; now regenerated numbers are in
  `metrics_focused.json::horizon_utility`).
- **Actual-vs-predicted time correlation (secondary output):** Pearson
  r=0.25, Spearman=0.265. **Not a bug or wrong comparison** — the predicted
  time (`cond_time_24h`) has ~8.5x less variance (std 2.32h) than actual time
  (std 6.75h) because it's a probability-weighted average over only 7
  interval midpoints; grouped by actual-time bucket the ranking IS
  monotonically correct (9.14h→11.11h across buckets), just heavily
  compressed in magnitude. This is a structural property of the estimator,
  not a defect to "fix" without giving up the monotonic/calibrated-curve
  design.

## 7. Why The AFT-vs-Hazard Gap Is Small (0.789 vs 0.791) — Not A Bug

Both are XGBoost on the **identical 55 features and identical label** — model
architecture matters far less than feature information content once a
flexible learner is already in use. The real benefit of the hazard model
isn't raw accuracy, it's: (1) no unconditional-median pathology, (2)
monotonicity guaranteed by construction, (3) direct multi-horizon calibrated
probability output without numerical-integration hacks, (4) cleaner
per-interval censoring/masking. Say this plainly if asked why the numbers
look so similar — don't oversell it as a big accuracy win.

## 8. Data Artifacts Currently On Disk

```
data/anchors_news2.parquet, features_news2.parquet     — Stage-0-fixed (298,679 rows / 9,157 stays)
data/vitals_hourly_news2.parquet                        — hourly vitals+NEWS2 cache
data/preds_focused_news2.parquet                         — AFT predictions (all splits)
data/preds_ordinal_news2.parquet                         — hazard model predictions, PRIMARY
data/preds_focused_labs_news2.parquet                    — AFT+labs (null result)
data/preds_ordinal_labs_news2.parquet                    — hazard+labs (null result)
data/models_news2/                                       — AFT model + calibrators + meta.json
data/models_ordinal_news2/                               — hazard model (7 interval boosters) + calibrators + meta.json
data/models_news2_labs/, data/models_ordinal_labs_news2/ — labs-experiment models
data/metrics_focused.json                                — every number, traceable
data/charts_focused/*.png                                — 16 charts (00.. through 14_limitations)
data/stage0_verification_news2.json                      — durable Stage-0 fix verification
```

## 9. Deferred / Not Solved (state plainly if asked, don't imply otherwise)

- SHAP feature-importance plots (fast-follow, not attempted).
- External (multi-hospital) validation, prospective/shadow-mode testing,
  human-factors testing, a defined clinical override protocol, regulatory
  review — all prerequisites before any real-patient use, none attempted.
- The 54.3% imminent-deterioration residual (§3 above) — not solved, hard
  floor set by charting frequency.
- Full repeated-measures down-sampling of the stable class (only the
  patient-clustered bootstrap-CI mitigation was done, not the "v1-light"
  stride down-sampling the original plan flagged as optional).
- Cox baseline — not built, expected to underperform (see §7 reasoning
  extended: linear + proportional-hazards assumptions likely violated by 55+
  correlated non-linear rolling-window features).

## 10. For Next Session

Paste the professor's new feedback points here before starting, so the next
session can plan directly against them instead of re-deriving this context:

```
[ professor's feedback — paste here ]
```
