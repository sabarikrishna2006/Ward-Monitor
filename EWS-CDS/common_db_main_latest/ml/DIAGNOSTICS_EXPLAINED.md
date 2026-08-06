# Deterioration model — diagnostics, in plain words

Read this before you present. Every number below is defined so you can defend it out loud.
Plots are in `ml/data/charts/diag_*.png`.

---

## The one-paragraph story (say this)
"I built the diagnostic scatter for evaluation. It honestly shows the model's **raw predicted
*time* is not a usable countdown** — it's pulled long by censoring, so I should not put a literal
'deteriorates in T hours' on screen. But the model's **risk ranking is strong and reliable**:
patients it ranks highest deteriorate ~30× more often than the lowest, and it achieves AUC ≈ 0.78
for 'will deteriorate within 12 hours'. So the correct readout is a **risk level within an
actionable horizon**, not a clock. Next step is to sharpen it into a single, focused event."

That is a *mature* result. It shows you found the model's real behaviour instead of dressing it up.

---

## The 5 plots — what each shows and what to say

### 1. `diag_scatter_time.png` — predicted time vs actual time (the unconditional time plot)
- **x-axis:** how many hours until the patient *actually* deteriorated.
- **y-axis:** the hours the *model* predicted (its median).
- **red dashed line:** perfect prediction (predicted = actual).
- **What it shows:** almost every point sits **far above** the red line — the model predicts far
  longer than reality (e.g. predicts ~57 h when the patient deteriorates in ~9 h). The correlation
  is weak (Pearson r = 0.12).
- **Say:** "The raw time output over-predicts and barely tracks the truth — a known effect of heavy
  censoring in survival models. So we do **not** use the raw predicted time as a countdown."

### 2. `diag_reliability.png` — the model works (your strongest plot)
- **x-axis:** the model sorts patients into 10 risk groups (decile 0 = lowest risk … 9 = highest).
- **y-axis:** the % in each group who *actually* deteriorated within 12 h.
- **What it shows:** a clean staircase — **1% in the lowest group, 30% in the highest**. Risk rises
  smoothly and monotonically.
- **Say:** "Even though the absolute time is off, the **ranking is trustworthy**: the model
  concentrates real deteriorations in its high-risk groups — a 30× gradient from bottom to top."

### 3. `diag_horizon_metrics.png` — the numbers to quote (defined below)
A table at three horizons (≤6h / ≤12h / ≤24h). This computes the metrics inside an actionable horizon.
See definitions in the next section.

### 4. `diag_separation.png` — risk score separates the two groups
Two overlaid histograms: patients who deteriorated within 12 h (teal) sit at higher risk
percentiles than those who didn't (grey). Visual version of the AUC.

### 5. `diag_rank_vs_actual.png` — sooner events get higher risk
The median risk-percentile line drifts down as actual time grows (≈88 at 1 h → ≈72 at 21 h):
patients who deteriorate *sooner* are scored *higher*. The signal is modest but in the right direction.

---

## Every metric, defined (so you are never caught again)

Set the alarm threshold so the model **catches 80% of real events** (that's the "operating point").
Then, among patients:
- **TP** = flagged high-risk AND deteriorated. **FP** = flagged AND did not.
- **FN** = not flagged BUT deteriorated. **TN** = not flagged AND did not.

| Metric | Formula | Plain meaning | Our ≤12h value |
|--------|---------|---------------|----------------|
| **Base rate** | events / all | how common the event is in this window | 9% |
| **AUC** | area under ROC | chance the model ranks a true event above a non-event; 0.5 = coin-flip, 1.0 = perfect | **0.78** |
| **Sensitivity** (recall) | TP/(TP+FN) | of real deteriorations, what % we catch | 80% (we set this) |
| **Specificity** | TN/(TN+FP) | of stable patients, what % we correctly leave alone | 62% |
| **PPV** (precision) | TP/(TP+FP) | of the alarms we raise, what % are real | 0.17 |
| **Alerts per event** | (TP+FP)/TP = 1/PPV | how many alarms fire for each real catch | 5.8 |

**The "4.17" that tripped you up** = *alerts per event at the 24-hour horizon* = 1 ÷ PPV(0.24).
It means: to catch 80% of deteriorations within 24 h, the system raises ~4.2 alarms per genuine one
(≈76% of alarms are false). NEWS2 in the same setting is 5.7, so we're better — but this is the
core "alarm fatigue" challenge, and it's **worse at shorter horizons** (9.2 at 6 h) because the
event is rarer there.

> Why accuracy is NOT in this table: with a 9% base rate, a model that predicts "nobody
> deteriorates" is 91% accurate and useless. That's why we use AUC / sensitivity / PPV instead.

---

## Anticipated questions → your answers
- **"Why is the predicted time so wrong?"** Heavy right-censoring: most patients never deteriorate,
  which tells the survival model event times are long, inflating the median. Expected; that's why we
  use rank + horizon, not the raw time.
- **"So does the model work?"** Yes as a *risk ranker* — 30× gradient (reliability plot), AUC 0.78.
  Not as a literal countdown.
- **"What's the actionable horizon?"** 12–24 h is where PPV is usable; 6 h is most clinically useful
  but hardest (event rate 5%, alerts/event ~9). We report all three honestly.
- **"What's next?"** (1) split into a single focused event (time to
  NEWS2 ≥ 7) instead of a mixed event, (2) per-patient SHAP in the UI, (3) show risk + horizon flag,
  not a countdown.

---

## Honest limitations (state them first)
- One model, retrospective ICU (MIMIC) data; not validated prospectively.
- Absolute predicted time is **not** used — only the risk rank within a horizon.
- The event currently mixes NEWS2≥7 and treatment-escalation; the next model separates them.