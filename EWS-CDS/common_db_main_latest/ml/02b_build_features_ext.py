"""
Stage 02b — Build the feature set FOR THE ESCALATION TARGET.

WHY THIS EXISTS. `02_build_features.py` produces 55 columns that are all NEWS2-derived
(the top four by XGBoost gain literally ARE the NEWS2 score). Against the escalation
target that set is mismatched, and the measurement proving it is stark:

    NEWS2-slope ruler, C-index on the NEWS2 target      0.5454
    NEWS2-slope ruler, C-index on the escalation target 0.4926   <- worse than chance

NEWS2 trend carries no information about who gets escalated. A model handed only
NEWS2-derived features and asked to predict escalation scored 0.711 vs 0.812 on its
native target -- not because escalation is unpredictable, but because the inputs were
built to predict something else.

WHAT DRIVES ESCALATION, and which of these were previously unavailable:

  circulatory collapse -> pressors / IABP / Impella
      MAP (measured, NEW -- was approximated as (SBP+2*DBP)/3), shock index,
      lactate (NEW), base excess (NEW), HCO3 (NEW), anion gap (NEW)
      Metabolic acidosis moves BEFORE the vitals do -- this is the "NEWS2=3 but
      deteriorating from hidden physiology" patient.
  respiratory failure -> intubation / ventilation
      RR, SpO2, FiO2, pH (NEW), pCO2 (NEW), pO2 (NEW)
  renal failure -> RRT
      creatinine, BUN (NEW), potassium
  myocardial injury -> cardiogenic shock
      troponin (NEW at flowsheet cadence)
  clinician concern (a leading indicator of clinician ACTION, which is the event)
      alarm-limit settings, parameters-checked frequency, hours-since-measured (NEW)
  management already under way
      infusion titration: nitroglycerin weaned as pressure falls, furosemide
      escalated for congestion (NEW, allow-listed to exclude target leakage)

MULTI-WINDOW is applied SELECTIVELY, not to everything. 90 value columns x 3 windows
x 3 statistics would be ~810 features; the JAMIA 2024 review found every system that
reduced mortality used <39 variables, and the two largest (CHARTwatch 526, HBI 349)
degraded worst in deployment. Cell C already showed a train/test gap of 0.0505. So
windows go only on variables where the TRAJECTORY is mechanistically informative;
everything else contributes a last-value plus a hours-since-measured staleness flag.

Output: data/features_<TAG>_mw.parquet
Run: PYTHONUTF8=1 EWS_TAG=esc py -3 02b_build_features_ext.py
"""
from __future__ import annotations

import argparse
import logging

import numpy as np
import pandas as pd

import config
import extended_grid as eg

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("features_ext")

# Trajectory matters -> full multi-window treatment (mean/std/slope + crossovers +
# deviation from the patient's own long-window baseline).
TRAJECTORY_VARS = [
    "map", "shock_index",                       # circulatory
    "heart_rate", "sbp", "resp_rate", "spo2",   # raw physiology, not NEWS2 points
    "hco3", "anion_gap", "lactate_l",           # metabolic acidosis / perfusion
    "creatinine_f", "bun_f",                    # renal
    "gcs_motor",                                # neuro
]

# Level and staleness matter, trajectory does not (drawn 1-2x/day, or a setting).
LEVEL_VARS = [
    "potassium_f", "sodium_f", "chloride_f", "glucose_f", "magnesium", "calcium",
    "phosphorous", "hematocrit", "hemoglobin_f", "platelets_f", "wbc", "inr_f", "pt",
    "troponin_f", "ph_art", "ph_l", "po2_l", "pco2_l", "base_excess_l",
    "bilirubin_l", "albumin_l", "map_art",
    "gcs_eye", "gcs_verbal", "mental_status",
    "hr_alarm_hi", "hr_alarm_lo", "spo2_alarm_hi", "spo2_alarm_lo",
    "rr_alarm_hi", "rr_alarm_lo", "nibp_alarm_hi", "nibp_alarm_lo",
    "alarms_on", "params_checked", "spo2_desat_limit",
    "braden_sensory", "braden_mobility", "braden_activity",
    "braden_moisture", "braden_nutrition", "braden_friction", "adm_weight_lbs",
]


def main(windows=None):
    windows = windows or config.LOOKBACK_WINDOWS
    anchors = pd.read_parquet(config.tpath("anchors.parquet"))
    hv = pd.read_parquet(config.tpath("vitals_hourly.parquet"))
    base = pd.read_parquet(config.tpath("features.parquet"))
    log.info("anchors=%d  base features=%d cols  windows=%s",
             len(anchors), base.shape[1], windows)

    # ---- extended hourly grid, then derive the two composites ----------------
    grid = eg.build_extended_grid(hv[["stay_id", "hour"]])
    v = hv[["stay_id", "hour", "heart_rate", "sbp", "resp_rate", "spo2"]].copy()
    v["hour"] = pd.to_datetime(v["hour"])
    grid = grid.merge(v, on=["stay_id", "hour"], how="left")
    with np.errstate(divide="ignore", invalid="ignore"):
        grid["shock_index"] = grid["heart_rate"] / grid["sbp"].replace(0, np.nan)
    # prefer the MEASURED mean arterial pressure; fall back to the arterial line, and
    # only then to the (SBP+2*DBP)/3 estimate the project used to rely on entirely
    if "map_art" in grid.columns:
        grid["map"] = grid["map"].fillna(grid["map_art"])

    traj = [c for c in TRAJECTORY_VARS if c in grid.columns]
    lvl = [c for c in LEVEL_VARS if c in grid.columns]
    log.info("trajectory vars: %d  level vars: %d", len(traj), len(lvl))

    # ---- multi-window features on the trajectory variables -------------------
    mw = eg.multiwindow_features(grid, anchors, traj, windows=windows)
    log.info("multi-window block: %d columns", mw.shape[1] - 2)

    # ---- level + staleness + infusion state, as-of the anchor hour -----------
    stale = [c for c in grid.columns if c.endswith("_hrs_since")]
    inf = [c for c in grid.columns
           if c.startswith("on_") or c.endswith(("_rate", "_rate_chg2h"))
           or c in ("n_infusions_running", "any_rate_increase_2h")]
    pres = [c for c in grid.columns if c.startswith("has_")]
    keep = sorted(set(lvl + traj + stale + inf + pres))
    a = anchors[["stay_id", "anchor_time"]].copy()
    a["hour"] = pd.to_datetime(a["anchor_time"]).dt.floor("h")
    asof = a.merge(grid[["stay_id", "hour"] + keep], on=["stay_id", "hour"], how="left")
    asof = asof.drop(columns=["hour"])
    log.info("as-of block: %d columns (%d level, %d staleness, %d infusion, %d presence)",
             len(keep), len(lvl), len(stale), len(inf), len(pres))

    # ---- join everything onto the existing base features --------------------
    out = base.merge(asof, on=["stay_id", "anchor_time"], how="left", suffixes=("", "_ext"))
    out = out.merge(mw, on=["stay_id", "anchor_time"], how="left", suffixes=("", "_mw"))

    # leakage guards -- fail loudly rather than train on a leaked feature
    leaky = {str(i) for i in config.LEAKY_POST_ESCALATION_ITEMIDS}
    bad = [c for c in out.columns if any(t in c.lower()
           for t in ("peep", "tidal_volume", "tidalvolume"))]
    assert not bad, f"post-escalation ventilator features present: {bad}"
    forbidden_names = {"norepinephrine", "dopamine", "phenylephrine", "dobutamine",
                       "vasopressin", "epinephrine", "milrinone", "propofol",
                       "fentanyl", "midazolam", "prbc", "packed_red"}
    bad2 = [c for c in out.columns if any(t in c.lower() for t in forbidden_names)]
    assert not bad2, f"target-leaking infusion features present: {bad2}"

    n_new = out.shape[1] - base.shape[1]
    log.info("FINAL: %d columns (%d base + %d new)  rows=%d",
             out.shape[1], base.shape[1], n_new, len(out))
    path = config.tpath("features_mw.parquet")
    out.to_parquet(path, index=False)
    log.info("wrote %s", path)

    num = out.select_dtypes(include=[np.number])
    miss = num.isna().mean().sort_values()
    print("\n  BEST-COVERED new features:")
    newcols = [c for c in num.columns if c not in base.columns]
    print(miss[miss.index.isin(newcols)].head(12).round(3).to_string())
    print("\n  WORST-COVERED new features (high missingness is informative to XGBoost, "
          "not fatal):")
    print(miss[miss.index.isin(newcols)].tail(8).round(3).to_string())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--windows", default=None, help="comma-separated, e.g. 2,6,12")
    a = ap.parse_args()
    w = [int(x) for x in a.windows.split(",")] if a.windows else None
    main(windows=w)
