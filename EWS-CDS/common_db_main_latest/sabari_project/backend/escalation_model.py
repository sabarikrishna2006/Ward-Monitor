import os
import json
import logging
import numpy as np
import xgboost as xgb
import shap
import pickle
from datetime import datetime

log = logging.getLogger(__name__)

# Global state for lazy loading — MODEL ARTEFACTS ONLY. Do not add any
# per-patient mutable state here (e.g. a latch dict): the hysteresis tier must
# be re-derivable from vitals history alone so it survives a process restart.
# See predict()'s docstring.
_BOOSTERS = None
_CALIBRATORS = None
_META = None
_SHAP_EXPLAINER = None   # TreeExplainer for the 24h-horizon booster only —
                          # tau_high/tau_low are fit on that horizon's score,
                          # so explanations must come from the same booster
                          # driving the alarm, not an arbitrary/blended one.
_HORIZON_24H_IDX = None

MODEL_DIR = os.path.join(os.path.dirname(__file__), "model")

# ── Human-readable feature labels for SHAP driver display ──────────────────
# Built compositionally (base vital x suffix) rather than a 55-entry literal
# table, so every feature in serving_meta.json's feature list resolves to a
# real label instead of silently falling through to the raw column name.
_BASE_LABELS = {
    "dbp": "Diastolic BP", "heart_rate": "Heart rate", "resp_rate": "Respiratory rate",
    "sbp": "Systolic BP", "spo2": "SpO₂", "temperature": "Temperature",
    "news2": "NEWS2 score", "age": "Age", "is_female": "Sex",
    "fio2_last": "Oxygen requirement (FiO₂)", "not_alert": "Consciousness level",
    "on_oxygen": "Supplemental oxygen", "hours_in_band": "Time in current NEWS2 band",
    "hours_of_history": "Monitoring history length", "hours_since_adm": "Time since admission",
}
_SUFFIX_LABELS = [
    ("_delta_adm", "change since admission"), ("_last", "latest value"),
    ("_max", "recent high"), ("_min", "recent low"), ("_mean", "recent average"),
    ("_std", "recent variability"), ("_rate", "trend (rate of change)"),
]


def _feature_base_and_suffix(fname: str) -> tuple[str, str | None]:
    """Splits a feature name into (base vital, suffix description) — e.g.
    'sbp_min' -> ('sbp', 'recent low'). Used both for the single-feature
    label and for grouping correlated sub-features (sbp_last/_mean/_min/
    _max/_std/_rate/_delta_adm are 7 features describing ONE vital; SHAP
    naturally splits credit for a real BP effect across all 7, which makes
    any single one look weak even when the underlying signal is strong)."""
    for suf, desc in _SUFFIX_LABELS:
        if fname.endswith(suf):
            base = fname[: -len(suf)]
            if base in _BASE_LABELS:
                return base, desc
    return fname, None


def _feature_label(fname: str) -> str:
    base, desc = _feature_base_and_suffix(fname)
    label = _BASE_LABELS.get(base, base.replace("_", " ").capitalize())
    return f"{label} — {desc}" if desc else label

LOOKBACK_H = 6.0          # trailing window for _mean/_std/_min/_max/_rate — must
                          # match ml/config.py's LOOKBACK_H used at training time
HYSTERESIS_ANCHORS = 6    # trailing readings to replay the latch over — kept
                          # modest because this multiplies booster calls per
                          # patient (6 anchors x 7 interval boosters); the main
                          # per-patient score is the only call site paying this


def load_models():
    global _BOOSTERS, _CALIBRATORS, _META, _HORIZON_24H_IDX
    if _META is not None:
        return True

    try:
        with open(os.path.join(MODEL_DIR, "serving_meta.json"), "r") as f:
            _META = json.load(f)

        with open(os.path.join(MODEL_DIR, "calibrators.pkl"), "rb") as f:
            _CALIBRATORS = pickle.load(f)

        _BOOSTERS = []
        for h in _META["horizons"]:
            b = xgb.Booster()
            b.load_model(os.path.join(MODEL_DIR, f"hazard_interval_{h}h.json"))
            _BOOSTERS.append(b)
        _HORIZON_24H_IDX = _META["horizons"].index(24)
        return True
    except Exception as e:
        log.error(f"Failed to load escalation models: {e}")
        return False


def _get_shap_explainer():
    """Lazily builds (once) a TreeExplainer against the 24h booster — the
    same booster tau_high/tau_low are fit on, so the explanation always
    matches the number actually driving the alarm."""
    global _SHAP_EXPLAINER
    if _SHAP_EXPLAINER is None:
        _SHAP_EXPLAINER = shap.TreeExplainer(_BOOSTERS[_HORIZON_24H_IDX])
    return _SHAP_EXPLAINER


def _shap_drivers(X, feature_names, top_n=4):
    """Real per-prediction explainability: SHAP values from the model's own
    24h-horizon booster (log-odds/margin space, binary:logistic objective),
    not a NEWS2-derived or hand-built heuristic.

    Sub-features are grouped by physiological base vital before ranking
    (sbp_last/_mean/_min/_max/_std/_rate/_delta_adm are 7 correlated features
    describing ONE vital -- SHAP splits credit for a real BP effect across
    all 7, so ranking individual columns understates vitals with many
    engineered sub-features relative to single-column ones like age or
    is_female). Grouping sums real |SHAP| within each vital -- it does not
    invent or reweight anything -- and reports the single most-influential
    sub-feature's own suffix/direction as the representative detail, so
    every number shown is still one specific SHAP value, just aggregated for
    a clinician-legible top line.
    """
    explainer = _get_shap_explainer()
    sv = np.asarray(explainer.shap_values(X)).reshape(-1)
    total_abs = float(np.sum(np.abs(sv))) or 1.0

    groups: dict[str, list[int]] = {}
    for i, fname in enumerate(feature_names):
        base, _ = _feature_base_and_suffix(fname)
        groups.setdefault(base, []).append(i)

    scored = []
    for base, idxs in groups.items():
        group_importance = float(np.sum(np.abs(sv[idxs])))
        rep_i = idxs[int(np.argmax(np.abs(sv[idxs])))]
        scored.append((group_importance, base, rep_i))
    scored.sort(key=lambda t: -t[0])

    return [
        {
            "label": _feature_label(feature_names[rep_i]) if len(groups[base]) == 1
                      else _BASE_LABELS.get(base, base.replace("_", " ").capitalize()),
            "feature": feature_names[rep_i],
            "pct": round(group_importance / total_abs * 100),
            "direction": "up" if sv[rep_i] > 0 else "down",
            "shapValue": float(sv[rep_i]),
        }
        for group_importance, base, rep_i in scored[:top_n]
    ]


def _elapsed_hours(t_from, t_to):
    if t_from is None or t_to is None:
        return None
    return (t_to - t_from).total_seconds() / 3600.0


def build_features(patient, vitals_asc, as_of_idx=None):
    """Constructs the 55 features required by models_ordinal_esc.

    vitals_asc: full available history, ordered OLDEST -> NEWEST, each item a
    dict with chart_time (datetime) plus the vital/news2 fields _vt_to_dict()
    in main.py produces.
    as_of_idx: score as of vitals_asc[as_of_idx] (inclusive); defaults to the
    last element. Used by predict() to replay a trailing risk trajectory for
    hysteresis without needing separate DB calls.

    Matches ml/02_build_features.py's definitions: _mean/_std/_min/_max/_rate
    are computed over a trailing LOOKBACK_H=6 CLOCK-HOUR window (not a fixed
    reading count — ward monitoring cadence varies 1h-12h by acuity, so
    "last N readings" would silently span a different amount of history for
    every patient). _delta_adm is change since the earliest reading actually
    fetched for this patient (up to 96 rows server-side) — for stays longer
    than that window this is "since earliest available", not true admission,
    which is the honest limit of scoring from already-fetched rows without an
    extra query.
    """
    if not vitals_asc:
        return None
    if as_of_idx is None:
        as_of_idx = len(vitals_asc) - 1
    history = vitals_asc[:as_of_idx + 1]
    if not history:
        return None

    anchor = history[-1]
    anchor_time = anchor.get("chart_time") or datetime.now()

    f = {}
    f["age"] = float(getattr(patient, "anchor_age", getattr(patient, "age", 60)) or 60)
    f["is_female"] = 1.0 if getattr(patient, "gender", getattr(patient, "sex", "")) == "F" else 0.0

    # admit_time sanity check: MIMIC-sourced patients carry their ORIGINAL
    # MIMIC admission timestamp (sometimes a de-identified date decades away,
    # e.g. year 2150) while their vitals' chart_time has been re-anchored to a
    # realistic recent timeline by the sync job. Computing (now - admit_time)
    # directly against that raw MIMIC date produced hours_since_adm in the
    # MILLIONS (once even negative -1.08M hours) -- a wildly out-of-training-
    # distribution value fed straight into the model. Fall back to the span of
    # the patient's own fetched vitals history when admit_time doesn't yield a
    # sane, bounded, non-negative duration.
    now = datetime.now()
    admit_time = getattr(patient, "admit_time", None)
    if admit_time and hasattr(admit_time, 'tzinfo') and admit_time.tzinfo is not None:
        admit_time = admit_time.replace(tzinfo=None)
    hours_since_adm = _elapsed_hours(admit_time, now) if admit_time else None
    if hours_since_adm is None or hours_since_adm < 0 or hours_since_adm > 24 * 365:
        earliest_time = history[0].get("chart_time")
        vitals_span = _elapsed_hours(earliest_time, anchor_time) if earliest_time else None
        hours_since_adm = vitals_span if (vitals_span is not None and vitals_span >= 0) else LOOKBACK_H
    f["hours_since_adm"] = hours_since_adm
    # Clock-hours of history actually usable for the rolling window, capped at
    # LOOKBACK_H — NOT a count of readings (ml/config.py: hours_of_history =
    # min(hours_since_adm, LOOKBACK_H)).
    f["hours_of_history"] = float(min(hours_since_adm, LOOKBACK_H))

    v_map = {"dbp": "dbp", "hr": "heart_rate", "rr": "resp_rate",
             "sbp": "sbp", "spo2": "spo2", "temp": "temperature", "news2": "news2"}

    def _num(v, short_k):
        val = v.get(short_k)
        if val is None or val in ('--', '-'):
            return np.nan
        try:
            return float(val)
        except (ValueError, TypeError):
            return np.nan

    # ---- windowed series: only readings within the trailing LOOKBACK_H clock
    # hours of the anchor, matching training's rolling(W).mean()/std()/etc. ----
    windowed = [v for v in history
                if _elapsed_hours(v.get("chart_time"), anchor_time) is not None
                and 0 <= _elapsed_hours(v.get("chart_time"), anchor_time) <= LOOKBACK_H]
    if not windowed:
        windowed = [anchor]

    last_v = anchor
    f["not_alert"] = 1.0 if (last_v.get("consciousness") or "A") != "A" else 0.0
    f["on_oxygen"] = 1.0 if (last_v.get("air_or_oxygen") or "Air") != "Air" else 0.0
    f["fio2_last"] = 21.0
    news2_anchor = _num(anchor, "news2")
    f["news2_at_anchor"] = float(news2_anchor) if not np.isnan(news2_anchor) else 0.0

    for short_k, long_k in v_map.items():
        win_vals = np.array([_num(v, short_k) for v in windowed], dtype=float)
        win_times = [v.get("chart_time") for v in windowed]
        win_valid = ~np.isnan(win_vals)

        last_val = _num(anchor, short_k)
        # full (unwindowed) history for delta_adm — "since earliest available
        # reading", the honest analogue of "since admission" given only the
        # already-fetched rows (see docstring).
        full_vals = np.array([_num(v, short_k) for v in history], dtype=float)
        full_valid = np.flatnonzero(~np.isnan(full_vals))

        if long_k == "news2":
            prefix = "news2"
            stats = ("mean", "max")  # training's news2 family: last/mean/max/rate (no min/std)
        else:
            prefix = long_k
            stats = ("mean", "std", "min", "max")

        if np.isnan(last_val) and win_valid.any():
            last_val = win_vals[win_valid][-1]
        f[f"{prefix}_last"] = float(last_val) if not np.isnan(last_val) else 0.0

        if win_valid.sum() >= 1:
            vv = win_vals[win_valid]
            if "mean" in stats: f[f"{prefix}_mean"] = float(np.mean(vv))
            if "std" in stats:  f[f"{prefix}_std"] = float(np.std(vv, ddof=1)) if len(vv) > 1 else 0.0
            if "min" in stats:  f[f"{prefix}_min"] = float(np.min(vv))
            if "max" in stats:  f[f"{prefix}_max"] = float(np.max(vv))
        else:
            for s in stats:
                f[f"{prefix}_{s}"] = 0.0

        # rate = (last - earliest-in-window) / elapsed HOURS between them —
        # ml/02_build_features.py's _rate_over_available_window, adapted from
        # an hourly grid (where index-steps==hours) to real timestamps.
        rate = 0.0
        if win_valid.sum() >= 2:
            idxs = np.flatnonzero(win_valid)
            i0, i1 = idxs[0], idxs[-1]
            span_h = _elapsed_hours(win_times[i0], win_times[i1])
            if span_h and span_h > 1e-6:
                rate = float((win_vals[i1] - win_vals[i0]) / span_h)
        f[f"{prefix}_rate"] = rate

        if long_k != "news2":
            delta_adm = 0.0
            if len(full_valid) >= 1 and not np.isnan(last_val):
                delta_adm = float(last_val - full_vals[full_valid[0]])
            f[f"{prefix}_delta_adm"] = delta_adm

    # ---- hours_in_band: elapsed CLOCK HOURS the patient has spent in the
    # current NEWS2 band (0-4 low / 5-6 medium / >=7 high), walking backward
    # from the anchor through the full history until the band changes. ----
    def _band(n):
        if n >= 7: return 2
        if n >= 5: return 1
        return 0

    hours_in_band = 0.0
    if not np.isnan(news2_anchor):
        current_band = _band(news2_anchor)
        band_start_time = anchor_time
        for v in reversed(history[:-1]):
            n = _num(v, "news2")
            if np.isnan(n) or _band(n) != current_band:
                break
            band_start_time = v.get("chart_time") or band_start_time
        elapsed = _elapsed_hours(band_start_time, anchor_time)
        hours_in_band = float(elapsed) if elapsed is not None else 0.0
    f["hours_in_band"] = hours_in_band

    feature_names = _META["features"]
    x = [f.get(fn, 0.0) for fn in feature_names]
    return np.array([x], dtype=float)


def score_only(patient, vitals_asc, as_of_idx=None):
    """Cheap single-anchor 24h risk, no hysteresis replay. For call sites that
    only need a display number (e.g. the historical sparkline) and would
    otherwise pay for a full HYSTERESIS_ANCHORS-deep replay per point for no
    reason — that multiplies out fast when called once per trajectory point."""
    if not load_models() or not vitals_asc:
        return None
    try:
        if as_of_idx is None:
            as_of_idx = len(vitals_asc) - 1
        S = _score_risk24h(patient, vitals_asc, as_of_idx)
        return None if S is None else float(round((1.0 - S[-1]) * 100, 1))
    except Exception:
        return None


def _score_risk24h(patient, vitals_asc, as_of_idx):
    """One booster pass -> calibrated 24h escalation probability at a single
    trailing anchor point. Returns None if there isn't enough data to score."""
    X = build_features(patient, vitals_asc, as_of_idx)
    if X is None:
        return None
    hazards_raw = np.array([b.predict(xgb.DMatrix(X, feature_names=_META["features"]))[0]
                             for b in _BOOSTERS])
    hazards_calib = np.array([_CALIBRATORS[h].predict([hv])[0]
                               for h, hv in zip(_META["horizons"], hazards_raw)])
    S = np.ones(len(hazards_calib) + 1)
    for j in range(1, len(S)):
        S[j] = S[j - 1] * (1.0 - hazards_calib[j - 1])
    return S


def predict(patient, recent_vitals):
    """recent_vitals must be ordered OLDEST -> NEWEST (matches how main.py
    builds vitals_history/vitals_dict_history).

    Hysteresis is STATELESS by design: rather than latching PAGE/CRITICAL in
    an in-process dict (which resets on every restart/redeploy and would
    silently un-page a patient mid-demo), the Schmitt trigger is replayed each
    request over the trailing HYSTERESIS_ANCHORS readings already fetched for
    this patient. The resulting tier is a pure function of vitals history, so
    it is identical before and after a process restart — see plan verification
    item #7.
    """
    if not load_models():
        return None

    try:
        if not recent_vitals:
            return None

        S_current = _score_risk24h(patient, recent_vitals, len(recent_vitals) - 1)
        if S_current is None:
            return None
        risk_24h = 1.0 - S_current[-1]
        risk_2h = 1.0 - S_current[1]

        tau_high = _META.get("tau_high", 0.0932)
        tau_low = _META.get("tau_low", 0.0466)

        # ---- stateless hysteresis replay over the trailing anchors ----
        n = len(recent_vitals)
        anchor_idxs = list(range(max(0, n - HYSTERESIS_ANCHORS), n))
        latched = False
        for idx in anchor_idxs:
            S_i = _score_risk24h(patient, recent_vitals, idx)
            if S_i is None:
                continue
            r_i = 1.0 - S_i[-1]
            if r_i >= tau_high:
                latched = True
            elif r_i < tau_low:
                latched = False
        currently_latched = latched

        if currently_latched:
            tier = "CRITICAL RISK"
        elif risk_24h >= tau_low:
            tier = "HIGH RISK"
        else:
            tier = "LOW RISK"

        cutpoints = [0] + _META["horizons"]
        midpoints = np.array([(cutpoints[j] + cutpoints[j + 1]) / 2.0 for j in range(len(cutpoints) - 1)])
        p_fail = S_current[:-1] - S_current[1:]
        num = np.sum(p_fail * midpoints)
        time_to_event = num / max(risk_24h, 1e-9)

        window_str = f"next {int(time_to_event)} hours" if risk_24h > 0.05 else "--"

        # Real per-prediction explainability: SHAP attribution from the
        # model's own 24h booster, not a NEWS2-score readout or a hand-built
        # vital-threshold heuristic (neither of those was ever actually
        # derived from what this model computed — see plan for why that
        # matters under scrutiny). X_last is the same feature vector that
        # produced risk_24h, so the explanation matches the number shown.
        X_last = build_features(patient, recent_vitals, n - 1)
        drivers = _shap_drivers(X_last, _META["features"]) if X_last is not None else [
            {"label": "Insufficient data for attribution", "pct": 100, "direction": "up", "shapValue": 0.0}
        ]

        return {
            "escalationRisk": float(round(risk_24h * 100, 1)),
            "escalationRisk2h": float(round(risk_2h * 100, 1)),
            "escalationTier": tier,
            "escalationWindow": window_str,
            "escalationDrivers": drivers,
            "escalationModel": "live",
            "stats": {**_META.get("practitioner_stats", {}), "auroc_test": _META.get("auroc_test")},
        }
    except Exception as e:
        log.error(f"Escalation model prediction error: {e}")
        return None
