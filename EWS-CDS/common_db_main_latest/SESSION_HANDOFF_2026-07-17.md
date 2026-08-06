# Session Handoff — EWS Deterioration Model (Survival → Focused NEWS2 Model)

**Purpose of this file:** a complete, self-contained summary of everything built
in this session, so a fresh chat (with no memory of this conversation) can pick
up exactly where it left off. Written 2026-07-17.

---

## 0. The project, one paragraph

Foqal CareOS is an integrated hospital product: Ashmit owns discharge-summary/
billing AI, Sabari (the user) owns the Ward Monitor / Early Warning System
(EWS) — a NEWS2-based deterioration alert system for a cardiology ward/CCU,
now being extended with a real ML model trained on MIMIC-IV. All ML work this
session lives under `E:\IP_EarlyWarning\EWS-CDS\common_db_main_latest\ml\`.

**Environment essentials (don't rediscover these):**
- Use `py -3` for Python, NOT `python` (that resolves to an ancient Python 2.7
  shim via Git Bash on this machine).
- Set `$env:PYTHONUTF8=1` in PowerShell before running scripts (console is
  cp1252 and chokes on unicode in some print statements).
- BigQuery: active gcloud account is `sabari24486@iiitd.ac.in` (PhysioNet-
  credentialed). **Bill to `avid-stone-497321-r3`** (has Storage-API
  readsessions permission; the shared `healthcare-project-496207` project does
  not). All extraction is already done — no need to re-pull from BigQuery.
- `config.py` registers `db_dtypes` at import time so parquet files written by
  BigQuery downloads (DATE columns as `dbdate`) can be read back. If you ever
  read a `data/*.parquet` file directly without importing `config` first, add
  `import db_dtypes` yourself or the read will throw `TypeError: data type
  'dbdate' not understood`.
- **`EWS_TAG` env var** controls output file tagging via `config.tpath(name)`.
  Set `$env:EWS_TAG="news2"` before running any of the pipeline scripts to work
  with the focused-model artifacts (e.g. `anchors_news2.parquet`,
  `features_news2.parquet`, `preds_focused_news2.parquet`). Unset/empty tag
  falls back to the older composite-model files (`anchors.parquet`, etc.) —
  those still exist on disk but are superseded by the news2 versions.

**Standing rule added to `~/.claude/CLAUDE.md` this session (global, applies to
every future project too):** never hand over a metric/chart/number without
first defining it, showing how it's computed, and explaining how to interpret
it. This was added after the user got publicly embarrassed presenting an
AI-generated stats report they couldn't defend (see §5 for the incident and
what it produced).

---

## 1. The ML formulation journey (chronological)

1. **Original plan** (`ml_plan.md`, pre-dates this session): binary classification,
   fixed 6h horizon. Never trained.
2. **Pivot to survival analysis** (this session, early): reframed as
   time-to-event using XGBoost AFT, per the professor's (Gautam's) direction.
   Built a **composite event** = earliest of {treatment escalation (vasopressor/
   vent/RRT), sustained NEWS2≥7, death-as-competing-risk}, two-axis features
   (NEWS2 acute + DCM congestion/substrate axis: weight, NT-proBNP, eGFR,
   rhythm, Charlson), CCU-only cohort. Result: C-index 0.75 overall / 0.80 DCM,
   beat a NEWS2-slope baseline. Built a full report + walkthrough artifact.
3. **Meeting feedback (harsh)**: presented this to the professor and got
   criticized for (a) not understanding metrics well enough to defend them
   (esp. "4.17 alerts/event"), (b) presenting a multi-model comparison before a
   base model was validated, (c) no plot showing what the model actually
   predicts (he wanted actual-vs-predicted-time scatter + calibration analysis
   at an actionable horizon).
4. **Diagnostic response**: built `08_diagnostics.py` on the *composite* model
   — scatter plots, horizon-based utility metrics, reliability deciles. Found
   the raw AFT median is not a usable countdown (Pearson r≈0.12) but the model's
   *risk ranking* is strong (AUC≈0.78, 30x gradient across risk deciles).
5. **Full pivot to the FOCUSED single-event model** (per further professor
   feedback: "start with ONE focused event, e.g. time to NEWS2>7, before adding
   complexity"): this is the CURRENT model. See §2.

---

## 2. The current model (what actually exists and runs)

**Event**: ONE event only — first time NEWS2 sustains ≥7 for 2 consecutive
hourly readings. Everything else (escalation, death, discharge, 24h horizon
cap) is plain right-censoring, not a competing event.

**Features**: ONLY the 7 NEWS2 clinical parameters (HR, RR, SpO2, SBP, DBP,
temperature, consciousness) + rolling-window trends (last/mean/std/min/max/
rate/delta-from-admission) + NEWS2 score dynamics (value/mean/max/rate/hours-
in-band) + minimal context (age, sex, hours-since-admission). 54 columns total.
**No labs, no weight, no biomarkers, no DCM axis** — deliberately narrow, to
prove a clean base model works before adding complexity.

**Model**: one XGBoost `survival:aft`, distribution chosen by validation
log-likelihood (logistic won: nloglik 0.682 vs normal 0.717 vs extreme 0.683).
Plus a trivial **NEWS2-slope-extrapolation ruler** as the mandatory floor
baseline (since the event is NEWS2-defined and features are NEWS2-only, the
model MUST beat naive linear extrapolation of the score itself, or it proves
nothing).

**Cohort**: MIMIC-IV v3.1, CCU (Coronary Care Unit) stays only — 10,775 stays,
mean age 67.7, 57.8% M / 42.2% F. 5,424 (50.3%) reach the event at some point;
the rest never do (genuine negative population, not events-only).

**Split**: patient-level 70/15/15 → 180,762 train / 38,673 calib / 37,277 test
anchors (hourly patient-observations). No patient in two splits.

### Key measured results (test set)
- **C-index: 0.782** (train 0.815, gap 0.034 — small, not overfitting) vs the
  NEWS2-slope ruler's **0.540** (barely above random 0.5).
- **AUC for "deteriorates within 12h": 0.802**. At 6h: 0.821. At 24h: 0.778.
- At an 80%-sensitivity operating point: alerts-per-true-event = **8.2 / 4.5 /
  2.8** at 6h/12h/24h horizons respectively (AFT), vs the ruler's **17.6 / 8.8 /
  4.4** — the AFT roughly **halves** the false-alarm rate at every horizon.
- **Important finding**: the ruler's confusion matrix has `tn=0, fn=0` at every
  horizon — its "80%-sensitivity threshold" degenerates to alerting on
  literally everyone (its risk scores are so tie-dominated that no real
  threshold exists). Its alerts/event numbers are just `1/base_rate` — i.e. it
  adds zero information. This is the cleanest "our model actually works"
  evidence in the whole analysis.
- **Naive median is not a usable countdown** (Pearson r=0.13 vs actual time;
  ranged up to 2,872h for some patients) — a mathematically expected effect
  under our ~13% event rate (median of a survival curve with <50% event
  probability is forced beyond the horizon). Fixed by reporting, from the SAME
  fitted model: (a) `P(T≤h)` = `sigmoid((log h − log median)/σ)` for the
  logistic AFT, isotonic-calibrated on the calib split, and (b) conditional
  expected time `E[T|T≤24h]` via numerical integration — MAE 5.6h, Pearson
  r=0.21, a far more sensible corrected scatter.
- **Error-by-bin / cutoff horizon**: MAPE is 663% for 0-2h-out events (the
  conditional estimate floors around 5-9h so imminent events look terrible in
  %), drops to 10% MAPE at 9-12h (best), rises again toward 24h. Point-estimate
  time is reliable in a ~6-18h window; classification/probability signal
  (AUC) stays strong at ALL horizons including <6h.
- **Decision curve analysis** (Vickers & Elkin 2006): model beats both "alert
  everyone" and "alert no one" across the entire 1-50% threshold range.
- **SHAP**: `news2_mean` dominates (0.56, >3x next feature), then `on_oxygen`,
  `age`, `fio2_last`, `heart_rate_last`, `hours_in_band` — all clinically
  sensible, no leakage surprises.

### A serious data-composition finding (found via direct query, not estimated)
**51.5% of true deteriorators (2,794 of 5,424) contribute ZERO training
anchors** — not from any censoring rule, but because their entire recorded CCU
stay is shorter than the 6-hour minimum look-back window the pipeline requires
before generating even one feature row. Only 2,614 (48.2%) of true
deteriorators ever produce a labeled positive example. **This means the model
is trained/evaluated on a population that systematically excludes the fastest,
most acute deteriorators** — exactly the patients an early-warning system
should matter most for. This was found by direct pandas query against
`data/cohort.parquet` + `data/anchors_news2.parquet`, reproducible via the
query in §6 below. This is a genuine, serious limitation — not yet resolved,
not yet mentioned in any deck/report produced so far.

---

## 3. Files built this session (all under `common_db_main_latest/ml/` unless noted)

| File | Purpose |
|---|---|
| `config.py` | Central config. Added: `TAG`/`tpath()` (env-var-tagged output paths), `NEWS2_FEATURE_PREFIXES`, `CONTEXT_FEATURES`, `HORIZONS_H=[6,12,24]`. Also has BigQuery coords, MIMIC itemid vocab, cohort SQL constants (pre-existing). |
| `news2.py` | Standalone NEWS2 scorer — faithful copy of production `calculate_news2()` from `sabari_project/backend/main.py`, loads the same `news2_thresholds.yaml`. |
| `charlson.py` | Charlson comorbidity index (Quan 2005 ICD mapping) — used by the OLDER composite model only, not the focused model. |
| `bq.py` | BigQuery client helper + db_dtypes sanitizing. Extraction already done; shouldn't need to re-run. |
| `known_status.py` | **Critical correctness module.** Fixes a real bug: naively labeling "deteriorated by hour h" for censored patients wrongly counts those discharged before h as confirmed negatives. `known_at(df,h)`, `label_at(df,h)`, `known_subset(df,h)`, `dropped_fraction(df,h)`. Has its own inline self-test (`py -3 known_status.py`) — passes. |
| `00_extract_cohort.py` | BigQuery → local parquet (cohort, chartevents, labevents, inputevents, procedureevents, outputevents, diagnoses). Already run; data on disk. Billing project `avid-stone-497321-r3`. |
| `01_build_labels.py` | Builds hourly vitals grid + NEWS2 replay + survival labels. **Has `--event {composite,news2}` flag** — use `news2` for the current model. Has `--selftest` (3-patient hand-computed toy cohort, includes a specific test that escalation-without-NEWS2-crossing must be censored, not an event, in news2 mode). Run: `EWS_TAG=news2 py -3 01_build_labels.py --event news2`. |
| `02_build_features.py` | Two-axis windowed feature engineering (leakage-guarded — every feature strictly from `[t-6h,t]`). Reads/writes via `config.tpath`. Run: `EWS_TAG=news2 py -3 02_build_features.py`. |
| `09_focused_train.py` | **The current model's training script.** Single AFT (dist chosen by val nloglik), conformal median calibration, `P(T≤h)` + isotonic calibration per horizon, conditional expected time via numerical integration, NEWS2-slope ruler baseline, train-vs-test C-index check. Run: `EWS_TAG=news2 py -3 09_focused_train.py`. Outputs: `data/preds_focused_news2.parquet`, `data/models_news2/{aft_focused.json, calibrators.pkl, meta.json}`. |
| `10_focused_report.py` | All diagnostic plots for the focused model (12 PNGs to `data/charts_focused/`): naive scatter, corrected/conditional scatter, error-by-bin, horizon utility table, threshold sweep, calibration reliability, overfit check, SHAP global + per-patient, 3 real patient case-study trajectories, decision curve, executive scorecard. Also writes `data/metrics_focused.json` (every number, traceable). Run: `EWS_TAG=news2 py -3 10_focused_report.py`. **All 12 charts have been visually reviewed and are good** — several real bugs were caught and fixed during review (jitter added for hourly-grid overplotting; case-study outcome-time computation was wrong for censored/long-stay patients because T_hours is horizon-capped per-anchor, not the true discharge time — fixed by using the full vitals_hourly span). |
| `11_build_deck.py` | PPTX deck builder — reads `metrics_focused.json` + charts, assembles `data/report_focused.pptx` (18 slides). **STATUS: v1 exists and is structurally verified (correct slide count/dimensions, no malformed shapes) but its TEXT CONTENT IS STALE — see §4, this is the immediate next task.** |
| `08_diagnostics.py` | Diagnostics for the OLDER **composite** model (not the current focused one) — scatter/reliability/separation/horizon-metrics plots. Superseded by `10_focused_report.py` for the focused model, kept for reference. |
| `05_plots.py`, `03_train.py`, `04_evaluate.py` | Composite-model pipeline (older event definition). Still functional, not the current model. `03_train.py` is imported by `09_focused_train.py` via `importlib` for shared helpers (`three_way_split`, `make_dmatrix`, `train_aft`) since `03_train` isn't a valid Python identifier for a normal import. |
| `DIAGNOSTICS_EXPLAINED.md` | Plain-language explainer for the composite model's diagnostics (older). |
| `FOCUSED_MODEL_EXPLAINED.md` | **Plain-language explainer for the CURRENT focused model** — every number/plot defined with formula + interpretation, per the standing CLAUDE.md rule. Read this before presenting anything. |
| `ews_quantile_regression_plan.md` (repo top-level, `common_db_main_latest/`) | The original formulation write-up for the composite model. |

**Two Claude Code plugin memory files also updated this session:**
- `~/.claude/CLAUDE.md` (global) — the "explain before handoff" standing rule.
- `~/.claude/projects/E--IP-EarlyWarning/memory/project_ews_survival_model.md` — project memory entry (may need updating with the focused-model pivot; wasn't updated after the focused-model work, only after the composite-model + diagnostics work).

---



## 5. A separate, not-yet-fully-resolved thread: critical evaluation + research prompt

Just before this handoff was requested, the user asked a substantial, separate
question: **critically evaluate from scratch whether time-to-event/AFT survival
modeling is even the right approach** for this use case, compare against
classification and other regression framings, research industry/academic
standards, and be brutally honest — not accept the current approach just
because it's what's been built. They asked for (1) a very detailed research
prompt they can hand to a dedicated research session, and (2) direct answers to
their questions about dataset composition, false-positive calculation, and
metrics — answered directly, not deferred.

**This was fully drafted** (grounded in live queries against the real local
data — see the exact query in §6 below for the 51.5%-exclusion finding) and
written to the ephemeral plan file
(`C:\Users\sabari krishna\.claude\plans\foqal-summer-projects-imperative-canyon.md`)
as three parts:
- **Part A**: direct, data-grounded answers (dataset diversity — real
  age/gender numbers pulled by query; how false positives/alerts-per-event are
  computed — anchor-level not patient-level, known-status filtering, 80%
  sensitivity operating point; what isotonic calibration and per-patient SHAP
  mean).
- **Part B**: an honest critical evaluation arguing (a) the raw AFT median is
  provably uninterpretable under our event rate, (b) the calibrated `P(T≤h)`
  workaround we actually use clinically is functionally a classifier output,
  meaning the survival-model machinery may be more overhead than benefit for
  this specific deployment need, (c) real deployed systems (eCART, Epic
  Deterioration Index, Rothman Index) are classification-based, not survival-
  based, which is a signal worth weighing, (d) quantile regression on raw time
  (the original pre-AFT approach) is a worse alternative, not a fallback,
  because it can't use censored patients at all.
- **Part C**: a long, fully self-contained, copy-pasteable research prompt
  (includes all the numbers above) for a dedicated research session — asks it
  to survey NEWS2/MEWS/qSOFA/APACHE/Rothman/eCART/Epic Deterioration Index,
  academic MIMIC/eICU literature (classification vs. survival vs. discrete-time
  hazard models), PhysioNet Challenge results, assess whether our false-positive
  rate is normal for this problem class, assess dataset adequacy against
  TRIPOD/PROBAST guidelines, and deliver an unhedged verdict.

**A separate list of ~11 genuine ML questions to ask the professor** was also
drafted (covering: framing choice, alarm hysteresis/false-positive reduction,
the 80%-sensitivity threshold choice, the 51.5%-exclusion data problem, class-
imbalance/censoring best practices beyond what's done, competing-risks methods
(Fine-Gray vs. cause-specific), TRIPOD/PROBAST validation bar, hyperparameter
tuning strategy for survival objectives). This was given directly in chat, not
saved to any file — **reproduce this list if picked up in a new chat**, since
it exists only in this conversation's history, not on disk.

**IMPORTANT**: the plan-mode ExitPlanMode call for the critical-evaluation
deliverable was REJECTED by the user (they exited plan mode via `/model`
switching instead of approving), and then asked for this handoff instead. So
**the Part A/B/C research-prompt content currently only exists in the
ephemeral plan file** — it has NOT been saved anywhere durable yet. If the plan
file gets overwritten by a future planning session, that content is lost
unless it's been copied elsewhere. **Recommend saving it to a proper file
(e.g. `common_db_main_latest/ml/RESEARCH_PROMPT_survival_vs_classification.md`)
in the next session if the user still wants it preserved.**

---

## 6. Reproducible queries (for verifying numbers / re-deriving if files change)

The 51.5%-exclusion finding was produced by this exact query (read-only, run
from `common_db_main_latest/ml/`):

```python
import db_dtypes
import pandas as pd
cohort = pd.read_parquet('data/cohort.parquet')
anchors = pd.read_parquet('data/anchors_news2.parquet')

import importlib.util, sys
spec = importlib.util.spec_from_file_location('labels', '01_build_labels.py')
labels = importlib.util.module_from_spec(spec)
sys.modules['labels'] = labels
spec.loader.exec_module(labels)

hv = pd.read_parquet('data/vitals_hourly_news2.parquet')
chart = pd.read_parquet('data/chartevents.parquet')
inp = pd.read_parquet('data/inputevents.parquet')
proc = pd.read_parquet('data/procedureevents.parquet')
ev = labels.compute_stay_events(cohort, inp, proc, hv, event_mode='news2')
true_det = ev.dropna(subset=['deterioration_time'])   # 5424 rows

has_anchor = set(anchors.stay_id.unique())
has_event_anchor = set(anchors.loc[anchors.event == 1, 'stay_id'].unique())
no_anchor_at_all = true_det[~true_det.stay_id.isin(has_anchor)]              # 2794
# has_anchor_no_event_label = crossing before intime+6h specifically          # 16
# true_det.stay_id.isin(has_event_anchor).sum()                              # 2614
```

---

## 7. Suggested first message in the new chat

> "Continuing from `SESSION_HANDOFF_2026-07-17.md` in `common_db_main_latest/`.
>  §4 / save the
> research prompt from §5 to a durable file / whatever the priority is at that
> point]."
