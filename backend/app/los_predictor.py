"""
los_predictor.py — ML day-wise "days remaining in this stay" prediction.

Serves the LOS submodel trained in cost_ml_model/train_los_predictor_experiment.py
(cost_ml_model/models/los_predictor_full_train.joblib) against a live admitted
patient's real synced data, via the same live_feature_builder.py used by
cost_predictor.py. Predicts remaining_days (log1p-transformed at train time,
so expm1 to invert), which combined with the admission date gives an expected
discharge date -- replacing the old "discharge_time +/- a few days" fudge that
only worked for historical/offline patients whose real discharge was already
known.

Known limitation (see cost_ml_model/train_los_predictor_experiment.py's
findings): this submodel gives close to zero benefit at Day 0 specifically --
that's exactly when a "remaining days" guess is hardest, no better than the
cost model's own Day-0 uncertainty. It's still a real, out-of-fold-trained
prediction (not a leak), just don't expect Day-0 discharge estimates to be
sharp -- they're a genuine best guess, not a solved answer.
"""
from __future__ import annotations

import logging
import os
from datetime import timedelta
from typing import Optional

import joblib
import numpy as np

logger = logging.getLogger(__name__)

_COST_ML_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "cost_ml_model")
_MODEL_PATH = os.path.join(_COST_ML_DIR, "models", "los_predictor_full_train.joblib")


class LosPredictor:
    """Wraps the trained LOS-remaining submodel. Loads once, reused across requests."""

    def __init__(self) -> None:
        self._model = None
        self._features: Optional[list] = None
        logger.info("LosPredictor initialised (model not yet loaded — lazy)")

    def _load(self) -> None:
        if self._model is None:
            logger.info(f"Loading LOS submodel from {_MODEL_PATH} ...")
            bundle = joblib.load(_MODEL_PATH)
            self._model = bundle["model"]
            self._features = bundle["features"]
            logger.info(f"LOS submodel ready ({len(self._features)} features)")

    def predict_live(self, hadm_id: int, conn, hospital_day: Optional[int] = None) -> dict:
        """
        Predict remaining days (and the resulting expected discharge date)
        for a live admitted patient, computing features fresh from
        active_patients/ap_* via live_feature_builder. Requires an open
        SQLAlchemy connection (caller owns the transaction/engine).

        Raises ValueError if the hadm_id isn't found / has no synced data yet.
        """
        self._load()
        from .live_feature_builder import build_live_feature_row

        X, _breakdown, _today_breakdown, admit_date = build_live_feature_row(
            hadm_id, conn, self._features, hospital_day)

        pred_log = self._model.predict(X)[0]
        remaining_days = float(np.clip(np.expm1(pred_log), 0, None))
        this_hospital_day = int(X["hospital_day"].iloc[0])

        expected_discharge_date = admit_date + timedelta(days=round(remaining_days))

        return {
            "hadm_id": int(hadm_id),
            "hospital_day": this_hospital_day,
            "predicted_remaining_days": round(remaining_days, 1),
            "expected_discharge_date": expected_discharge_date.isoformat(),
            "source": "live",
        }


# Module-level singleton, mirrors cost_predictor.py's pattern.
los_predictor = LosPredictor()
