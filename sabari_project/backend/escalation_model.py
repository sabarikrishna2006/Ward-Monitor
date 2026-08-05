import os
import json
import logging
import numpy as np
import xgboost as xgb
import pickle
from datetime import datetime

log = logging.getLogger(__name__)

# Global state for lazy loading
_BOOSTERS = None
_CALIBRATORS = None
_META = None
_LATCH_STATE = {}  # hadm_id -> True/False (PAGE/CLEAR)

MODEL_DIR = os.path.join(os.path.dirname(__file__), "model")

def load_models():
    global _BOOSTERS, _CALIBRATORS, _META
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
        return True
    except Exception as e:
        log.error(f"Failed to load escalation models: {e}")
        return False

def build_features(patient, recent_vitals):
    """
    Constructs the 55 features required by the models_ordinal_esc model.
    recent_vitals: list of dicts, ordered chronologically (oldest to newest in the 24h window).
    """
    if not recent_vitals:
        return None

    f = {}
    
    # Context features
    f["age"] = float(getattr(patient, "anchor_age", getattr(patient, "age", 60)) or 60)
    f["is_female"] = 1.0 if getattr(patient, "gender", getattr(patient, "sex", "")) == "F" else 0.0
    
    now = datetime.now()
    admit_time = getattr(patient, "admit_time", None)
    if admit_time:
        if hasattr(admit_time, 'tzinfo') and admit_time.tzinfo is not None:
            admit_time = admit_time.replace(tzinfo=None)
        f["hours_since_adm"] = (now - admit_time).total_seconds() / 3600.0
    else:
        f["hours_since_adm"] = 24.0

    # Parse vitals into arrays
    series = {
        "dbp": [], "heart_rate": [], "resp_rate": [], "sbp": [],
        "spo2": [], "temperature": [], "news2": []
    }
    
    # We map 'hr' to 'heart_rate', 'rr' to 'resp_rate', 'temp' to 'temperature'
    v_map = {
        "dbp": "dbp", "hr": "heart_rate", "rr": "resp_rate", 
        "sbp": "sbp", "spo2": "spo2", "temp": "temperature", "news2": "news2"
    }

    for v in recent_vitals:
        for short_k, long_k in v_map.items():
            val = v.get(short_k)
            if val is not None and val != '--' and val != '-':
                try:
                    if isinstance(val, str) and '/' in val:
                        val = float(val.split('/')[0])
                    else:
                        val = float(val)
                    series[long_k].append(val)
                except ValueError:
                    series[long_k].append(np.nan)
            else:
                series[long_k].append(np.nan)
                
    f["hours_of_history"] = min(f["hours_since_adm"], len(recent_vitals))
    
    last_v = recent_vitals[-1]
    f["not_alert"] = 1.0 if last_v.get("consciousness", "A") != "A" else 0.0
    f["on_oxygen"] = 1.0 if last_v.get("air_or_oxygen", "Air") != "Air" else 0.0
    f["fio2_last"] = 21.0
    f["news2_at_anchor"] = series["news2"][-1] if series["news2"] and not np.isnan(series["news2"][-1]) else 0.0
    
    # Calculate rolling stats
    for k, vals in series.items():
        arr = np.array(vals, dtype=float)
        arr = arr[~np.isnan(arr)]
        if len(arr) > 0:
            f[f"{k}_last"] = arr[-1]
            f[f"{k}_min"] = np.min(arr)
            f[f"{k}_max"] = np.max(arr)
            f[f"{k}_mean"] = np.mean(arr)
            f[f"{k}_std"] = np.std(arr, ddof=1) if len(arr) > 1 else 0.0
            f[f"{k}_delta_adm"] = arr[-1] - arr[0]
            f[f"{k}_rate"] = (arr[-1] - arr[0]) / float(len(vals) - 1) if len(vals) > 1 else 0.0
        else:
            f[f"{k}_last"] = 0.0
            f[f"{k}_min"] = 0.0
            f[f"{k}_max"] = 0.0
            f[f"{k}_mean"] = 0.0
            f[f"{k}_std"] = 0.0
            f[f"{k}_delta_adm"] = 0.0
            f[f"{k}_rate"] = 0.0
            
    # Calculate hours_in_band
    def get_band(n):
        if n >= 7: return 3
        if n >= 5: return 2
        return 1
    
    hours_in_band = 1.0
    if len(series["news2"]) > 0:
        arr = np.array(series["news2"], dtype=float)
        arr = arr[~np.isnan(arr)]
        if len(arr) > 0:
            current_band = get_band(arr[-1])
            for i in range(len(arr)-2, -1, -1):
                if get_band(arr[i]) == current_band:
                    hours_in_band += 1.0
                else:
                    break
    f["hours_in_band"] = hours_in_band

    feature_names = _META["features"]
    x = []
    for fn in feature_names:
        x.append(f.get(fn, 0.0))
        
    return np.array([x], dtype=float)

def predict(patient, recent_vitals, news_factors=None):
    if not load_models():
        return None
        
    try:
        X = build_features(patient, recent_vitals)
        if X is None:
            return None
            
        hazards_raw = []
        for b in _BOOSTERS:
            h = b.predict(xgb.DMatrix(X, feature_names=_META["features"]))
            hazards_raw.append(h[0])
            
        hazards = np.array(hazards_raw)
        
        hazards_calib = np.zeros_like(hazards)
        for j, h_val in enumerate(hazards):
            horizon = _META["horizons"][j]
            calibrator = _CALIBRATORS[horizon]
            hazards_calib[j] = calibrator.predict([h_val])[0]
            
        S = np.zeros(len(hazards_calib) + 1)
        S[0] = 1.0
        for j in range(1, len(S)):
            S[j] = S[j-1] * (1.0 - hazards_calib[j-1])
            
        risk_24h = 1.0 - S[-1]
        risk_2h = 1.0 - S[1]
        
        tau_high = _META.get("tau_high", 0.0932)
        tau_low = _META.get("tau_low", 0.0466)
        
        hadm_id = str(getattr(patient, "hadm_id", getattr(patient, "id", "unknown")))
        currently_latched = _LATCH_STATE.get(hadm_id, False)
        
        if risk_24h >= tau_high:
            currently_latched = True
        elif risk_24h < tau_low:
            currently_latched = False
            
        _LATCH_STATE[hadm_id] = currently_latched
        
        if currently_latched:
            tier = "PAGE"
        elif risk_24h >= tau_low: 
            tier = "WATCH"
        else:
            tier = "CLEAR"
            
        cutpoints = [0] + _META["horizons"]
        midpoints = np.array([(cutpoints[j] + cutpoints[j+1])/2.0 for j in range(len(cutpoints)-1)])
        p_fail = S[:-1] - S[1:]
        num = np.sum(p_fail * midpoints)
        time_to_event = num / max(risk_24h, 1e-9)
        
        window_str = f"next {int(time_to_event)} hours" if risk_24h > 0.05 else "--"
        
        # 1. Dynamic Drivers
        drivers = []
        if news_factors:
            # Map standard NEWS2 factors to ML Labels, similar to demo but real
            _ML_LABELS = {
                "Respiration Rate": "Respiratory rate trend",
                "SpO2 (Scale 1)": "SpO₂ downtrend", "SpO2 (Scale 2)": "SpO₂ downtrend",
                "Supplemental Oxygen": "Oxygen requirement",
                "Systolic BP": "Falling blood pressure", "Heart Rate": "Heart-rate trend",
                "Consciousness (CVPU)": "Reduced consciousness", "Temperature": "Temperature",
            }
            total = sum(f["score"] for f in news_factors) or 1
            drivers = [
                {"label": _ML_LABELS.get(f["name"], f["name"]), "pct": round(f["score"] / total * 100)}
                for f in sorted(news_factors, key=lambda x: x["score"], reverse=True)[:4]
            ]
        
        # Fallback if news_factors isn't passed or is empty
        if not drivers:
            # Check the feature dict for obvious anomalies
            x_dict = dict(zip(_META["features"], X[0]))
            if x_dict.get("heart_rate_mean", 0) > 100 or x_dict.get("heart_rate_mean", 0) < 50:
                drivers.append({"label": "Heart-rate trend", "pct": 40})
            if x_dict.get("sbp_mean", 120) < 90 or x_dict.get("sbp_mean", 120) > 160:
                drivers.append({"label": "Abnormal blood pressure", "pct": 30})
            if x_dict.get("resp_rate_mean", 16) > 22 or x_dict.get("resp_rate_mean", 16) < 10:
                drivers.append({"label": "Respiratory rate trend", "pct": 30})
            if not drivers:
                drivers = [{"label": "Multivariate vital instability", "pct": 100}]
        
        return {
            "escalationRisk": float(round(risk_24h * 100, 1)),
            "escalationRisk2h": float(round(risk_2h * 100, 1)),
            "escalationTier": tier,
            "escalationWindow": window_str,
            "escalationDrivers": drivers,
            "escalationModel": "live",
            "stats": _META.get("practitioner_stats", {})
        }
    except Exception as e:
        log.error(f"Escalation model prediction error: {e}")
        return None
