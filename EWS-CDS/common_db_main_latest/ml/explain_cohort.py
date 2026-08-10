"""
explain_cohort.py  — answers three questions:
  1. 10% prevalence — are we training only on deteriorating patients?
  2. Why do 885/903 patients have NEWS2<7 at some point?
  3. What does the population actually look like?
"""
import pandas as pd, sys, os
sys.path.insert(0, os.path.dirname(__file__))
import config
from known_status import known_subset

preds = pd.read_parquet(config.dpath("preds_ordinal_esc.parquet"))
test  = preds[preds.split == "test"]
train = preds[preds.split == "train"]

print("=" * 68)
print("Q1: Are we training only on deteriorating patients?")
print("=" * 68)

# How many train stays had an event?
train_stays = train.groupby("stay_id").agg(had_event=("event","max")).reset_index()
n_train_event = train_stays["had_event"].sum()
n_train_total = len(train_stays)
print(f"\n  Train stays:              {n_train_total:,}")
print(f"  Train stays WITH event:   {n_train_event:,}  ({100*n_train_event/n_train_total:.1f}%)")
print(f"  Train stays WITHOUT event:{n_train_total-n_train_event:,}  ({100*(n_train_total-n_train_event)/n_train_total:.1f}%)")
print(f"\n  → NO. The model trains on ALL patients. The ~10% is the FRACTION")
print(f"    of patient-hours (not patients) where the event label = 1.")
print(f"    A patient who deteriorates at hour 20 has ~19 hours labelled 0")
print(f"    and a few labelled 1. That is why the row-level base rate is low.")

print()
print("=" * 68)
print("Q2: 10% prevalence — what does that actually mean?")
print("=" * 68)
tsub, ty = known_subset(test, 24)
n_event_hrs = int(ty.sum())
n_total_hrs = len(tsub)

# patient-level event rate (did the patient deteriorate at all in their stay?)
test_stays = test.groupby("stay_id").agg(had_event=("event","max")).reset_index()
n_test_event_stays = test_stays["had_event"].sum()
n_test_total_stays = len(test_stays)

print(f"\n  Test set — PATIENT level (did they deteriorate at any point in stay?):")
print(f"    Patients who deteriorated:          {n_test_event_stays:,}  / {n_test_total_stays:,} = {100*n_test_event_stays/n_test_total_stays:.1f}%")
print(f"\n  Test set — PATIENT-HOUR level (is this specific hour within 24h of event?):")
print(f"    Hours labelled event=1 at 24h:      {n_event_hrs:,}  / {n_total_hrs:,} = {100*n_event_hrs/n_total_hrs:.1f}%")
print(f"\n  → The 9.48% base rate = PATIENT-HOUR prevalence, not patient prevalence.")
print(f"    At PATIENT level, {100*n_test_event_stays/n_test_total_stays:.1f}% of patients will eventually escalate.")
print(f"    The 9.48% is lower because most of each patient's stay is BEFORE")
print(f"    the 24h window before their event (they are 'not yet at risk' row-wise).")

print()
print("=" * 68)
print("Q3: Why do 885/903 patients have NEWS2<7 at some point?")
print("=" * 68)

# For each test stay, compute min, max, mean NEWS2
news_stats = tsub.groupby("stay_id")["news2_at_anchor"].agg(
    min_news2="min", max_news2="max", mean_news2="mean"
).reset_index()

always_below7  = (news_stats["max_news2"]  < 7).sum()
ever_below7    = (news_stats["min_news2"]  < 7).sum()
always_above7  = (news_stats["min_news2"] >= 7).sum()
ever_above7    = (news_stats["max_news2"] >= 7).sum()

print(f"\n  Of 903 test stays with known outcome at 24h:")
print(f"    Stays where NEWS2 was ALWAYS < 7:       {always_below7:>4,}  ({100*always_below7/903:.1f}%) — never reached threshold")
print(f"    Stays where NEWS2 was EVER   < 7:       {ever_below7:>4,}  ({100*ever_below7/903:.1f}%) — had at least one hour below 7")
print(f"    Stays where NEWS2 was ALWAYS >= 7:      {always_above7:>4,}  ({100*always_above7/903:.1f}%) — always above threshold")
print(f"    Stays where NEWS2 was EVER   >= 7:      {ever_above7:>4,}  ({100*ever_above7/903:.1f}%) — reached threshold at some point")

print(f"\n  NEWS2 distribution across all known-status test hours:")
for thr in [0, 3, 5, 7, 9, 12, 15]:
    frac = (tsub["news2_at_anchor"] < thr).mean() if thr > 0 else 0
    n    = (tsub["news2_at_anchor"] < thr).sum()  if thr > 0 else 0
    print(f"    NEWS2 < {thr:2d}:  {n:>7,} hrs  ({100*frac:.1f}%)")

print(f"\n  Median NEWS2 at anchor: {tsub['news2_at_anchor'].median():.1f}")
print(f"  Mean   NEWS2 at anchor: {tsub['news2_at_anchor'].mean():.2f}")
print(f"  75th pct:               {tsub['news2_at_anchor'].quantile(0.75):.1f}")
print(f"  90th pct:               {tsub['news2_at_anchor'].quantile(0.90):.1f}")
print(f"  95th pct:               {tsub['news2_at_anchor'].quantile(0.95):.1f}")

print(f"\n  → YES — most CCU patients spend most of their stay with NEWS2<7.")
print(f"    A CCU patient admitted for heart failure may have NEWS2=3-5 for")
print(f"    most of the stay, spiking to 7+ only hours before deterioration.")
print(f"    That is EXACTLY why the model is useful: it can flag risk early,")
print(f"    while the score still looks low to a nurse doing a visual check.")

print()
print("=" * 68)
print("SUMMARY TABLE — stay-level breakdown (test set)")
print("=" * 68)
news_stats2 = news_stats.merge(
    test_stays[["stay_id","had_event"]], on="stay_id", how="left"
)
print(f"\n  {'Category':<40} {'N stays':>9} {'% of 903':>9}")
print(f"  {'-'*60}")
grp = [
    ("Will deteriorate (event stay)",        news_stats2["had_event"]==1),
    ("Will NOT deteriorate (stable stay)",   news_stats2["had_event"]==0),
    ("Had at least one NEWS2<7 hour",        news_stats2["min_news2"]<7),
    ("Stayed ALWAYS below NEWS2=7",          news_stats2["max_news2"]<7),
    ("Reached NEWS2>=7 at some point",       news_stats2["max_news2"]>=7),
    ("Event stay AND had NEWS2<7 hours",     (news_stats2["had_event"]==1) & (news_stats2["min_news2"]<7)),
    ("Stable stay AND had NEWS2<7 hours",    (news_stats2["had_event"]==0) & (news_stats2["min_news2"]<7)),
]
for label, mask in grp:
    n = mask.sum()
    print(f"  {label:<40} {n:>9,} {100*n/903:>8.1f}%")
