# Implementation Plan: Hospital-Grade Composite Deterioration Target & Multi-Window Time-Series CDS

This plan outlines the complete restructuring of the early warning deterioration system to address false positives, eliminate self-referential NEWS2 circularity, and implement Professor Gautam Shroff's meeting recommendations (multi-window time-series dynamics, 3-way confidence abstention policy, and literature-grounded hospital-grade clinical target definitions).

---

## User Review Required

> [!IMPORTANT]
> **Key Architectural Shift:** We are moving away from predicting pure NEWS2 score threshold crossings ($\text{NEWS2} \ge 7$) to a **Hospital-Grade Intelligent Composite Target (HICT)** that combines objective circulatory collapse, respiratory failure, acute organ failure ($\Delta\text{SOFA}$), treatment escalations (pressors/ventilation), and a multi-system NEWS2 backup guardrail.

> [!NOTE]
> **Data Extraction:** Additional MIMIC-IV BigQuery tables and itemids will be pulled (e.g., Arterial Blood Gases $\text{PaO}_2/\text{FiO}_2$, Bilirubin, Platelets, Procedure Events for Mechanical Ventilation & CRRT) using `bq.py` to ensure complete coverage for SOFA organ failure tracks and treatment escalations.

---

## Proposed Changes

### Data Layer & Label Construction

#### [MODIFY] [config.py](file:///e:/IP_EarlyWarning/EWS-CDS/common_db_main_latest/ml/config.py)
* Add BigQuery itemids and extraction queries for complete SOFA score components (Bilirubin itemid `50885`, Platelets `51265`, $\text{PaO}_2$ `50821`, Arterial $\text{pH}$ `50820`, Base Excess `50802`).
* Define multi-window lookback durations: `LOOKBACK_WINDOWS = [2, 4, 6, 8, 12]`.
* Define default evaluation episode gap: `EPISODE_GAP_H = 8.0` (8-hour refractory window).
* Set composite target definition constants (Track 1: Shock Index $\ge 0.9$ + hypoperfusion; Track 2: $\text{SpO}_2/\text{FiO}_2 < 230$; Track 3: Pressors/Vent/RRT/Death; Track 4: Multi-system NEWS2 $\ge 7$).

#### [MODIFY] [01_build_labels.py](file:///e:/IP_EarlyWarning/EWS-CDS/common_db_main_latest/ml/01_build_labels.py)
* Implement `build_composite_hict_labels()` to compute the Hospital-Grade Intelligent Composite Target (HICT) across all CCU stays.
* Pull treatment escalations (Vasopressors, Ventilation, RRT) and combine with continuous bedside Shock Index ($\text{HR}/\text{SBP}$) and organ failure thresholds ($\Delta\text{SOFA} \ge 2$).
* Output `anchors_hict.parquet` with precise event onset timestamps $T_{\text{event}}$ and time-to-event $T_{\text{hours}}$.

---

### Feature Engineering Layer

#### [MODIFY] [02_build_features.py](file:///e:/IP_EarlyWarning/EWS-CDS/common_db_main_latest/ml/02_build_features.py)
* Expand feature extraction from a single 6h window to **5 overlapping lookback windows**: $W \in \{2\text{h}, 4\text{h}, 6\text{h}, 8\text{h}, 12\text{h}\}$.
* For each vital sign and lab parameter across all 5 windows, compute:
  * Rolling means (`*_mean_2h`, `*_mean_4h`, `*_mean_6h`, `*_mean_8h`, `*_mean_12h`).
  * Rolling standard deviations / volatility (`*_std_2h`, `*_std_6h`, `*_std_12h`).
  * Rolling rates of change / velocity (`*_rate_2h`, `*_rate_6h`, `*_rate_12h`).
* Implement **Moving Average Crossovers (Trend Acceleration Signals)**:
  * `short_vs_long_trend_2h_8h = mean_2h - mean_8h` (captures acute deterioration vs baseline).
  * `short_vs_long_trend_4h_12h = mean_4h - mean_12h`.
* Output `features_hict.parquet`.

---

### Model Training & Inference Layer

#### [MODIFY] [12_ordinal_train.py](file:///e:/IP_EarlyWarning/EWS-CDS/common_db_main_latest/ml/12_ordinal_train.py)
* Train discrete-time hazard survival XGBoost boosters per interval ($2\text{h}, 4\text{h}, 6\text{h}, 9\text{h}, 12\text{h}, 18\text{h}, 24\text{h}$) on the new `features_hict.parquet` and `anchors_hict.parquet`.
* Reconstruct monotonic non-increasing survival curves $S(c_j) = \prod_{k=1}^j (1 - h_k)$ by construction.
* Output `preds_ordinal_hict.parquet` and trained model artifacts in `data/models_ordinal_hict/`.

#### [NEW] [19_ensemble_hict_uncertainty.py](file:///e:/IP_EarlyWarning/EWS-CDS/common_db_main_latest/ml/19_ensemble_hict_uncertainty.py)
* Implement an ensemble of discrete-time hazard models to compute predictive standard deviation $\sigma$.
* Operationalize Prof. Gautam's **3-Way Decision Policy ("YES / NO / IDK")**:
  * **YES (Actionable Alarm / PAGE):** Predicted risk $P \ge 0.30$ AND $\sigma < 0.10$.
  * **NO (Clear / Low Risk):** Predicted risk $P \le 0.10$ AND $\sigma < 0.10$.
  * **IDK (Abstain / Silent WATCH Ward Dashboard):** Moderate risk ($0.10 < P < 0.30$) OR high uncertainty ($\sigma \ge 0.10$).

---

### Evaluation & Reporting Pipeline

#### [MODIFY] [eval_core.py](file:///e:/IP_EarlyWarning/EWS-CDS/common_db_main_latest/ml/eval_core.py)
* Update `episode_metrics()` to use `EPISODE_GAP_H = 8.0` (8-hour refractory grace period).
* Add evaluation metrics for the 3-Way Decision Policy (PAGE Episode-PPV, WATCH Recall, Abstention Rate).
* Ensure threshold selection remains strictly frozen on `calib` split and evaluated out-of-sample on `test` split.

#### [MODIFY] [10_focused_report.py](file:///e:/IP_EarlyWarning/EWS-CDS/common_db_main_latest/ml/10_focused_report.py)
* Re-generate all 16 diagnostic and clinical evaluation plots under the HICT target and multi-window features.
* Save output metrics to `data/metrics_hict.json` and charts to `data/charts_hict/`.

#### [MODIFY] [21_ablation_report.py](file:///e:/IP_EarlyWarning/EWS-CDS/common_db_main_latest/ml/21_ablation_report.py)
* Update ablation reporting to include the HICT target baseline comparisons and false alarm reduction metrics.

---

## Verification Plan

### Automated Tests
- Run self-test scripts to verify zero data leakage and exact person-period table alignment:
  ```bash
  EWS_TAG=hict py -3 01_build_labels.py --selftest
  EWS_TAG=hict py -3 02_build_features.py
  EWS_TAG=hict py -3 eval_core.py
  ```
- Retrain ordinal discrete-time hazard model and ensemble:
  ```bash
  EWS_TAG=hict py -3 12_ordinal_train.py
  EWS_TAG=hict py -3 19_ensemble_hict_uncertainty.py
  ```
- Generate complete evaluation report:
  ```bash
  EWS_TAG=hict py -3 10_focused_report.py
  EWS_TAG=hict py -3 21_ablation_report.py
  ```

### Manual Verification & Output Check
- Verify that `metrics_hict.json` shows:
  1. Episode PPV @ 12h under 8h gap is $\ge 40\%-50\%$.
  2. Alarm density is $< 1.0$ episode per patient-day.
  3. Patient recall remains $\ge 95\%$.
  4. Monotonic survival curves $S(c_j)$ have zero violations.
