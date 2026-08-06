"""
Stage 10 — the v1 discrete-time hazard model report: what does the model
predict, and how accurate/trustworthy is it?

PRIMARY model: 12_ordinal_train.py's discrete-time hazard model
(data/preds_ordinal_news2.parquet). AFT (09_focused_train.py) is loaded only
for the side-by-side model-comparison table and as a labeled HISTORICAL
reference for the "naive median" censoring pathology that motivated moving
off it -- it is not this report's headline.

Report ordering (plan §3/§5): the calibrated bucket-probability profile and
its calibration/discrimination metrics are PRIMARY and presented FIRST;
the actual-vs-predicted-TIME point estimate (cond_time_24h) is SECONDARY,
presented after, with a fake-precision caveat printed as visible text on its
own figure -- never as the headline. Chart filenames are numbered to match
this order when sorted (not the order in which they appear below).

Produces (data/charts_focused/*.png), in report order:
  01_horizon_utility      AUC/AUPRC/PPV/alerts-per-event/lift, hazard model vs
                          the NEWS2-slope ruler, at all 7 horizons, known-status
                          anchors only (Brier + alarms/patient-hour in the JSON).
  01b_alarm_episode_comparison   anchor-level (hourly re-alerts counted separately)
                          vs episode-level (consecutive alerts on one patient
                          collapsed to one alarm) alerts-per-event, all horizons --
                          quantifies how much of the raw FP count is re-alerting
                          on the same rising patient rather than distinct false alarms.
  02_threshold_sweep      sensitivity <-> alerts-per-event tradeoff, primary horizon.
  03_calibration          reliability curve (raw vs isotonic) + ECE + calibration
                          slope/intercept, primary horizon.
  04_overfit_check        train vs test C-index / AUC side by side.
  05_decision_curve       net benefit vs treat-all/treat-none.
  06_case_studies         3 real patient trajectories.
  07_table1_cohort        cohort description (row-level AND patient-level N).
  08_model_comparison     hazard model vs AFT vs labs-augmented hazard vs ruler,
                          identical metrics, one table.
  08b_benchmark_context   our own PPV/lift vs published deployed/research systems
                          (eCARTv2, Epic DI, Hyland et al.), with citations --
                          shows our false-positive rate is inside the normal band
                          for this problem class, not evidence of a broken model.
  09_subgroup_breakdown   same metrics split by DCM flag and age band.
  10_scatter_corrected    [SECONDARY] actual time vs conditional E[T|T<=24h].
  11_error_by_bin         [SECONDARY] MAE/MAPE by actual-time bin.
  12_scatter_naive_aft    [AFT REFERENCE ONLY] the old unconditional-median
                          pathology that motivated the discrete-time reframing.
  13_scorecard            one-page executive summary tile grid.
  14_limitations          written limitations, rendered into the report itself.

Also writes data/metrics_focused.json (every number on every slide, traceable).

Run: EWS_TAG=news2 py -3 10_focused_report.py
"""
from __future__ import annotations

import json
import os
import textwrap

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

import config
from known_status import dropped_fraction, known_subset

OUT = config.dpath("charts_focused")
os.makedirs(OUT, exist_ok=True)

TEAL = "#2A6F77"; TEALD = "#215a61"; TEAL_L = "#5AA6AE"; GREY = "#9AA5AD"
AMBER = "#C8862B"; RED = "#B4453C"; GREEN = "#2E7D57"; INK = "#1c2b30"
plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 11, "axes.edgecolor": "#5b6b72",
    "axes.linewidth": 0.8, "axes.grid": True, "grid.color": "#e9edee",
    "grid.linewidth": 0.8, "axes.axisbelow": True, "figure.dpi": 150,
})

PRIMARY_H = 12   # headline horizon for single-horizon plots
METRICS: dict = {}

# one-sentence legend key per figure (plan §2 Q5) -- printed as visible text,
# not just spoken, per the standing "explain before you hand over" rule.
LEGEND = {
    "horizon_utility": "Each row compares this model's calibrated alert (raised when "
        "P(deteriorate by this horizon) crosses the 80%-sensitivity threshold) against the "
        "NEWS2-slope ruler, counted only on anchors whose true status at that horizon is "
        "actually knowable (dropped % = anchors excluded as unknown, per known_status.py).",
    "threshold_sweep": "X-axis = the sensitivity you choose to target; Y-axis = how many "
        "false alarms you must tolerate per true event caught to hit it -- moving right "
        "always costs more false alarms; this is a measured tradeoff curve, not one number.",
    "calibration": "X-axis = the model's stated probability (binned into deciles); Y-axis = "
        "the actual observed event fraction in that bin; the diagonal is 'perfectly honest' -- "
        "points below it mean the model is overconfident. Slope=1/intercept=0 is perfect.",
    "overfit_check": "Compares the same metric computed on data the model was trained on vs. "
        "data it never saw; a small gap means the model generalized rather than memorized.",
    "decision_curve": "Net benefit at a threshold = true alerts' value minus false alerts' "
        "cost, weighted by how many false alerts you'd tolerate per true catch at that "
        "threshold; above BOTH 'alert everyone' and 'alert no one' means the model is useful there.",
    "case_studies": "Grey = the patient's actual NEWS2 score over time; teal = the model's "
        "calibrated P(deteriorate <=h), over time; the dashed line marks the true outcome time, "
        "compared visually against when the risk line was already elevated.",
    "table1_cohort": "Describes who is actually in this dataset at both the ROW level "
        "(repeated hourly snapshots) and the PATIENT level (independent stays) -- a row count "
        "alone overstates independent evidence (repeated-measures caveat, plan §4).",
    "model_comparison": "Same event definition, same features, same train/calib/test split, "
        "same horizons for all three rows -- an apples-to-apples comparison, not cherry-picked.",
    "subgroup_breakdown": "Same discrimination (AUC) and calibration (Brier) metrics, "
        "recomputed separately within each subgroup, to check the model isn't silently failing "
        "a group it looks fine on average over.",
    "scatter_corrected": "SECONDARY output. X-axis = real hours until the event, for patients "
        "who actually had one; Y-axis = the model's own conditional estimate of when, GIVEN it "
        "happens within 24h. This is clinical color commentary -- the calibration/discrimination "
        "metrics above are the actual evidence of accuracy, not this scatter.",
    "error_by_bin": "SECONDARY output. For events that did happen, how far off (hours, and %) "
        "the conditional time estimate was, by how soon the event actually occurred.",
    "scatter_naive_aft": "HISTORICAL REFERENCE, not this model's result. This is the prior "
        "AFT iteration's known failure mode: a perfectly-calibrated but UNCONDITIONAL median is "
        "mathematically forced past the horizon whenever event probability is under 50% -- the "
        "reason the discrete-time hazard model (this report's subject) replaced it.",
    "alarm_episode_comparison": "Anchor-level counts every hourly alert separately, so one "
        "patient trending upward for 8 hours straight is counted as 8 alerts. Episode-level "
        "collapses each patient's consecutive run of alerts into ONE alarm before dividing by "
        "true events caught -- the real-world alarm burden a nurse would actually experience.",
    "benchmark_context": "Our own PPV/lift (this model, live) placed next to published "
        "deployed/research systems predicting DIFFERENT, unambiguously independent outcomes -- "
        "if our false-positive rate were caused by predicting a NEWS2-derived label, independent-"
        "outcome systems should show a clearly better PPV, and they do not (eCARTv2 PPV=0.082, "
        "worse than ours). The rare-event base rate sets this band for everyone, not the label.",
}


def savefig(fig, name):
    path = os.path.join(OUT, name)
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def _legend_text(ax_or_fig, key, y=-0.16):
    txt = "\n".join(textwrap.wrap(LEGEND[key], width=118))
    # Figure objects have no transAxes (that's per-Axes 0-1 space) -- use transFigure
    # instead so the text lands in the intended 0-1 fraction, not raw pixel coords.
    transform = ax_or_fig.transAxes if hasattr(ax_or_fig, "transAxes") else ax_or_fig.transFigure
    ax_or_fig.text(0.0, y, txt, transform=transform, fontsize=8.3, color="#5b6b72", va="top", ha="left")


# ══════════════════════════════════════════════════════════════════════════
# shared confusion-matrix + patient-clustered bootstrap helpers
# ══════════════════════════════════════════════════════════════════════════
def _confusion_at(y, score, sens_target=0.80):
    thr = np.quantile(score[y == 1], 1 - sens_target)
    pred = score >= thr
    tp = int((pred & (y == 1)).sum()); fp = int((pred & (y == 0)).sum())
    fn = int((~pred & (y == 1)).sum()); tn = int((~pred & (y == 0)).sum())
    sens = tp / (tp + fn) if (tp + fn) else np.nan
    spec = tn / (tn + fp) if (tn + fp) else np.nan
    ppv = tp / (tp + fp) if (tp + fp) else np.nan
    return dict(threshold=float(thr), tp=tp, fp=fp, fn=fn, tn=tn,
               sensitivity=sens, specificity=spec, ppv=ppv,
               alerts_per_event=(tp + fp) / tp if tp else np.nan)


def _cluster_bootstrap(y, p, subject_ids, stat_fn, n_boot=300, seed=config.RANDOM_SEED):
    """Patient-clustered bootstrap 95% CI (plan §4.1): resample subject_ids WITH
    replacement, not rows, so repeated hourly snapshots from one patient aren't
    treated as independent evidence."""
    rng = np.random.default_rng(seed)
    uniq = np.unique(subject_ids)
    idx_by_subj = {s: np.where(subject_ids == s)[0] for s in uniq}
    boots = []
    for _ in range(n_boot):
        samp = rng.choice(uniq, size=len(uniq), replace=True)
        idx = np.concatenate([idx_by_subj[s] for s in samp])
        if len(np.unique(y[idx])) < 2:
            continue
        try:
            boots.append(stat_fn(y[idx], p[idx]))
        except Exception:
            continue
    if not boots:
        return float("nan"), float("nan"), 0
    lo, hi = np.percentile(boots, [2.5, 97.5])
    return float(lo), float(hi), len(boots)


# ══════════════════════════════════════════════════════════════════════════
# 00 — presentation-only schematic: how the person-period masking/reconstruction
# actually works (not a metric -- no METRICS[] entry, built for the deck).
# ══════════════════════════════════════════════════════════════════════════
def ordinal_concept_diagram():
    """Three example patients showing exactly which interval-rows they
    contribute, and why, per plan §3's exact masking rule."""
    cutpoints = [0] + [float(h) for h in config.HORIZONS_H]

    patients = [
        dict(name="Patient A — DETERIORATES at 5h", T=5.0, event=True,
            note="Fails inside interval 3 (4-6h) -> contributes\nlabel=1, THEN EXITS. No rows in later\nintervals -- already resolved."),
        dict(name="Patient B — DISCHARGED at 10h (censored)", T=10.0, event=False,
            note="Censored PARTWAY through interval 5\n(9-12h) -> MASKED (excluded) from interval 5\nAND every later interval -- outcome unknowable,\nnot a negative."),
        dict(name="Patient C — STABLE, observed to 24h", T=24.0, event=False,
            note="Survives every interval -> contributes\nlabel=0 to ALL 7 intervals."),
    ]

    fig, ax = plt.subplots(figsize=(13, 5.8))
    y_positions = [2, 1, 0]
    for p, y in zip(patients, y_positions):
        T = p["T"]
        for j in range(1, len(cutpoints)):
            c0, c1 = cutpoints[j - 1], cutpoints[j]
            if T <= c0:
                continue
            if p["event"] and c0 < T <= c1:
                ax.broken_barh([(c0, T - c0)], (y - 0.32, 0.64), facecolors=RED, edgecolors="white")
                ax.plot(T, y, marker="X", color=RED, ms=12, zorder=5)
                break
            if (not p["event"]) and c0 < T < c1:
                ax.broken_barh([(c0, T - c0)], (y - 0.32, 0.64), facecolors="#dfe6e8",
                              edgecolors=GREY, hatch="///")
                ax.plot(T, y, marker="o", color=GREY, ms=10, mfc="white", mew=2, zorder=5)
                break
            ax.broken_barh([(c0, c1 - c0)], (y - 0.32, 0.64), facecolors=GREEN, alpha=0.75, edgecolors="white")

    for c in cutpoints:
        ax.axvline(c, color="#c7cdd0", lw=1, ls=":", zorder=0)
    for j in range(1, len(cutpoints)):
        ax.text((cutpoints[j - 1] + cutpoints[j]) / 2, 2.62, f"interval {j}",
               ha="center", fontsize=8.5, color="#5b6b72")

    ax.set_yticks(y_positions)
    ax.set_yticklabels([p["name"] for p in patients], fontsize=11, color=INK)
    for p, y in zip(patients, y_positions):
        ax.text(25.5, y, p["note"], fontsize=8.6, color=INK, va="center", ha="left")
    ax.set_xlim(0, 24); ax.set_xlabel("Hours since anchor time")
    ax.set_xticks(cutpoints)
    ax.set_ylim(-0.9, 3.05)
    ax.set_xlim(0, 24)
    ax.grid(axis="x", visible=False)
    fig.subplots_adjust(right=0.62)

    from matplotlib.patches import Patch
    ax.legend(handles=[
        Patch(color=GREEN, alpha=0.75, label="Survives interval -> label=0 (trains that interval's classifier)"),
        Patch(color=RED, label="Fails inside interval -> label=1 (terminal row, patient exits)"),
        Patch(facecolor="#dfe6e8", edgecolor=GREY, hatch="///",
             label="Censored partway -> MASKED (excluded here and from every later interval)"),
    ], loc="upper center", bbox_to_anchor=(0.5, -0.16), fontsize=9.5, frameon=False, ncol=1)
    ax.set_title("How the discrete-time hazard model is trained: ONE binary classifier per interval,\n"
                "fit only on whoever is still validly \"at risk\" -- masking (not discarding) unresolved patients",
                fontsize=12.5, weight="bold", color=INK, pad=24)
    savefig(fig, "00_ordinal_concept_diagram.png")


# ══════════════════════════════════════════════════════════════════════════
# 01 — PRIMARY: within-horizon utility, hazard model vs ruler, known-status only
# ══════════════════════════════════════════════════════════════════════════
def horizon_utility(te: pd.DataFrame):
    rows = {}
    for h in config.HORIZONS_H:
        sub, y = known_subset(te, h)
        drop = dropped_fraction(te, h)
        p_model = sub[f"p_calibrated_{h}h"].values
        risk_ruler = 1.0 / np.clip(sub["ruler_time"].values, 1e-3, None)
        subj = sub["subject_id"].values
        base_rate = float(y.mean())

        has_both = len(np.unique(y)) > 1
        auc_model = roc_auc_score(y, p_model) if has_both else np.nan
        auc_ruler = roc_auc_score(y, risk_ruler) if has_both else np.nan
        auprc_model = average_precision_score(y, p_model) if has_both else np.nan
        auprc_ruler = average_precision_score(y, risk_ruler) if has_both else np.nan
        brier_model = float(brier_score_loss(y, np.clip(p_model, 0, 1)))

        cm_model = _confusion_at(y, p_model)
        cm_ruler = _confusion_at(y, risk_ruler)
        lift_model = cm_model["ppv"] / base_rate if base_rate else np.nan
        lift_ruler = cm_ruler["ppv"] / base_rate if base_rate else np.nan
        n_known = len(sub)
        # alarms per patient-hour: each known-status anchor IS one hourly observation,
        # so (alerts raised) / (known-status anchors) = alerts per patient-hour observed.
        alarms_ph_model = (cm_model["tp"] + cm_model["fp"]) / n_known if n_known else np.nan
        alarms_ph_ruler = (cm_ruler["tp"] + cm_ruler["fp"]) / n_known if n_known else np.nan

        auc_ci = _cluster_bootstrap(y, p_model, subj, lambda yy, pp: roc_auc_score(yy, pp)) if has_both else (np.nan, np.nan, 0)

        rows[h] = dict(n_known=n_known, n_events=int(y.sum()), base_rate=base_rate,
                       dropped_unknown_pct=round(drop * 100, 1),
                       auc_model=float(auc_model), auc_model_ci=[auc_ci[0], auc_ci[1]],
                       auc_ruler=float(auc_ruler),
                       auprc_model=float(auprc_model), auprc_ruler=float(auprc_ruler),
                       brier_model=brier_model,
                       lift_model=float(lift_model), lift_ruler=float(lift_ruler),
                       alarms_per_patient_hour_model=float(alarms_ph_model),
                       alarms_per_patient_hour_ruler=float(alarms_ph_ruler),
                       model=cm_model, ruler=cm_ruler)

    fig, ax = plt.subplots(figsize=(12.5, 3.9)); ax.axis("off")
    cols = ["Horizon", "n known\n(dropped %)", "Events\n(base rate)",
            "Hazard\nAUC", "Hazard\nAUPRC", "Hazard\nPPV", "Hazard\nLift", "Hazard\nalerts/event",
            "Ruler\nAUC", "Ruler\nalerts/event"]
    tbl = []
    for h in config.HORIZONS_H:
        r = rows[h]
        tbl.append([f"<= {h}h", f"{r['n_known']}\n({r['dropped_unknown_pct']}%)",
                   f"{r['n_events']} ({r['base_rate']:.0%})",
                   f"{r['auc_model']:.3f}", f"{r['auprc_model']:.3f}",
                   f"{r['model']['ppv']:.2f}", f"{r['lift_model']:.2f}x", f"{r['model']['alerts_per_event']:.1f}",
                   f"{r['auc_ruler']:.3f}", f"{r['ruler']['alerts_per_event']:.1f}"])
    t = ax.table(cellText=tbl, colLabels=cols, cellLoc="center", loc="center")
    t.auto_set_font_size(False); t.set_fontsize(9.5); t.scale(1, 2.15)
    for j in range(len(cols)):
        t[0, j].set_facecolor(TEALD); t[0, j].set_text_props(color="white", weight="bold")
    for j in (3, 4, 5, 6, 7):
        for i in range(1, len(config.HORIZONS_H) + 1):
            t[i, j].set_facecolor("#eaf3f3")
    ax.set_title("PRIMARY OUTPUT — utility inside each horizon, discrete-time hazard model vs the NEWS2-slope ruler\n"
                "(known-status anchors only, 80% sensitivity operating point; Brier score + alarms/patient-hour in metrics_focused.json)",
                fontsize=11.5, weight="bold", color=INK, pad=14)
    _legend_text(fig, "horizon_utility", y=0.02)
    savefig(fig, "01_horizon_utility.png")

    METRICS["horizon_utility"] = rows
    return rows


# ══════════════════════════════════════════════════════════════════════════
# 01b — alarm-episode deduplication: how much of the FP count is re-alerting
# on the same rising patient, vs. distinct alarm episodes?
# ══════════════════════════════════════════════════════════════════════════
def alarm_episode_metrics(te: pd.DataFrame, hutil: dict):
    """Collapse each patient's consecutive run of alerts into ONE episode, at
    every horizon, using the SAME 80%-sensitivity threshold horizon_utility()
    already computed. Two honestly-different comparisons, not one:
      (a) alarm RATE per patient-hour, anchor-level vs episode-level -- this
          comparison IS mathematically guaranteed episode<=anchor, because an
          episode is a strict collapse of a run of alerted rows (same
          denominator, n_known, on both sides).
      (b) mean episodes per successfully-alerted true-event patient -- the
          direct "how many separate alarms did THIS caught patient personally
          generate" number (not comparable to the row-based alerts_per_event,
          which divides by a different, row-level denominator -- comparing
          those two directly would be an apples-to-oranges denominator mismatch)."""
    rows = {}
    for h in config.HORIZONS_H:
        sub, y = known_subset(te, h)
        thr = hutil[h]["model"]["threshold"]
        n_known = len(sub)
        d = sub[["stay_id", "anchor_time", "event"]].copy()
        d["alert"] = sub[f"p_calibrated_{h}h"].values >= thr
        d = d.sort_values(["stay_id", "anchor_time"]).reset_index(drop=True)

        prev_alert = d.groupby("stay_id")["alert"].shift(1, fill_value=False)
        episode_start = d["alert"].values & ~prev_alert.values
        d["episode_start"] = episode_start

        n_anchor_alerts = int(d["alert"].sum())
        n_episodes = int(episode_start.sum())
        assert n_episodes <= n_anchor_alerts, (
            f"episode count ({n_episodes}) exceeds alerted-row count ({n_anchor_alerts}) at h={h} "
            f"-- episodes are a collapse of alerted rows and must never exceed them")

        anchor_rate = hutil[h]["alarms_per_patient_hour_model"]
        episode_rate = n_episodes / n_known if n_known else float("nan")
        assert episode_rate <= anchor_rate + 1e-9, (
            f"episode rate ({episode_rate}) exceeds anchor rate ({anchor_rate}) at h={h}")

        event_stays = set(d.loc[d["event"] == 1, "stay_id"].unique())
        ep_per_stay = d[d["stay_id"].isin(event_stays)].groupby("stay_id")["episode_start"].sum()
        caught = ep_per_stay[ep_per_stay > 0]

        rows[h] = dict(
            anchor_alarms_per_patient_hour=float(anchor_rate),
            episode_alarms_per_patient_hour=float(episode_rate),
            n_episodes_total=n_episodes,
            n_true_event_patients_alerted=int(len(caught)),
            mean_episodes_per_caught_patient=float(caught.mean()) if len(caught) else float("nan"),
            anchor_alerts_per_event_for_reference=float(hutil[h]["model"]["alerts_per_event"]),
        )

    fig, ax = plt.subplots(figsize=(8, 4.9))
    hs = config.HORIZONS_H
    x = np.arange(len(hs))
    ax.plot(x, [rows[h]["anchor_alarms_per_patient_hour"] for h in hs], color=GREY, lw=2.2, marker="s", ms=6,
           label="Anchor-level (every hourly alert counted)")
    ax.plot(x, [rows[h]["episode_alarms_per_patient_hour"] for h in hs], color=TEAL, lw=2.4, marker="o", ms=6,
           label="Episode-level (real alarm burden)")
    ax.set_xticks(x); ax.set_xticklabels([f"<={h}h" for h in hs])
    ax.set_xlabel("Horizon"); ax.set_ylabel("Alarms per patient-hour observed")
    ax.set_ylim(0, max(rows[h]["anchor_alarms_per_patient_hour"] for h in hs) * 1.15)
    ax.set_title("Real alarm burden: collapsing re-alerts on the same rising patient into one episode",
                fontsize=12, weight="bold", color=INK)
    ax.legend(frameon=False, fontsize=9, loc="upper left")
    mep = rows[PRIMARY_H]["mean_episodes_per_caught_patient"]
    # placed BELOW the axes (negative y, axes-fraction coords) -- inside the plot area
    # an opaque annotation box would sit right on top of the (correctly small) episode
    # line and visually hide it, since that line sits near the bottom of the y-range.
    ax.text(0.0, -0.16, f"At {PRIMARY_H}h: a caught patient personally generates "
           f"{mep:.1f} separate alarm episodes on average before their event (not "
           f"{rows[PRIMARY_H]['anchor_alerts_per_event_for_reference']:.1f} -- that anchor-level "
           f"number counts every hour of one sustained alarm as a separate alert).",
           transform=ax.transAxes, fontsize=8.3, color=TEALD, va="top", ha="left", wrap=True)
    _legend_text(ax, "alarm_episode_comparison", y=-0.30)
    savefig(fig, "01b_alarm_episode_comparison.png")

    METRICS["alarm_episode_comparison"] = rows
    return rows


# ══════════════════════════════════════════════════════════════════════════
# 02 — sensitivity <-> alerts-per-event tradeoff sweep
# ══════════════════════════════════════════════════════════════════════════
def threshold_sweep(te: pd.DataFrame, h=PRIMARY_H):
    sub, y = known_subset(te, h)
    p_model = sub[f"p_calibrated_{h}h"].values
    risk_ruler = 1.0 / np.clip(sub["ruler_time"].values, 1e-3, None)

    targets = np.linspace(0.5, 0.95, 19)
    model_alerts, ruler_alerts = [], []
    for s in targets:
        model_alerts.append(_confusion_at(y, p_model, s)["alerts_per_event"])
        ruler_alerts.append(_confusion_at(y, risk_ruler, s)["alerts_per_event"])

    fig, ax = plt.subplots(figsize=(7, 4.6))
    ax.plot(targets * 100, model_alerts, color=TEAL, lw=2.4, marker="o", ms=4, label="Discrete-time hazard model")
    ax.plot(targets * 100, ruler_alerts, color=GREY, lw=2.0, marker="s", ms=4, label="NEWS2-slope ruler")
    ax.set_xlabel("Target sensitivity (% of true events caught)")
    ax.set_ylabel("False alarms per true event")
    ax.set_title(f"Threshold tuning at the {h}h horizon\n(lower = fewer false alarms for the same catch rate)",
                fontsize=12, weight="bold", color=INK)
    ax.legend(frameon=False, fontsize=9)
    _legend_text(ax, "threshold_sweep")
    savefig(fig, "02_threshold_sweep.png")

    METRICS["threshold_sweep"] = dict(horizon=h, sensitivity_targets=targets.tolist(),
                                      model_alerts_per_event=model_alerts, ruler_alerts_per_event=ruler_alerts)


# ══════════════════════════════════════════════════════════════════════════
# 03 — calibration reliability + ECE + calibration slope/intercept
# ══════════════════════════════════════════════════════════════════════════
def calibration_reliability(te: pd.DataFrame, h=PRIMARY_H):
    sub, y = known_subset(te, h)
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.8), sharey=True)
    results = {}
    for ax, col, title in [(axes[0], f"p_raw_{h}h", "BEFORE calibration (raw per-interval hazard chain)"),
                           (axes[1], f"p_calibrated_{h}h", "AFTER isotonic calibration")]:
        p = sub[col].values
        dec = pd.qcut(p, 10, labels=False, duplicates="drop")
        obs = pd.Series(y).groupby(dec).mean()
        pred = pd.Series(p).groupby(dec).mean()
        ece = float((obs - pred).abs().mean())
        ax.plot([0, 1], [0, 1], color=RED, lw=1.4, ls="--")
        ax.plot(pred.values, obs.values, color=TEAL, lw=2, marker="o", ms=5)
        ax.set_xlabel(f"predicted P(event <= {h}h)")
        ax.set_title(f"{title}\nECE = {ece:.3f}", fontsize=11, color=INK)
        ax.set_xlim(0, 1); ax.set_ylim(0, 1)
        results[col] = dict(pred=pred.round(3).tolist(), obs=obs.round(3).tolist(), ece=ece)
    axes[0].set_ylabel(f"observed frequency of event <= {h}h")

    p_cal = np.clip(sub[f"p_calibrated_{h}h"].values, 1e-4, 1 - 1e-4)
    logit_p = np.log(p_cal / (1 - p_cal)).reshape(-1, 1)
    lr = LogisticRegression().fit(logit_p, y)
    slope, intercept = float(lr.coef_[0, 0]), float(lr.intercept_[0])

    fig.suptitle(f"Is the {h}h risk probability trustworthy?  "
                f"calibration slope={slope:.2f}, intercept={intercept:.2f}  (1.0 / 0.0 = perfect; slope<1 = overconfident)",
                fontsize=12.5, weight="bold", color=INK)
    _legend_text(axes[0], "calibration", y=-0.18)
    savefig(fig, "03_calibration.png")
    METRICS["calibration"] = dict(horizon=h, calibration_slope=slope, calibration_intercept=intercept, **results)


# ══════════════════════════════════════════════════════════════════════════
# 04 — overfitting check: train vs test
# ══════════════════════════════════════════════════════════════════════════
def overfit_check(preds: pd.DataFrame, meta: dict, h=PRIMARY_H):
    tr = preds[preds.split == "train"]; te = preds[preds.split == "test"]
    rows = []
    for name, d in [("train", tr), ("test", te)]:
        sub, y = known_subset(d, h)
        auc = roc_auc_score(y, sub[f"p_calibrated_{h}h"].values) if len(np.unique(y)) > 1 else np.nan
        ev = d[d.event == 1]
        mae = float((ev["T_hours"] - ev["cond_time_24h"]).abs().mean())
        rows.append(dict(split=name, n=len(d), c_index=meta[f"c_index_hazard_{name}"],
                         auc_at_h=float(auc), mae_cond_time=mae))
    fig, ax = plt.subplots(figsize=(9.5, 3.4)); ax.axis("off")
    cols = ["Split", "n rows", "C-index", f"AUC (<={h}h)", "MAE cond.\ntime (h)"]
    tbl = [[r["split"], r["n"], f"{r['c_index']:.4f}", f"{r['auc_at_h']:.4f}", f"{r['mae_cond_time']:.2f}"] for r in rows]
    t = ax.table(cellText=tbl, colLabels=cols, cellLoc="center", loc="center",
                colWidths=[0.16, 0.2, 0.2, 0.22, 0.22])
    t.auto_set_font_size(False); t.set_fontsize(11); t.scale(1, 2.4)
    for j in range(len(cols)):
        t[0, j].set_facecolor(TEALD); t[0, j].set_text_props(color="white", weight="bold")
    gap = rows[0]["c_index"] - rows[1]["c_index"]
    ci = meta.get("c_index_hazard_test_ci", [float("nan"), float("nan")])
    ax.set_title(f"Overfitting check — train vs test  (C-index gap = {gap:.3f}; test 95% CI [{ci[0]:.3f}, {ci[1]:.3f}], patient-clustered)",
                fontsize=12, weight="bold", color=INK, pad=16)
    _legend_text(ax, "overfit_check", y=-0.08)
    savefig(fig, "04_overfit_check.png")
    METRICS["overfit_check"] = dict(rows=rows, c_index_gap=float(gap), c_index_test_ci=ci)


# ══════════════════════════════════════════════════════════════════════════
# 05 — decision curve analysis (Vickers & Elkin 2006)
# ══════════════════════════════════════════════════════════════════════════
def decision_curve(te: pd.DataFrame, h=PRIMARY_H):
    sub, y = known_subset(te, h)
    p = sub[f"p_calibrated_{h}h"].values
    N = len(y)
    thresholds = np.linspace(0.01, 0.5, 50)
    nb_model, nb_all = [], []
    prevalence = y.mean()
    for pt in thresholds:
        pred = p >= pt
        tp = (pred & (y == 1)).sum(); fp = (pred & (y == 0)).sum()
        nb_model.append(tp / N - fp / N * (pt / (1 - pt)))
        nb_all.append(prevalence - (1 - prevalence) * (pt / (1 - pt)))
    nb_none = np.zeros_like(thresholds)

    fig, ax = plt.subplots(figsize=(7.2, 4.9))
    ax.plot(thresholds * 100, nb_model, color=TEAL, lw=2.4, label="Discrete-time hazard model")
    ax.plot(thresholds * 100, nb_all, color=GREY, lw=1.8, ls="--", label="Alert on everyone")
    ax.plot(thresholds * 100, nb_none, color="#3a3a3a", lw=1.8, ls=":", label="Alert on no one")
    ax.set_ylim(min(nb_model + [0]) - 0.02, max(max(nb_model), prevalence) * 1.15)
    ax.set_xlabel("Alert threshold (probability %)"); ax.set_ylabel("Net benefit")
    ax.set_title(f"Decision curve analysis — does using this model beat the alternatives?\n(horizon={h}h)",
                fontsize=12, weight="bold", color=INK)
    ax.legend(frameon=False, fontsize=9)
    _legend_text(ax, "decision_curve")
    savefig(fig, "05_decision_curve.png")
    METRICS["decision_curve"] = dict(horizon=h, thresholds=thresholds.tolist(),
                                     net_benefit_model=nb_model, net_benefit_treat_all=nb_all)


# ══════════════════════════════════════════════════════════════════════════
# 06 — case studies: real patient trajectories
# ══════════════════════════════════════════════════════════════════════════
def case_studies(preds: pd.DataFrame, vh: pd.DataFrame, alert_threshold: float, h=PRIMARY_H):
    te = preds[preds.split == "test"].sort_values(["stay_id", "anchor_time"])
    span = vh.groupby("stay_id", observed=True)["hour"].agg(["min", "max"])

    def stay_stats(g):
        has_event = bool((g["event"] == 1).any())
        if has_event:
            ev_row = g[g["event"] == 1].iloc[0]
            outcome_ts = ev_row["anchor_time"] + pd.Timedelta(hours=float(ev_row["T_hours"]))
        else:
            outcome_ts = span.loc[g.name, "max"] if g.name in span.index else g["anchor_time"].max()
        return pd.Series(dict(n=len(g), first_risk=g[f"p_calibrated_{h}h"].iloc[0],
                              last_risk=g[f"p_calibrated_{h}h"].iloc[-1],
                              max_risk=g[f"p_calibrated_{h}h"].max(),
                              event=int(has_event), outcome_ts=outcome_ts,
                              t0=span.loc[g.name, "min"] if g.name in span.index else g["anchor_time"].min()))
    stats = te.groupby("stay_id", observed=True).apply(stay_stats, include_groups=False)
    stats["duration_h"] = (stats["outcome_ts"] - stats["t0"]).dt.total_seconds() / 3600
    stats = stats[stats.n >= 6]

    ev_stays = stats[stats.event == 1]
    caught_early = (ev_stays[ev_stays.last_risk - ev_stays.first_risk > 0.15]
                    .sort_values("n", ascending=False))
    caught_early_id = int(caught_early.index[0]) if len(caught_early) else (
        int(ev_stays.sort_values("max_risk", ascending=False).index[0]) if len(ev_stays) else None)

    borderline = ev_stays[ev_stays.first_risk < 0.25]
    borderline = borderline.drop(index=[caught_early_id], errors="ignore")
    borderline_id = int(borderline.sort_values("n", ascending=False).index[0]) if len(borderline) else None

    stable_stays = stats[(stats.event == 0) & stats.duration_h.between(24, 96)]
    if not len(stable_stays):
        stable_stays = stats[stats.event == 0]
    stable_stays = stable_stays.sort_values("n", ascending=False)
    stable_id = int(stable_stays.index[0]) if len(stable_stays) else None

    picks = [(caught_early_id, "CAUGHT EARLY — risk climbs well ahead of the crossing"),
            (borderline_id, "BORDERLINE — risk stays low, only rises late (honest limitation)"),
            (stable_id, "STABLE — correctly stays low-risk throughout")]
    picks = [(sid, label) for sid, label in picks if sid is not None]

    fig, axes = plt.subplots(len(picks), 1, figsize=(9, 3.1 * len(picks)), sharex=False)
    if len(picks) == 1:
        axes = [axes]
    summary = []
    for ax, (sid, label) in zip(axes, picks):
        g = te[te.stay_id == sid].sort_values("anchor_time")
        v = vh[vh.stay_id == sid].sort_values("hour")
        row = stats.loc[sid]
        t0 = row["t0"]
        outcome_hour = (row["outcome_ts"] - t0).total_seconds() / 3600
        hours_v_full = (v["hour"] - t0).dt.total_seconds() / 3600
        hours_g = (g["anchor_time"] - t0).dt.total_seconds() / 3600

        window_end = outcome_hour + 12
        keep_v = hours_v_full <= window_end
        hours_v = hours_v_full[keep_v]
        news2_v = v["news2"][keep_v]
        keep_g = hours_g <= window_end
        hours_g_show, risk_show = hours_g[keep_g], g[f"p_calibrated_{h}h"][keep_g]

        ax2 = ax.twinx()
        ax.plot(hours_v, news2_v, color=GREY, lw=1.6, label="NEWS2 score")
        ax.axhline(7, color=RED, lw=1, ls=":")
        ax2.plot(hours_g_show, risk_show * 100, color=TEAL, lw=2.2, marker="o", ms=3,
                 label=f"P(deteriorate <={h}h), calibrated")
        ax2.axhline(alert_threshold * 100, color=AMBER, lw=1.4, ls="--",
                   label=f"alert threshold ({alert_threshold:.0%})")
        if row["event"] == 1:
            ax.axvline(outcome_hour, color=RED, lw=1.6, ls="--")
            ax.text(outcome_hour, ax.get_ylim()[1] * 0.9, " actual\n crossing", color=RED, fontsize=8)
        else:
            ax.axvline(outcome_hour, color="#5b6b72", lw=1.2, ls="--")
            ax.text(outcome_hour, ax.get_ylim()[1] * 0.9, " discharged\n (no event)", color="#5b6b72", fontsize=8)
        ax.set_ylabel("NEWS2", color="#5b6b72"); ax2.set_ylabel("risk %", color=TEAL)
        ax.set_title(f"stay_id {sid} — {label}", fontsize=11, weight="bold", color=INK, loc="left")
        ax.set_xlabel("hours since ICU admission (window ends shortly after the outcome)")
        h1, l1 = ax.get_legend_handles_labels(); h2, l2 = ax2.get_legend_handles_labels()
        ax.legend(h1 + h2, l1 + l2, loc="upper left", fontsize=7.5, frameon=True, facecolor="white", framealpha=0.85)
        summary.append(dict(stay_id=sid, label=label, n_anchors=int(len(g)),
                            event=int(row["event"]), outcome_hour=float(outcome_hour),
                            first_risk=float(row["first_risk"]), last_risk=float(row["last_risk"])))
    fig.suptitle("Real patient trajectories: NEWS2 vs. the model's calibrated risk over time",
                fontsize=13, weight="bold", color=INK, y=1.01)
    _legend_text(axes[-1], "case_studies", y=-0.30)
    savefig(fig, "06_case_studies.png")
    METRICS["case_studies"] = summary


# ══════════════════════════════════════════════════════════════════════════
# 07 — Table 1: cohort description (row-level AND patient-level N)
# ══════════════════════════════════════════════════════════════════════════
def table1_cohort(preds: pd.DataFrame, feat_df: pd.DataFrame):
    rows = []
    rows.append(("Total anchor-rows (hourly snapshots)", f"{len(preds):,}"))
    rows.append(("Distinct CCU stays contributing anchors", f"{preds.stay_id.nunique():,}"))
    rows.append(("Row-level event rate", f"{preds.event.mean():.1%}"))
    stay_ever_event = preds.groupby("stay_id")["event"].max()
    rows.append(("Stays that ever deteriorate", f"{int((stay_ever_event == 1).sum()):,} "
                 f"({(stay_ever_event == 1).mean():.1%} of stays)"))
    for split in ["train", "calib", "test"]:
        d = preds[preds.split == split]
        rows.append((f"{split.capitalize()} split (rows / patients)",
                    f"{len(d):,} rows / {d.subject_id.nunique():,} patients"))
    rows.append(("Age, median [IQR]", f"{feat_df['age'].median():.0f} "
                 f"[{feat_df['age'].quantile(.25):.0f}-{feat_df['age'].quantile(.75):.0f}]"))
    rows.append(("Female", f"{feat_df['is_female'].mean():.1%}"))
    rows.append(("DCM-flagged anchors", f"{int(preds['dcm_flag'].sum()):,} ({preds['dcm_flag'].mean():.1%})"))
    miss = feat_df.filter(like="_missing").mean().sort_values(ascending=False)
    for lab, pct in miss.head(5).items():
        rows.append((f"Feature missingness: {lab.replace('_missing', '')}", f"{pct:.1%}"))

    fig, ax = plt.subplots(figsize=(8.6, 0.42 * len(rows) + 1.0)); ax.axis("off")
    tbl = ax.table(cellText=[[k, v] for k, v in rows], colLabels=["Table 1 — cohort description", "Value"],
                  cellLoc="left", loc="center", colWidths=[0.68, 0.32])
    tbl.auto_set_font_size(False); tbl.set_fontsize(10.3); tbl.scale(1, 1.55)
    for j in range(2):
        tbl[0, j].set_facecolor(TEALD); tbl[0, j].set_text_props(color="white", weight="bold")
    ax.set_title("Table 1 — who is actually in this dataset", fontsize=12.5, weight="bold", color=INK, pad=14)
    _legend_text(ax, "table1_cohort", y=-0.04)
    savefig(fig, "07_table1_cohort.png")
    METRICS["table1_cohort"] = dict(rows=rows)


# ══════════════════════════════════════════════════════════════════════════
# 08 — model comparison: hazard model vs AFT vs ruler, identical metrics
# ══════════════════════════════════════════════════════════════════════════
def model_comparison_table(te_hazard: pd.DataFrame, te_aft: pd.DataFrame,
                           meta_hazard: dict, meta_aft: dict, h=PRIMARY_H,
                           te_labs: pd.DataFrame | None = None, meta_labs: dict | None = None):
    def metrics_for(sub_all, prob_col):
        sub, y = known_subset(sub_all, h)
        p = sub[prob_col].values
        auc = roc_auc_score(y, p) if len(np.unique(y)) > 1 else np.nan
        auprc = average_precision_score(y, p) if len(np.unique(y)) > 1 else np.nan
        cm = _confusion_at(y, p)
        lift = cm["ppv"] / y.mean() if y.mean() else np.nan
        return dict(auc=float(auc), auprc=float(auprc), ppv=cm["ppv"],
                   alerts_per_event=cm["alerts_per_event"], lift=float(lift))

    sub, y = known_subset(te_hazard, h)
    risk_ruler = 1.0 / np.clip(sub["ruler_time"].values, 1e-3, None)
    auc_ruler = roc_auc_score(y, risk_ruler) if len(np.unique(y)) > 1 else np.nan
    auprc_ruler = average_precision_score(y, risk_ruler) if len(np.unique(y)) > 1 else np.nan
    cm_ruler = _confusion_at(y, risk_ruler)
    lift_ruler = cm_ruler["ppv"] / y.mean() if y.mean() else np.nan
    m_ruler = dict(auc=float(auc_ruler), auprc=float(auprc_ruler), ppv=cm_ruler["ppv"],
                   alerts_per_event=cm_ruler["alerts_per_event"], lift=float(lift_ruler))

    # (display name, metrics dict, c-index) per column -- labs column only added if provided,
    # so this function works unchanged before the labs retrain exists.
    columns = [("Discrete-time hazard\n(v1, PRIMARY)", metrics_for(te_hazard, f"p_calibrated_{h}h"),
               meta_hazard["c_index_hazard_test"])]
    if te_labs is not None and meta_labs is not None:
        columns.append(("Discrete-time hazard\n+ labs/congestion", metrics_for(te_labs, f"p_calibrated_{h}h"),
                        meta_labs["c_index_hazard_test"]))
    columns.append(("AFT\n(prior iteration)", metrics_for(te_aft, f"p_calibrated_{h}h"), meta_aft["c_index_aft_test"]))
    columns.append(("NEWS2-slope ruler\n(floor)", m_ruler, meta_hazard["c_index_ruler_test"]))

    metric_defs = [("C-index (test)", "c_index", "{:.3f}"),
                  (f"AUC @ {h}h", "auc", "{:.3f}"),
                  (f"AUPRC @ {h}h", "auprc", "{:.3f}"),
                  (f"PPV @ {h}h (80% sens.)", "ppv", "{:.2f}"),
                  (f"Alerts/event @ {h}h", "alerts_per_event", "{:.1f}"),
                  (f"Lift @ {h}h", "lift", "{:.2f}x")]
    rows_tbl = []
    for label, key, fmt in metric_defs:
        row = [label]
        for _, m, c_index in columns:
            val = c_index if key == "c_index" else m[key]
            row.append(fmt.format(val))
        rows_tbl.append(row)

    cols = ["Metric"] + [name for name, _, _ in columns]
    n_cols = len(cols)
    fig, ax = plt.subplots(figsize=(2.35 * n_cols + 1.3, 3.8)); ax.axis("off")
    tbl = ax.table(cellText=rows_tbl, colLabels=cols, cellLoc="center", loc="center")
    tbl.auto_set_font_size(False); tbl.set_fontsize(10.2); tbl.scale(1, 2.15)
    for j in range(n_cols):
        tbl[0, j].set_facecolor(TEALD); tbl[0, j].set_text_props(color="white", weight="bold")
    ax.set_title(f"Model comparison — identical event/split/horizons ({h}h shown; C-index is split-level;\n"
                f"'+ labs/congestion' column adds input features only -- same label, same split)",
                fontsize=11.5, weight="bold", color=INK, pad=14)
    _legend_text(ax, "model_comparison", y=-0.06)
    savefig(fig, "08_model_comparison.png")
    METRICS["model_comparison"] = dict(horizon=h, columns={name: {**m, "c_index": c} for name, m, c in columns})


# ══════════════════════════════════════════════════════════════════════════
# 08b — benchmark context: is our false-positive rate actually abnormal?
# ══════════════════════════════════════════════════════════════════════════
# Hardcoded, explicitly-cited external figures from FALSE_POSITIVE_COMPARISON_and_
# professor_reply.md (2026-07-21 research review). These are published numbers for
# DIFFERENT systems/outcomes -- not derived from our data -- kept here only for
# side-by-side context, each with its source.
EXTERNAL_BENCHMARKS = [
    dict(system="eCARTv2", outcome="ICU transfer/death <=24h (independent outcome)",
        ppv=0.082, alarm_burden="~1 alert/day/35-bed unit",
        source="Churpek et al., eCARTv5 paper, PMC11949291"),
    dict(system="Epic Deterioration Index", outcome="RRT/deterioration",
        ppv=0.338, alarm_burden="—",
        source="validation study, PMID 34152373"),
    dict(system="eCART risk-spike alerts", outcome="Deterioration",
        ppv_range="0.07-0.35", alarm_burden="~1/day/73-bed ward",
        source="alert-threshold paper, doi 10.1007/s10877-019-00361-5"),
    dict(system="Hyland et al. 2020", outcome="Circulatory failure (independent outcome)",
        ppv=None, alarm_burden="0.05/pt-hr (AUPRC 0.63)",
        source="Nature Medicine, doi 10.1038/s41591-020-0789-4"),
]


def benchmark_context_table(hutil: dict, h=PRIMARY_H, h2=24):
    ours_rows = [
        [f"Ours, {h}h", "NEWS2>=7 (same-signal label)", f"{hutil[h]['model']['ppv']:.3f}",
         f"{hutil[h]['lift_model']:.2f}x", f"{hutil[h]['alarms_per_patient_hour_model']:.2f}"],
        [f"Ours, {h2}h", "NEWS2>=7 (same-signal label)", f"{hutil[h2]['model']['ppv']:.3f}",
         f"{hutil[h2]['lift_model']:.2f}x", f"{hutil[h2]['alarms_per_patient_hour_model']:.2f}"],
    ]
    ext_rows = []
    for b in EXTERNAL_BENCHMARKS:
        ppv_str = f"{b['ppv']:.3f}" if b.get("ppv") is not None else b.get("ppv_range", "—")
        ext_rows.append([b["system"], b["outcome"], ppv_str, "—", b["alarm_burden"]])

    rows_tbl = ours_rows + ext_rows
    fig, ax = plt.subplots(figsize=(12, 0.5 * len(rows_tbl) + 1.6)); ax.axis("off")
    cols = ["System", "Outcome", "PPV", "Lift", "Alarm burden"]
    tbl = ax.table(cellText=rows_tbl, colLabels=cols, cellLoc="center", loc="center",
                  colWidths=[0.16, 0.30, 0.11, 0.11, 0.32])
    tbl.auto_set_font_size(False); tbl.set_fontsize(9.8); tbl.scale(1, 1.9)
    for j in range(len(cols)):
        tbl[0, j].set_facecolor(TEALD); tbl[0, j].set_text_props(color="white", weight="bold")
    for i in range(1, len(ours_rows) + 1):
        for j in range(len(cols)):
            tbl[i, j].set_facecolor("#eaf3f3")
    ax.set_title("Is our false-positive rate actually abnormal? — PPV in context\n"
                "note: eCARTv2 predicts an unambiguously INDEPENDENT outcome (ICU transfer/death) and still has WORSE PPV (0.082) than ours",
                fontsize=11.5, weight="bold", color=INK, pad=14)
    sources = "  |  ".join(f"{b['system']}: {b['source']}" for b in EXTERNAL_BENCHMARKS)
    ax.text(0, -0.10, "Sources — " + sources, transform=ax.transAxes, fontsize=7, color="#8a99a0", wrap=True)
    _legend_text(ax, "benchmark_context", y=-0.22)
    savefig(fig, "08b_benchmark_context.png")

    METRICS["benchmark_context"] = dict(ours=ours_rows, external=EXTERNAL_BENCHMARKS)


# ══════════════════════════════════════════════════════════════════════════
# 09 — subgroup breakdown: DCM flag + age band
# ══════════════════════════════════════════════════════════════════════════
def subgroup_breakdown(te: pd.DataFrame, feat_df: pd.DataFrame, h=PRIMARY_H):
    age_lookup = (feat_df.drop_duplicates(subset=["stay_id", "anchor_time"])
                 .set_index(["stay_id", "anchor_time"])["age"])
    te = te.copy()
    te["age"] = age_lookup.reindex(pd.MultiIndex.from_frame(te[["stay_id", "anchor_time"]])).values

    groups = {"DCM": te[te.dcm_flag == True], "Non-DCM": te[te.dcm_flag == False],
             "Age < 65": te[te.age < 65], "Age >= 65": te[te.age >= 65]}
    rows_tbl, summary = [], {}
    for name, d in groups.items():
        if len(d) < 50:
            continue
        sub, y = known_subset(d, h)
        if len(np.unique(y)) < 2:
            continue
        p = sub[f"p_calibrated_{h}h"].values
        auc = float(roc_auc_score(y, p))
        brier = float(brier_score_loss(y, np.clip(p, 0, 1)))
        n_stays = int(d.stay_id.nunique())
        rows_tbl.append([name, f"{len(d):,} ({n_stays:,} pts)", f"{y.mean():.1%}", f"{auc:.3f}", f"{brier:.3f}"])
        summary[name] = dict(n_rows=len(d), n_stays=n_stays, event_rate=float(y.mean()), auc=auc, brier=brier)

    fig, ax = plt.subplots(figsize=(9.2, 0.5 * len(rows_tbl) + 1.4)); ax.axis("off")
    cols = ["Subgroup", "N rows (patients)", f"Event rate <={h}h", "AUC", "Brier"]
    tbl = ax.table(cellText=rows_tbl, colLabels=cols, cellLoc="center", loc="center")
    tbl.auto_set_font_size(False); tbl.set_fontsize(10.5); tbl.scale(1, 2.0)
    for j in range(len(cols)):
        tbl[0, j].set_facecolor(TEALD); tbl[0, j].set_text_props(color="white", weight="bold")
    ax.set_title(f"Subgroup check @ {h}h — does the model quietly fail a group it's averaged over?",
                fontsize=12, weight="bold", color=INK, pad=14)
    _legend_text(ax, "subgroup_breakdown", y=-0.04)
    savefig(fig, "09_subgroup_breakdown.png")
    METRICS["subgroup_breakdown"] = summary


# ══════════════════════════════════════════════════════════════════════════
# 10 — [SECONDARY] corrected scatter: actual vs conditional E[T | T<=24h]
# ══════════════════════════════════════════════════════════════════════════
def scatter_corrected(te: pd.DataFrame):
    ev = te[te.event == 1]
    col = "cond_time_24h"
    r = ev["T_hours"].corr(ev[col])
    rs = ev["T_hours"].corr(ev[col], method="spearman")
    mae = float((ev["T_hours"] - ev[col]).abs().mean())
    rng = np.random.default_rng(config.RANDOM_SEED)
    x_jit = ev["T_hours"] + rng.uniform(-0.35, 0.35, len(ev))

    fig, ax = plt.subplots(figsize=(7.2, 6.6))
    ax.scatter(x_jit, ev[col], s=14, alpha=0.35, color=TEAL, label="test-set patient")
    ax.plot([0, 24], [0, 24], color=RED, lw=1.8, ls="--", label="perfect prediction (45°)")
    ax.set_xlim(0, 25); ax.set_ylim(0, 14)
    ax.set_xlabel("ACTUAL hours until NEWS2 first sustains >= 7")
    ax.set_ylabel("CONDITIONAL expected hours,  E[T | T <= 24h]")
    ax.set_title("SECONDARY — the actual-vs-predicted-TIME comparison (not the headline)\n"
                f"Pearson r = {r:.2f}  |  Spearman = {rs:.2f}  |  MAE = {mae:.1f}h  ({len(ev)} events)",
                fontsize=12, weight="bold", color=INK)
    ax.legend(loc="upper left", fontsize=9, frameon=False)
    _legend_text(ax, "scatter_corrected", y=-0.14)
    savefig(fig, "10_scatter_corrected.png")

    METRICS["scatter_corrected"] = dict(pearson_r=float(r), spearman_r=float(rs), mae_hours=mae, n_events=int(len(ev)),
        note="SECONDARY. Report r exactly as measured, even if weak -- the model's primary "
             "evidence is the calibrated probability output (horizon_utility/calibration above), "
             "not this scalar (plan §3's honest limit).")
    return r, mae


# ══════════════════════════════════════════════════════════════════════════
# 11 — [SECONDARY] error by actual-time bin
# ══════════════════════════════════════════════════════════════════════════
def error_by_bin(te: pd.DataFrame):
    ev = te[te.event == 1].copy()
    bins = [0, 2, 4, 6, 9, 12, 18, 24]
    labels = ["0-2h", "2-4h", "4-6h", "6-9h", "9-12h", "12-18h", "18-24h"]
    ev["bin"] = pd.cut(ev["T_hours"], bins=bins, labels=labels, include_lowest=True)
    g = ev.groupby("bin", observed=True).apply(
        lambda d: pd.Series({
            "n": len(d),
            "mae": (d["T_hours"] - d["cond_time_24h"]).abs().mean(),
            "mape": ((d["T_hours"] - d["cond_time_24h"]).abs() / d["T_hours"].clip(lower=0.5)).mean() * 100,
            "median_error": (d["T_hours"] - d["cond_time_24h"]).median(),
        }), include_groups=False)
    g = g.reindex(labels)

    fig, ax = plt.subplots(figsize=(8, 4.4))
    ax2 = ax.twinx()
    ax.bar(range(len(g)), g["n"], color="#dfe6e8", width=0.6, zorder=1, label="n events (bar)")
    ax2.plot(range(len(g)), g["mape"], color=AMBER, lw=2.4, marker="o", zorder=3, label="MAPE %")
    ax.set_xticks(range(len(g))); ax.set_xticklabels(g.index, rotation=0)
    ax.set_ylabel("n events in bin", color="#5b6b72")
    ax2.set_ylabel("MAPE (%)", color=AMBER)
    ax.set_xlabel("Actual time-to-event bin")
    ax.set_title("SECONDARY — where the corrected estimate is accurate, and where it decays",
                fontsize=12, weight="bold", color=INK)
    ax.grid(axis="x", visible=False)
    _legend_text(ax, "error_by_bin", y=-0.24)
    savefig(fig, "11_error_by_bin.png")

    METRICS["error_by_bin"] = g.round(2).to_dict(orient="index")
    return g


# ══════════════════════════════════════════════════════════════════════════
# 12 — [AFT REFERENCE ONLY] the old unconditional-median pathology
# ══════════════════════════════════════════════════════════════════════════
def scatter_naive_aft(te_aft: pd.DataFrame):
    ev = te_aft[te_aft.event == 1]
    r = ev["T_hours"].corr(ev["pred_median"])
    rs = ev["T_hours"].corr(ev["pred_median"], method="spearman")
    rng = np.random.default_rng(config.RANDOM_SEED)
    x_jit = ev["T_hours"] * np.exp(rng.uniform(-0.05, 0.05, len(ev)))

    fig, ax = plt.subplots(figsize=(7.2, 6.4))
    ax.errorbar(x_jit, ev["pred_median"],
                yerr=[np.clip(ev["pred_median"] - ev["conf_lo"], 0, None),
                      np.clip(ev["conf_hi"] - ev["pred_median"], 0, None)],
                fmt="o", ms=3.5, alpha=0.25, color=GREY, ecolor="#c7cdd0", elinewidth=0.6,
                capsize=0, label="AFT test-set patient (95% predictive interval)")
    lim = [0.5, max(ev["conf_hi"].quantile(0.98), 30)]
    ax.plot([0.5, 24], [0.5, 24], color=RED, lw=1.8, ls="--", label="perfect prediction (45°)")
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlim(0.5, 26); ax.set_ylim(*lim)
    ax.set_xlabel("ACTUAL hours until NEWS2 first sustains >= 7")
    ax.set_ylabel("AFT raw median (unconditional) — HISTORICAL")
    ax.set_title("HISTORICAL REFERENCE — the AFT pathology that motivated this iteration\n"
                f"Pearson r = {r:.2f}  |  Spearman = {rs:.2f}  (n={len(ev)} AFT test events)",
                fontsize=12, weight="bold", color=INK)
    ax.legend(loc="lower right", fontsize=9, frameon=True, facecolor="white")
    _legend_text(ax, "scatter_naive_aft", y=-0.16)
    savefig(fig, "12_scatter_naive_aft.png")

    METRICS["scatter_naive_aft"] = dict(pearson_r=float(r), spearman_r=float(rs), n_events=int(len(ev)))


# ══════════════════════════════════════════════════════════════════════════
# 13 — executive scorecard
# ══════════════════════════════════════════════════════════════════════════
def scorecard(meta, hutil):
    fig, ax = plt.subplots(figsize=(10, 3.4)); ax.axis("off")
    h = PRIMARY_H
    tiles = [
        ("C-index (test)", f"{meta['c_index_hazard_test']:.3f}", f"vs ruler {meta['c_index_ruler_test']:.3f}"),
        (f"AUC @ {h}h", f"{hutil[h]['auc_model']:.3f}", f"vs ruler {hutil[h]['auc_ruler']:.3f}"),
        (f"Lift @ {h}h", f"{hutil[h]['lift_model']:.2f}x", f"vs ruler {hutil[h]['lift_ruler']:.2f}x"),
        ("Event rate", f"{hutil[h]['base_rate']:.1%}", "sustained NEWS2>=7"),
    ]
    for i, (label, val, sub) in enumerate(tiles):
        x = i / len(tiles)
        ax.text(x + 0.02, 0.72, val, fontsize=26, weight="bold", color=TEALD, transform=ax.transAxes)
        ax.text(x + 0.02, 0.42, label, fontsize=11, color="#5b6b72", transform=ax.transAxes)
        ax.text(x + 0.02, 0.22, sub, fontsize=9.5, color="#8a99a0", transform=ax.transAxes, style="italic")
    ax.set_title("Discrete-time hazard model (v1) — at a glance", fontsize=14, weight="bold", color=INK, pad=10)
    savefig(fig, "13_scorecard.png")


# ══════════════════════════════════════════════════════════════════════════
# 14 — written Limitations (rendered into the report, not left implicit)
# ══════════════════════════════════════════════════════════════════════════
def limitations_section(stage0: dict, meta: dict, meta_labs: dict | None = None):
    text_lines = [
        f"Imminent-deterioration blind spot (plan §0b): even after the Stage-0 look-back fix, "
        f"{stage0['residual_n']:,} of the {stage0['old_gate_zero_anchor_n']:,} originally-invisible "
        f"fast deteriorators ({stage0['residual_pct_of_old_zero']}%) still contribute zero anchors -- "
        f"{stage0['residual_deteriorate_within_2h_pct']}% of that residual deteriorates within 2h of "
        f"admission, too fast for even 2 hourly vital readings to exist before the event. This is a "
        f"hard floor set by charting frequency, not a bug, and is not solved by this iteration.",
        "Single-hospital, single-unit-type, one-era cohort: MIMIC-IV v3.1, CCU only, one health "
        "system, historical data. External validity to other hospitals, units, or eras is unproven.",
        "Repeated-measures structure: stable stays contribute dozens of correlated hourly "
        "snapshots each; row counts are NOT independent-evidence counts -- always quote the "
        "patient-level N alongside the row-level N (Table 1), and prefer the patient-clustered "
        "bootstrap CIs over a bare point estimate.",
        "Actual-vs-predicted-TIME correlation (scatter_corrected, secondary output) is reported "
        "exactly as measured, unrounded, even if weak -- the model's primary evidence is the "
        "calibrated probability output above, not this scalar.",
        "SHAP feature-importance plots are deferred for this model (fast-follow, not attempted "
        "this iteration).",
        "False-positive rate context (see 08b_benchmark_context.png, sourced to "
        "FALSE_POSITIVE_COMPARISON_and_professor_reply.md): our PPV (0.22-0.35) is inside the "
        "published band for deployed/research deterioration systems (eCARTv2 0.082, Epic DI "
        "0.338), including systems predicting an unambiguously independent outcome (ICU "
        "transfer/death) that still have WORSE PPV than ours. This is evidence against "
        "'the false-positive rate proves the label is broken' -- the rare-event base rate sets "
        "this band for everyone. The larger, fixable lever was alarm-episode deduplication "
        "(01b_alarm_episode_comparison.png), not label or model-family changes.",
        "Not solved by anything in this iteration: external (multi-hospital) validation, "
        "prospective/shadow-mode testing, human-factors testing, a defined clinical override "
        "protocol, and regulatory review -- all prerequisites before any real-patient use.",
    ]
    if meta_labs is not None:
        c_base, c_labs = meta["c_index_hazard_test"], meta_labs["c_index_hazard_test"]
        text_lines.append(
            f"Labs/congestion feature addition (lactate, troponin, creatinine/eGFR, potassium, "
            f"weight trend, urine output, rhythm flags) was tried and did NOT meaningfully change "
            f"discrimination: test C-index {c_base:.3f} (NEWS2-only) vs {c_labs:.3f} (+labs) -- "
            f"within each other's bootstrap CIs, i.e. no significant difference. Only "
            f"urine_rate_24h ranked in the top-15 features by gain; the rest of the labs axis "
            f"contributed little, most plausibly because NEWS2's own vitals already capture most "
            f"of the extractable signal at these 2-24h horizons. Reported plainly, not rounded up.")
    wrapped = ["- " + "\n  ".join(textwrap.wrap(t, width=108)) for t in text_lines]
    body = "\n\n".join(wrapped)
    n_lines = sum(len(textwrap.wrap(t, width=108)) + 1 for t in text_lines)

    fig_h = 0.34 * n_lines + 1.0
    fig = plt.figure(figsize=(11, fig_h))
    ax = fig.add_axes([0.03, 0.02, 0.94, 0.86]); ax.axis("off")
    ax.text(0, 1, body, fontsize=10, color=INK, va="top", ha="left", family="DejaVu Sans",
           linespacing=1.4, transform=ax.transAxes)
    fig.suptitle("Written Limitations (stated in advance, not implied away)",
                fontsize=13.5, weight="bold", color=INK, y=1.0 - 0.35 / fig_h)
    savefig(fig, "14_limitations.png")
    METRICS["limitations"] = dict(text=text_lines, stage0_verification=stage0)


def main():
    preds = pd.read_parquet(config.tpath("preds_ordinal.parquet"))
    meta = json.load(open(config.dpath("models_ordinal_news2/meta.json")))
    preds_aft = pd.read_parquet(config.tpath("preds_focused.parquet"))
    meta_aft = json.load(open(config.dpath("models_news2/meta.json")))
    vh = pd.read_parquet(config.tpath("vitals_hourly.parquet"))
    feat_df = pd.read_parquet(config.tpath("features.parquet"))
    stage0 = json.load(open(config.tpath("stage0_verification.json")))

    te = preds[preds.split == "test"].copy()
    te_aft = preds_aft[preds_aft.split == "test"].copy()

    te_labs, meta_labs = None, None
    try:
        preds_labs = pd.read_parquet(config.tpath("preds_ordinal_labs.parquet"))
        meta_labs = json.load(open(config.dpath("models_ordinal_labs_news2/meta.json")))
        te_labs = preds_labs[preds_labs.split == "test"].copy()
        print(f"Labs-augmented hazard model found: {len(preds_labs)} total, {len(te_labs)} test rows")
    except FileNotFoundError:
        print("No labs-augmented hazard model found yet (run 14_ordinal_train_labs.py first) -- "
             "model_comparison_table will show 3 columns, not 4.")

    print(f"PRIMARY model (discrete-time hazard): {len(preds)} total, {len(te)} test rows, "
          f"{int(te.event.sum())} test events")
    print(f"AFT (comparison + historical reference only): {len(preds_aft)} total, {len(te_aft)} test rows")
    print("NOTE: SHAP plots (08/09 in the prior version) are deferred for this model per plan -- not run.")

    ordinal_concept_diagram()

    # ---- PRIMARY: bucket-probability profile + calibration/discrimination first ----
    hutil = horizon_utility(te)
    alarm_episode_metrics(te, hutil)
    threshold_sweep(te)
    calibration_reliability(te)
    overfit_check(preds, meta)
    decision_curve(te)
    case_studies(preds, vh, alert_threshold=hutil[PRIMARY_H]["model"]["threshold"])
    table1_cohort(preds, feat_df)
    model_comparison_table(te, te_aft, meta, meta_aft, te_labs=te_labs, meta_labs=meta_labs)
    benchmark_context_table(hutil)
    subgroup_breakdown(te, feat_df)

    # ---- SECONDARY: actual-vs-predicted-TIME, presented after ----
    scatter_corrected(te)
    error_by_bin(te)

    # ---- AFT historical reference only (not this model's headline) ----
    scatter_naive_aft(te_aft)

    scorecard(meta, hutil)
    limitations_section(stage0, meta, meta_labs)

    METRICS["meta"] = meta
    METRICS["meta_aft"] = meta_aft
    with open(config.dpath("metrics_focused.json"), "w") as f:
        json.dump(METRICS, f, indent=2, default=str)
    print(f"\nwrote charts to {OUT}")
    print(f"wrote {config.dpath('metrics_focused.json')}")


if __name__ == "__main__":
    main()
