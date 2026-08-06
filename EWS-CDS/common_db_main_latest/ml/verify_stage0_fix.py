"""
Stage-0 verification (plan §0b/§5): quantify exactly how much of the <6h
imminent-deterioration blind spot the look-back-gate fix recovered, and what
residual remains -- re-derived from data on every run, never typed in from
memory. Reconstructs the OLD (pre-fix) build_anchors() gate (a full
t >= intime + LOOKBACK_H requirement) purely to compare zero-anchor sets; it
does not touch or overwrite any pipeline output.

Writes data/stage0_verification_news2.json (with EWS_TAG=news2), read by
10_focused_report.py for the written Limitations section so that text is
sourced from a real artifact, not hardcoded prose.

Run: EWS_TAG=news2 py -3 verify_stage0_fix.py
"""
from __future__ import annotations

import importlib
import json
import logging

import numpy as np
import pandas as pd

import config
from news2 import news2_band

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("verify_stage0")

labels = importlib.import_module("01_build_labels")
W = pd.Timedelta(hours=config.LOOKBACK_H)


def _old_stays_with_anchor(hv: pd.DataFrame, ev: pd.DataFrame) -> set:
    """Reconstruction of the PRE-FIX build_anchors() eligibility gate
    (t >= intime + LOOKBACK_H required) -- used only to compute which stays
    had >=1 anchor under the old rule, for an exact before/after comparison."""
    hv = hv.sort_values(["stay_id", "hour"])
    stays_with_anchor = set()
    for sid, g in hv.groupby("stay_id"):
        if sid not in ev.index:
            continue
        e = ev.loc[sid]
        intime = e["intime"]
        det, death, out = e["deterioration_time"], e["deathtime"], e["outtime"]
        stay_end = min([t for t in [det, death, out] if pd.notna(t)], default=out)
        ghours = g["hour"].values
        gnews = g["news2"].values
        have_vitals = ~pd.isna(gnews)
        for i, t in enumerate(ghours):
            t = pd.Timestamp(t)
            if t < intime + W:
                continue
            if pd.notna(stay_end) and t >= stay_end:
                continue
            win = (ghours > np.datetime64(t - W)) & (ghours <= np.datetime64(t))
            if have_vitals[win].sum() < config.MIN_VITALS_IN_WINDOW:
                continue
            if pd.notna(gnews[i]) and news2_band(int(gnews[i])) == config.NEWS2_HIGH_BAND:
                continue
            stays_with_anchor.add(sid)
            break
    return stays_with_anchor


def main():
    cohort = pd.read_parquet(config.dpath("cohort.parquet"))
    hv = pd.read_parquet(config.tpath("vitals_hourly.parquet"))
    inputevents = pd.read_parquet(config.dpath("inputevents.parquet"))
    procedureevents = pd.read_parquet(config.dpath("procedureevents.parquet"))
    anchors_new = pd.read_parquet(config.tpath("anchors.parquet"))

    ev = labels.compute_stay_events(cohort, inputevents, procedureevents, hv, event_mode="news2")
    ev = ev.set_index("stay_id")
    ev["intime"] = pd.to_datetime(ev["intime"])
    det = ev.dropna(subset=["deterioration_time"])
    det_ids = set(det.index)

    old_with_anchor = _old_stays_with_anchor(hv, ev)
    old_zero_anchor = det_ids - old_with_anchor

    new_with_anchor = set(anchors_new["stay_id"].unique())
    recovered = old_zero_anchor - (old_zero_anchor - new_with_anchor)
    residual = old_zero_anchor - new_with_anchor

    hours_to_onset_all = (det["deterioration_time"] - det["intime"]) / pd.Timedelta(hours=1)
    residual_onset = hours_to_onset_all.loc[list(residual)]

    result = dict(
        n_true_deteriorators=len(det_ids),
        old_gate_zero_anchor_n=len(old_zero_anchor),
        old_gate_zero_anchor_pct=round(100 * len(old_zero_anchor) / len(det_ids), 1),
        recovered_n=len(recovered),
        recovered_pct_of_old_zero=round(100 * len(recovered) / len(old_zero_anchor), 1),
        residual_n=len(residual),
        residual_pct_of_old_zero=round(100 * len(residual) / len(old_zero_anchor), 1),
        residual_deteriorate_within_1h_pct=round(100 * float((residual_onset <= 1).mean()), 1),
        residual_deteriorate_within_2h_pct=round(100 * float((residual_onset <= 2).mean()), 1),
        residual_deteriorate_within_3h_pct=round(100 * float((residual_onset <= 3).mean()), 1),
        residual_onset_median_h=round(float(residual_onset.median()), 2),
    )
    log.info("Stage-0 fix verification: %s", json.dumps(result, indent=2))
    with open(config.tpath("stage0_verification.json"), "w") as f:
        json.dump(result, f, indent=2)
    log.info("wrote %s", config.tpath("stage0_verification.json"))


if __name__ == "__main__":
    main()
