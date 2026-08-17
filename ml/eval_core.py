"""
eval_core.py — the corrected evaluation definitions, in one place, unit-tested.

WHY THIS FILE EXISTS. `10_focused_report.py` computes precision/recall per
ANCHOR ROW (one row = one patient-hour) and picks its alert threshold using the
TEST SET's own labels. Both are wrong, in ways that change the headline numbers:

  1. ROW-LEVEL PPV counts a stable patient with 60 charted hours as 60 separate
     chances to be a false positive, and a patient who deteriorates at hour 3 as
     3. The false-positive count is therefore dominated by long-stay stable
     patients, which is not what a clinician experiences. The clinical unit of a
     false alarm is an ALARM EPISODE — one continuous run of alerting — not a
     patient-hour.

  2. THRESHOLD FIT ON TEST. `_confusion_at` did
         thr = np.quantile(score[y == 1], 1 - sens_target)
     on the test set. That makes "80% sensitivity" true by construction on the
     very data it is reported on. The threshold must be chosen on the CALIBRATION
     split and then applied, frozen, to test — then the resulting test sensitivity
     is a real out-of-sample number (and will land NEAR, not exactly at, 80%).

Nothing here changes what the operating point MEANS (still "the threshold that
yields 80% sensitivity"). It changes where it is estimated, and what unit the
resulting counts are in.

Run the self-test:  PYTHONUTF8=1 py -3 eval_core.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from known_status import known_subset

# Two alerting hours belong to the SAME episode if they are no more than this many
# hours apart. This is the "episode deduplication" parameter: 1.0 means strictly
# consecutive charted hours; larger values tolerate a dip below threshold or a
# missing anchor without splitting one clinical episode into two.
# The choice is deliberate and its sensitivity is reported by
# episode_gap_sensitivity() rather than being asserted as obviously correct.
EPISODE_GAP_H = 2.0


# ══════════════════════════════════════════════════════════════════════════
# 1. Threshold selection — fit on calibration, applied frozen to test
# ══════════════════════════════════════════════════════════════════════════
def select_threshold(scores: np.ndarray, y: np.ndarray, sens_target: float = 0.80) -> float:
    """Threshold achieving `sens_target` sensitivity ON THE DATA PASSED IN.

        thr = quantile( scores among true events , 1 - sens_target )

    Read it as: "put exactly sens_target of the true events above the line."
    Call this with the CALIBRATION split only. Calling it with test data
    reproduces the circularity this module exists to remove.

    Returns +inf if there are no positives (nothing can be calibrated).
    """
    pos = np.asarray(scores)[np.asarray(y) == 1]
    if len(pos) == 0:
        return float("inf")
    return float(np.quantile(pos, 1.0 - sens_target))


def row_confusion(y: np.ndarray, scores: np.ndarray, thr: float) -> dict:
    """Row-level (per patient-hour) confusion at a FIXED, externally-supplied
    threshold. Kept so the old unit can be shown side by side with the episode
    unit — not because it is the right unit for a false-alarm claim.

        sensitivity = TP/(TP+FN)      recall / true-positive rate
        specificity = TN/(TN+FP)      NOT 1-PPV
        PPV         = TP/(TP+FP)      = precision
    """
    y = np.asarray(y).astype(int)
    pred = np.asarray(scores) >= thr
    tp = int((pred & (y == 1)).sum()); fp = int((pred & (y == 0)).sum())
    fn = int((~pred & (y == 1)).sum()); tn = int((~pred & (y == 0)).sum())
    return dict(
        threshold=float(thr), tp=tp, fp=fp, fn=fn, tn=tn,
        sensitivity=tp / (tp + fn) if (tp + fn) else float("nan"),
        specificity=tn / (tn + fp) if (tn + fp) else float("nan"),
        ppv=tp / (tp + fp) if (tp + fp) else float("nan"),
    )


def lift(ppv: float, base_rate: float) -> float:
    """lift = PPV / base_rate.

    1.0x means the alert carries no information over picking a patient at random;
    the ceiling is 1/base_rate. THIS is the metric to compare across two different
    labels, because a looser label raises PPV and base_rate together — lift divides
    the prevalence back out. A no-skill model scores 1.0x under any label.
    """
    return float(ppv / base_rate) if base_rate else float("nan")


# ══════════════════════════════════════════════════════════════════════════
# 1b. Hysteresis — a dual-threshold (Schmitt trigger) alert rule
# ══════════════════════════════════════════════════════════════════════════
def hysteresis_alert(df: pd.DataFrame, score_col: str, thr_high: float, thr_low: float,
                     patient_col: str = "stay_id", time_col: str = "anchor_time") -> np.ndarray:
    """Alert turns ON when score >= thr_high and stays ON until score < thr_low.

    WHY THIS IS DIFFERENT FROM THE EPISODE GAP -- the distinction matters and is easy
    to blur. With a single threshold, a patient hovering at the boundary flickers on
    and off, producing several episodes out of measurement noise rather than out of
    new physiology. The episode gap merges those *after the fact, inside the metric*.
    Hysteresis stops the second alarm being generated *at all*. One is accounting,
    the other is behaviour -- and a real deployed system needs the behaviour, because
    the clinician sees the alarms, not the metric.

    This is a Schmitt trigger, the same mechanism that stops a thermostat cycling
    every thirty seconds.

    KEY PROPERTY, asserted in the self-test: hysteresis can never reduce patient
    recall. It only changes when an alarm ENDS, never whether the first one fires --
    the ON condition is identical to the single-threshold rule. Contrast persistence
    voting (k-of-m), which changes the ON condition and was measured to lose 58% of
    patients having only 1-2 pre-event observations.

    thr_low == thr_high reproduces single-threshold behaviour exactly.
    """
    assert thr_low <= thr_high, "thr_low must be <= thr_high"
    d = df[[patient_col, time_col]].copy()
    d["_s"] = np.asarray(df[score_col].values, dtype=float)
    order = d.sort_values([patient_col, time_col]).index
    s = d.loc[order, "_s"].to_numpy()
    pid = d.loc[order, patient_col].to_numpy()

    on = s >= thr_high
    stay_on = s >= thr_low                      # not yet below the release threshold
    out = np.zeros(len(s), dtype=bool)
    state = False
    prev = None
    for i in range(len(s)):
        if pid[i] != prev:                      # new patient -> reset the latch
            state = False
            prev = pid[i]
        if on[i]:
            state = True
        elif not stay_on[i]:
            state = False
        out[i] = state
    return pd.Series(out, index=order).reindex(df.index).to_numpy()


# ══════════════════════════════════════════════════════════════════════════
# 2. Alarm episodes — the clinical unit of a false alarm
# ══════════════════════════════════════════════════════════════════════════
def alert_episodes(df: pd.DataFrame, score_col: str, thr: float, y: np.ndarray,
                   patient_col: str = "stay_id", time_col: str = "anchor_time",
                   gap_h: float = EPISODE_GAP_H) -> pd.DataFrame:
    """Collapse each patient's alerting hours into alarm EPISODES.

    An episode is a maximal run of alerting hours for one patient in which no two
    successive alerts are more than `gap_h` apart. Unlike the previous
    implementation (a positional `shift(1)`), the break test is on TIMESTAMPS, so a
    missing anchor hour does not silently split one episode into two.

    One row per episode:
      t_start, t_end     first/last alerting hour in the episode
      n_alerts           how many alerting hours it collapsed
      y_any              1 if ANY anchor in the episode has label 1 at this horizon,
                         i.e. the episode correctly anticipated the event -> a TRUE
                         episode. 0 -> a FALSE episode.
      lead_time_h        T_hours at the episode's FIRST alerting hour = how much
                         warning this episode actually bought. Only meaningful when
                         the patient has an event.
      event              the anchor-level event flag (does the patient deteriorate
                         at all within follow-up), used to decompose false episodes.
    """
    d = df[[patient_col, time_col, "T_hours", "event"]].copy()
    d["y"] = np.asarray(y).astype(int)
    d["alert"] = np.asarray(df[score_col].values) >= thr
    d = d[d["alert"]].sort_values([patient_col, time_col]).reset_index(drop=True)
    if len(d) == 0:
        return pd.DataFrame(columns=[patient_col, "ep_id", "t_start", "t_end",
                                     "n_alerts", "y_any", "lead_time_h", "event"])

    t = pd.to_datetime(d[time_col])
    gap = t.groupby(d[patient_col]).diff().dt.total_seconds() / 3600.0
    new_ep = gap.isna() | (gap > gap_h + 1e-9)          # NaN = first alert for this patient
    d["ep_id"] = new_ep.groupby(d[patient_col]).cumsum().astype(int)

    ep = (d.groupby([patient_col, "ep_id"])
            .agg(t_start=(time_col, "min"), t_end=(time_col, "max"),
                 n_alerts=("y", "size"), y_any=("y", "max"),
                 lead_time_h=("T_hours", "first"), event=("event", "max"))
            .reset_index())
    return ep


def episode_metrics(df: pd.DataFrame, score_col: str, thr: float, y: np.ndarray,
                    gap_h: float = EPISODE_GAP_H) -> dict:
    """Episode-level and patient-level performance at a fixed threshold.

      episode_ppv       = TRUE episodes / ALL episodes
                          "of the alarms a nurse actually responds to, what
                           fraction were followed by a real event within h"
      patient_recall    = deteriorating patients with >=1 alerting hour inside the
                          h before their event / all deteriorating patients
                          "what fraction of deteriorating patients did the system
                           warn about at least once" — the number that matters
                          clinically, and NOT the same as row-level sensitivity
      episodes_per_patient_day = alarm burden. One anchor = one patient-hour, so
                          the denominator is n_known_anchors / 24.
      median_lead_time_h = median warning bought by a TRUE episode.
    """
    ep = alert_episodes(df, score_col, thr, y, gap_h=gap_h)
    y = np.asarray(y).astype(int)
    n_known = len(df)

    n_ep = len(ep)
    n_true_ep = int(ep["y_any"].sum()) if n_ep else 0

    ev_stays = set(df.loc[y == 1, "stay_id"].unique())
    alerting = df[(np.asarray(df[score_col].values) >= thr) & (y == 1)]
    caught = set(alerting["stay_id"].unique())

    true_ep = ep[ep["y_any"] == 1] if n_ep else ep
    return dict(
        threshold=float(thr),
        gap_h=float(gap_h),
        n_episodes=n_ep,
        n_true_episodes=n_true_ep,
        n_false_episodes=n_ep - n_true_ep,
        episode_ppv=n_true_ep / n_ep if n_ep else float("nan"),
        n_event_patients=len(ev_stays),
        n_event_patients_caught=len(caught),
        patient_recall=len(caught) / len(ev_stays) if ev_stays else float("nan"),
        episodes_per_patient_day=n_ep / (n_known / 24.0) if n_known else float("nan"),
        mean_alerts_per_episode=float(ep["n_alerts"].mean()) if n_ep else float("nan"),
        median_lead_time_h=float(true_ep["lead_time_h"].median()) if len(true_ep) else float("nan"),
    )


def episode_gap_sensitivity(df: pd.DataFrame, score_col: str, thr: float, y: np.ndarray,
                            gaps=(1.0, 2.0, 4.0, 8.0)) -> list[dict]:
    """How much does the episode definition itself drive the numbers?

    The professor's instruction was to "define this carefully" rather than adopt a
    constant. This reports episode count and episode-PPV across several gap
    tolerances so the choice of EPISODE_GAP_H is shown to be a deliberate,
    sensitivity-checked decision instead of an unexamined default.
    """
    out = []
    for g in gaps:
        m = episode_metrics(df, score_col, thr, y, gap_h=g)
        out.append(dict(gap_h=g, n_episodes=m["n_episodes"],
                        episode_ppv=m["episode_ppv"],
                        patient_recall=m["patient_recall"],
                        episodes_per_patient_day=m["episodes_per_patient_day"]))
    return out


# ══════════════════════════════════════════════════════════════════════════
# 3. What is a "false" episode actually firing on?
# ══════════════════════════════════════════════════════════════════════════
def decompose_false_episodes(ep: pd.DataFrame, profile: pd.DataFrame) -> dict:
    """Split FALSE episodes by what the patient's NEWS2 record actually shows.

    `profile` is verify_label_v2.excursion_profile() output: one row per stay with
    `n_hi` (hours spent at NEWS2>=7) and `longest_pos_run`.

      never_high        the patient never reached NEWS2>=7 at any point in the
                        entire stay -> an unambiguous false alarm
      transient_high    reached NEWS2>=7 but never for 2 consecutive hours -> the
                        label-v2 group; under v1 the model was scored wrong for
                        seeing something that was really there
      sustained_outside the patient DID sustain NEWS2>=7, just not inside this
                        prediction window

    This is the honest answer to "your model is 80-90% false positives": measured
    under label v1 at 12h, only ~27% of alert episodes fire on a patient who shows
    no NEWS2 deterioration whatsoever.
    """
    if len(ep) == 0:
        return dict(n_false=0, never_high=0, transient_high=0, sustained_outside=0)
    fp = ep[ep["y_any"] == 0].merge(profile[["stay_id", "n_hi", "longest_pos_run"]],
                                    on="stay_id", how="left")
    never = int((fp["n_hi"].fillna(0) == 0).sum())
    transient = int(((fp["n_hi"].fillna(0) > 0) & (fp["longest_pos_run"].fillna(0) < 2)).sum())
    sustained = int((fp["longest_pos_run"].fillna(0) >= 2).sum())
    n = len(fp)
    return dict(
        n_false=n,
        never_high=never, never_high_pct=round(100 * never / n, 1) if n else float("nan"),
        transient_high=transient,
        transient_high_pct=round(100 * transient / n, 1) if n else float("nan"),
        sustained_outside=sustained,
        sustained_outside_pct=round(100 * sustained / n, 1) if n else float("nan"),
    )


# ══════════════════════════════════════════════════════════════════════════
# 4. One horizon, end to end — the function callers should use
# ══════════════════════════════════════════════════════════════════════════
def evaluate_horizon(calib: pd.DataFrame, test: pd.DataFrame, h: float,
                     score_col_tmpl: str = "p_calibrated_{h}h",
                     sens_target: float = 0.80,
                     gap_h: float = EPISODE_GAP_H,
                     profile: pd.DataFrame | None = None) -> dict:
    """Full evaluation at horizon h with the threshold fit on CALIB, applied to TEST.

    Both splits are first restricted to anchors whose status at h is KNOWN
    (known_status.known_subset) — a patient discharged before h is not a confirmed
    negative. `dropped_unknown_pct` reports how much that removes.
    """
    col = score_col_tmpl.format(h=int(h) if float(h).is_integer() else h)
    csub, cy = known_subset(calib, h)
    tsub, ty = known_subset(test, h)

    thr = select_threshold(csub[col].values, cy, sens_target)      # CALIB ONLY

    base_rate = float(np.mean(ty)) if len(ty) else float("nan")
    row = row_confusion(ty, tsub[col].values, thr)
    epm = episode_metrics(tsub, col, thr, ty, gap_h=gap_h)

    out = dict(
        horizon=float(h),
        n_known=len(tsub), n_events=int(np.sum(ty)), base_rate=base_rate,
        dropped_unknown_pct=round(100 * (1 - len(tsub) / len(test)), 1) if len(test) else float("nan"),
        threshold=thr,
        threshold_fit_on="calibration split",
        calib_sensitivity_at_threshold=sens_target,
        row=row,
        row_lift=lift(row["ppv"], base_rate),
        episode=epm,
        episode_lift=lift(epm["episode_ppv"], base_rate),
        gap_sensitivity=episode_gap_sensitivity(tsub, col, thr, ty),
    )
    if profile is not None:
        ep = alert_episodes(tsub, col, thr, ty, gap_h=gap_h)
        out["false_episode_decomposition"] = decompose_false_episodes(ep, profile)
    return out


# ══════════════════════════════════════════════════════════════════════════
# self-test — every number below is hand-computable from the toy frame
# ══════════════════════════════════════════════════════════════════════════
def _selftest():
    ok = True

    def check(name, got, want, tol=1e-9):
        nonlocal ok
        if isinstance(want, bool) or isinstance(got, bool):
            good = bool(got) == bool(want)
        elif isinstance(want, float) and np.isfinite(want):
            good = abs(got - want) < tol
        else:                       # ints, and non-finite floats like inf
            good = got == want
        if not good:
            ok = False
            print(f"  FAIL {name}: got {got!r}, expected {want!r}")

    # --- select_threshold ---------------------------------------------------
    # positives score 0.1,0.2,...,1.0 ; the 20th percentile of those is ~0.28,
    # so 80% of positives (0.3..1.0) sit above it.
    s = np.array([0.1 * i for i in range(1, 11)])
    thr = select_threshold(s, np.ones(10), 0.80)
    check("select_threshold puts 80% of positives above", float((s >= thr).mean()), 0.8, 0.06)
    check("no positives -> inf", select_threshold(np.array([0.5]), np.array([0]), 0.8), float("inf"))

    # --- alert_episodes: gap handling ---------------------------------------
    # One patient alerting at hours 0,1,2 then 10,11. With gap_h=2 that is TWO
    # episodes (the 8h break splits them); with gap_h=12 it is ONE.
    base = pd.Timestamp("2150-01-01")
    hrs = [0, 1, 2, 10, 11]
    df = pd.DataFrame(dict(
        stay_id=[1] * 5,
        anchor_time=[base + pd.Timedelta(hours=x) for x in hrs],
        T_hours=[20.0, 19.0, 18.0, 10.0, 9.0],
        event=[1] * 5,
        score=[0.9] * 5,
    ))
    y = np.array([0, 0, 0, 1, 1])          # only the later run is inside the horizon
    ep2 = alert_episodes(df, "score", 0.5, y, gap_h=2.0)
    ep12 = alert_episodes(df, "score", 0.5, y, gap_h=12.0)
    check("gap_h=2 -> 2 episodes", len(ep2), 2)
    check("gap_h=12 -> 1 episode", len(ep12), 1)
    check("episode 1 collapses 3 alerts", int(ep2.iloc[0]["n_alerts"]), 3)
    check("episode 1 is FALSE (no y=1 inside)", int(ep2.iloc[0]["y_any"]), 0)
    check("episode 2 is TRUE", int(ep2.iloc[1]["y_any"]), 1)
    check("episode 2 lead time = T at its first alert", float(ep2.iloc[1]["lead_time_h"]), 10.0)
    # merged into one episode, y_any must be the max over the whole run
    check("gap_h=12 merged episode is TRUE", int(ep12.iloc[0]["y_any"]), 1)

    # --- a timestamp gap must NOT silently split an episode ------------------
    # alerts at hours 0 and 2 with hour 1 missing: positionally adjacent, and 2h
    # apart, so with gap_h=2 they are ONE episode (the old positional shift(1)
    # would also merge them, but for the wrong reason -- this asserts the
    # timestamp rule is what is actually running).
    df2 = pd.DataFrame(dict(
        stay_id=[2, 2], anchor_time=[base, base + pd.Timedelta(hours=2)],
        T_hours=[6.0, 4.0], event=[1, 1], score=[0.9, 0.9]))
    check("2h apart with gap_h=2 -> 1 episode", len(alert_episodes(df2, "score", 0.5, np.array([1, 1]), gap_h=2.0)), 1)
    check("2h apart with gap_h=1 -> 2 episodes", len(alert_episodes(df2, "score", 0.5, np.array([1, 1]), gap_h=1.0)), 2)

    # --- episode_metrics ----------------------------------------------------
    # Patient 1: 5 alerting hours -> 2 episodes (1 true, 1 false), IS caught.
    # Patient 3: 1 alerting hour, never deteriorates -> 1 false episode.
    df3 = pd.concat([df, pd.DataFrame(dict(
        stay_id=[3], anchor_time=[base], T_hours=[30.0], event=[0], score=[0.9]))],
        ignore_index=True)
    y3 = np.append(y, 0)
    m = episode_metrics(df3, "score", 0.5, y3, gap_h=2.0)
    check("3 episodes total", m["n_episodes"], 3)
    check("1 true episode", m["n_true_episodes"], 1)
    check("episode PPV = 1/3", m["episode_ppv"], 1 / 3)
    check("1 event patient", m["n_event_patients"], 1)
    check("that patient is caught", m["n_event_patients_caught"], 1)
    check("patient recall = 1.0", m["patient_recall"], 1.0)
    # 6 anchors = 6 patient-hours = 0.25 patient-days -> 3/0.25 = 12 episodes/day
    check("episodes per patient-day", m["episodes_per_patient_day"], 12.0)

    # --- hysteresis ---------------------------------------------------------
    # one patient whose risk crosses up, dips into the deadband, then falls away
    hb = pd.DataFrame(dict(
        stay_id=[7] * 6,
        anchor_time=[base + pd.Timedelta(hours=i) for i in range(6)],
        score=[0.10, 0.60, 0.35, 0.55, 0.05, 0.05]))
    single = (hb.score.values >= 0.50)
    hyst = hysteresis_alert(hb, "score", thr_high=0.50, thr_low=0.30)
    # single threshold: on,off,on -> flickers.  hysteresis: on and stays on through
    # the 0.35 dip (>= thr_low), releases only at 0.05.
    check("single threshold flickers", list(single.astype(int)), [0, 1, 0, 1, 0, 0])
    check("hysteresis holds through the dip", list(hyst.astype(int)), [0, 1, 1, 1, 0, 0])
    check("thr_low == thr_high reproduces single threshold",
          list(hysteresis_alert(hb, "score", 0.50, 0.50).astype(int)),
          list(single.astype(int)))
    # the ON condition is unchanged, so the FIRST alert time can never be later
    first_single = int(np.argmax(single)) if single.any() else -1
    first_hyst = int(np.argmax(hyst)) if hyst.any() else -1
    check("hysteresis never delays the first alert", first_hyst, first_single)
    # latch must reset between patients
    hb2 = pd.concat([hb, pd.DataFrame(dict(
        stay_id=[8], anchor_time=[base], score=[0.35]))], ignore_index=True)
    check("latch resets on a new patient",
          int(hysteresis_alert(hb2, "score", 0.50, 0.30)[-1]), 0)

    # --- lift ---------------------------------------------------------------
    check("lift = ppv/base", lift(0.234, 0.1155), 2.0259, 1e-3)
    check("no-skill lift is 1.0", lift(0.2, 0.2), 1.0)

    # --- row_confusion: specificity is NOT 1-PPV ----------------------------
    yr = np.array([1, 1, 0, 0, 0, 0])
    sr = np.array([0.9, 0.8, 0.9, 0.7, 0.1, 0.1])
    r = row_confusion(yr, sr, 0.75)
    check("tp", r["tp"], 2); check("fp", r["fp"], 1); check("fn", r["fn"], 0); check("tn", r["tn"], 3)
    check("sensitivity = 2/2", r["sensitivity"], 1.0)
    check("ppv = 2/3", r["ppv"], 2 / 3)
    check("specificity = 3/4", r["specificity"], 0.75)
    check("specificity != 1-ppv", abs(r["specificity"] - (1 - r["ppv"])) > 0.05, True)

    # --- decompose_false_episodes -------------------------------------------
    prof = pd.DataFrame(dict(stay_id=[1, 3], n_hi=[3, 0], longest_pos_run=[1, 0]))
    ep3 = alert_episodes(df3, "score", 0.5, y3, gap_h=2.0)
    dec = decompose_false_episodes(ep3, prof)
    check("2 false episodes", dec["n_false"], 2)
    check("1 on a never-high patient", dec["never_high"], 1)
    check("1 on a transient-high patient", dec["transient_high"], 1)

    print("SELFTEST", "PASS" if ok else "FAIL", "-- eval_core.py")
    return ok


if __name__ == "__main__":
    raise SystemExit(0 if _selftest() else 1)
