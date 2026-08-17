# EWS Survival-ML Pipeline (CCU deterioration, time-to-event)

Predicts **time until the next clinical deterioration** for CCU cardiology patients
using an **XGBoost AFT** survival model on MIMIC-IV, with quantile uncertainty
bands. See `../../..` plan and `ews_quantile_regression_plan.md` for the full
formulation and the rationale behind every design choice.

## What this is (and isn't)
- A **rigorous retrospective CCU proof-of-concept** trained on MIMIC-IV (US ICU data).
- **NOT** a deployable general-ward model — MIMIC has no ward vitals; ward ML needs
  Medanta prospective data. See the plan's "honest framing" section.

## Event definition (the survival label)
Composite deterioration = earliest of **(a)** treatment escalation
(vasopressor/inotrope start, invasive/NIV ventilation, RRT), **(b)** sustained
NEWS2 ≥ 7 over 2 consecutive hours. **Death is a competing risk** (cause-specific
censoring). Soft NEWS2 crossings are features, not events.

## Run order
```bash
# 0) one-time extract from BigQuery -> local parquet (needs gcloud ADC = IIIT acct)
py -3 00_extract_cohort.py --dry-run          # print scan-byte estimates (free)
py -3 00_extract_cohort.py                    # full CCU cohort (~26 GB scan, free tier)
py -3 00_extract_cohort.py --limit 2000       # smaller dev sample

# 1) labels (composite survival target). Self-test first:
py -3 01_build_labels.py --selftest
py -3 01_build_labels.py

# 2) two-axis features
py -3 02_build_features.py

# 3) train AFT + baselines + ablations (+ conformal calibration)
py -3 03_train.py

# 4) evaluate against the gates (+ SHAP)
py -3 04_evaluate.py
```
All stages after 00 are **fully offline** on `data/*.parquet` — no further billing.

## Modules
| file | role |
|------|------|
| `config.py` | BigQuery coords, MIMIC itemid vocab, cohort SQL constants, horizons |
| `news2.py`  | standalone NEWS2 replay (faithful copy of production `calculate_news2`) |
| `charlson.py` | Charlson comorbidity index (Quan 2005 ICD-9/10 mapping) |
| `bq.py` | BigQuery client + db_dtypes sanitising |
| `00..04_*.py` | pipeline stages (numbered; not importable — shared code lives in the modules above) |

## Pre-registered gates (stage 04)
1. **AFT-full must beat the NEWS2-slope heuristic** on C-index (else the model adds nothing).
2. **Alert burden** at 80% sensitivity (PPV / alerts-per-true-event) beats the heuristic.
3. **Interval coverage** of the 5–95% band ≈ 0.90 (conformal).
Reported overall **and** on the held-out DCM subcohort.

## Environment
Python 3.13; `pip install -r requirements.txt`. `scikit-survival` has no 3.13
wheel — IPCW metrics are implemented on lifelines instead. BigQuery access uses
the active gcloud ADC account (IIIT, PhysioNet-credentialed); jobs bill to
`BQ_BILLING_PROJECT` (default `avid-stone-497321-r3`), well within the 1 TB/mo free tier.
