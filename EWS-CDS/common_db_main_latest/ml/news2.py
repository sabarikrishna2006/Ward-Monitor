"""
Standalone NEWS2 replay for the survival-ML pipeline.

This is a faithful, dependency-free copy of `calculate_news2()` /
`_score_range()` / `_load_news2_thresholds()` from
`sabari_project/backend/main.py` (the production scorer, lines 21-143), so the
ML label pipeline scores vitals *identically* to the live ward system.

Why copy instead of import: `main.py` pulls in FastAPI, SQLAlchemy, and the
Cloud SQL connector at import time. We only need the pure scoring function, so
we re-implement it here and load the SAME `news2_thresholds.yaml` (single source
of truth for the bands). A unit test (see `tests/`) asserts parity on sample
vitals.
"""
from __future__ import annotations

import os
import yaml

# Reuse the production thresholds file — do NOT fork the bands.
_NEWS2_YAML = os.path.join(
    os.path.dirname(__file__),
    "..", "sabari_project", "backend", "rules", "news2_thresholds.yaml",
)
_NEWS2_CACHE: dict | None = None


def _load_news2_thresholds() -> dict:
    global _NEWS2_CACHE
    if _NEWS2_CACHE is None:
        with open(os.path.abspath(_NEWS2_YAML), "r", encoding="utf-8") as f:
            _NEWS2_CACHE = yaml.safe_load(f)
    return _NEWS2_CACHE


def _score_range(value: float, bands: list[dict]) -> int:
    """Score a numeric vital against a sorted list of band dicts {min?, max?, score}."""
    for band in bands:
        lo = band.get("min", float("-inf"))
        hi = band.get("max", float("inf"))
        if lo <= value <= hi:
            return band.get("score", 0)
    return 0


def calculate_news2(vitals: dict, hypercapnic_failure: bool = False) -> dict:
    """
    YAML-driven NEWS2 scorer — identical logic to production main.py:79.

    `vitals` keys (any may be missing -> that parameter contributes 0):
        resp_rate, spo2, air_or_oxygen ('Air'|'Oxygen'), sbp, heart_rate,
        consciousness ('A' = alert; anything else -> +3), temperature (deg C).

    Returns {"total": int, "factors": [{"name","score"}, ...]}.
    """
    cfg = _load_news2_thresholds()
    active = cfg.get("active_set", "uk_news2")
    thresholds = cfg.get(active, cfg.get("uk_news2", {}))

    score = 0
    factors: list[dict] = []

    rr = vitals.get("resp_rate")
    if rr is not None:
        s = _score_range(rr, thresholds.get("resp_rate", []))
        score += s
        if s > 0:
            factors.append({"name": "Respiration Rate", "score": s})

    spo2 = vitals.get("spo2")
    if spo2 is not None:
        on_o2 = vitals.get("air_or_oxygen") == "Oxygen"
        if hypercapnic_failure:
            s = _score_range(spo2, thresholds.get("spo2_scale2", []))
            if on_o2 and spo2 >= 93:            # RCP SpO2 Scale 2 on-oxygen bonuses
                if spo2 <= 94:
                    s = 1
                elif spo2 <= 96:
                    s = 2
                else:
                    s = 3
            score += s
            if s > 0:
                factors.append({"name": "SpO2 (Scale 2)", "score": s})
        else:
            s = _score_range(spo2, thresholds.get("spo2_scale1", []))
            score += s
            if s > 0:
                factors.append({"name": "SpO2 (Scale 1)", "score": s})

    if vitals.get("air_or_oxygen") == "Oxygen":
        score += 2
        factors.append({"name": "Supplemental Oxygen", "score": 2})

    sbp = vitals.get("sbp")
    if sbp is not None:
        s = _score_range(sbp, thresholds.get("sbp", []))
        score += s
        if s > 0:
            factors.append({"name": "Systolic BP", "score": s})

    hr = vitals.get("heart_rate")
    if hr is not None:
        s = _score_range(hr, thresholds.get("heart_rate", []))
        score += s
        if s > 0:
            factors.append({"name": "Heart Rate", "score": s})

    consciousness = vitals.get("consciousness")
    if consciousness and consciousness != "A":
        score += 3
        factors.append({"name": "Consciousness (CVPU)", "score": 3})

    temp = vitals.get("temperature")
    if temp is not None:
        s = _score_range(temp, thresholds.get("temperature", []))
        score += s
        if s > 0:
            factors.append({"name": "Temperature", "score": s})

    return {"total": score, "factors": factors}


# ── NEWS2 risk bands (matches production main.py tiering) ────────────────────
def news2_band(score: int) -> int:
    """0 = stable (0-4), 1 = warning (5-6), 2 = HIGH/critical (>=7)."""
    if score >= 7:
        return 2
    if score >= 5:
        return 1
    return 0
