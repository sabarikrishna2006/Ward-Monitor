"""
deck_plots.py — generate every chart embedded in the presentation deck.

All values are hard-coded from RESULTS_2026-07-30.md so the deck is reproducible
without re-running the pipeline. Each block names its source metric.

Style: dark background matching the deck theme, large fonts for projection,
no chart junk.

Run: PYTHONUTF8=1 py -3 deck_plots.py     ->  writes data/deck_charts/*.png
"""
from __future__ import annotations

import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "deck_charts")
os.makedirs(OUT, exist_ok=True)

BG = "#0f172a"
CARD = "#1e293b"
INK = "#f8fafc"
MUTED = "#94a3b8"
CYAN = "#38bdf8"
GOLD = "#fbbf24"
GREEN = "#34d399"
RED = "#f87171"
VIOLET = "#a78bfa"

plt.rcParams.update({
    "figure.facecolor": BG, "axes.facecolor": BG, "savefig.facecolor": BG,
    "text.color": INK, "axes.labelcolor": INK, "axes.edgecolor": MUTED,
    "xtick.color": MUTED, "ytick.color": MUTED, "grid.color": "#334155",
    "font.size": 13, "axes.titlesize": 15, "axes.titleweight": "bold",
    "axes.spines.top": False, "axes.spines.right": False,
    "legend.frameon": False, "figure.autolayout": True,
})


def save(fig, name):
    p = os.path.join(OUT, name)
    fig.savefig(p, dpi=170, bbox_inches="tight")
    plt.close(fig)
    print("  wrote", name)
    return p


# ══════════════════════════════════════════════════════════════════════════
# 1. Episode-gap curve  [26_fp_reduction_stack, NEWS2 target @12h]
# ══════════════════════════════════════════════════════════════════════════
def gap_curve():
    gap = [1, 2, 4, 8, 12]
    eps = [3467, 2069, 1754, 1513, 1394]
    ppv = [0.3098, 0.3311, 0.3683, 0.4111, 0.4455]
    rec = [0.9673] * 5
    fig, ax1 = plt.subplots(figsize=(9.2, 4.6))
    ax1.bar(range(len(gap)), eps, color=CARD, edgecolor=MUTED, width=0.55,
            label="Alert episodes")
    ax1.set_xticks(range(len(gap)))
    ax1.set_xticklabels([f"{g}h" for g in gap])
    ax1.set_xlabel("Episode-gap parameter  (hours between alerts that still count as one alarm)")
    ax1.set_ylabel("Alert episodes", color=MUTED)
    ax1.set_ylim(0, 4000)
    for i, v in enumerate(eps):
        ax1.text(i, v + 90, f"{v:,}", ha="center", color=MUTED, fontsize=11)
    ax2 = ax1.twinx()
    ax2.plot(range(len(gap)), ppv, "-o", color=GOLD, lw=2.6, ms=8, label="Episode PPV")
    ax2.plot(range(len(gap)), rec, "-s", color=GREEN, lw=2.6, ms=7, label="Patient recall")
    for i, v in enumerate(ppv):
        ax2.annotate(f"{v:.3f}", (i, v), textcoords="offset points", xytext=(0, 11),
                     ha="center", color=GOLD, fontsize=11, fontweight="bold")
    ax2.annotate("Patient recall is IDENTICAL at every value: 0.9673",
                 (2, 0.9673), textcoords="offset points", xytext=(0, -26),
                 ha="center", color=GREEN, fontsize=11, fontweight="bold")
    ax2.set_ylabel("Episode PPV  /  Patient recall")
    ax2.set_ylim(0.25, 1.05)
    ax2.spines["right"].set_visible(True)
    ax1.set_title("Merging alerts changes the COUNT, never the DETECTION", color=INK)
    h1, l1 = ax1.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax1.legend(h1 + h2, l1 + l2, loc="lower left", fontsize=11)
    ax1.grid(axis="y", alpha=0.25)
    return save(fig, "gap_curve.png")


# ══════════════════════════════════════════════════════════════════════════
# 2. Sensitivity operating curve  [NEWS2 @12h, base rate 0.1204 fixed]
# ══════════════════════════════════════════════════════════════════════════
def sens_curve():
    sens = [80, 70, 60, 50, 40, 30, 20]
    ppv = [0.331, 0.357, 0.390, 0.423, 0.460, 0.510, 0.578]
    lift = [2.750, 2.963, 3.241, 3.515, 3.820, 4.237, 4.800]
    rec = [0.967, 0.932, 0.882, 0.822, 0.746, 0.618, 0.494]
    fig, ax1 = plt.subplots(figsize=(9.2, 4.6))
    ax1.plot(sens, ppv, "-o", color=GOLD, lw=2.8, ms=8, label="Episode PPV")
    ax1.plot(sens, rec, "-s", color=GREEN, lw=2.8, ms=7, label="Patient recall")
    ax1.set_xlabel("Target sensitivity used to set the alert threshold  (%)")
    ax1.set_ylabel("Episode PPV  /  Patient recall")
    ax1.invert_xaxis()
    ax1.set_ylim(0.2, 1.05)
    ax2 = ax1.twinx()
    ax2.plot(sens, lift, "--^", color=CYAN, lw=2.4, ms=7, label="Episode LIFT")
    ax2.set_ylabel("Episode LIFT  (PPV / base rate)", color=CYAN)
    ax2.set_ylim(2.2, 5.2)
    ax2.spines["right"].set_visible(True)
    ax1.axvline(80, color=VIOLET, ls=":", lw=2)
    ax1.annotate("operating point\nchosen: 80%", (80, 0.63), color=VIOLET,
                 fontsize=11, fontweight="bold", ha="left")
    ax1.set_title("Base rate is FIXED down this curve, so rising lift is a real gain "
                  "in information per alert", color=INK, fontsize=13)
    h1, l1 = ax1.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax1.legend(h1 + h2, l1 + l2, loc="upper left", fontsize=11)
    ax1.grid(alpha=0.25)
    return save(fig, "sens_curve.png")


# ══════════════════════════════════════════════════════════════════════════
# 3. Hysteresis  [eval_core.hysteresis_alert, tau_low = 50% of tau_high]
# ══════════════════════════════════════════════════════════════════════════
def hysteresis():
    hz = ["6h", "12h", "24h"]
    e0, e1 = [2321, 2069, 1693], [1754, 1551, 1307]
    p0, p1 = [0.2714, 0.3311, 0.4341], [0.3529, 0.4101, 0.4996]
    r0, r1 = [0.9439, 0.9673, 0.9782], [0.9502, 0.9751, 0.9782]
    x = np.arange(3)
    w = 0.35
    fig, axes = plt.subplots(1, 3, figsize=(12.6, 4.2))
    for ax, (a, b, ttl, fmt) in zip(axes, [
            (e0, e1, "Alert episodes  (lower is better)", "{:,.0f}"),
            (p0, p1, "Episode PPV  (higher is better)", "{:.3f}"),
            (r0, r1, "Patient recall  (higher is better)", "{:.4f}")]):
        ax.bar(x - w / 2, a, w, label="Single threshold", color=CARD, edgecolor=MUTED)
        ax.bar(x + w / 2, b, w, label="With hysteresis latch", color=GOLD)
        for i in range(3):
            ax.text(i - w / 2, a[i], fmt.format(a[i]), ha="center", va="bottom",
                    fontsize=9.5, color=MUTED)
            ax.text(i + w / 2, b[i], fmt.format(b[i]), ha="center", va="bottom",
                    fontsize=9.5, color=GOLD, fontweight="bold")
        ax.set_xticks(x); ax.set_xticklabels(hz)
        ax.set_title(ttl, fontsize=12)
        ax.grid(axis="y", alpha=0.25)
    axes[2].set_ylim(0.90, 1.0)
    axes[0].set_ylabel("Prediction horizon")
    axes[0].legend(fontsize=10, loc="upper right")
    fig.suptitle("Hysteresis: fewer alarms, higher precision, recall unchanged or "
                 "better — replicated at all three horizons",
                 color=INK, fontsize=13.5, fontweight="bold", y=1.04)
    return save(fig, "hysteresis.png")


# ══════════════════════════════════════════════════════════════════════════
# 4. Field comparison scatter  [JAMIA 2024 review + DETERIO]
# ══════════════════════════════════════════════════════════════════════════
def field_scatter():
    pts = [
        ("MEWS++", 79, 12, CARD), ("MC-EWS", 73, 12, CARD),
        ("APPROVE", 63, 21, CARD), ("Duke XGBoost", 60, 8.5, CARD),
        ("DETERIO", 46, 22, CARD), ("Epic EDI", 39, 74, CARD),
        ("CHARTwatch\n(retrospective)", 40, 71, CARD),
        ("CHARTwatch\n(deployed)", 52, 21, RED),
        ("DEWS", 37, 4, CARD), ("HBI", 23, 31, CARD),
        ("Univ. of Washington", 41, 30, CARD),
    ]
    fig, ax = plt.subplots(figsize=(9.6, 5.2))
    for name, s, p, col in pts:
        ax.scatter(s, p, s=140, color=col, edgecolor=MUTED, zorder=3)
        ax.annotate(name, (s, p), textcoords="offset points", xytext=(8, 5),
                    fontsize=10, color=MUTED)
    ax.scatter(81, 33.1, s=460, marker="*", color=GOLD, edgecolor=INK,
               zorder=5, label="OUR MODEL @12h")
    ax.annotate("OUR MODEL\n81% sens, 33.1% PPV", (81, 33.1),
                textcoords="offset points", xytext=(-18, 20), fontsize=12,
                color=GOLD, fontweight="bold", ha="right")
    ax.axvspan(75, 85, color=CYAN, alpha=0.10)
    ax.annotate("matched-sensitivity band", (80, 62), color=CYAN, fontsize=10.5,
                ha="center")
    ax.set_xlabel("Sensitivity  (%)")
    ax.set_ylabel("Positive Predictive Value  (%)")
    ax.set_title("PPV is only meaningful WITH its sensitivity — at 79–81% "
                 "sensitivity the field achieves 12%", color=INK, fontsize=13)
    ax.set_xlim(18, 90); ax.set_ylim(0, 82)
    ax.grid(alpha=0.25)
    return save(fig, "field_scatter.png")


# ══════════════════════════════════════════════════════════════════════════
# 5. Architecture ablation with CIs
# ══════════════════════════════════════════════════════════════════════════
def architecture():
    names = ["7 independent\nXGBoost boosters",
             "1 pooled XGBoost\n+ interval feature",
             "Shared-trunk MLP\n+ 7 hazard heads",
             "Shared-trunk MLP\n+ cumulative heads"]
    c = [0.7860, 0.7853, 0.7779, 0.7767]
    lo = [0.7667, 0.7662, 0.7593, 0.7575]
    hi = [0.8061, 0.8051, 0.7974, 0.7955]
    cols = [GOLD, CYAN, VIOLET, VIOLET]
    fig, ax = plt.subplots(figsize=(9.4, 4.4))
    x = np.arange(4)
    ax.errorbar(x, c, yerr=[np.array(c) - np.array(lo), np.array(hi) - np.array(c)],
                fmt="none", ecolor=MUTED, elinewidth=2, capsize=8, zorder=2)
    ax.scatter(x, c, s=220, color=cols, edgecolor=INK, zorder=3)
    for i, v in enumerate(c):
        ax.annotate(f"{v:.4f}", (i, v), textcoords="offset points", xytext=(0, 14),
                    ha="center", fontsize=12, fontweight="bold", color=cols[i])
    ax.set_xticks(x); ax.set_xticklabels(names, fontsize=10.5)
    ax.set_ylabel("Test C-index  (95% CI)")
    ax.set_ylim(0.745, 0.815)
    ax.axhspan(0.7767, 0.7860, color=MUTED, alpha=0.10)
    ax.annotate("total spread across all four architectures: 0.0093\n"
                "confidence intervals are ~0.040 wide",
                (1.5, 0.752), ha="center", fontsize=11, color=GOLD, fontweight="bold")
    ax.set_title("Sharing parameters across intervals changes C-index by −0.0007",
                 color=INK)
    ax.grid(axis="y", alpha=0.25)
    return save(fig, "architecture.png")


# ══════════════════════════════════════════════════════════════════════════
# 6. Target x feature 2x2
# ══════════════════════════════════════════════════════════════════════════
def two_by_two():
    fig, ax = plt.subplots(figsize=(9.2, 4.6))
    x = np.arange(2)
    w = 0.34
    base = [0.8120, 0.7249]
    mw = [0.8141, 0.7974]
    ax.bar(x - w / 2, base, w, label="55 NEWS2-derived features", color=CARD,
           edgecolor=MUTED)
    ax.bar(x + w / 2, mw, w, label="Multi-window physiology features", color=GOLD)
    for i in range(2):
        ax.text(i - w / 2, base[i] + 0.004, f"{base[i]:.4f}", ha="center",
                fontsize=12, color=MUTED)
        ax.text(i + w / 2, mw[i] + 0.004, f"{mw[i]:.4f}", ha="center",
                fontsize=12, color=GOLD, fontweight="bold")
        d = mw[i] - base[i]
        ax.annotate(f"{d:+.4f}", (i, max(base[i], mw[i]) + 0.022), ha="center",
                    fontsize=15, fontweight="bold",
                    color=GREEN if d > 0.01 else RED)
    ax.set_xticks(x)
    ax.set_xticklabels(["NEWS2 ≥ 7 target", "Escalation-of-care target"], fontsize=13)
    ax.set_ylabel("AUC @12h")
    ax.set_ylim(0.68, 0.87)
    ax.legend(fontsize=11, loc="lower right")
    ax.set_title("The SAME features are worth 35× more on the escalation target",
                 color=INK)
    ax.grid(axis="y", alpha=0.25)
    return save(fig, "two_by_two.png")


# ══════════════════════════════════════════════════════════════════════════
# 7. Feature-family gain
# ══════════════════════════════════════════════════════════════════════════
def features():
    fam = ["Renal (creatinine/BUN/eGFR)", "Systolic BP", "Anion gap",
           "Measurement staleness", "Lactate", "Heart rate", "Shock index",
           "Infusion titration", "SpO2", "Respiratory rate", "MAP (measured)",
           "Neuro / GCS", "HCO3", "NEWS2 score"]
    val = [8.5, 7.7, 7.6, 6.1, 6.0, 4.6, 4.5, 4.4, 4.3, 3.8, 3.4, 3.1, 2.8, 2.5]
    newf = [1, 0, 1, 1, 1, 0, 1, 1, 0, 0, 1, 1, 1, 0]
    fig, ax = plt.subplots(figsize=(9.4, 5.2))
    y = np.arange(len(fam))[::-1]
    cols = [GOLD if n else CYAN for n in newf]
    ax.barh(y, val, color=cols, edgecolor=MUTED, height=0.68)
    for yy, v in zip(y, val):
        ax.text(v + 0.12, yy, f"{v:.1f}%", va="center", fontsize=11, color=INK)
    ax.set_yticks(y); ax.set_yticklabels(fam, fontsize=11)
    ax.set_xlabel("Share of total model gain  (%)")
    ax.set_xlim(0, 10.2)
    ax.set_title("Gain by variable family — labs 37% vs vitals 32.5%, matching "
                 "published ICU findings", color=INK, fontsize=13)
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color=GOLD, label="Newly extracted this iteration"),
                       Patch(color=CYAN, label="Already available")],
              fontsize=10.5, loc="lower right")
    ax.grid(axis="x", alpha=0.25)
    return save(fig, "features.png")


# ══════════════════════════════════════════════════════════════════════════
# 8. Lookback-window contribution
# ══════════════════════════════════════════════════════════════════════════
def windows():
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11.6, 4.1))
    w = ["2h window\n(acute change)", "6h window\n(current state)",
         "12h window\n(personal baseline)"]
    v = [8.3, 12.0, 13.7]
    n = [21, 45, 48]
    a1.bar(range(3), v, color=[CYAN, GOLD, GREEN], edgecolor=MUTED, width=0.6)
    for i, (vv, nn) in enumerate(zip(v, n)):
        a1.text(i, vv + 0.25, f"{vv:.1f}%", ha="center", fontsize=13,
                fontweight="bold", color=INK)
        a1.text(i, 0.5, f"{nn} features", ha="center", fontsize=10, color=BG,
                fontweight="bold")
    a1.set_xticks(range(3)); a1.set_xticklabels(w, fontsize=10.5)
    a1.set_ylabel("Share of total gain (%)")
    a1.set_ylim(0, 16)
    a1.set_title("Every window earns its place —\nthe longest carries the most",
                 fontsize=12)
    a1.grid(axis="y", alpha=0.25)

    a2.pie([47.3, 52.7], labels=["Window / trend /\nacceleration features",
                                 "Static current\nvalues"],
           colors=[GOLD, CARD], autopct="%1.1f%%", startangle=110,
           textprops={"color": INK, "fontsize": 11.5},
           wedgeprops={"edgecolor": MUTED, "linewidth": 1.2})
    a2.set_title("Nearly half of all model gain comes\nfrom time-series dynamics",
                 fontsize=12)
    return save(fig, "windows.png")


# ══════════════════════════════════════════════════════════════════════════
# 9. Precision@K worklist re-ranking
# ══════════════════════════════════════════════════════════════════════════
def precision_at_k():
    k = [10, 25, 50, 100]
    prec = [0.5704, 0.4307, 0.2842, 0.1935]
    n = [135, 339, 679, 1359]
    fig, ax = plt.subplots(figsize=(9.2, 4.5))
    ax.plot(k, prec, "-o", color=GOLD, lw=3, ms=11)
    ax.axhline(0.1935, color=MUTED, ls="--", lw=1.8)
    ax.annotate("unranked: every alert treated equally  (0.1935)", (62, 0.205),
                fontsize=11, color=MUTED)
    for kk, pp, nn in zip(k, prec, n):
        ax.annotate(f"{pp:.3f}\n({nn} alerts)", (kk, pp),
                    textcoords="offset points", xytext=(0, 16), ha="center",
                    fontsize=11.5, fontweight="bold", color=GOLD)
    ax.set_xlabel("Top K% of the alert worklist, ranked by predicted severity")
    ax.set_ylabel("Precision  (fraction that precede a real event)")
    ax.set_ylim(0.10, 0.68)
    ax.set_xticks(k); ax.set_xticklabels([f"{x}%" for x in k])
    ax.set_title("Re-ranking the worklist: 57% precision on the first 135 alerts — "
                 "nothing suppressed", color=INK, fontsize=13)
    ax.grid(alpha=0.25)
    return save(fig, "precision_at_k.png")


# ══════════════════════════════════════════════════════════════════════════
# 10. Conformal tiers
# ══════════════════════════════════════════════════════════════════════════
def conformal():
    a = [0.05, 0.10, 0.20]
    page = [8.2, 15.0, 26.2]
    watch = [67.9, 53.9, 26.1]
    clear = [23.9, 31.1, 47.8]
    ppv = [0.2643, 0.2078, 0.1602]
    rec = [0.6953, 0.8197, 0.8884]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12.0, 4.3))
    x = np.arange(3)
    a1.bar(x, page, color=RED, label="PAGE  {1} — page a clinician")
    a1.bar(x, watch, bottom=page, color=GOLD,
           label="WATCH  {0,1} — worklist only, never suppressed")
    a1.bar(x, clear, bottom=np.array(page) + np.array(watch), color=CARD,
           edgecolor=MUTED, label="CLEAR  {0} — no alert")
    for i in range(3):
        a1.text(i, page[i] / 2, f"{page[i]:.1f}%", ha="center", fontsize=10.5,
                color=INK, fontweight="bold")
        a1.text(i, page[i] + watch[i] / 2, f"{watch[i]:.1f}%", ha="center",
                fontsize=10.5, color=BG, fontweight="bold")
    a1.set_xticks(x); a1.set_xticklabels([f"α = {v}" for v in a])
    a1.set_ylabel("Share of patient-hours (%)")
    a1.set_title("α sets the abstention rate directly\n(coverage guarantee = 1 − α)",
                 fontsize=12)
    a1.legend(fontsize=9.5, loc="lower center", bbox_to_anchor=(0.5, -0.42))

    a2.plot(a, ppv, "-o", color=GOLD, lw=2.8, ms=9, label="PAGE-tier PPV")
    a2.plot(a, rec, "-s", color=GREEN, lw=2.8, ms=8, label="PAGE-tier patient recall")
    for xx, yy in zip(a, ppv):
        a2.annotate(f"{yy:.3f}", (xx, yy), textcoords="offset points",
                    xytext=(0, 12), ha="center", fontsize=11, color=GOLD)
    for xx, yy in zip(a, rec):
        a2.annotate(f"{yy:.3f}", (xx, yy), textcoords="offset points",
                    xytext=(0, -20), ha="center", fontsize=11, color=GREEN)
    a2.set_xlabel("α  (1 − coverage guarantee)")
    a2.set_ylabel("PAGE-tier PPV  /  recall")
    a2.set_xticks(a)
    a2.set_ylim(0.10, 1.0)
    a2.set_title("Choosing α trades PAGE precision\nagainst PAGE recall explicitly",
                 fontsize=12)
    a2.legend(fontsize=10.5, loc="center right")
    a2.grid(alpha=0.25)
    return save(fig, "conformal.png")


# ══════════════════════════════════════════════════════════════════════════
# 11. Calibration reliability curve  [cell A @12h]
# ══════════════════════════════════════════════════════════════════════════
def calibration():
    # decile means from the test split, cell A @12h (base rate 0.1204)
    pred = [0.012, 0.028, 0.045, 0.064, 0.087, 0.114, 0.150, 0.201, 0.283, 0.463]
    obs = [0.016, 0.031, 0.041, 0.070, 0.084, 0.121, 0.146, 0.212, 0.291, 0.470]
    fig, ax = plt.subplots(figsize=(6.4, 5.0))
    ax.plot([0, 0.5], [0, 0.5], "--", color=MUTED, lw=1.8, label="perfect calibration")
    ax.plot(pred, obs, "-o", color=GOLD, lw=2.6, ms=9, label="observed (test deciles)")
    ax.set_xlabel("Predicted probability of deterioration")
    ax.set_ylabel("Observed event frequency")
    ax.set_title("Predicted probabilities can be\nread at face value", fontsize=13)
    ax.set_xlim(0, 0.5); ax.set_ylim(0, 0.5)
    ax.legend(fontsize=11, loc="upper left")
    ax.grid(alpha=0.25)
    ax.annotate("calibration slope 1.007\nintercept 0.125\nECE 0.013",
                (0.30, 0.10), fontsize=12, color=GREEN, fontweight="bold")
    return save(fig, "calibration.png")


# ══════════════════════════════════════════════════════════════════════════
# 12. Escalation operating curve (24h) with and without hysteresis
# ══════════════════════════════════════════════════════════════════════════
def esc_operating():
    sens = [80, 70, 60]
    single = [0.1935, 0.2254, 0.2564]
    hyst = [0.2588, 0.2926, 0.3210]
    rec_s = [0.9619, 0.9110, 0.8602]
    rec_h = [0.9703, 0.9153, 0.8644]
    fig, ax = plt.subplots(figsize=(9.2, 4.5))
    x = np.arange(3)
    w = 0.34
    ax.bar(x - w / 2, single, w, label="Single threshold", color=CARD, edgecolor=MUTED)
    ax.bar(x + w / 2, hyst, w, label="With hysteresis latch", color=GOLD)
    for i in range(3):
        ax.text(i - w / 2, single[i] + 0.006, f"{single[i]:.3f}", ha="center",
                fontsize=11, color=MUTED)
        ax.text(i + w / 2, hyst[i] + 0.006, f"{hyst[i]:.3f}", ha="center",
                fontsize=11.5, color=GOLD, fontweight="bold")
        ax.text(i + w / 2, hyst[i] / 2, f"recall\n{rec_h[i]:.3f}", ha="center",
                fontsize=9.5, color=BG, fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels([f"{s}% sensitivity" for s in sens], fontsize=12)
    ax.set_ylabel("Episode PPV  (24h horizon)")
    ax.set_ylim(0, 0.40)
    ax.legend(fontsize=11, loc="upper left")
    ax.set_title("Escalation model: the operating point and the latch are "
                 "independent levers", color=INK, fontsize=13)
    ax.grid(axis="y", alpha=0.25)
    return save(fig, "esc_operating.png")


def main():
    print(f"writing charts to {OUT}")
    for f in (gap_curve, sens_curve, hysteresis, field_scatter, architecture,
              two_by_two, features, windows, precision_at_k, conformal,
              calibration, esc_operating):
        f()
    print("done")


if __name__ == "__main__":
    main()
