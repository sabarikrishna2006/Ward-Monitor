"""
Stage 08 — Single-model diagnostics (the meeting deliverable).

ONE model (AFT-full). No comparison framing. Answers the professor's asks:
  1. Scatter: predicted median time vs actual time-to-event, with 45-degree line
     -> honestly shows the raw median is not a usable countdown (flattening cloud).
  2. Reframe that works: the model's RISK RANK vs actual time  (does higher risk
     -> sooner event?), and risk separation for "deteriorates within 12h".
  3. Actionable-horizon metrics (<=6h / <=12h / <=24h): AUC, sensitivity, PPV,
     false-alarms-per-event -> the numbers to quote, each defined in the caption.
  4. Reliability: observed deterioration rate by predicted-risk decile.

Every plot has an honest, self-explanatory title. Writes PNGs to data/charts/diag_*.
Run: py -3 08_diagnostics.py
"""
from __future__ import annotations
import os
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np, pandas as pd
from sklearn.metrics import roc_auc_score, roc_curve
import config

OUT = config.dpath("charts"); os.makedirs(OUT, exist_ok=True)
TEAL="#2A6F77"; TEALD="#215a61"; GREY="#9AA5AD"; AMBER="#C8862B"; RED="#B4453C"; GREEN="#2E7D57"; INK="#1c2b30"
plt.rcParams.update({"font.family":"DejaVu Sans","font.size":11,"axes.edgecolor":"#5b6b72",
    "axes.linewidth":.8,"axes.grid":True,"grid.color":"#e9edee","axes.axisbelow":True,"figure.dpi":150})

df = pd.read_parquet(config.dpath("preds_test.parquet")).copy()
df["risk"] = 1.0/np.clip(df["pred_median"],1e-3,None)
df["risk_pct"] = df["risk"].rank(pct=True)*100
ev = df[df.event==1]
HMAX = config.HMAX_H


def plot_scatter():
    fig, ax = plt.subplots(figsize=(6.6,6))
    within = ev["T_hours"]<=12
    ax.scatter(ev.loc[~within,"T_hours"], ev.loc[~within,"pred_median"], s=10, alpha=.35,
               color=GREY, label="event after 12h")
    ax.scatter(ev.loc[within,"T_hours"], ev.loc[within,"pred_median"], s=12, alpha=.5,
               color=TEAL, label="event within 12h")
    lim=[.5, 1300]
    ax.plot([.5,24],[.5,24], color=RED, lw=1.6, ls="--", label="perfect prediction (45°)")
    ax.set_xscale("log"); ax.set_yscale("log"); ax.set_xlim(.5,26); ax.set_ylim(lim)
    ax.axhline(24, color=AMBER, lw=1, ls=":"); ax.text(.6,27,"most predictions sit far ABOVE the line",color=INK,fontsize=9)
    r = ev["T_hours"].corr(ev["pred_median"]); rs = ev["T_hours"].corr(ev["pred_median"],method="spearman")
    ax.set_xlabel("ACTUAL hours until deterioration"); ax.set_ylabel("PREDICTED median hours (raw model)")
    ax.set_title("Raw predicted TIME is not a usable countdown\n"
                 f"weak tracking: Pearson r={r:.2f}, Spearman={rs:.2f}", fontsize=12, weight="bold", color=INK)
    ax.legend(loc="lower right", fontsize=9, frameon=True, facecolor="white")
    fig.tight_layout(); fig.savefig(os.path.join(OUT,"diag_scatter_time.png"), bbox_inches="tight"); plt.close(fig)


def plot_rank_vs_actual():
    """The reframe: does higher risk -> sooner event? (rank works even though time doesn't)"""
    fig, ax = plt.subplots(figsize=(6.6,4.4))
    ax.scatter(ev["T_hours"], ev["risk_pct"], s=10, alpha=.35, color=TEAL)
    # binned median trend
    bins = np.arange(0,25,2); ev2=ev.copy(); ev2["b"]=pd.cut(ev2["T_hours"],bins)
    tr = ev2.groupby("b", observed=True)["risk_pct"].median()
    xs=[b.mid for b in tr.index]
    ax.plot(xs, tr.values, color=TEALD, lw=2.4, marker="o", label="median risk-percentile")
    ax.set_xlabel("ACTUAL hours until deterioration"); ax.set_ylabel("model risk percentile (0–100)")
    ax.set_title("Sooner deteriorations get HIGHER risk scores\n(the ranking is the usable signal)",
                 fontsize=12, weight="bold", color=INK)
    ax.legend(fontsize=9, frameon=False); ax.set_ylim(0,100)
    fig.tight_layout(); fig.savefig(os.path.join(OUT,"diag_rank_vs_actual.png"), bbox_inches="tight"); plt.close(fig)


def plot_separation():
    fig, ax = plt.subplots(figsize=(6.6,4)); H=12
    y = (df.event==1)&(df.T_hours<=H)
    bins=np.linspace(0,df["risk_pct"].max(),36)
    ax.hist(df.loc[~y,"risk_pct"], bins=bins, density=True, color=GREY, alpha=.75, label=f"did NOT deteriorate in {H}h")
    ax.hist(df.loc[y,"risk_pct"], bins=bins, density=True, color=TEAL, alpha=.8, label=f"deteriorated within {H}h")
    ax.set_xlabel("model risk percentile"); ax.set_ylabel("density"); ax.legend(fontsize=9, frameon=False)
    ax.set_title(f"Risk score separates who deteriorates within {H}h", fontsize=12, weight="bold", color=INK)
    fig.tight_layout(); fig.savefig(os.path.join(OUT,"diag_separation.png"), bbox_inches="tight"); plt.close(fig)


def plot_reliability():
    fig, ax = plt.subplots(figsize=(6.2,4.4)); H=12
    y=((df.event==1)&(df.T_hours<=H)).astype(int).values
    dec=pd.qcut(df["risk"],10,labels=False,duplicates="drop")
    obs=pd.Series(y).groupby(dec).mean()
    ax.bar(range(len(obs)), obs.values*100, color=TEAL, width=.72)
    for i,v in enumerate(obs.values): ax.text(i, v*100+.4, f"{v*100:.0f}%", ha="center", fontsize=9, color=INK)
    ax.set_xlabel("predicted-risk decile  (0 = lowest risk, 9 = highest)")
    ax.set_ylabel(f"% who actually deteriorated within {H}h")
    ax.set_title("Higher predicted risk → higher real deterioration rate\n(monotonic = ranking is trustworthy)",
                 fontsize=12, weight="bold", color=INK)
    ax.grid(axis="x", visible=False)
    fig.tight_layout(); fig.savefig(os.path.join(OUT,"diag_reliability.png"), bbox_inches="tight"); plt.close(fig)


def plot_horizon_metrics():
    rows=[]
    for H in [6,12,24]:
        y=((df.event==1)&(df.T_hours<=H)).astype(int).values
        auc=roc_auc_score(y, df["risk"].values)
        thr=np.quantile(df["risk"].values[y==1],0.2); pred=df["risk"].values>=thr
        tp=int((pred&(y==1)).sum()); fp=int((pred&(y==0)).sum()); fn=int((~pred&(y==1)).sum())
        tn=int((~pred&(y==0)).sum())
        rows.append(dict(H=H, npos=int(y.sum()), base=y.mean(), auc=auc,
                         sens=tp/(tp+fn), spec=tn/(tn+fp), ppv=tp/(tp+fp), fpe=(tp+fp)/tp))
    m=pd.DataFrame(rows)
    fig, ax = plt.subplots(figsize=(9.2,3.0)); ax.axis("off")
    cols=["Horizon","Events\n(base rate)","AUC","Sensitivity","Specificity","PPV","Alerts\nper event"]
    tbl=[[f"≤ {r.H} h", f"{r.npos}  ({r.base:.0%})", f"{r.auc:.3f}", f"{r.sens:.0%}",
          f"{r.spec:.0%}", f"{r.ppv:.2f}", f"{r.fpe:.1f}"] for r in m.itertuples()]
    t=ax.table(cellText=tbl, colLabels=cols, cellLoc="center", loc="center",
               colWidths=[0.11,0.18,0.11,0.15,0.15,0.10,0.14])
    t.auto_set_font_size(False); t.set_fontsize(10.5); t.scale(1,2.0)
    for j in range(len(cols)):
        t[0,j].set_facecolor(TEALD); t[0,j].set_text_props(color="white", weight="bold")
    ax.set_title("Performance inside an actionable horizon  (operating point = 80% sensitivity)",
                 fontsize=12, weight="bold", color=INK, pad=18)
    fig.tight_layout(); fig.savefig(os.path.join(OUT,"diag_horizon_metrics.png"), bbox_inches="tight"); plt.close(fig)
    return m


if __name__=="__main__":
    plot_scatter(); plot_rank_vs_actual(); plot_separation(); plot_reliability()
    m=plot_horizon_metrics()
    print("wrote diag_*.png to", OUT)
    print("\nHorizon metrics (also rendered as an image):")
    print(m.round(3).to_string(index=False))
