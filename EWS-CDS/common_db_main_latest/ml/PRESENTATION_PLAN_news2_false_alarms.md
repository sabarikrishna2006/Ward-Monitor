# Presentation Plan — Reducing False Alarms on the NEWS2 Model

Every number below is measured on the test split with the threshold fitted on the
calibration split. Nothing here reuses an old chart.

**Read this first:** the numbers you can defend today are in §A. The one thing you
asked for that is NOT yet measured on the NEWS2 target is flagged in §B — do not put
it on a slide until it returns.

---

## §A — The story, in the order it should be told

The spine is not "we improved the model." It is:

> **The false-alarm number was wrong three different ways. Fixing the measurement,
> the alerting behaviour, and the presentation order cut alarms by half without
> losing patients — and I can show which of the three is which.**

That framing survives cross-examination because it concedes what is bookkeeping
before anyone asks.

---

### Slide 1 — What the model does, in one sentence and one number

> Every hour, for every CCU patient, predict the probability they will cross
> NEWS2 ≥ 7 (sustained 2h) within the next 2/4/6/9/12/18/24 hours.

| | |
|---|---|
| Patients | 7,860 CCU stays (MIMIC-IV, Beth Israel, 2008–2019) |
| Prediction rows | 298,679 hourly anchors |
| Test C-index | **0.786** [0.767, 0.806] |
| AUC @12h | **0.812** |
| NEWS2-slope ruler (must-beat floor) | 0.545 |

**Say the patient count out loud, not the row count.** 298,679 rows come from 7,860
people; hourly rows from one patient are correlated, which is why the split and every
confidence interval is by `subject_id`.

**If asked "why is C-index only 0.79":** it is 0.79 against a floor of 0.545, and the
partition alone moves it ±0.005 — quote three decimals, never four.

---

### Slide 2 — Defect 1: false positives were counted in the wrong unit

This is the strongest opening because it is a defect you found and fixed, not a claim.

| | ep-PPV @12h |
|---|---|
| As originally reported (per patient-hour) | 0.234 |
| Corrected — per **alarm episode** | **0.331** |

**The argument:** a stable patient with 60 charted hours was 60 separate chances to be
a false positive. A patient who deteriorates at hour 3 was 3. So the false-positive
count was dominated by long-stay stable patients — which is not what a clinician
experiences. **One continuous run of alerting = one alarm a nurse responds to.**

Two sub-fixes inside this, worth one line each:
- The old episode-merger used **positional** adjacency (`shift(1)`), so two alarms
  hours apart merged if no anchor was charted between them. Now timestamp-based.
- The alert threshold was fitted on the **test set's own labels**, making
  "80% sensitivity" true by construction. Moved to the calibration split: honest
  out-of-sample sensitivity is **81.1%**, not 80%.

**Volunteer the second one.** "I audited my own evaluation and found the operating
point was fitted on test" converts a liability into evidence of rigour.

---

### Slide 3 — Defect 2: most "false" alarms were not false

Of the 1,384 false alarm episodes at 12h:

| | count | share |
|---|---|---|
| Patient **never** reached NEWS2 ≥ 7 at any point in the stay | **360** | **26.0%** |
| Patient hit NEWS2 ≥ 7 but never for 2 consecutive hours | 700 | 50.6% |
| Patient sustained NEWS2 ≥ 7, outside this prediction window | 324 | 23.4% |

> **The unambiguous false-alarm rate is 26% of episodes, not 90%.** Half of what was
> counted as false fired on patients who visibly crossed the critical threshold — the
> model saw it and the label scored it wrong.

**Expected challenge — "so fix the label."** Answer: I did, and measured it. Label v2
(2 high hours within any 4h window) recovers **515 of 2,019** such patients. It cannot
recover more: **1,008 had exactly one high hour ever**, and no two-reading rule reaches
them. Result: episode-PPV rose 0.331 → 0.345 but **lift fell 2.750 → 2.610**.

**Then the sharper follow-up you should pre-empt:** lower lift on a looser label is
ambiguous — the task also got harder. The 2×2 settles it (same 261,436 anchors, split
agreement 100%):

| | evaluated on v1 labels | evaluated on v2 labels |
|---|---|---|
| trained on v1 | AUC 0.7956, AUPRC 0.3086 | AUC 0.7948 |
| trained on v2 | **AUC 0.7982, AUPRC 0.3208** | AUC 0.7968 |

Training on v2 wins on the **original** label too (+0.0026 AUC, **+4.0% relative
AUPRC**). So v2 is a genuinely better training signal and the headline drop was
entirely the harder target. **State the size honestly** — +0.0026 AUC is inside the CI;
the AUPRC gain is the more credible signal.

---

### Slide 4 — The episode-gap parameter: a convention, shown as a curve

He asked you to define this carefully. Show all of it.

| gap | episodes | ep-PPV | **patient recall** | alarms/day/100 |
|---|---|---|---|---|
| 1h | 3,467 | 0.3098 | **0.9673** | 213 |
| **2h** | **2,069** | **0.3311** | **0.9673** | **127** |
| 4h | 1,754 | 0.3683 | **0.9673** | 108 |
| 8h | 1,513 | 0.4111 | **0.9673** | 93 |
| 12h | 1,394 | 0.4455 | **0.9673** | 86 |

**Two sentences that must be said:**

1. **Patient recall is identical at every value.** Merging never changes whether a
   patient was caught, so this parameter changes *counting*, not *detection* — it
   cannot be used to fake a better model, only a more or less honest count.
2. **I chose 2h, the conservative end, deliberately.** 12h would report 0.4455 instead
   of 0.3311 — 35% higher precision — for free. 2h merges a single-hour dip below
   threshold, the known artefact, and nothing more.

**If he asks why not 8h:** published precedent exists at 4h (MEWS++), 6h (DETERIO, as
a disclosed "end-user clinical response policy") and 8h (Mayo MC-EWS). So 8h is
defensible — but it must be reported as a *response policy*, never as a model
improvement, and I would rather show the whole curve than pick the flattering point.

---

### Slide 5 — The sensitivity operating point, benchmarked against the field

| target sens | row-PPV | ep-PPV | **ep-LIFT** | patient recall | alarms/day/100 | lead time |
|---|---|---|---|---|---|---|
| **80%** | 0.248 | **0.331** | **2.750** | **0.967** | 127 | 7.0h |
| 70% | 0.292 | 0.357 | 2.963 | 0.932 | 117 | — |
| 60% | 0.334 | 0.390 | 3.241 | 0.882 | 103 | — |
| 50% | 0.381 | 0.423 | 3.515 | 0.822 | 88 | — |
| 30% | 0.476 | 0.510 | 4.237 | 0.618 | 55 | — |
| 20% | 0.555 | 0.578 | **4.800** | 0.494 | 38 | — |

**Lift rises monotonically 2.750 → 4.800.** The base rate is fixed, so this is a
genuine increase in the information each alert carries — not a definitional shift.

**Then the field comparison, which is your strongest single slide** (JAMIA 2024
systematic review, 14 deployed systems + DETERIO):

| System | sensitivity | PPV |
|---|---|---|
| **MEWS++** (Icahn, RF, 36 vars) | **79%** | **12%** |
| MC-EWS (Mayo, GBM, 59 vars) | 73% | 12% |
| **OURS @12h** | **81%** | **25% row / 33% episode** |
| APPROVE (Mayo, RF) | 63% | 21% |
| DETERIO (UCSD, NN, 229 vars) | 46% | 22% |
| Epic Deterioration Index | 39% | 74% |
| CHARTwatch (526 vars) | 40% | 71% → **17–26% deployed** |
| DEWS (LSTM) | 37% | **4%** |
| eCARTv2 | — | 8.2% |

> **At 79–81% sensitivity the published field achieves 12% PPV. We achieve 25–33% —
> roughly twice the best comparable deployed system.**

**Say the caveat every time:** our label is NEWS2 ≥ 7, a same-signal target; theirs are
independent outcomes (ICU transfer, arrest, death). Favourable but not perfectly
apples-to-apples.

**And the honest counterweight:** the field sets thresholds to hit an alert budget of
**3–10 alerts/day/100 patients** and accepts 25–63% sensitivity to get there. We run at
81% sensitivity and 127 alerts/day/100. **We are far noisier in absolute terms**, because
our target occurs in 50.3% of CCU stays versus 2.1–32.8% in the field. Pre-empt this;
do not let him find it.

---

### Slide 6 — Hysteresis: the one change that costs nothing

**The idea in one line:** a single threshold makes a patient hovering at the boundary
flicker on and off, generating several alarms out of measurement noise. Fire at
`τ_high`, and keep firing until risk drops below a lower `τ_low` — a Schmitt trigger,
the same mechanism that stops a thermostat cycling every thirty seconds.

**This is behaviour, not bookkeeping.** The episode gap merges alarms *after the fact
inside the metric*; hysteresis stops the second alarm being *generated*.

Replicated at three horizons, `τ_low` = 50% of `τ_high`:

| horizon | episodes | ep-PPV | ep-LIFT | patient recall | alarms/day/100 |
|---|---|---|---|---|---|
| 6h | 2,321 → **1,754** | 0.2714 → **0.3529** | 4.171 → **5.423** | 0.9439 → **0.9502** | 128 → **97** |
| 12h | 2,069 → **1,551** | 0.3311 → **0.4101** | 2.750 → **3.406** | 0.9673 → **0.9751** | 127 → **95** |
| 24h | 1,693 → **1,307** | 0.4341 → **0.4996** | 1.908 → 2.195 | 0.9782 → 0.9782 | 129 → **100** |

**Alarms −25%, precision +24%, recall up, and nothing traded.**

**The self-criticism you must include, because it is what makes the rest credible:**

- Part of the PPV gain is merging, like the gap. Decomposed at 12h: true episodes fell
  **7%** while false fell **34%** — false alarms are *flicker* near the threshold, true
  alarms are *sustained*, so hysteresis merges the false ones preferentially. Real
  separation, but still partly a counting effect.
- **I initially claimed rising lead time proved genuine earlier detection. That was
  wrong** — the episode gap alone raises lead time 7.0 → 9.8h, because merging makes an
  episode inherit the earlier start. Lead time is not merging-independent.
- What survives as non-definitional: **patient recall**, which counts patients not
  episodes and therefore cannot be inflated by merging. It went up.
- **Human-factors caveat to volunteer:** the nurse now sees fewer but *longer* alarms. A
  continuously-latched alert can be its own nuisance. Whether 95 long alarms beat 127
  short ones is a question for Harshika, not for me.

---

### Slide 7 — Three kinds of "false-alarm reduction"

This is the slide that wins the meeting. Put it late, keep it simple.

| Kind | Lever | Recall cost | What it actually is |
|---|---|---|---|
| **Counting** | episode gap | none — recall invariant | a reporting convention |
| **Behaviour** | hysteresis | none | an implementable system property |
| **Frontier** | sensitivity / horizon | real | a genuine precision-for-recall trade |

> **Only the third is a real trade. The first is bookkeeping. The second is
> engineering. Two of my three headline improvements are not model improvements, and
> I can tell you which.**

---

### Slide 8 — What was tried and failed

Never hide this. Five named negatives make everything else believable.

| Attempt | Result |
|---|---|
| **Persistence voting (k-of-m)** | +18% PPV, −34% alarms — **but drops 58% of patients having only 1–2 pre-event observations.** It cannot fire on someone who crashes after two readings. Rejected on clinical grounds. |
| **Interval voting (OR / majority)** | Provably a no-op: `P(T≤2h) ≤ … ≤ P(T≤24h)` by construction, so every k-of-7 vote equals thresholding one horizon. Agreement **1.0000**. |
| **Anchor-level uncertainty gating** | Splits an episode mid-run → PPV moved **backwards** 0.3073 → 0.2834. |
| **Hard alarm budget cap** | Suppresses the 11th real alert to protect a metric. Clinically indefensible. |
| **Labs added to a NEWS2 target** | Null — and now explained: NEWS2 is computed from 7 vitals, so lactate/BNP/creatinine can only act indirectly. **Arithmetic, not bad luck.** |
| **Architecture: 7 independent → pooled XGBoost → multi-head MLP → cumulative MLP** | Total spread **0.0093** across all four, against CIs ~0.040 wide. Parameter sharing changed C-index by **−0.0007**. |

**On the architecture point specifically** — this is his own #1 criticism, so lead with
the concession: *"You were right that the seven boosters are independent; that's
literally what the code does. So I built the pooled version that shares parameters
with the base learner held fixed. It moves C-index by 0.0007. Sharing helps the
data-poor late intervals and hurts the data-rich early one, and they cancel."*

| Interval | Train rows | A (independent) | B (shared) |
|---|---|---|---|
| ≤2h | 199,184 | **0.8707** | 0.8645 |
| ≤12h | 149,389 | 0.7387 | **0.7455** |
| ≤24h | 105,416 | 0.7192 | **0.7206** |

---

### Slide 9 — Bridge to the escalation model (2 slides maximum)

Do not open this until the NEWS2 story has landed.

**The one finding that motivates it:** NEWS2 ≥ 7 occurs in **50.3%** of CCU stays,
against a published ICU range of **11.3–32.8%**. And its protocol action is *"escalate
to ICU-level care"* — which these patients already receive. **The alert is actionless
in a CCU, and that is why 127 alarms/day/100 patients is unavoidable.**

Then the headline result and stop:

| | NEWS2 target, 12h | Escalation target, 24h + hysteresis |
|---|---|---|
| episode-LIFT | 2.750 | 2.729 — equal |
| patient recall | 0.9673 | 0.9703 |
| alarms/day/100 | 127 | **67** |
| median lead time | 7.0h | **11.0h** |
| **PPV on the top 10% of the worklist** | — | **0.5704** |

Plus one sentence on the mechanism: anion gap took the #1, #2, #3 and #5 slots by
feature gain — metabolic acidosis moves *before* the vitals do, which is exactly the
"NEWS2 = 3 but deteriorating" patient. **83.1% of total gain came from newly extracted
features.** And this matches published ICU work, which finds labs and organ-function
markers outrank hemodynamic fluctuations.

---

## §B — The lookback window: a NULL on NEWS2, and that is the point

**Insert this as Slide 6b, immediately before the bridge. It is the strongest slide in
the deck.**

The multi-window feature set (2h/6h/12h means, standard deviations, slopes, explicit
`mean_2h − mean_12h` crossovers, plus measured MAP, HCO3, anion gap, lactate, infusion
titration, hours-since-measured) was run against **both** targets on the same split:

| | 55 NEWS2 features | 370 multi-window features | Δ AUC |
|---|---|---|---|
| **NEWS2 ≥ 7 target** | 0.8120 | 0.8141 | **+0.0021** |
| **escalation target** | 0.7249 | 0.7974 | **+0.0725** |

**The same features are worth 35× more on one target than the other.**

Full NEWS2-target detail (cell B), so the reject is defensible:

| | A: 55 feats | B: 370 multi-window feats |
|---|---|---|
| C-index | **0.7860** | 0.7847 |
| AUC @12h | 0.8120 | 0.8141 |
| episode-PPV | 0.3311 | 0.3403 |
| episode-LIFT | 2.750 | 2.827 |
| **patient recall** | **0.9673** | 0.9548 |
| alarms/day/100 | 127 | 120 |
| **train/test gap** | **0.0151** | **0.0443** |

**Verdict: do not adopt multi-window features for the NEWS2 model.** +0.002 AUC,
recall *down* 1.25pp, 6.7× the features, and the overfit gap triples.

### Why this is the most important slide

> **NEWS2 is a deterministic function of seven vital signs. Anion gap, MAP, lactate and
> infusion titration cannot improve a prediction of NEWS2, because they do not enter
> it — they can only act through their eventual effect on those same seven vitals,
> which the vitals features already capture. Against escalation, where acidosis and
> perfusion are direct causal mechanisms, the identical features are worth +0.073.**

Three things this slide does at once:
1. It explains the **null labs result** from months ago as arithmetic rather than bad
   luck — labs were always going to fail against a NEWS2 target.
2. It is a **2×2 design**, which is the methodology his own architecture criticism
   taught us to build. Say that.
3. It is the **entire justification for changing the target**, established by
   measurement rather than argument.

### On the windows themselves — say this on the escalation side only

Measured on the escalation model, where the features do work:
- **47.3%** of total feature gain comes from window/trend/delta features
- 2h: 8.3% · 6h: 12.0% · **12h: 13.7%** — every window earns its place and the longest
  carries the most
- Vitals are **not** absent: SBP + HR + shock index + SpO₂ + RR + MAP + temp + DBP =
  **32.5%** of gain. They looked absent in a top-20 list only because gain dilutes
  across 19 features per vital while anion gap concentrates into 12. **Ranking
  individual features is invalid when variables have unequal feature counts** — aggregate
  to the family first.

**Why the explicit crossover feature and not just the two window means:** trees split on
axis-aligned thresholds, so the diagonal boundary `mean_2h − mean_12h > 30` needs a
*staircase* of splits, and at `max_depth=4` one path holds only four conditions — a
single diagonal consumes the whole tree. The explicit difference makes it **one split**.
Clinically it separates HR 100 on a 12h mean of 100 (stably sick) from HR 100 on a 12h
mean of 70 (accelerating into crisis).

---

## §C — Numbers to never say

| Never | Instead |
|---|---|
| PPV across two different labels | lift — base rate differs (0.1204 v1 vs 0.1322 v2) |
| A C-index to 4 decimals | 3 decimals — the partition alone moves it ±0.005 |
| "80% sensitivity" | 81.1% — the honest out-of-sample value |
| An episode count without its gap | 1h → 3,467 episodes; 12h → 1,394 |
| "alerts per event" | retired — it is 1/PPV with no reference point |
| A precision gain without its recall cost | always paired |
| A lead-time gain as evidence of earlier detection | it rises from merging alone |

---

## §D — Five questions he will ask, with the answer

**"Why is your PPV only 33%?"**
> Because PPV is bounded by prevalence. PPV = sens·base/(sens·base + FPR·(1−base)). At
> a 12.0% base rate and 80% sensitivity, reaching 0.50 needs specificity 0.94 against
> our 0.66. At 79% sensitivity the published field gets 12%; we get 25–33%.

**"How do you know the episode dedup isn't just making the number look better?"**
> Because patient recall is identical at every gap value — 0.9673 from 1h to 12h. It
> changes counting, not detection. And I chose the conservative end: 12h would have
> reported 0.4455 instead of 0.3311.

**"Did the multi-head MLP work?"**
> No. 0.7779 versus 0.7860 for the independent boosters, and the pooled XGBoost that
> isolates sharing alone moved it −0.0007. The mechanism you described is real and
> observable — it helps the data-poor late intervals — it just cancels against the
> data-rich early one. And an 8-configuration sweep spanned only 0.7% of validation
> loss, so it is not a tuning failure.

**"Is 26% false alarms acceptable?"**
> That is the *unambiguous* false rate — patients who never reach NEWS2 ≥ 7 at any
> point. Comparable deployed systems run at 88% (MEWS++) and 96% (DEWS) at similar
> sensitivity. It is not acceptable for deployment; it is competitive for research.

**"What would actually improve this further?"**
> Not another model — six directions have each moved AUC by under 0.01. Higher-frequency
> monitoring, which would also address the 1,516 patients who deteriorate too fast
> (median 16 minutes) to produce two readings; and the escalation target, which is
> actionable in a CCU where NEWS2 ≥ 7 is not.
