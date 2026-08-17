# What Changed, Why, and What Did Not Work

Session of 2026-07-27, responding to the professor's review. Written so every
decision can be defended out loud without notes.

**Reading rule:** every number here was recomputed this session from the parquet
files, not copied from an earlier document. Where a number superseded an older one,
the old value is shown struck through rather than deleted.

---

## 0. The one-paragraph summary

Three of the professor's five points were implemented and **measured**. Two of them
did not survive measurement, and that is the main result of this session, not a
failure of it. Parameter sharing across intervals — his primary architectural
criticism — changes test C-index by **+0.0005**. The label change he asked for
raises PPV but *lowers* lift and C-index, i.e. the PPV gain is definitional. What
did work is unglamorous: the false-positive rate was being computed in the wrong
unit and against a threshold fitted on the test set, and fixing both changes the
honest numbers materially.

---

## 1. His claims, tested against the data rather than accepted

| Claim | Verdict | Evidence |
|---|---|---|
| "Seven independent classifiers, not like the paper" | **Correct** | `12_ordinal_train.py` trains 7 disjoint XGBoost boosters, zero shared parameters. His paper (arXiv:1903.09795, Fig 1c / Eq 3) is one trunk + K sigmoid units with a summed loss. Conceded without argument. |
| "Patients arriving already sick get labelled 0 because they lack 2h of data" | **False as stated** | 2,014 stays reach NEWS2≥7 within 1h of admission; **1,815 (90%) are already event=1**. Only **19** stays cohort-wide had a record ending before 2h could elapse. |
| "The label mislabels real deteriorators as non-events" | **Correct, different mechanism** | **2,019 stays (18.7%)** reach NEWS2≥7 but never for 2 *consecutive* hours. Median such patient stayed **29 more hours** — not a data shortage, a brittleness to a one-hour dip. |
| "False positives are counted wrong" | **Correct, and worse** | PPV was per patient-hour; **and** the alert threshold was fitted on the test set's own labels. |
| "80–90% false positives is unusable" | **Reframed by measurement** | Of 1,622 false episodes @12h under v1: 27.1% on patients who never reached NEWS2≥7 at all, 50.2% on the mislabelled transient group, 22.7% on patients who sustained ≥7 outside the window. |

**How to present this:** lead with the count that confirms his instinct (2,019), then
give the corrected mechanism. He was right that the label is broken; the reason is
not the one he named, and knowing the real one changes what the fix should be.

---

## 2. Changes that were made

### 2.1 Label v2 — `01_build_labels.py --label-version v2`

Four rules; the event fires at the **earliest** time any is satisfied:

| Rule | Condition | Stays it fires on |
|---|---|---|
| (a) sustained | NEWS2≥7 for 2 consecutive hours — identical to v1 | (v1's 5,424) |
| (b) windowed | ≥2 hours at NEWS2≥7 inside any 4h window | **+515 new** |
| (c) terminal | one NEWS2≥7 hour, then death within 6h | +14 |
| (d) truncated | one NEWS2≥7 hour, record ends <2h later | +35 |

**v2 is a strict superset of v1 by construction** — v1's time is always one of the
candidates, so v2 fires at the same time or earlier and never drops an event. The
verification script asserts `fired_later_under_v2 == 0`; it is 0.

**Why only 515 of the 2,019 transient stays are recovered** — the question to expect:

- **1,008** had exactly ONE high hour. No two-reading rule can ever recover them,
  and a single isolated NEWS2≥7 reading is exactly the artefact pattern the
  2-hour rule exists to filter. Recovering them would trade one kind of label
  noise for another.
- **496** had ≥2 high hours but every gap exceeded 4h. A spike at hour 2 and
  another at hour 40 is not one clinical episode.

A label change that recovered all 2,019 would be worse, not better.

**Unit test:** `01_build_labels.py --selftest-v2` — five hand-computable patients,
one per rule plus a negative control, with the NEWS2 arithmetic written out in the
docstring. Also asserts the superset property.

### 2.2 Evaluation correctness — `eval_core.py` (new)

Three defects fixed, all of which change reported numbers because the old ones
were wrong:

**(i) The alert threshold was fitted on the test set.**
```python
thr = np.quantile(score[y == 1], 1 - sens_target)   # on TEST
```
This makes "80% sensitivity" true by construction on the data it is reported on.
Split into `select_threshold(calib)` + apply-frozen-to-test. The operating point
still *means* "the threshold giving 80% sensitivity"; only where it is estimated
changed.

Effect @12h (stable split): threshold **0.089763 → 0.093262**, and honest
out-of-sample sensitivity is **81.1%**, not the 80% target. The *size* of the miss
(~1 point) is the finding, not its direction — it means the calibration and test
score distributions are close, i.e. the model generalises. The direction is
partition-dependent: an earlier run on a different split gave 77.2%.

**(ii) PPV was counted per patient-hour.** A stable patient with 60 charted hours
was 60 chances to be a false positive. The clinical unit is an **alarm episode**.

**(iii) Episode merging used positional adjacency**, the same bug class found in
the label: `groupby('stay_id')['alert'].shift(1)` merged two alarms hours apart if
no anchor was charted between them. Now timestamp-based.

Combined effect @12h: ~~episode-PPV 0.2846~~ → **0.3311**.

**Unit test:** `py -3 eval_core.py` — 22 hand-computable assertions including that
specificity ≠ 1−PPV (a correction the professor made).

### 2.3 The episode-gap parameter, defined rather than assumed

He asked for this to be defined carefully. `EPISODE_GAP_H = 2.0`: two alerting
hours belong to the same episode if ≤2h apart.

```
 gap_h   episodes   ep-PPV   patient-recall   ep/pat-day
   1.0      3,467   0.3098           0.9673        2.131
   2.0      2,069   0.3311           0.9673        1.272   <- chosen
   4.0      1,754   0.3683           0.9673        1.078
   8.0      1,513   0.4111           0.9673        0.930
  12.0      1,394   0.4455           0.9673        0.857
```

Two things to say about this table:

- **Patient recall is invariant at 0.9673 for every value.** Merging alarms never
  changes whether a patient was caught, so this parameter cannot fake a better
  model — only a more or less honest count.
- **2.0 is the conservative end, chosen deliberately.** 12h would report 0.4455
  instead of 0.3311 — 35% higher precision — for free, purely by redefining what
  counts as one alarm. 2h merges a single-hour dip below threshold, the known
  artefact flagged as unfixed by the previous session, and nothing more.

### 2.4 Stable train/test split — `03_train.py`

**A methodological bug nobody had found.** `GroupShuffleSplit` permutes only the
unique subjects *present in the dataframe*. Label v2 drops 452 subjects, which
reshuffled everyone: the v1 and v2 builds agreed on only **53%** of split
assignments, so the two models were being scored on different patients and every
v1-vs-v2 comparison was confounded.

Replaced with a deterministic bucket: `md5(f"{subject_id}|{seed}")` → uniform
[0,1) → test / calib / train. A subject's split is now a pure function of its own
id and never depends on cohort composition. `_split_selftest()` asserts 100%
agreement after dropping 30% of subjects.

**Honest side effect worth quoting:** the same model on the same data gives
C-index **0.7906** under the old partition and **0.7860** under the new one. That
±0.005 is real precision information — do not quote four decimal places as if the
fourth is meaningful.

`three_way_split_legacy` is kept so pre-2026-07-27 numbers remain reproducible.

### 2.5 Architecture ablation — cells B, C, D

His proposal changes two things at once (independent→shared AND trees→neural net),
so the 2×2 separates them:

| | independent per interval | shared / pooled |
|---|---|---|
| **XGBoost** | **A** `12_ordinal_train.py` | **B** `16_pooled_xgb_train.py` |
| **MLP** | — | **C** `17_mlp_ordinal_train.py` |
| | | **D** `18_mlp_cumulative_train.py` |

- **B** stacks all 1,115,275 person-period rows, adds `interval_j` as an input
  column, trains ONE booster. Sharing, with the base learner held fixed.
- **C** is his actual request: shared trunk `55→128→64`, seven heads, masked BCE
  per his Eq 5 with the **per-row** normaliser K′ (not global K).
- **D** is his paper's literal cumulative target (Eq 2), with monotone-by-
  construction heads so it is not a straw man.

**Fairness controls, all deliberate:**
- B gets 2,000 boosting rounds because A gets 600 *per interval* (up to 4,200
  total); capping B at 600 would hand A a 7× capacity advantage.
- C's mask is **asserted identical** to A's person-period inclusion set
  (`17_mlp_ordinal_train.py --selftest`), so A, B and C train on the same data.
- C gets a 8-point hyperparameter search scored on **calibration** masked-BCE,
  because a first run early-stopped at epoch 9 and an under-trained MLP compared
  against a tuned XGBoost would be a straw man whose negative result was worthless.
- All cells use the same features, split, per-interval isotonic calibration, and
  survival reconstruction.

### 2.6 Deliberate divergences from the paper, and why

| | Paper | Here | Reason |
|---|---|---|---|
| Encoder | LSTM over raw sensor series | MLP over engineered features | The 55 features are already rolling-window aggregates over a 6h look-back; an LSTM would see a sequence of length 1. |
| Target | cumulative `y_j = 1{T ≤ c_j}` (Eq 2) | conditional hazard (cell C) | `S(c_j) = S(c_{j-1})(1−h_j)` is monotone **by construction**. Cell D builds the paper's form anyway so the trade is measured, not asserted. |

---

## 3. Things that were tried and DID NOT work

State these plainly. They are evidence of rigour, and each cost real work.

### 3.1 ARCHITECTURE DOES NOT MATTER HERE — the headline negative result

All four cells, label v1, stable split, identical features and calibration:

| Cell | Architecture | Test C-index | 95% CI | ep-PPV @12h | ep-lift @12h |
|---|---|---|---|---|---|
| **A** | 7 independent XGBoost | **0.7860** | [0.7667, 0.8061] | **0.3311** | **2.750** |
| **B** | 1 pooled XGBoost + `interval_j` | 0.7853 | [0.7662, 0.8051] | 0.3306 | 2.746 |
| **C** (m=1) | shared MLP + 7 hazard heads | 0.7779 | [0.7593, 0.7974] | 0.3051 | 2.534 |
| **C** (m=6) | ensemble of 6 | 0.7806 | [0.7619, 0.8009] | — | — |
| **D** | shared MLP + cumulative heads | 0.7767 | [0.7575, 0.7955] | 0.2955 | 2.454 |

**Total spread: 0.0093.** The 95% CIs are ~0.040 wide and overlap almost
completely. For scale, simply changing the random patient partition moves the same
model by **0.005** — so the architecture effect is barely larger than the effect of
which patients happen to land in the test set.

**Answering his specific criticism (A vs B — sharing, base learner held fixed):**
−0.0007. The mechanism he described is nonetheless **real and observable** in the
per-interval breakdown:

| Interval | Train rows | A | B | Δ |
|---|---|---|---|---|
| ≤2h | 199,184 | **0.8707** | 0.8645 | −0.0062 |
| ≤12h | 149,389 | 0.7387 | **0.7455** | +0.0068 |
| ≤24h | 105,416 | 0.7192 | **0.7206** | +0.0014 |

Textbook multi-task learning: sharing helps the data-poor late intervals and hurts
the data-rich early one, and the effects cancel. It is not large enough to matter
because the smallest interval still has 105,000 training rows — multi-task sharing
pays off when a task is data-starved, and none here are.

Supporting facts that stop this being "the model ignored the feature":
`interval_j` ranks **5th of 56 features by gain**, and the pooled model converged
at 160–259 rounds vs up to 600 per interval for A.

**The MLP is not a straw man.** An 8-point hyperparameter search scored on
calibration masked-BCE spanned only **0.0013 (0.7%)** of loss across the whole
grid — the network is at its ceiling, so its slightly-lower score is a real result,
not a tuning failure. Ensembling m=6 recovered +0.0027 and still did not reach A.

**Cell D's measured trade-off** (the answer to "why did you not follow the paper
literally"): the cumulative form does have the class-balance advantage claimed for
it — positive rate per head **2.3% → 23.7%** across horizons, vs the hazard form's
2.4% → 4.4% — and it still performs the same. But **1.201% of its predictions
required a monotonicity patch** after calibration (a `cummax` to stop
P(T≤12h) > P(T≤24h)); the hazard form required **zero**, because a running product
of terms in [0,1] cannot increase. That is the concrete reason for the divergence.

**This is the fourth independent negative result pointing at the same conclusion:**
labs didn't help, AFT→hazard barely helped, parameter sharing doesn't help,
neural architecture doesn't help. The ceiling is the information content of
NEWS2-derived features against a NEWS2-threshold label — not the model family.

### 3.1b Label v2 — a provisional conclusion that the 2x2 REVERSED

The first comparison looked like a failure: under v2, episode-PPV rose (0.3311 →
0.3451 @12h) while **lift fell** (2.750 → 2.610) and C-index fell (0.7860 →
0.7731). By the pre-declared kill-switch that reads as "the PPV gain was
definitional inflation."

**That conclusion was wrong**, and the ambiguity was foreseeable: a looser label
adds harder events, so the TASK got harder, and lift can fall even if the label is
an improvement. Lower lift on a harder problem does not distinguish "worse label"
from "harder target."

The disambiguating experiment crosses TRAIN-label with EVAL-label on the **same
261,436 anchors** (split agreement 100.0%, only possible after §2.4's fix):

| | evaluated on **v1** | evaluated on **v2** |
|---|---|---|
| **trained on v1** | AUC 0.7956, AUPRC 0.3086, lift 2.843 | AUC 0.7948, AUPRC 0.3783, lift 2.565 |
| **trained on v2** | **AUC 0.7982, AUPRC 0.3208, lift 2.850** | **AUC 0.7968, AUPRC 0.3845, lift 2.610** |

Training on v2 wins **every cell, including on the original v1 label it was never
trained for**: AUC +0.0026, **AUPRC +0.0122 (+4.0% relative)**, lift +0.007.

**Verdict:** v2 is a genuinely better training signal; the headline degradation is
entirely the harder-target effect. **But state the size honestly** — +0.0026 AUC
sits well inside the ±0.02 CI. AUPRC's +4% relative is the more credible signal
because AUPRC is the honest metric under a rare event. The defensible claim is
"the corrected label does not hurt and slightly helps", not "the label fix improved
the model."

### 3.1c Temporal persistence (k-of-m) — works, and is clinically unsafe here

`20_persistence_voting.py`. Best rule at 12h (2-of-6) genuinely delivers:
episode-PPV **0.3311 → 0.3914 (+18% relative)** and alarm burden **1.272 → 0.842
episodes/patient-day (−34%)**.

It is **not adopted**, because patient recall falls **0.9673 → 0.8245**, below the
pre-declared 0.90 floor at every horizon. And the reason is decisive:

| pre-event observations available | patients | recall base | recall 2-of-6 | lost |
|---|---|---|---|---|
| **1–2 anchors** | 134 | 0.9925 | 0.4104 | **−0.5821** |
| 3–4 | 72 | 0.9722 | 0.9583 | −0.0139 |
| 5–8 | 109 | 0.9908 | 0.9633 | −0.0275 |
| 9+ | 327 | 0.9480 | 0.9297 | −0.0183 |

Median max lead time: **1.0h among patients it drops, 11.0h among those it keeps.**

A rule requiring two alerts within six hours **cannot fire on a patient who crashes
after one or two observations — by construction.** It removes 58% of the fastest
deteriorators and almost nobody else. That is the opposite of what an early-warning
system is for, and it lands on the same population as this project's known 54.3%
imminent-deterioration residual.

### 3.1d Interval voting — provably a no-op, agreement 1.0000

Because `P(T≤2h) ≤ … ≤ P(T≤24h)` by construction, with a common threshold
**every** k-of-7 vote across the cumulative horizons is *exactly* equivalent to
thresholding one horizon: OR-vote ≡ the 24h horizon, AND-vote ≡ the 2h horizon.
Asserted numerically on the real predictions
(`prove_interval_voting_is_redundant()`, agreement 1.000, not 0.99). The vote has
nothing to vote on. This is why the idea was reinterpreted as temporal persistence
(§3.1c), which operates on genuinely independent observations.

### 3.1e Ensemble uncertainty — the signal is real; my first gate was wrong

`19_ensemble_uncertainty.py`, m=6 networks differing only in random init and batch
shuffle (his paper §5). **Falsification test passes at all 7 horizons** — among
alerting anchors, precision in the lowest-disagreement decile far exceeds the
highest:

| horizon | low-std decile | high-std decile | spread | Spearman ρ |
|---|---|---|---|---|
| 6h | 0.2201 | 0.1365 | +0.0836 | −0.051 |
| 12h | 0.3435 | 0.2346 | +0.1088 | −0.067 |
| 24h | 0.5371 | 0.3416 | +0.1955 | −0.097 |

**But the first gate made PPV worse** (0.3073 → 0.2834 @12h), contradicting the
decile evidence. The bug was gating individual anchor-HOURS: removing one
high-uncertainty hour from the middle of an alarm run **splits one episode into
two**, raising the episode count and diluting PPV. Gating at the EPISODE level
(mean std across the episode's hours) fixes it:

| horizon | base ep-PPV | PAGE ep-PPV | WATCH ep-PPV |
|---|---|---|---|
| 12h | 0.3073 | **0.3203** | 0.2653 |
| 24h | 0.3879 | **0.4256** | 0.2755 |

**This is the third instance of the same error class in this codebase** — applying
a row-level operation to an object that spans multiple rows (the other two being
the label's and the episode-merger's positional adjacency). Worth naming as a
pattern.

**Honest limitation:** PAGE recall falls 0.9782 → 0.8100 @12h. Unlike persistence,
**nothing is suppressed** — those patients appear on the worklist as WATCH rather
than paging, so total detection is unchanged at 0.9782. Persistence *deletes*
alerts; uncertainty gating *ranks* them. Adopt the two-tier structure; do not
oversell the +0.013 PPV.

### 3.2 `keep_high_anchors` — my own proposal, null result

I argued the "skip anchor hours where the patient is already at NEWS2≥7" rule
(`01_build_labels.py:222`) caused spectrum bias against the sickest presentations.
Keeping those hours adds **3,923 anchor rows (+1.5%)** and recovers **0**
additional deteriorating patients. It does not fix the coverage gap it was aimed
at. The flag remains in the code so the negative result is reproducible.

### 3.3 v1's positional-adjacency artefact — suspected bug, null result

v1 tests "2 consecutive readings" by position in the NaN-dropped frame, so a
charting gap could fake adjacency. Built the check expecting it to matter: it
affects **1 stay of 5,424 (0.02%)**. Documented in the code so nobody
re-discovers it.

### 3.4 Ward-level top-K ranking — abandoned before it reached a slide

Precision@K over "the riskiest patients on the ward right now" is the metric that
matches how a charge nurse triages, and it would have looked good. The test split
has a **median of 1 concurrent patient per wall-clock hour** (1,360 patients
scattered across 2008–2019), so a ward cannot be simulated without a synthetic
construction that would not survive one question about how it was built.

### 3.5 Fixed alarm budget — dropped on clinical grounds, not statistical ones

Setting the threshold so the unit emits N alarms per bed-day *suppresses* alerts:
if the cap is 10 and the 11th patient is crashing, the system hides a real
deterioration to protect a metric. Replaced with **severity ranking** — everything
is shown, ordered by predicted time-to-event, nothing suppressed — and alarm rate
reported as an axis rather than used as a control.

---

## 4. Numbers that must never be quoted alone

**PPV across two different labels.** Base rate @12h is 0.1155 under v1 and 0.1498
under v2, so PPV rises under v2 regardless of model quality. The comparator across
labels is **lift = PPV / base_rate**, which divides prevalence back out — a
no-skill model scores 1.0× under either label.

**Any C-index to four decimal places.** The partition alone moves it by ±0.005.

**"80% sensitivity."** It is a chosen operating point, now fitted on calibration
and yielding 81.1% on test. It is not evidence of anything by itself; the evidence
is what PPV, lift and alarm burden do *at* that point.

**`mean_episodes_per_caught_patient` vs `alerts_per_event`.** Retired entirely —
different denominators (patients vs rows). This was the source of the 4.45→1.8
figure that did not reconcile under questioning.
