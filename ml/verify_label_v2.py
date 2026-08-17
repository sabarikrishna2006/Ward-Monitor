"""
verify_label_v2.py — durable, re-runnable verification of the label-v2 change.

Answers, from the data rather than from prose, the questions a reviewer will ask:

  Q1  How many stays does each label call a deteriorator, and how do the four v2
      rules split that total?
  Q2  The 2,019 "transient" stays (reach NEWS2>=7 but never for 2 consecutive
      hours) — how many does v2 actually recover, and WHY are the rest still not
      events? (Answer: a single isolated HIGH hour can never satisfy any 2-reading
      rule. That half is genuinely ambiguous and v2 deliberately leaves it alone.)
  Q3  v1's "2 consecutive readings" test is POSITIONAL inside the NaN-dropped
      frame, not temporal. How often did v1 fire on two HIGH readings that were
      not actually an hour apart?
  Q4  v2 fires no later than v1 by construction — how much earlier, in practice?
  Q5  What does the label change cost in ANCHOR COVERAGE? Earlier event times mean
      a shorter pre-event window, so some patients lose their last anchors.
  Q6  Base rate per horizon under each label (needed because PPV is not comparable
      across labels — lift = PPV/base_rate is).

Writes data/label_v2_verification.json. Every number quoted anywhere else about
the label must come from this file.

Run:  PYTHONUTF8=1 EWS_TAG=news2 py -3 verify_label_v2.py
"""
from __future__ import annotations

import json
import logging

import numpy as np
import pandas as pd

import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("verify_label_v2")

HI = config.NEWS2_HIGH_BAND
V1_TAG = "news2"           # label v1 build
V2_TAG = "news2_v2lab"     # label v2, anchor rule unchanged (isolates the label effect)
V2K_TAG = "news2_v2"       # label v2 + keep_high_anchors (isolates the anchor effect)


def _hv_path(tag):      return config.dpath(f"vitals_hourly_{tag}.parquet")
def _anchor_path(tag):  return config.dpath(f"anchors_{tag}.parquet")


# ── Q1/Q2/Q3: per-stay NEWS2>=7 excursion profile ───────────────────────────
def excursion_profile(hv: pd.DataFrame) -> pd.DataFrame:
    """One row per stay describing its NEWS2>=7 history.

      n_hi                 how many hours the stay spent at NEWS2>=7
      longest_pos_run      longest run of HIGH readings by POSITION (what v1 tests)
      longest_time_run     longest run of HIGH readings actually 1h apart (what v1
                           was *meant* to test) -- the gap between these two is Q3
      min_hi_gap_h         smallest gap between two HIGH readings (drives v2 rule b)
    """
    out = []
    for sid, g in hv.groupby("stay_id"):
        g = g.dropna(subset=["band"]).sort_values("hour")
        if len(g) == 0:
            out.append((sid, 0, 0, 0, np.nan)); continue
        is_hi = (g["band"].values == HI)
        hours = g["hour"].values
        hi_t = hours[is_hi]

        pos_best = pos_run = 0
        time_best = time_run = 0
        prev_hi_t = None
        for i, v in enumerate(is_hi):
            if not v:
                pos_run = time_run = 0
                prev_hi_t = None
                continue
            pos_run += 1
            pos_best = max(pos_best, pos_run)
            if prev_hi_t is not None and abs(
                    (hours[i] - prev_hi_t) / np.timedelta64(1, "h") - 1.0) < 1e-6:
                time_run = max(time_run, 1) + 1
            else:
                time_run = 1
            time_best = max(time_best, time_run)
            prev_hi_t = hours[i]

        gaps = np.diff(hi_t) / np.timedelta64(1, "h") if len(hi_t) > 1 else np.array([])
        out.append((sid, int(is_hi.sum()), pos_best, time_best,
                    float(gaps.min()) if len(gaps) else np.nan))
    return pd.DataFrame(out, columns=["stay_id", "n_hi", "longest_pos_run",
                                      "longest_time_run", "min_hi_gap_h"])


def main():
    res: dict = {}

    hv = pd.read_parquet(_hv_path(V1_TAG))
    log.info("profiling NEWS2>=7 excursions across %d stays…", hv.stay_id.nunique())
    prof = excursion_profile(hv)

    # ---- Q1/Q2: cohort composition -------------------------------------------
    never = prof[prof.n_hi == 0]
    sustained = prof[prof.longest_pos_run >= config.SUSTAINED_READINGS]
    transient = prof[(prof.n_hi > 0) & (prof.longest_pos_run < config.SUSTAINED_READINGS)]
    res["cohort_composition"] = dict(
        n_stays_with_vitals=int(len(prof)),
        never_reached_news2_7=int(len(never)),
        v1_sustained_event=int(len(sustained)),
        transient_high_but_not_sustained=int(len(transient)),
        transient_pct_of_cohort=round(100 * len(transient) / len(prof), 1),
    )
    # why the transient group is only half-recoverable
    res["transient_breakdown"] = dict(
        exactly_one_high_hour=int((transient.n_hi == 1).sum()),
        two_or_more_high_hours=int((transient.n_hi >= 2).sum()),
        two_plus_with_a_pair_within_4h=int(
            ((transient.n_hi >= 2) & (transient.min_hi_gap_h <= 4.0)).sum()),
        note=("A stay with exactly one HIGH hour cannot satisfy ANY two-reading rule, "
              "so v2 cannot recover it. That half of the transient group is genuinely "
              "ambiguous — a single isolated HIGH reading is the pattern the "
              "2-consecutive-hour rule exists to filter as artefact."),
    )

    # ---- Q3: v1's positional-vs-temporal adjacency -----------------------------
    fired_v1 = prof[prof.longest_pos_run >= 2]
    leaky = fired_v1[fired_v1.longest_time_run < 2]
    res["v1_positional_adjacency_artifact"] = dict(
        v1_events=int(len(fired_v1)),
        fired_on_non_adjacent_readings=int(len(leaky)),
        pct_of_v1_events=round(100 * len(leaky) / max(len(fired_v1), 1), 2),
        note=("v1 tests consecutiveness by POSITION in the NaN-dropped frame, so two "
              "HIGH readings separated by a charting gap can count as 'consecutive'. "
              "v2 rule (b) is timestamp-based and not subject to this."),
    )

    # ---- Q1 cont.: label totals + rule attribution -----------------------------
    a1 = pd.read_parquet(_anchor_path(V1_TAG))
    a2 = pd.read_parquet(_anchor_path(V2_TAG))
    a2k = pd.read_parquet(_anchor_path(V2K_TAG))

    rule_counts = (a2.drop_duplicates("stay_id")["event_rule"].value_counts().to_dict()
                   if "event_rule" in a2.columns else {})
    res["label_totals"] = dict(
        v1_news2_events=int(len(sustained)),
        v2_news2_events=int(len(sustained) + len(transient[transient.min_hi_gap_h <= 4.0])),
        v2_rule_attribution_over_anchored_stays={k: int(v) for k, v in rule_counts.items()},
        note=("v2_rule_attribution counts only stays that produced >=1 anchor, so it is "
              "smaller than the cohort-level event count. Rule (a)'s share shrinks vs v1 "
              "not because events were lost but because rule (b) fires EARLIER on many "
              "stays and therefore wins the tie-break."),
    )

    # ---- Q4: how much earlier does v2 fire? ------------------------------------
    # reconstruct per-stay event time from anchors: anchor_time + T_hours on any event row
    def first_event_time(a):
        e = a[a.event == 1].copy()
        if len(e) == 0:
            return pd.Series(dtype="datetime64[ns]")
        e["ev_t"] = pd.to_datetime(e["anchor_time"]) + pd.to_timedelta(e["T_hours"], unit="h")
        return e.groupby("stay_id")["ev_t"].min()

    t1, t2 = first_event_time(a1), first_event_time(a2)
    both = pd.concat([t1.rename("v1"), t2.rename("v2")], axis=1).dropna()
    shift_h = (both["v1"] - both["v2"]) / pd.Timedelta(hours=1)
    res["event_time_shift"] = dict(
        stays_with_event_under_both=int(len(both)),
        fired_earlier_under_v2=int((shift_h > 1e-6).sum()),
        fired_later_under_v2=int((shift_h < -1e-6).sum()),
        median_hours_earlier_when_shifted=round(float(shift_h[shift_h > 1e-6].median()), 2)
        if (shift_h > 1e-6).any() else None,
        max_hours_earlier=round(float(shift_h.max()), 2),
        superset_property_holds=bool((shift_h >= -1e-6).all()),
        note=("v2 must never fire LATER than v1 (v1's time is always one of v2's "
              "candidates). fired_later_under_v2 must be 0 — it is an integrity check."),
    )

    # ---- Q5: what the label change costs in anchor coverage --------------------
    def cov(a, tag):
        return dict(
            tag=tag,
            anchor_rows=int(len(a)),
            stays_with_any_anchor=int(a.stay_id.nunique()),
            stays_with_an_event_anchor=int(a.loc[a.event == 1, "stay_id"].nunique()),
            row_event_rate=round(float(a.event.mean()), 4),
            already_high_anchors=int(a["already_high_at_anchor"].sum())
            if "already_high_at_anchor" in a.columns else 0,
        )
    res["anchor_coverage"] = dict(
        v1=cov(a1, V1_TAG), v2_label_only=cov(a2, V2_TAG), v2_plus_keep_high=cov(a2k, V2K_TAG),
        note=("v2 fires earlier, which SHORTENS each patient's pre-event anchor window — "
              "so anchor_rows falls even though the event count rises. Report this as a "
              "real cost of the label change, not a bug."),
    )
    res["keep_high_anchors_effect"] = dict(
        extra_anchor_rows=int(len(a2k) - len(a2)),
        extra_pct=round(100 * (len(a2k) - len(a2)) / len(a2), 2),
        extra_event_stays_recovered=int(
            a2k.loc[a2k.event == 1, "stay_id"].nunique() - a2.loc[a2.event == 1, "stay_id"].nunique()),
        verdict=("NULL RESULT if extra_event_stays_recovered == 0: keeping already-critical "
                 "anchor hours adds training rows but recovers no additional deteriorating "
                 "patient, so it does not fix the spectrum-bias/coverage gap it was aimed at."),
    )

    # ---- Q6: base rate per horizon under each label ----------------------------
    def base_rates(a):
        out = {}
        for h in config.HORIZONS_H:
            # a patient discharged before h has UNKNOWN status at h -> excluded,
            # matching known_status.py's censoring-correct rule
            known = a[(a.event == 1) | (a.T_hours >= h)]
            y = ((known.event == 1) & (known.T_hours <= h)).astype(int)
            out[str(h)] = dict(n_known=int(len(known)), n_events=int(y.sum()),
                               base_rate=round(float(y.mean()), 4),
                               dropped_unknown_pct=round(100 * (1 - len(known) / len(a)), 1))
        return out
    res["base_rate_by_horizon"] = dict(
        v1=base_rates(a1), v2_label_only=base_rates(a2),
        note=("Base rate RISES under v2. PPV is therefore NOT comparable across labels — "
              "a looser label mechanically raises precision. Compare lift = PPV/base_rate."),
    )

    out_path = config.dpath("label_v2_verification.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=2)
    log.info("wrote %s", out_path)

    # ---- human-readable summary ------------------------------------------------
    c = res["cohort_composition"]; tb = res["transient_breakdown"]
    print("\n" + "=" * 78)
    print("COHORT COMPOSITION")
    print(f"  stays with vitals                       {c['n_stays_with_vitals']:>7,}")
    print(f"  never reached NEWS2>=7                  {c['never_reached_news2_7']:>7,}")
    print(f"  v1 event (>=2 consecutive HIGH hours)   {c['v1_sustained_event']:>7,}")
    print(f"  TRANSIENT (HIGH but never 2 consec)     {c['transient_high_but_not_sustained']:>7,}"
          f"   <- v1 calls these non-deteriorators")
    print(f"     of which exactly ONE high hour       {tb['exactly_one_high_hour']:>7,}"
          f"   <- unrecoverable by any 2-reading rule")
    print(f"     of which >=2 high hours              {tb['two_or_more_high_hours']:>7,}")
    print(f"     of which a pair within 4h (rule b)   {tb['two_plus_with_a_pair_within_4h']:>7,}"
          f"   <- what v2 actually recovers")

    v = res["v1_positional_adjacency_artifact"]
    print("\nv1 POSITIONAL-ADJACENCY ARTEFACT")
    print(f"  v1 events                               {v['v1_events']:>7,}")
    print(f"  fired on NON-adjacent readings          {v['fired_on_non_adjacent_readings']:>7,}"
          f"   ({v['pct_of_v1_events']}% of v1 events)")

    s = res["event_time_shift"]
    print("\nEVENT-TIME SHIFT (v1 -> v2)")
    print(f"  stays with an event under both          {s['stays_with_event_under_both']:>7,}")
    print(f"  fired EARLIER under v2                  {s['fired_earlier_under_v2']:>7,}"
          f"   (median {s['median_hours_earlier_when_shifted']}h earlier)")
    print(f"  fired LATER under v2 (must be 0)        {s['fired_later_under_v2']:>7,}")
    print(f"  superset property holds                 {str(s['superset_property_holds']):>7}")

    print("\nANCHOR COVERAGE")
    print(f"  {'':22} {'rows':>9} {'stays':>7} {'event stays':>12} {'row ev rate':>12}")
    for k in ["v1", "v2_label_only", "v2_plus_keep_high"]:
        a = res["anchor_coverage"][k]
        print(f"  {k:22} {a['anchor_rows']:>9,} {a['stays_with_any_anchor']:>7,} "
              f"{a['stays_with_an_event_anchor']:>12,} {a['row_event_rate']:>12}")
    kh = res["keep_high_anchors_effect"]
    print(f"\n  keep_high_anchors: +{kh['extra_anchor_rows']:,} rows ({kh['extra_pct']}%), "
          f"extra event stays recovered = {kh['extra_event_stays_recovered']}")

    print("\nBASE RATE BY HORIZON (PPV is not comparable across labels — use lift)")
    print(f"  {'horizon':>8} {'v1 base':>10} {'v2 base':>10} {'v1 n_known':>12} {'v2 n_known':>12}")
    for h in config.HORIZONS_H:
        b1 = res["base_rate_by_horizon"]["v1"][str(h)]
        b2 = res["base_rate_by_horizon"]["v2_label_only"][str(h)]
        print(f"  {h:>7}h {b1['base_rate']:>10} {b2['base_rate']:>10} "
              f"{b1['n_known']:>12,} {b2['n_known']:>12,}")
    print("=" * 78 + "\n")


if __name__ == "__main__":
    main()
