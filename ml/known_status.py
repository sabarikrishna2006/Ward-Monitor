"""
Censoring-correct within-horizon labeling.

THE BUG THIS FIXES: naively labeling `y = (event==1) & (T_hours <= h)` silently
counts patients CENSORED BEFORE h as confirmed negatives. A patient discharged
at hour 8 with horizon h=12 has UNKNOWN status at hour 12 -- they left the risk
set before we could observe it. Counting them as "did not deteriorate by 12h"
corrupts every downstream count (inflates TN, deflates the false-positive rate,
makes the model look better than it is).

The correct rule: an anchor's status at horizon h is only KNOWN if either
  (a) the event occurred at or before h (a known positive), or
  (b) the anchor was still under observation at h, i.e. its censoring/event
      time T_hours >= h (a known negative).
Anyone with T_hours < h and event==0 has UNKNOWN status at h and must be
dropped from any metric computed at that horizon (not treated as a negative).

This is the standard "administrative censoring at a fixed horizon" rule used
throughout survival analysis (e.g. Kaplan-Meier risk sets, time-dependent AUC).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def known_at(df: pd.DataFrame, h: float) -> np.ndarray:
    """Boolean mask: True where the anchor's status AT horizon h is knowable."""
    event = df["event"].values.astype(bool)
    T = df["T_hours"].values.astype(float)
    return (event & (T <= h)) | (T >= h)


def label_at(df: pd.DataFrame, h: float) -> np.ndarray:
    """
    Ground-truth label 'deteriorated by hour h', defined ONLY where known_at() is
    True. Callers MUST filter to known_at(df, h) before using this label --
    calling label_at alone on the full (unfiltered) frame silently reproduces the
    bug this module exists to fix.
    """
    event = df["event"].values.astype(bool)
    T = df["T_hours"].values.astype(float)
    return (event & (T <= h)).astype(int)


def known_subset(df: pd.DataFrame, h: float) -> tuple[pd.DataFrame, np.ndarray]:
    """Convenience: return (df restricted to known-status rows, their labels at h)."""
    mask = known_at(df, h)
    sub = df.loc[mask]
    y = label_at(sub, h)
    return sub, y


def dropped_fraction(df: pd.DataFrame, h: float) -> float:
    """Fraction of anchors with UNKNOWN status at h (censored before h, no event) --
    report this on any horizon-metrics slide; a large value means the horizon is
    stretching past what the data can actually confirm."""
    mask = known_at(df, h)
    return float(1.0 - mask.mean()) if len(df) else float("nan")


def _selftest():
    df = pd.DataFrame([
        dict(name="event_early",   event=1, T_hours=4.0),   # deteriorated at 4h -> known positive at h=12
        dict(name="event_late",    event=1, T_hours=20.0),  # deteriorated at 20h -> known NEGATIVE at h=12
        dict(name="censored_long", event=0, T_hours=18.0),  # observed to 18h, no event -> known negative at h=12
        dict(name="censored_short",event=0, T_hours=8.0),   # discharged at 8h, no event -> UNKNOWN at h=12 (the bug case)
        dict(name="event_at_h",    event=1, T_hours=12.0),  # deteriorated exactly at h -> known positive
    ])
    h = 12.0
    known = known_at(df, h)
    expected_known = np.array([True, True, True, False, True])
    assert (known == expected_known).all(), f"known_at mismatch: {known} vs {expected_known}"

    sub, y = known_subset(df, h)
    assert list(sub["name"]) == ["event_early", "event_late", "censored_long", "event_at_h"], \
        f"known_subset dropped the wrong row(s): {list(sub['name'])}"
    assert list(y) == [1, 0, 0, 1], f"label_at wrong: {list(y)}"

    frac = dropped_fraction(df, h)
    assert abs(frac - 0.2) < 1e-9, f"dropped_fraction wrong: {frac} (expected 0.2, 1/5 rows)"
    print("SELFTEST PASS -- known_status.py")


if __name__ == "__main__":
    _selftest()
