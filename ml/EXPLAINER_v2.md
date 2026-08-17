# Every Metric, Defined — Written So You Can Restate It Without Notes

For each metric: what it is in plain language, the exact formula with units, a
worked example on real numbers from this project, how to read it, and what it
cannot tell you.

**Rule of thumb before any of it:** if you cannot say *what the denominator is*,
you cannot defend the number. Almost every dispute in this project has been a
denominator dispute.

---

## 0. The three units, and why mixing them caused the last meeting to go badly

Every count in this project is in one of three units. They are not interchangeable
and a ratio built from two different units is meaningless.

| Unit | One item is… | How many in the 12h test set |
|---|---|---|
| **anchor / patient-hour** | one hourly snapshot of one patient | 39,046 |
| **alarm episode** | one continuous run of alerting hours for one patient | 2,069 |
| **patient** | one CCU stay | 1,236 |

The number that did not reconcile last time — "4.45 alerts per event dropped to
1.8" — divided **alerted rows** by **true-event rows** in one figure and
**episodes** by **caught patients** in the other. Different denominators, so the
"drop" was not a drop at all. That comparison is now deleted from the codebase.

---

## 1. PPV (= precision)

**Plain language.** Of the alarms the system raised, what fraction were followed by
a real deterioration.

**Formula.** `PPV = TP / (TP + FP)`, unitless, in [0,1].

**Which unit?** This project now reports **episode-PPV**:

```
episode-PPV = (alarm episodes followed by a real event within h) / (all alarm episodes)
```

**Worked example, 12h horizon, cell A:**
```
2,069 alarm episodes on the test set
  685 of them were followed by a deterioration within 12 hours
  episode-PPV = 685 / 2069 = 0.3311
```

**How to read it.** About 1 in 3 alarms is real. Equivalently 67% are false —
which is the number your professor called unusable. See §7 for what those 67%
actually are.

**Limitations.**
- PPV depends on the **alert threshold**. It is not a property of the model. Quote
  it only with its threshold and horizon.
- PPV depends on the **base rate**. A rarer event mechanically lowers PPV. So PPV
  is **not comparable across labels or across horizons** — use lift for that.
- PPV says nothing about the patients you missed. Pair it with recall, always.

**PPV = precision. Sensitivity = recall. Specificity is NOT 1 − PPV** — specificity
has the *negatives* in its denominator (`TN/(TN+FP)`), PPV has the *predicted
positives*. This correction is asserted in `eval_core.py`'s self-test.

---

## 2. Lift — the only fair comparator across labels

**Plain language.** How many times better than guessing.

**Formula.** `lift = PPV / base_rate`, unitless. 1.0× = no information. Ceiling =
`1 / base_rate`.

**Worked example, 12h:**
```
base_rate = 4,701 events / 39,046 known anchors = 0.1204
lift      = 0.3311 / 0.1204 = 2.750x
```
An alarm is 2.75 times more likely to precede a real deterioration than a patient
picked at random.

**Why it exists.** Label v2 raises the base rate from 0.1204 to 0.1322, so PPV
rises under v2 **no matter how good the model is**. Lift divides prevalence back
out: a no-skill model scores exactly 1.0× under either label. If someone says
"your precision improved," the honest check is whether lift improved.

**Limitation.** Lift falls automatically as the horizon grows (base rate grows), so
it is comparable *across labels at a fixed horizon*, not across horizons.

---

## 3. Patient-level recall — the number that matters clinically

**Plain language.** Of the patients who deteriorated, how many did the system warn
about at least once.

**Formula.**
```
patient recall = (deteriorating patients with >=1 alerting hour inside the h before their event)
                 / (all deteriorating patients)
```

**Worked example, 12h:** `621 / 642 = 0.9673`.

**How to read it.** The system flags 97% of deteriorating patients at least once.
**This is not the same as the 77% row-level sensitivity** — that one asks "of all
patient-hours that should have alerted, how many did," which is a much harsher and
much less clinically meaningful question. A patient warned about once, in time, is
caught.

**Limitation.** Says nothing about *how early*. Pair with lead time (§5).

---

## 4. Alarm burden — episodes per patient-day

**Formula.**
```
episodes / (n_anchors / 24)          [one anchor = one patient-hour]
```

**Worked example, 12h:** `2,069 / (39,046/24) = 1.272 episodes per patient-day`.

**How to read it.** A patient generates roughly **1.3 alarms per day of CCU stay**.
That is the number a nurse manager cares about, and it is the honest replacement
for "alerts per event."

**Limitation.** It is an average over a heterogeneous population; a small number of
unstable patients generate disproportionately many.

---

## 5. Detection lead time

**Plain language.** How much warning a correct alarm actually bought.

**Formula.** `T_hours` at the episode's **first** alerting hour = hours from that
alert to the event. Reported as a median over true episodes.

**Worked example, 12h:** median **7.0 hours**.

**Why it must accompany any precision claim.** Persistence voting raised PPV to
0.3810 *and raised* median lead time to 8.0h — which sounds good until you see it
happened because the short-lead detections were **deleted**, not improved. Lead
time going up can be a symptom of losing your fastest patients.

---

## 6. C-index (Harrell's concordance)

**Plain language.** Of all pairs of patients whose ordering we can actually
determine, how often does the model rank the one who deteriorated sooner as riskier.

**Formula.** Over all comparable (non-censored-ambiguous) pairs:
`C = P(model ranks the earlier-event patient as higher risk)`. 0.5 = coin flip.

**Worked example.** Cell A test = **0.786**, 95% CI [0.767, 0.806]. NEWS2-slope
ruler = 0.545.

**How to read it.** Threshold-free, horizon-free summary of ranking quality. Good
for comparing models; useless for deciding when to alarm.

**Limitations — both important here.**
- **Quote three decimals at most.** Changing nothing but the random patient
  partition moved this model from 0.7906 to 0.7860. The fourth decimal is noise.
- The whole architecture ablation spans 0.0093 while the CI is ~0.040 wide. When
  differences are smaller than the CI, say "indistinguishable", not "better."

---

## 7. What a "false alarm" actually is — the answer to "80–90% false positives"

Of the 1,622 false alert episodes at 12h under label v1:

| | count | share |
|---|---|---|
| patient **never** reached NEWS2≥7 at any point in the stay | **439** | **27.1%** |
| patient hit NEWS2≥7 but never for 2 consecutive hours (the label-v2 group) | 814 | 50.2% |
| patient sustained NEWS2≥7, just outside this prediction window | 369 | 22.7% |

**How to say it.** *"The unambiguous false-alarm rate is 27% of episodes, not 90%.
Half of what was being counted as false fired on patients who visibly crossed
NEWS2≥7 — the model saw it and the label scored it wrong."*

**Limitation, volunteer it:** the 22.7% "outside the window" group is measured at
the stay level, so it includes events far outside 24h. Only 4.8% of all episodes
are rigorously "correct but early" (event within 24h, beyond 12h). Do not claim the
whole 22.7% as early warnings.

---

## 8. The alert threshold — a chosen operating point, not a result

**How it is set.** The score at which 80% of true events fall above the line, **fitted
on the calibration split**, then frozen and applied to test.

**Worked example, 12h (stable split, cell A):**
```
threshold fit on TEST  (old, circular) : 0.089763  -> test sensitivity 0.8205
threshold fit on CALIB (correct)       : 0.093262  -> test sensitivity 0.8113
```

**Why the old number was circular.** It used to be fitted on the *test* set's own
labels, making "80% sensitivity" true by construction on the data it was reported
on. Moving it to calibration makes it a real out-of-sample number.

**The right thing to say about the small miss:** the honest out-of-sample
sensitivity is **81.1%**, against an 80% target — it misses by 1.1 points, and in
this run it misses *upward*. The direction is not the point; the **size** is. A
miss that small means the calibration and test score distributions are close, i.e.
the model generalises. Had it landed at 60% you would have a distribution-shift
problem.

**Do not over-narrate this.** The miss direction depends on the partition: an
earlier run on a different split gave 77.2%. What is stable across partitions is
that the miss is ~1–3 points, not that it goes one way.

**What is and is not evidence.** The 80% is chosen. The evidence is what PPV, lift,
recall and alarm burden do *at* that point — none of those are constrained.

---

## 9. The episode-gap parameter — a definition, sensitivity-tested

Two alerting hours belong to the same episode if they are **≤ 2 hours apart**
(`EPISODE_GAP_H = 2.0`, timestamp-based).

```
 gap_h   episodes   ep-PPV   patient-recall   ep/pat-day
   1.0      3,467   0.3098           0.9673        2.131
   2.0      2,069   0.3311           0.9673        1.272   <- chosen
   4.0      1,754   0.3683           0.9673        1.078
   8.0      1,513   0.4111           0.9673        0.930
  12.0      1,394   0.4455           0.9673        0.857
```

**Two things to say about this table.**
1. **Patient recall is invariant.** Merging alarms never changes whether a patient
   was caught — so this knob cannot fake a better model, only a more or less
   honest count.
2. **2.0 is the conservative end, chosen deliberately.** 12h would report 0.4455
   instead of 0.3311 for free. 2h merges a single-hour dip below threshold — the
   known artefact — and nothing more.

**If asked why not 4 or 12:** *"Because 12 would have reported 0.4455 instead of
0.3311 — a 35% higher precision — purely by redefining what counts as one alarm.
I couldn't justify that clinically, and patient recall is identical at every value,
so nothing about detection improves."*

---

## 10. Severity — validated as an ORDER, not as a clock

**What it is.** `cond_time_24h = E[T | T ≤ 24h]`, the probability-weighted average
of the seven interval midpoints. Shorter = more urgent.

**The claim under test:** does a shorter *predicted* time mean a sooner *actual*
event? Measured on 7,166 event anchors:

| severity bin | n | median PREDICTED | median ACTUAL | median risk@12h |
|---|---|---|---|---|
| 1 (most urgent) | 1,434 | 7.48h | **5.00h** | 0.4276 |
| 2 | 1,433 | 8.95h | 8.00h | 0.2894 |
| 3 | 1,433 | 10.25h | 9.00h | 0.1958 |
| 4 | 1,433 | 11.35h | 11.00h | 0.1164 |
| 5 (least urgent) | 1,433 | 12.85h | **12.00h** | 0.0671 |

**Monotonic across all five bins.** Spearman **+0.295** (p = 4.3e-144). Risk at 12h
falls monotonically too — an independent coherence check.

**How to read it, and the limitation in the same breath.** The predicted range
spans 7.5–12.9h while the actual range spans 5–12h: the estimate is **compressed**,
because it is an average over only seven interval midpoints. So the ordering is
trustworthy and the absolute value is not.

**Use it to sort the worklist. Never say "this patient will deteriorate in 7.5
hours."** That is the same fake-precision error that made the original AFT median
misleading.

---

## 11. Ensemble uncertainty — a confidence measure, from his own paper

**What it is.** Six networks differing only in random initialisation and batch
shuffling. Their **mean** is the prediction; their **standard deviation** is the
confidence (his paper §5, Eq 7–8).

```
Patient A: [0.31, 0.29, 0.34, 0.30, 0.33, 0.28] -> mean 0.31, std 0.02
Patient B: [0.55, 0.12, 0.61, 0.09, 0.48, 0.15] -> mean 0.33, std 0.22
```
Same mean risk; A's answer is in the data, B's is an artefact of where training
started.

**Does it work here?** Tested before being used. Among alerting anchors at 12h,
precision is **0.3435** in the lowest-disagreement decile vs **0.2346** in the
highest (spread +0.109, Spearman −0.067). It passes at all 7 horizons — his
turbofan result transfers to vitals.

**How it is used.** Two tiers at the **episode** level: **PAGE** (risk high AND the
ensemble agrees) vs **WATCH** (risk high, ensemble disagrees). PAGE episode-PPV
0.3203 vs WATCH 0.2653 at 12h — the separation is real.

**The critical design point.** **Nothing is suppressed.** A WATCH episode still
appears on the worklist; it just does not interrupt anyone. Total detection stays
at 0.9782. This is the opposite of persistence voting, which *deleted* alerts and
permanently lost 58% of the fastest deteriorators.

**Limitation.** The PPV gain is small (+0.013 at 12h, +0.038 at 24h). The value is
the triage structure and the fact that it costs zero detection — not the precision
number.

---

## 12. Numbers to never quote alone

| Number | Why |
|---|---|
| **PPV across two labels** | base rate differs (0.1204 v1 vs 0.1322 v2) — use lift |
| **Any C-index to 4 decimals** | the random partition alone moves it ±0.005 |
| **"80% sensitivity"** | a chosen operating point; the real out-of-sample value is 81.1% |
| **Episode counts without the gap parameter** | 1.0h gives 3,467 episodes, 12h gives 1,394 |
| **"alerts per event"** | retired — it is `1/PPV` with no reference point |
| **A precision gain without its recall cost** | persistence gained +18% PPV by losing 14 points of recall |

---

## 13. The four converging negative results — the most defensible thing in this project

| Direction tried | Result |
|---|---|
| Add labs/congestion features | AUC 0.8099 → 0.8096. Null. |
| AFT → discrete-time hazard framing | C-index 0.789 → 0.791. Negligible. |
| Parameter sharing across intervals (cell B) | C-index 0.7860 → 0.7853. Null. |
| Neural architecture (cells C, D) | 0.7779 / 0.7767. Slightly worse. |

**Four independent research directions, four dead ends, one consistent
explanation:** the ceiling is the information content of NEWS2-derived features
against a NEWS2-threshold label — **not the model family, and not feature
richness.**

One negative result is a disappointment. Four converging ones with a stated
mechanism is a finding, and it is the strongest claim this project can make.

**What would actually move it** (say this if asked "so what next"): higher-frequency
monitoring data, which would also address the 54.3% of fast deteriorators who
cannot produce two readings before they crash — the same population that persistence
voting was shown to destroy. Not another model.
