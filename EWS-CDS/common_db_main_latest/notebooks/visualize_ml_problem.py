"""
EWS ML Problem Formulation — Visualization Script
==================================================
Generates 5 publication-quality charts from live CCU demo patient data.

Charts produced in notebooks/charts/:
  chart_1_patient_trajectory.png   — NEWS2 trajectory over 12h (critical vs stable)
  chart_2_sliding_window.png       — ML training example construction diagram
  chart_3_stage_transitions.png    — 3x3 stage-transition heatmap
  chart_4_feature_space.png        — Feature engineering overview
  chart_5_auroc_ladder.png         — Baseline AUROC comparison ladder

Run from:  common_db_main_latest/
  py notebooks/visualize_ml_problem.py
"""

import sys
import os
import warnings
import numpy as np
import pandas as pd
import yaml

import matplotlib
matplotlib.use("Agg")                       # non-interactive backend (safe for scripts)
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.gridspec as gridspec
from matplotlib.patches import FancyBboxPatch
import seaborn as sns
from sqlalchemy import text

warnings.filterwarnings("ignore")

# ── Path setup ─────────────────────────────────────────────────────────────────
HERE     = os.path.dirname(os.path.abspath(__file__))
ROOT     = os.path.dirname(HERE)
BACKEND  = os.path.join(ROOT, "sabari_project", "backend")
YAML_PATH = os.path.join(BACKEND, "rules", "news2_thresholds.yaml")
OUT_DIR  = os.path.join(HERE, "charts")
os.makedirs(OUT_DIR, exist_ok=True)

sys.path.insert(0, BACKEND)

# ── Global plot style ──────────────────────────────────────────────────────────
plt.rcParams.update({
    "font.family":          "DejaVu Sans",
    "font.size":            11,
    "axes.titlesize":       14,
    "axes.titleweight":     "bold",
    "axes.labelsize":       12,
    "axes.labelweight":     "normal",
    "figure.facecolor":     "white",
    "axes.facecolor":       "#fafafa",
    "axes.grid":            True,
    "grid.alpha":           0.35,
    "grid.linestyle":       "--",
    "axes.spines.top":      False,
    "axes.spines.right":    False,
    "axes.spines.left":     True,
    "axes.spines.bottom":   True,
    "legend.framealpha":    0.9,
    "legend.fontsize":      10,
    "xtick.labelsize":      10,
    "ytick.labelsize":      10,
    "savefig.dpi":          150,
    "savefig.bbox":         "tight",
    "savefig.facecolor":    "white",
})

# ── Clinical colour constants ─────────────────────────────────────────────────
C_NORMAL   = "#27ae60"   # green
C_MODERATE = "#e67e22"   # amber
C_CRITICAL = "#e74c3c"   # red
C_BG_NORM  = "#eafaf1"   # light green bg
C_BG_MOD   = "#fef5e7"   # light amber bg
C_BG_CRIT  = "#fdedec"   # light red bg
C_BLUE     = "#2980b9"
C_DARK     = "#2c3e50"

STAGE_COLORS  = {0: C_NORMAL, 1: C_MODERATE, 2: C_CRITICAL}
STAGE_LABELS  = {0: "Normal (0–4)", 1: "Moderate (5–6)", 2: "Critical (≥ 7)"}
STAGE_BG      = {0: C_BG_NORM,   1: C_BG_MOD,     2: C_BG_CRIT}

# ── NEWS2 calculation (standalone, mirrors main.py logic) ─────────────────────
with open(YAML_PATH) as _f:
    _NEWS2_CFG = yaml.safe_load(_f)

def _score_range(value, bands):
    for band in bands:
        lo = band.get("min", float("-inf"))
        hi = band.get("max", float("inf"))
        if lo <= value <= hi:
            return band["score"]
    return 0

def news2_total(row):
    """Compute NEWS2 total from a DataFrame row or dict."""
    active = _NEWS2_CFG.get("active_set", "uk_news2")
    th = _NEWS2_CFG.get(active, _NEWS2_CFG.get("uk_news2", {}))
    s = 0
    rr = row.get("resp_rate") if isinstance(row, dict) else getattr(row, "resp_rate", None)
    if rr is not None and not (isinstance(rr, float) and np.isnan(rr)):
        s += _score_range(float(rr), th.get("resp_rate", []))
    spo2 = row.get("spo2") if isinstance(row, dict) else getattr(row, "spo2", None)
    if spo2 is not None and not (isinstance(spo2, float) and np.isnan(spo2)):
        s += _score_range(float(spo2), th.get("spo2_scale1", []))
    aor = row.get("air_or_oxygen") if isinstance(row, dict) else getattr(row, "air_or_oxygen", None)
    if aor == "Oxygen":
        s += 2
    sbp = row.get("sbp") if isinstance(row, dict) else getattr(row, "sbp", None)
    if sbp is not None and not (isinstance(sbp, float) and np.isnan(sbp)):
        s += _score_range(float(sbp), th.get("sbp", []))
    hr = row.get("heart_rate") if isinstance(row, dict) else getattr(row, "heart_rate", None)
    if hr is not None and not (isinstance(hr, float) and np.isnan(hr)):
        s += _score_range(float(hr), th.get("heart_rate", []))
    con = row.get("consciousness") if isinstance(row, dict) else getattr(row, "consciousness", None)
    if con and con != "A":
        s += 3
    temp = row.get("temperature") if isinstance(row, dict) else getattr(row, "temperature", None)
    if temp is not None and not (isinstance(temp, float) and np.isnan(temp)):
        s += _score_range(float(temp), th.get("temperature", []))
    return s

def get_stage(score):
    if score >= 7: return 2
    if score >= 5: return 1
    return 0

# ── Try importing database; fall back to synthetic generation if unavailable ──
_USE_SYNTHETIC = False
try:
    from database import engine
    from sqlalchemy import text as _sql_text
except Exception:
    _USE_SYNTHETIC = True

# ── Patient metadata (for labels in charts) ───────────────────────────────────
PATIENT_META = {
    91001: {"name": "Ramesh Iyer",   "scenario": "critical_high", "label": "Critical — DCM HFrEF (EF 25%)"},
    91002: {"name": "Lakshmi Menon", "scenario": "critical_dl",   "label": "Critical — DCM + AF, Pulm. Oedema"},
    91003: {"name": "Govind Rao",    "scenario": "warning_rr",    "label": "Moderate — Ischaemic CM, HF Flare"},
    91004: {"name": "Fatima Begum",  "scenario": "warning_spo2",  "label": "Moderate — Post-Partum CM, NYHA III"},
    91005: {"name": "Joseph Thomas", "scenario": "stable_watch",  "label": "Normal — DCM, VT Risk (step-down)"},
    91006: {"name": "Anjali Nair",   "scenario": "stable_meds",   "label": "Normal — DCM NYHA II (controlled)"},
}
DEMO_IDS = list(PATIENT_META.keys())

# ── Vitals profiles mirroring build_demo_db.py VITALS_PROFILE ─────────────────
# (base_hr, base_rr, base_spo2, base_sbp, base_dbp, base_temp, consciousness, air_or_oxygen)
_VITALS_PROFILE = {
    "critical_high": (115, 24, 90, 86,  54,  37.2, "A", "Oxygen"),
    "critical_dl":   (118, 26, 88, 82,  50,  37.8, "A", "Oxygen"),
    "warning_rr":    (98,  22, 92, 100, 62,  37.0, "A", "Air"),
    "warning_spo2":  (96,  20, 91, 104, 64,  36.9, "A", "Air"),
    "stable_watch":  (88,  17, 95, 112, 72,  37.0, "A", "Air"),
    "stable_meds":   (82,  16, 96, 118, 74,  36.9, "A", "Air"),
}

def _generate_synthetic_vitals():
    """Reproduce the exact trajectory logic from build_demo_db.gen_vitals_trajectory."""
    import random
    from datetime import datetime, timedelta
    rng = random.Random(42)   # fixed seed for reproducibility

    rows = []
    now = datetime.now()
    for pid, meta in PATIENT_META.items():
        profile_key = meta["scenario"]
        base_hr, base_rr, base_spo2, base_sbp, base_dbp, base_temp, consciousness, air_ox = \
            _VITALS_PROFILE[profile_key]

        for h in range(12, 0, -1):
            hour_key = now - timedelta(hours=h) + timedelta(minutes=rng.randint(-10, 10))
            trend = 0
            if profile_key.startswith("critical") and h <= 4:
                trend = (5 - h) * 0.5

            hr   = max(38,  min(145, int(base_hr   + trend * 3  + rng.gauss(0, 4))))
            rr   = max(8,   min(32,  int(base_rr   + trend      + rng.gauss(0, 1.5))))
            spo2 = max(82,  min(99,  round(base_spo2 - trend * 0.5 + rng.gauss(0, 1), 1)))
            sbp  = max(65,  min(210, int(base_sbp  - trend * 2  + rng.gauss(0, 6))))
            dbp  = max(40,  min(120, int(base_dbp  - trend      + rng.gauss(0, 4))))
            temp = max(35.0, min(40.5, round(base_temp + rng.gauss(0, 0.15), 1)))

            rows.append({
                "hadm_id": pid, "chart_time": hour_key,
                "heart_rate": hr, "resp_rate": rr, "spo2": spo2,
                "sbp": sbp, "dbp": dbp, "temperature": temp,
                "consciousness": consciousness, "air_or_oxygen": air_ox,
            })
    return rows

# ── Load vitals: try Cloud SQL first, fall back to synthetic ──────────────────
def load_vitals_df():
    rows = None

    if not _USE_SYNTHETIC:
        try:
            q = _sql_text("""
                SELECT hadm_id, chart_time,
                       heart_rate, resp_rate, spo2, sbp, dbp,
                       temperature, consciousness, air_or_oxygen
                FROM ews_vitals_timeseries
                WHERE hadm_id = ANY(:ids)
                ORDER BY hadm_id, chart_time
            """)
            with engine.connect() as conn:
                db_rows = conn.execute(q, {"ids": DEMO_IDS}).mappings().fetchall()
            if db_rows:
                rows = [dict(r) for r in db_rows]
                print("      [DB] Connected to Cloud SQL — using live demo patient data.")
        except Exception as e:
            print(f"      [DB] Cloud SQL unavailable ({type(e).__name__}). Using synthetic fallback.")

    if not rows:
        print("      [Synthetic] Generating vitals from build_demo_db profiles (deterministic seed=42).")
        rows = _generate_synthetic_vitals()

    df = pd.DataFrame(rows)
    df["chart_time"] = pd.to_datetime(df["chart_time"])
    df = df.sort_values(["hadm_id", "chart_time"]).reset_index(drop=True)
    df["news2"]  = df.apply(news2_total, axis=1)
    df["stage"]  = df["news2"].apply(get_stage)
    df["hours"]  = df.groupby("hadm_id")["chart_time"].transform(
        lambda x: (x - x.min()).dt.total_seconds() / 3600
    )
    return df


# ══════════════════════════════════════════════════════════════════════════════
# CHART 1 — Patient Vital Signs Trajectory with NEWS2 Stage Coloring
# ══════════════════════════════════════════════════════════════════════════════
def chart1_patient_trajectory(df):
    """Two-panel chart: one critical patient vs one stable patient."""
    pair = [91001, 91006]   # critical_high vs stable_meds
    titles = [
        "Patient A — Critical Stage (DCM, Decompensated HF)",
        "Patient B — Normal Stage (DCM, NYHA II, Controlled)",
    ]

    fig, axes = plt.subplots(1, 2, figsize=(14, 5), sharey=False)
    fig.suptitle(
        "Chart 1: NEWS2 Trajectory Over 12 Hours — Why We Need Trend-Aware ML",
        fontsize=15, fontweight="bold", y=1.02
    )

    for ax, pid, title in zip(axes, pair, titles):
        sub = df[df["hadm_id"] == pid].copy()
        hours  = sub["hours"].values
        scores = sub["news2"].values
        stages = sub["stage"].values

        # Stage background zones
        ax.axhspan(0,   4.5, color=C_BG_NORM, alpha=0.8, label="Normal zone (0–4)")
        ax.axhspan(4.5, 6.5, color=C_BG_MOD,  alpha=0.8, label="Moderate zone (5–6)")
        ax.axhspan(6.5, 16,  color=C_BG_CRIT, alpha=0.8, label="Critical zone (≥7)")

        # Threshold lines
        ax.axhline(y=5, color=C_MODERATE, linewidth=1.2, linestyle=":", alpha=0.7)
        ax.axhline(y=7, color=C_CRITICAL, linewidth=1.2, linestyle=":", alpha=0.7)

        # NEWS2 score line (colored segments by stage)
        for i in range(len(hours) - 1):
            col = STAGE_COLORS[stages[i]]
            ax.plot(hours[i:i+2], scores[i:i+2], color=col, linewidth=2.8, solid_capstyle="round")

        # Scatter points colored by stage
        for h, s, st in zip(hours, scores, stages):
            ax.scatter(h, s, color=STAGE_COLORS[st], s=70, zorder=5, edgecolors="white", linewidths=1.2)

        # Prediction window annotation (show a 6h horizon arrow at hour 6)
        if len(hours) >= 6:
            mid_h = hours[len(hours) // 2]
            ax.annotate(
                "",
                xy=(mid_h + 6, scores[len(hours) // 2]),
                xytext=(mid_h, scores[len(hours) // 2]),
                arrowprops=dict(
                    arrowstyle="->", color=C_DARK, lw=1.5,
                    connectionstyle="arc3,rad=0.15"
                ),
            )
            ax.text(
                mid_h + 3, scores[len(hours) // 2] + 0.5,
                "6h prediction\nhorizon →",
                fontsize=8.5, color=C_DARK, ha="center",
                bbox=dict(boxstyle="round,pad=0.2", facecolor="white", alpha=0.8)
            )

        ax.set_title(title, fontsize=12, fontweight="bold", pad=10)
        ax.set_xlabel("Hours Since Admission", fontsize=11)
        ax.set_ylabel("NEWS2 Score", fontsize=11)
        ax.set_ylim(-0.5, 16)
        ax.set_xlim(-0.3, max(hours) + 0.3 if len(hours) > 0 else 12)
        ax.set_yticks([0, 2, 4, 5, 6, 7, 9, 11, 13, 15])

        # Stage zone labels on right axis
        ax2 = ax.twinx()
        ax2.set_ylim(ax.get_ylim())
        ax2.set_yticks([2.0, 5.5, 11.0])
        ax2.set_yticklabels(["Normal", "Moderate", "Critical"],
                             fontsize=9, fontweight="bold")
        ax2.yaxis.set_tick_params(length=0)
        ax2.tick_params(axis="y", colors=C_DARK)
        for tick, color in zip(ax2.get_yticklabels(), [C_NORMAL, C_MODERATE, C_CRITICAL]):
            tick.set_color(color)
        ax2.spines["right"].set_visible(False)
        ax2.spines["top"].set_visible(False)

    # Shared legend on figure
    legend_patches = [
        mpatches.Patch(color=C_NORMAL,   label="Normal stage (NEWS2 0–4)"),
        mpatches.Patch(color=C_MODERATE, label="Moderate stage (NEWS2 5–6)"),
        mpatches.Patch(color=C_CRITICAL, label="Critical stage (NEWS2 ≥7)"),
    ]
    fig.legend(handles=legend_patches, loc="lower center", ncol=3,
               bbox_to_anchor=(0.5, -0.08), framealpha=0.9, fontsize=10)

    fig.text(
        0.5, -0.14,
        "ML Insight: NEWS2 changes over time — a static threshold misses early deterioration.\n"
        "Our model uses the last 6h of trends to predict the next 6h stage.",
        ha="center", fontsize=10, color="#555555", style="italic"
    )

    out = os.path.join(OUT_DIR, "chart_1_patient_trajectory.png")
    fig.savefig(out)
    plt.close(fig)
    print(f"  [OK]{out}")
    return out


# ══════════════════════════════════════════════════════════════════════════════
# CHART 2 — Sliding Window Construction Diagram
# ══════════════════════════════════════════════════════════════════════════════
def chart2_sliding_window():
    """Pure diagram — no patient data needed."""
    fig, ax = plt.subplots(figsize=(13, 5))
    ax.set_xlim(0, 22)
    ax.set_ylim(0, 10)
    ax.axis("off")

    fig.suptitle(
        "Chart 2: ML Training Example Construction — Sliding Window Method\n"
        "(Applied to MIMIC-IV CCU Patient Stays)",
        fontsize=14, fontweight="bold", y=1.01
    )

    # ── Timeline backbone ──
    ax.annotate("", xy=(21.5, 5), xytext=(0.5, 5),
                arrowprops=dict(arrowstyle="-|>", lw=2, color=C_DARK))
    ax.text(21.7, 5, "time", va="center", fontsize=11, color=C_DARK)

    # ── Three segments ──
    # Lookback W=6h (blue)
    lb = FancyBboxPatch((1, 3.5), 7, 3, boxstyle="round,pad=0.1",
                         facecolor="#d6eaf8", edgecolor=C_BLUE, linewidth=2.0)
    ax.add_patch(lb)
    ax.text(4.5, 5.05, "LOOKBACK WINDOW\nW = 6 hours", ha="center", va="center",
            fontsize=11, fontweight="bold", color=C_BLUE)
    ax.text(4.5, 4.1, "X_p(t)  =  vitals in [t − 6h, t]", ha="center",
            fontsize=9.5, color=C_BLUE, style="italic")

    # NOW marker
    ax.axvline(x=8, ymin=0.25, ymax=0.85, color=C_DARK, linewidth=2.5, linestyle="--")
    ax.text(8, 7.5, "t = NOW\n(prediction time)",
            ha="center", va="bottom", fontsize=10, fontweight="bold",
            color=C_DARK,
            bbox=dict(boxstyle="round,pad=0.3", facecolor="white",
                      edgecolor=C_DARK, linewidth=1.5))

    # Horizon H=6h (red)
    hz = FancyBboxPatch((8, 3.5), 7, 3, boxstyle="round,pad=0.1",
                         facecolor="#fde8e8", edgecolor=C_CRITICAL, linewidth=2.0)
    ax.add_patch(hz)
    ax.text(11.5, 5.05, "PREDICTION HORIZON\nH = 6 hours", ha="center", va="center",
            fontsize=11, fontweight="bold", color=C_CRITICAL)
    ax.text(11.5, 4.1,
            "y_p(t) = 1  if stage(NEWS2 at t+6h) > stage(NEWS2 at t)",
            ha="center", fontsize=9, color=C_CRITICAL, style="italic")

    # ── Label box ──
    lbl = FancyBboxPatch((15.5, 3.5), 5, 3, boxstyle="round,pad=0.2",
                          facecolor="#f4ecf7", edgecolor="#7d3c98", linewidth=1.8)
    ax.add_patch(lbl)
    ax.text(18, 6.2, "LABEL", ha="center", fontsize=10, fontweight="bold", color="#7d3c98")
    ax.text(18, 5.4, "y_p(t) ∈ {0, 1}", ha="center", fontsize=11,
            color="#7d3c98", fontweight="bold")
    ax.text(18, 4.6, "1 = deterioration", ha="center", fontsize=9, color="#e74c3c")
    ax.text(18, 4.0, "0 = stable / improved", ha="center", fontsize=9, color="#27ae60")

    ax.annotate("", xy=(15.5, 5), xytext=(14.9, 5),
                arrowprops=dict(arrowstyle="-|>", color="#7d3c98", lw=2.0))

    # ── Bottom annotations ──
    ax.text(4.5, 2.8, "stride = 1 hour\n→ each CCU stay yields ~90 training examples",
            ha="center", fontsize=9.5, color="#555555", style="italic")
    ax.text(11.5, 2.8, "~10–20% positive rate (stage transitions are rare)\n→ use Focal Loss, not standard BCE",
            ha="center", fontsize=9.5, color="#555555", style="italic")

    # ── Top data split note ──
    ax.text(11, 9, "70% Train  |  15% Validation  |  15% Test   (split by patient ID, not by window)",
            ha="center", fontsize=10, color=C_DARK,
            bbox=dict(boxstyle="round,pad=0.35", facecolor="#eaecee", alpha=0.8))

    out = os.path.join(OUT_DIR, "chart_2_sliding_window.png")
    fig.savefig(out)
    plt.close(fig)
    print(f"  [OK]{out}")
    return out


# ══════════════════════════════════════════════════════════════════════════════
# CHART 3 — Stage Transition Heatmap
# ══════════════════════════════════════════════════════════════════════════════
def chart3_stage_transitions(df):
    """3×3 heatmap of stage-to-stage transitions over a 6h window."""
    HORIZON_IDX = 6   # 6 readings ahead ≈ 6 hours (1 reading/hour)

    counts  = np.zeros((3, 3), dtype=int)
    n_total = 0

    for pid in DEMO_IDS:
        sub = df[df["hadm_id"] == pid].sort_values("hours").reset_index(drop=True)
        stages = sub["stage"].values
        for i in range(len(stages) - HORIZON_IDX):
            s_now    = stages[i]
            s_future = stages[i + HORIZON_IDX]
            counts[s_now][s_future] += 1
            n_total += 1

    # Normalise to percentages (row-wise is most intuitive: given current stage, where do you end up?)
    row_sums = counts.sum(axis=1, keepdims=True)
    row_sums[row_sums == 0] = 1   # avoid div-by-zero
    pct = (counts / row_sums * 100).round(1)

    stage_names = ["Normal\n(NEWS2 0–4)", "Moderate\n(NEWS2 5–6)", "Critical\n(NEWS2 ≥7)"]

    fig, (ax_heat, ax_bar) = plt.subplots(1, 2, figsize=(13, 5),
                                           gridspec_kw={"width_ratios": [1.3, 1]})
    fig.suptitle(
        "Chart 3: Stage Transition Matrix over 6h Prediction Horizon\n"
        "(Computed from CCU Demo Patients — illustrates label distribution & class imbalance)",
        fontsize=13, fontweight="bold", y=1.02
    )

    # Heatmap
    mask = np.zeros_like(pct, dtype=bool)
    annot = np.array([[f"{pct[r][c]:.1f}%\n(n={counts[r][c]})"
                        for c in range(3)] for r in range(3)])

    cmap = sns.color_palette("Reds", as_cmap=True)
    sns.heatmap(
        pct, ax=ax_heat,
        annot=annot, fmt="", cmap=cmap,
        linewidths=2, linecolor="white",
        xticklabels=stage_names, yticklabels=stage_names,
        vmin=0, vmax=100,
        cbar_kws={"label": "% of windows (row-normalised)", "shrink": 0.85},
    )

    # Highlight diagonal (stable) vs. upper triangle (deterioration)
    for r in range(3):
        ax_heat.add_patch(plt.Rectangle((r, r), 1, 1, fill=False,
                                         edgecolor="#27ae60", lw=3))
    for r in range(3):
        for c in range(3):
            if c > r:   # upper triangle = deterioration
                ax_heat.add_patch(plt.Rectangle((c, r), 1, 1, fill=False,
                                                 edgecolor="#e74c3c", lw=2.5,
                                                 linestyle="--"))

    ax_heat.set_title("Stage at t  →  Stage at t + 6h", fontsize=11, fontweight="bold")
    ax_heat.set_xlabel("Future Stage (t + 6h)",  fontsize=11)
    ax_heat.set_ylabel("Current Stage (t = now)", fontsize=11)

    # Key for diagonal vs off-diagonal
    legend_elem = [
        mpatches.Patch(facecolor="none", edgecolor="#27ae60", lw=2.5,
                       label="Diagonal: stable (majority class, y=0)"),
        mpatches.Patch(facecolor="none", edgecolor="#e74c3c", lw=2.5,
                       linestyle="dashed",
                       label="Upper triangle: deterioration (minority class, y=1)"),
    ]
    ax_heat.legend(handles=legend_elem, loc="upper left",
                   bbox_to_anchor=(0, -0.22), fontsize=9, framealpha=0.9)

    # Bar chart: label distribution across all windows
    total_stable  = int(counts[0,0] + counts[1,1] + counts[2,2])
    total_improve = int(counts[0,0]*0 + counts[1,0] + counts[2,0] + counts[2,1])
    total_worsen  = int(counts[0,1] + counts[0,2] + counts[1,2])
    totals = [total_stable, total_improve, total_worsen]
    labels_bar = ["Stable\n(y = 0)", "Improved\n(y = 0)", "Deteriorated\n(y = 1 — our target)"]
    colours_bar = [C_NORMAL, C_BLUE, C_CRITICAL]

    bars = ax_bar.barh(labels_bar, totals, color=colours_bar, height=0.5, alpha=0.85)
    for bar, val in zip(bars, totals):
        ax_bar.text(bar.get_width() + 0.3, bar.get_y() + bar.get_height() / 2,
                    f"{val}  ({val/max(n_total,1)*100:.0f}%)",
                    va="center", fontsize=10)
    ax_bar.set_title("Label Distribution\nacross all 6h windows", fontsize=11, fontweight="bold")
    ax_bar.set_xlabel("Number of training windows", fontsize=10)
    ax_bar.set_xlim(0, max(totals) * 1.35)
    ax_bar.spines["top"].set_visible(False)
    ax_bar.spines["right"].set_visible(False)
    ax_bar.set_facecolor("white")

    ax_bar.text(
        max(totals) * 0.5, -0.7,
        "Class imbalance → Focal Loss\n(not standard BCE)",
        ha="center", fontsize=9, color="#7f8c8d", style="italic",
        bbox=dict(boxstyle="round,pad=0.3", facecolor="#f8f9fa", alpha=0.8)
    )

    fig.tight_layout()
    out = os.path.join(OUT_DIR, "chart_3_stage_transitions.png")
    fig.savefig(out)
    plt.close(fig)
    print(f"  [OK]{out}")
    return out


# ══════════════════════════════════════════════════════════════════════════════
# CHART 4 — Feature Space Overview
# ══════════════════════════════════════════════════════════════════════════════
def chart4_feature_space():
    """Horizontal bar chart showing feature categories and feature counts."""
    categories = [
        ("Patient Context\n(age, gender, admission hours, ward)",         4,  "#8e44ad"),
        ("Missingness Indicators\n(was vital measured at time t?)",        5,  "#2980b9"),
        ("Derived Clinical Scores\n(NEWS2 total, NEWS2 slope over 3h)",   2,  "#1a5276"),
        ("Rolling Min / Max\n(5 vitals × 2 stats × 3 windows)",          30,  "#e67e22"),
        ("Rolling Std / Variability\n(5 vitals × 1 stat × 3 windows)",   15,  "#e74c3c"),
        ("Rolling Slope / Trend\n(5 vitals × 1 stat × 3 windows)",       15,  "#c0392b"),
        ("Rolling Mean\n(5 vitals × 1 stat × 3 windows = 1h, 3h, 6h)",  15,  "#922b21"),
        ("Last Observed Value\n(HR, SpO2, RR, SBP, Temperature)",         5,  "#2ecc71"),
    ]
    labels  = [c[0] for c in categories]
    counts  = [c[1] for c in categories]
    colours = [c[2] for c in categories]
    total   = sum(counts)

    fig, ax = plt.subplots(figsize=(12, 6))
    fig.suptitle(
        f"Chart 4: Feature Engineering — {total} Input Features per Prediction Window\n"
        "(All features computed from data available at time t — no lookahead)",
        fontsize=13, fontweight="bold", y=1.02
    )

    bars = ax.barh(labels, counts, color=colours, height=0.55, alpha=0.88)

    for bar, val in zip(bars, counts):
        ax.text(bar.get_width() + 0.3, bar.get_y() + bar.get_height() / 2,
                f"{val} features", va="center", fontsize=10, color=C_DARK)

    # Vital signs sources
    vitals = ["HR (220045)", "SpO₂ (220277)", "RR (220210)", "SBP (220179)", "Temp (223761)"]
    ax.text(
        total * 0.55, -1.0,
        "Source vitals (MIMIC-IV itemids):  " + "  ·  ".join(vitals),
        ha="center", fontsize=9, color="#555555", style="italic",
        bbox=dict(boxstyle="round,pad=0.35", facecolor="#eaecee", alpha=0.85)
    )

    # Rolling window annotation
    ax.annotate(
        "3 windows:\n1h · 3h · 6h",
        xy=(15, 4.5), xytext=(25, 4.5),
        fontsize=9.5, color="#7f8c8d",
        arrowprops=dict(arrowstyle="->", color="#7f8c8d", lw=1.2),
        bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.85)
    )

    ax.set_xlabel("Number of features", fontsize=11)
    ax.set_xlim(0, total * 1.15)
    ax.set_facecolor("white")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    # Total label
    ax.text(total * 0.98, len(categories) - 0.3,
            f"Total:  {total}  features\n(~100 is standard in eCARTv5 / clinical literature)",
            ha="right", fontsize=10.5, fontweight="bold", color=C_DARK,
            bbox=dict(boxstyle="round,pad=0.4", facecolor="#f0f3f4", alpha=0.9))

    fig.tight_layout()
    out = os.path.join(OUT_DIR, "chart_4_feature_space.png")
    fig.savefig(out)
    plt.close(fig)
    print(f"  [OK]{out}")
    return out


# ══════════════════════════════════════════════════════════════════════════════
# CHART 5 — AUROC Evaluation Ladder
# ══════════════════════════════════════════════════════════════════════════════
def chart5_auroc_ladder():
    """Horizontal bar chart: baseline ladder from literature."""
    models = [
        ("Naive — always predict 0",                  0.50,  0.50,  0.50,  "#bdc3c7"),
        ("NEWS2 threshold ≥7 (current system)",        0.77,  0.67,  0.85,  C_MODERATE),
        ("Logistic Regression on raw vitals",          0.72,  0.68,  0.76,  "#85c1e9"),
        ("XGBoost — our primary target",               0.84,  0.78,  0.89,  C_BLUE),
        ("LSTM (2-layer, temporal trends)",            0.86,  0.80,  0.91,  "#2471a3"),
        ("eCARTv5  (SOTA, 97 features, multicenter)", 0.895, 0.89,  0.90,  C_CRITICAL),
    ]

    labels  = [m[0] for m in models]
    centers = [m[1] for m in models]
    lo      = [m[1] - m[2] for m in models]
    hi      = [m[3] - m[1] for m in models]
    colours = [m[4] for m in models]

    fig, ax = plt.subplots(figsize=(12, 5.5))
    fig.suptitle(
        "Chart 5: Evaluation Framework — AUROC Baseline Ladder\n"
        "(Task: predict CCU stage worsening within next 6h; data: MIMIC-IV CCU cohort)",
        fontsize=13, fontweight="bold", y=1.02
    )

    y_pos = range(len(models))
    bars = ax.barh(list(y_pos), centers, xerr=[lo, hi], color=colours, height=0.5,
                   alpha=0.85, capsize=5, error_kw={"elinewidth": 1.5, "ecolor": "#555555"})

    # Value labels
    for i, (bar, m) in enumerate(zip(bars, models)):
        center, lo_v, hi_v = m[1], m[2], m[3]
        label_txt = f"AUROC {center:.3f}"
        if lo_v != center or hi_v != center:
            label_txt += f"  [{lo_v:.2f}–{hi_v:.2f}]"
        ax.text(hi_v + 0.004, i, label_txt,
                va="center", fontsize=9.5, color=C_DARK, fontweight="bold")

    # SOTA reference line
    ax.axvline(x=0.895, color=C_CRITICAL, linestyle="--", linewidth=1.5, alpha=0.8)
    ax.text(0.896, len(models) - 0.3, "eCARTv5 SOTA\n(Churpek 2025)",
            fontsize=8.5, color=C_CRITICAL, va="top")

    # Our target highlight
    ax.annotate(
        "← Our target ≥ 0.80\n   (beat NEWS2 threshold)",
        xy=(0.82, 3), xytext=(0.70, 3.6),
        fontsize=9, color=C_BLUE,
        arrowprops=dict(arrowstyle="->", color=C_BLUE, lw=1.3),
        bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.9)
    )

    ax.set_yticks(list(y_pos))
    ax.set_yticklabels(labels, fontsize=10.5)
    ax.set_xlabel("AUROC (Area Under ROC Curve)", fontsize=11)
    ax.set_xlim(0.40, 0.98)
    ax.set_facecolor("white")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    # Footer note
    fig.text(
        0.5, -0.06,
        "AUROC measures overall discrimination ability (1.0 = perfect, 0.5 = random).\n"
        "We also report AUPRC, Sensitivity @ 90% Specificity, and mean time-to-detection.",
        ha="center", fontsize=9, color="#555555", style="italic"
    )

    fig.tight_layout()
    out = os.path.join(OUT_DIR, "chart_5_auroc_ladder.png")
    fig.savefig(out)
    plt.close(fig)
    print(f"  [OK]{out}")
    return out


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 60)
    print("EWS ML Problem — Generating Presentation Charts")
    print("=" * 60)

    print("\n[1/5] Loading vitals from Cloud SQL (demo patients 91001-91006)...")
    df = load_vitals_df()
    print(f"      Loaded {len(df)} vital readings across {df['hadm_id'].nunique()} patients")
    print(f"      NEWS2 range: {df['news2'].min():.0f} – {df['news2'].max():.0f}")
    stage_counts = df['stage'].value_counts().sort_index()
    stage_lbl_ascii = {0: "Normal (0-4)", 1: "Moderate (5-6)", 2: "Critical (>=7)"}
    for stg, cnt in stage_counts.items():
        print(f"        Stage {stg} ({stage_lbl_ascii[stg]}): {cnt} readings")

    print("\n[2/5] Generating charts...")
    chart1_patient_trajectory(df)
    chart2_sliding_window()
    chart3_stage_transitions(df)
    chart4_feature_space()
    chart5_auroc_ladder()

    print(f"\n{'=' * 60}")
    print(f"All charts saved to:  {OUT_DIR}")
    print(f"{'=' * 60}")
    print("\nSlide mapping:")
    print("  Chart 1 -> Slide 2 (Clinical Motivation) + Slide 4 (What Is Deterioration?)")
    print("  Chart 2 -> Slide 6 (Dataset Construction)")
    print("  Chart 3 -> Slide 6 (Dataset Construction) / Slide 8 (Loss Function)")
    print("  Chart 4 -> Slide 7 (Feature Engineering)")
    print("  Chart 5 -> Slide 9 (Evaluation Framework)")
    print("\nOpen charts/ folder and drag PNGs into Google Slides or PowerPoint.")
