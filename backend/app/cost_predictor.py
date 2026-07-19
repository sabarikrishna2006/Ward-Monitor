"""
cost_predictor.py — ML day-wise cost prediction (quantile regression)
=======================================================================

Serves the trained XGBoost quantile model from cost_ml_model/ (P10/P50/P90
final-bill range for a DCM admission, as of the end of a given hospital day).

Lazy-loaded once at first use, same pattern as embedder.py's MedCPTEmbedder.

CURRENT LIMITATION (first pass, backend-only, not wired to the live app yet):
this reads pre-computed features from cost_ml_model/data/dcm_model_ready_data.csv
(built from real MIMIC-IV admissions) — it can only predict for hadm_ids that
exist in that file, i.e. our own historical DCM cohort, not the live app's
synthetic/demo patients. Serving predictions for real live-app patients needs
a feature-generation pipeline mirroring cost_ml_model/build_day_costs.py
against whatever data source the live app's patients actually have — a
separate, bigger integration task, not solved here.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import joblib
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_COST_ML_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "cost_ml_model")
# xgb_quantile_remaining_based.joblib predicts remaining_cost (bill so far
# subtracted out), not the total bill directly -- tested against the old
# total-predicting model on the same held-out set: fewer errors on every
# single day bucket (44.5% -> 41.3% overall MAPE), AND it structurally
# cannot predict a Floor below money already charged (0/9,849 test rows
# violate that vs. 32.4% for the old model), since remaining cost is
# clamped >= 0 before being added back to the known cumulative cost.
_MODEL_PATH = os.path.join(_COST_ML_DIR, "models", "xgb_quantile_remaining_based.joblib")
_DATA_PATH = os.path.join(_COST_ML_DIR, "data", "dcm_model_ready_data.csv")


class CostPredictor:
    """Wraps the trained XGBoost quantile model. Loads once, reused across requests."""

    def __init__(self) -> None:
        self._model = None
        self._features: Optional[list] = None
        self._data: Optional[pd.DataFrame] = None
        logger.info("CostPredictor initialised (model not yet loaded — lazy)")

    def _load(self) -> None:
        if self._model is None:
            logger.info(f"Loading cost model from {_MODEL_PATH} ...")
            bundle = joblib.load(_MODEL_PATH)
            self._model = bundle["model"]
            self._features = bundle["features"]
            self._data = pd.read_csv(_DATA_PATH)
            logger.info(f"Cost model ready ({len(self._features)} features, "
                        f"{len(self._data)} rows available)")

    def available_hadm_ids(self) -> list:
        """hadm_ids this predictor can currently serve (our DCM cohort only)."""
        self._load()
        return sorted(self._data["hadm_id"].unique().tolist())

    def predict(self, hadm_id: int, hospital_day: Optional[int] = None) -> dict:
        """
        Predict the final-bill range for one admission, as of the end of
        `hospital_day`. If hospital_day is None, uses the latest day
        available for that admission (i.e. "as of today").

        Returns: {hadm_id, hospital_day, p10, p50, p90, cumulative_cost_so_far}
        Raises ValueError if hadm_id isn't in the served cohort.
        """
        self._load()
        rows = self._data[self._data["hadm_id"] == hadm_id]
        if rows.empty:
            raise ValueError(
                f"hadm_id {hadm_id} is not in the served DCM cohort — this endpoint "
                f"currently only serves predictions for our historical MIMIC dataset, "
                f"not live-app patients (see module docstring)."
            )

        if hospital_day is None:
            row = rows.sort_values("hospital_day").iloc[[-1]]
        else:
            row = rows[rows["hospital_day"] == hospital_day]
            if row.empty:
                available_days = sorted(rows["hospital_day"].tolist())
                raise ValueError(
                    f"hadm_id {hadm_id} has no row for hospital_day={hospital_day}. "
                    f"Available days: {available_days}"
                )

        X = row[self._features]
        cumulative = float(row["cumulative_cost_so_far"].iloc[0])
        pred_log = self._model.predict(X)[0]
        # Model predicts remaining cost (bill so far subtracted out), not the
        # total bill -- clamp at >=0 (can't owe negative future money), sort
        # to guard quantile crossing, then add back the known cumulative
        # cost. This makes "Floor >= money already charged" a structural
        # guarantee from the model itself, not a hardcoded rule bolted on
        # after -- see _MODEL_PATH comment for the numbers.
        pred_remaining = np.clip(np.expm1(pred_log), 0, None)
        p10, p50, p90 = cumulative + np.sort(pred_remaining)

        this_hospital_day = int(row["hospital_day"].iloc[0])
        # Cumulative breakdown by category, days 0..this_hospital_day -- the
        # exact same day-level columns the model itself was trained on.
        history = rows[rows["hospital_day"] <= this_hospital_day]
        breakdown = {
            "procedures": round(float(history["day_procedures_cost"].sum()), 2),
            "medicines": round(float(history["day_medicines_cost"].sum()), 2),
            "labs": round(float(history["day_labs_cost"].sum()), 2),
            "ward": round(float(history["day_ward_cost"].sum()), 2),
            "icu": round(float(history["day_icu_cost"].sum()), 2),
        }
        today_breakdown = {
            "procedures": round(float(row["day_procedures_cost"].iloc[0]), 2),
            "medicines": round(float(row["day_medicines_cost"].iloc[0]), 2),
            "labs": round(float(row["day_labs_cost"].iloc[0]), 2),
            "ward": round(float(row["day_ward_cost"].iloc[0]), 2),
            "icu": round(float(row["day_icu_cost"].iloc[0]), 2),
            "total": round(float(row["day_total_cost"].iloc[0]), 2),
        }

        return {
            "hadm_id": int(hadm_id),
            "hospital_day": this_hospital_day,
            "cumulative_cost_so_far": round(float(row["cumulative_cost_so_far"].iloc[0]), 2),
            "cost_breakdown": breakdown,
            "today_breakdown": today_breakdown,
            "predicted_final_bill_p10": round(float(p10), 2),
            "predicted_final_bill_p50": round(float(p50), 2),
            "predicted_final_bill_p90": round(float(p90), 2),
            "source": "precomputed_dcm_cohort",
        }

    def predict_live(self, hadm_id: int, conn, hospital_day: Optional[int] = None) -> dict:
        """
        Predict for ANY admitted patient, computing features fresh from the
        live active_patients/ap_* tables via live_feature_builder. Requires
        an open SQLAlchemy connection (caller owns the transaction/engine).
        """
        self._load()
        from .live_feature_builder import build_live_feature_row

        X, breakdown, today_breakdown, _admit_date = build_live_feature_row(hadm_id, conn, self._features, hospital_day)
        cumulative = float(X["cumulative_cost_so_far"].iloc[0])
        pred_log = self._model.predict(X)[0]
        # Same remaining-cost reconstruction as predict() above -- see
        # _MODEL_PATH comment for why this replaced predicting the total
        # bill directly.
        pred_remaining = np.clip(np.expm1(pred_log), 0, None)
        p10, p50, p90 = cumulative + np.sort(pred_remaining)

        return {
            "hadm_id": int(hadm_id),
            "hospital_day": int(X["hospital_day"].iloc[0]),
            "cumulative_cost_so_far": round(float(X["cumulative_cost_so_far"].iloc[0]), 2),
            "cost_breakdown": {k: round(float(v), 2) for k, v in breakdown.items()},
            "today_breakdown": today_breakdown,
            "predicted_final_bill_p10": round(float(p10), 2),
            "predicted_final_bill_p50": round(float(p50), 2),
            "predicted_final_bill_p90": round(float(p90), 2),
            "source": "live",
        }

    def predict_auto(self, hadm_id: int, conn, hospital_day: Optional[int] = None) -> dict:
        """Try live data first (real admitted patient); fall back to the
        precomputed historical CSV (useful for our own demo/test hadm_ids
        that haven't been admitted through the live app)."""
        try:
            return self.predict_live(hadm_id, conn, hospital_day)
        except ValueError:
            return self.predict(hadm_id, hospital_day)


# Module-level singleton, mirrors the embedder.py pattern.
cost_predictor = CostPredictor()
