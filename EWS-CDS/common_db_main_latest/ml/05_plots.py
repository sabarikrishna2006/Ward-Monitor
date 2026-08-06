"""
Stage 05 — Presentation plots (PNG) for the meeting/slide deck.

Reads data/metrics.json, data/shap_summary.csv, data/preds_test.parquet,
data/anchors.parquet. Writes PNGs to data/charts/.
Run: py -3 05_plots.py
"""
from __future__ import annotations

import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import config

OUT = config.dpath("charts"); os.makedirs(OUT, exist_ok=True)
TEAL = "#2A6F77"; TEAL_L = "#5AA6AE"; GREY = "#9AA5AD"; AMBER = "#C8862B"
GREEN = "#2E7D57"; RED = "#B4453C"; INK = "#1c2b30"
plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 11, "axes.edgecolor": "#5b6b72",
    "axes.linewidth": 0.8, "axes.grid": True, "grid.color": "#e6eaec",
    "grid.linewidth": 0.8, "axes.axisbelow": True, "figure.dpi": 150,
})

M = json.load(open(config.dpath("metrics.json")))
ORDER = ["AFT-full", "AFT-news2", "Cox", "NEWS2-slope"]
NICE = {"AFT-full": "AFT (full, ours)", "AFT-news2": "AFT (NEWS2-only)",
        "Cox": "Cox PH", "NEWS2-slope": "NEWS2-slope\n(baseline)"}


def _bars(ax, labels, vals, colors, err=None, fmt="{:.2f}"):
    y = np.arange(len(labels))[::-1]
    ax.barh(y, vals, color=colors, height=0.62,
            xerr=err, error_kw=dict(ecolor="#5b6b72", elinewidth=1, capsize=3))
    ax.set_yticks(y); ax.set_yticklabels(labels)
    for yi, v in zip(y, vals):
        ax.text(v, yi, "  " + fmt.format(v), va="center", ha="left", fontsize=10, color=INK)
    ax.set_axisbelow(True); ax.grid(axis="y", visible=False)


def cindex_plot():
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 3.6), sharex=True)
    for ax, block, title in [(axes[0], "overall", "All CCU patients"),
                             (axes[1], "dcm_subcohort", "DCM subcohort")]:
        d = M[block]
        vals = [d[m]["c_index"] for m in ORDER]
        err = [[d[m]["c_index"] - d[m]["ci95"][0] for m in ORDER],
               [d[m]["ci95"][1] - d[m]["c_index"] for m in ORDER]]
        colors = [TEAL, TEAL_L, GREY, "#c2ccd0"]
        _bars(ax, [NICE[m] for m in ORDER], vals, colors, err=np.array(err))
        ax.axvline(0.5, color=RED, ls="--", lw=1, label="random (0.5)")
        ax.set_xlim(0.45, 1.0); ax.set_title(title, fontsize=12, color=INK, weight="bold")
        ax.set_xlabel("Harrell C-index (95% CI)")
    axes[0].legend(loc="lower right", fontsize=8, frameon=False)
    fig.suptitle("Discrimination — our AFT model vs baselines", fontsize=13, weight="bold", color=INK)
    fig.tight_layout(); fig.savefig(os.path.join(OUT, "cindex_comparison.png"), bbox_inches="tight")
    plt.close(fig)


def alert_plot():
    fig, ax = plt.subplots(figsize=(9, 3.4))
    ov = [M["overall"][m]["alert_burden_at_80_sens"]["alerts_per_true_event"] for m in ORDER]
    dc = [M["dcm_subcohort"][m]["alert_burden_at_80_sens"]["alerts_per_true_event"] for m in ORDER]
    y = np.arange(len(ORDER))[::-1]
    ax.barh(y + 0.19, ov, height=0.36, color=TEAL, label="All CCU")
    ax.barh(y - 0.19, dc, height=0.36, color=TEAL_L, label="DCM")
    for yi, v in zip(y + 0.19, ov):
        ax.text(v, yi, f"  {v:.2f}", va="center", fontsize=9, color=INK)
    for yi, v in zip(y - 0.19, dc):
        ax.text(v, yi, f"  {v:.2f}", va="center", fontsize=9, color=INK)
    ax.set_yticks(y); ax.set_yticklabels([NICE[m] for m in ORDER])
    ax.set_xlabel("False alarms per true event  @ 80% sensitivity   (lower = better)")
    ax.grid(axis="y", visible=False); ax.legend(frameon=False, fontsize=9)
    ax.set_title("Alert burden — the false-alarm metric", fontsize=13, weight="bold", color=INK)
    fig.tight_layout(); fig.savefig(os.path.join(OUT, "alert_burden.png"), bbox_inches="tight")
    plt.close(fig)


def shap_plot():
    imp = pd.read_csv(config.dpath("shap_summary.csv")).head(12).iloc[::-1]
    # colour by axis
    congestion = {"egfr", "urine_rate_24h", "urine_rate_6h", "rhythm_af", "rhythm_vt_vf",
                  "charlson", "nt_probnp_last", "bnp_last", "troponin_t_last", "lactate_last",
                  "sodium_last", "hemoglobin_last", "potassium_last", "weight_d24", "weight_d72",
                  "esc_weight_flag", "hfsa_weight_flag", "creatinine_last"}
    ctx = {"age", "is_female", "hours_since_adm"}
    colors = [AMBER if f in congestion else (GREY if f in ctx else TEAL) for f in imp["feature"]]
    fig, ax = plt.subplots(figsize=(9, 4.3))
    ax.barh(np.arange(len(imp)), imp["mean_abs_shap"], color=colors, height=0.7)
    ax.set_yticks(np.arange(len(imp))); ax.set_yticklabels(imp["feature"])
    ax.grid(axis="y", visible=False); ax.set_xlabel("mean |SHAP|  (impact on predicted time-to-event)")
    ax.set_title("What drives the model (SHAP)", fontsize=13, weight="bold", color=INK)
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color=TEAL, label="Acute / NEWS2 axis"),
                       Patch(color=AMBER, label="Congestion / substrate axis (DCM)"),
                       Patch(color=GREY, label="Context")], frameon=False, fontsize=9, loc="lower right")
    fig.tight_layout(); fig.savefig(os.path.join(OUT, "shap_top.png"), bbox_inches="tight")
    plt.close(fig)


def coverage_plot():
    fig, ax = plt.subplots(figsize=(5.2, 3.2))
    labels = ["Conformal\nband (ours)", "Raw AFT\nparametric"]
    vals = [M["overall"]["interval_coverage"]["conformal"],
            M["overall"]["interval_coverage"]["parametric"]]
    ax.bar(labels, vals, color=[GREEN, GREY], width=0.55)
    ax.axhline(0.90, color=RED, ls="--", lw=1.2); ax.text(1.4, 0.905, "target 0.90", color=RED, fontsize=9)
    for i, v in enumerate(vals):
        ax.text(i, v + 0.01, f"{v:.3f}", ha="center", fontsize=11, color=INK, weight="bold")
    ax.set_ylim(0, 1.05); ax.set_ylabel("5–95% interval coverage")
    ax.grid(axis="x", visible=False)
    ax.set_title("Uncertainty band is calibrated", fontsize=12, weight="bold", color=INK)
    fig.tight_layout(); fig.savefig(os.path.join(OUT, "coverage.png"), bbox_inches="tight")
    plt.close(fig)


def risk_separation_plot():
    df = pd.read_parquet(config.dpath("preds_test.parquet"))
    risk = 1.0 / np.clip(df["pred_median"].values, 1e-3, None)  # higher = sooner
    ev = df["event"].values == 1
    lo, hi = np.percentile(risk, [1, 99]); bins = np.linspace(lo, hi, 40)
    fig, ax = plt.subplots(figsize=(7.5, 3.4))
    ax.hist(np.clip(risk[~ev], lo, hi), bins=bins, color=GREY, alpha=0.75,
            density=True, label="No deterioration (censored)")
    ax.hist(np.clip(risk[ev], lo, hi), bins=bins, color=TEAL, alpha=0.75,
            density=True, label="Deterioration event")
    ax.set_xlabel("Model risk score  (1 / predicted time-to-event)")
    ax.set_ylabel("density"); ax.grid(axis="x", visible=False)
    ax.legend(frameon=False, fontsize=9)
    ax.set_title("Risk separates deteriorating vs stable patients", fontsize=12, weight="bold", color=INK)
    fig.tight_layout(); fig.savefig(os.path.join(OUT, "risk_separation.png"), bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    cindex_plot(); alert_plot(); shap_plot(); coverage_plot(); risk_separation_plot()
    print("wrote charts to", OUT)
