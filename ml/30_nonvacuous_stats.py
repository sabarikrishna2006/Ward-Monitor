"""
The exact statistic Prof. Shroff asked for, computed properly.

His written ask, verbatim: "Calculate the number of cases where this is a
non-vacuous prediction (i.e. news2 not reached yet and alarm predicted) and
the false-positives and recall for these cases. Cases where news2 is already
reached are vacuous."

non_vacuous := known_subset(df, h=24) AND news2_at_anchor < 7

This is NOT the same population as build_serving_esc.py's practitioner_stats
(computed across ALL anchors, vacuous and non-vacuous alike). Reusing that
number here would be exactly the stale/mismatched-number failure that already
damaged trust once. This script reruns the same label-conditional hysteresis
machinery, restricted to the non-vacuous subset, and is the ONLY source any
UI or slide number for "non-vacuous" should ever quote.

tau_high/tau_low are loaded from the already-DEPLOYED
sabari_project/backend/model/serving_meta.json (not refit here) so this
script measures the exact model+threshold combination currently serving
live traffic, not a hypothetical refit.

Run: PYTHONUTF8=1 py -3 30_nonvacuous_stats.py
"""
from __future__ import annotations

import json
import os

import numpy as np
import pandas as pd

import config
import eval_core as ec
from known_status import known_subset

HORIZON_FOR_TIER = 24
BACKEND_MODEL_DIR = os.path.join(
    os.path.dirname(__file__), "..", "sabari_project", "backend", "model"
)


def main():
    preds = pd.read_parquet(config.dpath("preds_ordinal_esc.parquet"))
    test = preds[preds.split == "test"].copy()
    col = f"p_calibrated_{HORIZON_FOR_TIER}h"

    with open(os.path.join(BACKEND_MODEL_DIR, "serving_meta.json")) as f:
        serving_meta = json.load(f)
    tau_high = serving_meta["tau_high"]
    tau_low = serving_meta["tau_low"]
    assert serving_meta["source_model"] == "models_ordinal_esc", (
        "serving_meta.json no longer points at models_ordinal_esc -- this "
        "script's tau_high/tau_low would silently measure the wrong model."
    )

    # ---- known-status restriction, then hysteresis over the FULL known set.
    # Hysteresis is stateful (a Schmitt trigger over each patient's own
    # chronology) so it must be computed over the complete anchor sequence
    # BEFORE any news2<7 filtering -- filtering first would corrupt the latch
    # state by silently deleting the history the trigger depends on. ----
    tsub, ty = known_subset(test, HORIZON_FOR_TIER)
    hyst_on = ec.hysteresis_alert(tsub, col, thr_high=tau_high, thr_low=tau_low)
    tsub_h = tsub.copy()
    tsub_h["_hyst_score"] = hyst_on.astype(float)

    # ---- sanity: this must be a strict subset of the all-anchors population
    # build_serving_esc.py measured (verification item #1 in the plan). ----
    n_total_known = len(tsub_h)

    # ---- NOW restrict to non-vacuous anchors: NEWS2 hasn't reached 7 yet. ----
    nv_mask = tsub_h["news2_at_anchor"].values < 7
    nv_df = tsub_h.loc[nv_mask].reset_index(drop=True)
    nv_y = np.asarray(ty)[nv_mask]

    n_non_vacuous = len(nv_df)
    assert n_non_vacuous < n_total_known, (
        "non-vacuous subset is not strictly smaller than the full known-status "
        "population -- news2_at_anchor filter did not do anything, investigate."
    )

    n_alerting_hours = int(nv_df["_hyst_score"].sum())

    epm = ec.episode_metrics(nv_df, "_hyst_score", 0.5, nv_y)
    ep = ec.alert_episodes(nv_df, "_hyst_score", 0.5, nv_y)
    true_ep = ep[ep["y_any"] == 1] if len(ep) else ep
    lead = true_ep["lead_time_h"].values if len(true_ep) else np.array([])

    stats = dict(
        model="models_ordinal_esc",
        tau_high=tau_high,
        tau_low=tau_low,
        definition="known_subset(test, h=24) AND news2_at_anchor < 7 at the anchor",
        n_total_known_anchors=n_total_known,
        n_non_vacuous_person_hours=n_non_vacuous,
        n_alerting_non_vacuous_hours=n_alerting_hours,
        n_episodes=epm["n_episodes"],
        n_true_episodes=epm["n_true_episodes"],
        n_false_episodes=epm["n_false_episodes"],
        episode_ppv=epm["episode_ppv"],
        false_positive_rate_episodes=(1.0 - epm["episode_ppv"]) if epm["n_episodes"] else float("nan"),
        n_event_patients_non_vacuous=epm["n_event_patients"],
        n_event_patients_caught=epm["n_event_patients_caught"],
        patient_recall=epm["patient_recall"],
        median_lead_time_h=epm["median_lead_time_h"],
        n_true_episodes_with_lead_time=int(len(lead)),
        lead_time_ci_note="median reported above; small true-episode N means this can be noisy -- see n_true_episodes_with_lead_time",
    )

    print(json.dumps(stats, indent=2, default=float))

    # ---- write into the same serving_meta.json every UI/backend number reads
    # from, so nothing downstream can quote a number from a different run. ----
    serving_meta["non_vacuous_stats"] = stats
    with open(os.path.join(BACKEND_MODEL_DIR, "serving_meta.json"), "w") as f:
        json.dump(serving_meta, f, indent=2, default=float)
    print(f"\nWrote non_vacuous_stats block into {os.path.join(BACKEND_MODEL_DIR, 'serving_meta.json')}")


if __name__ == "__main__":
    main()
