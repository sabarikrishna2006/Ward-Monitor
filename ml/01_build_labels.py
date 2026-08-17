"""
Stage 01 — Build the composite time-to-event survival labels.

Pipeline:
  1. Assemble an hourly vitals grid per CCU stay (irregular MIMIC charting ->
     regular 1h grid; last-value-per-hour + time-limited forward-fill).
  2. Replay NEWS2 at every hour (reuse the production scorer via news2.py).
  3. Determine per-stay event times:
       - escalation_time   = first vasopressor/vent/RRT start   (objective deterioration)
       - news2_sustained   = first NEWS2>=7 persisting >=2 consecutive hours
       - deterioration_time = min(escalation_time, news2_sustained)   [the EVENT]
       - death_time        = in-hospital death (COMPETING risk)
       - outtime           = ICU discharge (administrative censoring)
  4. Generate hourly anchors t and label each with (T_hours, event, cause):
       event=1  deterioration occurs first, within H_max
       event=0  censored: competing death, discharge, or horizon cap
     with anchor exclusions (need >=2 vitals in look-back; drop already-critical
     NEWS2>=7 anchors; only pre-event anchors).

Outputs:
  data/vitals_hourly.parquet   hourly vitals + NEWS2 (reused by stage 02)
  data/anchors.parquet         one row per (stay, anchor) with survival label

Run:
  py -3 01_build_labels.py            # build from data/*.parquet
  py -3 01_build_labels.py --selftest # unit test on a 3-patient toy set
"""
from __future__ import annotations

import argparse
import logging
import os

import numpy as np
import pandas as pd

import config
from news2 import calculate_news2, news2_band

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("labels")

FFILL_LIMIT_H = 6          # carry a vital forward at most 6 hourly steps
CORE_FOR_NEWS2 = ["heart_rate", "resp_rate", "spo2", "sbp"]  # min presence to score


# ── itemid -> canonical vital column ────────────────────────────────────────
def _itemid_to_col() -> dict[int, str]:
    m: dict[int, str] = {}
    for col, ids in config.VITAL_ITEMIDS.items():
        for i in ids:
            m[i] = col
    m[config.GCS_TOTAL_ITEMID] = "gcs"
    m[config.O2_FLOW_ITEMID] = "o2_flow"
    m[config.FIO2_ITEMID] = "fio2"
    m[config.HEART_RHYTHM_ITEMID] = "rhythm"
    return m


def assemble_hourly_vitals(chartevents: pd.DataFrame, cohort: pd.DataFrame) -> pd.DataFrame:
    """Return a per-stay hourly grid with vital columns + derived NEWS2 inputs."""
    ce = chartevents.copy()
    ce["col"] = ce["itemid"].map(_itemid_to_col())
    ce = ce.dropna(subset=["col"])
    ce["charttime"] = pd.to_datetime(ce["charttime"])

    # Fahrenheit temp (223761) -> Celsius; unify into temp_c-as-"temperature".
    is_f = ce["itemid"] == config.VITAL_ITEMIDS["temp_f"][0]
    ce.loc[is_f, "valuenum"] = (ce.loc[is_f, "valuenum"] - 32.0) * 5.0 / 9.0
    ce.loc[ce["col"].isin(["temp_c", "temp_f"]), "col"] = "temperature"
    # dual-itemid vitals already share a col name (sbp/dbp/weight_kg).

    ce["hour"] = ce["charttime"].dt.floor("h")
    # numeric vitals: mean within the hour
    num = ce[ce["col"] != "rhythm"]
    wide = (num.groupby(["stay_id", "hour", "col"])["valuenum"].mean()
               .unstack("col").reset_index())

    # reindex each stay to a full hourly range [floor(intime), ceil(outtime)]
    cinfo = cohort.set_index("stay_id")[["intime", "outtime"]]
    frames = []
    numeric_cols = [c for c in wide.columns if c not in ("stay_id", "hour")]
    for sid, g in wide.groupby("stay_id"):
        if sid not in cinfo.index:
            continue
        t0 = pd.to_datetime(cinfo.loc[sid, "intime"]).floor("h")
        t1 = pd.to_datetime(cinfo.loc[sid, "outtime"]).ceil("h")
        if pd.isna(t0) or pd.isna(t1) or t1 <= t0:
            continue
        grid = pd.DataFrame({"hour": pd.date_range(t0, t1, freq="h")})
        g = grid.merge(g.drop(columns="stay_id"), on="hour", how="left")
        g[numeric_cols] = g[numeric_cols].ffill(limit=FFILL_LIMIT_H)
        g["stay_id"] = sid
        frames.append(g)
    if not frames:
        return pd.DataFrame()
    hv = pd.concat(frames, ignore_index=True)

    # derived NEWS2 inputs
    # consciousness: GCS>=14 -> Alert ('A'); GCS<14 -> not-alert (+3). Missing -> None.
    if "gcs" in hv:
        hv["consciousness"] = np.where(hv["gcs"] >= 14, "A",
                                np.where(hv["gcs"].notna(), "V", None))
    else:
        hv["consciousness"] = None
    # air_or_oxygen: on O2 if O2 flow>0 or FiO2>21; else Air.
    o2flow = hv["o2_flow"] if "o2_flow" in hv.columns else pd.Series(np.nan, index=hv.index)
    fio2 = hv["fio2"] if "fio2" in hv.columns else pd.Series(np.nan, index=hv.index)
    on_o2 = (pd.to_numeric(o2flow, errors="coerce").fillna(0) > 0) | \
            (pd.to_numeric(fio2, errors="coerce").fillna(0) > 21)
    hv["air_or_oxygen"] = np.where(on_o2, "Oxygen", "Air")
    return hv


def score_news2(hv: pd.DataFrame) -> pd.DataFrame:
    """Add news2 + band columns; NaN where core vitals are absent."""
    def _row(r):
        if any(pd.isna(r.get(c)) for c in CORE_FOR_NEWS2):
            return np.nan
        v = {
            "heart_rate": r.get("heart_rate"), "resp_rate": r.get("resp_rate"),
            "spo2": r.get("spo2"), "sbp": r.get("sbp"),
            "temperature": r.get("temperature"),
            "consciousness": r.get("consciousness"),
            "air_or_oxygen": r.get("air_or_oxygen"),
        }
        return calculate_news2(v)["total"]
    hv = hv.sort_values(["stay_id", "hour"]).reset_index(drop=True)
    hv["news2"] = hv.apply(_row, axis=1)
    hv["band"] = hv["news2"].apply(lambda s: news2_band(int(s)) if pd.notna(s) else np.nan)
    return hv


# ── event times ─────────────────────────────────────────────────────────────
def _first_start(df: pd.DataFrame, id_col="stay_id", time_col="starttime") -> pd.Series:
    if df.empty:
        return pd.Series(dtype="datetime64[ns]")
    d = df.copy()
    d[time_col] = pd.to_datetime(d[time_col])
    return d.groupby(id_col)[time_col].min()


def _news2_sustained_time(hv: pd.DataFrame, n=config.SUSTAINED_READINGS) -> pd.Series:
    """LABEL v1. First hour where band==HIGH persists >= n consecutive hourly readings.

    NOTE (documented, deliberately NOT changed -- v1 is the locked baseline):
    consecutiveness here is POSITIONAL within the NaN-dropped frame, not temporal.
    If NEWS2 is missing for hours 4-6 then HIGH readings at hour 3 and hour 7 count
    as "consecutive". verify_label_v2.py quantifies how often this happens; v2's
    rule (b) below is timestamp-based and therefore not subject to it.
    """
    out = {}
    for sid, g in hv.groupby("stay_id"):
        g = g.dropna(subset=["band"]).sort_values("hour")
        bands = (g["band"].values == config.NEWS2_HIGH_BAND)
        hours = g["hour"].values
        run = 0
        for i, hi in enumerate(bands):
            run = run + 1 if hi else 0
            if run >= n:
                out[sid] = pd.Timestamp(hours[i - n + 1])   # onset of the run
                break
    return pd.Series(out, dtype="datetime64[ns]")


# ── label v2 ────────────────────────────────────────────────────────────────
# Motivation (measured 2026-07-27, not assumed): 2,019 of 10,769 CCU stays (18.7%)
# reach NEWS2>=7 at least once but never for two CONSECUTIVE hours, so v1 labels
# them "never deteriorated". 1,008 of those had exactly one HIGH hour and 461 had
# two non-adjacent HIGH hours; the median such patient stayed 29 MORE hours, so
# this is not a missing-data problem -- v1 is simply brittle to a one-hour dip.
# At the 12h horizon, 50.2% of the model's "false" alarm episodes fire on this
# group: the model saw the deterioration and was scored wrong by the label.
#
# v2 is a strict SUPERSET of v1 by construction (the v1 time is always one of the
# candidates), so any v1 event stays an event and v2 can only fire at the same
# time or earlier. That superset property is what makes the v1-vs-v2 sensitivity
# analysis interpretable.
V2_WINDOW_H       = 4.0   # (b) two HIGH readings within this many hours
V2_DEATH_WINDOW_H = 6.0   # (c) HIGH reading followed by death within this many hours
V2_TRUNCATION_H   = 2.0   # (d) record ends this soon after a HIGH reading
_V2_RULE_PRIORITY = {"a_sustained": 0, "b_windowed": 1, "c_terminal": 2, "d_truncated": 3}


def _news2_event_time_v2(hv: pd.DataFrame, stay_end: pd.Series, deathtime: pd.Series,
                         v1_time: pd.Series) -> tuple[pd.Series, pd.Series]:
    """LABEL v2. Earliest of four rules; returns (event_time, event_rule).

      (a) sustained  -- NEWS2>=7 for >=2 consecutive hours  [identical to v1]
      (b) windowed   -- >=2 hours at NEWS2>=7 inside any 4h window (one dip allowed).
                        Timestamp-based, so a charting gap cannot fake adjacency.
      (c) terminal   -- a single NEWS2>=7 hour followed by death within 6h.
      (d) truncated  -- a single NEWS2>=7 hour where the record ends <2h later, so
                        the 2-consecutive-hour rule was UNSATISFIABLE. These were
                        right-censoring misapplied as a confirmed negative.

    Ties are broken toward the lower-numbered rule so a stay that satisfies both
    (a) and (b) at the same hour is credited to (a) -- making each rule's marginal
    contribution countable in verify_label_v2.py.
    """
    times, rules = {}, {}
    for sid, g in hv.groupby("stay_id"):
        g = g.dropna(subset=["band"]).sort_values("hour")
        hi = g.loc[g["band"].values == config.NEWS2_HIGH_BAND, "hour"].values
        if len(hi) == 0:
            continue
        cands: list[tuple[pd.Timestamp, str]] = []

        t1 = v1_time.get(sid, pd.NaT)                                   # (a)
        if pd.notna(t1):
            cands.append((pd.Timestamp(t1), "a_sustained"))

        for k in range(len(hi) - 1):                                    # (b)
            gap_h = (hi[k + 1] - hi[k]) / np.timedelta64(1, "h")
            if gap_h <= V2_WINDOW_H:
                cands.append((pd.Timestamp(hi[k]), "b_windowed"))
                break                    # hi is sorted, so this is the earliest pair

        d = deathtime.get(sid, pd.NaT)                                  # (c)
        if pd.notna(d):
            for t in hi:
                dh = (pd.Timestamp(d) - pd.Timestamp(t)) / pd.Timedelta(hours=1)
                if 0 <= dh <= V2_DEATH_WINDOW_H:
                    cands.append((pd.Timestamp(t), "c_terminal"))
                    break

        end = stay_end.get(sid, pd.NaT)                                 # (d)
        if pd.notna(end):
            for t in hi:
                eh = (pd.Timestamp(end) - pd.Timestamp(t)) / pd.Timedelta(hours=1)
                if 0 <= eh < V2_TRUNCATION_H:
                    cands.append((pd.Timestamp(t), "d_truncated"))
                    break

        if cands:
            cands.sort(key=lambda c: (c[0], _V2_RULE_PRIORITY[c[1]]))
            times[sid], rules[sid] = cands[0]
    return pd.Series(times, dtype="datetime64[ns]"), pd.Series(rules, dtype=object)


def _escalation_event_time(cohort: pd.DataFrame, min_hours=None,
                           include_ambiguous=False) -> tuple[pd.Series, pd.Series]:
    """ESCALATION TARGET. First CCU-relevant escalation of care occurring at least
    `min_hours` after ICU admission. Returns (event_time, event_group).

    Reads data/escalation_events_ext.parquet (built by 00b_extract_escalation_ext.py)
    -- NOT inputevents/procedureevents.parquet, which were extracted filtered to the
    OLD itemid list and therefore contain no mechanical circulatory support, no
    cardiac arrest, no defibrillation and not the standalone Intubation itemid.

    Primary therapy groups (measured prevalence on this 10,775-stay CCU cohort):
        pressor      vasopressors/inotropes
        vent         invasive + non-invasive ventilation
        rrt          CRRT/CVVHD/PD/CVVHDF/SCUF/HD
        mcs          IABP / Impella / ECMO          -- 6%, previously 100% missing
        acute_event  cardiac arrest / respiratory arrest / cardioversion-defibrillation
        rescue       intubation / pericardiocentesis / temporary pacemaker
    Union = 4,479 stays (41.6%); 312 stays (2.9%) are captured ONLY by the newly
    added groups and were invisible to the old definition.

    `include_ambiguous=True` adds amiodarone/lidocaine/alteplase for the sensitivity
    analysis. Excluded by default: amiodarone for rate control in new AF is routine
    CCU care, so including ~11% of stays' worth of routine antiarrhythmic would
    inflate prevalence with normal practice rather than deterioration.

    WHY THE min_hours CUTOFF IS NOT CHERRY-PICKING. Measured on this cohort: median
    time to first escalation is 1.07h, 21.6% of stays escalate inside 2h and 3.9%
    arrive already escalated. Those are not predictions -- the event is concurrent
    with or prior to the first observation. They are covered by an ADMISSION RULE
    (alert immediately, no model needed), exactly as arrival-critical NEWS2 patients
    are. Restricting the model to later escalations stops it taking credit for
    events it could not have foreseen.
    """
    if min_hours is None:
        min_hours = config.ESCALATION_MIN_HOURS
    path = config.dpath("escalation_events_ext.parquet")
    ev = pd.read_parquet(path)
    if not include_ambiguous:
        ev = ev[ev["tier"] == "primary"]
    intime = pd.to_datetime(cohort.set_index("stay_id")["intime"])
    ev = ev.copy()
    ev["starttime"] = pd.to_datetime(ev["starttime"])
    ev["_intime"] = ev["stay_id"].map(intime)
    ev["h_since_adm"] = (ev["starttime"] - ev["_intime"]).dt.total_seconds() / 3600.0
    ev = ev[ev["h_since_adm"] >= float(min_hours)]
    if ev.empty:
        return pd.Series(dtype="datetime64[ns]"), pd.Series(dtype=object)
    first = (ev.sort_values("starttime").groupby("stay_id")
               .agg(t=("starttime", "first"), g=("group", "first")))
    return first["t"], first["g"]


def _severe_shock_time(hv: pd.DataFrame, map_thresh=55.0, si_thresh=1.1,
                       hours=2) -> pd.Series:
    """SEVERE PHYSIOLOGICAL COLLAPSE track. First hour at which MAP < map_thresh AND
    shock index (HR/SBP) >= si_thresh has persisted for `hours` consecutive readings.

    Uses MEASURED mean arterial pressure (chartevents 220181 NIBP-mean at 98.3%
    coverage / 220052 arterial-mean at 26.7%), not the (SBP + 2*DBP)/3
    approximation. This track only became possible once MAP was extracted.

    WHY THIS TRACK EXISTS. Measured inside the eligible cohort: 252 stays (3.2%)
    meet it, of which 192 (76.2%) are already captured by escalation-or-death. The
    remaining **60 stays (0.8%)** sustained MAP<55 with SI>=1.1 for >=2h, were never
    escalated, and never died in hospital -- so today they are labelled "nothing
    happened" and any alert on them is scored as a false positive.

    It was proposed as a DNR/DNI fix (a DNR patient in shock is never escalated, so
    is labelled 0). Tested against Code Status (223758, 49.7% coverage): only 8 of
    the 60 are DNR/DNI/comfort-care -- a real 2.3x enrichment over the 5.7% cohort
    base rate, but a small minority. **The track is justified by the physiology of
    all 60, not by the DNR story of 8.** That argument survives the question "how
    many were actually DNR?".

    Code status is deliberately NOT used as a feature anywhere: the model would
    learn treatment policy (DNR -> not escalated -> predict no event) instead of
    physiology.
    """
    path = config.dpath("chartevents_ext.parquet")
    if not os.path.exists(path):
        log.warning("chartevents_ext.parquet missing -- severe-shock track disabled")
        return pd.Series(dtype="datetime64[ns]")
    ce = pd.read_parquet(path, columns=["stay_id", "charttime", "itemid", "valuenum"])
    ce = ce[ce["itemid"].isin(list(config.HEMO_ITEMIDS))]
    if ce.empty:
        return pd.Series(dtype="datetime64[ns]")
    ce["hour"] = pd.to_datetime(ce["charttime"]).dt.floor("h")
    mp = (ce.groupby(["stay_id", "hour"])["valuenum"].median()
            .rename("map_meas").reset_index())

    g = hv[["stay_id", "hour", "heart_rate", "sbp"]].copy()
    g["hour"] = pd.to_datetime(g["hour"])
    g = g.merge(mp, on=["stay_id", "hour"], how="left").sort_values(["stay_id", "hour"])
    with np.errstate(divide="ignore", invalid="ignore"):
        g["si"] = g["heart_rate"] / g["sbp"].replace(0, np.nan)
    g["hit"] = (g["map_meas"] < map_thresh) & (g["si"] >= si_thresh)

    out = {}
    for sid, gg in g.groupby("stay_id"):
        hits = gg["hit"].to_numpy()
        hrs = gg["hour"].to_numpy()
        run = 0
        for i, v in enumerate(hits):
            run = run + 1 if v else 0
            if run >= hours:
                out[sid] = pd.Timestamp(hrs[i - hours + 1])   # onset of the run
                break
    return pd.Series(out, dtype="datetime64[ns]")


def eligible_escalation_cohort(cohort: pd.DataFrame, min_hours=None) -> tuple[set, dict]:
    """The DETERIO cohort rule, verbatim: exclude stays whose deterioration occurred
    before hour `min_hours` of unit admission, and stays shorter than that.

    An escalation at or near admission is not a prediction -- the event is
    concurrent with, or prior to, the first observation. Measured: median
    time-to-first-escalation in this CCU is 1.07h. Those patients are covered by an
    ADMISSION RULE (alert immediately, no model), so nobody is left uncovered; the
    model is simply restricted to the population where prediction is meaningful.

    Returns (eligible stay_ids, counts dict for the verification report).
    """
    if min_hours is None:
        min_hours = config.ESCALATION_MIN_HOURS
    min_hours = float(min_hours)
    ev = pd.read_parquet(config.dpath("escalation_events_ext.parquet"))
    ev = ev[ev["tier"] == "primary"].copy()
    ev["starttime"] = pd.to_datetime(ev["starttime"])

    c = cohort.copy()
    for col in ("intime", "outtime", "deathtime"):
        c[col] = pd.to_datetime(c[col])
    intime = c.set_index("stay_id")["intime"]
    ev["h"] = (ev["starttime"] - ev["stay_id"].map(intime)).dt.total_seconds() / 3600.0

    h_death = ((c["deathtime"] - c["intime"]).dt.total_seconds() / 3600.0)
    h_death.index = c["stay_id"].values
    los = ((c["outtime"] - c["intime"]).dt.total_seconds() / 3600.0)
    los.index = c["stay_id"].values

    all_stays = set(c["stay_id"])
    early_esc = set(ev.loc[ev["h"] < min_hours, "stay_id"]) & all_stays
    early_death = set(h_death.index[h_death < min_hours]) & all_stays
    short = set(los.index[los < min_hours]) & all_stays
    eligible = all_stays - early_esc - early_death - short
    counts = dict(all_stays=len(all_stays), excluded_early_escalation=len(early_esc),
                  excluded_early_death=len(early_death - early_esc),
                  excluded_short_stay=len(short - early_esc - early_death),
                  eligible=len(eligible), min_hours=min_hours)
    return eligible, counts


def compute_stay_events(cohort, inputevents, procedureevents, hv, event_mode="composite",
                        label_version="v1", escalation_min_hours=None,
                        include_ambiguous_escalation=False,
                        severe_shock_track=True) -> pd.DataFrame:
    """
    event_mode="composite": deterioration = earliest of {treatment escalation, sustained NEWS2>=7}.
    event_mode="news2":     deterioration = sustained NEWS2>=7 ONLY. Escalation no longer ends the
        risk set or counts as an event -- a patient who is escalated but never sustains NEWS2>=7
        is right-censored at death/discharge/horizon, same as any other non-event patient. This is
        the focused single-event base model (2026-07 review): one target, no mixing.

    label_version="v1": the NEWS2 event is `_news2_sustained_time` (2 consecutive hours).
    label_version="v2": the NEWS2 event is `_news2_event_time_v2` (adds the windowed /
        terminal / truncated rules). v2 is a strict superset of v1, so this widens the
        event set and never removes an event. `event_rule` records which rule fired.

    NOTE: this changes the CENSORING RULES AROUND the NEWS2>=7 construct, not the
    construct itself. The event is still "the patient crossed NEWS2>=7" -- settled with
    Prof. Shroff 2026-07-22/23 and not reopened here.
    """
    esc_input = _first_start(inputevents)                       # vasopressors
    proc = procedureevents
    esc_proc = _first_start(proc) if not proc.empty else pd.Series(dtype="datetime64[ns]")
    escalation = pd.concat([esc_input, esc_proc], axis=1).min(axis=1)
    news2_sus = _news2_sustained_time(hv)

    ev = cohort[["stay_id", "hadm_id", "subject_id", "intime", "outtime",
                 "deathtime", "dcm_flag"]].copy()
    ev["intime"] = pd.to_datetime(ev["intime"])
    ev["outtime"] = pd.to_datetime(ev["outtime"])
    ev["deathtime"] = pd.to_datetime(ev["deathtime"])
    # death only counts as competing if it falls at/after ICU admission
    ev.loc[ev["deathtime"] < ev["intime"], "deathtime"] = pd.NaT
    ev["escalation_time"] = ev["stay_id"].map(escalation)
    ev["news2_sustained_time"] = ev["stay_id"].map(news2_sus)

    if label_version == "v1":
        ev["news2_event_time"] = ev["news2_sustained_time"]
        ev["event_rule"] = np.where(ev["news2_sustained_time"].notna(), "a_sustained", None)
    elif label_version == "v2":
        # stay_end = the last moment a second reading could have been charted
        stay_end = ev[["outtime", "deathtime"]].min(axis=1)
        stay_end.index = ev["stay_id"].values
        death_by_stay = ev.set_index("stay_id")["deathtime"]
        t2, r2 = _news2_event_time_v2(hv, stay_end, death_by_stay, news2_sus)
        ev["news2_event_time"] = ev["stay_id"].map(t2)
        ev["event_rule"] = ev["stay_id"].map(r2)
    else:
        raise ValueError(f"unknown label_version {label_version!r}")

    if event_mode == "news2":
        ev["deterioration_time"] = ev["news2_event_time"]
    elif event_mode == "composite":
        ev["deterioration_time"] = ev[["escalation_time", "news2_event_time"]].min(axis=1)
    elif event_mode == "escalation":
        # THE ESCALATION TARGET. Replaces NEWS2 rather than being OR'd with it --
        # an OR-composite inherits NEWS2's 50.3% prevalence (measured: the 4-track
        # union lands at 71.4%), and prevalence is the binding constraint on the
        # false-alarm rate. NEWS2 plays no part in this target at all.
        t_esc, g_esc = _escalation_event_time(
            cohort, min_hours=escalation_min_hours,
            include_ambiguous=include_ambiguous_escalation)
        ev["escalation_ext_time"] = ev["stay_id"].map(t_esc)
        ev["escalation_group"] = ev["stay_id"].map(g_esc)

        # Death is an EVENT here, not a competing risk -- it is the terminal form of
        # the thing we are predicting. Same >min_hours rule: a death at/near
        # admission was not foreseeable from the first observation.
        min_h = config.ESCALATION_MIN_HOURS if escalation_min_hours is None else escalation_min_hours
        h_death = (ev["deathtime"] - ev["intime"]).dt.total_seconds() / 3600.0
        death_as_event = ev["deathtime"].where(h_death >= float(min_h))

        # SEVERE PHYSIOLOGICAL COLLAPSE safety net -- see _severe_shock_time().
        # Also subject to the >min_hours rule: shock present at admission is not a
        # prediction either.
        if severe_shock_track:
            t_shock = _severe_shock_time(hv)
            ev["shock_time"] = ev["stay_id"].map(t_shock)
            h_shock = (ev["shock_time"] - ev["intime"]).dt.total_seconds() / 3600.0
            ev["shock_time"] = ev["shock_time"].where(h_shock >= float(min_h))
        else:
            ev["shock_time"] = pd.NaT

        cand = pd.DataFrame({
            "escalation": ev["escalation_ext_time"].values,
            "death": death_as_event.values,
            "shock": ev["shock_time"].values,
        }, index=ev.index)
        ev["deterioration_time"] = cand.min(axis=1)
        # Attribute each event to the track that fired FIRST, so the report can show
        # each track's marginal contribution rather than a bare event count.
        # idxmin is only defined where at least one candidate is non-null -- calling
        # it on the all-NaT (non-event) rows raises, so restrict to event rows.
        has_ev = ev["deterioration_time"].notna()
        which = pd.Series(index=ev.index, dtype=object)
        if has_ev.any():
            which.loc[has_ev] = cand.loc[has_ev].idxmin(axis=1)
        ev["event_rule"] = np.where(
            ~has_ev, None,
            np.where(which.eq("escalation"), ev["escalation_group"].fillna("escalation"),
                     np.where(which.eq("death"), "death", "severe_shock")))
        # For this target NEWS2 is not the event, so it must not terminate the risk
        # set either -- a patient who crosses NEWS2>=7 and is never escalated is
        # censored at discharge like anyone else.
        ev["news2_event_time"] = pd.NaT
    else:
        raise ValueError(f"unknown event_mode {event_mode!r}")
    return ev


# ── anchors + labels ─────────────────────────────────────────────────────────
def build_anchors(hv: pd.DataFrame, ev: pd.DataFrame, hmax_h=config.HMAX_H,
                  keep_high_anchors=False) -> pd.DataFrame:
    """keep_high_anchors=False (default, reproduces v1 exactly): an anchor hour where
    the patient is ALREADY at NEWS2>=7 is dropped entirely.

    keep_high_anchors=True: that hour is kept, with `already_high_at_anchor=True`
    recorded so it can be used as a training feature but EXCLUDED FROM EVALUATION
    (you cannot claim credit for predicting deterioration that is already visible on
    the chart). Rationale: the hard drop is a spectrum bias -- combined with the
    1,516 patients who deteriorate too fast to have 2 readings, only 3,891 of 5,424
    true deteriorators (71.7%) contribute a single training row, and the ones being
    excluded are the sickest presentations. This flag is deliberately INDEPENDENT of
    --label-version so the two changes can be ablated separately.
    """
    hv = hv.sort_values(["stay_id", "hour"])
    evx = ev.set_index("stay_id")
    W = pd.Timedelta(hours=config.LOOKBACK_H)
    Hmax = pd.Timedelta(hours=hmax_h)
    rows = []
    # count of non-null vital hours per stay for the look-back check
    for sid, g in hv.groupby("stay_id"):
        if sid not in evx.index:
            continue
        e = evx.loc[sid]
        intime = e["intime"]
        det = e["deterioration_time"]
        death = e["deathtime"]
        out = e["outtime"]
        # terminator: end of usable timeline for this stay
        stay_end = min([t for t in [det, death, out] if pd.notna(t)], default=out)
        ghours = g["hour"].values
        gnews = g["news2"].values
        have_vitals = ~pd.isna(gnews)
        for i, t in enumerate(ghours):
            t = pd.Timestamp(t)
            if pd.notna(stay_end) and t >= stay_end:   # only pre-event anchors
                continue
            # eligibility = >=MIN_VITALS_IN_WINDOW readings in (t-W, t], capping W as
            # the MAXIMUM look-back rather than a required one -- the grid starts at
            # intime, so this window is naturally clipped there for anchors <W into
            # the stay (graceful degradation instead of a hard 6h floor, see plan §0b).
            win = (ghours > np.datetime64(t - W)) & (ghours <= np.datetime64(t))
            if have_vitals[win].sum() < config.MIN_VITALS_IN_WINDOW:
                continue
            already_high = bool(pd.notna(gnews[i])
                                and news2_band(int(gnews[i])) == config.NEWS2_HIGH_BAND)
            if already_high and not keep_high_anchors:
                continue                            # already critical -> skip (v1 behaviour)
            # ---- outcome resolution (cause-specific; death competes) ----
            if pd.notna(det) and det > t and (pd.isna(death) or det <= death):
                T = det - t; event = 1; cause = "deterioration"
            elif pd.notna(death) and death > t and (pd.isna(det) or death < det):
                T = death - t; event = 0; cause = "death"
            else:
                T = out - t; event = 0; cause = "administrative"
            T_h = T / pd.Timedelta(hours=1)
            if T_h <= 0:
                continue
            if T_h > hmax_h:                        # administrative horizon cap
                T_h = float(hmax_h); event = 0
                if cause == "deterioration":
                    cause = "censored_horizon"
            rows.append((sid, e["hadm_id"], e["subject_id"], t, T_h, event, cause,
                         bool(e["dcm_flag"]), float(gnews[i]) if pd.notna(gnews[i]) else np.nan,
                         already_high))
    cols = ["stay_id", "hadm_id", "subject_id", "anchor_time", "T_hours", "event",
            "cause", "dcm_flag", "news2_at_anchor", "already_high_at_anchor"]
    return pd.DataFrame(rows, columns=cols)


def run(hmax_h=config.HMAX_H, event_mode="composite", label_version="v1",
        keep_high_anchors=False, vitals_from=None, escalation_min_hours=None,
        include_ambiguous_escalation=False):
    cohort = pd.read_parquet(config.dpath("cohort.parquet"))
    inputevents = pd.read_parquet(config.dpath("inputevents.parquet"))
    procedureevents = pd.read_parquet(config.dpath("procedureevents.parquet"))

    if vitals_from:
        # The hourly vitals grid + NEWS2 replay depends only on chartevents and the
        # cohort -- NOT on the label version -- so a v2 run can reuse the v1 grid
        # instead of spending minutes rebuilding an identical file.
        src = config.dpath(f"vitals_hourly_{vitals_from}.parquet")
        log.info("reusing existing hourly vitals grid: %s", src)
        hv = pd.read_parquet(src)
    else:
        chartevents = pd.read_parquet(config.dpath("chartevents.parquet"))
        log.info("assembling hourly vitals for %d stays… (event_mode=%s)",
                 cohort["stay_id"].nunique(), event_mode)
        hv = assemble_hourly_vitals(chartevents, cohort)
        hv = score_news2(hv)
    hv.to_parquet(config.tpath("vitals_hourly.parquet"), index=False)
    log.info("vitals_hourly: %d hourly rows (%d with NEWS2)", len(hv), int(hv["news2"].notna().sum()))

    esc_counts = None
    if event_mode == "escalation":
        # COHORT RESTRICTION (DETERIO rule) applied BEFORE event computation, so
        # build_anchors never sees an ineligible stay.
        eligible, esc_counts = eligible_escalation_cohort(cohort, escalation_min_hours)
        log.info("escalation cohort restriction: %d stays -> %d eligible "
                 "(excluded: %d escalated <%.0fh, %d died <%.0fh, %d stay <%.0fh)",
                 esc_counts["all_stays"], esc_counts["eligible"],
                 esc_counts["excluded_early_escalation"], esc_counts["min_hours"],
                 esc_counts["excluded_early_death"], esc_counts["min_hours"],
                 esc_counts["excluded_short_stay"], esc_counts["min_hours"])
        cohort = cohort[cohort["stay_id"].isin(eligible)].copy()
        hv = hv[hv["stay_id"].isin(eligible)].copy()
        # NEWS2 is not the event here, so an already-high NEWS2 hour is a perfectly
        # valid -- arguably the most valuable -- prediction point. Never skip it.
        if not keep_high_anchors:
            log.info("escalation mode: forcing keep_high_anchors=True "
                     "(NEWS2>=7 is not the event, so it must not gate anchors)")
            keep_high_anchors = True

    ev = compute_stay_events(cohort, inputevents, procedureevents, hv,
                             event_mode=event_mode, label_version=label_version,
                             escalation_min_hours=escalation_min_hours,
                             include_ambiguous_escalation=include_ambiguous_escalation)
    n_det = ev["deterioration_time"].notna().sum()
    n_esc = ev["escalation_time"].notna().sum()
    n_v1 = ev["news2_sustained_time"].notna().sum()
    n_lab = ev["news2_event_time"].notna().sum()
    n_death = ev["deathtime"].notna().sum()
    log.info("stay events (mode=%s label=%s): %d deterioration | %d escalation | "
             "NEWS2 event: v1-rule %d -> this label %d | %d death | of %d stays",
             event_mode, label_version, n_det, n_esc, n_v1, n_lab, n_death, len(ev))
    if event_mode == "escalation":
        log.info("escalation-target event attribution (first track to fire):\n%s",
                 ev["event_rule"].value_counts().to_string())
        log.info("stay-level prevalence: %d / %d = %.1f%%",
                 n_det, len(ev), 100 * n_det / max(len(ev), 1))
    elif label_version == "v2":
        log.info("v2 rule contributions:\n%s", ev["event_rule"].value_counts().to_string())

    anchors = build_anchors(hv, ev, hmax_h=hmax_h, keep_high_anchors=keep_high_anchors)
    # carry the firing rule onto every anchor so downstream analysis can attribute
    # any metric change to a specific rule rather than to "the label changed"
    anchors = anchors.merge(ev[["stay_id", "event_rule"]], on="stay_id", how="left")
    anchors.to_parquet(config.tpath("anchors.parquet"), index=False)
    ev_rate = anchors["event"].mean() if len(anchors) else 0
    log.info("anchors: %d rows | %d stays | event rate %.3f | DCM anchors %d | already-high anchors %d",
             len(anchors), anchors["stay_id"].nunique(), ev_rate, int(anchors["dcm_flag"].sum()),
             int(anchors["already_high_at_anchor"].sum()))
    log.info("cause breakdown:\n%s", anchors["cause"].value_counts().to_string())
    # unique events (not overlapping-window rows) for honest reporting
    uniq_events = anchors.loc[anchors["event"] == 1, "stay_id"].nunique()
    log.info("UNIQUE stays with a deterioration event: %d (of %d stays whose label fired -- "
             "the difference is stays that deteriorate too fast to produce any anchor)",
             uniq_events, n_lab)


# ── self-test on a tiny synthetic cohort ─────────────────────────────────────
def selftest():
    """Three patients with hand-computable labels."""
    base = pd.Timestamp("2150-01-01 00:00")
    # Patient A: stable then vasopressor at +10h -> deterioration event.
    # Patient B: discharged at +12h, no event -> censored.
    # Patient C: dies at +8h without deterioration -> competing-death censor.
    cohort = pd.DataFrame([
        dict(stay_id=1, hadm_id=1, subject_id=1, intime=base, outtime=base + pd.Timedelta(hours=20),
             deathtime=pd.NaT, dcm_flag=True),
        dict(stay_id=2, hadm_id=2, subject_id=2, intime=base, outtime=base + pd.Timedelta(hours=12),
             deathtime=pd.NaT, dcm_flag=False),
        dict(stay_id=3, hadm_id=3, subject_id=3, intime=base, outtime=base + pd.Timedelta(hours=8),
             deathtime=base + pd.Timedelta(hours=8), dcm_flag=False),
    ])
    # hourly stable vitals (NEWS2 ~0) for all three across their stay
    rows = []
    for sid, hrs in [(1, 20), (2, 12), (3, 8)]:
        for h in range(hrs + 1):
            t = base + pd.Timedelta(hours=h)
            for itemid, val in [(220045, 75), (220210, 16), (220277, 98), (220179, 120),
                                (223762, 37.0)]:
                rows.append(dict(stay_id=sid, hadm_id=sid, charttime=t, itemid=itemid,
                                 valuenum=val, value=None))
    chartevents = pd.DataFrame(rows)
    inputevents = pd.DataFrame([dict(stay_id=1, hadm_id=1,
                                     starttime=base + pd.Timedelta(hours=10),
                                     itemid=221906, rate=5, amount=1)])
    procedureevents = pd.DataFrame(columns=["stay_id", "hadm_id", "starttime", "itemid"])

    hv = score_news2(assemble_hourly_vitals(chartevents, cohort))
    ev = compute_stay_events(cohort, inputevents, procedureevents, hv)
    anchors = build_anchors(hv, ev)

    a1 = anchors[anchors.stay_id == 1]
    a2 = anchors[anchors.stay_id == 2]
    a3 = anchors[anchors.stay_id == 3]
    ok = True
    # Patient A: anchors from h6..h9 (pre-event, before escalation at h10), event=1
    exp_a1 = a1[a1.anchor_time == base + pd.Timedelta(hours=6)]
    if not (len(exp_a1) == 1 and exp_a1.iloc[0].event == 1
            and abs(exp_a1.iloc[0].T_hours - 4.0) < 1e-6 and exp_a1.iloc[0].cause == "deterioration"):
        ok = False; log.error("A failed: %s", exp_a1.to_dict("records"))
    # Patient B: all anchors censored (event=0, administrative)
    if not (len(a2) > 0 and (a2.event == 0).all() and (a2.cause == "administrative").all()):
        ok = False; log.error("B failed: %s", a2[["anchor_time", "event", "cause"]].to_dict("records"))
    # Patient C: censored by competing death (event=0, cause=death)
    if not (len(a3) > 0 and (a3.event == 0).all() and (a3.cause == "death").all()):
        ok = False; log.error("C failed: %s", a3[["anchor_time", "event", "cause"]].to_dict("records"))

    # ---- news2-only event mode: Patient A is escalated (vasopressor @ h10) but its
    # vitals NEVER sustain NEWS2>=7 -> in news2 mode this must be CENSORED, not an
    # event. This is the case the 2026-07 review specifically asked to verify. ----
    ev2 = compute_stay_events(cohort, inputevents, procedureevents, hv, event_mode="news2")
    anchors2 = build_anchors(hv, ev2)
    a1n = anchors2[anchors2.stay_id == 1]
    if not (len(a1n) > 0 and (a1n.event == 0).all() and (a1n.cause == "administrative").all()):
        ok = False
        log.error("news2-mode A failed (escalation must NOT be an event): %s",
                  a1n[["anchor_time", "event", "cause"]].to_dict("records"))
    # and its anchors must extend PAST hour 10 (escalation no longer truncates the
    # risk set) all the way to discharge at hour 20 minus the lookback window.
    if not (a1n["anchor_time"].max() > base + pd.Timedelta(hours=10)):
        ok = False
        log.error("news2-mode A failed: anchors stopped at/before escalation (h10), "
                  "should continue to discharge (h20)")

    print("SELFTEST", "PASS" if ok else "FAIL")
    return ok


# ── self-test for LABEL v2 + keep_high_anchors ───────────────────────────────
def selftest_v2():
    """Five hand-computable patients, one per v2 rule plus one negative control.

    NEWS2 arithmetic used below (UK NEWS2, see news2.py):
      stable  HR 75(0) RR 16(0) SpO2 98(0) SBP 120(0) T 37.0(0)  -> total 0, band 0
      HIGH    HR 75(0) RR 30(3) SpO2 88(3) SBP 85(3)  T 37.0(0)  -> total 9, band 2

    Expected labels:
      P10  HIGH at h2,h3 (adjacent)      -> v1 event h2      v2 event h2 rule (a)
      P11  HIGH at h2,h5 (gap 3h <= 4h)  -> v1 NO event      v2 event h2 rule (b)
      P12  HIGH at h2, dies h5           -> v1 NO event      v2 event h2 rule (c)
      P13  HIGH at h2, discharged h3     -> v1 NO event      v2 event h2 rule (d)
      P14  HIGH at h2,h9 (gap 7h > 4h)   -> v1 NO event      v2 NO event  (negative control)
    """
    base = pd.Timestamp("2150-01-01 00:00")
    STABLE = {220045: 75, 220210: 16, 220277: 98, 220179: 120, 223762: 37.0}
    HIGH   = {220045: 75, 220210: 30, 220277: 88, 220179: 85,  223762: 37.0}

    spec = {  # stay_id -> (stay_hours, high_hours, death_hour)
        10: (20, {2, 3}, None),
        11: (20, {2, 5}, None),
        12: (5,  {2},    5),
        13: (3,  {2},    None),
        14: (30, {2, 9}, None),
    }
    cohort = pd.DataFrame([
        dict(stay_id=sid, hadm_id=sid, subject_id=sid, intime=base,
             outtime=base + pd.Timedelta(hours=hrs),
             deathtime=(base + pd.Timedelta(hours=dh)) if dh else pd.NaT, dcm_flag=False)
        for sid, (hrs, _, dh) in spec.items()
    ])
    rows = []
    for sid, (hrs, highs, _) in spec.items():
        for h in range(hrs + 1):
            # write an explicit value EVERY hour so the 6h forward-fill can never
            # smear a HIGH reading into the following hours and fake a sustained run
            vals = HIGH if h in highs else STABLE
            for itemid, val in vals.items():
                rows.append(dict(stay_id=sid, hadm_id=sid, charttime=base + pd.Timedelta(hours=h),
                                 itemid=itemid, valuenum=val, value=None))
    chartevents = pd.DataFrame(rows)
    empty_in = pd.DataFrame(columns=["stay_id", "hadm_id", "starttime", "itemid", "rate", "amount"])
    empty_pr = pd.DataFrame(columns=["stay_id", "hadm_id", "starttime", "itemid"])

    hv = score_news2(assemble_hourly_vitals(chartevents, cohort))
    ok = True

    # the toy vitals must actually produce the bands the test assumes
    for sid, (_, highs, _) in spec.items():
        g = hv[hv.stay_id == sid].dropna(subset=["band"]).sort_values("hour")
        got = {int((pd.Timestamp(r.hour) - base) / pd.Timedelta(hours=1))
               for r in g.itertuples() if r.band == config.NEWS2_HIGH_BAND}
        if got != highs:
            ok = False
            log.error("P%d band setup wrong: HIGH hours %s, expected %s", sid, sorted(got), sorted(highs))

    ev1 = compute_stay_events(cohort, empty_in, empty_pr, hv, event_mode="news2", label_version="v1")
    ev2 = compute_stay_events(cohort, empty_in, empty_pr, hv, event_mode="news2", label_version="v2")
    e1 = ev1.set_index("stay_id"); e2 = ev2.set_index("stay_id")

    expect = {  # stay_id -> (v1 fires?, v2 event hour or None, v2 rule)
        10: (True,  2.0, "a_sustained"),
        11: (False, 2.0, "b_windowed"),
        12: (False, 2.0, "c_terminal"),
        13: (False, 2.0, "d_truncated"),
        14: (False, None, None),
    }
    for sid, (v1_fires, v2_h, v2_rule) in expect.items():
        if bool(pd.notna(e1.loc[sid, "deterioration_time"])) != v1_fires:
            ok = False
            log.error("P%d v1: expected fires=%s, got %s", sid, v1_fires, e1.loc[sid, "deterioration_time"])
        t2 = e2.loc[sid, "deterioration_time"]
        if v2_h is None:
            if pd.notna(t2):
                ok = False; log.error("P%d v2: expected NO event, got %s", sid, t2)
        else:
            got_h = (pd.Timestamp(t2) - base) / pd.Timedelta(hours=1) if pd.notna(t2) else None
            if got_h != v2_h or e2.loc[sid, "event_rule"] != v2_rule:
                ok = False
                log.error("P%d v2: expected h%s rule %s, got h%s rule %s",
                          sid, v2_h, v2_rule, got_h, e2.loc[sid, "event_rule"])

    # v2 must be a strict SUPERSET of v1 -- never later, never dropping an event
    for sid in spec:
        t1, t2 = e1.loc[sid, "deterioration_time"], e2.loc[sid, "deterioration_time"]
        if pd.notna(t1) and (pd.isna(t2) or t2 > t1):
            ok = False; log.error("P%d superset violated: v1=%s v2=%s", sid, t1, t2)

    # keep_high_anchors: P14 is HIGH at h2/h9 but never has an event, so those two
    # hours are droppable/keepable and make a clean test of the flag.
    a_drop = build_anchors(hv, ev2, keep_high_anchors=False)
    a_keep = build_anchors(hv, ev2, keep_high_anchors=True)
    n_drop = int(a_drop[a_drop.stay_id == 14]["already_high_at_anchor"].sum())
    n_keep = int(a_keep[a_keep.stay_id == 14]["already_high_at_anchor"].sum())
    if n_drop != 0 or n_keep != 2:
        ok = False
        log.error("keep_high_anchors: expected 0 kept when off and 2 when on, got %d / %d",
                  n_drop, n_keep)
    if len(a_keep) <= len(a_drop):
        ok = False; log.error("keep_high_anchors=True must produce MORE anchors (%d vs %d)",
                              len(a_keep), len(a_drop))

    print("SELFTEST_V2", "PASS" if ok else "FAIL")
    return ok


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--selftest-v2", action="store_true",
                    help="Unit-test label v2's four rules + keep_high_anchors on a toy cohort.")
    ap.add_argument("--hmax", type=int, default=config.HMAX_H)
    ap.add_argument("--event", choices=["composite", "news2", "escalation"], default="composite",
                    help="composite = escalation OR sustained NEWS2>=7 (original). "
                         "news2 = sustained NEWS2>=7 ONLY (focused base model). "
                         "escalation = first escalation of care / death / severe "
                         "physiological collapse, >2h after admission, on the "
                         "restricted eligible cohort. NEWS2 plays no part.")
    ap.add_argument("--escalation-min-hours", type=float, default=None,
                    help=f"cohort/event cutoff (default {config.ESCALATION_MIN_HOURS}h)")
    ap.add_argument("--include-ambiguous-escalation", action="store_true",
                    help="sensitivity analysis: also count amiodarone/lidocaine/alteplase "
                         "as escalation. Excluded by default -- amiodarone for rate control "
                         "in new AF is routine CCU care, not deterioration.")
    ap.add_argument("--label-version", choices=["v1", "v2"], default="v1",
                    help="v1 = NEWS2>=7 for 2 CONSECUTIVE hours (locked baseline). "
                         "v2 = adds windowed (2-in-4h) / terminal-death / truncated-record "
                         "rules; a strict superset of v1.")
    ap.add_argument("--keep-high-anchors", action="store_true",
                    help="Keep anchor hours where the patient is ALREADY at NEWS2>=7, flagged "
                         "as already_high_at_anchor, instead of dropping them. Train on them, "
                         "exclude them from evaluation. Independent of --label-version.")
    ap.add_argument("--vitals-from", default=None, metavar="TAG",
                    help="Reuse data/vitals_hourly_<TAG>.parquet instead of rebuilding the "
                         "hourly grid from chartevents (the grid does not depend on the label).")
    args = ap.parse_args()
    if args.selftest or args.selftest_v2:
        ok = True
        if args.selftest:
            ok = selftest() and ok
        if args.selftest_v2:
            ok = selftest_v2() and ok
        raise SystemExit(0 if ok else 1)
    else:
        run(hmax_h=args.hmax, event_mode=args.event, label_version=args.label_version,
            keep_high_anchors=args.keep_high_anchors, vitals_from=args.vitals_from,
            escalation_min_hours=args.escalation_min_hours,
            include_ambiguous_escalation=args.include_ambiguous_escalation)
